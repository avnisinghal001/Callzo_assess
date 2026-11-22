"""The operator console: static files served by the API itself (no build step, no container)."""

from pathlib import Path

from starlette.staticfiles import StaticFiles
from starlette.types import Scope

from app.core import console_session

STATIC_DIR = Path(__file__).parent / "static"

# No inline script or style, no third-party origins, cannot be framed.
CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
    "font-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'; "
    "frame-ancestors 'none'"
)


class ConsoleFiles(StaticFiles):
    def __init__(self) -> None:
        super().__init__(directory=STATIC_DIR, html=True)

    async def get_response(self, path: str, scope: Scope):
        response = await super().get_response(path, scope)
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-cache"
        settings = scope["app"].state.settings
        if settings.console_open_access and path in ("", ".", "index.html"):
            response.set_cookie(
                console_session.COOKIE,
                console_session.issue(settings.admin_api_key),
                max_age=console_session.LIFETIME_SECONDS,
                httponly=True,
                samesite="strict",
                secure=scope["scheme"] == "https",
            )
        return response
