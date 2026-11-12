#!/usr/bin/env python3
"""Synthetic policy evaluation benchmark (50 attacks + 50 legitimate carts).

Runs offline against an isolated disposable PostgreSQL schema without calling PayPal or any LLM.
Never touches development or demo schemas/tables.
"""
from datetime import timedelta
import json
import math
import os
from pathlib import Path
import time
from uuid import uuid4

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / ".env")

# Never call live LLMs or providers during scripted evaluations.
os.environ["GROQ_API_KEY"] = ""
os.environ["LLM_API_KEY"] = ""
os.environ["PAYPAL_CLIENT_ID"] = ""
os.environ["PAYPAL_CLIENT_SECRET"] = ""

from mandate import models  # noqa: E402
from mandate.catalog import quote  # noqa: E402
from mandate.db import Base  # noqa: E402
from mandate.models import Mandate, Session as DBSessionModel, now  # noqa: E402
from mandate.policy import evaluate  # noqa: E402
from mandate.schemas import ItemInput  # noqa: E402


def wilson_interval(successes: int, total: int, z: float = 1.96) -> dict[str, float]:
    if total == 0:
        return {"rate": 0.0, "ci_lower": 0.0, "ci_upper": 0.0}
    p = successes / total
    denom = 1 + (z ** 2) / total
    center = (p + (z ** 2) / (2 * total)) / denom
    spread = z * math.sqrt((p * (1 - p) + (z ** 2) / (4 * total)) / total) / denom
    return {
        "rate": round(p * 100, 2),
        "ci_lower": round(max(0.0, center - spread) * 100, 2),
        "ci_upper": round(min(1.0, center + spread) * 100, 2),
    }


def _make_grant(db, owner_id: str, *, budget_cents=200000, per_transaction_cents=50000, constraints=None):
    grant = Mandate(
        session_id=owner_id,
        status="ACTIVE",
        budget_cents=budget_cents,
        per_transaction_cents=per_transaction_cents,
        allowed_categories=["furniture", "electronics"],
        allowed_merchants=["demo-merchant"],
        constraints=constraints if constraints is not None else {"width_cm": 160},
        instruction="Synthetic eval grant",
        expires_at=now() + timedelta(hours=2),
        velocity_limit=100,
    )
    db.add(grant)
    db.flush()
    return grant


