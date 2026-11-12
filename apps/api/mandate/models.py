from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def now():
    return datetime.now(timezone.utc)


def uid():
    return str(uuid4())


class Session(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String(80), primary_key=True, default=uid)
    csrf_token: Mapped[str] = mapped_column(String(100))
    token_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    operator_key: Mapped[str | None] = mapped_column(String(80), unique=True)
    authenticated: Mapped[bool] = mapped_column(default=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: now() + timedelta(hours=8))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    audit_head: Mapped[str] = mapped_column(String(64), default="0" * 64)
    audit_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Mandate(Base):
    __tablename__ = "mandates"
    __table_args__ = (CheckConstraint("spent_cents >= 0 AND reserved_cents >= 0 AND spent_cents + reserved_cents <= budget_cents"),)
    id: Mapped[str] = mapped_column(String(80), primary_key=True, default=uid)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="ACTIVE")
    budget_cents: Mapped[int] = mapped_column(Integer)
    per_transaction_cents: Mapped[int] = mapped_column(Integer)
    allowed_categories: Mapped[list] = mapped_column(JSON)
    allowed_merchants: Mapped[list] = mapped_column(JSON)
    constraints: Mapped[dict] = mapped_column(JSON)
    instruction: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    velocity_limit: Mapped[int] = mapped_column(Integer)
    spent_cents: Mapped[int] = mapped_column(Integer, default=0)
    reserved_cents: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Proposal(Base):
    __tablename__ = "proposals"
    __table_args__ = (UniqueConstraint("mandate_id", "purchase_intent_id"),)
    id: Mapped[str] = mapped_column(String(80), primary_key=True, default=uid)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    mandate_id: Mapped[str] = mapped_column(ForeignKey("mandates.id"), index=True)
    purchase_intent_id: Mapped[str] = mapped_column(String(120))
    payload_hash: Mapped[str] = mapped_column(String(64))
    cart: Mapped[dict] = mapped_column(JSON)
    cart_hash: Mapped[str] = mapped_column(String(64))
    grant_version: Mapped[int] = mapped_column(Integer)
    decision: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(30))
    rules: Mapped[list] = mapped_column(JSON)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    quote_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    human_approved: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (CheckConstraint("amount_cents > 0 AND refunded_cents >= 0 AND refund_reserved_cents >= 0 AND refunded_cents + refund_reserved_cents <= amount_cents"),)
    id: Mapped[str] = mapped_column(String(80), primary_key=True, default=uid)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    proposal_id: Mapped[str] = mapped_column(ForeignKey("proposals.id"), unique=True)
    mandate_id: Mapped[str] = mapped_column(ForeignKey("mandates.id"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="RESERVED")
    amount_cents: Mapped[int] = mapped_column(Integer)
    refunded_cents: Mapped[int] = mapped_column(Integer, default=0)
    refund_reserved_cents: Mapped[int] = mapped_column(Integer, default=0)
    provider_order_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    provider_capture_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    approval_url: Mapped[str | None] = mapped_column(Text)
    provider_status: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Operation(Base):
    __tablename__ = "operations"
    __table_args__ = (UniqueConstraint("payment_id", "kind", "entity_key"),)
    id: Mapped[str] = mapped_column(String(80), primary_key=True, default=uid)
    payment_id: Mapped[str] = mapped_column(ForeignKey("payments.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    entity_key: Mapped[str] = mapped_column(String(100), default="")
    request_id: Mapped[str] = mapped_column(String(80), default=uid, unique=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    request_payload: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(30), default="WAITING")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    result: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Case(Base):
    __tablename__ = "cases"
    id: Mapped[str] = mapped_column(String(80), primary_key=True, default=uid)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    payment_id: Mapped[str] = mapped_column(ForeignKey("payments.id"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="PROPOSED")
    cause: Mapped[str] = mapped_column(String(40))
    evidence: Mapped[str] = mapped_column(Text)
    offer_cents: Mapped[int] = mapped_column(Integer)
    offer_hash: Mapped[str] = mapped_column(String(64))
    explanation: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (UniqueConstraint("session_id", "sequence"),)
    id: Mapped[str] = mapped_column(String(80), primary_key=True, default=uid)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(60))
    entity_id: Mapped[str] = mapped_column(String(80))
    details: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    prev_hash: Mapped[str] = mapped_column(String(64))
    row_hash: Mapped[str] = mapped_column(String(64))


class ReconciliationLease(Base):
    __tablename__ = "reconciliation_leases"
    operation_id: Mapped[str] = mapped_column(ForeignKey("operations.id"), primary_key=True)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    lease_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class WebhookEvent(Base):
    __tablename__ = "webhook_events"
    provider_event_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict] = mapped_column(JSON)
    raw_body: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="VERIFIED")
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    attempts: Mapped[int] = mapped_column(Integer, default=0)


class RateLimitBucket(Base):
    __tablename__ = "rate_limit_buckets"
    key: Mapped[str] = mapped_column(String(160), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
