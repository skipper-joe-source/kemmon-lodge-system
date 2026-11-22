"""Operational alerts evaluated from committed lodge records; reviews never change the source."""
from uuid import UUID
from decimal import Decimal
from typing import Literal
from fastapi import HTTPException,Request,Query
from pydantic import BaseModel,Field,field_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

AlertKind=Literal['all','low_stock','maintenance','checkout_balance','shift_variance','large_payment']
class AlertReview(BaseModel):
    requestId:UUID
    alertKey:str=Field(min_length=1,max_length=160,pattern=r'^[a-z0-9:_-]+$')
    version:str=Field(pattern=r'^[a-f0-9]{32}$')
    notes:str=Field(default='',max_length=1000)
    @field_validator('notes')
    @classmethod
    def clean(cls,value):return value.strip()

class AlertSettings(BaseModel):
    requestId:UUID
    expectedVersion:int=Field(ge=1,strict=True)
    largePaymentThreshold:Decimal|None=Field(ge=1,max_digits=12,decimal_places=0,allow_inf_nan=False)

def setting_response(r):
    return {'largePaymentThreshold':int(r['large_payment_threshold']) if r['large_payment_threshold'] is not None else None,
        'version':r['version'],'changedAt':r['changed_at'].isoformat()}

def reviewed_response(r):
    return {'id':str(r['id']),'alertKey':r['alert_key'],'version':r['version'],'kind':r['kind'],'title':r['title'],
        'details':r['details'],'reviewedBy':r['username'],'reviewedAt':r['reviewed_at'].isoformat(),'notes':r['notes']}

