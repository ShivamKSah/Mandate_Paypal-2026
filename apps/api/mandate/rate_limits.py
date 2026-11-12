from datetime import timedelta
import hashlib

from fastapi import HTTPException
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert

from .models import RateLimitBucket, now


def consume(db, scope: str, identity: str, limit: int, seconds: int = 60):
    timestamp = now()
    window = int(timestamp.timestamp()) // seconds
    key = f"{scope}:{hashlib.sha256(identity.encode()).hexdigest()}:{window}"
    statement = insert(RateLimitBucket).values(key=key, count=1, expires_at=timestamp + timedelta(seconds=seconds * 2))
    count = db.scalar(statement.on_conflict_do_update(index_elements=[RateLimitBucket.key],
                                                     set_={"count": RateLimitBucket.count + 1}).returning(RateLimitBucket.count))
    db.execute(delete(RateLimitBucket).where(RateLimitBucket.expires_at < timestamp))
    if count > limit:
        raise HTTPException(429, "Request limit reached; retry later", headers={"Retry-After": str(seconds)})
