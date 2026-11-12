"""Migrations touch only uniquely named disposable PostgreSQL schemas."""
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from mandate.migrate import ensure_schema_current, migrate, migration_config
from mandate_migrations.prototype import prototype_metadata


@pytest.fixture()
def migration_engine():
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL PostgreSQL is required for migration tests")
    url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    admin = create_engine(url)
    schema = "test_migrations_" + uuid4().hex
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def prototype(engine):
    with engine.begin() as connection:
        command.upgrade(migration_config(connection), "0001_prototype")
        connection.execute(text("DROP TABLE alembic_version"))


def seed_prototype(engine):
    tables = prototype_metadata().tables
    now = datetime.now(timezone.utc)
    records = {
        "sessions": dict(id="owner", csrf_token="old-cookie", audit_head="a" * 64, audit_count=1, created_at=now),
        "mandates": dict(id="grant", session_id="owner", status="ACTIVE", budget_cents=10000, per_transaction_cents=5000, allowed_categories=[], allowed_merchants=[], constraints={}, instruction="retained", expires_at=now, velocity_limit=4, spent_cents=2000, reserved_cents=3000, version=1, created_at=now),
        "proposals": dict(id="proposal", session_id="owner", mandate_id="grant", purchase_intent_id="intent", payload_hash="b" * 64, cart={}, cart_hash="c" * 64, grant_version=1, decision="APPROVE", status="APPROVED", rules=[], expires_at=now, quote_expires_at=now, human_approved=True, created_at=now),
        "payments": dict(id="payment", session_id="owner", proposal_id="proposal", mandate_id="grant", status="UNKNOWN", amount_cents=3000, refunded_cents=0, refund_reserved_cents=500, provider_order_id="order", provider_capture_id="capture", created_at=now),
        "operations": dict(id="operation", payment_id="payment", kind="CAPTURE", entity_key="", request_id="same-retry-key", payload_hash="d" * 64, status="UNKNOWN", attempts=2, result={"status": "PENDING"}, created_at=now),
        "cases": dict(id="case", session_id="owner", payment_id="payment", status="UNKNOWN", cause="seller_error", evidence="retained", offer_cents=500, offer_hash="e" * 64, explanation="retained", created_at=now),
        "audit_events": dict(id="audit", session_id="owner", sequence=1, event_type="RESERVED", entity_id="payment", details={"cents": 3000}, created_at=now, prev_hash="0" * 64, row_hash="a" * 64),
        "reconciliation_leases": dict(operation_id="operation", available_at=now, lease_until=now),
        "webhook_events": dict(provider_event_id="event", event_type="PAYMENT.CAPTURE.PENDING", payload={"id": "event"}, status="VERIFIED", verified_at=now),
    }
    with engine.begin() as connection:
        for name, values in records.items():
            connection.execute(tables[name].insert().values(**values))
    return records


def test_fresh_upgrade_matches_models_and_is_repeatable(migration_engine):
    with pytest.raises(RuntimeError, match="migrations are required"):
        ensure_schema_current(migration_engine)
    migrate(migration_engine)
    migrate(migration_engine)
    ensure_schema_current(migration_engine)


def test_adoption_preserves_money_operations_and_audit(migration_engine):
    prototype(migration_engine)
    records = seed_prototype(migration_engine)
    with pytest.raises(RuntimeError, match="explicit --adopt-prototype"):
        migrate(migration_engine)
    migrate(migration_engine, adopt_prototype=True)
    tables = prototype_metadata().tables
    with migration_engine.connect() as connection:
        for name, values in records.items():
            actual = connection.execute(tables[name].select()).mappings().one()
            assert all(actual[key] == value for key, value in values.items()), name
        session = connection.execute(text("SELECT token_hash, operator_key, authenticated, expires_at <= CURRENT_TIMESTAMP AS expired, revoked_at FROM sessions")).mappings().one()
        assert session["token_hash"] is None
        assert session["operator_key"] is None
        assert not session["authenticated"]
        assert session["expired"] and session["revoked_at"]
        assert connection.scalar(text("SELECT request_payload FROM operations")) is None
        webhook = connection.execute(text("SELECT available_at, attempts, raw_body FROM webhook_events")).mappings().one()
        assert webhook["available_at"] and webhook["attempts"] == 0 and webhook["raw_body"] is None
    ensure_schema_current(migration_engine)


def test_operator_workspace_is_unique_and_anonymous_sessions_remain_independent(migration_engine):
    migrate(migration_engine)
    insert = text("INSERT INTO sessions (id, csrf_token, audit_head, audit_count, created_at, authenticated, expires_at, operator_key) VALUES (:id, 'csrf', repeat('0', 64), 0, CURRENT_TIMESTAMP, false, CURRENT_TIMESTAMP, :operator_key)")
    with migration_engine.begin() as connection:
        connection.execute(insert, [
            {"id": "anonymous-one", "operator_key": None},
            {"id": "anonymous-two", "operator_key": None},
            {"id": "operator-workspace", "operator_key": "operator"},
        ])
    with pytest.raises(IntegrityError):
        with migration_engine.begin() as connection:
            connection.execute(insert, {"id": "duplicate-workspace", "operator_key": "operator"})
    with migration_engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM sessions")) == 3
        assert connection.scalar(text("SELECT id FROM sessions WHERE operator_key = 'operator'")) == "operator-workspace"


