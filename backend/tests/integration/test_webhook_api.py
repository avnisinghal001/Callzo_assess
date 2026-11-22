import json

import pytest

from tests.helpers import body_of, event, sign


def count_events(conn) -> int:
    return conn.execute("SELECT count(*) AS n FROM call_events").fetchone()["n"]


def test_valid_event_is_accepted_and_stored_once(post, conn):
    response = post(event("evt_1"))
    assert response.status_code == 202 and response.json()["status"] == "accepted"
    assert count_events(conn) == 1


def test_duplicates_are_acknowledged_but_stored_once(post, conn):
    assert post(event("evt_1")).status_code == 202
    assert [post(event("evt_1")).status_code for _ in range(3)] == [200, 200, 200]
    assert count_events(conn) == 1


@pytest.mark.parametrize("change", [{"duration_seconds": 61}, {"destination_country": "CA"}])
def test_same_event_id_with_different_content_is_a_conflict(post, conn, change):
    original = event("evt_1", duration=60)
    assert post(original).status_code == 202
    response = post({**original, **change})
    assert response.status_code == 409 and response.json()["error"]["code"] == "conflict"
    assert count_events(conn) == 1


@pytest.mark.parametrize("kind", ["missing", "wrong", "garbage"])
def test_bad_signature_is_rejected_before_anything_is_stored(client, conn, kind):
    body = body_of(event("evt_1"))
    headers = {
        "missing": {},
        "wrong": {"X-Signature": "0" * 64},
        "garbage": {"X-Signature": "not-a-signature"},
    }
    response = client.post("/webhooks/calls", content=body, headers=headers[kind])
    assert response.status_code == 401 and count_events(conn) == 0


def test_signature_is_checked_before_the_payload_is_parsed(post, conn):
    # Unsigned and malformed: must be 401, never a 400/422 that reveals parsing happened.
    assert post(None, signed=False, raw=b"{not json").status_code == 401


def test_a_valid_signature_over_the_wrong_bytes_is_rejected(client, conn):
    body = body_of(event("evt_1"))
    response = client.post(
        "/webhooks/calls", content=body + b" ", headers={"X-Signature": sign(body)}
    )
    assert response.status_code == 401 and count_events(conn) == 0


@pytest.mark.parametrize(
    ("raw", "status"),
    [
        (b"", 400),
        (b'{"event_id": "evt_1", "event_type": "call.sta', 400),  # truncated
        (b"[]", 422),
        (b"null", 422),
    ],
)
def test_malformed_bodies_are_client_errors(post, conn, raw, status):
    assert post(None, raw=raw).status_code == status and count_events(conn) == 0


@pytest.mark.parametrize(
    "mutate",
    [
        lambda e: e.pop("event_id"),
        lambda e: e.pop("timestamp"),
        lambda e: e.update(event_type="call.exploded"),
        lambda e: e.update(duration_seconds="60"),
        lambda e: e.update(duration_seconds=True),
        lambda e: e.update(duration_seconds=1.5),
        lambda e: e.update(cost_cents=-1),
        lambda e: e.update(cost_cents=10**12),
        lambda e: e.update(timestamp="2026-11-10T10:00:00"),  # no timezone
        lambda e: e.update(timestamp="2999-01-01T00:00:00+00:00"),  # far future
        lambda e: e.update(account_id="acct 001"),
        lambda e: e.update(call_id="x\u0000y"),
        lambda e: e.update(event_id=""),
    ],
)
def test_invalid_fields_are_422_without_echoing_input(post, conn, mutate):
    payload = event("evt_1")
    mutate(payload)
    response = post(payload)
    assert response.status_code == 422 and count_events(conn) == 0
    error = response.json()["error"]
    assert error["code"] == "validation_error" and error["fields"]
    assert "acct 001" not in json.dumps(error)


def test_unknown_extra_fields_are_ignored(post):
    assert post({**event("evt_1"), "carrier": "x"}).status_code == 202


def test_oversized_body_is_rejected(client):
    body = b"x" * 5000  # limit is 4096 in tests
    response = client.post("/webhooks/calls", content=body, headers={"X-Signature": sign(body)})
    assert response.status_code == 413
