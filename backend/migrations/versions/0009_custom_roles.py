"""Owner-created role names and explicit application permissions."""
from alembic import op

revision = "0009_custom_roles"
down_revision = "0008_staff_access"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE roles (
            id uuid PRIMARY KEY,
            name varchar(80) NOT NULL CHECK (length(trim(name)) > 0 AND lower(trim(name)) <> 'owner'),
            permissions jsonb NOT NULL DEFAULT '[]'::jsonb
                CHECK (jsonb_typeof(permissions) = 'array'),
            created_by uuid REFERENCES users(id),
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE UNIQUE INDEX roles_name_key ON roles (lower(trim(name)))")
    op.execute("""
        INSERT INTO roles (id, name, permissions) VALUES
        ('10000000-0000-0000-0000-000000000001', 'Manager',
         '["rooms.view","rooms.ready","reservations.view","reservations.manage","stays.manage","payments.view","payments.record"]'),
        ('10000000-0000-0000-0000-000000000002', 'Receptionist',
         '["rooms.view","rooms.ready","reservations.view","reservations.manage","stays.manage","payments.view","payments.record"]'),
        ('10000000-0000-0000-0000-000000000003', 'Housekeeping',
         '["rooms.view","rooms.ready"]')
    """)
    op.execute("ALTER TABLE users ADD COLUMN role_id uuid REFERENCES roles(id)")
    op.execute("""
        UPDATE users SET role_id = CASE role
            WHEN 'manager' THEN '10000000-0000-0000-0000-000000000001'::uuid
            WHEN 'receptionist' THEN '10000000-0000-0000-0000-000000000002'::uuid
            WHEN 'housekeeping' THEN '10000000-0000-0000-0000-000000000003'::uuid
        END WHERE role <> 'owner'
    """)
    op.drop_constraint("users_role_check", "users", type_="check")
    op.execute("UPDATE users SET role='staff' WHERE role <> 'owner'")
    op.create_check_constraint("users_role_check", "users", "role IN ('owner','staff')")
    op.create_check_constraint("users_role_assignment_check", "users", "(role='owner' AND role_id IS NULL) OR (role='staff' AND role_id IS NOT NULL)")
    op.execute("CREATE INDEX users_role_id_idx ON users(role_id)")
    op.execute("""
        CREATE TABLE role_audit (
            id uuid PRIMARY KEY,
            owner_id uuid NOT NULL REFERENCES users(id),
            role_id uuid NOT NULL REFERENCES roles(id),
            action varchar(20) NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    # Staff re-login once so the website loads their explicit permission set.
    op.execute("DELETE FROM staff_sessions WHERE user_id IN (SELECT id FROM users WHERE role='staff')")


def downgrade():
    raise RuntimeError("Review custom roles and staff assignments before reversing this migration.")
