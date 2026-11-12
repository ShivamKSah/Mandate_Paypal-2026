from uuid import uuid4
import logging
import time

from fastapi import HTTPException
from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from . import config
from .db import SessionLocal
from .rate_limits import consume

logger = logging.getLogger("mandate.http")


def enforce_http_rate(identity):
    with SessionLocal() as db:
        try:
            consume(db, "http", identity, 120)
        except HTTPException:
            db.commit()
            raise
        db.commit()


class HttpBoundary:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request_id, started = uuid4().hex, time.monotonic()
        headers = Headers(scope=scope)
        status = 500

        async def send_headers(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                h = MutableHeaders(scope=message)
                h["X-Request-ID"] = request_id
                h["X-Content-Type-Options"] = "nosniff"
                h["X-Frame-Options"] = "DENY"
                h["Referrer-Policy"] = "no-referrer"
                h["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
                if scope["path"].startswith("/api/"):
                    h["Cache-Control"] = "no-store"
                if config.PRODUCTION:
                    h["Strict-Transport-Security"] = "max-age=31536000"
                    h["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
            await send(message)

        async def reject(code, detail, extra=None):
            await JSONResponse({"detail": detail}, status_code=code, headers=extra)(scope, receive, send_headers)

        try:
            if config.PRODUCTION and scope["path"].startswith("/api/") and scope["method"] not in {"GET", "HEAD", "OPTIONS"} and scope["path"] != "/api/webhooks/paypal":
                origin = headers.get("origin")
                if origin not in config.ALLOWED_ORIGINS:
                    return await reject(403, "A same-origin browser request is required")
                # A separate transaction counts rejected requests across processes.
                try:
                    await run_in_threadpool(enforce_http_rate, (scope.get("client") or ("unknown",))[0])
                except HTTPException as exc:
                    return await reject(exc.status_code, exc.detail, exc.headers)
            body, size = [], 0
            while True:
                chunk = await receive()
                if chunk["type"] == "http.disconnect":
                    return
                data = chunk.get("body", b"")
                size += len(data)
                if size > config.MAX_REQUEST_BYTES:
                    return await reject(413, "Request body exceeds the allowed size")
                body.append(data)
                if not chunk.get("more_body", False):
                    break
            buffered = b"".join(body)
            delivered = False

            async def replay():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": buffered, "more_body": False}
                return await receive()

            await self.app(scope, replay, send_headers)
        except Exception as exc:
            logger.error("request_failed request_id=%s error_type=%s", request_id, type(exc).__name__)
            raise
        finally:
            logger.info("request request_id=%s method=%s path=%s status=%s duration_ms=%d", request_id,
                        scope["method"], scope["path"], status, int((time.monotonic() - started) * 1000))
