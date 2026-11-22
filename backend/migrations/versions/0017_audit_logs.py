"""Unified, immutable operational audit events and transactional change capture."""
from alembic import op
revision='0017_audit_logs'
down_revision='0016_cashier_shifts'
branch_labels=None
depends_on=None


def upgrade():
    op.execute('''CREATE TABLE audit_tracking (id integer PRIMARY KEY CHECK(id=1),started_at timestamptz NOT NULL DEFAULT clock_timestamp())''')
    op.execute('INSERT INTO audit_tracking(id) VALUES(1)')
    op.execute('CREATE TRIGGER audit_tracking_keep_history BEFORE UPDATE OR DELETE ON audit_tracking FOR EACH ROW EXECUTE FUNCTION protect_operating_history()')
    op.execute('''CREATE TABLE audit_events (
        id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,event_at timestamptz NOT NULL,
        actor_id uuid,actor_name varchar(80) NOT NULL,action varchar(80) NOT NULL,
        entity_type varchar(60) NOT NULL,entity_id text NOT NULL,
        source_table varchar(80) NOT NULL,source_key text,
        origin varchar(20) NOT NULL CHECK(origin IN ('live','historical_record')),
        details jsonb NOT NULL)''')
    op.execute('CREATE INDEX audit_events_time ON audit_events(event_at DESC,id DESC)')
    op.execute('CREATE INDEX audit_events_staff ON audit_events(actor_id,event_at DESC)')
    op.execute('CREATE INDEX audit_events_action ON audit_events(action,event_at DESC)')
    op.execute('CREATE UNIQUE INDEX audit_source_record ON audit_events(source_table,source_key) WHERE source_key IS NOT NULL')
    op.execute('CREATE TRIGGER audit_events_keep_history BEFORE UPDATE OR DELETE ON audit_events FOR EACH ROW EXECUTE FUNCTION protect_operating_history()')
    op.execute('''CREATE FUNCTION audit_pick(data jsonb,keys text[]) RETURNS jsonb LANGUAGE sql IMMUTABLE AS $$
        SELECT COALESCE(jsonb_object_agg(key,value),'{}'::jsonb) FROM jsonb_each(data) WHERE key=ANY(keys)
    $$''')
    op.execute('''CREATE FUNCTION write_operating_audit(tab text,n jsonb,o jsonb DEFAULT NULL,mode text DEFAULT 'live') RETURNS void LANGUAGE plpgsql AS $$
        DECLARE who uuid;who_name text;act text;entity text;entity_key text;source text;stamp timestamptz;
            detail jsonb; fields text[];actor_column text;time_column text;product_label text; public_room integer;
        BEGIN
            who=NULLIF(current_setting('kemmon.actor_id',true),'')::uuid;
            stamp=clock_timestamp();entity_key=n->>'id';source=n->>'id';detail='{}'::jsonb;
            CASE tab
            WHEN 'reservations' THEN
                source=NULL;entity='reservation';
                IF o IS NULL THEN
                    act=CASE WHEN n->>'status'='checked_in' THEN 'reservation.walk_in_created' ELSE 'reservation.created' END;
                ELSIF o->'status' IS DISTINCT FROM n->'status' THEN
                    act=CASE n->>'status' WHEN 'checked_in' THEN 'reservation.checked_in' WHEN 'checked_out' THEN 'reservation.checked_out' WHEN 'cancelled' THEN 'reservation.cancelled' ELSE 'reservation.status_changed' END;
                ELSE
                    -- Extensions/transfers have their own immutable records. Bar debits are captured as bar sales.
                    fields=ARRAY['guest_name','phone','arrival_date','departure_date','nightly_rate','room_id','billing_adjustment','room_allocated_from','bar_charges'];
                    IF audit_pick(o,fields)=audit_pick(n,fields) THEN RETURN; END IF;
                    IF (COALESCE(current_setting('kemmon.request_path',true),'') LIKE '/api/reservations/%/extend'
                        OR COALESCE(current_setting('kemmon.request_path',true),'') LIKE '/api/reservations/%/transfer')
                        AND (o->'guest_name',o->'phone',o->'arrival_date') IS NOT DISTINCT FROM (n->'guest_name',n->'phone',n->'arrival_date') THEN RETURN; END IF;
                    IF pg_trigger_depth()>1 AND audit_pick(o,ARRAY['guest_name','phone','arrival_date','departure_date','nightly_rate','room_id','billing_adjustment','room_allocated_from'])=audit_pick(n,ARRAY['guest_name','phone','arrival_date','departure_date','nightly_rate','room_id','billing_adjustment','room_allocated_from']) THEN RETURN; END IF;
                    act='reservation.updated';
                END IF;
                SELECT room_number INTO public_room FROM rooms WHERE id=(n->>'room_id')::integer;
                fields=ARRAY['room_id','arrival_date','departure_date','nightly_rate','status','checked_in_at','checked_out_at','billing_adjustment','bar_charges','room_allocated_from'];
                detail=jsonb_build_object('room_number',public_room,'after',audit_pick(n,fields),'before',CASE WHEN o IS NULL THEN NULL ELSE audit_pick(o,fields) END,
                    'guest_details_changed',o IS NOT NULL AND (o->'guest_name',o->'phone') IS DISTINCT FROM (n->'guest_name',n->'phone'));
            WHEN 'rooms' THEN
                IF o IS NULL OR (o->'taken',o->'cleaning_status',o->'maintenance_status') IS NOT DISTINCT FROM (n->'taken',n->'cleaning_status',n->'maintenance_status') THEN RETURN; END IF;
                source=NULL;entity='room';act=CASE WHEN o->>'cleaning_status'<>'ready' AND n->>'cleaning_status'='ready' THEN 'room.marked_ready' ELSE 'room.status_changed' END;
                fields=ARRAY['taken','cleaning_status','maintenance_status'];detail=jsonb_build_object('room_number',n->'room_number','before',audit_pick(o,fields),'after',audit_pick(n,fields));
            WHEN 'payments' THEN
                entity='payment';act='payment.recorded';actor_column='received_by';time_column='created_at';
                detail=audit_pick(n,ARRAY['reservation_id','amount','method']);
                SELECT room_number INTO public_room FROM payment_room_snapshots WHERE payment_id=(n->>'id')::uuid;
                detail=detail||jsonb_build_object('room_number',public_room);
            WHEN 'expenses' THEN
                entity='expense';act='expense.recorded';actor_column='recorded_by';time_column='recorded_at';
                detail=audit_pick(n,ARRAY['paid_on','category','description','amount','method']);
            WHEN 'reservation_extensions' THEN
                entity='reservation';entity_key=n->>'reservation_id';act='reservation.extended';actor_column='changed_by';time_column='changed_at';
                detail=audit_pick(n,ARRAY['old_departure','new_departure','nightly_rate','old_total','new_total','reason']);
            WHEN 'room_transfers' THEN
                entity='reservation';entity_key=n->>'reservation_id';act='reservation.room_transferred';actor_column='changed_by';time_column='changed_at';
                detail=audit_pick(n,ARRAY['transfer_date','old_rate','new_rate','old_total','new_total','reason']);
                detail=detail||jsonb_build_object('from_room_number',(SELECT room_number FROM rooms WHERE id=(n->>'from_room_id')::integer),'to_room_number',(SELECT room_number FROM rooms WHERE id=(n->>'to_room_id')::integer));
            WHEN 'inventory_movements' THEN
                entity='product';entity_key=n->>'product_id';act='stock.'||(n->>'kind');actor_column='actor_id';time_column='created_at';
                detail=audit_pick(n,ARRAY['quantity','delta','balance','unit_cost','supplier','notes','occurred_on','sale_id']);
            WHEN 'inventory_products' THEN
                source=NULL;entity='product';actor_column=CASE WHEN o IS NULL THEN 'created_by' ELSE NULL END;
                fields=ARRAY['name','unit','reorder_level','barcode'];
                IF o IS NOT NULL AND audit_pick(o,ARRAY['name','unit','reorder_level'])=audit_pick(n,ARRAY['name','unit','reorder_level']) THEN RETURN; END IF;
                act=CASE WHEN o IS NULL THEN 'product.created' ELSE 'product.updated' END;
                detail=jsonb_build_object('before',CASE WHEN o IS NULL THEN NULL ELSE audit_pick(o,fields) END,'after',audit_pick(n,fields));
            WHEN 'bar_sales' THEN
                entity='bar_sale';act=CASE WHEN n->>'method'='room' THEN 'bar.charged_to_room' ELSE 'bar.sale_paid' END;actor_column='sold_by';time_column='created_at';
                detail=audit_pick(n,ARRAY['method','total','reservation_id','room_number']);
                -- Line items and stock postings have their own records; never copy request_payload or guest details.
            WHEN 'bar_price_changes' THEN
                entity='product';entity_key=n->>'product_id';act='product.price_changed';actor_column='actor_id';time_column='created_at';
                detail=audit_pick(n,ARRAY['old_price','new_price']);
            WHEN 'product_barcode_changes' THEN
                entity='product';entity_key=n->>'product_id';act='product.barcode_changed';actor_column='actor_id';time_column='created_at';
                detail=audit_pick(n,ARRAY['old_barcode','new_barcode']);
            WHEN 'maintenance_events' THEN
                entity='maintenance';entity_key=n->>'issue_id';act='maintenance.'||(n->>'action');actor_column='actor_id';time_column='created_at';
                detail=audit_pick(n,ARRAY['notes']);
                SELECT r.room_number INTO public_room FROM maintenance_issues m JOIN rooms r ON r.id=m.room_id WHERE m.id=(n->>'issue_id')::uuid;
                detail=detail||jsonb_build_object('room_number',public_room);
            WHEN 'opening_cash_changes' THEN
                entity='daily_opening_cash';entity_key=n->>'day';act='cash.opening_changed';actor_column='changed_by';time_column='changed_at';
                detail=audit_pick(n,ARRAY['day','previous_amount','amount','reason']);
            WHEN 'cashier_shifts' THEN
                entity='cashier_shift';
                IF o IS NULL THEN
                    source=source||'|open';act='shift.opened';actor_column='staff_id';time_column='opened_at';detail=audit_pick(n,ARRAY['drawer','staff_username','opening_cash']);
                ELSIF o->>'closed_at' IS NULL AND n->>'closed_at' IS NOT NULL THEN
                    source=source||'|close';act='shift.closed';actor_column='closed_by';time_column='closed_at';
                    detail=audit_pick(n,ARRAY['drawer','staff_username','opening_cash','counted_cash','cash_collected','mobile_collected','cash_expenses','mobile_expenses','entry_count','close_notes']);
                    detail=detail||jsonb_build_object('expected_cash',(n->>'opening_cash')::numeric+(n->>'cash_collected')::numeric-(n->>'cash_expenses')::numeric,
                        'variance',(n->>'counted_cash')::numeric-((n->>'opening_cash')::numeric+(n->>'cash_collected')::numeric-(n->>'cash_expenses')::numeric));
                ELSE RETURN; END IF;
            WHEN 'users' THEN
                source=NULL;entity='staff';fields=ARRAY['username','role','role_id','is_active'];
                IF o IS NOT NULL AND audit_pick(o,fields)=audit_pick(n,fields) THEN RETURN; END IF;
                act=CASE WHEN o IS NULL THEN 'staff.created' ELSE 'staff.access_changed' END;
                detail=jsonb_build_object('before',CASE WHEN o IS NULL THEN NULL ELSE audit_pick(o,fields) END,'after',audit_pick(n,fields));
            WHEN 'roles' THEN
                source=NULL;entity='role';fields=ARRAY['name','permissions'];
                IF o IS NOT NULL AND audit_pick(o,fields)=audit_pick(n,fields) THEN RETURN; END IF;
                act=CASE WHEN o IS NULL THEN 'role.created' ELSE 'role.updated' END;
                detail=jsonb_build_object('before',CASE WHEN o IS NULL THEN NULL ELSE audit_pick(o,fields) END,'after',audit_pick(n,fields));
            ELSE RETURN;
            END CASE;
            IF who IS NULL AND actor_column IS NOT NULL THEN who=NULLIF(n->>actor_column,'')::uuid; END IF;
            SELECT username INTO who_name FROM users WHERE id=who;
            IF mode='historical_record' AND time_column IS NOT NULL THEN stamp=(n->>time_column)::timestamptz; END IF;
            IF entity='product' AND tab<>'inventory_products' THEN
                SELECT name INTO product_label FROM inventory_products WHERE id=entity_key::uuid;
                detail=detail||jsonb_build_object('product_name',product_label);
            END IF;
            INSERT INTO audit_events(event_at,actor_id,actor_name,action,entity_type,entity_id,source_table,source_key,origin,details)
                VALUES(stamp,who,COALESCE(who_name,'Not recorded'),act,entity,entity_key,tab,source,mode,detail)
                ON CONFLICT(source_table,source_key) WHERE source_key IS NOT NULL DO NOTHING;
        END $$''')
    # Import recorded history only, preserving the original event timestamps.
    for table in ['payments','expenses','reservation_extensions','room_transfers','inventory_movements','bar_sales','bar_price_changes','product_barcode_changes','maintenance_events','opening_cash_changes','cashier_shifts']:
        op.execute(f"SELECT write_operating_audit('{table}',to_jsonb(r),NULL,'historical_record') FROM {table} r")
    op.execute("SELECT write_operating_audit('cashier_shifts',to_jsonb(r),jsonb_build_object('closed_at',NULL),'historical_record') FROM cashier_shifts r WHERE closed_at IS NOT NULL")
    for table,entity,col in [('staff_audit','staff','staff_id'),('role_audit','role','role_id')]:
        op.execute(f'''INSERT INTO audit_events(event_at,actor_id,actor_name,action,entity_type,entity_id,source_table,source_key,origin,details)
            SELECT a.created_at,a.owner_id,COALESCE(u.username,'Not recorded'),'{entity}.'||a.action,'{entity}',a.{col}::text,'{table}',a.id::text,'historical_record',
                '{{"note":"Older audit entry; before/after details were not recorded."}}'::jsonb
            FROM {table} a LEFT JOIN users u ON u.id=a.owner_id''')
    op.execute('''CREATE FUNCTION capture_operating_audit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
        PERFORM write_operating_audit(TG_TABLE_NAME,to_jsonb(NEW),CASE WHEN TG_OP='UPDATE' THEN to_jsonb(OLD) ELSE NULL END,'live');
        RETURN NEW;
    END $$''')
    inserts=['payments','expenses','reservation_extensions','room_transfers','inventory_movements','bar_sales','bar_price_changes','product_barcode_changes','maintenance_events','opening_cash_changes']
    for table in inserts:
        op.execute(f'CREATE TRIGGER zz_operating_audit AFTER INSERT ON {table} FOR EACH ROW EXECUTE FUNCTION capture_operating_audit()')
    for table in ['reservations','rooms','inventory_products','cashier_shifts','users','roles']:
        op.execute(f'CREATE TRIGGER zz_operating_audit AFTER INSERT OR UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION capture_operating_audit()')


def downgrade():
    raise RuntimeError('Audit history must be reviewed and preserved before reverting.')
