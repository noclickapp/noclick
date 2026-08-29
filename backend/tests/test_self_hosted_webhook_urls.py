"""Self-hosted webhook URLs land on the route that serves them.

`get_webhook_url` takes the backend's ORIGIN — the same value the Discord
app-event registration appends `/webhook/app/discord` to — and the delivery
route is mounted under /webhook. Minting a bare `{origin}/{id}` sent every
schedule tick and provider delivery to the app's 404 page behind the
single-origin front door.
"""

import pytest

from utils import webhook_tunnel


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    for name in ("PUBLIC_WEBHOOK_URL", "WEBHOOK_URL_BASE", "PUBLIC_API_URL"):
        monkeypatch.delenv(name, raising=False)


def test_the_delivery_route_prefix_is_part_of_the_minted_url(monkeypatch):
    monkeypatch.setenv("PUBLIC_API_URL", "https://noclick.example.com/")
    assert webhook_tunnel.get_webhook_url("abc-123") == "https://noclick.example.com/webhook/abc-123"


def test_a_base_that_already_names_the_prefix_is_not_doubled(monkeypatch):
    monkeypatch.setenv("PUBLIC_WEBHOOK_URL", "https://noclick.example.com/webhook")
    assert webhook_tunnel.get_webhook_url("abc-123") == "https://noclick.example.com/webhook/abc-123"


def test_explicit_webhook_base_wins_over_the_api_url(monkeypatch):
    monkeypatch.setenv("PUBLIC_API_URL", "https://api.example.com")
    monkeypatch.setenv("PUBLIC_WEBHOOK_URL", "https://hooks.example.com")
    assert webhook_tunnel.get_webhook_url("x") == "https://hooks.example.com/webhook/x"


def test_no_base_fails_loudly():
    with pytest.raises(RuntimeError):
        webhook_tunnel.get_webhook_url("x")
