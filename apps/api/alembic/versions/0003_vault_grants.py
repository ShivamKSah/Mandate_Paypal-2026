"""Add vault grant status, encrypted token reference, and setup order ID to mandates."""
from alembic import op
import sqlalchemy as sa

revision = "0003_vault_grants"
down_revision = "0002_hardening"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("mandates", sa.Column("vault_status", sa.String(20), nullable=False, server_default="NONE"))
    op.add_column("mandates", sa.Column("vault_token_ref", sa.Text(), nullable=True))
    op.add_column("mandates", sa.Column("grant_order_id", sa.String(100), nullable=True))
    op.alter_column("mandates", "vault_status", server_default=None)


def downgrade():
    raise RuntimeError("Security and financial history downgrades are disabled; restore a verified backup instead")

