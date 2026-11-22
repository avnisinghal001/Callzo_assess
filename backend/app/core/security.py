"""Authentication primitives. All comparisons are constant-time."""

import hashlib
import hmac
from typing import Literal

from fastapi import Header, Request

from app.core import console_session, context
from app.core.errors import Forbidden, Unauthorized


def signature_is_valid(secret: str, body: bytes, provided: str | None) -> bool:
    """HMAC-SHA256 over the raw bytes, hex encoded. Never over re-serialized JSON."""
    if not provided:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected.encode(), provided.strip().lower().encode())


def any_signature_is_valid(secrets: list[str], body: bytes, provided: str | None) -> bool:
    return any([signature_is_valid(s, body, provided) for s in secrets])  # list: compare all


def api_key_is_valid(expected: str, authorization: str | None) -> bool:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        return False
    return hmac.compare_digest(expected.encode(), token.strip().encode())


def key_fingerprint(key: str) -> str:
    """Identifies a key in the audit log without revealing it."""
    return hashlib.sha256(key.encode()).hexdigest()[:8]


def _has_console_session(request: Request) -> bool:
    settings = request.app.state.settings
    return (
        settings.console_open_access
        and console_session.CSRF_HEADER in request.headers
        and console_session.is_valid(
            settings.admin_api_key, request.cookies.get(console_session.COOKIE)
        )
    )


def require_scope(scope: Literal["read", "admin"]):
    """FastAPI dependency. The admin key may do everything; the read key only reads usage.
    A valid read key on an admin route is 403 (known, not allowed), anything else is 401.
    Async so that the actor it sets is visible to the route (same context)."""

    async def dependency(
        request: Request, authorization: str | None = Header(default=None)
    ) -> None:
        settings = request.app.state.settings
        if _has_console_session(request):
            context.actor.set("console")
            return
        # Every key is always compared: timing must not reveal which one matched.
        admins = [k for k in settings.admin_keys if api_key_is_valid(k, authorization)]
        readers = [k for k in settings.reader_keys if api_key_is_valid(k, authorization)]
        if admins or (scope == "read" and readers):
            role, key = ("admin", admins[0]) if admins else ("reader", readers[0])
            context.actor.set(f"{role}:{key_fingerprint(key)}")
            return
        if readers:
            raise Forbidden("This key cannot use the admin API")
        raise Unauthorized("Missing or invalid API key")

    return dependency
