"""The console opens without a sign-in, but the API never becomes anonymous."""

import pytest
from fastapi.testclient import TestClient

from app.core import console_session
from app.main import create_app

OVERVIEW = "/admin/v1/overview"
CONSOLE = {"X-Console": "1"}


@pytest.fixture
def open_client(settings, conn):
    with TestClient(create_app(settings.model_copy(update={"console_open_access": True}))) as c:
        yield c


def test_opening_the_console_is_all_it_takes(open_client):
    assert open_client.get(OVERVIEW, headers=CONSOLE).status_code == 401  # not opened yet
    page = open_client.get("/console/")
    cookie = page.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert open_client.get(OVERVIEW, headers=CONSOLE).status_code == 200
    assert open_client.get("/v1/accounts/acct_001/usage", headers=CONSOLE).status_code == 200


def test_a_cross_site_request_cannot_ride_on_the_cookie(open_client):
    open_client.get("/console/")
    assert open_client.get(OVERVIEW).status_code == 401  # cookie alone: no custom header, no access


@pytest.mark.parametrize("token", ["", "x", "9999999999.", "9999999999.deadbeef", "²³.x"])
def test_forged_sessions_are_refused(open_client, token):
    assert not console_session.is_valid("a" * 20, token)


def test_sessions_expire_and_depend_on_the_secret():
    token = console_session.issue("secret-one-secret-one", now=1000)
    assert console_session.is_valid("secret-one-secret-one", token, now=1001)
    assert not console_session.is_valid("secret-two-secret-two", token, now=1001)
    late = 1000 + console_session.LIFETIME_SECONDS + 1
    assert not console_session.is_valid("secret-one-secret-one", token, now=late)


def test_open_access_is_off_unless_asked_for(client):
    assert "set-cookie" not in client.get("/console/").headers
    token = console_session.issue(client.app.state.settings.admin_api_key)
    client.cookies.set(console_session.COOKIE, token)
    assert client.get(OVERVIEW, headers=CONSOLE).status_code == 401  # genuine, but not enabled


def test_console_actions_are_audited_as_the_console(open_client):
    open_client.get("/console/")
    body = {"external_id": "acct_x", "monthly_cap_minutes": 1}
    assert open_client.post("/admin/v1/accounts", headers=CONSOLE, json=body).status_code == 201
    entry = open_client.get("/admin/v1/audit", headers=CONSOLE).json()["items"][0]
    assert (entry["action"], entry["target"], entry["actor"]) == (
        "account.create",
        "acct_x",
        "console",
    )


def test_unknown_hosts_are_refused(settings, conn):
    """DNS rebinding: a web page that resolves its own name to 127.0.0.1 must get nothing."""
    locked = settings.model_copy(
        update={"console_open_access": True, "allowed_hosts": "localhost,127.0.0.1"}
    )
    with TestClient(create_app(locked), base_url="http://localhost:8000") as c:
        assert c.get("/console/").status_code == 200
        evil = c.get("/console/", headers={"Host": "evil.example"})
        assert evil.status_code == 400 and "set-cookie" not in evil.headers
