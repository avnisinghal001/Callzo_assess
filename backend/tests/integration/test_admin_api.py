"""The control plane the console uses: accounts, events, reconcile, sandbox, overview."""

import uuid
from datetime import UTC, datetime

import pytest

from tests.helpers import event

ADMIN = "/admin/v1"


def lifetime_cost(client, admin, account="acct_001"):
    r = client.get(f"/v1/accounts/{account}/usage", headers=admin)
    return r.json()["lifetime"]["cost_cents"]


# ---- authentication and scopes -----------------------------------------------------------


@pytest.mark.parametrize("path", ["/overview", "/accounts", "/events"])
def test_admin_routes_need_the_admin_key(client, auth, admin, path):
    assert client.get(ADMIN + path).status_code == 401
    assert client.get(ADMIN + path, headers={"Authorization": "Bearer nope"}).status_code == 401
    read_only = client.get(ADMIN + path, headers=auth)
    assert read_only.status_code == 403 and read_only.json()["error"]["code"] == "forbidden"
    assert client.get(ADMIN + path, headers=admin).status_code == 200


def test_the_admin_key_can_also_read_usage_but_the_read_key_cannot_write(client, auth, admin):
    assert client.get("/v1/accounts/acct_001/usage", headers=admin).status_code == 200
    assert client.post(f"{ADMIN}/accounts", headers=auth, json={}).status_code == 403


def test_both_keys_must_differ(settings):
    from app.core.config import Settings

    with pytest.raises(ValueError, match="must be different"):
        Settings(**{**settings.model_dump(), "admin_api_key": settings.api_key})


# ---- accounts ----------------------------------------------------------------------------


def test_account_lifecycle(client, admin):
    created = client.post(
        f"{ADMIN}/accounts",
        headers=admin,
        json={"external_id": "acct_new", "monthly_cap_minutes": 30, "metadata": {"name": "Acme"}},
    )
    assert created.status_code == 201
    body = created.json()
    assert (
        uuid.UUID(body["id"])
        and body["deleted_at"] is None
        and body["metadata"] == {"name": "Acme"}
    )

    assert (
        client.post(
            f"{ADMIN}/accounts",
            headers=admin,
            json={"external_id": "acct_new", "monthly_cap_minutes": 1},
        ).status_code
        == 409
    )

    patched = client.patch(
        f"{ADMIN}/accounts/acct_new",
        headers=admin,
        json={"monthly_cap_minutes": 45, "metadata": {"tier": "gold", "name": None}},
    )
    assert patched.json()["monthly_cap_minutes"] == 45
    assert patched.json()["metadata"] == {"tier": "gold"}  # merged; null removed the key
    assert patched.json()["updated_at"] > body["updated_at"]

    deleted = client.delete(f"{ADMIN}/accounts/acct_new", headers=admin)
    assert deleted.json()["deleted_at"] is not None
    assert client.get("/v1/accounts/acct_new/usage", headers=admin).status_code == 404
    assert (
        client.patch(
            f"{ADMIN}/accounts/acct_new", headers=admin, json={"monthly_cap_minutes": 1}
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"{ADMIN}/accounts",
            headers=admin,
            json={"external_id": "acct_new", "monthly_cap_minutes": 1},
        ).status_code
        == 409
    )  # restore instead

    restored = client.post(f"{ADMIN}/accounts/acct_new/restore", headers=admin)
    assert restored.json()["deleted_at"] is None
    assert client.get("/v1/accounts/acct_new/usage", headers=admin).status_code == 200
    assert client.post(f"{ADMIN}/accounts/acct_new/restore", headers=admin).status_code == 404


