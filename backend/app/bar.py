"""Bar POS: immutable receipts and atomic stock/room postings."""
from datetime import date, datetime, timedelta, time
from zoneinfo import ZoneInfo
from uuid import UUID,uuid4
from typing import Literal
from decimal import Decimal
from fastapi import HTTPException,Request,Query
from pydantic import BaseModel,Field,model_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
import json

class Price(BaseModel):
    requestId:UUID
    expectedPrice:Decimal=Field(ge=0,max_digits=12,decimal_places=0,allow_inf_nan=False)
    price:Decimal=Field(gt=0,max_digits=12,decimal_places=0,allow_inf_nan=False)

class SaleItem(BaseModel):
    productId:UUID
    quantity:int=Field(ge=1,le=1000000,strict=True)
    expectedPrice:Decimal=Field(gt=0,max_digits=12,decimal_places=0,allow_inf_nan=False)

class Sale(BaseModel):
    requestId:UUID
    method:Literal['cash','mobile_money','room']
    reference:str|None=Field(default=None,max_length=120)
    reservationId:UUID|None=None
    items:list[SaleItem]=Field(min_length=1,max_length=100)
    @model_validator(mode='after')
    def valid(self):
        self.reference=(self.reference or '').strip().upper() or None
        if len({i.productId for i in self.items})!=len(self.items): raise ValueError('Combine duplicate products into one line')
        if self.method=='mobile_money' and not self.reference:raise ValueError('Enter the received mobile payment reference')
        if self.method!='mobile_money' and self.reference:raise ValueError('Only mobile money accepts a reference')
        if (self.method=='room')!=(self.reservationId is not None):raise ValueError('Select a checked-in guest for room charges only')
        return self

def bar_receipt(c,sale_id):
    s=c.execute(text('SELECT s.*,u.username AS staff FROM bar_sales s JOIN users u ON u.id=s.sold_by WHERE s.id=:id'),{'id':sale_id}).mappings().first()
    if not s:raise HTTPException(404,'Bar receipt not found')
    items=c.execute(text('SELECT * FROM bar_sale_items WHERE sale_id=:id ORDER BY product_name,product_id'),{'id':sale_id}).mappings().all()
    return {'type':'bar','lodgeName':'Kemmon Lodge','receiptNumber':'KEMMON-BAR-'+str(sale_id).upper(),'id':str(sale_id),
        'method':s['method'],'reference':s['reference'],'total':int(s['total']),'soldAt':s['created_at'].isoformat(),
        'staff':s['staff'],'roomNumber':s['room_number'],'guest':s['guest_name'],'reservationId':str(s['reservation_id']) if s['reservation_id'] else None,
        'items':[{'productId':str(i['product_id']),'name':i['product_name'],'unit':i['unit'],'quantity':i['quantity'],'unitPrice':int(i['unit_price']),'total':int(i['unit_price'])*i['quantity']} for i in items]}

