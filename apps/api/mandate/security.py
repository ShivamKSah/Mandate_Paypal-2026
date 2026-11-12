import secrets
import hashlib

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from .db import get_db
from .models import Session
from .models import now
from . import config

COOKIE_NAME = "mandate_session"


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def check_origin(request: Request):
    origin = request.headers.get("origin")
    if (origin is not None and origin not in config.ALLOWED_ORIGINS) or (config.PRODUCTION and origin is None):
        raise HTTPException(403, "A same-origin browser request is required")


def find_session(request: Request, db: DBSession, *, lock=False):
    token = request.cookies.get(COOKIE_NAME, "")
    query = select(Session).where(Session.token_hash == token_digest(token), Session.expires_at > now(), Session.revoked_at.is_(None))
    if config.ACCESS_REQUIRED:
        query = query.where(Session.authenticated.is_(True))
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return db.scalar(query) if token else None


def human(request: Request, db: DBSession = Depends(get_db)) -> Session:
    # A capability must never inherit authority from a browser cookie.
    if request.headers.get("authorization"):
        raise HTTPException(403, "Agent credentials cannot perform human actions")
    mutation = request.method not in {"GET", "HEAD"}
    owner = find_session(request, db, lock=mutation)
    if owner is None:
        raise HTTPException(401, "Create a session first")
    if mutation:
        check_origin(request)
        token = request.headers.get("x-csrf-token", "")
        if not secrets.compare_digest(owner.csrf_token.encode(), token.encode()):
            raise HTTPException(403, "Invalid CSRF token")
    return owner


def owned(db, model, entity_id, owner, *, lock=False):
    query = select(model).where(model.id == entity_id, model.session_id == owner.id)
    record = db.scalar(query.with_for_update() if lock else query)
    if record is None:
        raise HTTPException(404, "Record not found")
    return record
