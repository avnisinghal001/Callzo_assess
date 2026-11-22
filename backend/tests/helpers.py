import hashlib
import hmac
import json
from datetime import UTC, datetime

from tests.conftest import WEBHOOK_SECRET


def sign(body: bytes, secret: str = WEBHOOK_SECRET) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


def event(
    event_id: str,
    event_type: str = "call.ended",
    *,
    call_id: str = "call_1",
    account_id: str = "acct_001",
    timestamp: str = "2026-11-10T10:00:00+00:00",
    duration: int | None = None,
    cost: int | None = None,
) -> dict:
    ended = event_type == "call.ended"
    return {
        "event_id": event_id,
        "event_type": event_type,
        "account_id": account_id,
        "call_id": call_id,
        "timestamp": timestamp,
        "duration_seconds": (60 if duration is None else duration) if ended else 0,
        "cost_cents": (2 if cost is None else cost) if ended else 0,
        "destination_country": "US",
    }


def body_of(payload: dict) -> bytes:
    return json.dumps(payload).encode()


def account_uuid(conn, external_id: str = "acct_001"):
    row = conn.execute("SELECT id FROM accounts WHERE external_id = %s", (external_id,)).fetchone()
    conn.commit()
    return row["id"]
