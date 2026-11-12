from datetime import timedelta
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import Field
from sqlalchemy.orm import Session as DBSession
from sqlalchemy import select, text

from . import config
from .audit import append
from .db import get_db
from .models import Mandate, Session, now
from .rate_limits import consume
from .schemas import EmptyInput, LoginInput
from .security import COOKIE_NAME, check_origin, find_session, human, token_digest

router = APIRouter(prefix="/api")


def session_view(owner):
    return {"id": owner.id, "csrf_token": owner.csrf_token, "authenticated": owner.authenticated,
            "access_required": config.ACCESS_REQUIRED, "public_demo": config.PUBLIC_DEMO,
            "mode": "sandbox" if config.PAYPAL_CONFIGURED else "unconfigured",
            "paypal_configured": config.PAYPAL_CONFIGURED}


def _seed_demo_grant(db, owner):
    grant = Mandate(
        session_id=owner.id,
        status="ACTIVE",
        budget_cents=50000,
        per_transaction_cents=40000,
        allowed_categories=["furniture", "electronics"],
        allowed_merchants=["demo-merchant"],
        constraints={"width_cm": 160},
        instruction="Office furniture and electronics. Desk width must be 160 cm.",
        expires_at=now() + timedelta(minutes=60),
        velocity_limit=5,
    )
    db.add(grant)
    db.flush()
    append(db, owner, "MANDATE_CREATED", grant.id, {
        "budget_cents": grant.budget_cents,
        "constraints": grant.constraints,
        "version": grant.version,
        "seeded_demo": True,
    })


def create_session(db, response, authenticated, owner=None, *, seed_demo=False):
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
    if seed_demo:
        _seed_demo_grant(db, owner)
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
    return create_session(db, response, False, seed_demo=config.PUBLIC_DEMO)


@router.post("/session/reset")
def reset_demo_session(
    response: Response,
    body: EmptyInput = EmptyInput(),
    owner=Depends(human),
    db: DBSession = Depends(get_db),
):
    if config.PRODUCTION and not config.PUBLIC_DEMO:
        raise HTTPException(403, "Session reset is only available in public demo or development mode")
    consume(db, "demo-reset", owner.id, 10)
    owner.revoked_at = now()
    return create_session(db, response, False, seed_demo=True)


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
