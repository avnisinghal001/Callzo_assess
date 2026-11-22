from datetime import timedelta
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from app.core.timeutil import utc_now
from app.core.types import ID_PATTERN

MAX_DURATION_SECONDS = 7 * 24 * 3600
MAX_COST_CENTS = 10**9
MAX_FUTURE_SKEW = timedelta(hours=24)


class CallEventIn(BaseModel):
    """Strict on purpose: "120" is not an integer, a naive timestamp is not a timestamp.
    Unknown extra fields are ignored so the provider can add some without breaking us."""

    model_config = ConfigDict(strict=True, extra="ignore", frozen=True)

    event_id: str = Field(pattern=ID_PATTERN)
    event_type: Literal["call.started", "call.ended", "call.failed"]
    account_id: str = Field(pattern=ID_PATTERN)
    call_id: str = Field(pattern=ID_PATTERN)
    timestamp: AwareDatetime
    duration_seconds: int = Field(ge=0, le=MAX_DURATION_SECONDS)
    cost_cents: int = Field(ge=0, le=MAX_COST_CENTS)
    destination_country: str = Field(pattern=r"^[A-Za-z]{2,8}$")

    @field_validator("timestamp")
    @classmethod
    def not_far_in_the_future(cls, value: AwareDatetime) -> AwareDatetime:
        if value - utc_now() > MAX_FUTURE_SKEW:
            raise ValueError("timestamp is in the future")
        return value
