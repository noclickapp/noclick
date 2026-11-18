import pytest
import respx

import noclick as nc
from noclick import _client as client_module

from platform_helpers import BASE


@pytest.fixture
def client(monkeypatch):
    """The default client, pointed at the mock API, with instant backoff."""
    c = nc.Client(api_key="nk_live_test", base_url=BASE, max_retries=2)
    c.sleeps = []

    async def fake_sleep(delay):
        c.sleeps.append(delay)

    c._sleep = fake_sleep
    monkeypatch.setattr(client_module, "_default", c)
    return c


@pytest.fixture
def api(client):
    with respx.mock(base_url=BASE, assert_all_called=False) as router:
        yield router
