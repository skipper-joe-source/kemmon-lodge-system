"""Cashier shift API, with serialized collection posting and immutable closing totals."""
import logging
from datetime import date,datetime,timedelta,time
from zoneinfo import ZoneInfo
from uuid import UUID
from decimal import Decimal
from typing import Literal
from fastapi import HTTPException,Request,Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel,Field,field_validator
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError,IntegrityError

class OpenShift(BaseModel):
    requestId:UUID
    drawer:str=Field(min_length=1,max_length=80)
    openingCash:Decimal=Field(ge=0,max_digits=12,decimal_places=0,allow_inf_nan=False)
    @field_validator('drawer')
    @classmethod
    def clean(cls,value):
        value=value.strip()
        if not value:raise ValueError('Enter the cash drawer name')
        return value

class CloseShift(BaseModel):
    requestId:UUID
    countedCash:Decimal=Field(ge=0,max_digits=12,decimal_places=0,allow_inf_nan=False)
    expectedEntryCount:int=Field(ge=0,strict=True)
    notes:str=Field(default='',max_length=1000)
    @field_validator('notes')
    @classmethod
    def clean(cls,value):return value.strip()

def can_review(user):return user['role']=='owner' or 'shifts.review' in (user.get('role_permissions') or [])

def shift_totals(c,s):
    if s['closed_at']:
        return {key:int(s[key]) for key in ['cash_collected','mobile_collected','cash_expenses','mobile_expenses','entry_count']}
    r=c.execute(text('''SELECT
        COALESCE(sum(amount) FILTER(WHERE kind='collection' AND method='cash'),0) AS cash_collected,
        COALESCE(sum(amount) FILTER(WHERE kind='collection' AND method='mobile_money'),0) AS mobile_collected,
        COALESCE(sum(amount) FILTER(WHERE kind='expense' AND method='cash'),0) AS cash_expenses,
        COALESCE(sum(amount) FILTER(WHERE kind='expense' AND method='mobile_money'),0) AS mobile_expenses,
        count(*) AS entry_count FROM cashier_shift_entries WHERE shift_id=:id'''),{'id':s['id']}).mappings().one()
    return {k:int(v) for k,v in r.items()}

def shift_response(c,s):
    totals=shift_totals(c,s)
    expected=int(s['opening_cash'])+totals['cash_collected']-totals['cash_expenses']
    closed_by=c.execute(text('SELECT username FROM users WHERE id=:id'),{'id':s['closed_by']}).scalar_one_or_none() if s['closed_by'] else None
    return {'id':str(s['id']),'staffId':str(s['staff_id']),'staff':s['staff_username'],'drawer':s['drawer'],
        'openingCash':int(s['opening_cash']),'openedAt':s['opened_at'].isoformat(),'closedAt':s['closed_at'].isoformat() if s['closed_at'] else None,
        'closedBy':closed_by,'closeNotes':s['close_notes'],'countedCash':int(s['counted_cash']) if s['counted_cash'] is not None else None,
        'cashCollected':totals['cash_collected'],'mobileCollected':totals['mobile_collected'],'cashExpenses':totals['cash_expenses'],
        'mobileExpenses':totals['mobile_expenses'],'entryCount':totals['entry_count'],'expectedCash':expected,
        'variance':int(s['counted_cash'])-expected if s['closed_at'] else None,
        'mobileMovement':totals['mobile_collected']-totals['mobile_expenses']}

