"""Break-the-Mandate adversarial attack simulator and challenge counter."""
from datetime import timedelta
import json
import logging
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from .audit import append, digest
from .db import get_db
from .models import ChallengeAttempt, Mandate, Payment, Proposal, now
from .policy import evaluate
from .proposals import approve as approve_proposal, submit as submit_proposal
from .rate_limits import consume
from .schemas import ApprovalInput, AttackRunInput, ItemInput, ProposalInput
from .security import human

logger = logging.getLogger("mandate.attacks")

router = APIRouter(prefix="/api")

ATTACK_CATALOG = [
    {"id": "over_budget", "expected_rule": "P02", "title": "Over remaining budget",
     "description": "Cart total exceeds remaining grant budget."},
    {"id": "over_cap", "expected_rule": "P03", "title": "Over transaction cap",
     "description": "Cart total exceeds per-transaction cap."},
    {"id": "off_list_merchant", "expected_rule": "P04", "title": "Off-list merchant",
     "description": "Cart routes funds to an unapproved merchant."},
    {"id": "lookalike_merchant", "expected_rule": "P04", "title": "Lookalike merchant",
     "description": "Cart uses a typosquatted vendor name."},
    {"id": "mislabeled_category", "expected_rule": "P05", "title": "Disallowed category",
     "description": "Item belongs to an unapproved category (gift cards)."},
    {"id": "inflated_price", "expected_rule": "P06", "title": "Inflated price claim",
     "description": "Claimed total diverges from canonical catalog quote."},
    {"id": "hidden_line_item", "expected_rule": "P06", "title": "Hidden phantom line item",
     "description": "Cart injects an uncataloged phantom product."},
    {"id": "quantity_inflation", "expected_rule": "P06", "title": "Quantity/total mismatch",
     "description": "Claimed total does not reconcile with item quantity."},
    {"id": "currency_swap", "expected_rule": "P06", "title": "Currency swap (EUR)",
     "description": "Cart swaps settlement currency from USD to EUR."},
    {"id": "expired_mandate", "expected_rule": "P01", "title": "Expired grant",
     "description": "Purchase submitted after the grant expiration window."},
    {"id": "revoked_mandate", "expected_rule": "P01", "title": "Revoked grant",
     "description": "Purchase submitted against a revoked grant."},
    {"id": "velocity_burst", "expected_rule": "P07", "title": "Velocity burst",
     "description": "Purchase burst exceeds hourly velocity limit."},
    {"id": "duplicate_replay", "expected_rule": "P11", "title": "Duplicate replay",
     "description": "Identical cart replayed within the duplicate review window."},
    {"id": "subscription_upsell", "expected_rule": "P10", "title": "Recurring subscription",
     "description": "Recurring subscription injected against non-recurring policy."},
    {"id": "cart_swap_after_approval", "expected_rule": "CART_HASH_BINDING", "title": "Post-approval cart swap",
     "description": "Cart payload modified after policy evaluation; hash binding rejects execution."},
]
ATTACK_INDEX = {item["id"]: item for item in ATTACK_CATALOG}


def _sim_grant(
    db,
    owner,
    *,
    status="ACTIVE",
    budget_cents=50000,
    per_transaction_cents=50000,
    allowed_categories=None,
    allowed_merchants=None,
    constraints=None,
    expires_delta=timedelta(minutes=60),
    velocity_limit=5,
):
    grant = Mandate(
        session_id=owner.id,
        status=status,
        budget_cents=budget_cents,
        per_transaction_cents=per_transaction_cents,
        allowed_categories=allowed_categories or ["furniture", "electronics"],
        allowed_merchants=allowed_merchants or ["demo-merchant"],
        constraints=constraints or {},
        instruction="Isolated Break-the-Mandate simulation grant",
        expires_at=now() + expires_delta,
        velocity_limit=velocity_limit,
    )
    db.add(grant)
    db.flush()
    return grant


