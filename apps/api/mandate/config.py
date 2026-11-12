import os
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values, load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[3]
INNER_ENV_PATH = REPO_ROOT / ".env"
OUTER_ENV_PATH = REPO_ROOT.parent / ".env"


def normalize_merchant_id(value: str | None) -> str:
    """Strip whitespace and matching surrounding quotes, then uppercase a PayPal merchant ID."""
    if not isinstance(value, str):
        return ""
    cleaned = value.strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {"'", '"'}:
        cleaned = cleaned[1:-1].strip()
    return cleaned.upper()


def mask_merchant_id(value: str | None) -> str:
    """Mask a PayPal merchant ID to first 3 and last 3 characters (e.g. ABC...XYZ)."""
    cleaned = normalize_merchant_id(value)
    if not cleaned:
        return "(empty)"
    if len(cleaned) <= 6:
        return "***"
    return f"{cleaned[:3]}...{cleaned[-3:]}"


def load_environment(
    env_path: Path | None = None,
    *,
    allow_override: bool | None = None,
    inner_path: Path = INNER_ENV_PATH,
    outer_path: Path = OUTER_ENV_PATH,
) -> dict[str, object]:
    """Load .env safely, preferring .env over stale OS vars in local development, and detect conflicts."""
    if env_path is not None:
        chosen = env_path
    elif (Path.cwd() / ".env").is_file():
        chosen = Path.cwd() / ".env"
    elif inner_path.is_file():
        chosen = inner_path
    else:
        chosen = None

    pre_existing_merchant = normalize_merchant_id(os.environ.get("PAYPAL_MERCHANT_ID"))
    file_merchant = ""
    if chosen is not None and chosen.is_file():
        file_values = dotenv_values(chosen)
        file_merchant = normalize_merchant_id(file_values.get("PAYPAL_MERCHANT_ID"))

    if allow_override is None:
        should_override = not os.getenv("PYTEST_CURRENT_TEST") and os.getenv("APP_ENV", "development").lower() == "development"
    else:
        should_override = allow_override

    if chosen is not None and chosen.is_file():
        load_dotenv(chosen, override=should_override)

    effective_merchant = normalize_merchant_id(os.getenv("PAYPAL_MERCHANT_ID", ""))
    if effective_merchant:
        os.environ["PAYPAL_MERCHANT_ID"] = effective_merchant

    stale_os_conflict: str | None = None
    if pre_existing_merchant and file_merchant and pre_existing_merchant != file_merchant:
        resolution = "overridden by .env" if should_override else "stale OS env retained"
        stale_os_conflict = (
            f"OS env PAYPAL_MERCHANT_ID ({mask_merchant_id(pre_existing_merchant)}) "
            f"conflicts with .env ({mask_merchant_id(file_merchant)}); {resolution}"
        )

    inner_outer_conflict: str | None = None
    if inner_path.is_file() and outer_path.is_file() and inner_path.resolve() != outer_path.resolve():
        inner_m = normalize_merchant_id(dotenv_values(inner_path).get("PAYPAL_MERCHANT_ID"))
        outer_m = normalize_merchant_id(dotenv_values(outer_path).get("PAYPAL_MERCHANT_ID"))
        if inner_m and outer_m and inner_m != outer_m:
            inner_outer_conflict = (
                f"Inner .env ({inner_path}) has PAYPAL_MERCHANT_ID={mask_merchant_id(inner_m)} "
                f"while outer .env ({outer_path}) has {mask_merchant_id(outer_m)}"
            )

    return {
        "loaded_env_path": str(chosen) if chosen is not None else "(none)",
        "override_applied": should_override,
        "merchant_length": len(effective_merchant),
        "masked_merchant_id": mask_merchant_id(effective_merchant),
        "stale_os_conflict": stale_os_conflict,
        "inner_outer_conflict": inner_outer_conflict,
    }


ENV_DIAGNOSTICS = load_environment()
PAYPAL_MERCHANT_ID = normalize_merchant_id(os.getenv("PAYPAL_MERCHANT_ID", ""))

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://mandate:mandate@localhost:5432/mandate")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)
if not DATABASE_URL.startswith("postgresql+psycopg://"):
    raise RuntimeError("Mandate requires PostgreSQL through psycopg; SQLite is unsupported")
if os.getenv("PAYPAL_ENV", "sandbox").lower() != "sandbox":
    raise RuntimeError("Only PayPal sandbox is permitted")
if os.getenv("PAYPAL_BASE_URL", "https://api-m.sandbox.paypal.com") != "https://api-m.sandbox.paypal.com":
    raise RuntimeError("Only the PayPal sandbox API is permitted")

PAYPAL_CONFIGURED = all(os.getenv(name, "").strip() for name in ("PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "PAYPAL_MERCHANT_ID"))
VAULT_ENCRYPTION_KEY = os.getenv("VAULT_ENCRYPTION_KEY", "").strip()
VAULT_AUTONOMY_VERIFIED = os.getenv("VAULT_AUTONOMY_VERIFIED", "false").strip().lower() == "true"
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", os.getenv("APP_BASE_URL", "http://localhost:5173")).rstrip("/")
APP_ENV = os.getenv("APP_ENV", "development").lower()
if APP_ENV not in {"development", "test", "production"}:
    raise RuntimeError("APP_ENV must be development, test, or production")
PRODUCTION = APP_ENV == "production"
PUBLIC_DEMO = os.getenv("PUBLIC_DEMO", "false").lower() == "true"
APP_ACCESS_KEY = os.getenv("APP_ACCESS_KEY", "")
ACCESS_REQUIRED = (PRODUCTION or bool(APP_ACCESS_KEY)) and not PUBLIC_DEMO
DAILY_LLM_RUN_LIMIT = max(1, int(os.getenv("DAILY_LLM_RUN_LIMIT", "50")))
SESSION_SECONDS = 8 * 60 * 60
MAX_REQUEST_BYTES = 128 * 1024
WEB_DIST = Path(os.getenv("WEB_DIST", str(Path.cwd() / "apps/web/dist"))).resolve()
_public = urlsplit(PUBLIC_BASE_URL)
if _public.scheme not in {"http", "https"} or not _public.hostname or _public.username or _public.password or _public.query or _public.fragment or _public.path not in {"", "/"}:
    raise RuntimeError("PUBLIC_BASE_URL must be an HTTP(S) origin without credentials or a path")
if PRODUCTION and (not COOKIE_SECURE or _public.scheme != "https" or (not PUBLIC_DEMO and len(APP_ACCESS_KEY) < 32)):
    raise RuntimeError("Production requires HTTPS PUBLIC_BASE_URL, COOKIE_SECURE=true, and APP_ACCESS_KEY of at least 32 characters (unless PUBLIC_DEMO=true)")
ALLOWED_ORIGINS = {PUBLIC_BASE_URL}
if not PRODUCTION:
    ALLOWED_ORIGINS.update({"http://localhost:5173", "http://127.0.0.1:5173", "http://testserver"})
_extra_hosts = {host.strip() for host in os.getenv("ALLOWED_HOSTS", "").split(",") if host.strip()}
ALLOWED_HOSTS = list({_public.hostname, "localhost", "127.0.0.1"} | _extra_hosts | ({"testserver"} if not PRODUCTION else set()))