@pytest.mark.parametrize(
    "payload",
    [
        {"external_id": "bad id", "monthly_cap_minutes": 1},
        {"external_id": "ok", "monthly_cap_minutes": -1},
        {"external_id": "ok", "monthly_cap_minutes": 10**9},
        {"external_id": "ok"},
        {"external_id": "ok", "monthly_cap_minutes": 1, "surprise": True},
        {"external_id": "ok", "monthly_cap_minutes": 1, "metadata": {"big": "x" * 9000}},
        {"external_id": "ok", "monthly_cap_minutes": 1, "metadata": []},
    ],
)
def test_account_validation(client, admin, payload):
    assert client.post(f"{ADMIN}/accounts", headers=admin, json=payload).status_code == 422


def test_empty_patch_is_rejected(client, admin):
    assert client.patch(f"{ADMIN}/accounts/acct_001", headers=admin, json={}).status_code == 422


def test_changing_the_cap_changes_the_cap_state_immediately(client, admin, post, process):
    post(event("e1", duration=400, cost=1))  # 400 s; seeded cap is 5 min = 300 s
    process()
    cap = client.get("/v1/accounts/acct_001/usage", headers=admin).json()["cap"]
    assert cap["status"] == "exceeded"
    client.patch(f"{ADMIN}/accounts/acct_001", headers=admin, json={"monthly_cap_minutes": 60})
    cap = client.get("/v1/accounts/acct_001/usage", headers=admin).json()["cap"]
    assert (cap["status"], cap["new_calls_allowed"]) == ("ok", True)


def test_account_list_paginates_with_keyset_and_shows_month_usage(client, admin, post, process):
    now = datetime.now(UTC).isoformat()
    post(event("e1", account_id="acct_002", duration=240, cost=1, timestamp=now))
    process()
    first = client.get(f"{ADMIN}/accounts?limit=2", headers=admin).json()
    assert [a["external_id"] for a in first["items"]] == ["acct_001", "acct_002"]
    assert first["next_cursor"] == "acct_002"
    assert first["items"][1]["month"]["used_seconds"] == 240
    assert first["items"][1]["month"]["status"] == "warning"
    rest = client.get(f"{ADMIN}/accounts?limit=2&cursor=acct_002", headers=admin).json()
    assert [a["external_id"] for a in rest["items"]] == ["acct_003"] and rest["next_cursor"] is None
    client.delete(f"{ADMIN}/accounts/acct_003", headers=admin)
    live = client.get(f"{ADMIN}/accounts", headers=admin).json()["items"]
    gone = client.get(f"{ADMIN}/accounts?deleted=true", headers=admin).json()["items"]
    assert "acct_003" not in [a["external_id"] for a in live]
    assert [a["external_id"] for a in gone] == ["acct_003"]


def test_events_for_a_deleted_account_are_retried_then_applied_after_restore(
    client, admin, post, process, conn
):
    client.delete(f"{ADMIN}/accounts/acct_001", headers=admin)
    post(event("e1", duration=60, cost=2))
    process()
    assert (
        conn.execute("SELECT status, attempts FROM call_events").fetchone()["status"] == "pending"
    )
    client.post(f"{ADMIN}/accounts/acct_001/restore", headers=admin)
    conn.execute("UPDATE call_events SET next_attempt_at = now()")
    conn.commit()
    process()
    assert lifetime_cost(client, admin) == 2


# ---- events ------------------------------------------------------------------------------


def seed_events(post, process, conn):
    post(event("ok1", call_id="a", duration=60, cost=2))
    post(event("ok2", call_id="b", duration=120, cost=4, account_id="acct_002"))
    post(event("bad1", call_id="c", account_id="acct_404"))
    process()
    conn.execute("UPDATE call_events SET status = 'dead' WHERE provider_event_id = 'bad1'")
    conn.commit()


