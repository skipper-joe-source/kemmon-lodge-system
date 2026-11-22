"""Record cash and mobile-money receipts without overwriting payment history."""
from alembic import op

revision = "0006_cash_mobile_payments"
down_revision = "0005_same_day_stays"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE payments (
            id uuid PRIMARY KEY,
            reservation_id uuid NOT NULL REFERENCES reservations(id),
            amount numeric(12,0) NOT NULL CHECK (amount > 0),
            method varchar(20) NOT NULL CHECK (method IN ('cash', 'mobile_money')),
            reference varchar(120),
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT payment_reference_check CHECK (
                (method = 'cash' AND reference IS NULL) OR
                (method = 'mobile_money' AND reference IS NOT NULL
                 AND length(trim(reference)) > 0)
            )
        )
    """)
    op.execute("CREATE INDEX payments_reservation_idx ON payments (reservation_id)")
    op.execute("""
        CREATE UNIQUE INDEX payments_mobile_reference_key
        ON payments (lower(trim(reference))) WHERE method = 'mobile_money'
    """)
    op.execute("""
        CREATE FUNCTION protect_payment_history() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'Payment receipts cannot be edited or deleted. Use a separate correction workflow.';
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER payments_keep_history
        BEFORE UPDATE OR DELETE ON payments
        FOR EACH ROW EXECUTE FUNCTION protect_payment_history()
    """)


def downgrade():
    raise RuntimeError("Review payment records and backups before reversing this migration.")