def register_alerts(app,engine):
    join='FROM owner_alert_candidates a LEFT JOIN owner_alert_reviews r ON r.alert_key=a.alert_key AND r.version=a.version'
    def summary(c):
        row=c.execute(text('SELECT count(*) AS total,count(*) FILTER(WHERE r.id IS NULL) AS unreviewed,count(*) FILTER(WHERE r.id IS NOT NULL) AS reviewed '+join)).mappings().one()
        return dict(row)
    @app.get('/api/alerts/summary')
    def alert_summary():
        with engine.connect() as c:return summary(c)
    @app.get('/api/alerts/settings')
    def get_settings():
        with engine.connect() as c:return setting_response(c.execute(text('SELECT * FROM owner_alert_settings WHERE id=1')).mappings().one())
    @app.post('/api/alerts/settings')
    def set_settings(body:AlertSettings,request:Request):
        if request.state.user['role']!='owner':raise HTTPException(403,'Only the owner can change alert thresholds')
        with engine.begin() as c:
            current=c.execute(text('SELECT * FROM owner_alert_settings WHERE id=1 FOR UPDATE')).mappings().one()
            prior=c.execute(text('SELECT * FROM owner_alert_setting_changes WHERE id=:id'),{'id':body.requestId}).mappings().first()
            if prior:
                if (prior['previous_version'],prior['threshold'],str(prior['changed_by']))!=(body.expectedVersion,body.largePaymentThreshold,str(request.state.user['id'])):raise HTTPException(409,'Request ID already used for different settings')
                return setting_response(current)
            if current['version']!=body.expectedVersion:raise HTTPException(409,'Alert settings changed. Refresh and review again.')
            row=c.execute(text('UPDATE owner_alert_settings SET large_payment_threshold=:threshold,version=version+1,changed_at=clock_timestamp(),changed_by=:staff WHERE id=1 RETURNING *'),{'threshold':body.largePaymentThreshold,'staff':request.state.user['id']}).mappings().one()
            c.execute(text('''INSERT INTO owner_alert_setting_changes(id,previous_threshold,threshold,previous_version,new_version,changed_by)
                VALUES(:id,:old,:threshold,:old_version,:new_version,:staff)'''),{'id':body.requestId,'old':current['large_payment_threshold'],'threshold':body.largePaymentThreshold,'old_version':current['version'],'new_version':row['version'],'staff':request.state.user['id']})
            return setting_response(row)
    @app.get('/api/alerts')
    def list_alerts(state:Literal['unreviewed','reviewed','all']='unreviewed',kind:AlertKind='all',page:int=Query(1,ge=1),page_size:int=Query(30,ge=1,le=100)):
        params={'state':state,'kind':kind,'limit':page_size,'offset':(page-1)*page_size}
        where=" WHERE (:kind='all' OR a.kind=:kind) AND (:state='all' OR (:state='unreviewed' AND r.id IS NULL) OR (:state='reviewed' AND r.id IS NOT NULL))"
        with engine.connect().execution_options(isolation_level='REPEATABLE READ') as c:
            with c.begin():
                total=c.execute(text('SELECT count(*) '+join+where),params).scalar_one()
                rows=c.execute(text('SELECT a.*,r.id AS review_id,r.reviewed_at,r.notes,u.username '+join+' LEFT JOIN users u ON u.id=r.reviewed_by'+where+' ORDER BY a.occurred_at DESC,a.alert_key LIMIT :limit OFFSET :offset'),params).mappings().all()
                return {'summary':summary(c),'count':total,'page':page,'pageCount':max(1,(total+page_size-1)//page_size),
                    'alerts':[{'key':r['alert_key'],'version':r['version'],'kind':r['kind'],'title':r['title'],'entityId':r['entity_id'],'at':r['occurred_at'].isoformat(),'details':r['details'],
                        'reviewed':r['review_id'] is not None,'reviewedBy':r['username'],'reviewedAt':r['reviewed_at'].isoformat() if r['reviewed_at'] else None,'reviewNotes':r['notes']} for r in rows]}
    @app.post('/api/alerts/review')
    def review_alert(body:AlertReview,request:Request):
        try:
            with engine.connect() as c:
                with c.begin():
                    # Serialize identical versions/UUID retries without locking rooms, stock or guest records.
                    for key in sorted(['alert-review:'+body.alertKey+':'+body.version,'alert-review-request:'+str(body.requestId)]):
                        c.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key,0))'),{'key':key})
                    prior=c.execute(text('SELECT r.*,u.username FROM owner_alert_reviews r JOIN users u ON u.id=r.reviewed_by WHERE r.id=:id'),{'id':body.requestId}).mappings().first()
                    if prior:
                        if (prior['alert_key'],prior['version'],prior['notes'],str(prior['reviewed_by']))!=(body.alertKey,body.version,body.notes,str(request.state.user['id'])):raise HTTPException(409,'Request ID already used for another alert review')
                        return reviewed_response(prior)
                    prior=c.execute(text('SELECT r.*,u.username FROM owner_alert_reviews r JOIN users u ON u.id=r.reviewed_by WHERE r.alert_key=:key AND r.version=:version'),{'key':body.alertKey,'version':body.version}).mappings().first()
                    if prior:return reviewed_response(prior)
                    alert=c.execute(text('SELECT * FROM owner_alert_candidates WHERE alert_key=:key'),{'key':body.alertKey}).mappings().first()
                    if not alert:raise HTTPException(409,'This alert is no longer active. Refresh alerts.')
                    if alert['version']!=body.version:raise HTTPException(409,'Alert details changed. Refresh and review the latest information.')
                    import json
                    row=c.execute(text('''INSERT INTO owner_alert_reviews(id,alert_key,version,kind,title,details,reviewed_by,notes)
                        VALUES(:id,:key,:version,:kind,:title,CAST(:details AS jsonb),:staff,:notes) RETURNING *'''),
                        {'id':body.requestId,'key':body.alertKey,'version':body.version,'kind':alert['kind'],'title':alert['title'],'details':json.dumps(alert['details']),
                        'staff':request.state.user['id'],'notes':body.notes}).mappings().one()
                    return reviewed_response(dict(row,username=request.state.user['username']))
        except IntegrityError as error:
            if getattr(error.orig,'sqlstate',None)=='23505':raise HTTPException(409,'This alert was already reviewed. Refresh alerts.') from error
            raise
    @app.get('/api/alerts/reviews')
    def review_history(page:int=Query(1,ge=1),page_size:int=Query(30,ge=1,le=100)):
        with engine.connect().execution_options(isolation_level='REPEATABLE READ') as c:
            with c.begin():
                count=c.execute(text('SELECT count(*) FROM owner_alert_reviews')).scalar_one()
                rows=c.execute(text('''SELECT r.*,u.username FROM owner_alert_reviews r JOIN users u ON u.id=r.reviewed_by
                    ORDER BY r.reviewed_at DESC,r.id LIMIT :limit OFFSET :offset'''),{'limit':page_size,'offset':(page-1)*page_size}).mappings().all()
                return {'reviews':[reviewed_response(r) for r in rows],'count':count,'page':page,'pageCount':max(1,(count+page_size-1)//page_size)}