def test_event_listing_filters_and_paginates(client, admin, post, process, conn):
    seed_events(post, process, conn)

    def by_status(s, **q):
        return client.get(f"{ADMIN}/events", headers=admin, params={"status": s, **q}).json()

    assert {e["provider_event_id"] for e in by_status("processed")["items"]} == {"ok1", "ok2"}
    assert [e["provider_event_id"] for e in by_status("dead")["items"]] == ["bad1"]
    assert [
        e["provider_event_id"] for e in by_status("processed", account="acct_002")["items"]
    ] == ["ok2"]
    everything = by_status("all", account="acct_001")
    assert [e["provider_event_id"] for e in everything["items"]] == ["ok1"]

    page = by_status("processed", limit=1)
    assert len(page["items"]) == 1 and page["next_cursor"]
    nxt = by_status("processed", limit=1, cursor=page["next_cursor"])
    assert {page["items"][0]["id"], nxt["items"][0]["id"]} == {
        e["id"] for e in by_status("processed")["items"]
    }
    assert nxt["next_cursor"] is None

    assert (
        client.get(f"{ADMIN}/events?status=all", headers=admin).status_code == 422
    )  # would scan all
    assert client.get(f"{ADMIN}/events?status=bogus", headers=admin).status_code == 422


def test_event_detail_shows_exactly_what_was_signed(client, admin, post, conn):
    post(event("d1"))
    listed = client.get(f"{ADMIN}/events?status=pending", headers=admin).json()["items"][0]
    detail = client.get(f"{ADMIN}/events/{listed['id']}", headers=admin).json()
    assert '"event_id": "d1"' in detail["raw_body"] and detail["metadata"]["source"] == "webhook"
    assert client.get(f"{ADMIN}/events/{uuid.uuid4()}", headers=admin).status_code == 404
    assert client.get(f"{ADMIN}/events/not-a-uuid", headers=admin).status_code == 422


def test_requeue_a_dead_event_and_all_dead_events(client, admin, post, process, conn):
    seed_events(post, process, conn)
    dead = client.get(f"{ADMIN}/events?status=dead", headers=admin).json()["items"][0]
    assert (
        client.post(f"{ADMIN}/events/{dead['id']}/requeue", headers=admin).json()["status"]
        == "pending"
    )
    assert client.post(f"{ADMIN}/events/requeue-dead", headers=admin).json() == {"requeued": 0}
    conn.execute("UPDATE call_events SET status = 'dead'")
    conn.commit()
    assert client.post(f"{ADMIN}/events/requeue-dead?account=acct_404", headers=admin).json() == {
        "requeued": 1
    }
    processed = client.get(f"{ADMIN}/events?status=pending", headers=admin).json()["items"]
    assert [e["account_external_id"] for e in processed] == ["acct_404"]
    other = conn.execute("SELECT id FROM call_events WHERE provider_event_id = 'ok1'").fetchone()[
        "id"
    ]
    conn.execute("UPDATE call_events SET status = 'processed' WHERE id = %s", (other,))
    conn.commit()
    assert client.post(f"{ADMIN}/events/{other}/requeue", headers=admin).status_code == 409


def test_voiding_a_processed_event_corrects_the_totals_at_once_and_restore_brings_it_back(
    client, admin, post, process, conn
):
    post(event("keep", call_id="a", duration=60, cost=2))
    post(event("wrong", call_id="b", duration=600, cost=20))
    process()
    assert lifetime_cost(client, admin) == 22
    wrong = conn.execute("SELECT id FROM call_events WHERE provider_event_id = 'wrong'").fetchone()[
        "id"
    ]
    conn.commit()

    voided = client.post(
        f"{ADMIN}/events/{wrong}/void", headers=admin, json={"reason": "provider bug"}
    )
    assert voided.status_code == 200 and voided.json()["deleted_at"] is not None
    assert voided.json()["metadata"]["void"]["reason"] == "provider bug"
    assert lifetime_cost(client, admin) == 2  # recomputed in the same request
    assert (
        client.post(
            f"{ADMIN}/events/{wrong}/void", headers=admin, json={"reason": "again"}
        ).status_code
        == 409
    )
    assert [
        e["provider_event_id"]
        for e in client.get(f"{ADMIN}/events?status=voided", headers=admin).json()["items"]
    ] == ["wrong"]

    # A redelivery of the voided event stays a duplicate: it must not resurrect itself.
    assert post(event("wrong", call_id="b", duration=600, cost=20)).status_code == 200
    process()
    assert lifetime_cost(client, admin) == 2

    restored = client.post(f"{ADMIN}/events/{wrong}/restore", headers=admin)
    assert restored.json()["deleted_at"] is None and restored.json()["status"] == "pending"
    assert "void" not in restored.json()["metadata"]
    process()
    assert lifetime_cost(client, admin) == 22
    assert client.post(f"{ADMIN}/events/{wrong}/restore", headers=admin).status_code == 409


