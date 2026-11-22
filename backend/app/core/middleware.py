"""Request id, one structured access log line, and a latency histogram for every request.

Pure ASGI (not BaseHTTPMiddleware), so request bodies still stream straight to the route.
"""

import re
import time
import uuid

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core import context

log = structlog.get_logger()
_SAFE_ID = re.compile(r"^[A-Za-z0-9_.-]{8,64}$")
_QUIET = ("/health/", "/metrics", "/console")  # polled constantly; measured, not logged


class RequestContext:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.lower(): v for k, v in scope["headers"]}
        incoming = headers.get(b"x-request-id", b"").decode("latin-1")
        request_id = incoming if _SAFE_ID.match(incoming) else uuid.uuid4().hex
        context.request_id.set(request_id)
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        status = 500
        started = time.perf_counter()

        async def send_with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message["headers"] = [*message["headers"], (b"x-request-id", request_id.encode())]
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            seconds = time.perf_counter() - started
            route = getattr(scope.get("route"), "path", "unmatched")  # template, not raw path
            metrics = getattr(scope["app"].state, "metrics", None)
            if metrics is not None:
                metrics.observe_request(scope["method"], route, status, seconds)
            if not scope["path"].startswith(_QUIET):
                log.info(
                    "request",
                    method=scope["method"],
                    route=route,
                    status=status,
                    ms=round(seconds * 1000, 1),
                )
