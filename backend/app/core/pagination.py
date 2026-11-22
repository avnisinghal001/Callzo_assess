"""Opaque keyset cursors. Clients treat them as strings; we encode (timestamp, uuid)."""

import base64
import binascii
from datetime import datetime
from uuid import UUID

from app.core.errors import ValidationFailed


def encode_cursor(moment: datetime, row_id: UUID) -> str:
    raw = f"{moment.isoformat()}|{row_id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(token: str) -> tuple[datetime, UUID]:
    try:
        padded = token + "=" * (-len(token) % 4)
        stamp, _, row_id = base64.urlsafe_b64decode(padded).decode().partition("|")
        return datetime.fromisoformat(stamp), UUID(row_id)
    except (binascii.Error, ValueError, UnicodeDecodeError):
        raise ValidationFailed("Invalid cursor") from None
