from app.core.security import api_key_is_valid, signature_is_valid
from tests.helpers import sign

SECRET = "s" * 20
BODY = b'{"a": 1}'


def test_valid_signature():
    assert signature_is_valid(SECRET, BODY, sign(BODY, SECRET))


def test_signature_is_over_raw_bytes_not_reserialized_json():
    reserialized = b'{"a":1}'
    assert not signature_is_valid(SECRET, reserialized, sign(BODY, SECRET))


def test_rejects_missing_wrong_garbage_and_non_ascii():
    for provided in (None, "", "0" * 64, "zz", "é" * 64):
        assert not signature_is_valid(SECRET, BODY, provided)


def test_signature_is_case_and_whitespace_tolerant_but_exact():
    assert signature_is_valid(SECRET, BODY, f" {sign(BODY, SECRET).upper()} ")
    assert not signature_is_valid(SECRET, BODY, sign(BODY, SECRET)[:-1])


def test_api_key():
    assert api_key_is_valid("k" * 20, "Bearer " + "k" * 20)
    assert api_key_is_valid("k" * 20, "bearer " + "k" * 20)
    for header in (None, "", "Bearer", "Bearer wrong", "Basic " + "k" * 20, "k" * 20):
        assert not api_key_is_valid("k" * 20, header)
