"""Cashier drawers, immutable shift ledger, and closing reconciliation."""
from alembic import op
revision='0016_cashier_shifts'
down_revision='0015_product_barcodes'
branch_labels=None
depends_on=None

def upgrade():
    op.execute('''CREATE TABLE cashier_shifts (
        id uuid PRIMARY KEY,staff_id uuid NOT NULL REFERENCES users(id),staff_username varchar(80) NOT NULL,
        drawer varchar(80) NOT NULL CHECK(length(trim(drawer))>0),opening_cash numeric(16,0) NOT NULL CHECK(opening_cash>=0),
        opened_at timestamptz NOT NULL DEFAULT clock_timestamp(),closed_at timestamptz,
        close_request_id uuid UNIQUE,closed_by uuid REFERENCES users(id),close_notes varchar(1000),
        counted_cash numeric(16,0),cash_collected numeric(16,0),mobile_collected numeric(16,0),
        cash_expenses numeric(16,0),mobile_expenses numeric(16,0),entry_count integer,
        CHECK((closed_at IS NULL AND close_request_id IS NULL AND closed_by IS NULL AND counted_cash IS NULL AND close_notes IS NULL
            AND cash_collected IS NULL AND mobile_collected IS NULL AND cash_expenses IS NULL AND mobile_expenses IS NULL AND entry_count IS NULL)
        OR (closed_at IS NOT NULL AND close_request_id IS NOT NULL AND closed_by IS NOT NULL AND counted_cash>=0 AND counted_cash IS NOT NULL
            AND cash_collected>=0 AND cash_collected IS NOT NULL AND mobile_collected>=0 AND mobile_collected IS NOT NULL
            AND cash_expenses>=0 AND cash_expenses IS NOT NULL AND mobile_expenses>=0 AND mobile_expenses IS NOT NULL
            AND entry_count>=0 AND entry_count IS NOT NULL AND close_notes IS NOT NULL)))''')
    op.execute('CREATE UNIQUE INDEX one_shift_per_staff ON cashier_shifts(staff_id) WHERE closed_at IS NULL')
    op.execute('CREATE UNIQUE INDEX one_shift_per_drawer ON cashier_shifts(lower(drawer)) WHERE closed_at IS NULL')
    op.execute('CREATE INDEX cashier_shifts_opened ON cashier_shifts(opened_at)')
    op.execute('''CREATE TABLE cashier_shift_entries (
        source varchar(10) NOT NULL CHECK(source IN ('stay','bar','expense')),record_id uuid NOT NULL,
        shift_id uuid NOT NULL REFERENCES cashier_shifts(id),kind varchar(12) NOT NULL CHECK(kind IN ('collection','expense')),
        method varchar(20) NOT NULL CHECK(method IN ('cash','mobile_money')),amount numeric(12,0) NOT NULL CHECK(amount>0),
        recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),PRIMARY KEY(source,record_id),
        CHECK((source='expense' AND kind='expense') OR (source IN ('stay','bar') AND kind='collection')))''')
    op.execute('CREATE INDEX cashier_shift_entries_shift ON cashier_shift_entries(shift_id,recorded_at)')
    op.execute('CREATE TRIGGER cashier_entries_keep_history BEFORE UPDATE OR DELETE ON cashier_shift_entries FOR EACH ROW EXECUTE FUNCTION protect_operating_history()')
    op.execute('''CREATE FUNCTION protect_shift_history() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
        IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Cashier shift history cannot be deleted'; END IF;
        IF OLD.closed_at IS NOT NULL OR NEW.closed_at IS NULL OR
            (NEW.id,NEW.staff_id,NEW.staff_username,NEW.drawer,NEW.opening_cash,NEW.opened_at) IS DISTINCT FROM
            (OLD.id,OLD.staff_id,OLD.staff_username,OLD.drawer,OLD.opening_cash,OLD.opened_at)
        THEN RAISE EXCEPTION 'Cashier shifts can only be closed once; shift history cannot be edited'; END IF;
        RETURN NEW; END $$''')
    op.execute('CREATE TRIGGER cashier_shifts_keep_history BEFORE UPDATE OR DELETE ON cashier_shifts FOR EACH ROW EXECUTE FUNCTION protect_shift_history()')
    op.execute('''CREATE FUNCTION attach_cashier_shift() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE cashier uuid; active uuid; value numeric; entry_kind text;
        BEGIN
            IF TG_ARGV[0]='bar' THEN
                IF NEW.method='room' THEN RETURN NEW; END IF;
                cashier=NEW.sold_by;value=NEW.total;entry_kind='collection';
            ELSIF TG_ARGV[0]='expense' THEN
                -- Historical paid expenses are records of earlier spending, not money leaving today's drawer.
                IF NEW.paid_on<>(clock_timestamp() AT TIME ZONE 'Africa/Dar_es_Salaam')::date THEN RETURN NEW; END IF;
                cashier=NEW.recorded_by;value=NEW.amount;entry_kind='expense';
            ELSE cashier=NEW.received_by;value=NEW.amount;entry_kind='collection'; END IF;
            PERFORM pg_advisory_xact_lock(hashtextextended('cashier-shift:'||cashier::text,0));
            SELECT id INTO active FROM cashier_shifts WHERE staff_id=cashier AND closed_at IS NULL FOR UPDATE;
            IF active IS NULL THEN RAISE EXCEPTION USING ERRCODE='P7501',MESSAGE='Open a cashier shift from Cashier shifts before recording money or today''s paid expenses.'; END IF;
            INSERT INTO cashier_shift_entries(source,record_id,shift_id,kind,method,amount)
                VALUES(TG_ARGV[0],NEW.id,active,entry_kind,NEW.method,value);
            RETURN NEW;
        END $$''')
    op.execute("CREATE TRIGGER payments_shift AFTER INSERT ON payments FOR EACH ROW EXECUTE FUNCTION attach_cashier_shift('stay')")
    op.execute("CREATE TRIGGER bar_sales_shift AFTER INSERT ON bar_sales FOR EACH ROW EXECUTE FUNCTION attach_cashier_shift('bar')")
    op.execute("CREATE TRIGGER expenses_shift AFTER INSERT ON expenses FOR EACH ROW EXECUTE FUNCTION attach_cashier_shift('expense')")
    # Existing cashiers retain the ability to take payments by receiving access to their own shifts.
    op.execute('''UPDATE roles SET permissions=(SELECT jsonb_agg(DISTINCT p) FROM jsonb_array_elements_text(permissions || '["shifts.view","shifts.manage"]'::jsonb) AS v(p))
        WHERE permissions ?| ARRAY['payments.record','bar.sell','expenses.record']''')

def downgrade():
    raise RuntimeError('Review cashier shift history before reverting.')
