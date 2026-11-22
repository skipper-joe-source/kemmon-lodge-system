"""Create rooms and reservations with database overlap protection."""
from alembic import op

revision = "0001_reservations"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.execute("""
        CREATE TABLE rooms (
            id integer PRIMARY KEY CHECK (id BETWEEN 1 AND 11),
            nightly_rate numeric(12,0) NOT NULL CHECK (nightly_rate > 0),
            taken boolean NOT NULL DEFAULT false
        )
    """)
    op.execute("INSERT INTO rooms (id, nightly_rate) SELECT generate_series(1,11), 40000")
    op.execute("""
        CREATE TABLE reservations (
            id uuid PRIMARY KEY,
            guest_name varchar(120) NOT NULL CHECK (length(trim(guest_name)) > 0),
            phone varchar(40) NOT NULL CHECK (length(trim(phone)) > 0),
            room_id integer NOT NULL REFERENCES rooms(id),
            arrival_date date NOT NULL,
            departure_date date NOT NULL CHECK (departure_date > arrival_date),
            nightly_rate numeric(12,0) NOT NULL CHECK (nightly_rate > 0),
            status varchar(20) NOT NULL DEFAULT 'confirmed' CHECK (status IN ('confirmed','cancelled')),
            created_at timestamptz NOT NULL DEFAULT now(),
            cancelled_at timestamptz,
            CONSTRAINT no_overlapping_room_bookings EXCLUDE USING gist (
                room_id WITH =, daterange(arrival_date, departure_date, '[)') WITH &&
            ) WHERE (status = 'confirmed')
        )
    """)


def downgrade():
    op.execute("DROP TABLE reservations")
    op.execute("DROP TABLE rooms")
