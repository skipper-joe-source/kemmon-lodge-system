"""Read-only audit browser and request actor context for transactional audit triggers."""
from contextvars import ContextVar
from datetime import date,datetime,timedelta,time
from uuid import UUID
from zoneinfo import ZoneInfo
from fastapi import HTTPException,Query
from sqlalchemy import event,text

_request=ContextVar('kemmon_audit_request',default=None)
ACTION_LABELS={
    'reservation.edited':'Guest / booking details corrected','reservation.guest_count_changed':'Guest count recorded / changed',
    'alert.reviewed':'Owner alert reviewed','alerts.threshold_changed':'Large-payment alert threshold changed',
    'reservation.created':'Reservation created','reservation.walk_in_created':'Walk-in created',
    'reservation.checked_in':'Guest checked in','reservation.checked_out':'Guest checked out','reservation.cancelled':'Reservation cancelled',
    'reservation.status_changed':'Reservation status changed','reservation.updated':'Reservation updated',
    'reservation.extended':'Stay extended','reservation.room_transferred':'Guest transferred to another room',
    'room.marked_ready':'Room marked ready','room.status_changed':'Room status changed',
    'payment.recorded':'Guest payment recorded','expense.recorded':'Paid expense recorded',
    'stock.purchase':'Stock purchased','stock.wastage':'Stock damage / wastage recorded','stock.count':'Physical stock count recorded','stock.sale':'Stock deducted for bar sale',
    'product.created':'Product created','product.updated':'Product updated','product.price_changed':'Selling price changed','product.barcode_changed':'Barcode changed',
    'bar.sale_paid':'Paid bar sale recorded','bar.charged_to_room':'Bar sale charged to guest room',
    'maintenance.reported':'Maintenance reported','maintenance.resolved':'Repairs completed',
    'cash.opening_changed':'Daily opening cash set / corrected','shift.opened':'Cashier shift opened','shift.closed':'Cashier shift closed',
    'staff.created':'Staff account created','staff.access_changed':'Staff access changed','role.created':'Custom role created','role.updated':'Custom role changed',
}

def register_audit(app,engine):
    @app.middleware('http')
    async def audit_request_context(request,call_next):
        token=_request.set(request)
        try:return await call_next(request)
        finally:_request.reset(token)
    @event.listens_for(engine,'begin')
    def bind_actor(connection):
        req=_request.get()
        user=getattr(req.state,'user',None) if req is not None else None
        connection.execute(text("SELECT set_config('kemmon.actor_id',:actor,true),set_config('kemmon.request_path',:path,true)"),{'actor':str(user['id']) if user else '', 'path':req.url.path if req is not None else ''})
    @app.get('/api/audit/options')
    def options():
        with engine.connect().execution_options(isolation_level='REPEATABLE READ') as c:
            with c.begin():
                actions=c.execute(text('SELECT DISTINCT action FROM audit_events ORDER BY action')).scalars().all()
                staff=c.execute(text('''SELECT DISTINCT ON (actor_id) actor_id,actor_name FROM audit_events
                    WHERE actor_id IS NOT NULL ORDER BY actor_id,event_at DESC,id DESC''')).mappings().all()
                started=c.execute(text('SELECT started_at FROM audit_tracking WHERE id=1')).scalar_one()
                unknown=c.execute(text('SELECT EXISTS(SELECT 1 FROM audit_events WHERE actor_id IS NULL)')).scalar_one()
                return {'actions':[{'key':a,'label':ACTION_LABELS.get(a,a)} for a in actions],
                    'staff':sorted([{'id':str(r['actor_id']),'name':r['actor_name']} for r in staff],key=lambda r:r['name'].lower()),
                    'hasUnknownStaff':unknown,'trackingStartedAt':started.isoformat(),'timezone':'Africa/Dar_es_Salaam'}
    @app.get('/api/audit')
    def audit_logs(start_date:date,end_date:date,staff_id:str|None=Query(None,max_length=40),action:str|None=Query(None,max_length=80),page:int=Query(1,ge=1),page_size:int=Query(50,ge=1,le=100)):
        if start_date>end_date or end_date==date.max:raise HTTPException(422,'Choose a valid date range')
        actor=None
        if staff_id not in (None,'unknown'):
            try:actor=UUID(staff_id)
            except ValueError as e:raise HTTPException(422,'Choose a valid staff filter') from e
        zone=ZoneInfo('Africa/Dar_es_Salaam')
        params={'start':datetime.combine(start_date,time.min,tzinfo=zone),'stop':datetime.combine(end_date+timedelta(days=1),time.min,tzinfo=zone),
            'all_staff':staff_id is None,'unknown':staff_id=='unknown','actor':actor,'all_actions':action is None,'action':action,
            'limit':page_size,'offset':(page-1)*page_size}
        where="event_at>=:start AND event_at<:stop AND (:all_staff OR (:unknown AND actor_id IS NULL) OR actor_id=:actor) AND (:all_actions OR action=:action)"
        with engine.connect().execution_options(isolation_level='REPEATABLE READ') as c:
            with c.begin():
                total=c.execute(text('SELECT count(*) FROM audit_events WHERE '+where),params).scalar_one()
                rows=c.execute(text('SELECT * FROM audit_events WHERE '+where+' ORDER BY event_at DESC,id DESC LIMIT :limit OFFSET :offset'),params).mappings().all()
                return {'startDate':str(start_date),'endDate':str(end_date),'timezone':'Africa/Dar_es_Salaam','count':total,'page':page,'pageCount':max(1,(total+page_size-1)//page_size),
                    'events':[{'id':str(r['id']),'at':r['event_at'].isoformat(),'staffId':str(r['actor_id']) if r['actor_id'] else None,'staff':r['actor_name'],
                        'action':r['action'],'label':ACTION_LABELS.get(r['action'],r['action']),'entityType':r['entity_type'],'entityId':r['entity_id'],
                        'source':r['source_table'],'sourceId':r['source_key'],'origin':r['origin'],'details':r['details']} for r in rows]}
