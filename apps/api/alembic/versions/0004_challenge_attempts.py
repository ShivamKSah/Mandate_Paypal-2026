"""Add challenge_attempts table for Break-the-Mandate attack tracking."""
from alembic import op
import sqlalchemy as sa

revision = "0004_challenge_attempts"
down_revision = "0003_vault_grants"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "challenge_attempts",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("session_id", sa.String(80), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("attack_id", sa.String(60), nullable=False),
        sa.Column("verdict", sa.String(30), nullable=False),
        sa.Column("expected_rule", sa.String(40), nullable=False),
        sa.Column("actual_rule", sa.String(40), nullable=False),
        sa.Column("rules", sa.JSON(), nullable=False),
        sa.Column("breached", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_challenge_attempts_session_id", "challenge_attempts", ["session_id"])


def downgrade():
    raise RuntimeError("Security and financial history downgrades are disabled; restore a verified backup instead")

