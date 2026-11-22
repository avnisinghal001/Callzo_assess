"""Who is making this request. Set by the middleware and the auth dependency, read by audit."""

from contextvars import ContextVar

request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
actor: ContextVar[str] = ContextVar("actor", default="system")