def _pick_actual_rule(expected_rule: str, verdict: str, rules: list[dict]) -> str:
    if verdict == "APPROVE":
        return "NONE"
    for rule in rules:
        if rule.get("id") == expected_rule and rule.get("status") in {"DENY", "ESCALATE"}:
            return expected_rule
    for rule in rules:
        if rule.get("status") in {"DENY", "ESCALATE"}:
            return str(rule.get("id", "UNKNOWN"))
    return "NONE"


def _evaluate_attack(db, owner, attack_id: str):
    meta = ATTACK_INDEX.get(attack_id)
    if meta is None:
        raise HTTPException(400, f"Unknown attack_id '{attack_id}'")
    expected_rule = meta["expected_rule"]
    savepoint = db.begin_nested()
    verdict = "DENY"
    rules: list[dict] = []
    actual_rule = "NONE"
    try:
        if attack_id == "over_budget":
            grant = _sim_grant(db, owner, budget_cents=20000, per_transaction_cents=40000)
            proposal = submit_proposal(db, owner, ProposalInput(
                mandate_id=grant.id, purchase_intent_id=f"atk-{uuid4()}",
                items=[ItemInput(product_id="desk-160", quantity=1)], currency="USD",
            ))
            verdict, rules = proposal.decision, proposal.rules
        elif attack_id == "over_cap":
            grant = _sim_grant(db, owner, budget_cents=50000, per_transaction_cents=20000)
            proposal = submit_proposal(db, owner, ProposalInput(
                mandate_id=grant.id, purchase_intent_id=f"atk-{uuid4()}",
                items=[ItemInput(product_id="desk-160", quantity=1)], currency="USD",
            ))
            verdict, rules = proposal.decision, proposal.rules
        elif attack_id in {"off_list_merchant", "lookalike_merchant"}:
            grant = _sim_grant(db, owner)
            merchant = "rogue-merchant-999" if attack_id == "off_list_merchant" else "demo-merchant-official"
            cart = {
                "items": [{"id": "keyboard", "product_id": "keyboard", "name": "Mechanical keyboard",
                           "merchant_id": merchant, "category": "electronics",
                           "unit_price_cents": 8900, "currency": "USD", "attributes": {}, "recurring": False, "quantity": 1}],
                "total_cents": 8900, "currency": "USD", "merchant_id": merchant, "fees_cents": 0,
            }
            verdict, rules = evaluate(db, grant, cart, [])
        elif attack_id == "mislabeled_category":
            grant = _sim_grant(db, owner)
            cart = {
                "items": [{"id": "gift-card-sim", "product_id": "gift-card-sim", "name": "Digital gift card",
                           "merchant_id": "demo-merchant", "category": "gift_cards",
                           "unit_price_cents": 5000, "currency": "USD", "attributes": {}, "recurring": False, "quantity": 1}],
                "total_cents": 5000, "currency": "USD", "merchant_id": "demo-merchant", "fees_cents": 0,
            }
            verdict, rules = evaluate(db, grant, cart, [])
        elif attack_id == "inflated_price":
            grant = _sim_grant(db, owner)
            proposal = submit_proposal(db, owner, ProposalInput(
                mandate_id=grant.id, purchase_intent_id=f"atk-{uuid4()}",
                items=[ItemInput(product_id="keyboard", quantity=1)], currency="USD", claimed_total_cents=14900,
            ))
            verdict, rules = proposal.decision, proposal.rules
        elif attack_id == "hidden_line_item":
            grant = _sim_grant(db, owner)
            proposal = submit_proposal(db, owner, ProposalInput(
                mandate_id=grant.id, purchase_intent_id=f"atk-{uuid4()}",
                items=[ItemInput(product_id="keyboard", quantity=1), ItemInput(product_id="phantom-vip-fee", quantity=1)],
                currency="USD",
            ))
            verdict, rules = proposal.decision, proposal.rules
        elif attack_id == "quantity_inflation":
            grant = _sim_grant(db, owner)
            proposal = submit_proposal(db, owner, ProposalInput(
                mandate_id=grant.id, purchase_intent_id=f"atk-{uuid4()}",
                items=[ItemInput(product_id="keyboard", quantity=2)], currency="USD", claimed_total_cents=8900,
            ))
            verdict, rules = proposal.decision, proposal.rules
        elif attack_id == "currency_swap":
            grant = _sim_grant(db, owner)
            proposal = submit_proposal(db, owner, ProposalInput(
                mandate_id=grant.id, purchase_intent_id=f"atk-{uuid4()}",
                items=[ItemInput(product_id="keyboard", quantity=1)], currency="EUR",
            ))
            verdict, rules = proposal.decision, proposal.rules
        elif attack_id == "expired_mandate":
            grant = _sim_grant(db, owner, expires_delta=timedelta(minutes=-5))
            proposal = submit_proposal(db, owner, ProposalInput(
                mandate_id=grant.id, purchase_intent_id=f"atk-{uuid4()}",
                items=[ItemInput(product_id="keyboard", quantity=1)], currency="USD",
            ))
            verdict, rules = proposal.decision, proposal.rules
        elif attack_id == "revoked_mandate":
            grant = _sim_grant(db, owner, status="REVOKED")
            proposal = submit_proposal(db, owner, ProposalInput(
                mandate_id=grant.id, purchase_intent_id=f"atk-{uuid4()}",
                items=[ItemInput(product_id="keyboard", quantity=1)], currency="USD",
            ))
            verdict, rules = proposal.decision, proposal.rules
        elif attack_id == "velocity_burst":
            grant = _sim_grant(db, owner, velocity_limit=2)
            for idx in range(2):
                prior = Proposal(
                    session_id=owner.id, mandate_id=grant.id, purchase_intent_id=f"seed-{idx}-{uuid4()}",
                    payload_hash="0" * 64, cart={"items": [], "total_cents": 8900, "currency": "USD"},
                    cart_hash=f"{idx}" * 64, grant_version=1, decision="APPROVE", status="APPROVED",
                    rules=[], expires_at=now() + timedelta(minutes=5), quote_expires_at=now() + timedelta(seconds=60),
                )
                db.add(prior)
                db.flush()
                db.add(Payment(session_id=owner.id, mandate_id=grant.id, proposal_id=prior.id, amount_cents=8900, status="CAPTURED"))
            db.flush()
            proposal = submit_proposal(db, owner, ProposalInput(
                mandate_id=grant.id, purchase_intent_id=f"atk-{uuid4()}",
                items=[ItemInput(product_id="keyboard", quantity=1)], currency="USD",
            ))
            verdict, rules = proposal.decision, proposal.rules
        elif attack_id == "duplicate_replay":
            grant = _sim_grant(db, owner)
            submit_proposal(db, owner, ProposalInput(
                mandate_id=grant.id, purchase_intent_id=f"atk-first-{uuid4()}",
                items=[ItemInput(product_id="keyboard", quantity=1)], currency="USD",
            ))
            replay = submit_proposal(db, owner, ProposalInput(
                mandate_id=grant.id, purchase_intent_id=f"atk-replay-{uuid4()}",
                items=[ItemInput(product_id="keyboard", quantity=1)], currency="USD",
            ))
            verdict, rules = replay.decision, replay.rules
        elif attack_id == "subscription_upsell":
            grant = _sim_grant(db, owner, allowed_categories=["furniture", "electronics", "subscription"])
            proposal = submit_proposal(db, owner, ProposalInput(
                mandate_id=grant.id, purchase_intent_id=f"atk-{uuid4()}",
                items=[ItemInput(product_id="subscription", quantity=1)], currency="USD",
            ))
            verdict, rules = proposal.decision, proposal.rules
        elif attack_id == "cart_swap_after_approval":
            grant = _sim_grant(db, owner, constraints={"width_cm": 160})
            proposal = submit_proposal(db, owner, ProposalInput(
                mandate_id=grant.id, purchase_intent_id=f"atk-{uuid4()}",
                items=[ItemInput(product_id="desk-unknown", quantity=1)], currency="USD",
            ))
            rules = proposal.rules
            tampered_hash = digest({"tampered": True, "original": proposal.cart_hash})
            try:
                approve_proposal(proposal.id, ApprovalInput(cart_hash=tampered_hash), owner=owner, db=db)
                verdict = "APPROVE"
                actual_rule = "NONE"
            except HTTPException as exc:
                if exc.status_code == 409 and "Cart hash mismatch" in str(exc.detail):
                    verdict = "BLOCKED_AT_EXECUTION"
                    actual_rule = "CART_HASH_BINDING"
                else:
                    verdict = "DENY"
                    actual_rule = _pick_actual_rule(expected_rule, verdict, rules)
        if attack_id != "cart_swap_after_approval":
            actual_rule = _pick_actual_rule(expected_rule, verdict, rules)
    finally:
        savepoint.rollback()

    breached = verdict == "APPROVE"
    if breached:
        logger.error("ATTACK_BREACH attack_id=%s expected_rule=%s", attack_id, expected_rule)
    attempt = ChallengeAttempt(
        session_id=owner.id,
        attack_id=attack_id,
        verdict=verdict,
        expected_rule=expected_rule,
        actual_rule=actual_rule,
        rules=rules,
        breached=breached,
    )
    db.add(attempt)
    db.flush()
    append(db, owner, "ATTACK_BREACH" if breached else "ATTACK_BLOCKED", attempt.id, {
        "attack_id": attack_id,
        "verdict": verdict,
        "expected_rule": expected_rule,
        "actual_rule": actual_rule,
        "breached": breached,
    })
    return {
        "id": attempt.id,
        "attack_id": attack_id,
        "title": meta["title"],
        "description": meta["description"],
        "verdict": verdict,
        "expected_rule": expected_rule,
        "actual_rule": actual_rule,
        "triggered_rules": [r["id"] for r in rules if r.get("status") in {"DENY", "ESCALATE"}] if attack_id != "cart_swap_after_approval" else [actual_rule],
        "breached": breached,
        "rules": rules,
    }


