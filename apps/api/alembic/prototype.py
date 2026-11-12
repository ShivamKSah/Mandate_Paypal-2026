"""Frozen schema of the unversioned October 2026 prototype."""
import sqlalchemy as sa


def prototype_metadata():
    metadata = sa.MetaData()
    sa.Table('sessions', metadata,
        sa.Column('id', sa.String(length=80), nullable=False),
        sa.Column('csrf_token', sa.String(length=100), nullable=False),
        sa.Column('audit_head', sa.String(length=64), nullable=False),
        sa.Column('audit_count', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    sa.Table('webhook_events', metadata,
        sa.Column('provider_event_id', sa.String(length=100), nullable=False),
        sa.Column('event_type', sa.String(length=100), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('verified_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('provider_event_id')
    )
    sa.Table('audit_events', metadata,
        sa.Column('id', sa.String(length=80), nullable=False),
        sa.Column('session_id', sa.String(length=80), nullable=False),
        sa.Column('sequence', sa.Integer(), nullable=False),
        sa.Column('event_type', sa.String(length=60), nullable=False),
        sa.Column('entity_id', sa.String(length=80), nullable=False),
        sa.Column('details', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('prev_hash', sa.String(length=64), nullable=False),
        sa.Column('row_hash', sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('session_id', 'sequence')
    )
    sa.Table('mandates', metadata,
        sa.Column('id', sa.String(length=80), nullable=False),
        sa.Column('session_id', sa.String(length=80), nullable=False),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('budget_cents', sa.Integer(), nullable=False),
        sa.Column('per_transaction_cents', sa.Integer(), nullable=False),
        sa.Column('allowed_categories', sa.JSON(), nullable=False),
        sa.Column('allowed_merchants', sa.JSON(), nullable=False),
        sa.Column('constraints', sa.JSON(), nullable=False),
        sa.Column('instruction', sa.Text(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('velocity_limit', sa.Integer(), nullable=False),
        sa.Column('spent_cents', sa.Integer(), nullable=False),
        sa.Column('reserved_cents', sa.Integer(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('spent_cents >= 0 AND reserved_cents >= 0 AND spent_cents + reserved_cents <= budget_cents'),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    sa.Table('proposals', metadata,
        sa.Column('id', sa.String(length=80), nullable=False),
        sa.Column('session_id', sa.String(length=80), nullable=False),
        sa.Column('mandate_id', sa.String(length=80), nullable=False),
        sa.Column('purchase_intent_id', sa.String(length=120), nullable=False),
        sa.Column('payload_hash', sa.String(length=64), nullable=False),
        sa.Column('cart', sa.JSON(), nullable=False),
        sa.Column('cart_hash', sa.String(length=64), nullable=False),
        sa.Column('grant_version', sa.Integer(), nullable=False),
        sa.Column('decision', sa.String(length=30), nullable=False),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('rules', sa.JSON(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('quote_expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('human_approved', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['mandate_id'], ['mandates.id'], ),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('mandate_id', 'purchase_intent_id')
    )
    sa.Table('payments', metadata,
        sa.Column('id', sa.String(length=80), nullable=False),
        sa.Column('session_id', sa.String(length=80), nullable=False),
        sa.Column('proposal_id', sa.String(length=80), nullable=False),
        sa.Column('mandate_id', sa.String(length=80), nullable=False),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('amount_cents', sa.Integer(), nullable=False),
        sa.Column('refunded_cents', sa.Integer(), nullable=False),
        sa.Column('refund_reserved_cents', sa.Integer(), nullable=False),
        sa.Column('provider_order_id', sa.String(length=100), nullable=True),
        sa.Column('provider_capture_id', sa.String(length=100), nullable=True),
        sa.Column('approval_url', sa.Text(), nullable=True),
        sa.Column('provider_status', sa.String(length=40), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('amount_cents > 0 AND refunded_cents >= 0 AND refund_reserved_cents >= 0 AND refunded_cents + refund_reserved_cents <= amount_cents'),
        sa.ForeignKeyConstraint(['mandate_id'], ['mandates.id'], ),
        sa.ForeignKeyConstraint(['proposal_id'], ['proposals.id'], ),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('proposal_id')
    )
    sa.Table('cases', metadata,
        sa.Column('id', sa.String(length=80), nullable=False),
        sa.Column('session_id', sa.String(length=80), nullable=False),
        sa.Column('payment_id', sa.String(length=80), nullable=False),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('cause', sa.String(length=40), nullable=False),
        sa.Column('evidence', sa.Text(), nullable=False),
        sa.Column('offer_cents', sa.Integer(), nullable=False),
        sa.Column('offer_hash', sa.String(length=64), nullable=False),
        sa.Column('explanation', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['payment_id'], ['payments.id'], ),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    sa.Table('operations', metadata,
        sa.Column('id', sa.String(length=80), nullable=False),
        sa.Column('payment_id', sa.String(length=80), nullable=False),
        sa.Column('kind', sa.String(length=30), nullable=False),
        sa.Column('entity_key', sa.String(length=100), nullable=False),
        sa.Column('request_id', sa.String(length=80), nullable=False),
        sa.Column('payload_hash', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('result', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['payment_id'], ['payments.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('payment_id', 'kind', 'entity_key'),
        sa.UniqueConstraint('request_id')
    )
    sa.Table('reconciliation_leases', metadata,
        sa.Column('operation_id', sa.String(length=80), nullable=False),
        sa.Column('available_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('lease_until', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['operation_id'], ['operations.id'], ),
        sa.PrimaryKeyConstraint('operation_id')
    )
    sa.Index('ix_audit_events_session_id', metadata.tables['audit_events'].c['session_id'], unique=False)
    sa.Index('ix_mandates_session_id', metadata.tables['mandates'].c['session_id'], unique=False)
    sa.Index('ix_proposals_mandate_id', metadata.tables['proposals'].c['mandate_id'], unique=False)
    sa.Index('ix_proposals_session_id', metadata.tables['proposals'].c['session_id'], unique=False)
    sa.Index('ix_payments_mandate_id', metadata.tables['payments'].c['mandate_id'], unique=False)
    sa.Index('ix_payments_session_id', metadata.tables['payments'].c['session_id'], unique=False)
    sa.Index('ix_cases_payment_id', metadata.tables['cases'].c['payment_id'], unique=False)
    sa.Index('ix_cases_session_id', metadata.tables['cases'].c['session_id'], unique=False)
    sa.Index('ix_operations_payment_id', metadata.tables['operations'].c['payment_id'], unique=False)
    return metadata
