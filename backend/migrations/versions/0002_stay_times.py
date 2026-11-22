from alembic import op
import sqlalchemy as sa

revision = "0002_stay_times"
down_revision = "0001_reservations"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "reservations",
        sa.Column("checked_in_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "reservations",
        sa.Column("checked_out_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade():
    op.drop_column("reservations", "checked_out_at")
    op.drop_column("reservations", "checked_in_at")