"""Login geo lookup is opt-in, HTTPS-only, and gated before IP work."""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_geo_lookup_unset_makes_no_request(monkeypatch):
    from utils.geo import get_country_from_ip

    monkeypatch.delenv("GEOIP_LOOKUP_URL", raising=False)
    with patch("utils.geo.httpx.AsyncClient") as client:
        assert await get_country_from_ip("203.0.113.7") is None
    client.assert_not_called()


@pytest.mark.asyncio
async def test_geo_lookup_rejects_plain_http(monkeypatch):
    from utils.geo import get_country_from_ip

    monkeypatch.setenv("GEOIP_LOOKUP_URL", "http://geo.example.test/{ip}")
    with patch("utils.geo.httpx.AsyncClient") as client:
        assert await get_country_from_ip("203.0.113.8") is None
    client.assert_not_called()


@pytest.mark.asyncio
async def test_login_notification_gates_before_geo(monkeypatch):
    from utils import slack

    monkeypatch.setattr(slack, "login_notifications_enabled", lambda: False)
    with patch("utils.geo.get_country_from_ip", new=AsyncMock()) as geo:
        assert await slack.send_login_notification(
            "user-id", {"email": "user@example.test"}, "203.0.113.9"
        ) is None
    geo.assert_not_awaited()
