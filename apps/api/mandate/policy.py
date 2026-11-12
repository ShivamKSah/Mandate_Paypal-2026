from datetime import timedelta

from sqlalchemy import func, select

from .audit import digest
from .models import Payment, Proposal, now

NAMES = ["Active authority", "Budget", "Transaction cap", "Trusted merchant", "Category", "Exact quote", "Velocity", "Purchase identity", "Confirmed constraints", "Non-recurring", "Additional review"]


def evaluate(db, grant, cart, missing, *, claimed_total=None, proposal_id=None, human_approved=False, reserved_credit=0, payment_id=None):
    rules = []

    def rule(number, status, message):
        rules.append({"id": f"P{number:02d}", "name": NAMES[number - 1], "status": status, "message": message})

    total, items = cart["total_cents"], cart["items"]
    active = grant.status == "ACTIVE" and grant.expires_at > now()
    rule(1, "PASS" if active else "DENY", "Grant is active" if active else "Grant is revoked or expired")
    rule(2, "PASS" if total + grant.spent_cents + grant.reserved_cents - reserved_credit <= grant.budget_cents else "DENY", "Canonical total plus spent and reserved must fit the budget")
    rule(3, "PASS" if total <= grant.per_transaction_cents else "DENY", "Canonical total must fit the transaction cap")
    merchant_ok = not missing and bool(items) and all(i["merchant_id"] == "demo-merchant" and i["merchant_id"] in grant.allowed_merchants for i in items)
    rule(4, "PASS" if merchant_ok else "DENY", "Only the trusted configured merchant and grant allowlist can receive payment")
    rule(5, "PASS" if not missing and items and all(i["category"] in grant.allowed_categories for i in items) else "DENY", "Catalog category must be allowed and available")
    exact = not missing and cart["currency"] == "USD" and total > 0 and all(i["quantity"] <= 100 for i in items) and (claimed_total is None or claimed_total == total)
    rule(6, "PASS" if exact else "DENY", "Trusted quote including fees reconciles" if exact else "Unknown product, unsupported currency, quantity, or invented total")
    slots = select(func.count(Payment.id)).where(Payment.mandate_id == grant.id, Payment.created_at > now() - timedelta(hours=1), Payment.status != "RELEASED")
    if payment_id:
        slots = slots.where(Payment.id != payment_id)
    used = db.scalar(slots)
    rule(7, "PASS" if used < grant.velocity_limit else "DENY", f"{used} of {grant.velocity_limit} hourly purchase slots reserved or used")
    rule(8, "PASS", "Purchase intent is deduplicated under the grant lock")
    missing_attributes, mismatches = [], []
    for item in items:
        for key, value in grant.constraints.items():
            if key not in item["attributes"]:
                missing_attributes.append(f"{item['product_id']}.{key}")
            elif item["attributes"][key] != value:
                mismatches.append(f"{item['product_id']}.{key}")
    constraint_status = "DENY" if mismatches else "ESCALATE" if missing_attributes and not human_approved else "PASS"
    rule(9, constraint_status, "Mismatched: " + ", ".join(mismatches) if mismatches else "Missing: " + ", ".join(missing_attributes) if missing_attributes else "Confirmed constraints match")
    rule(10, "DENY" if any(i["recurring"] for i in items) else "PASS", "Recurring purchases are forbidden")
    duplicate_query = select(Proposal.id).where(Proposal.mandate_id == grant.id, Proposal.cart_hash == digest(cart), Proposal.created_at > now() - timedelta(hours=1))
    if proposal_id:
        proposal = db.get(Proposal, proposal_id)
        # Later submissions cannot retroactively invalidate an approved purchase.
        duplicate_query = duplicate_query.where(Proposal.created_at < proposal.created_at)
    duplicate = db.scalar(duplicate_query.limit(1)) is not None
    review = total * 100 > grant.per_transaction_cents * 80 or duplicate
    rule(11, "ESCALATE" if review and not human_approved else "PASS", "Recent duplicate cart or above 80% of transaction cap" if review else "Merchant pre-approved and within review threshold")
    decision = "DENY" if any(r["status"] == "DENY" for r in rules) else "ESCALATE" if any(r["status"] == "ESCALATE" for r in rules) else "APPROVE"
    return decision, rules
