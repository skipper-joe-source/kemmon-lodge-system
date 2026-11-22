"""Inventory operations. Product row locks serialize every stock change."""
import re
from datetime import date, datetime
from zoneinfo import ZoneInfo
from uuid import UUID
from typing import Literal
from decimal import Decimal
from fastapi import HTTPException, Request, Query
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

def normalize_barcode(value):
    if value is None:return None
    value=value.strip()
    if not value:return None
    if not re.fullmatch(r"[!-~]{1,80}",value):raise ValueError("Barcode must contain 1–80 printable characters without spaces")
    return value

class BarcodeAssignment(BaseModel):
    requestId:UUID
    expectedBarcode:str|None=Field(default=None,max_length=80)
    barcode:str|None=Field(max_length=80)
    @field_validator('barcode','expectedBarcode')
    @classmethod
    def clean_barcode(cls,value):return normalize_barcode(value)

class Product(BaseModel):
    requestId: UUID
    name: str = Field(min_length=1,max_length=120)
    unit: str = Field(min_length=1,max_length=30)
    reorderLevel: int = Field(ge=0,le=1000000,strict=True)
    barcode:str|None=Field(default=None,max_length=80)
    @field_validator('barcode')
    @classmethod
    def clean_barcode(cls,value):return normalize_barcode(value)
    @field_validator('name','unit')
    @classmethod
    def clean(cls,value):
        value=value.strip()
        if not value: raise ValueError('Enter a value')
        return value

class Movement(BaseModel):
    requestId: UUID
    productId: UUID
    kind: Literal['purchase','wastage','count']
    quantity: int = Field(ge=0,le=1000000,strict=True)
    expectedStock: int = Field(ge=0,strict=True)
    unitCost: Decimal | None = Field(default=None,ge=0,le=999999999999,max_digits=12,decimal_places=0)
    supplier: str = Field(default='',max_length=160)
    notes: str = Field(min_length=1,max_length=1000)
    occurredOn: date
    @field_validator('supplier','notes')
    @classmethod
    def clean(cls,value): return value.strip()
    @model_validator(mode='after')
    def valid(self):
        if not self.notes: raise ValueError('Enter a reason or purchase reference')
        if self.occurredOn>datetime.now(ZoneInfo('Africa/Dar_es_Salaam')).date(): raise ValueError('Date cannot be in the future')
        if self.kind=='purchase':
            if self.quantity==0 or self.unitCost is None or not self.supplier: raise ValueError('Purchase needs quantity, unit cost and supplier')
        elif self.unitCost is not None or self.supplier: raise ValueError('Only purchases accept a cost or supplier')
        if self.kind=='wastage' and self.quantity==0: raise ValueError('Enter a positive quantity')
        return self

