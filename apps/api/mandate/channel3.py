import logging
import os
import re
from typing import Any

import httpx

logger = logging.getLogger("mandate.channel3")

CHANNEL3_BASE_URL = "https://api.channel3.tv/v1"

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


def search_channel3(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Search for products using Channel3 API, falling back to curated Channel3 catalog."""
    api_key = get_channel3_api_key()
    tokens = set(re.findall(r"[a-z0-9]+", query.lower()))

    # If live key is provided, attempt live Channel3 API query
    if api_key and not os.getenv("PYTEST_CURRENT_TEST"):
        try:
            with httpx.Client(timeout=4.0) as client:
                res = client.get(
                    f"{CHANNEL3_BASE_URL}/products/search",
                    params={"q": query, "limit": limit},
                    headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
                )
                if res.status_code == 200:
                    data = res.json()
                    raw_items = data.get("products") or data.get("items") or []
                    normalized = []
                    for item in raw_items[:limit]:
                        pid = str(item.get("id") or item.get("sku") or hash(item.get("title", "")))
                        price = int(item.get("price_cents") or (float(item.get("price", 0)) * 100))
                        normalized.append({
                            "id": f"c3-{pid}",
                            "name": item.get("title") or item.get("name") or "Channel3 Product",
                            "merchant_id": item.get("retailer") or "channel3-merchant",
                            "category": item.get("category", "general"),
                            "unit_price_cents": price,
                            "currency": item.get("currency", "USD"),
                            "attributes": item.get("attributes") or {},
                            "recurring": False,
                            "description": item.get("description", "Product retrieved via Channel3 API"),
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

