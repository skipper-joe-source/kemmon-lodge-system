"""Keep an immutable history of reservation departure extensions."""
from alembic import op

revision = "0010_reservation_extensions"
down_revision = "0009_custom_roles"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE reservation_extensions (
            id uuid PRIMARY KEY,
            reservation_id uuid NOT NULL REFERENCES reservations(id),
            changed_by uuid NOT NULL REFERENCES users(id),
            old_departure date NOT NULL,
            new_departure date NOT NULL CHECK (new_departure > old_departure),
            nightly_rate numeric(12,0) NOT NULL CHECK (nightly_rate > 0),
            old_total numeric(12,0) NOT NULL CHECK (old_total > 0),
            new_total numeric(12,0) NOT NULL CHECK (new_total >= old_total),
            reason varchar(500) NOT NULL CHECK (length(trim(reason)) > 0),
            changed_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX reservation_extensions_reservation_idx ON reservation_extensions(reservation_id)")
    op.execute("""
        CREATE FUNCTION protect_extension_history() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'Reservation extension history cannot be edited or deleted.';
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER reservation_extensions_keep_history
        BEFORE UPDATE OR DELETE ON reservation_extensions
        FOR EACH ROW EXECUTE FUNCTION protect_extension_history()
    """)


def downgrade():
    raise RuntimeError("Review reservation extension history before reversing this migration.")
