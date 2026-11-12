from datetime import timedelta
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import Field
from sqlalchemy.orm import Session as DBSession
from sqlalchemy import select, text

from . import config
from .db import get_db
from .models import Session, now
from .rate_limits import consume
from .schemas import Input
from .security import COOKIE_NAME, check_origin, find_session, human, token_digest

router = APIRouter(prefix="/api")


class LoginInput(Input):
    access_key: str = Field(min_length=1, max_length=1024)


def session_view(owner):
    return {"id": owner.id, "csrf_token": owner.csrf_token, "authenticated": owner.authenticated,
            "access_required": config.ACCESS_REQUIRED, "mode": "sandbox" if config.PAYPAL_CONFIGURED else "unconfigured",
            "paypal_configured": config.PAYPAL_CONFIGURED}


def create_session(db, response, authenticated, owner=None):
    token = secrets.token_urlsafe(32)
    if owner is None:
        owner = Session(operator_key="operator" if authenticated else None)
        db.add(owner)
    owner.token_hash = token_digest(token)
    owner.csrf_token = secrets.token_urlsafe(32)
    owner.authenticated = authenticated
    owner.expires_at = now() + timedelta(seconds=config.SESSION_SECONDS)
    owner.revoked_at = None
    db.flush()
    response.set_cookie(COOKIE_NAME, token, httponly=True, secure=config.COOKIE_SECURE, samesite="strict", max_age=config.SESSION_SECONDS)
    return session_view(owner)


@router.get("/session")
def session(request: Request, response: Response, db: DBSession = Depends(get_db)):
    if request.headers.get("authorization"):
        raise HTTPException(403, "Agent credentials cannot create human sessions")
    owner = find_session(request, db)
    if owner:
        return session_view(owner)
    if config.ACCESS_REQUIRED:
        raise HTTPException(401, "Sign in with the application access key")
    return create_session(db, response, False)


@router.post("/login")
def login(body: LoginInput, request: Request, response: Response, db: DBSession = Depends(get_db)):
    check_origin(request)
    if request.headers.get("authorization"):
        raise HTTPException(403, "Agent credentials cannot sign in")
    try:
        consume(db, "login", request.client.host if request.client else "unknown", 5)
    except HTTPException:
        db.commit()
        raise
    db.commit()  # Failed attempts must count even when the response is an error.
    if not config.APP_ACCESS_KEY or not secrets.compare_digest(body.access_key.encode(), config.APP_ACCESS_KEY.encode()):
        raise HTTPException(401, "Invalid application access key")
    # This deployment has one operator credential and one durable operator workspace.
    db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": "mandate:operator-login"})
    owner = db.scalar(select(Session).where(Session.operator_key == "operator").with_for_update())
    return create_session(db, response, True, owner)


@router.post("/logout", status_code=204)
def logout(response: Response, owner=Depends(human)):
    owner.revoked_at = now()
    response.delete_cookie(COOKIE_NAME, secure=config.COOKIE_SECURE, httponly=True, samesite="strict")
