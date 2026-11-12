"""Frozen initial prototype schema, also the explicit adoption baseline."""
from alembic import op
from mandate_migrations.prototype import prototype_metadata

revision = "0001_prototype"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    for table in prototype_metadata().sorted_tables:
        table.create(op.get_bind())


def downgrade():
    raise RuntimeError("Destructive downgrades are disabled; restore a verified backup instead")
