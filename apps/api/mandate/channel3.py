import logging
import os
import re
from typing import Any

import httpx

logger = logging.getLogger("mandate.channel3")

CHANNEL3_BASE_URL = "https://api.trychannel3.com"

# Curated fallback product items normalized to Channel3 schema
CHANNEL3_FALLBACK_CATALOG: list[dict[str, Any]] = [
    {
        "id": "c3-chair-ergonomic",
        "name": "Herman Miller Aeron Ergonomic Chair",
        "merchant_id": "herman-miller",
        "retailer": "Herman Miller Direct",
        "category": "furniture",
        "unit_price_cents": 129500,
        "currency": "USD",
        "attributes": {"ergonomic": True, "material": "mesh"},
        "recurring": False,
        "description": "Premium ergonomic office seating with PostureFit SL lumbar support.",
    },
    {
        "id": "c3-dock-tb4",
        "name": "CalDigit TS4 Thunderbolt 4 Dock",
        "merchant_id": "caldigit-store",
        "retailer": "CalDigit",
        "category": "electronics",
        "unit_price_cents": 39900,
        "currency": "USD",
        "attributes": {"ports": 18, "charging_w": 98},
        "recurring": False,
        "description": "18-port Thunderbolt 4 hub for pro workstations and multi-monitor setups.",
    },
    {
        "id": "c3-mouse-mxmaster",
        "name": "Logitech MX Master 3S Wireless Mouse",
        "merchant_id": "demo-merchant",
        "retailer": "Logitech Store",
        "category": "electronics",
        "unit_price_cents": 9900,
        "currency": "USD",
        "attributes": {"ergonomic": True, "connectivity": "wireless"},
        "recurring": False,
        "description": "Quiet click 8K DPI high precision ergonomic performance mouse.",
    },
    {
        "id": "c3-desk-uplift",
        "name": "UPLIFT V2 Commercial Standing Desk 180cm",
        "merchant_id": "uplift-desk",
        "retailer": "Uplift Desk Direct",
        "category": "furniture",
        "unit_price_cents": 68900,
        "currency": "USD",
        "attributes": {"width_cm": 180, "electric": True},
        "recurring": False,
        "description": "Dual-motor motorized sit-stand desk with 355 lb lifting capacity.",
    },
    {
        "id": "c3-light-screenbar",
        "name": "BenQ ScreenBar Pro Monitor Light",
        "merchant_id": "demo-merchant",
        "retailer": "BenQ Store",
        "category": "electronics",
        "unit_price_cents": 13900,
        "currency": "USD",
        "attributes": {"auto_dimming": True},
        "recurring": False,
        "description": "Eye-care asymmetric optical design desktop monitor bar light.",
    },
]


def get_channel3_api_key() -> str:
    """Return the configured Channel3 API key from environment."""
    return os.getenv("CHANNEL3_API_KEY", "").strip()


def is_channel3_configured() -> bool:
    """Check if a Channel3 API key is configured."""
    return bool(get_channel3_api_key())


def search_channel3(
    query: str,
    limit: int = 5,
    client: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    """Search for products using Channel3 API, falling back to curated Channel3 catalog.

    Per docs.trychannel3.com (api-reference/v1/search):
      - Base URL: https://api.trychannel3.com
      - Endpoint: POST /v1/search
      - Header: x-api-key: <key>
      - Body: {"query": query, "limit": limit}
      - Response: {"products": [{"title": "...", "offers": [{"price": ...}]}]}
    """
    api_key = get_channel3_api_key()
    tokens = set(re.findall(r"[a-z0-9]+", query.lower()))

    # If live key is provided and not in unmocked pytest test runner, attempt Channel3 POST /v1/search
    allow_network = client is not None or not os.getenv("PYTEST_CURRENT_TEST") or os.getenv("CHANNEL3_TEST_MOCK")
    if api_key and allow_network:
        try:
            headers = {
                "x-api-key": api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
            body = {
                "query": query,
                "limit": limit,
            }
            if client is not None:
                res = client.post(
                    f"{CHANNEL3_BASE_URL}/v1/search",
                    json=body,
                    headers=headers,
                )
            else:
                with httpx.Client(timeout=4.0) as http_client:
                    res = http_client.post(
                        f"{CHANNEL3_BASE_URL}/v1/search",
                        json=body,
                        headers=headers,
                    )

            if res.status_code == 200:
                data = res.json()
                raw_products = data.get("products") or []
                normalized = []
                for item in raw_products[:limit]:
                    title = item.get("title") or item.get("name") or "Channel3 Product"
                    pid = str(item.get("id") or item.get("sku") or abs(hash(title)))

                    offers = item.get("offers") or []
                    first_offer = (
                        offers[0]
                        if isinstance(offers, list) and len(offers) > 0 and isinstance(offers[0], dict)
                        else {}
                    )

                    price_val = first_offer.get("price")
                    if price_val is not None:
                        try:
                            price_cents = int(round(float(price_val) * 100))
                        except (ValueError, TypeError):
                            price_cents = int(first_offer.get("price_cents") or 0)
                    else:
                        price_cents = int(first_offer.get("price_cents") or item.get("price_cents") or 0)

                    merchant = (
                        first_offer.get("merchant")
                        or first_offer.get("merchant_name")
                        or first_offer.get("retailer")
                        or item.get("brand")
                        or "channel3-merchant"
                    )
                    currency = first_offer.get("currency") or item.get("currency") or "USD"
                    category = item.get("category") or "general"
                    attributes = item.get("attributes") or {}

                    normalized.append({
                        "id": f"c3-{pid}",
                        "name": title,
                        "merchant_id": merchant,
                        "category": category,
                        "unit_price_cents": price_cents,
                        "currency": currency,
                        "attributes": attributes,
                        "recurring": False,
                        "description": item.get("description", f"{title} from {merchant}"),
                        "source": "channel3-live",
                    })
                if normalized:
                    return normalized
        except Exception as exc:
            logger.warning("Channel3 live search failed, falling back to curated catalog: %s", exc)

    # Curated Channel3 fallback matching query tokens
    scored: list[tuple[int, dict[str, Any]]] = []
    for item in CHANNEL3_FALLBACK_CATALOG:
        haystack = f"{item['id']} {item['name']} {item['description']} {item['category']}".lower()
        item_tokens = set(re.findall(r"[a-z0-9]+", haystack))
        overlap = len(tokens & item_tokens)
        scored.append((overlap, {**item, "source": "channel3-catalog"}))

    scored.sort(key=lambda x: x[0], reverse=True)
    results = [item for score, item in scored if score > 0]
    return (results if results else [item for _, item in scored])[:limit]


def lookup_channel3_item(product_id: str) -> dict[str, Any] | None:
    """Lookup a product record by ID in Channel3 catalog."""
    for item in CHANNEL3_FALLBACK_CATALOG:
        if item["id"] == product_id:
            return {**item, "source": "channel3-catalog"}
    return None

