"""[MOCKED] Tests for sponsor integrations: Zapier and Channel3."""
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
import pytest

from mandate.catalog import quote
from mandate.channel3 import lookup_channel3_item, search_channel3
from mandate.db import get_db
from mandate.main import app
from mandate.models import Mandate, Session, now
from mandate.policy import evaluate
from mandate.zapier import get_zapier_webhook_url, mask_url, send_zapier_event


class MockItem:
    def __init__(self, product_id: str, quantity: int = 1):
        self.product_id = product_id
        self.quantity = quantity


def test_zapier_mask_url():
    assert mask_url("") == "(not configured)"
    assert "..." in mask_url("https://hooks.zapier.com/hooks/catch/123456/abcdef/")


@patch("mandate.zapier.httpx.Client")
def test_zapier_send_event_dispatched(mock_client_class):
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_client.post.return_value = mock_response
    mock_client_class.return_value.__enter__.return_value = mock_client

    result = send_zapier_event(
        "mandate.proposal.evaluated",
        {"proposal_id": "prop-123", "decision": "APPROVE"},
        webhook_url="https://hooks.zapier.com/hooks/catch/test/123/",
    )
    assert result is True


def test_zapier_unconfigured_skips_cleanly():
    with patch.dict("os.environ", {"ZAPIER_WEBHOOK_URL": ""}):
        result = send_zapier_event("mandate.test", {"data": 123}, webhook_url=None)
        assert result is False


def test_channel3_search_fallback():
    results = search_channel3("ergonomic mouse", limit=3)
    assert len(results) > 0
    assert any("mouse" in item["name"].lower() or "ergonomic" in str(item).lower() for item in results)
    assert results[0]["id"].startswith("c3-")


@patch("mandate.channel3.httpx.Client")
def test_channel3_search_live_api_mocked(mock_client_class, monkeypatch):
    """Test Channel3 live API search with mocked real POST /v1/search endpoint and schema."""
    monkeypatch.setenv("CHANNEL3_API_KEY", "test-c3-key-12345")
    monkeypatch.setenv("CHANNEL3_TEST_MOCK", "1")

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "products": [
            {
                "id": "prod-desk-99",
                "title": "Ergonomic Standing Desk",
                "category": "furniture",
                "brand": "Jarvis",
                "offers": [
                    {
                        "price": 450.50,
                        "currency": "USD",
                        "merchant": "demo-merchant",
                        "url": "https://example.com/desk",
                    }
                ],
                "attributes": {"width_cm": 160, "electric": True},
                "description": "Adjustable height ergonomic desk",
            }
        ]
    }
    mock_client.post.return_value = mock_response
    mock_client_class.return_value.__enter__.return_value = mock_client

    results = search_channel3("standing desk", limit=1)

    assert len(results) == 1
    item = results[0]
    assert item["id"] == "c3-prod-desk-99"
    assert item["name"] == "Ergonomic Standing Desk"
    assert item["unit_price_cents"] == 45050
    assert item["currency"] == "USD"
    assert item["merchant_id"] == "demo-merchant"
    assert item["category"] == "furniture"
    assert item["attributes"] == {"width_cm": 160, "electric": True}
    assert item["recurring"] is False
    assert item["source"] == "channel3-live"

    # Verify real request endpoint, headers, and body per docs.trychannel3.com
    mock_client.post.assert_called_once()
    call_args, call_kwargs = mock_client.post.call_args
    assert call_args[0] == "https://api.trychannel3.com/v1/search"
    assert call_kwargs["headers"]["x-api-key"] == "test-c3-key-12345"
    assert call_kwargs["headers"]["Content-Type"] == "application/json"
    assert call_kwargs["headers"]["Accept"] == "application/json"
    assert call_kwargs["json"] == {"query": "standing desk", "limit": 1}


def test_channel3_lookup_and_quote_integration():
    item = lookup_channel3_item("c3-dock-tb4")
    assert item is not None
    assert item["name"] == "CalDigit TS4 Thunderbolt 4 Dock"
    assert item["unit_price_cents"] == 39900

    # Test quote integration in mandate/catalog.py
    cart, missing = quote([MockItem("c3-dock-tb4", 2)], "USD")
    assert len(missing) == 0
    assert cart["total_cents"] == 39900 * 2
    assert cart["items"][0]["name"] == "CalDigit TS4 Thunderbolt 4 Dock"


def test_integrations_api_status_and_search(client: TestClient):
    # Status endpoint
    res = client.get("/api/integrations/status")
    assert res.status_code == 200
    data = res.json()
    assert "zapier" in data
    assert "channel3" in data
    assert data["channel3"]["catalog_items_available"] >= 4

    # Channel3 search endpoint
    search_res = client.get("/api/integrations/channel3/search?q=desk")
    assert search_res.status_code == 200
    search_data = search_res.json()
    assert search_data["count"] > 0
    assert any("desk" in p["name"].lower() for p in search_data["products"])

    # Zapier test dispatch endpoint
    zapier_res = client.post("/api/integrations/zapier/test", json={"webhook_url": "https://hooks.zapier.com/hooks/catch/fake/123"})
    assert zapier_res.status_code == 200
    assert zapier_res.json()["dispatched"] is True


def test_channel3_non_allowlisted_merchant_denied_by_p04(database):
    """Channel3 items from outside the grant's allowed_merchants must be DENIED by P04."""
    # c3-chair-ergonomic has merchant_id="herman-miller"
    cart, missing = quote([MockItem("c3-chair-ergonomic", 1)], "USD")
    assert len(missing) == 0

    with database() as db:
        from datetime import timedelta
        sess = Session(csrf_token="test_csrf_token_p04")
        db.add(sess)
        db.flush()

        grant = Mandate(
            session_id=sess.id,
            budget_cents=200000,
            per_transaction_cents=200000,
            allowed_categories=["furniture"],
            allowed_merchants=["demo-merchant"],  # herman-miller is not allowlisted
            constraints={},
            instruction="Buy furniture",
            expires_at=now() + timedelta(hours=1),
            velocity_limit=10,
        )
        db.add(grant)
        db.flush()

        decision, rules = evaluate(db, grant, cart, missing)
        assert decision == "DENY"
        p04 = next(r for r in rules if r["id"] == "P04")
        assert p04["status"] == "DENY"


def test_channel3_missing_attribute_escalates_p09(database):
    """Channel3 item missing required grant constraint attributes must ESCALATE under P09."""
    # c3-light-screenbar has attributes {"auto_dimming": True}, lacks width_cm
    # Use demo-merchant so P04 passes
    cart, missing = quote([MockItem("c3-light-screenbar", 1)], "USD")
    assert len(missing) == 0

    with database() as db:
        from datetime import timedelta
        sess = Session(csrf_token="test_csrf_token_p09")
        db.add(sess)
        db.flush()

        grant = Mandate(
            session_id=sess.id,
            budget_cents=50000,
            per_transaction_cents=50000,
            allowed_categories=["electronics"],
            allowed_merchants=["demo-merchant"],
            constraints={"width_cm": 160},  # screenbar does not have width_cm
            instruction="Buy 160 cm electronics",
            expires_at=now() + timedelta(hours=1),
            velocity_limit=10,
        )
        db.add(grant)
        db.flush()

        decision, rules = evaluate(db, grant, cart, missing)
        assert decision == "ESCALATE"
        p09 = next(r for r in rules if r["id"] == "P09")
        assert p09["status"] == "ESCALATE"
        assert "Missing" in p09["message"]

