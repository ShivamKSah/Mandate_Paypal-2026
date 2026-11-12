#!/usr/bin/env python3
"""Operator helper: inspect the sandbox payee on a PayPal order without printing secrets.

Usage:
    .venv/Scripts/python.exe scripts/show_payee.py <PAYPAL_ORDER_ID>
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "apps" / "api") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))

from mandate.config import ENV_DIAGNOSTICS, mask_merchant_id, normalize_merchant_id  # noqa: E402

SANDBOX_BASE_URL = "https://api-m.sandbox.paypal.com"
ORDER_ID_RE = re.compile(r"^[A-Za-z0-9-]{1,64}$")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect PayPal Sandbox order payee (never prints secrets).")
    parser.add_argument("order_id", help="PayPal order ID to inspect (e.g. 5C667789U0059001F)")
    args = parser.parse_args(argv)

    order_id = args.order_id.strip()
    if not ORDER_ID_RE.fullmatch(order_id):
        print("ERROR: Invalid PayPal order ID format.", file=sys.stderr)
        return 1

    if os.getenv("PAYPAL_ENV", "sandbox").strip().lower() != "sandbox":
        print("ERROR: Refusing to run: PAYPAL_ENV must be 'sandbox'.", file=sys.stderr)
        return 1
    if os.getenv("PAYPAL_BASE_URL", SANDBOX_BASE_URL).strip().rstrip("/") != SANDBOX_BASE_URL:
        print("ERROR: Refusing to run: PAYPAL_BASE_URL must target PayPal Sandbox only.", file=sys.stderr)
        return 1

    client_id = os.getenv("PAYPAL_CLIENT_ID", "").strip()
    client_secret = os.getenv("PAYPAL_CLIENT_SECRET", "").strip()
    configured_merchant = normalize_merchant_id(os.getenv("PAYPAL_MERCHANT_ID", ""))
    if not client_id or not client_secret:
        print("ERROR: PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET must be configured in .env.", file=sys.stderr)
        return 1

    print(f"ENV loaded: {ENV_DIAGNOSTICS['loaded_env_path']}")
    print(f"Configured PAYPAL_MERCHANT_ID (masked): {mask_merchant_id(configured_merchant)} (length={len(configured_merchant)})")
    if ENV_DIAGNOSTICS.get("stale_os_conflict"):
        print(f"WARNING: {ENV_DIAGNOSTICS['stale_os_conflict']}")
    if ENV_DIAGNOSTICS.get("inner_outer_conflict"):
        print(f"WARNING: {ENV_DIAGNOSTICS['inner_outer_conflict']}")

    with httpx.Client(timeout=15.0, follow_redirects=False) as http:
        tok_resp = http.post(
            f"{SANDBOX_BASE_URL}/v1/oauth2/token",
            auth=httpx.BasicAuth(client_id, client_secret),
            data={"grant_type": "client_credentials"},
            headers={"Accept": "application/json"},
        )
        if tok_resp.status_code != 200:
            print(f"ERROR: OAuth token request failed with HTTP {tok_resp.status_code}.", file=sys.stderr)
            return 1
        access_token = tok_resp.json().get("access_token")
        if not isinstance(access_token, str) or not access_token:
            print("ERROR: PayPal OAuth response missing access_token.", file=sys.stderr)
            return 1

        order_resp = http.get(
            f"{SANDBOX_BASE_URL}/v2/checkout/orders/{order_id}",
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        )
        print(f"GET /v2/checkout/orders/{order_id} -> HTTP {order_resp.status_code}")
        try:
            payload = order_resp.json()
        except ValueError:
            print("Order response was not valid JSON.", file=sys.stderr)
            return 1

        if not 200 <= order_resp.status_code < 300:
            print(
                f"PayPal error: name={payload.get('name')} debug_id={payload.get('debug_id')}",
                file=sys.stderr,
            )
            return 1

        units = payload.get("purchase_units") or []
        if not units:
            print("No purchase_units found in order response.")
            return 0
        for idx, unit in enumerate(units):
            payee = unit.get("payee") if isinstance(unit, dict) else {}
            merchant_id = payee.get("merchant_id") if isinstance(payee, dict) else None
            email = payee.get("email_address") if isinstance(payee, dict) else None
            print(
                f"purchase_units[{idx}].payee: merchant_id={merchant_id or '(missing)'} "
                f"(masked={mask_merchant_id(merchant_id)}), email_address={email or '(missing)'}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
