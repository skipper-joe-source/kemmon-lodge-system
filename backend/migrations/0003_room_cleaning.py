from alembic import op
import sqlalchemy as sa

revision = "0003_room_cleaning"
down_revision = "0002_stay_times"
branch_labels = None
depends_on = None


def upgrade():
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


def downgrade():
    op.drop_constraint(
        "rooms_cleaning_status_check", "rooms", type_="check"
    )
    op.drop_column("rooms", "cleaning_status")