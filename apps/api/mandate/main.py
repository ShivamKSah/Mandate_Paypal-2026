import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session as DBSession

from . import models
from .catalog import CATALOG
from . import config
from .attacks import router as attacks_router
from .db import engine, get_db
from .proposals import router as proposals_router
from .resources import router as resources_router
from .sessions import router as sessions_router
from .http_boundary import HttpBoundary
from .agents.router import router as agents_router
from .integrations_api import router as integrations_router
from .payments_api import router as payments_router
from .recovery import router as recovery_router
from .reconciliation import poll
from .webhooks import router as webhooks_router


@asynccontextmanager
async def lifespan(app):
    if not getattr(app.state, "testing", False):
        from .migrate import ensure_schema_current
        ensure_schema_current(engine)
        if config.PRODUCTION and not (config.WEB_DIST / "index.html").is_file():
            raise RuntimeError("Build the frontend before starting production mode")
    stop = asyncio.Event()
    worker = asyncio.create_task(poll(stop))
    app.state.payment_worker = worker
    try:
        yield
    finally:
        stop.set()
        await worker


app = FastAPI(title="Mandate sandbox API", lifespan=lifespan, docs_url=None if config.PRODUCTION else "/docs",
              redoc_url=None, openapi_url=None if config.PRODUCTION else "/openapi.json")
app.add_middleware(TrustedHostMiddleware, allowed_hosts=config.ALLOWED_HOSTS)
app.add_middleware(HttpBoundary)
app.include_router(sessions_router)
app.include_router(resources_router)
app.include_router(proposals_router)
app.include_router(agents_router)
app.include_router(payments_router)
app.include_router(recovery_router)
app.include_router(webhooks_router)
app.include_router(attacks_router)
app.include_router(integrations_router)


@app.exception_handler(SQLAlchemyError)
async def database_unavailable(request, error):
    return JSONResponse({"detail": "Database unavailable; retry later"}, status_code=503)


@app.get("/api/health")
def health(db: DBSession = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "postgresql"}


@app.get("/api/ready")
def ready(db: DBSession = Depends(get_db)):
    db.execute(text("SELECT 1"))
    if config.PRODUCTION and not (config.WEB_DIST / "index.html").is_file():
        raise HTTPException(503, "Frontend build is missing")
    worker = getattr(app.state, "payment_worker", None)
    if worker is not None and worker.done():
        raise HTTPException(503, "Payment reconciliation worker is unavailable")
    return {"status": "ready", "payments": "configured" if config.PAYPAL_CONFIGURED else "unconfigured"}


@app.get("/api/catalog")
def catalog():
    return list(CATALOG.values())


if (config.WEB_DIST / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=config.WEB_DIST / "assets"), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def frontend(path: str):
    if path.startswith("api/"):
        raise HTTPException(404, "API route not found")
    if path == "favicon.svg" and (config.WEB_DIST / path).is_file():
        return FileResponse(config.WEB_DIST / path)
    if not (config.WEB_DIST / "index.html").is_file():
        raise HTTPException(404, "Build the frontend first or use the local Vite server")
    return FileResponse(config.WEB_DIST / "index.html", headers={"Cache-Control": "no-cache"})
