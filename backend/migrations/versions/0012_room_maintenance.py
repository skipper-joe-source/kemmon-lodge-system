"""Room out-of-service state, maintenance issues, and immutable action history."""
from alembic import op

revision = "0012_room_maintenance"
down_revision = "0011_transfers_expenses"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE rooms ADD COLUMN maintenance_status varchar(20) NOT NULL DEFAULT 'available' CHECK(maintenance_status IN ('available','out_of_service'))")
    op.execute("""
        CREATE TABLE maintenance_issues (
            id uuid PRIMARY KEY,
            room_id integer NOT NULL REFERENCES rooms(id),
            title varchar(200) NOT NULL CHECK(length(trim(title))>0),
            description varchar(1000) NOT NULL CHECK(length(trim(description))>0),
            reported_by uuid NOT NULL REFERENCES users(id),
            reported_at timestamptz NOT NULL DEFAULT now(),
            resolved_by uuid REFERENCES users(id),
            resolved_at timestamptz,
            resolution_notes varchar(1000),
            CHECK ((resolved_at IS NULL AND resolved_by IS NULL AND resolution_notes IS NULL)
                OR (resolved_at IS NOT NULL AND resolved_by IS NOT NULL AND length(trim(resolution_notes))>0))
        )
    """)
    op.execute("CREATE UNIQUE INDEX maintenance_one_open_issue ON maintenance_issues(room_id) WHERE resolved_at IS NULL")
    op.execute("""
        CREATE TABLE maintenance_events (
            id uuid PRIMARY KEY,
            issue_id uuid NOT NULL REFERENCES maintenance_issues(id),
            action varchar(20) NOT NULL CHECK(action IN ('reported','resolved')),
            notes varchar(1000) NOT NULL,
            actor_id uuid NOT NULL REFERENCES users(id),
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE TRIGGER maintenance_events_keep_history BEFORE UPDATE OR DELETE ON maintenance_events FOR EACH ROW EXECUTE FUNCTION protect_operating_history()")


def downgrade():
    raise RuntimeError("Review maintenance records before reversing this migration.")
