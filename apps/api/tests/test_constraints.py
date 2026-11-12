"""[MOCKED] Tests for instruction-based constraint extraction and P09 ESCALATE-only safety."""
import json

import httpx
import pytest

from mandate.constraints import constraints_to_dict, extract_constraints, extract_constraints_async
from mandate.models import Mandate
from mandate.policy import evaluate


def test_regex_constraint_extraction_extracts_width_and_unspecified():
    res = extract_constraints("Please buy a 160 cm standing desk in black")
    merged, failed = constraints_to_dict(res)
    assert failed is False
    assert merged["width_cm"] == 160
    assert merged["color"] == "black"

    unspec = extract_constraints("Buy a desk with specific width")
    merged_u, _ = constraints_to_dict(unspec)
    assert merged_u["width_cm"] == "unspecified"


@pytest.mark.asyncio
async def test_llm_constraint_extraction_falls_back_cleanly_mocked(monkeypatch):
    """[MOCKED] LLM extraction parses structured constraints and falls back to regex on failure."""
    monkeypatch.setenv("GROQ_API_KEY", "test-key")

    def ok_handler(_request):
        content = json.dumps({"constraints": [{"field": "width", "target_value": 160, "unit": "cm", "raw_mention": "160 cm"}]})
        return httpx.Response(200, json={"model": "openai/gpt-oss-20b", "choices": [{"message": {"content": content}}]})

    res = await extract_constraints_async("160 cm desk", transport=httpx.MockTransport(ok_handler))
    assert res.extraction_method == "llm_groq"
    assert res.llm_fallback is False
    assert constraints_to_dict(res)[0]["width_cm"] == 160

    def fail_handler(_request):
        return httpx.Response(503, text="unavailable")

    fallback = await extract_constraints_async("160 cm desk", transport=httpx.MockTransport(fail_handler))
    assert fallback.extraction_method == "regex_fallback"
    assert fallback.llm_fallback is True
    assert fallback.failed is False
    assert constraints_to_dict(fallback)[0]["width_cm"] == 160


def test_extraction_failure_or_mismatch_never_causes_deny(client, database):
    """Extracted constraint mismatches or failures may only push P09 to ESCALATE, never DENY."""
    grant = client.post("/api/mandates", json={
        "budget_cents": 50000,
        "per_transaction_cents": 50000,
        "allowed_categories": ["furniture"],
        "allowed_merchants": ["demo-merchant"],
        "constraints": {},
        "instruction": "Buy a 160 cm black standing desk",
        "expires_in_minutes": 60,
        "velocity_limit": 5,
    }).json()

    # desk-120 has width_cm=120 != extracted 160, and lacks color="black":
    # Because constraints came from extraction (not human-set grant.constraints), P09 must ESCALATE, never DENY!
    prop = client.post("/api/proposals", json={
        "mandate_id": grant["id"],
        "purchase_intent_id": "extract-escalate-only",
        "items": [{"product_id": "desk-120", "quantity": 1}],
        "currency": "USD",
        "instruction": "Buy a 160 cm black standing desk",
    }).json()
    assert prop["decision"] == "ESCALATE"
    p09 = next(r for r in prop["rules"] if r["id"] == "P09")
    assert p09["status"] == "ESCALATE"

    # Direct extraction_failed=True check in policy.evaluate pushes P09 to ESCALATE, never DENY
    with database() as db:
        grant_row = db.get(Mandate, grant["id"])
        decision, rules = evaluate(db, grant_row, {
            "items": [{"id": "desk-160", "product_id": "desk-160", "name": "160 cm standing desk",
                       "merchant_id": "demo-merchant", "category": "furniture",
                       "unit_price_cents": 34900, "currency": "USD", "attributes": {"width_cm": 160},
                       "recurring": False, "quantity": 1}],
            "total_cents": 34900, "currency": "USD", "merchant_id": "demo-merchant", "fees_cents": 0,
        }, [], extraction_failed=True)
        assert decision == "ESCALATE"
        assert next(r for r in rules if r["id"] == "P09")["status"] == "ESCALATE"

    # Human-set grant.constraints mismatch MUST still DENY
    strict_grant = client.post("/api/mandates", json={
        "budget_cents": 50000,
        "per_transaction_cents": 50000,
        "allowed_categories": ["furniture"],
        "allowed_merchants": ["demo-merchant"],
        "constraints": {"width_cm": 160},
        "instruction": "Buy a 160 cm desk",
        "expires_in_minutes": 60,
        "velocity_limit": 5,
    }).json()
    denied = client.post("/api/proposals", json={
        "mandate_id": strict_grant["id"],
        "purchase_intent_id": "human-constraint-deny",
        "items": [{"product_id": "desk-120", "quantity": 1}],
        "currency": "USD",
    }).json()
    assert denied["decision"] == "DENY"
    assert next(r for r in denied["rules"] if r["id"] == "P09")["status"] == "DENY"

