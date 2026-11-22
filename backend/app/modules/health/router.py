from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

router = APIRouter(tags=["ops"])


@router.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
def ready(request: Request) -> JSONResponse:
    try:
        with request.app.state.pool.connection(timeout=2) as conn:
            conn.execute("SELECT 1")
    except Exception:
        return JSONResponse({"status": "database_unavailable"}, status_code=503)
    return JSONResponse({"status": "ok"})


@router.get("/metrics")
def metrics(request: Request) -> Response:
    return Response(
        generate_latest(request.app.state.metrics.registry), media_type=CONTENT_TYPE_LATEST
    )