def register_inventory(app,engine):
    def stock(c,pid):
        return c.execute(text('SELECT COALESCE(sum(delta),0) FROM inventory_movements WHERE product_id=:id'),{'id':pid}).scalar_one()
    def result(row):
        return {k:(str(v) if k in ('id','product_id','actor_id') else v) for k,v in dict(row).items()}
    @app.get('/api/inventory/products')
    def products():
        with engine.connect() as c:
            rows=c.execute(text('''SELECT p.id,p.name,p.unit,p.reorder_level,p.barcode,COALESCE(sum(m.delta),0)::integer AS stock
                FROM inventory_products p LEFT JOIN inventory_movements m ON m.product_id=p.id
                GROUP BY p.id ORDER BY lower(p.name)''')).mappings().all()
            return [dict(result(r),low_stock=r['stock']<=r['reorder_level']) for r in rows]
    @app.post('/api/inventory/products')
    def create_product(body:Product,request:Request):
        try:
            with engine.begin() as c:
                c.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:id,0))'),{'id':str(body.requestId)})
                prior=c.execute(text('SELECT * FROM inventory_products WHERE id=:id'),{'id':body.requestId}).mappings().first()
                if prior:
                    if (prior['name'],prior['unit'],prior['reorder_level'],prior['barcode'],str(prior['created_by']))!=(body.name,body.unit,body.reorderLevel,body.barcode,str(request.state.user['id'])): raise HTTPException(409,'Request ID already used')
                    return {'id':str(body.requestId)}
                c.execute(text('INSERT INTO inventory_products(id,name,unit,reorder_level,barcode,created_by) VALUES(:id,:name,:unit,:level,:barcode,:staff)'),{'id':body.requestId,'name':body.name,'unit':body.unit,'level':body.reorderLevel,'barcode':body.barcode,'staff':request.state.user['id']})
                if body.barcode:
                    c.execute(text('INSERT INTO product_barcode_changes(id,product_id,new_barcode,actor_id) VALUES(:id,:id,:barcode,:staff)'),{'id':body.requestId,'barcode':body.barcode,'staff':request.state.user['id']})
                return {'id':str(body.requestId)}
        except IntegrityError as e:
            if getattr(e.orig,'sqlstate',None)=='23505': raise HTTPException(409,'A product with this name or barcode already exists') from e
            raise
    @app.get('/api/inventory/movements')
    def history(product_id:UUID|None=None,page:int=Query(1,ge=1)):
        with engine.connect() as c:
            rows=c.execute(text('''SELECT m.*,p.name AS product_name,p.unit,u.username AS staff FROM inventory_movements m
                JOIN inventory_products p ON p.id=m.product_id JOIN users u ON u.id=m.actor_id
                WHERE (:all OR m.product_id=:product) ORDER BY m.created_at DESC,m.id LIMIT 51 OFFSET :offset'''),{'all':product_id is None,'product':product_id,'offset':(page-1)*50}).mappings().all()
            return {'items':[result(r) for r in rows[:50]],'hasMore':len(rows)>50,'page':page}
    @app.post('/api/inventory/movements')
    def move(body:Movement,request:Request):
        needed={'purchase':'inventory.purchase','wastage':'inventory.adjust','count':'inventory.adjust'}[body.kind]
        user=request.state.user
        if user['role']!='owner' and needed not in (user.get('role_permissions') or []): raise HTTPException(403,'Your role cannot record this stock action')
        with engine.begin() as c:
            c.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:id,0))'),{'id':str(body.requestId)})
            prior=c.execute(text('SELECT * FROM inventory_movements WHERE id=:id'),{'id':body.requestId}).mappings().first()
            if prior:
                fields=(str(prior['product_id']),prior['kind'],prior['quantity'],prior['unit_cost'],prior['supplier'] or '',prior['notes'],prior['occurred_on'],str(prior['actor_id']))
                if fields!=(str(body.productId),body.kind,body.quantity,body.unitCost,body.supplier,body.notes,body.occurredOn,str(user['id'])): raise HTTPException(409,'Request ID already used')
                return result(prior)
            product=c.execute(text('SELECT id FROM inventory_products WHERE id=:id FOR UPDATE'),{'id':body.productId}).first()
            if not product: raise HTTPException(404,'Product not found')
            current=stock(c,body.productId)
            if current!=body.expectedStock: raise HTTPException(409,'Stock changed. Refresh and review the quantity again.')
            delta=body.quantity if body.kind=='purchase' else -body.quantity if body.kind=='wastage' else body.quantity-current
            if current+delta<0: raise HTTPException(409,'Not enough stock for this wastage')
            row=c.execute(text('''INSERT INTO inventory_movements(id,product_id,kind,quantity,delta,balance,unit_cost,supplier,notes,occurred_on,actor_id)
                VALUES(:id,:product,:kind,:qty,:delta,:balance,:cost,:supplier,:notes,:day,:staff) RETURNING *'''),
                {'id':body.requestId,'product':body.productId,'kind':body.kind,'qty':body.quantity,'delta':delta,'balance':current+delta,'cost':body.unitCost,'supplier':body.supplier or None,'notes':body.notes,'day':body.occurredOn,'staff':user['id']}).mappings().one()
            return result(row)

    @app.post('/api/inventory/products/{product_id}/barcode')
    def assign_barcode(product_id:UUID,body:BarcodeAssignment,request:Request):
        try:
            with engine.begin() as c:
                c.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:id,0))'),{'id':str(body.requestId)})
                prior=c.execute(text('SELECT * FROM product_barcode_changes WHERE id=:id'),{'id':body.requestId}).mappings().first()
                if prior:
                    if (prior['product_id'],prior['old_barcode'],prior['new_barcode'],str(prior['actor_id']))!=(product_id,body.expectedBarcode,body.barcode,str(request.state.user['id'])):raise HTTPException(409,'Request ID already used')
                    return {'saved':True}
                product=c.execute(text('SELECT * FROM inventory_products WHERE id=:id FOR UPDATE'),{'id':product_id}).mappings().first()
                if not product:raise HTTPException(404,'Product not found')
                if product['barcode']!=body.expectedBarcode:raise HTTPException(409,'Barcode changed. Refresh inventory and review again.')
                c.execute(text('UPDATE inventory_products SET barcode=:code WHERE id=:id'),{'code':body.barcode,'id':product_id})
                c.execute(text('INSERT INTO product_barcode_changes(id,product_id,old_barcode,new_barcode,actor_id) VALUES(:id,:product,:old,:new,:staff)'),{'id':body.requestId,'product':product_id,'old':body.expectedBarcode,'new':body.barcode,'staff':request.state.user['id']})
                return {'saved':True}
        except IntegrityError as e:
            if getattr(e.orig,'sqlstate',None)=='23505':raise HTTPException(409,'This barcode is already assigned to another product') from e
            raise
