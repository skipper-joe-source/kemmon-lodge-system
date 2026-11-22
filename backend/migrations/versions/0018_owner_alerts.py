"""Live operational alert candidates, owner settings and immutable review history."""
from alembic import op
revision='0018_owner_alerts'
down_revision='0017_audit_logs'
branch_labels=None
depends_on=None


def upgrade():
    op.execute('''CREATE TABLE owner_alert_settings (
        id integer PRIMARY KEY CHECK(id=1),large_payment_threshold numeric(12,0) CHECK(large_payment_threshold>0),
        version integer NOT NULL DEFAULT 1 CHECK(version>0),changed_at timestamptz NOT NULL DEFAULT clock_timestamp(),changed_by uuid REFERENCES users(id))''')
    op.execute('INSERT INTO owner_alert_settings(id) VALUES(1)')
    op.execute('''CREATE TABLE owner_alert_setting_changes (
        id uuid PRIMARY KEY,previous_threshold numeric(12,0),threshold numeric(12,0),
        previous_version integer NOT NULL,new_version integer NOT NULL,
        changed_by uuid NOT NULL REFERENCES users(id),changed_at timestamptz NOT NULL DEFAULT clock_timestamp())''')
    op.execute('''CREATE TABLE owner_alert_reviews (
        id uuid PRIMARY KEY,alert_key varchar(160) NOT NULL,version varchar(32) NOT NULL,
        kind varchar(30) NOT NULL,title text NOT NULL,details jsonb NOT NULL,
        reviewed_by uuid NOT NULL REFERENCES users(id),reviewed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        notes varchar(1000) NOT NULL,UNIQUE(alert_key,version))''')
    for table in ['owner_alert_setting_changes','owner_alert_reviews']:
        op.execute(f'CREATE TRIGGER {table}_keep_history BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION protect_operating_history()')
    op.execute('CREATE INDEX owner_alert_reviews_time ON owner_alert_reviews(reviewed_at DESC,id DESC)')
    op.execute('CREATE INDEX audit_events_entity ON audit_events(entity_type,entity_id,event_at DESC,id DESC)')
    op.execute('''CREATE VIEW owner_alert_candidates AS
        WITH stock AS (
            SELECT p.id,p.name,p.unit,p.reorder_level,p.created_at,COALESCE(sum(m.delta),0) AS quantity
            FROM inventory_products p LEFT JOIN inventory_movements m ON m.product_id=p.id GROUP BY p.id
        ), receipts AS (
            SELECT reservation_id,sum(amount) AS paid,max(created_at) AS last_paid_at FROM payments GROUP BY reservation_id
        ), debts AS (
            SELECT r.*,rooms.room_number,COALESCE(receipts.paid,0) AS paid,
                r.nightly_rate*GREATEST(1,r.departure_date-r.arrival_date)+r.billing_adjustment+r.bar_charges AS total,
                receipts.last_paid_at
            FROM reservations r JOIN rooms ON rooms.id=r.room_id LEFT JOIN receipts ON receipts.reservation_id=r.id
            WHERE r.status='checked_out'
        ), candidates AS (
            SELECT 'stock:'||s.id::text AS alert_key,'low_stock'::text AS kind,'Low stock: '||s.name AS title,
                s.id::text AS entity_id,COALESCE(m.created_at,s.created_at) AS occurred_at,
                COALESCE(m.id::text,'initial') AS occurrence,
                jsonb_build_object('product',s.name,'stock',s.quantity,'unit',s.unit,'low_stock_threshold',s.reorder_level) AS details
            FROM stock s LEFT JOIN LATERAL (SELECT id,created_at FROM inventory_movements WHERE product_id=s.id ORDER BY created_at DESC,id DESC LIMIT 1) m ON true
            WHERE s.quantity<=s.reorder_level
            UNION ALL
            SELECT 'room:'||r.id::text,'maintenance','Room '||r.room_number||' is out of service',r.id::text,
                COALESCE(m.reported_at,a.event_at,t.started_at),COALESCE(m.id::text,a.id::text,'unrecorded'),
                jsonb_build_object('room_number',r.room_number,'issue',COALESCE(m.title,'Out of service'),'description',m.description,'issue_id',m.id)
            FROM rooms r CROSS JOIN audit_tracking t
            LEFT JOIN maintenance_issues m ON m.room_id=r.id AND m.resolved_at IS NULL
            LEFT JOIN LATERAL (SELECT id,event_at FROM audit_events WHERE entity_type='room' AND entity_id=r.id::text ORDER BY event_at DESC,id DESC LIMIT 1) a ON true
            WHERE r.maintenance_status='out_of_service'
            UNION ALL
            SELECT 'balance:'||d.id::text,'checkout_balance','Unpaid checkout: '||d.guest_name,d.id::text,
                COALESCE(GREATEST(d.checked_out_at,d.last_paid_at),d.created_at),'balance',
                jsonb_build_object('guest',d.guest_name,'room_number',d.room_number,'total_bill',d.total,'paid',d.paid,'outstanding_balance',d.total-d.paid)
            FROM debts d WHERE d.total>d.paid
            UNION ALL
            SELECT 'shift:'||s.id::text,'shift_variance',CASE WHEN s.counted_cash<(s.opening_cash+s.cash_collected-s.cash_expenses) THEN 'Cash shortage: ' ELSE 'Cash surplus: ' END||s.staff_username,
                s.id::text,s.closed_at,'closed',
                jsonb_build_object('staff',s.staff_username,'drawer',s.drawer,'expected_cash',s.opening_cash+s.cash_collected-s.cash_expenses,
                    'counted_cash',s.counted_cash,'variance',s.counted_cash-(s.opening_cash+s.cash_collected-s.cash_expenses),'closing_reason',s.close_notes)
            FROM cashier_shifts s WHERE s.closed_at IS NOT NULL AND s.counted_cash<>(s.opening_cash+s.cash_collected-s.cash_expenses)
            UNION ALL
            SELECT 'payment:'||p.source||':'||p.id::text,'large_payment','Large payment received',p.id::text,p.created_at,'receipt',
                jsonb_build_object('amount',p.amount,'method',p.method,'source',p.source,'receipt_id',p.id,'received_by',COALESCE(u.username,'Not recorded'))
            FROM collection_receipts p CROSS JOIN owner_alert_settings settings LEFT JOIN users u ON u.id=p.received_by
            WHERE settings.large_payment_threshold IS NOT NULL AND p.amount>=settings.large_payment_threshold
        )
        SELECT alert_key,kind,title,entity_id,occurred_at,details,
            md5((details||jsonb_build_object('_occurrence',occurrence))::text) AS version
        FROM candidates''')
    op.execute('''CREATE FUNCTION audit_owner_alert_action() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE actor uuid;name text;data jsonb;act text;entity text;
        BEGIN
            IF TG_TABLE_NAME='owner_alert_reviews' THEN
                actor=NEW.reviewed_by;act='alert.reviewed';entity=NEW.alert_key;
                data=jsonb_build_object('alert_key',NEW.alert_key,'kind',NEW.kind,'version',NEW.version,'notes',NEW.notes);
            ELSE
                actor=NEW.changed_by;act='alerts.threshold_changed';entity='settings';
                data=jsonb_build_object('previous_threshold',NEW.previous_threshold,'threshold',NEW.threshold,'version',NEW.new_version);
            END IF;
            SELECT username INTO name FROM users WHERE id=actor;
            INSERT INTO audit_events(event_at,actor_id,actor_name,action,entity_type,entity_id,source_table,source_key,origin,details)
                VALUES(clock_timestamp(),actor,COALESCE(name,'Not recorded'),act,'owner_alert',entity,TG_TABLE_NAME,NEW.id::text,'live',data);
            RETURN NEW;
        END $$''')
    for table in ['owner_alert_setting_changes','owner_alert_reviews']:
        op.execute(f'CREATE TRIGGER zz_owner_alert_audit AFTER INSERT ON {table} FOR EACH ROW EXECUTE FUNCTION audit_owner_alert_action()')


def downgrade():
    raise RuntimeError('Preserve alert review and setting history before reverting.')
