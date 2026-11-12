import os
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

load_dotenv(Path.cwd() / ".env")

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
