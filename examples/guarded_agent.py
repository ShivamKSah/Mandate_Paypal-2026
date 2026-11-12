"""Minimal example: any external agent proposes a cart via Mandate and gets APPROVE, ESCALATE, or DENY.

Never executes network calls on import. Run directly against a running Mandate server.
"""

from __future__ import annotations

import os
import uuid
import httpx


def propose_purchase(base_url: str, mandate_id: str, product_id: str, quantity: int = 1) -> dict:
    with httpx.Client(base_url=base_url, timeout=15.0) as client:
        sess = client.get("/api/session")
        sess.raise_for_status()
        csrf = sess.json()["csrf_token"]
        resp = client.post(
            "/api/proposals",
            headers={"X-CSRF-Token": csrf},
            json={
                "mandate_id": mandate_id,
                "purchase_intent_id": f"agent-{uuid.uuid4()}",
                "items": [{"product_id": product_id, "quantity": quantity}],
                "currency": "USD",
            },
        )
        resp.raise_for_status()
        return resp.json()


def main() -> None:
    base_url = os.getenv("MANDATE_URL", "http://127.0.0.1:8000")
    mandate_id = os.environ["MANDATE_ID"]
    result = propose_purchase(base_url, mandate_id, product_id="mouse-ergonomic", quantity=1)
    print(f"Decision: {result['decision']} | Status: {result['status']} | Total: {result['total_cents']} cents")


if __name__ == "__main__":
    main()