@pytest.mark.parametrize("change", [
    "ALTER TABLE payments DROP COLUMN refund_reserved_cents",
    "DROP INDEX ix_operations_payment_id",
    "ALTER TABLE audit_events DROP CONSTRAINT audit_events_session_id_sequence_key",
    "ALTER TABLE mandates DROP CONSTRAINT mandates_check",
])
def test_adoption_refuses_drift_without_stamping(migration_engine, change):
    prototype(migration_engine)
    with migration_engine.begin() as connection:
        connection.execute(text(change))
    with pytest.raises(RuntimeError, match="differ"):
        migrate(migration_engine, adopt_prototype=True)
    assert "alembic_version" not in inspect(migration_engine).get_table_names()


def test_failed_adoption_rolls_back_stamp_and_changes(migration_engine, monkeypatch):
    prototype(migration_engine)

    def fail_upgrade(config, revision):
        config.attributes["connection"].execute(text("ALTER TABLE sessions ADD COLUMN interrupted TEXT"))
        raise RuntimeError("interrupted")

    monkeypatch.setattr(command, "upgrade", fail_upgrade)
    with pytest.raises(RuntimeError, match="interrupted"):
        migrate(migration_engine, adopt_prototype=True)
    assert "alembic_version" not in inspect(migration_engine).get_table_names()
    assert "interrupted" not in {column["name"] for column in inspect(migration_engine).get_columns("sessions")}


@pytest.mark.parametrize("provider_column", ["provider_order_id", "provider_capture_id"])
def test_duplicate_provider_identity_blocks_adoption_atomically(migration_engine, provider_column):
    prototype(migration_engine)
    records = seed_prototype(migration_engine)
    tables = prototype_metadata().tables
    other_proposal = {**records["proposals"], "id": "other-proposal", "purchase_intent_id": "other-intent"}
    other_payment = {**records["payments"], "id": "other-payment", "proposal_id": "other-proposal", "provider_order_id": None, "provider_capture_id": None}
    other_payment[provider_column] = records["payments"][provider_column]
    with migration_engine.begin() as connection:
        connection.execute(tables["proposals"].insert().values(**other_proposal))
        connection.execute(tables["payments"].insert().values(**other_payment))
    with pytest.raises(IntegrityError):
        migrate(migration_engine, adopt_prototype=True)
    assert "alembic_version" not in inspect(migration_engine).get_table_names()
    assert "token_hash" not in {column["name"] for column in inspect(migration_engine).get_columns("sessions")}
    with migration_engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM payments")) == 2
        assert connection.scalar(text("SELECT reserved_cents FROM mandates")) == 3000


def test_startup_detects_drift_without_repairing(migration_engine):
    migrate(migration_engine)
    with migration_engine.begin() as connection:
        connection.execute(text("ALTER TABLE operations DROP COLUMN request_payload"))
    with pytest.raises(RuntimeError, match="differs"):
        ensure_schema_current(migration_engine)
    assert "request_payload" not in {column["name"] for column in inspect(migration_engine).get_columns("operations")}


def test_adoption_requires_validated_accounting_checks(migration_engine):
    prototype(migration_engine)
    with migration_engine.begin() as connection:
        connection.execute(text("ALTER TABLE mandates DROP CONSTRAINT mandates_check"))
        connection.execute(text("ALTER TABLE mandates ADD CHECK (spent_cents >= 0 AND reserved_cents >= 0 AND spent_cents + reserved_cents <= budget_cents) NOT VALID"))
    with pytest.raises(RuntimeError, match="unvalidated"):
        migrate(migration_engine, adopt_prototype=True)
    assert "alembic_version" not in inspect(migration_engine).get_table_names()


def test_migration_lock_serializes_concurrent_launches(migration_engine):
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: migrate(migration_engine), range(2)))
    ensure_schema_current(migration_engine)


def test_cli_redacts_database_errors(monkeypatch, capsys):
    import mandate.migrate as migrations

    def database_failure(*args, **kwargs):
        raise RuntimeError("postgresql://user:secret-password@private-host/db")

    monkeypatch.setattr(migrations, "migrate", database_failure)
    monkeypatch.setattr("sys.argv", ["mandate.migrate"])
    with pytest.raises(SystemExit) as error:
        migrations.main()
    assert error.value.code == 1
    output = capsys.readouterr()
    assert "Migration failed" in output.err
    assert "secret-password" not in output.err + output.out


def test_cli_reports_safe_schema_remediation(monkeypatch, capsys):
    import mandate.migrate as migrations

    def unversioned(*args, **kwargs):
        raise migrations.SchemaStateError("Existing unversioned database requires backup and explicit --adopt-prototype")

    monkeypatch.setattr(migrations, "migrate", unversioned)
    monkeypatch.setattr("sys.argv", ["mandate.migrate"])
    with pytest.raises(SystemExit) as error:
        migrations.main()
    assert error.value.code == 1
    assert "backup and explicit --adopt-prototype" in capsys.readouterr().err