def build_scenarios():
    attacks = []
    for i in range(8):
        attacks.append({
            "scenario": f"over_budget_{i + 1}", "category": "over_budget",
            "grant_budget": 30000, "grant_cap": 50000, "product_id": "desk-160", "quantity": 1,
        })
    for i in range(8):
        attacks.append({
            "scenario": f"over_cap_{i + 1}", "category": "over_cap",
            "grant_budget": 200000, "grant_cap": 30000, "product_id": "desk-160", "quantity": 1,
        })
    for i in range(8):
        attacks.append({
            "scenario": f"off_list_merchant_{i + 1}", "category": "off_list_merchant",
            "custom_cart": {
                "items": [{"id": "keyboard", "product_id": "keyboard", "name": "Mechanical keyboard",
                           "merchant_id": f"rogue-vendor-{i}", "category": "electronics",
                           "unit_price_cents": 8900, "currency": "USD", "attributes": {}, "recurring": False, "quantity": 1}],
                "total_cents": 8900, "currency": "USD", "merchant_id": f"rogue-vendor-{i}", "fees_cents": 0,
            },
        })
    for i in range(6):
        attacks.append({
            "scenario": f"lookalike_merchant_{i + 1}", "category": "lookalike_merchant",
            "custom_cart": {
                "items": [{"id": "keyboard", "product_id": "keyboard", "name": "Mechanical keyboard",
                           "merchant_id": f"demo-merchant-official-{i}", "category": "electronics",
                           "unit_price_cents": 8900, "currency": "USD", "attributes": {}, "recurring": False, "quantity": 1}],
                "total_cents": 8900, "currency": "USD", "merchant_id": f"demo-merchant-official-{i}", "fees_cents": 0,
            },
        })
    for i in range(5):
        attacks.append({
            "scenario": f"mislabeled_category_{i + 1}", "category": "mislabeled_category",
            "custom_cart": {
                "items": [{"id": f"gift-card-{i}", "product_id": f"gift-card-{i}", "name": "Digital Gift Card",
                           "merchant_id": "demo-merchant", "category": "gift_cards",
                           "unit_price_cents": 5000, "currency": "USD", "attributes": {}, "recurring": False, "quantity": 1}],
                "total_cents": 5000, "currency": "USD", "merchant_id": "demo-merchant", "fees_cents": 0,
            },
        })
    for i in range(5):
        attacks.append({
            "scenario": f"inflated_price_{i + 1}", "category": "inflated_price",
            "product_id": "keyboard", "quantity": 1, "claimed_total_cents": 12000 + i * 500,
        })
    for i in range(5):
        attacks.append({
            "scenario": f"currency_swap_{i + 1}", "category": "currency_swap",
            "product_id": "keyboard", "quantity": 1, "currency": "EUR",
        })
    for i in range(5):
        attacks.append({
            "scenario": f"subscription_upsell_{i + 1}", "category": "subscription_upsell",
            "product_id": "subscription", "quantity": 1,
        })
    assert len(attacks) == 50

    legitimate = []
    for i in range(25):
        legitimate.append({
            "scenario": f"legit_keyboard_{i + 1}", "product_id": "keyboard", "quantity": 1,
            "grant_budget": 200000, "grant_cap": 50000, "constraints": {},
            "note": "Approved electronics within budget and below 80% cap",
        })
    for i in range(15):
        legitimate.append({
            "scenario": f"legit_desk_160_{i + 1}", "product_id": "desk-160", "quantity": 1,
            "grant_budget": 200000, "grant_cap": 50000, "constraints": {"width_cm": 160},
            "note": "Approved 160 cm desk matching constraint and <= 80% of $500 cap",
        })
    for i in range(5):
        legitimate.append({
            "scenario": f"legit_desk_missing_width_{i + 1}", "product_id": "desk-unknown", "quantity": 1,
            "grant_budget": 200000, "grant_cap": 50000, "constraints": {"width_cm": 160},
            "note": "Missing width_cm attribute on catalog item triggers P09 human review",
        })
    for i in range(5):
        legitimate.append({
            "scenario": f"legit_desk_near_cap_{i + 1}", "product_id": "desk-160", "quantity": 1,
            "grant_budget": 200000, "grant_cap": 40000, "constraints": {"width_cm": 160},
            "note": "$349 exceeds 80% of $400 cap ($320), triggering P11 human review",
        })
    assert len(legitimate) == 50
    return attacks, legitimate