def test_void_needs_a_reason(client, admin, post, conn):
    post(event("v1"))
    event_id = conn.execute("SELECT id FROM call_events").fetchone()["id"]
    conn.commit()
    for body in ({}, {"reason": ""}, {"reason": "x" * 501}):
        assert (
            client.post(f"{ADMIN}/events/{event_id}/void", headers=admin, json=body).status_code
            == 422
        )


def test_reconcile_endpoint_defaults_to_a_dry_run(client, admin, post, process, conn):
    post(event("e1", duration=60, cost=2))
    process()
    conn.execute("UPDATE usage_aggregate SET cost_cents = 99 WHERE period_type = 'lifetime'")
    conn.commit()
    dry = client.post(f"{ADMIN}/accounts/acct_001/reconcile", headers=admin).json()
    assert dry["dry_run"] and not dry["repaired"] and dry["drift"][0]["stored"]["cost_cents"] == 99
    assert lifetime_cost(client, admin) == 99
    fixed = client.post(f"{ADMIN}/accounts/acct_001/reconcile?dry_run=false", headers=admin).json()
    assert fixed["repaired"] and lifetime_cost(client, admin) == 2
    audit = conn.execute(
        "SELECT metadata FROM usage_aggregate WHERE period_type = 'lifetime'"
    ).fetchone()
    assert audit["metadata"]["reconciled"]["previous"]["cost_cents"] == 99  # the drift is on record
    assert client.post(f"{ADMIN}/accounts/acct_404/reconcile", headers=admin).status_code == 404


# ---- sandbox, overview, console ----------------------------------------------------------


@pytest.mark.parametrize(
    ("scenario", "expected"),
    [
        ("normal", 2),
        ("failed", 2),
        ("out_of_order", 2),
        ("late", 1),
        ("burst", 1),
        ("duplicate", 3),
    ],
)
def test_sandbox_scenarios_go_through_the_real_ingest_path(
    client, admin, process, conn, scenario, expected
):
    r = client.post(
        f"{ADMIN}/sandbox/scenarios",
        headers=admin,
        json={"scenario": scenario, "account": "acct_001", "count": 1},
    )
    assert r.status_code == 200 and r.json()["sent"] == expected
    if scenario == "duplicate":
        assert [x["outcome"] for x in r.json()["results"]] == ["accepted", "duplicate", "duplicate"]
    process()
    assert (
        conn.execute("SELECT count(*) AS n FROM call_events WHERE status = 'pending'").fetchone()[
            "n"
        ]
        == 0
    )
    source = conn.execute("SELECT DISTINCT metadata->>'source' AS s FROM call_events").fetchall()
    assert [s["s"] for s in source] == ["console-sandbox"]


def test_sandbox_burst_trips_the_cap(client, admin, process):
    client.post(
        f"{ADMIN}/sandbox/scenarios",
        headers=admin,
        json={"scenario": "burst", "account": "acct_001", "count": 5},
    )  # 5 x 10 min vs 5 min cap
    process()
    cap = client.get("/v1/accounts/acct_001/usage", headers=admin).json()["cap"]
    assert cap["status"] == "exceeded" and not cap["new_calls_allowed"]


