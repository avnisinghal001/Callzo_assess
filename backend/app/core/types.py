"""Shared validated types, so every module agrees on what an identifier or metadata is."""

import json
from typing import Annotated, Any

from fastapi import Path
from pydantic import AfterValidator

# Letters, digits and a few separators. Excludes NUL and whitespace by construction.
ID_PATTERN = r"^[A-Za-z0-9_.:-]{1,128}$"

AccountIdPath = Annotated[str, Path(pattern=ID_PATTERN)]

MAX_METADATA_BYTES = 8 * 1024  # the database allows 16 KB; callers get half, the rest is ours


def _check_metadata_size(value: dict[str, Any]) -> dict[str, Any]:
    if len(json.dumps(value)) > MAX_METADATA_BYTES:
        raise ValueError(f"metadata larger than {MAX_METADATA_BYTES} bytes")
    return value


Metadata = Annotated[dict[str, Any], AfterValidator(_check_metadata_size)]
