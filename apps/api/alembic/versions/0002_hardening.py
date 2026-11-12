"""Opaque session credentials, durable provider payloads, and shared rate limits."""
from alembic import op
import sqlalchemy as sa

revision = "0002_hardening"
down_revision = "0001_prototype"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("sessions", sa.Column("token_hash", sa.String(64), nullable=True))
    op.create_unique_constraint("uq_sessions_token_hash", "sessions", ["token_hash"])
    op.add_column("sessions", sa.Column("operator_key", sa.String(80), nullable=True))
    op.create_unique_constraint("uq_sessions_operator_key", "sessions", ["operator_key"])
    # Old session IDs were bearer cookies. Expire access while retaining owned financial records.
    op.add_column("sessions", sa.Column("authenticated", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("sessions", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.add_column("sessions", sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE sessions SET revoked_at = CURRENT_TIMESTAMP")
    op.alter_column("sessions", "authenticated", server_default=None)
    op.alter_column("sessions", "expires_at", server_default=None)
    op.add_column("operations", sa.Column("request_payload", sa.JSON(), nullable=True))
    op.add_column("webhook_events", sa.Column("raw_body", sa.Text(), nullable=True))
    op.add_column("webhook_events", sa.Column("available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.add_column("webhook_events", sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"))
    op.alter_column("webhook_events", "available_at", server_default=None)
    op.alter_column("webhook_events", "attempts", server_default=None)
    op.create_unique_constraint("uq_payments_provider_order_id", "payments", ["provider_order_id"])
    op.create_unique_constraint("uq_payments_provider_capture_id", "payments", ["provider_capture_id"])
    op.create_table(
        "rate_limit_buckets",
        sa.Column("key", sa.String(160), primary_key=True),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_rate_limit_buckets_expires_at", "rate_limit_buckets", ["expires_at"])


def downgrade():
    raise RuntimeError("Security and financial history downgrades are disabled; restore a verified backup instead")