def register_bar(app,engine):
    @app.get('/api/bar/products')
    def catalog():
        with engine.connect() as c:
            return [dict(id=str(r['id']),barcode=r['barcode'],name=r['name'],unit=r['unit'],price=int(r['selling_price']),stock=int(r['stock'])) for r in c.execute(text('''SELECT p.*,COALESCE(sum(m.delta),0) AS stock FROM inventory_products p
                LEFT JOIN inventory_movements m ON m.product_id=p.id GROUP BY p.id ORDER BY lower(p.name)''')).mappings()]
    @app.post('/api/bar/products/{product_id}/price')
    def set_price(product_id:UUID,body:Price,request:Request):
        with engine.begin() as c:
            c.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:id,0))'),{'id':str(body.requestId)})
            old=c.execute(text('SELECT * FROM bar_price_changes WHERE id=:id'),{'id':body.requestId}).mappings().first()
            if old:
                if (old['product_id'],old['old_price'],old['new_price'],str(old['actor_id']))!=(product_id,body.expectedPrice,body.price,str(request.state.user['id'])):raise HTTPException(409,'Request ID already used')
                return {'saved':True}
            p=c.execute(text('SELECT * FROM inventory_products WHERE id=:id FOR UPDATE'),{'id':product_id}).mappings().first()
            if not p:raise HTTPException(404,'Product not found')
            if p['selling_price']!=body.expectedPrice:raise HTTPException(409,'Price changed. Refresh and review again.')
            c.execute(text('INSERT INTO bar_price_changes(id,product_id,old_price,new_price,actor_id) VALUES(:id,:p,:old,:new,:staff)'),{'id':body.requestId,'p':product_id,'old':body.expectedPrice,'new':body.price,'staff':request.state.user['id']})
            c.execute(text('UPDATE inventory_products SET selling_price=:price WHERE id=:id'),{'price':body.price,'id':product_id})
            return {'saved':True}
    @app.get('/api/bar/guests')
    def guests():
        with engine.connect() as c:
            return [dict(id=str(r['id']),guest=r['guest_name'],roomNumber=r['room_number']) for r in c.execute(text("SELECT r.id,r.guest_name,rooms.room_number FROM reservations r JOIN rooms ON rooms.id=r.room_id WHERE r.status='checked_in' ORDER BY rooms.room_number")).mappings()]
    @app.post('/api/bar/sales')
    def sell(body:Sale,request:Request):
        user=request.state.user
        if body.method=='room' and user['role']!='owner' and 'bar.charge' not in (user.get('role_permissions') or []):raise HTTPException(403,'Your role cannot charge a guest room')
        payload=body.model_dump(mode='json',exclude={'requestId'})
        payload['items']=sorted(payload['items'],key=lambda i:i['productId'])
        try:
            with engine.begin() as c:
                c.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:id,0))'),{'id':str(body.requestId)})
                prior=c.execute(text('SELECT * FROM bar_sales WHERE id=:id'),{'id':body.requestId}).mappings().first()
                if prior:
                    if prior['request_payload']!=payload or str(prior['sold_by'])!=str(user['id']):raise HTTPException(409,'Request ID already used for another sale')
                    return bar_receipt(c,body.requestId)
                guest=None
                if body.method=='room':
                    guest=c.execute(text('SELECT r.*,rooms.room_number FROM reservations r JOIN rooms ON rooms.id=r.room_id WHERE r.id=:id FOR UPDATE OF r'),{'id':body.reservationId}).mappings().first()
                    if not guest or guest['status']!='checked_in':raise HTTPException(409,'Room charges require a currently checked-in guest. Refresh guests.')
                lines=[];total=0
                for item in sorted(body.items,key=lambda i:str(i.productId)):
                    p=c.execute(text('SELECT * FROM inventory_products WHERE id=:id FOR UPDATE'),{'id':item.productId}).mappings().first()
                    if not p:raise HTTPException(404,'Product not found')
                    if p['selling_price']<=0 or p['selling_price']!=item.expectedPrice:raise HTTPException(409,'Selling price changed or is unset. Refresh products and review again.')
                    stock=int(c.execute(text('SELECT COALESCE(sum(delta),0) FROM inventory_movements WHERE product_id=:id'),{'id':item.productId}).scalar_one())
                    if stock<item.quantity:raise HTTPException(409,f"Insufficient stock for {p['name']}. Available: {stock}.")
                    total+=int(p['selling_price'])*item.quantity
                    lines.append((item,p,stock))
                if total>999999999999:raise HTTPException(422,'Sale total exceeds the maximum amount')
                c.execute(text('''INSERT INTO bar_sales(id,method,total,reference,reservation_id,room_number,guest_name,sold_by,request_payload)
                    VALUES(:id,:method,:total,:ref,:res,:room,:guest,:staff,CAST(:payload AS jsonb))'''),
                    {'id':body.requestId,'method':body.method,'total':total,'ref':body.reference,'res':body.reservationId,
                    'room':guest['room_number'] if guest else None,'guest':guest['guest_name'] if guest else None,'staff':user['id'],'payload':json.dumps(payload)})
                for item,p,stock in lines:
                    c.execute(text('INSERT INTO bar_sale_items(sale_id,product_id,product_name,unit,quantity,unit_price) VALUES(:sale,:p,:name,:unit,:qty,:price)'),{'sale':body.requestId,'p':item.productId,'name':p['name'],'unit':p['unit'],'qty':item.quantity,'price':p['selling_price']})
                    c.execute(text('''INSERT INTO inventory_movements(id,product_id,kind,quantity,delta,balance,notes,occurred_on,actor_id,sale_id)
                        VALUES(:id,:p,'sale',:qty,:delta,:balance,:notes,(now() AT TIME ZONE 'Africa/Dar_es_Salaam')::date,:staff,:sale)'''),
                        {'id':uuid4(),'p':item.productId,'qty':item.quantity,'delta':-item.quantity,'balance':stock-item.quantity,'notes':'Bar sale '+str(body.requestId),'staff':user['id'],'sale':body.requestId})
                return bar_receipt(c,body.requestId)
        except IntegrityError as e:
            if getattr(e.orig,'sqlstate',None)=='23505':raise HTTPException(409,'Sale request or mobile reference already recorded. Check receipts before retrying.') from e
            raise
    @app.get('/api/bar/sales/{sale_id}')
    def receipt(sale_id:UUID):
        with engine.connect() as c:return bar_receipt(c,sale_id)
    @app.get('/api/reservations/{reservation_id}/bar-sales')
    def folio(reservation_id:UUID):
        with engine.connect() as c:
            ids=c.execute(text('SELECT id FROM bar_sales WHERE reservation_id=:id ORDER BY created_at,id'),{'id':reservation_id}).scalars().all()
            return [bar_receipt(c,i) for i in ids]
    @app.get('/api/bar/report')
    def report(start_date:date,end_date:date,page:int=Query(1,ge=1)):
        if start_date>end_date or end_date==date.max:raise HTTPException(422,'Choose a valid date range')
        zone=ZoneInfo('Africa/Dar_es_Salaam')
        params={'start':datetime.combine(start_date,time.min,tzinfo=zone),'stop':datetime.combine(end_date+timedelta(days=1),time.min,tzinfo=zone),'offset':(page-1)*50}
        with engine.connect().execution_options(isolation_level='REPEATABLE READ') as c:
            with c.begin():
                totals=c.execute(text('''SELECT COALESCE(sum(total),0) AS total,COALESCE(sum(total) FILTER(WHERE method='cash'),0) AS cash,
                    COALESCE(sum(total) FILTER(WHERE method='mobile_money'),0) AS mobile,COALESCE(sum(total) FILTER(WHERE method='room'),0) AS room,
                    count(*) AS count FROM bar_sales WHERE created_at>=:start AND created_at<:stop'''),params).mappings().one()
                staff=c.execute(text('''SELECT u.username,COALESCE(sum(s.total),0) AS total,count(*) AS count FROM bar_sales s JOIN users u ON u.id=s.sold_by
                    WHERE s.created_at>=:start AND s.created_at<:stop GROUP BY u.id,u.username ORDER BY total DESC,u.username'''),params).mappings().all()
                ids=c.execute(text('SELECT id FROM bar_sales WHERE created_at>=:start AND created_at<:stop ORDER BY created_at DESC,id LIMIT 51 OFFSET :offset'),params).scalars().all()
                return {'startDate':str(start_date),'endDate':str(end_date),'timezone':'Africa/Dar_es_Salaam',**{k:int(v) for k,v in totals.items()},'staff':[dict(username=r['username'],total=int(r['total']),count=r['count']) for r in staff], 'sales':[bar_receipt(c,i) for i in ids[:50]],'page':page,'hasMore':len(ids)>50}

    @app.get('/api/bar/scan')
    def scan(barcode:str=Query(min_length=1,max_length=80)):
        # Keep codes as text so leading zeros survive USB/Bluetooth scanner input.
        from app.inventory import normalize_barcode
        try:code=normalize_barcode(barcode)
        except ValueError as e:raise HTTPException(422,str(e)) from e
        if not code:raise HTTPException(422,'Scan or enter a barcode')
        with engine.connect() as c:
            p=c.execute(text("SELECT p.*,COALESCE((SELECT sum(delta) FROM inventory_movements WHERE product_id=p.id),0) AS stock FROM inventory_products p WHERE p.barcode=:code"),{'code':code}).mappings().first()
            if not p:raise HTTPException(404,'Unknown barcode. Assign this code to a product in Inventory first.')
            if p['selling_price']<=0:raise HTTPException(409,'This product has no selling price. Set its price before selling.')
            if p['stock']<=0:raise HTTPException(409,'This product is out of stock.')
            return {'id':str(p['id']),'name':p['name'],'unit':p['unit'],'barcode':p['barcode'],'price':int(p['selling_price']),'stock':int(p['stock'])}
