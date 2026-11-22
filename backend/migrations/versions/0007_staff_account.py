from alembic import op

revision = "0007_staff_accounts"
down_revision = "0006_cash_mobile_payments"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE users (
            id uuid PRIMARY KEY,
            username varchar(80) NOT NULL UNIQUE,
            password_hash text NOT NULL,
            role varchar(20) NOT NULL
                CHECK (
                    role IN (
                        'owner', 'manager',
                        'receptionist', 'housekeeping'
                    )
                ),
            is_active boolean NOT NULL DEFAULT true,
            created_at timestamptz NOT NULL DEFAULT now(),
            CHECK (
                username = lower(trim(username))
                AND length(username) > 0
            )
        )
    """)

    op.execute("""
        ALTER TABLE payments
        ADD COLUMN received_by uuid REFERENCES users(id)
    """)


def downgrade():
    raise RuntimeError(
        "Review staff accounts and payment history before reversing."
    )