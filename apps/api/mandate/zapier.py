import logging
import os
import threading
from typing import Any

import httpx

logger = logging.getLogger("mandate.zapier")


def get_zapier_webhook_url() -> str:
    """Return the configured Zapier webhook URL from environment."""
    return os.getenv("ZAPIER_WEBHOOK_URL", "").strip()


def mask_url(url: str) -> str:
    """Mask a webhook URL for safe display without leaking auth tokens or webhook slugs."""
    if not url:
        return "(not configured)"
    if len(url) <= 24:
        return url[:8] + "..."
    return url[:18] + "..." + url[-6:]


def is_zapier_configured() -> bool:
    """Check if a Zapier webhook destination is configured."""
    return bool(get_zapier_webhook_url())


def _dispatch_worker(url: str, payload: dict[str, Any]) -> None:
    """Non-blocking background HTTP dispatch to Zapier webhook."""
    try:
        with httpx.Client(timeout=5.0) as client:
            response = client.post(url, json=payload)
            if response.status_code >= 400:
                logger.warning("Zapier webhook returned status %s: %s", response.status_code, response.text[:200])
    except Exception as exc:
        logger.warning("Failed to dispatch Zapier webhook: %s", exc)


def send_zapier_event(event_type: str, data: dict[str, Any], webhook_url: str | None = None) -> bool:
    """Dispatch an event payload to Zapier webhook. Never raises; fails gracefully."""
    target_url = webhook_url or get_zapier_webhook_url()
    if not target_url:
        return False

    payload = {
        "source": "mandate",
        "event": event_type,
        "timestamp": data.get("timestamp"),
        "data": data,
    }

    # Dispatch asynchronously so it never blocks payment or policy evaluation
    worker = threading.Thread(target=_dispatch_worker, args=(target_url, payload), daemon=True)
    worker.start()
    return True