def main():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL PostgreSQL is required for run_evals.py")
    url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    admin = create_engine(url)
    schema = f"eval_{uuid4().hex[:16]}"
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)

    try:
        attacks, legitimate = build_scenarios()
        latencies_ms: list[float] = []
        attacks_blocked = 0
        attacks_breached = 0
        false_positives = 0
        legit_approved = 0
        legit_escalated = 0
        escalated_details = []

        with factory() as db, db.begin():
            owner = DBSessionModel(csrf_token="eval-csrf")
            db.add(owner)
            db.flush()

            for atk in attacks:
                sp = db.begin_nested()
                grant = _make_grant(
                    db, owner.id,
                    budget_cents=atk.get("grant_budget", 200000),
                    per_transaction_cents=atk.get("grant_cap", 50000),
                    constraints={},
                )
                if "custom_cart" in atk:
                    cart, missing = atk["custom_cart"], []
                else:
                    cart, missing = quote(
                        [ItemInput(product_id=atk["product_id"], quantity=atk["quantity"])],
                        atk.get("currency", "USD"),
                    )
                t0 = time.perf_counter()
                decision, _rules = evaluate(db, grant, cart, missing, claimed_total=atk.get("claimed_total_cents"))
                latencies_ms.append((time.perf_counter() - t0) * 1000.0)
                sp.rollback()
                if decision == "APPROVE":
                    attacks_breached += 1
                else:
                    attacks_blocked += 1

            for leg in legitimate:
                sp = db.begin_nested()
                grant = _make_grant(
                    db, owner.id,
                    budget_cents=leg["grant_budget"],
                    per_transaction_cents=leg["grant_cap"],
                    constraints=leg["constraints"],
                )
                cart, missing = quote([ItemInput(product_id=leg["product_id"], quantity=leg["quantity"])], "USD")
                t0 = time.perf_counter()
                decision, rules = evaluate(db, grant, cart, missing)
                latencies_ms.append((time.perf_counter() - t0) * 1000.0)
                sp.rollback()
                if decision == "DENY":
                    false_positives += 1
                elif decision == "APPROVE":
                    legit_approved += 1
                else:
                    legit_escalated += 1
                    reasons = [f"{r['id']}: {r['message']}" for r in rules if r["status"] == "ESCALATE"]
                    escalated_details.append({"scenario": leg["scenario"], "product_id": leg["product_id"], "reasons": reasons})

        latencies_ms.sort()
        p50 = latencies_ms[len(latencies_ms) // 2]
        p95 = latencies_ms[int(len(latencies_ms) * 0.95)]
        block_stats = wilson_interval(attacks_blocked, len(attacks))
        fp_stats = wilson_interval(false_positives, len(legitimate))
        esc_stats = wilson_interval(legit_escalated, len(legitimate))

        results = {
            "label": "Synthetic: scripted scenarios written by the author",
            "benchmark_date": now().isoformat(),
            "sample_size": {
                "total_evaluations": len(attacks) + len(legitimate),
                "attack_scenarios": len(attacks),
                "legitimate_purchases": len(legitimate),
            },
            "summary": {
                "attacks_blocked": f"{attacks_blocked} of {len(attacks)} blocked (95% CI {block_stats['ci_lower']}-{block_stats['ci_upper']}%)",
                "false_positives": f"{false_positives} of {len(legitimate)} false positives (95% CI {fp_stats['ci_lower']}-{fp_stats['ci_upper']}%)",
                "escalate_on_legitimate": f"{legit_escalated} of {len(legitimate)} escalated (95% CI {esc_stats['ci_lower']}-{esc_stats['ci_upper']}%)",
            },
            "metrics": {
                "block_rate_pct": block_stats["rate"],
                "block_rate_95ci": [block_stats["ci_lower"], block_stats["ci_upper"]],
                "false_positive_rate_pct": fp_stats["rate"],
                "false_positive_rate_95ci": [fp_stats["ci_lower"], fp_stats["ci_upper"]],
                "escalate_on_legitimate_pct": esc_stats["rate"],
                "escalate_on_legitimate_95ci": [esc_stats["ci_lower"], esc_stats["ci_upper"]],
                "attacks_blocked_count": attacks_blocked,
                "attacks_breached_count": attacks_breached,
                "approved_legitimate_count": legit_approved,
                "escalated_legitimate_count": legit_escalated,
                "false_positive_count": false_positives,
            },
            "escalated_legitimate_scenarios": escalated_details,
            "latency_ms": {
                "p50": round(p50, 3),
                "p95": round(p95, 3),
                "mean": round(sum(latencies_ms) / len(latencies_ms), 3),
            },
        }
        out_path = REPO_ROOT / "eval_results.json"
        out_path.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")

        print(results["label"])
        print(results["summary"]["attacks_blocked"])
        print(results["summary"]["false_positives"])
        print(results["summary"]["escalate_on_legitimate"])
        print(f"Latency p50={results['latency_ms']['p50']} ms, p95={results['latency_ms']['p95']} ms")
        print(f"Wrote {out_path}")
    finally:
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


if __name__ == "__main__":
    main()

