"""[MOCKED] Tests for sponsor integrations: Zapier and Channel3."""
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
import pytest

from mandate.catalog import quote
from mandate.channel3 import lookup_channel3_item, search_channel3
from mandate.main import app
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
