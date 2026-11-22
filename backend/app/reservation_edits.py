"""Reasoned guest corrections and availability-checked, pre-check-in date edits."""
from datetime import date,datetime
from zoneinfo import ZoneInfo
from uuid import UUID
import hashlib
import json
from fastapi import HTTPException,Request,Query
from pydantic import BaseModel,Field,field_validator,model_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

class EditDraft(BaseModel):
    model_config={'extra':'forbid'}
    expectedVersion:str=Field(pattern=r'^[a-f0-9]{64}$')
    guest:str=Field(min_length=1,max_length=120)
    phone:str=Field(min_length=1,max_length=40)
    guestCount:int|None=Field(default=None,ge=1,le=100,strict=True)
    checkIn:date
    checkOut:date
    reason:str=Field(min_length=1,max_length=500)
    @field_validator('guest','phone')
    @classmethod
    def clean(cls,value):
        value=value.strip()
        if not value or any(ord(c)<32 for c in value):raise ValueError('Enter a value without control characters')
        return value
    @field_validator('reason')
    @classmethod
    def clean_reason(cls,value):
        value=value.strip()
        if not value:raise ValueError('Enter a reason for this correction')
        return value
    @model_validator(mode='after')
    def dates(self):
        if self.checkOut<self.checkIn:raise ValueError('Departure must be on or after arrival')
        return self

class SaveEdit(EditDraft):
    requestId:UUID

SNAPSHOT_FIELDS=['id','guest','phone','guestCount','roomId','roomNumber','roomAllocationFrom','checkIn','checkOut','nightlyRate',
    'roomTotal','barCharges','total','paid','balance','credit','status','checkedInAt','checkedOutAt']