def test_sandbox_validation_and_kill_switch(client, admin, settings):
    bad = {"scenario": "explode", "account": "acct_001"}
    assert client.post(f"{ADMIN}/sandbox/scenarios", headers=admin, json=bad).status_code == 422
    client.app.state.settings = settings.model_copy(update={"enable_sandbox": False})
    off = client.post(
        f"{ADMIN}/sandbox/scenarios",
        headers=admin,
        json={"scenario": "normal", "account": "acct_001"},
    )
    assert off.status_code == 403
    assert client.get(f"{ADMIN}/overview", headers=admin).json()["sandbox_enabled"] is False


def test_overview_is_fleet_wide(client, admin, post):
    post(event("e1"))
    post(event("e1"))
    client.app.state.reporter.flush()
    data = client.get(f"{ADMIN}/overview", headers=admin).json()
    assert data["inbox"]["pending"] == 1 and data["inbox"]["dead"] == 0
    totals: dict[str, int] = {}
    for minute in data["traffic"]:
        for outcome, n in minute["outcomes"].items():
            totals[outcome] = totals.get(outcome, 0) + n
    assert totals == {"accepted": 1, "duplicate": 1}
    assert [(i["role"], i["alive"]) for i in data["instances"]] == [("api", True)]
    assert {j["name"] for j in data["jobs"]} == {"reconcile_check", "retention"}


def test_console_is_served_with_a_strict_csp(client):
    page = client.get("/console/")
    assert page.status_code == 200 and "Metering console" in page.text
    csp = page.headers["content-security-policy"]
    assert (
        "script-src 'self'" in csp
        and "frame-ancestors 'none'" in csp
        and "unsafe-inline" not in csp
    )
    assert page.headers["x-content-type-options"] == "nosniff"
    assert (
        "<script>" not in page.text and "style=" not in page.text
    )  # nothing inline, so the CSP holds
    for asset in ("app.js", "styles.css"):
        assert client.get(f"/console/{asset}").status_code == 200
    assert client.get("/", follow_redirects=False).headers["location"] == "/console/"


def test_the_console_shell_holds_no_secrets_and_its_data_needs_the_key(client):
    text = client.get("/console/app.js").text + client.get("/console/").text
    assert "test-admin-key" not in text and "test-api-key" not in text
    assert client.get(f"{ADMIN}/overview").status_code == 401


@pytest.mark.parametrize(
    "scenario", ["normal", "failed", "duplicate", "out_of_order", "late", "burst"]
)
def test_a_simulator_run_adds_exactly_what_it_should(client, admin, process, scenario):
    run = client.post(
        f"{ADMIN}/sandbox/scenarios",
        headers=admin,
        json={"scenario": scenario, "account": "acct_001", "count": 4},
    ).json()
    body = {"account": "acct_001", "call_ids": run["call_ids"]}
    before = client.post(f"{ADMIN}/sandbox/verify", headers=admin, json=body).json()
    assert before["waiting_events"] > 0  # stored, not counted yet
    process()
    after = client.post(f"{ADMIN}/sandbox/verify", headers=admin, json=body).json()
    assert after["waiting_events"] == 0 and after["actual"] == run["expected"]


@pytest.mark.parametrize(
    ("scenario", "n", "codes"), [("malformed", 5, {400, 422}), ("bad_signature", 3, {401})]
)
def test_rejected_scenarios_store_nothing_and_are_counted(client, admin, conn, scenario, n, codes):
    run = client.post(
        f"{ADMIN}/sandbox/scenarios",
        headers=admin,
        json={"scenario": scenario, "account": "acct_001"},
    ).json()
    assert [r["outcome"] for r in run["results"]] == ["rejected"] * n
    assert {r["status_code"] for r in run["results"]} == codes
    assert conn.execute("SELECT count(*) AS n FROM call_events").fetchone()["n"] == 0
