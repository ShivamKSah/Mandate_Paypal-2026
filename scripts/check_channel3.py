#!/usr/bin/env python3
"""Operator helper: check Channel3 live product search API connectivity.

Usage:
    .venv/Scripts/python.exe scripts/check_channel3.py [--query QUERY]

Rules:
    - Never prints the CHANNEL3_API_KEY.
    - Operator-run script only.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "apps" / "api") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))

from mandate.config import load_environment  # noqa: E402

CHANNEL3_BASE_URL = "https://api.channel3.tv/v1"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check Channel3 API connectivity (never prints keys).")
    parser.add_argument("--query", "-q", default="desk", help="Search query term (default: 'desk')")
    args = parser.parse_args(argv)

    load_environment()
    api_key = os.getenv("CHANNEL3_API_KEY", "").strip()
    if not api_key:
        print("STATUS: CHANNEL3_API_KEY is not set in .env (running in curated catalog fallback mode).")
        return 0

    masked_key = f"{api_key[:4]}...{api_key[-4:]}" if len(api_key) > 8 else "***"
    print(f"CHANNEL3_API_KEY: configured (length={len(api_key)}, masked={masked_key})")
    print(f"Target URL: {CHANNEL3_BASE_URL}/products/search?q={args.query}&limit=1")

    try:
        with httpx.Client(timeout=10.0) as client:
            res = client.get(
                f"{CHANNEL3_BASE_URL}/products/search",
                params={"q": args.query, "limit": 1},
                headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
            )
            print(f"HTTP Status: {res.status_code}")
            if res.status_code == 200:
                data = res.json()
                items = data.get("products") or data.get("items") or []
                print(f"Products Found: {len(items)}")
                if items:
                    first = items[0]
                    title = first.get("title") or first.get("name") or "(untitled)"
                    print(f"First Product Title: {title}")
                else:
                    print("First Product Title: (no items returned for query)")
                return 0
            else:
                print(f"Error: API returned status {res.status_code}")
                return 1
    except Exception as exc:
        print(f"Connection Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
