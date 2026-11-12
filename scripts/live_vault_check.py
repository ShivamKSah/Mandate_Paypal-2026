#!/usr/bin/env python3
"""Live PayPal Sandbox verification script for vaulted autonomous purchases.

Run manually by the operator; never executed by automated test suites.
Uses an isolated disposable PostgreSQL schema so dev/operator tables stay clean.
"""
import asyncio
import os
import re
import sys
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / ".env")

PAYPAL_TXN_ID_RE = re.compile(r"^[0-9A-Z]{17}$")
BANNED_MOCK_MARKERS = ("mock", "synthetic", "fake", "dummy", "test-token", "pinned", "order-pp", "capture-pp")


def mask_id(value: str | None) -> str:
    if not value or len(value) <= 4:
        return "****"
    return f"****{value[-4:]}"


def assert_real_paypal_id(value: str | None, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AssertionError(f"{label} is empty")
    cleaned = value.strip()
    lower = cleaned.lower()
    for marker in BANNED_MOCK_MARKERS:
        if marker in lower:
            raise AssertionError(f"{label} contains forbidden mock marker {marker!r}: {mask_id(cleaned)}")
    if not PAYPAL_TXN_ID_RE.match(cleaned):
        raise AssertionError(f"{label} does not match PayPal 17-char format: {mask_id(cleaned)}")
    return cleaned


def require_env():
    required = ("DATABASE_URL", "PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "PAYPAL_MERCHANT_ID", "VAULT_ENCRYPTION_KEY")
    missing = [name for name in required if not os.getenv(name, "").strip()]
    if missing:
        print("Missing required environment variables:", ", ".join(missing))
        sys.exit(1)
    if os.getenv("PAYPAL_ENV", "sandbox").lower() != "sandbox":
        print("Only PayPal sandbox is permitted.")
        sys.exit(1)


def main():
    require_env()
    os.environ["APP_ENV"] = "development"
    os.environ["APP_ACCESS_KEY"] = ""
    os.environ["COOKIE_SECURE"] = "false"
    os.environ.setdefault("PUBLIC_BASE_URL", "http://127.0.0.1:8000")

    from mandate import models
    from mandate.db import Base, get_db
    from mandate.main import app
    from mandate.payments.paypal import PayPalClient

    url = os.environ["DATABASE_URL"].replace("postgresql://", "postgresql+psycopg://", 1)
    admin = create_engine(url)
    schema = f"live_vault_{uuid4().hex[:16]}"
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)

    def isolated_db():
        with factory() as db:
            try:
                yield db
                db.commit()
            except Exception:
                db.rollback()
                raise

    app.dependency_overrides[get_db] = isolated_db
    app.state.testing = True

    try:
        with TestClient(app) as client:
            sess = client.get("/api/session").json()
            client.headers["X-CSRF-Token"] = sess["csrf_token"]

            print("1. Creating $500 spending mandate...")
            mandate = client.post("/api/mandates", json={
                "budget_cents": 50000,
                "per_transaction_cents": 50000,
                "allowed_categories": ["furniture"],
                "allowed_merchants": ["demo-merchant"],
                "constraints": {"width_cm": 160},
                "instruction": "160 cm standing desk",
                "expires_in_minutes": 60,
                "velocity_limit": 5,
            })
            mandate.raise_for_status()
            grant = mandate.json()
            print(f"   Mandate ID: {mask_id(grant['id'])}")

            print("2. Initiating $1.00 PayPal vault setup order...")
            init_resp = client.post(f"/api/mandates/{grant['id']}/grant/init", json={})
            init_resp.raise_for_status()
            init_data = init_resp.json()
            grant_order_id = assert_real_paypal_id(init_data.get("order_id"), "Grant order ID")
            approval_url = init_data["approval_url"]
            print(f"   Grant order ID: {mask_id(grant_order_id)}")
            print(f"   Open this sandbox approval URL and complete buyer approval:\n   {approval_url}\n")
            input("Press Enter after completing PayPal approval in the browser... ")

            print("3. Completing vault grant and refunding $1.00 authorization...")
            comp_resp = client.post(f"/api/mandates/{grant['id']}/grant/complete", json={"order_id": grant_order_id})
            comp_resp.raise_for_status()
            comp_data = comp_resp.json()
            print(f"   Vault status: {comp_data['vault_status']} | Masked vault: {comp_data.get('masked_vault_id')} | $1 refund: {comp_data['refund_status']}")

            print("4. Submitting $349.00 catalog proposal...")
            prop_resp = client.post("/api/proposals", json={
                "mandate_id": grant["id"],
                "purchase_intent_id": f"live-vault-{uuid4()}",
                "items": [{"product_id": "desk-160", "quantity": 1}],
                "currency": "USD",
            })
            prop_resp.raise_for_status()
            proposal = prop_resp.json()
            assert proposal["decision"] == "APPROVE", proposal
            payment_id = proposal["payment_id"]

            print("5. Executing autonomous vault-charge...")
            charge_resp = client.post(f"/api/payments/{payment_id}/vault-charge", json={})
            charge_resp.raise_for_status()
            payment = charge_resp.json()
            assert payment["status"] == "CAPTURED", payment
            order_id = assert_real_paypal_id(payment.get("provider_order_id"), "Charged order ID")
            capture_id = assert_real_paypal_id(payment.get("provider_capture_id"), "Capture ID")
            print(f"   Charged order: {mask_id(order_id)} | Capture: {mask_id(capture_id)} | Status: {payment['status']}")

            print("6. Confirming order via live PayPal GET...")
            async def fetch_order():
                async with PayPalClient() as pp:
                    return await pp.get_order(order_id)
            live_order = asyncio.run(fetch_order())
            assert live_order.get("status") == "COMPLETED", live_order
            print(f"   PayPal GET order status: {live_order.get('status')}")

            print("7. Executing partial refund via recovery case...")
            case_resp = client.post("/api/cases", json={
                "payment_id": payment_id,
                "cause": "seller_error",
                "evidence": "Live vault verification partial refund check",
                "avoided_freight_cents": 5000,
                "resale_loss_cents": 5000,
            })
            case_resp.raise_for_status()
            case = case_resp.json()
            acc_resp = client.post(f"/api/cases/{case['id']}/accept", json={"offer_hash": case["offer_hash"]})
            acc_resp.raise_for_status()
            accepted = acc_resp.json()
            assert accepted["status"] == "REFUNDED", accepted
            print(f"   Partial refund status: {accepted['status']} | Amount: {accepted['offer_cents']} cents")

            print("8. Verifying audit hash chain...")
            verify = client.get("/api/ledger/verify").json()
            assert verify["valid"] is True, verify
            print(f"   Audit chain valid={verify['valid']} events={verify['event_count']} checkpoint={mask_id(verify['checkpoint'])}")
    finally:
        app.dependency_overrides.clear()
        app.state.testing = False
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


if __name__ == "__main__":
    main()

