"""Room transfers, expense receipts, and audited daily opening cash."""
from alembic import op

revision = "0011_transfers_expenses"
down_revision = "0010_reservation_extensions"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE reservations ADD COLUMN billing_adjustment numeric(12,0) NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE reservations ADD COLUMN room_allocated_from date")
    op.execute("UPDATE reservations SET room_allocated_from=arrival_date")
    op.execute("""
        CREATE FUNCTION set_room_allocation_start() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            NEW.room_allocated_from := COALESCE(NEW.room_allocated_from,NEW.arrival_date);
            RETURN NEW;
        END; $$
    """)
    op.execute("CREATE TRIGGER reservations_allocation_start BEFORE INSERT ON reservations FOR EACH ROW EXECUTE FUNCTION set_room_allocation_start()")
    op.execute("ALTER TABLE reservations ALTER COLUMN room_allocated_from SET NOT NULL")
    op.create_check_constraint("reservations_room_allocation_check", "reservations", "room_allocated_from >= arrival_date AND room_allocated_from <= departure_date")
    op.execute("ALTER TABLE reservations DROP CONSTRAINT no_overlapping_room_bookings")
    op.execute("""
        ALTER TABLE reservations ADD CONSTRAINT no_overlapping_room_bookings
        EXCLUDE USING gist (room_id WITH =,
            daterange(room_allocated_from,GREATEST(departure_date,room_allocated_from+1),'[)') WITH &&)
        WHERE (status IN ('confirmed','checked_in'))
    """)
    op.execute("""
        CREATE TABLE room_transfers (
            id uuid PRIMARY KEY,
            reservation_id uuid NOT NULL REFERENCES reservations(id),
            from_room_id integer NOT NULL REFERENCES rooms(id),
            to_room_id integer NOT NULL REFERENCES rooms(id) CHECK (to_room_id <> from_room_id),
            quote_version varchar(64) NOT NULL,
            old_allocation_start date NOT NULL,
            transfer_date date NOT NULL,
            old_rate numeric(12,0) NOT NULL CHECK(old_rate>0),
            new_rate numeric(12,0) NOT NULL CHECK(new_rate>0),
            old_total numeric(12,0) NOT NULL CHECK(old_total>0),
            new_total numeric(12,0) NOT NULL CHECK(new_total>0),
            reason varchar(500) NOT NULL CHECK (length(trim(reason)) > 0),
            changed_by uuid NOT NULL REFERENCES users(id),
            changed_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX room_transfers_reservation_idx ON room_transfers(reservation_id)")
    # Snapshot the room printed on each payment receipt without changing payment rows.
    op.execute("CREATE TABLE payment_room_snapshots(payment_id uuid PRIMARY KEY REFERENCES payments(id),room_number integer NOT NULL)")
    op.execute("INSERT INTO payment_room_snapshots SELECT p.id,rooms.room_number FROM payments p JOIN reservations r ON r.id=p.reservation_id JOIN rooms ON rooms.id=r.room_id")
    op.execute("""
        CREATE FUNCTION snapshot_payment_room() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            INSERT INTO payment_room_snapshots(payment_id,room_number)
            SELECT NEW.id,rooms.room_number FROM reservations r JOIN rooms ON rooms.id=r.room_id WHERE r.id=NEW.reservation_id;
            RETURN NEW;
        END; $$
    """)
    op.execute("CREATE TRIGGER payments_room_snapshot AFTER INSERT ON payments FOR EACH ROW EXECUTE FUNCTION snapshot_payment_room()")
    op.execute("""
        CREATE TABLE expenses (
            id uuid PRIMARY KEY,
            paid_on date NOT NULL,
            category varchar(80) NOT NULL CHECK (length(trim(category)) > 0),
            description varchar(500) NOT NULL CHECK (length(trim(description)) > 0),
            amount numeric(12,0) NOT NULL CHECK (amount > 0),
            method varchar(20) NOT NULL CHECK (method IN ('cash','mobile_money')),
            reference varchar(120),
            recorded_by uuid NOT NULL REFERENCES users(id),
            recorded_at timestamptz NOT NULL DEFAULT now(),
            CHECK ((method='cash' AND reference IS NULL) OR
                   (method='mobile_money' AND reference IS NOT NULL AND length(trim(reference))>0))
        )
    """)
    op.execute("CREATE INDEX expenses_paid_on_idx ON expenses(paid_on)")
    op.execute("CREATE UNIQUE INDEX expenses_mobile_reference_key ON expenses(lower(trim(reference))) WHERE method='mobile_money'")
    op.execute("""
        CREATE TABLE daily_opening_cash (
            day date PRIMARY KEY,
            amount numeric(12,0) NOT NULL CHECK(amount>=0),
            recorded_by uuid NOT NULL REFERENCES users(id),
            recorded_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE opening_cash_changes (
            id uuid PRIMARY KEY,
            day date NOT NULL REFERENCES daily_opening_cash(day),
            previous_amount numeric(12,0),
            amount numeric(12,0) NOT NULL CHECK(amount>=0),
            reason varchar(500) NOT NULL CHECK(length(trim(reason))>0),
            changed_by uuid NOT NULL REFERENCES users(id),
            changed_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE FUNCTION protect_operating_history() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'Operating history cannot be edited or deleted. Record a separate correction.';
        END; $$
    """)
    for table in ('room_transfers','payment_room_snapshots','expenses','opening_cash_changes'):
        op.execute(f"CREATE TRIGGER {table}_keep_history BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION protect_operating_history()")


def downgrade():
    raise RuntimeError("Review room transfers and financial records before reversing this migration.")
