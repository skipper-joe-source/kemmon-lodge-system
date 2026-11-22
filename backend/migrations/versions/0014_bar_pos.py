"""Bar sales, stock deductions, room folio charges and combined collections."""
from alembic import op
revision='0014_bar_pos'
down_revision='0013_inventory'
branch_labels=None
depends_on=None

def upgrade():
    op.execute("ALTER TABLE inventory_products ADD COLUMN selling_price numeric(12,0) NOT NULL DEFAULT 0 CHECK(selling_price>=0)")
    op.execute("ALTER TABLE reservations ADD COLUMN bar_charges numeric(16,0) NOT NULL DEFAULT 0 CHECK(bar_charges>=0)")
    op.execute('''CREATE TABLE bar_price_changes (
        id uuid PRIMARY KEY,product_id uuid NOT NULL REFERENCES inventory_products(id),
        old_price numeric(12,0) NOT NULL,new_price numeric(12,0) NOT NULL CHECK(new_price>0),
        actor_id uuid NOT NULL REFERENCES users(id),created_at timestamptz NOT NULL DEFAULT now())''')
    op.execute('''CREATE TABLE bar_sales (
        id uuid PRIMARY KEY, method varchar(20) NOT NULL CHECK(method IN ('cash','mobile_money','room')),
        total numeric(12,0) NOT NULL CHECK(total>0), reference varchar(120),
        reservation_id uuid REFERENCES reservations(id),room_number integer,guest_name varchar(120),
        sold_by uuid NOT NULL REFERENCES users(id),created_at timestamptz NOT NULL DEFAULT now(),
        request_payload jsonb NOT NULL,
        CHECK((method='room' AND reservation_id IS NOT NULL AND room_number IS NOT NULL AND guest_name IS NOT NULL AND reference IS NULL)
           OR (method='cash' AND reservation_id IS NULL AND reference IS NULL)
           OR (method='mobile_money' AND reservation_id IS NULL AND length(trim(reference))>0 AND reference IS NOT NULL)))''')
    op.execute('''CREATE TABLE bar_sale_items (
        sale_id uuid NOT NULL REFERENCES bar_sales(id),product_id uuid NOT NULL REFERENCES inventory_products(id),
        product_name varchar(120) NOT NULL,unit varchar(30) NOT NULL,
        quantity integer NOT NULL CHECK(quantity>0),unit_price numeric(12,0) NOT NULL CHECK(unit_price>0),
        PRIMARY KEY(sale_id,product_id))''')
    op.execute('CREATE INDEX bar_sales_guest ON bar_sales(reservation_id)')
    op.execute('CREATE INDEX bar_sales_date ON bar_sales(created_at)')
    op.execute('''DO $$ DECLARE c record; BEGIN
        FOR c IN SELECT conname FROM pg_constraint WHERE conrelid='inventory_movements'::regclass AND contype='c' AND pg_get_constraintdef(oid) LIKE '%kind%'
        LOOP EXECUTE format('ALTER TABLE inventory_movements DROP CONSTRAINT %I',c.conname); END LOOP;
        END $$''')
    op.execute("ALTER TABLE inventory_movements ADD COLUMN sale_id uuid REFERENCES bar_sales(id)")
    op.execute('''ALTER TABLE inventory_movements ADD CONSTRAINT inventory_kind_check CHECK(
        (kind='purchase' AND quantity>0 AND delta=quantity AND unit_cost IS NOT NULL AND unit_cost>=0 AND supplier IS NOT NULL AND sale_id IS NULL)
        OR (kind='wastage' AND quantity>0 AND delta=-quantity AND unit_cost IS NULL AND sale_id IS NULL)
        OR (kind='count' AND unit_cost IS NULL AND sale_id IS NULL)
        OR (kind='sale' AND quantity>0 AND delta=-quantity AND unit_cost IS NULL AND sale_id IS NOT NULL))''')
    op.execute('CREATE UNIQUE INDEX inventory_sale_product ON inventory_movements(sale_id,product_id) WHERE sale_id IS NOT NULL')
    for table in ['bar_sales','bar_sale_items','bar_price_changes']:
        op.execute(f'CREATE TRIGGER {table}_keep_history BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION protect_operating_history()')
    # Shared registry prevents a mobile transaction being used for both a room payment and a bar sale.
    op.execute("CREATE TABLE collection_receipt_ids(receipt_id uuid PRIMARY KEY,source varchar(10) NOT NULL)")
    op.execute("INSERT INTO collection_receipt_ids SELECT id,'stay' FROM payments")
    op.execute('CREATE TABLE collection_mobile_references(reference varchar(120) PRIMARY KEY,receipt_id uuid NOT NULL,source varchar(10) NOT NULL)')
    op.execute("INSERT INTO collection_mobile_references SELECT upper(trim(reference)),id,'stay' FROM payments WHERE method='mobile_money'")
    op.execute('''CREATE FUNCTION reserve_mobile_reference() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
        INSERT INTO collection_receipt_ids VALUES(NEW.id,TG_ARGV[0]);
        IF NEW.method='mobile_money' THEN
            INSERT INTO collection_mobile_references VALUES(upper(trim(NEW.reference)),NEW.id,TG_ARGV[0]);
        END IF; RETURN NEW; END $$''')
    op.execute("CREATE TRIGGER payments_mobile_registry BEFORE INSERT ON payments FOR EACH ROW EXECUTE FUNCTION reserve_mobile_reference('stay')")
    op.execute("CREATE TRIGGER bar_mobile_registry BEFORE INSERT ON bar_sales FOR EACH ROW EXECUTE FUNCTION reserve_mobile_reference('bar')")
    op.execute('''CREATE FUNCTION add_bar_folio_charge() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
        IF NEW.method='room' THEN UPDATE reservations SET bar_charges=bar_charges+NEW.total WHERE id=NEW.reservation_id; END IF;
        RETURN NEW; END $$''')
    op.execute('CREATE TRIGGER bar_charge_folio AFTER INSERT ON bar_sales FOR EACH ROW EXECUTE FUNCTION add_bar_folio_charge()')
    op.execute('''CREATE VIEW collection_receipts AS
        SELECT id,reservation_id,amount,method,reference,received_by,created_at,'stay'::text AS source FROM payments
        UNION ALL
        SELECT id,NULL::uuid,total,method,reference,sold_by,created_at,'bar'::text FROM bar_sales WHERE method<>'room' ''')

def downgrade():
    raise RuntimeError('Review bar sales, stock and payment history before reverting.')
