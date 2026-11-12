import asyncio
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field
from sqlalchemy import select

from ..audit import append
from ..catalog import CATALOG
from ..constraints import constraints_to_dict, extract_constraints_async
from ..db import SessionLocal
from ..models import Mandate, Session, now
from ..proposals import submit, view
from ..rate_limits import consume
from ..schemas import Input, ProposalInput
from ..security import human, owned
from .runner import AgentError, configuration, deterministic_select_purchase, select_purchase

router = APIRouter(prefix="/api")
_capacity = asyncio.Semaphore(2)


class AgentInput(Input):
    mandate_id: str = Field(min_length=1, max_length=80)
    instruction: str = Field(min_length=1, max_length=4000)
    allow_fallback: bool = False


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
        if not body.allow_fallback:
            try:
                configuration()
            except AgentError as exc:
                raise HTTPException(exc.status_code, str(exc)) from exc
        consume(db, "model-global", "all", 10)
        consume(db, "model-session", owner.id, 3)
        constraints, grant_instruction = dict(grant.constraints), grant.instruction
        owner_id, auth_version = owner.id, owner.csrf_token
        append(db, owner, "AGENT_RUN_STARTED", run_id, {"mandate_id": grant.id})

    # No database lock or transaction spans external model calls.
    llm_fallback = False
    planner_label = "GroqCloud Responses"
    try:
        async with _capacity:
            selection = await select_purchase(body.instruction, list(CATALOG.values()), constraints)
    except AgentError as exc:
        if not body.allow_fallback:
            raise HTTPException(exc.status_code, str(exc)) from exc
        llm_fallback = True
        planner_label = "Rules planner, LLM unavailable"
        selection = deterministic_select_purchase(body.instruction, list(CATALOG.values()), constraints)

    extraction = await extract_constraints_async(body.instruction)
    extracted_constraints, extraction_failed = constraints_to_dict(extraction)

    with SessionLocal() as db, db.begin():
        owner = db.scalar(select(Session).where(Session.id == owner_id).with_for_update())
        if owner is None:
            raise HTTPException(401, "Session no longer exists")
        if owner.revoked_at is not None or owner.expires_at <= now() or owner.csrf_token != auth_version:
            raise HTTPException(401, "Session expired while the agent was running")
        proposal_input = ProposalInput(
            mandate_id=body.mandate_id,
            purchase_intent_id=f"agent-{run_id}",
            items=[item.model_dump() for item in selection.items],
        )
        proposal = submit(
            db, owner, proposal_input,
            extracted_constraints=extracted_constraints,
            extraction_failed=extraction_failed,
        )
        append(db, owner, "AGENT_PROPOSAL_SUBMITTED", proposal.id, {
            "run_id": run_id,
            "llm_fallback": llm_fallback,
            "planner_label": planner_label,
        })
        return {
            "summary": selection.explanation,
            "llm_fallback": llm_fallback,
            "planner_label": planner_label,
            "proposal": view(db, proposal),
        }
