import asyncio
from datetime import timedelta
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field
from sqlalchemy import select

from ..audit import append
from ..catalog import CATALOG
from ..db import SessionLocal
from ..models import AuditEvent, Mandate, Session, now
from ..proposals import submit, view
from ..schemas import Input, ProposalInput
from ..security import human, owned
from ..rate_limits import consume
from .runner import AgentError, configuration, select_purchase

router = APIRouter(prefix="/api")
_capacity = asyncio.Semaphore(2)


class AgentInput(Input):
    mandate_id: str = Field(min_length=1, max_length=80)
    instruction: str = Field(min_length=1, max_length=4000)


@router.post("/agent-runs")
async def run(body: AgentInput, request: Request):
    if _capacity.locked():
        raise HTTPException(429, "Shopping agents are busy; retry shortly")
    run_id = str(uuid4())
    with SessionLocal() as db, db.begin():
        owner = human(request, db)
        grant = owned(db, Mandate, body.mandate_id, owner)
        if grant.status != "ACTIVE" or grant.expires_at <= now():
            raise HTTPException(409, "The grant is inactive or expired")
        try:
            configuration()
        except AgentError as exc:
            raise HTTPException(exc.status_code, str(exc)) from exc
        consume(db, "model-global", "all", 10)
        consume(db, "model-session", owner.id, 3)
        constraints, owner_id, auth_version = dict(grant.constraints), owner.id, owner.csrf_token
        append(db, owner, "AGENT_RUN_STARTED", run_id, {"mandate_id": grant.id})
    # No database lock or transaction spans the model request.
    try:
        async with _capacity:
            selection = await select_purchase(body.instruction, list(CATALOG.values()), constraints)
    except AgentError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    with SessionLocal() as db, db.begin():
        owner = db.scalar(select(Session).where(Session.id == owner_id).with_for_update())
        if owner is None:
            raise HTTPException(401, "Session no longer exists")
        if owner.revoked_at is not None or owner.expires_at <= now() or owner.csrf_token != auth_version:
            raise HTTPException(401, "Session expired while the agent was running")
        proposal_input = ProposalInput(mandate_id=body.mandate_id, purchase_intent_id=f"agent-{run_id}",
                                       items=[item.model_dump() for item in selection.items])
        proposal = submit(db, owner, proposal_input)
        append(db, owner, "AGENT_PROPOSAL_SUBMITTED", proposal.id, {"run_id": run_id})
        return {"summary": selection.explanation, "proposal": view(db, proposal)}
