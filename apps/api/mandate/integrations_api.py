from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from .channel3 import CHANNEL3_FALLBACK_CATALOG, is_channel3_configured, search_channel3
from .security import human
from .zapier import get_zapier_webhook_url, is_zapier_configured, mask_url, send_zapier_event

router = APIRouter(prefix="/api/integrations")


class ZapierTestInput(BaseModel):
    webhook_url: str | None = Field(default=None, max_length=500)


@router.get("/status")
def integrations_status(owner=Depends(human)) -> dict[str, Any]:
    """Return status of sponsor partner integrations."""
    zapier_url = get_zapier_webhook_url()
    return {
        "zapier": {
            "configured": is_zapier_configured(),
            "target": mask_url(zapier_url),
            "events_supported": [
                "mandate.proposal.evaluated",
                "mandate.payment.captured",
                "mandate.payment.refunded",
            ],
        },
        "channel3": {
            "configured": is_channel3_configured(),
            "catalog_items_available": len(CHANNEL3_FALLBACK_CATALOG),
            "source": "api" if is_channel3_configured() else "curated_fallback",
        },
    }


@router.post("/zapier/test")
def test_zapier_dispatch(body: ZapierTestInput | None = None, owner=Depends(human)) -> dict[str, Any]:
    """Dispatch a test webhook event to Zapier."""
    custom_url = body.webhook_url if body else None
    dispatched = send_zapier_event(
        "mandate.test.event",
        {
            "message": "Mandate spending controls Zapier integration active",
            "operator_id": owner.id,
            "sample_decision": "APPROVE",
            "sample_amount_cents": 4500,
            "currency": "USD",
        },
        webhook_url=custom_url,
    )
    return {
        "dispatched": dispatched,
        "configured": is_zapier_configured() or bool(custom_url),
        "target": mask_url(custom_url or get_zapier_webhook_url()),
    }


@router.get("/channel3/search")
def search_channel3_products(
    q: str = Query(default="", max_length=100),
    limit: int = Query(default=5, ge=1, le=20),
    owner=Depends(human),
) -> dict[str, Any]:
    """Search Channel3 e-commerce products for the shopping agent."""
    results = search_channel3(q, limit=limit)
    return {
        "query": q,
        "count": len(results),
        "configured": is_channel3_configured(),
        "products": results,
    }

