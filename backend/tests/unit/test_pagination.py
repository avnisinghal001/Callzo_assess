import uuid
from datetime import UTC, datetime

import pytest

from app.core.errors import ValidationFailed
from app.core.pagination import decode_cursor, encode_cursor


def test_round_trip():
    moment, row_id = datetime(2026, 11, 22, 1, 2, 3, 456789, tzinfo=UTC), uuid.uuid4()
    assert decode_cursor(encode_cursor(moment, row_id)) == (moment, row_id)


@pytest.mark.parametrize("token", ["", "!!!", "bm90LWEtY3Vyc29y", "e30"])
def test_garbage_is_a_validation_error(token):
    with pytest.raises(ValidationFailed):
        decode_cursor(token)
