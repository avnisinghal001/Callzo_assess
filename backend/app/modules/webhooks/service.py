from dataclasses import dataclass
from typing import Literal

import structlog
from pydantic import ValidationError

from app.core.db import Conn
from app.core.errors import BadRequest, Conflict, ValidationFailed, describe_validation_errors
from app.modules.inbox import repository as inbox
from app.modules.inbox.models import NewEvent
from app.modules.webhooks.schemas import CallEventIn

log = structlog.get_logger()


@dataclass(frozen=True)
class IngestResult:
    outcome: Literal["accepted", "duplicate"]
    event_id: str


def parse_event(body: bytes) -> CallEventIn:
    try:
        return CallEventIn.model_validate_json(body)
    except ValidationError as exc:
        errors = exc.errors()
        if any(e["type"] == "json_invalid" for e in errors):
            raise BadRequest("Body is not valid JSON") from None
        raise ValidationFailed("Invalid event", fields=describe_validation_errors(errors)) from None


def to_new_event(parsed: CallEventIn, source: str) -> NewEvent:
    return NewEvent(
        provider_event_id=parsed.event_id,
        event_type=parsed.event_type,
        account_external_id=parsed.account_id,
        provider_call_id=parsed.call_id,
        occurred_at=parsed.timestamp,
        duration_seconds=parsed.duration_seconds,
        cost_cents=parsed.cost_cents,
        destination_country=parsed.destination_country,
        metadata={"source": source},
    )


def store(conn: Conn, event: NewEvent, raw_body: bytes) -> IngestResult:
    """Store exactly once. Metering happens later, in the worker."""
    if inbox.insert_event(conn, event, raw_body):
        log.info(
            "event_accepted",
            event_id=event.provider_event_id,
            account=event.account_external_id,
            call=event.provider_call_id,
            type=event.event_type,
            source=event.metadata.get("source"),
        )
        return IngestResult("accepted", event.provider_event_id)

    if inbox.is_same_event(conn, event):
        log.info("event_duplicate", event_id=event.provider_event_id)
        return IngestResult("duplicate", event.provider_event_id)

    log.error("event_id_reused_with_different_content", event_id=event.provider_event_id)
    raise Conflict("event_id already used with different content")


def ingest(conn: Conn, body: bytes) -> IngestResult:
    """Validate, then store. Used by the signed webhook route."""
    return store(conn, to_new_event(parse_event(body), "webhook"), body)
