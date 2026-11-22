import psycopg
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.core.errors import AppError
from app.modules.webhooks import service
from app.modules.webhooks.verification import verified_body

router = APIRouter(tags=["webhooks"])

_STATUS = {"accepted": 202, "duplicate": 200}


@router.post("/webhooks/calls")
def receive_call_event(request: Request, body: bytes = Depends(verified_body)) -> JSONResponse:
    metrics = request.app.state.metrics
    try:
        with request.app.state.pool.connection() as conn:  # commits before we answer
            result = service.ingest(conn, body)
    except AppError as exc:
        metrics.webhook(exc.code)
        raise
    except psycopg.OperationalError:
        metrics.webhook("unavailable")  # answered 503: nothing stored, the provider redelivers
        raise
    metrics.webhook(result.outcome)
    return JSONResponse(
        {"status": result.outcome, "event_id": result.event_id}, status_code=_STATUS[result.outcome]
    )