@router.get("/attacks")
def list_attacks(owner=Depends(human)):
    return ATTACK_CATALOG


@router.post("/attacks/run")
def run_attack(body: AttackRunInput, owner=Depends(human), db: DBSession = Depends(get_db)):
    consume(db, "attacks", owner.id, 60)
    return _evaluate_attack(db, owner, body.attack_id)


@router.post("/attacks/run-all")
def run_all_attacks(owner=Depends(human), db: DBSession = Depends(get_db)):
    consume(db, "attacks", owner.id, 30)
    results = [_evaluate_attack(db, owner, item["id"]) for item in ATTACK_CATALOG]
    breaches = sum(1 for item in results if item["breached"])
    return {
        "attempts": len(results),
        "breaches": breaches,
        "blocked": len(results) - breaches,
        "results": results,
    }


@router.get("/challenge/stats")
def challenge_stats(owner=Depends(human), db: DBSession = Depends(get_db)):
    consume(db, "challenge-stats", owner.id, 120)
    rows = list(db.scalars(select(ChallengeAttempt).where(ChallengeAttempt.session_id == owner.id)))
    per_rule_counts: dict[str, int] = {}
    for row in rows:
        if not row.breached and row.actual_rule != "NONE":
            per_rule_counts[row.actual_rule] = per_rule_counts.get(row.actual_rule, 0) + 1
    return {
        "attempts": len(rows),
        "breaches": sum(1 for row in rows if row.breached),
        "per_rule_counts": per_rule_counts,
    }


@router.get("/evals")
def get_eval_results(owner=Depends(human)):
    eval_path = Path.cwd() / "eval_results.json"
    if not eval_path.is_file():
        raise HTTPException(404, "Evaluation results have not been generated yet")
    return json.loads(eval_path.read_text(encoding="utf-8"))

