from fastapi import APIRouter, Depends, Request

from app.core.errors import Forbidden
from app.core.security import require_scope
from app.modules.ops import service
from app.modules.ops.schemas import (
    Overview,
    SandboxRequest,
    SandboxResponse,
    VerifyRequest,
    VerifyResponse,
)

router = APIRouter(
    prefix="/admin/v1", tags=["admin: operations"], dependencies=[Depends(require_scope("admin"))]
)


def require_sandbox(request: Request) -> None:
    if not request.app.state.settings.enable_sandbox:
        raise Forbidden("Sandbox is disabled (set ENABLE_SANDBOX=true)")


@router.get("/overview", response_model=Overview)
def get_overview(request: Request) -> Overview:
    with request.app.state.pool.connection() as conn:
        return service.overview(conn, request.app.state.settings)


@router.post(
    "/sandbox/scenarios", response_model=SandboxResponse, dependencies=[Depends(require_sandbox)]
)
def run_scenario(request: Request, body: SandboxRequest) -> SandboxResponse:
    """Inject synthetic traffic. Disabled unless ENABLE_SANDBOX=true."""
    with request.app.state.pool.connection() as conn:
        response = service.run_scenario(conn, request.app.state.settings, body)
    for result in response.results:
        request.app.state.metrics.webhook(result.metric)
    return response


@router.post(
    "/sandbox/verify", response_model=VerifyResponse, dependencies=[Depends(require_sandbox)]
)
def verify(request: Request, body: VerifyRequest) -> VerifyResponse:
    """What a sandbox run has contributed to usage so far."""
    with request.app.state.pool.connection() as conn:
        return service.verify(conn, body)
