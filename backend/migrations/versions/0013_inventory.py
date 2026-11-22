"""Products and immutable stock movement ledger."""
from alembic import op
revision='0013_inventory'
down_revision='0012_room_maintenance'
branch_labels=None
depends_on=None

def upgrade():
    op.execute('''CREATE TABLE inventory_products (
        id uuid PRIMARY KEY, name varchar(120) NOT NULL CHECK(length(trim(name))>0),
        unit varchar(30) NOT NULL CHECK(length(trim(unit))>0),
        reorder_level integer NOT NULL CHECK(reorder_level>=0),
        created_by uuid NOT NULL REFERENCES users(id), created_at timestamptz NOT NULL DEFAULT now()
    )''')
    op.execute('CREATE UNIQUE INDEX inventory_product_name ON inventory_products(lower(name))')
    op.execute('''CREATE TABLE inventory_movements (
        id uuid PRIMARY KEY, product_id uuid NOT NULL REFERENCES inventory_products(id),
        kind varchar(20) NOT NULL CHECK(kind IN ('purchase','wastage','count')),
        quantity integer NOT NULL CHECK(quantity>=0), delta integer NOT NULL,
        balance integer NOT NULL CHECK(balance>=0), unit_cost numeric(12,0),
        supplier varchar(160), notes varchar(1000) NOT NULL,
        occurred_on date NOT NULL, actor_id uuid NOT NULL REFERENCES users(id),
        created_at timestamptz NOT NULL DEFAULT now(),
        CHECK((kind='purchase' AND quantity>0 AND delta=quantity AND unit_cost>=0 AND supplier IS NOT NULL)
           OR (kind='wastage' AND quantity>0 AND delta=-quantity AND unit_cost IS NULL)
           OR (kind='count' AND unit_cost IS NULL))
    )''')
    op.execute('CREATE INDEX inventory_movements_product ON inventory_movements(product_id,created_at)')
    op.execute('CREATE TRIGGER inventory_keep_history BEFORE UPDATE OR DELETE ON inventory_movements FOR EACH ROW EXECUTE FUNCTION protect_operating_history()')

def downgrade():
    raise RuntimeError('Review stock history before reverting inventory.')
