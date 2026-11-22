"""Unique product barcode assignments and immutable assignment history."""
from alembic import op
revision='0015_product_barcodes'
down_revision='0014_bar_pos'
branch_labels=None
depends_on=None

def upgrade():
    op.execute("ALTER TABLE inventory_products ADD COLUMN barcode varchar(80) UNIQUE CHECK(barcode IS NULL OR barcode ~ '^[!-~]{1,80}$')")
    op.execute('''CREATE TABLE product_barcode_changes (
        id uuid PRIMARY KEY,product_id uuid NOT NULL REFERENCES inventory_products(id),
        old_barcode varchar(80),new_barcode varchar(80),actor_id uuid NOT NULL REFERENCES users(id),
        created_at timestamptz NOT NULL DEFAULT now())''')
    op.execute('CREATE TRIGGER product_barcodes_keep_history BEFORE UPDATE OR DELETE ON product_barcode_changes FOR EACH ROW EXECUTE FUNCTION protect_operating_history()')

def downgrade():
    raise RuntimeError('Review barcode assignments before reverting.')
