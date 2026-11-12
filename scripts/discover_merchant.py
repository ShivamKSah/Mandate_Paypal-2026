#!/usr/bin/env python3
"""Discover the PayPal Sandbox Business merchant ID owning PAYPAL_CLIENT_ID.

Creates one unapproved $1.00 USD CAPTURE order with no explicit payee field,
reads purchase_units[0].payee via GET, and compares against PAYPAL_MERCHANT_ID.
Sandbox only; never prints client secrets, access tokens, or vault IDs.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from pathlib import Path
from uuid import uuid4

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "apps" / "api") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))

from mandate.config import (  # noqa: E402
    INNER_ENV_PATH,
    load_environment,
    mask_merchant_id,
    normalize_merchant_id,
)

SANDBOX_BASE_URL = "https://api-m.sandbox.paypal.com"
PAYPAL_LINE_RE = re.compile(r"^(\s*PAYPAL_MERCHANT_ID\s*=).*$")


def update_env_merchant_id(env_path: Path, new_merchant_id: str) -> Path:
    """Back up env_path to .env.bak and replace only the PAYPAL_MERCHANT_ID line."""
    bak_path = env_path.with_name(f"{env_path.name}.bak")
    shutil.copy2(env_path, bak_path)

    raw_text = env_path.read_text(encoding="utf-8")
    newline = "\r\n" if "\r\n" in raw_text else "\n"
    trailing_nl = raw_text.endswith(("\n", "\r"))
    lines = raw_text.splitlines()

    replaced = False
    out_lines: list[str] = []
    for line in lines:
        if not replaced and PAYPAL_LINE_RE.match(line):
            out_lines.append(f"PAYPAL_MERCHANT_ID={new_merchant_id}")
            replaced = True
        else:
            out_lines.append(line)
    if not replaced:
        out_lines.append(f"PAYPAL_MERCHANT_ID={new_merchant_id}")

    updated_text = newline.join(out_lines) + (newline if trailing_nl else "")
    env_path.write_text(updated_text, encoding="utf-8")
    return bak_path


def _print_paypal_error(step: str, resp: httpx.Response) -> None:
    try:
        payload = resp.json()
    except ValueError:
        payload = {}
    name = payload.get("name") if isinstance(payload, dict) else None
    debug_id = payload.get("debug_id") if isinstance(payload, dict) else None
    issues = [
        d.get("issue")
        for d in (payload.get("details") or [])
        if isinstance(d, dict) and d.get("issue")
    ] if isinstance(payload, dict) else []
    print(
        f"ERROR: {step} failed with HTTP {resp.status_code} "
        f"(name={name or 'unknown'}, issues={','.join(issues) or 'none'}, debug_id={debug_id or 'none'})",
        file=sys.stderr,
    )


def run_discovery(
    *,
    env_path: Path = INNER_ENV_PATH,
    write_env: bool = False,
    http_client: httpx.Client | None = None,
    load_env: bool = True,
) -> tuple[int, dict[str, object]]:
    if load_env:
        diag = load_environment(env_path=env_path, allow_override=True)
    else:
        diag = {"loaded_env_path": str(env_path)}

    if os.getenv("PAYPAL_ENV", "sandbox").strip().lower() != "sandbox":
        print("ERROR: Refusing to run: PAYPAL_ENV must be 'sandbox'.", file=sys.stderr)
        return 1, {"status": "refused_non_sandbox"}
    if os.getenv("PAYPAL_BASE_URL", SANDBOX_BASE_URL).strip().rstrip("/") != SANDBOX_BASE_URL:
        print("ERROR: Refusing to run: PAYPAL_BASE_URL must target PayPal Sandbox only.", file=sys.stderr)
        return 1, {"status": "refused_non_sandbox"}

    client_id = os.getenv("PAYPAL_CLIENT_ID", "").strip()
    client_secret = os.getenv("PAYPAL_CLIENT_SECRET", "").strip()
    configured_merchant = normalize_merchant_id(os.getenv("PAYPAL_MERCHANT_ID", ""))
    if not client_id or not client_secret:
        print("ERROR: PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET must be set.", file=sys.stderr)
        return 1, {"status": "missing_credentials"}

    print(f"ENV loaded: {diag['loaded_env_path']}")
    print(
        f"Configured PAYPAL_MERCHANT_ID: {mask_merchant_id(configured_merchant)} "
        f"(length={len(configured_merchant)})"
    )

    owns_client = http_client is None
    client = http_client or httpx.Client(timeout=20.0, follow_redirects=False)
    try:
        tok_resp = client.post(
            f"{SANDBOX_BASE_URL}/v1/oauth2/token",
            auth=httpx.BasicAuth(client_id, client_secret),
            data={"grant_type": "client_credentials"},
            headers={"Accept": "application/json"},
        )
        print(f"POST /v1/oauth2/token -> HTTP {tok_resp.status_code}")
        if tok_resp.status_code != 200:
            _print_paypal_error("POST /v1/oauth2/token", tok_resp)
            return 1, {"status": "oauth_error", "http_status": tok_resp.status_code}
        access_token = tok_resp.json().get("access_token")
        if not isinstance(access_token, str) or not access_token:
            print("ERROR: OAuth response did not contain access_token.", file=sys.stderr)
            return 1, {"status": "oauth_invalid"}

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "PayPal-Request-Id": f"dm-{uuid4().hex[:32]}",
        }
        create_resp = client.post(
            f"{SANDBOX_BASE_URL}/v2/checkout/orders",
            headers=headers,
            json={
                "intent": "CAPTURE",
                "purchase_units": [
                    {
                        "amount": {"currency_code": "USD", "value": "1.00"},
                        "description": "Mandate sandbox merchant discovery ($1.00 unapproved)",
                    }
                ],
            },
        )
        print(f"POST /v2/checkout/orders -> HTTP {create_resp.status_code}")
        if not 200 <= create_resp.status_code < 300:
            _print_paypal_error("POST /v2/checkout/orders", create_resp)
            return 1, {"status": "create_error", "http_status": create_resp.status_code}

        order_id = create_resp.json().get("id")
        if not isinstance(order_id, str) or not order_id:
            print("ERROR: Order response missing order id.", file=sys.stderr)
            return 1, {"status": "create_missing_id"}

        get_resp = client.get(
            f"{SANDBOX_BASE_URL}/v2/checkout/orders/{order_id}",
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        )
        print(f"GET /v2/checkout/orders/{order_id} -> HTTP {get_resp.status_code}")
        if not 200 <= get_resp.status_code < 300:
            _print_paypal_error(f"GET /v2/checkout/orders/{order_id}", get_resp)
            return 1, {"status": "get_error", "http_status": get_resp.status_code}

        order_data = get_resp.json()
        units = order_data.get("purchase_units") or []
        payee = units[0].get("payee", {}) if units and isinstance(units[0], dict) else {}
        discovered_merchant = normalize_merchant_id(payee.get("merchant_id") if isinstance(payee, dict) else None)
        discovered_email = (payee.get("email_address") or "").strip() if isinstance(payee, dict) else ""

        print(f"PayPal payee.merchant_id: {discovered_merchant or '(missing)'}")
        print(f"PayPal payee.email_address: {discovered_email or '(missing)'}")
        if discovered_email and not discovered_merchant:
            print("NOTE: PayPal returned payee.email_address without payee.merchant_id.")

        matched = bool(discovered_merchant) and discovered_merchant == configured_merchant
        outcome = "MATCH" if matched else "MISMATCH"
        print(f"Comparison: {outcome}")

        wrote = False
        bak_path = None
        if write_env and outcome == "MISMATCH" and discovered_merchant:
            bak_path = update_env_merchant_id(env_path, discovered_merchant)
            wrote = True
            print(
                f"Updated {env_path} (backup at {bak_path}); "
                f"new PAYPAL_MERCHANT_ID: {mask_merchant_id(discovered_merchant)} "
                f"(length={len(discovered_merchant)})"
            )

        return 0, {
            "status": outcome,
            "discovered_merchant": discovered_merchant,
            "discovered_email": discovered_email,
            "configured_masked": mask_merchant_id(configured_merchant),
            "wrote_env": wrote,
            "backup_path": str(bak_path) if bak_path else None,
        }
    finally:
        if owns_client:
            client.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Discover sandbox PayPal merchant ID from an unapproved $1 order.")
    parser.add_argument(
        "--write-env",
        action="store_true",
        help="Back up inner .env to .env.bak and update PAYPAL_MERCHANT_ID if MISMATCH.",
    )
    args = parser.parse_args(argv)
    code, _ = run_discovery(env_path=INNER_ENV_PATH, write_env=args.write_env)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
