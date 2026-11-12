"""Read-only local readiness checks. Credentials and connection URLs are never printed."""
import os

from . import config
from .db import engine
from .migrate import ensure_schema_current
from .payments.paypal import REQUIRED_ENVIRONMENT
from .vault import vault_key_configured


def integration_checks(environ):
    names = (*REQUIRED_ENVIRONMENT, "GROQ_API_KEY")
    return [(name, bool(environ.get(name, "").strip())) for name in names]


def main():
    checks = []
    try:
        ensure_schema_current(engine)
        checks.append(("Database connection and migration head", True))
    except Exception:
        checks.append(("Database connection and migration head; check PostgreSQL and run migrations", False))
    checks.append(("Built frontend; run npm.cmd --prefix apps/web run build", (config.WEB_DIST / "index.html").is_file()))
    checks.extend(integration_checks(os.environ))
    checks.append(("VAULT_ENCRYPTION_KEY (Fernet)", vault_key_configured(os.environ)))
    if config.ACCESS_REQUIRED:
        checks.append(("Application access key", len(config.APP_ACCESS_KEY) >= 32))
    for name, ready in checks:
        print(f"{'OK' if ready else 'MISSING'}: {name}")
    diag = config.ENV_DIAGNOSTICS
    print(f"ENV: loaded={diag['loaded_env_path']}")
    print(
        f"PAYPAL_MERCHANT_ID: length={diag['merchant_length']} "
        f"masked={diag['masked_merchant_id']}"
    )
    if diag.get("stale_os_conflict"):
        print(f"WARNING: {diag['stale_os_conflict']}")
    if diag.get("inner_outer_conflict"):
        print(f"WARNING: {diag['inner_outer_conflict']}")
    print("This is a configuration check. It does not verify live provider calls or webhook delivery.")
    return 0 if all(ready for _, ready in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
