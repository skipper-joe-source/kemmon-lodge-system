from alembic import op
import sqlalchemy as sa

revision = "0003_room_numbers_prices"
down_revision = "0002_stay_times"
branch_labels = None
depends_on = None


def upgrade():
    # Allow the twelfth internal room ID.
    op.drop_constraint("rooms_id_check", "rooms", type_="check")
    op.create_check_constraint(
        "rooms_id_check", "rooms", "id BETWEEN 1 AND 12"
    )

    # Add Room 12 without changing existing room IDs.
    op.execute("""
        INSERT INTO rooms (id, nightly_rate, taken)
        VALUES (12, 35000, false)
    """)

    # Public room numbers are separate from internal IDs.
    op.add_column(
        "rooms",
        sa.Column("room_number", sa.Integer(), nullable=True),
    )

    op.execute("""
        UPDATE rooms
        SET room_number = id + 199,
            nightly_rate = CASE
                WHEN id = 1 THEN 15000
                WHEN id BETWEEN 2 AND 3 THEN 20000
                WHEN id BETWEEN 4 AND 8 THEN 25000
                WHEN id BETWEEN 9 AND 11 THEN 30000
                WHEN id = 12 THEN 35000
            END
    """)

    op.alter_column("rooms", "room_number", nullable=False)
    op.create_unique_constraint(
        "rooms_room_number_key", "rooms", ["room_number"]
    )


def downgrade():
    raise RuntimeError(
        "Reversing this change requires reviewing bookings for Room 211."
    )