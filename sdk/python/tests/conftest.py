import pytest
import respx

import noclick as nc
from noclick import _client as client_module

from platform_helpers import BASE


@pytest.fixture(autouse=True)
def no_real_keychain(monkeypatch):
    """The OS keychain is per user, whatever HOME says: no test reaches the real one. A test that wants a keychain
    hands the CLI one (``cli._keyring``); any other that reaches for it fails here, before it touches anything, and a
    program a test starts gets keyring's backend that keeps nothing."""
    from noclick import cli

    def refused():
        raise AssertionError("A test reached the real OS keychain: give cli._keyring a stand-in, or pass --store file.")

    monkeypatch.setattr(cli, "_keyring", refused)
    monkeypatch.delenv("NOCLICK_KEYCHAIN", raising=False)
    monkeypatch.setenv("PYTHON_KEYRING_BACKEND", "keyring.backends.fail.Keyring")


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