def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def register_reservation_edits(app,engine,booking_response,lock_stay):
    def snapshot(c,row):
        data=booking_response(row,c)
        return {key:data[key] for key in SNAPSHOT_FIELDS}
    def version(before,room):return digest({'booking':before,'maintenance':room['maintenance_status'],'taken':room['taken']})
    def read(c,rid):
        row=c.execute(text('''SELECT r.*,rooms.room_number,rooms.maintenance_status AS room_maintenance_status
            FROM reservations r JOIN rooms ON rooms.id=r.room_id WHERE r.id=:id'''),{'id':rid}).mappings().first()
        if not row:raise HTTPException(404,'Reservation not found')
        room=c.execute(text('SELECT * FROM rooms WHERE id=:id'),{'id':row['room_id']}).mappings().one()
        return room,row
    def calculate(c,room,row,body):
        before=snapshot(c,row)
        if body.expectedVersion!=version(before,room):raise HTTPException(409,'This booking or its payments changed. Refresh details before editing again.')
        desired={'guest':body.guest,'phone':body.phone,'guestCount':body.guestCount,'checkIn':body.checkIn.isoformat(),'checkOut':body.checkOut.isoformat()}
        changed=[key for key,value in desired.items() if before[key]!=value]
        if not changed:raise HTTPException(409,'No changes to save')
        if before['guestCount'] is not None and body.guestCount is None:raise HTTPException(422,'Enter the number of guests; a recorded count cannot be cleared')
        date_changed=any(key in changed for key in ['checkIn','checkOut'])
        if date_changed:
            if row['status']!='confirmed':raise HTTPException(409,'Dates can only be edited before check-in. Use Extend stay for an active stay.')
            if room['maintenance_status']!='available':raise HTTPException(409,'This room is out of service. Resolve maintenance before changing booking dates.')
            today=datetime.now(ZoneInfo('Africa/Dar_es_Salaam')).date()
            if room['taken'] and body.checkIn<=today:raise HTTPException(409,'This room is currently occupied. Choose a future arrival or resolve occupancy first.')
            conflict=c.execute(text('''SELECT id FROM reservations WHERE room_id=:room AND id<>:id AND status IN ('confirmed','checked_in')
                AND daterange(room_allocated_from,GREATEST(departure_date,room_allocated_from+1),'[)') &&
                    daterange(CAST(:arrival AS date),GREATEST(CAST(:departure AS date),CAST(:arrival AS date)+1),'[)') LIMIT 1'''),
                {'room':row['room_id'],'id':row['id'],'arrival':body.checkIn,'departure':body.checkOut}).first()
            if conflict:raise HTTPException(409,'This room has another booking during the requested dates. Choose different dates.')
        after=dict(before,**desired)
        after['roomTotal']=int(row['nightly_rate'])*max(1,(body.checkOut-body.checkIn).days)+int(row['billing_adjustment'])
        after['total']=after['roomTotal']+after['barCharges']
        if after['total']<0:raise HTTPException(409,'The proposed dates conflict with earlier bill adjustments. Review the booking bill first.')
        after['balance']=max(0,after['total']-after['paid']);after['credit']=max(0,after['paid']-after['total'])
        if date_changed:after['roomAllocationFrom']=body.checkIn.isoformat()
        return {'before':before,'after':after,'changedFields':changed,'datesChanged':date_changed,'expectedVersion':body.expectedVersion}
    def edit_response(r):
        return {'id':str(r['id']),'changedAt':r['changed_at'].isoformat(),'changedBy':r['username'],'reason':r['reason'],
            'before':r['before_snapshot'],'after':r['after_snapshot'],'changedFields':r['changed_fields']}
    @app.get('/api/reservations/{reservation_id}/edits')
    def edit_history(reservation_id:UUID,page:int=Query(1,ge=1)):
        with engine.connect().execution_options(isolation_level='REPEATABLE READ') as c:
            with c.begin():
                room,row=read(c,reservation_id);current=booking_response(row,c);before={key:current[key] for key in SNAPSHOT_FIELDS}
                count=c.execute(text('SELECT count(*) FROM reservation_edits WHERE reservation_id=:id'),{'id':reservation_id}).scalar_one()
                history=c.execute(text('''SELECT e.*,u.username FROM reservation_edits e JOIN users u ON u.id=e.changed_by
                    WHERE e.reservation_id=:id ORDER BY e.changed_at DESC,e.id LIMIT 30 OFFSET :offset'''),{'id':reservation_id,'offset':(page-1)*30}).mappings().all()
                return {'reservation':current,'version':version(before,room),'edits':[edit_response(r) for r in history],'count':count,'page':page,'pageCount':max(1,(count+29)//30)}
    @app.post('/api/reservations/{reservation_id}/edit-preview')
    def preview_edit(reservation_id:UUID,body:EditDraft):
        with engine.connect().execution_options(isolation_level='REPEATABLE READ') as c:
            with c.begin():
                room,row=read(c,reservation_id)
                return calculate(c,room,row,body)
    @app.post('/api/reservations/{reservation_id}/edit')
    def save_edit(reservation_id:UUID,body:SaveEdit,request:Request):
        fingerprint=digest(body.model_dump(mode='json',exclude={'requestId'}))
        try:
            with engine.begin() as c:
                c.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key,0))'),{'key':'reservation-edit:'+str(body.requestId)})
                prior=c.execute(text('SELECT e.*,u.username FROM reservation_edits e JOIN users u ON u.id=e.changed_by WHERE e.id=:id'),{'id':body.requestId}).mappings().first()
                if prior:
                    if (prior['reservation_id'],prior['request_hash'],str(prior['changed_by']))!=(reservation_id,fingerprint,str(request.state.user['id'])):raise HTTPException(409,'Request ID already used for another booking edit')
                    room,current=read(c,reservation_id)
                    return {'edit':edit_response(prior),'reservation':booking_response(current,c)}
                room,row=lock_stay(c,reservation_id)
                # Add the public room number used by booking_response without changing the locked record.
                row=dict(row,room_number=room['room_number'],room_maintenance_status=room['maintenance_status'])
                quote=calculate(c,room,row,body)
                updated=c.execute(text('''UPDATE reservations SET guest_name=:guest,phone=:phone,guest_count=:count,
                    arrival_date=:arrival,departure_date=:departure,room_allocated_from=:allocated WHERE id=:id RETURNING *'''),
                    {'id':reservation_id,'guest':body.guest,'phone':body.phone,'count':body.guestCount,'arrival':body.checkIn,'departure':body.checkOut,
                    'allocated':body.checkIn if quote['datesChanged'] else row['room_allocated_from']}).mappings().one()
                saved=c.execute(text('''INSERT INTO reservation_edits(id,reservation_id,request_hash,changed_by,reason,before_snapshot,after_snapshot,changed_fields)
                    VALUES(:id,:reservation,:hash,:staff,:reason,CAST(:before AS jsonb),CAST(:after AS jsonb),CAST(:fields AS jsonb)) RETURNING *'''),
                    {'id':body.requestId,'reservation':reservation_id,'hash':fingerprint,'staff':request.state.user['id'],'reason':body.reason,
                    'before':json.dumps(quote['before']),'after':json.dumps(quote['after']),'fields':json.dumps(quote['changedFields'])}).mappings().one()
                return {'edit':edit_response(dict(saved,username=request.state.user['username'])),
                    'reservation':booking_response(dict(updated,room_number=room['room_number'],room_maintenance_status=room['maintenance_status']),c)}
        except IntegrityError as error:
            if getattr(error.orig,'sqlstate',None)=='23P01':raise HTTPException(409,'Another booking now overlaps these dates. Refresh and choose different dates.') from error
            if getattr(error.orig,'sqlstate',None)=='23505':raise HTTPException(409,'This booking edit request was already used') from error
            raise
