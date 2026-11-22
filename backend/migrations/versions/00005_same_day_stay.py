"""Allow same-day stays while keeping active booking conflict protection."""
from alembic import op
import sqlalchemy as sa

revision = "0005_same_day_stays"
down_revision = "0004_check_in_out"
branch_labels = None
depends_on = None


def upgrade():
    # Find PostgreSQL's automatically named original date constraint.
    connection = op.get_bind()
    constraints = connection.execute(sa.text("""
        SELECT conname
        FROM pg_constraint
        WHERE conrelid = 'reservations'::regclass
          AND contype = 'c'
          AND pg_get_constraintdef(oid) LIKE '%departure_date%'
          AND pg_get_constraintdef(oid) LIKE '%arrival_date%'
    """)).scalars().all()
    if len(constraints) != 1:
        raise RuntimeError("Expected one reservation date constraint. Review the schema before continuing.")
    op.drop_constraint(constraints[0], "reservations", type_="check")
    op.create_check_constraint(
        "reservations_stay_dates_check", "reservations",
        "departure_date >= arrival_date",
    )

    # A same-day booking must reserve the day, not an empty date range.
    op.execute("""
        ALTER TABLE reservations
        DROP CONSTRAINT no_overlapping_room_bookings
    """)
    op.execute("""
        ALTER TABLE reservations
        ADD CONSTRAINT no_overlapping_room_bookings
        EXCLUDE USING gist (
            room_id WITH =,
            daterange(
                arrival_date,
                GREATEST(departure_date, arrival_date + 1),
                '[)'
            ) WITH &&
        ) WHERE (status IN ('confirmed', 'checked_in'))
    """)


def downgrade():
    raise RuntimeError("Review same-day reservations before reversing this migration.")
