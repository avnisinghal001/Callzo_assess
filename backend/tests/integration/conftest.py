from collections.abc import Callable, Iterator

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.modules.metering.worker import drain
from tests.conftest import ADMIN_KEY, API_KEY
from tests.helpers import body_of, sign
from tests.helpers import event as event_payload


def pytest_collection_modifyitems(items):
    for item in items:
        if "integration" in str(item.path):
            item.add_marker(pytest.mark.integration)


@pytest.fixture
def client(settings: Settings, conn) -> Iterator[TestClient]:  # `conn` = clean database
    with TestClient(create_app(settings)) as c:
        yield c


@pytest.fixture
def post(client: TestClient, settings: Settings) -> Callable:
    """Send a signed event. Fixtures use fixed dates, so by default the event is made to look
    delivered one minute after it happened; pass on_time=False to keep the real receipt time."""

    def _post(payload, *, signed: bool = True, raw: bytes | None = None, on_time: bool = True):
        body = raw if raw is not None else body_of(payload)
        headers = {"X-Signature": sign(body)} if signed else {}
        response = client.post("/webhooks/calls", content=body, headers=headers)
        if on_time and response.status_code == 202:
            with psycopg.connect(settings.database_url, autocommit=True) as c:
                c.execute(
                    "UPDATE call_events SET received_at = occurred_at + interval '1 minute' "
                    "WHERE provider_event_id = %s",
                    (payload["event_id"],),
                )
        return response

    return _post


@pytest.fixture
def process(conn, settings) -> Callable[[], int]:
    """Run the worker until the inbox is empty."""

    def _process() -> int:
        conn.commit()  # an open transaction would freeze now() and hide newly inserted events
        handled = drain(conn, max_attempts=settings.max_attempts)
        conn.commit()
        return handled

    return _process


@pytest.fixture
def auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {API_KEY}"}


@pytest.fixture
def admin() -> dict[str, str]:
    return {"Authorization": f"Bearer {ADMIN_KEY}"}


@pytest.fixture
def post_raw():
    """Post a valid signed event with a given client (for apps built inside a test)."""

    def _post(client):
        body = body_of(event_payload("evt_pool"))
        return client.post("/webhooks/calls", content=body, headers={"X-Signature": sign(body)})

    return _post
