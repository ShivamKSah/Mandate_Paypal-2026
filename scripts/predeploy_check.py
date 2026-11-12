"""Offline production deployment readiness check for Mandate.

Checks required production environment variables and prints a PASS/FAIL
checklist without printing any environment variable values or secrets.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "apps" / "api") not in sys.path:
    sys.path.insert(0, str(ROOT / "apps" / "api"))


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    reason: str


def _parse_env_file(path: Path) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key:
            parsed[key] = value
    return parsed


def _is_valid_fernet_key(raw: str) -> bool:
    if not raw:
        return False
    try:
        Fernet(raw.encode("ascii"))
    except Exception:
        return False
    return True


def _effective_allowed_hosts(public_host: str | None, env: Mapping[str, str]) -> set[str]:
    configured = {
        entry.strip().lower()
        for entry in env.get("ALLOWED_HOSTS", "").split(",")
        if entry.strip()
    }
    if configured:
        return configured
    if public_host:
        return {public_host.lower(), "localhost", "127.0.0.1"}
    return set()


def evaluate_env(env: Mapping[str, str]) -> list[CheckResult]:
    results: list[CheckResult] = []

    app_env = env.get("APP_ENV", "").strip().lower()
    results.append(
        CheckResult(
            "APP_ENV",
            app_env == "production",
            "production" if app_env == "production" else "must be set to 'production'",
        )
    )

    public_demo_raw = env.get("PUBLIC_DEMO", "").strip().lower()
    public_demo_valid = public_demo_raw in {"true", "false"}
    results.append(
        CheckResult(
            "PUBLIC_DEMO",
            public_demo_valid,
            "explicit boolean configured" if public_demo_valid else "must be set to 'true' or 'false'",
        )
    )

    if public_demo_raw == "false":
        has_access_key = len(env.get("APP_ACCESS_KEY", "")) >= 32
        results.append(
            CheckResult(
                "APP_ACCESS_KEY",
                has_access_key,
                "configured (>= 32 chars)" if has_access_key else "must be >= 32 chars when PUBLIC_DEMO=false",
            )
        )

    cookie_secure = env.get("COOKIE_SECURE", "").strip().lower() == "true"
    results.append(
        CheckResult(
            "COOKIE_SECURE",
            cookie_secure,
            "enabled" if cookie_secure else "must be set to 'true'",
        )
    )

    public_base = env.get("PUBLIC_BASE_URL", "").strip().rstrip("/")
    parsed = urlsplit(public_base)
    base_ok = (
        parsed.scheme == "https"
        and bool(parsed.hostname)
        and not parsed.username
        and not parsed.password
        and not parsed.query
        and not parsed.fragment
        and parsed.path in {"", "/"}
    )
    results.append(
        CheckResult(
            "PUBLIC_BASE_URL",
            base_ok,
            "valid https origin" if base_ok else "must be an https:// origin without path, query, or credentials",
        )
    )

    allowed_hosts = _effective_allowed_hosts(parsed.hostname, env)
    host_ok = bool(parsed.hostname) and parsed.hostname.lower() in allowed_hosts
    explicit_hosts = bool(env.get("ALLOWED_HOSTS", "").strip())
    results.append(
        CheckResult(
            "ALLOWED_HOSTS",
            host_ok,
            (
                "explicit list includes PUBLIC_BASE_URL hostname"
                if host_ok and explicit_hosts
                else "derived from PUBLIC_BASE_URL hostname"
                if host_ok
                else "must include the PUBLIC_BASE_URL hostname"
            ),
        )
    )

    paypal_env = env.get("PAYPAL_ENV", "sandbox").strip().lower()
    paypal_base = env.get("PAYPAL_BASE_URL", "https://api-m.sandbox.paypal.com").strip()
    sandbox_ok = paypal_env == "sandbox" and paypal_base == "https://api-m.sandbox.paypal.com"
    results.append(
        CheckResult(
            "PAYPAL_SANDBOX_GUARD",
            sandbox_ok,
            "sandbox-only endpoints enforced" if sandbox_ok else "PAYPAL_ENV and PAYPAL_BASE_URL must target PayPal Sandbox only",
        )
    )

    for var in (
        "PAYPAL_CLIENT_ID",
        "PAYPAL_CLIENT_SECRET",
        "PAYPAL_MERCHANT_ID",
        "PAYPAL_WEBHOOK_ID",
        "GROQ_API_KEY",
    ):
        present = bool(env.get(var, "").strip())
        results.append(
            CheckResult(
                var,
                present,
                "configured" if present else "missing or empty",
            )
        )

    vault_ok = _is_valid_fernet_key(env.get("VAULT_ENCRYPTION_KEY", "").strip())
    results.append(
        CheckResult(
            "VAULT_ENCRYPTION_KEY",
            vault_ok,
            "valid Fernet key" if vault_ok else "missing or invalid Fernet key",
        )
    )

    vault_verified_raw = env.get("VAULT_AUTONOMY_VERIFIED", "").strip().lower()
    vault_verified_ok = vault_verified_raw in {"", "true", "false"}
    results.append(
        CheckResult(
            "VAULT_AUTONOMY_VERIFIED",
            vault_verified_ok,
            (
                f"configured ({vault_verified_raw or 'default false'})"
                if vault_verified_ok
                else "must be 'true' or 'false' when set"
            ),
        )
    )

    db_url = env.get("DATABASE_URL", "").strip()
    db_ok = db_url.startswith(("postgres://", "postgresql://", "postgresql+psycopg://"))
    results.append(
        CheckResult(
            "DATABASE_URL",
            db_ok,
            "PostgreSQL connection string configured" if db_ok else "must be a PostgreSQL connection string",
        )
    )

    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline pre-deployment environment check (prints no secret values).")
    parser.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help="Optional dotenv file to load for missing environment variables.",
    )
    args = parser.parse_args(argv)

    env: dict[str, str] = dict(os.environ)
    env_file = args.env_file if args.env_file is not None else (ROOT / ".env" if (ROOT / ".env").exists() else None)
    if env_file is not None:
        if not env_file.exists():
            print(f"FAIL env-file: requested file does not exist ({env_file.name})")
            return 1
        for key, value in _parse_env_file(env_file).items():
            env.setdefault(key, value)

    checks = evaluate_env(env)
    for item in checks:
        status = "PASS" if item.passed else "FAIL"
        print(f"{status} {item.name}: {item.reason}")

    failures = sum(1 for item in checks if not item.passed)
    print(f"\nSummary: {len(checks) - failures}/{len(checks)} checks passed.")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
