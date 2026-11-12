import hashlib
import json
from datetime import timezone

from sqlalchemy import select

from .models import AuditEvent, Session, now, uid


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def event_payload(event):
    return {"id": event.id, "sequence": event.sequence, "event_type": event.event_type,
            "entity_id": event.entity_id, "details": event.details, "created_at": event.created_at.astimezone(timezone.utc).isoformat(),
            "prev_hash": event.prev_hash}


def append(db, owner, event_type, entity_id, details):
    db.flush()
    owner = db.scalar(select(Session).where(Session.id == owner.id).with_for_update().execution_options(populate_existing=True))
    event = AuditEvent(id=uid(), session_id=owner.id, sequence=owner.audit_count + 1,
                       event_type=event_type, entity_id=entity_id, details=details,
                       created_at=now(), prev_hash=owner.audit_head)
    event.row_hash = digest(event_payload(event))
    db.add(event)
    owner.audit_count += 1
    owner.audit_head = event.row_hash
    return event


def verify(db, owner):
    owner = db.scalar(select(Session).where(Session.id == owner.id).with_for_update().execution_options(populate_existing=True))
    events = db.scalars(select(AuditEvent).where(AuditEvent.session_id == owner.id).order_by(AuditEvent.sequence)).all()
    previous, valid = "0" * 64, True
    for sequence, event in enumerate(events, 1):
        valid = valid and event.sequence == sequence and event.prev_hash == previous and event.row_hash == digest(event_payload(event))
        previous = event.row_hash
    return {"valid": bool(valid and previous == owner.audit_head and len(events) == owner.audit_count),
            "event_count": len(events), "checkpoint": owner.audit_head}