def register_shifts(app,engine):
    @app.exception_handler(DBAPIError)
    async def shift_database_error(request,error):
        if getattr(error.orig,'sqlstate',None)=='P7501':
            return JSONResponse(status_code=409,content={'detail':"Open a cashier shift from Cashier shifts before recording money or today's paid expenses."})
        logging.getLogger('uvicorn.error').error('Database action failed (SQLSTATE %s)',getattr(error.orig,'sqlstate','unknown'))
        return JSONResponse(status_code=500,content={'detail':'The database could not complete this action. Check the backend terminal.'})
    def lock_staff(c,staff):
        c.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key,0))'),{'key':'cashier-shift:'+str(staff)})
    def row(c,sid):
        result=c.execute(text('SELECT * FROM cashier_shifts WHERE id=:id'),{'id':sid}).mappings().first()
        if not result:raise HTTPException(404,'Cashier shift not found')
        return result
    def allowed(s,user):
        if str(s['staff_id'])!=str(user['id']) and not can_review(user):raise HTTPException(403,'You can only view your own shifts')
    @app.get('/api/shifts/current')
    def current(request:Request):
        with engine.connect().execution_options(isolation_level='REPEATABLE READ') as c:
            with c.begin():
                s=c.execute(text('SELECT * FROM cashier_shifts WHERE staff_id=:id AND closed_at IS NULL'),{'id':request.state.user['id']}).mappings().first()
                return shift_response(c,s) if s else None
    @app.post('/api/shifts')
    def open_shift(body:OpenShift,request:Request):
        user=request.state.user
        try:
            with engine.begin() as c:
                lock_staff(c,user['id'])
                existing=c.execute(text('SELECT * FROM cashier_shifts WHERE id=:id'),{'id':body.requestId}).mappings().first()
                if existing:
                    if (str(existing['staff_id']),existing['drawer'],existing['opening_cash'])!=(str(user['id']),body.drawer,body.openingCash):raise HTTPException(409,'Request ID already used for another shift')
                    return shift_response(c,existing)
                if c.execute(text('SELECT id FROM cashier_shifts WHERE staff_id=:id AND closed_at IS NULL'),{'id':user['id']}).first():raise HTTPException(409,'Close your current shift before opening another')
                s=c.execute(text('''INSERT INTO cashier_shifts(id,staff_id,staff_username,drawer,opening_cash)
                    VALUES(:id,:staff,:name,:drawer,:cash) RETURNING *'''),{'id':body.requestId,'staff':user['id'],'name':user['username'],'drawer':body.drawer,'cash':body.openingCash}).mappings().one()
                return shift_response(c,s)
        except IntegrityError as e:
            if getattr(e.orig,'sqlstate',None)=='23505':raise HTTPException(409,'This drawer already has an open shift, or the request ID was used. Close the previous drawer shift before handover.') from e
            raise
    @app.get('/api/shifts')
    def list_shifts(request:Request,start_date:date,end_date:date,state:Literal['all','open','closed']='all',scope:Literal['mine','all']='mine',page:int=Query(1,ge=1)):
        if start_date>end_date or end_date==date.max:raise HTTPException(422,'Choose a valid date range')
        if scope=='all' and not can_review(request.state.user):raise HTTPException(403,'Your role cannot review other staff shifts')
        zone=ZoneInfo('Africa/Dar_es_Salaam')
        params={'start':datetime.combine(start_date,time.min,tzinfo=zone),'stop':datetime.combine(end_date+timedelta(days=1),time.min,tzinfo=zone),'staff':request.state.user['id'],'all':scope=='all','state':state,'offset':(page-1)*50}
        with engine.connect().execution_options(isolation_level='REPEATABLE READ') as c:
            with c.begin():
                rows=c.execute(text('''SELECT * FROM cashier_shifts WHERE opened_at>=:start AND opened_at<:stop AND (:all OR staff_id=:staff)
                    AND (:state='all' OR (:state='open' AND closed_at IS NULL) OR (:state='closed' AND closed_at IS NOT NULL))
                    ORDER BY opened_at DESC,id LIMIT 51 OFFSET :offset'''),params).mappings().all()
                return {'shifts':[shift_response(c,s) for s in rows[:50]],'page':page,'hasMore':len(rows)>50,'timezone':'Africa/Dar_es_Salaam'}
    @app.get('/api/shifts/{shift_id}')
    def detail(shift_id:UUID,request:Request,page:int=Query(1,ge=1)):
        with engine.connect().execution_options(isolation_level='REPEATABLE READ') as c:
            with c.begin():
                s=row(c,shift_id);allowed(s,request.state.user)
                entries=c.execute(text('SELECT * FROM cashier_shift_entries WHERE shift_id=:id ORDER BY recorded_at,source,record_id LIMIT 51 OFFSET :offset'),{'id':shift_id,'offset':(page-1)*50}).mappings().all()
                return {'shift':shift_response(c,s),'entries':[{'source':r['source'],'id':str(r['record_id']),'kind':r['kind'],'method':r['method'],'amount':int(r['amount']),'recordedAt':r['recorded_at'].isoformat()} for r in entries[:50]],'page':page,'hasMore':len(entries)>50}
    @app.post('/api/shifts/{shift_id}/close')
    def close_shift(shift_id:UUID,body:CloseShift,request:Request):
        user=request.state.user
        try:
            with engine.begin() as c:
                s=row(c,shift_id)
                if str(s['staff_id'])!=str(user['id']) and user['role']!='owner':raise HTTPException(403,'Only the shift cashier or owner can close this shift')
                lock_staff(c,s['staff_id'])
                s=c.execute(text('SELECT * FROM cashier_shifts WHERE id=:id FOR UPDATE'),{'id':shift_id}).mappings().one()
                if s['closed_at']:
                    if (s['close_request_id'],s['counted_cash'],s['close_notes'],str(s['closed_by']),s['entry_count'])!=(body.requestId,body.countedCash,body.notes,str(user['id']),body.expectedEntryCount):raise HTTPException(409,'This shift is already closed')
                    return shift_response(c,s)
                totals=shift_totals(c,s)
                if totals['entry_count']!=body.expectedEntryCount:raise HTTPException(409,'New transactions arrived. Refresh the shift and review closing totals again.')
                expected=int(s['opening_cash'])+totals['cash_collected']-totals['cash_expenses']
                if (body.countedCash!=expected or str(s['staff_id'])!=str(user['id'])) and not body.notes:raise HTTPException(422,'Enter a reason for the shortage/surplus or for closing another staff member’s shift')
                s=c.execute(text('''UPDATE cashier_shifts SET closed_at=clock_timestamp(),close_request_id=:request,closed_by=:staff,
                    close_notes=:notes,counted_cash=:counted,cash_collected=:cash_collected,mobile_collected=:mobile_collected,
                    cash_expenses=:cash_expenses,mobile_expenses=:mobile_expenses,entry_count=:entry_count WHERE id=:id RETURNING *'''),
                    {'id':shift_id,'request':body.requestId,'staff':user['id'],'notes':body.notes,'counted':body.countedCash,**totals}).mappings().one()
                return shift_response(c,s)
        except IntegrityError as e:
            if getattr(e.orig,'sqlstate',None)=='23505':raise HTTPException(409,'Closing request already used for another shift') from e
            raise
