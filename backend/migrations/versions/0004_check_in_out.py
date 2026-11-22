from alembic import op
import sqlalchemy as sa

revision = "0004_check_in_out"
down_revision = "0003_room_numbers_prices"
branch_labels = None
depends_on = None


def upgrade():
    # Track whether a room is ready or needs cleaning.
    op.add_column(
        "rooms",
        sa.Column(
            "cleaning_status",
            sa.String(20),
            nullable=False,
            server_default="ready",
        ),
    )

    op.create_check_constraint(
        "rooms_cleaning_status_check",
        "rooms",
        "cleaning_status IN ('ready', 'needs_cleaning')",
    )

    # Allow reservations to move through the stay.
    op.drop_constraint(
        "reservations_status_check",
        "reservations",
        type_="check",
    )

    op.create_check_constraint(
        "reservations_status_check",
        "reservations",
        "status IN "
        "('confirmed', 'checked_in', 'checked_out', 'cancelled')",
    )

    # Keep double-booking protection after check-in.
    op.execute("""
        ALTER TABLE reservations
        DROP CONSTRAINT no_overlapping_room_bookings
    """)

    op.execute("""
        ALTER TABLE reservations
        ADD CONSTRAINT no_overlapping_room_bookings
        EXCLUDE USING gist (
            room_id WITH =,
            daterange(arrival_date, departure_date, '[)') WITH &&
        )
        WHERE (status IN ('confirmed', 'checked_in'))
    """)

    # Only one guest reservation can occupy a room at a time.
    op.execute("""
        CREATE UNIQUE INDEX one_checked_in_reservation_per_room
        ON reservations (room_id)
        WHERE status = 'checked_in'
    """)


def downgrade():
    raise RuntimeError(
        "Review stay records before reversing this migration."
    )