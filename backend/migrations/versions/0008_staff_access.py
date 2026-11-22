"""Owner-managed accounts and revocable staff login sessions."""
from alembic import op

revision = "0008_staff_access"
down_revision = "0007_staff_accounts"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE staff_sessions (
            token_hash varchar(64) PRIMARY KEY,
            user_id uuid NOT NULL REFERENCES users(id),
            created_at timestamptz NOT NULL DEFAULT now(),
            expires_at timestamptz NOT NULL
        )
    """)
    op.execute("CREATE INDEX staff_sessions_user_idx ON staff_sessions(user_id)")
    op.execute("""
        CREATE TABLE login_limits (
            bucket varchar(64) PRIMARY KEY,
            attempts integer NOT NULL DEFAULT 1,
            window_started timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE staff_audit (
            id uuid PRIMARY KEY,
            owner_id uuid NOT NULL REFERENCES users(id),
            staff_id uuid NOT NULL REFERENCES users(id),
            action varchar(30) NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)


def downgrade():
    raise RuntimeError("Review staff sessions and audit history before reversing this migration.")
