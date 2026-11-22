import random
from datetime import date, timedelta

from tests.helpers import event


def get(client, auth, path, **params):
    return client.get(f"/v1/accounts/acct_001/usage{path}", params=params, headers=auth)


def test_requires_a_valid_api_key(client):
    assert client.get("/v1/accounts/acct_001/usage").status_code == 401
    bad = client.get("/v1/accounts/acct_001/usage", headers={"Authorization": "Bearer nope"})
    assert bad.status_code == 401 and bad.headers["www-authenticate"] == "Bearer"


def test_unknown_account_is_404_and_empty_account_is_zeros(client, auth):
    assert client.get("/v1/accounts/acct_404/usage", headers=auth).status_code == 404
    body = get(client, auth, "", on="2026-11-10").json()
    assert body["lifetime"]["cost_cents"] == 0 and body["cap"]["status"] == "ok"


def test_summary_reports_each_period(post, process, client, auth):
    post(event("e1", call_id="a", timestamp="2026-11-02T10:00:00+00:00", duration=60, cost=2))
    post(event("e2", call_id="b", timestamp="2026-11-10T10:00:00+00:00", duration=120, cost=4))
    post(event("e3", call_id="c", timestamp="2026-10-20T10:00:00+00:00", duration=30, cost=1))
    process()
    body = get(client, auth, "", on="2026-11-10").json()
    assert body["today"]["cost_cents"] == 4
    assert body["this_week"]["cost_cents"] == 4  # week of Mon Nov 9
    assert body["this_month"]["cost_cents"] == 6
    assert body["lifetime"]["cost_cents"] == 7


def test_series_is_sparse_and_ordered(post, process, client, auth):
    for i, day in enumerate(["2026-11-05", "2026-11-03", "2026-11-09"]):
        post(
            event(f"e{i}", call_id=f"c{i}", timestamp=f"{day}T10:00:00+00:00", duration=60, cost=2)
        )
    process()
    points = get(client, auth, "/series", **{"from": "2026-11-01", "to": "2026-11-30"}).json()[
        "points"
    ]
    assert [p["period_start"] for p in points] == ["2026-11-03", "2026-11-05", "2026-11-09"]
    weekly = get(
        client, auth, "/series", **{"from": "2026-11-01", "to": "2026-11-30", "granularity": "week"}
    ).json()["points"]
    assert [(p["period_start"], p["usage"]["cost_cents"]) for p in weekly] == [
        ("2026-11-02", 4),
        ("2026-11-09", 2),
    ]


def test_custom_range_matches_a_day_by_day_sum_but_reads_far_fewer_rows(
    post, process, client, auth
):
    rng = random.Random(7)
    start = date(2026, 1, 1)
    expected: dict[date, int] = {}
    for i in range(160):
        day = start + timedelta(days=rng.randrange(330))
        cost = rng.randrange(1, 50)
        expected[day] = expected.get(day, 0) + cost
        post(
            event(
                f"e{i}",
                call_id=f"c{i}",
                timestamp=f"{day.isoformat()}T12:00:00+00:00",
                duration=60,
                cost=cost,
            )
        )
    process()
    for _ in range(25):
        first = start + timedelta(days=rng.randrange(300))
        last = first + timedelta(days=rng.randrange(0, 330 - (first - start).days + 1))
        body = get(
            client, auth, "/range", **{"from": first.isoformat(), "to": last.isoformat()}
        ).json()
        truth = sum(c for d, c in expected.items() if first <= d <= last)
        assert body["usage"]["cost_cents"] == truth, (first, last)
        assert body["buckets_read"] <= (last - first).days + 1


def test_input_validation(client, auth):
    cases = [
        ("", {"on": "nonsense"}),
        ("/series", {"from": "2026-11-05", "to": "2026-11-01"}),
        ("/series", {"from": "2026-01-01", "to": "2027-12-31"}),
        ("/series", {"from": "2026-01-01", "to": "2026-02-01", "granularity": "hour"}),
        ("/range", {"from": "2000-01-01", "to": "2026-11-01"}),
        ("/range", {"from": "2026-11-01"}),
    ]
    for path, params in cases:
        response = get(client, auth, path, **params)
        assert response.status_code == 422, (path, params)
        assert response.json()["error"]["code"] == "validation_error"
    assert client.get("/v1/accounts/bad id/usage", headers=auth).status_code == 422


def test_health_and_metrics(client, post, auth):
    assert client.get("/health/live").json() == {"status": "ok"}
    assert client.get("/health/ready").json() == {"status": "ok"}
    post(event("e1"))
    post(event("e1"))
    metrics = client.get("/metrics").text
    assert 'webhook_requests_total{outcome="accepted"} 1.0' in metrics
    assert 'webhook_requests_total{outcome="duplicate"} 1.0' in metrics
    assert 'inbox_events{status="pending"} 1.0' in metrics
    assert "inbox_oldest_due_seconds" in metrics


def test_calls_endpoint_is_the_evidence_behind_the_totals(post, process, client, auth):
    for i in range(5):
        post(
            event(
                f"e{i}",
                call_id=f"c{i}",
                timestamp=f"2026-11-0{i + 1}T10:00:00+00:00",
                duration=60,
                cost=i + 1,
            )
        )
    post(event("s9", "call.started", call_id="open"))  # unfinished: not listed
    process()
    first = get(client, auth, "/calls", limit=2).json()
    assert [c["provider_call_id"] for c in first["items"]] == ["c4", "c3"]  # newest first
    assert first["next_cursor"]
    second = get(client, auth, "/calls", limit=10, cursor=first["next_cursor"]).json()
    assert [c["provider_call_id"] for c in second["items"]] == ["c2", "c1", "c0"]
    assert second["next_cursor"] is None
    assert sum(c["cost_cents"] for c in first["items"] + second["items"]) == 15
    assert get(client, auth, "/calls", cursor="garbage").status_code == 422
