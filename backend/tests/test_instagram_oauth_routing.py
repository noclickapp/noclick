"""Instagram Login callbacks must reach their existing OAuth handler.

These regressions cover the routing gap that rejected completed logins as an
unknown event, including the generated routes used by both frontend editions.
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from wss.handlers.oauth import instagram_login_oauth_handler
from wss.receiver import client_events
from wss.receiver.chunk_reassembly import ChunkReassemblyManager
from wss.receiver.event_routing import EVENT_ROUTING, Handler
from wss.receiver.receiver import SocketIOProxy


INSTAGRAM_EVENTS = {
    model.event_name: model
    for model in vars(client_events).values()
    if isinstance(model, type)
    and getattr(model, "event_name", "").startswith("instagram_login:oauth:")
}
ROOT = Path(__file__).resolve().parents[2]


def test_every_declared_instagram_login_event_is_routed():
    assert len(INSTAGRAM_EVENTS) >= 3
    handler = object.__new__(instagram_login_oauth_handler.InstagramLoginOAuthHandler)
    assert set(INSTAGRAM_EVENTS) == set(handler.get_events())
    for event in INSTAGRAM_EVENTS:
        assert EVENT_ROUTING["API"].get(event) == Handler.INSTAGRAM_LOGIN_OAUTH


@pytest.mark.parametrize("event", INSTAGRAM_EVENTS)
@pytest.mark.asyncio
async def test_instagram_login_dispatch_reaches_the_real_handler(event, monkeypatch):
    # Exercise the handler's unauthenticated guard, without exchanging any code,
    # reading stored credentials, or connecting to a database/provider.
    sio = SimpleNamespace(get_session=AsyncMock(return_value={}))
    handler = object.__new__(instagram_login_oauth_handler.InstagramLoginOAuthHandler)
    handler.sio = sio
    sent = AsyncMock()
    monkeypatch.setattr(instagram_login_oauth_handler, "send_event", sent)

    proxy = object.__new__(SocketIOProxy)
    proxy.sio = sio
    proxy.SOCKET_PROXY_ENV = "API"
    proxy.chunk_manager = ChunkReassemblyManager()
    proxy.rate_limiter = SimpleNamespace(
        check_rate_limit=AsyncMock(return_value=(True, None))
    )
    proxy.frontend_request_pydantic_models = INSTAGRAM_EVENTS
    instances = {key: None for routes in EVENT_ROUTING.values() for key in routes.values()}
    instances[Handler.INSTAGRAM_LOGIN_OAUTH] = handler
    proxy.config = SimpleNamespace(
        event_handlers=proxy._build_event_handlers(instances)
    )
    proxy._enter_request_context = AsyncMock(return_value=None)
    proxy._exit_request_context = MagicMock()
    proxy._last_heavy_completion = {}
    payload = {"request_id": "instagram-routing-test"}
    if event.endswith(":exchange"):
        payload.update(
            code="synthetic-test-code",
            redirect_uri="https://example.test/api/auth/instagram/callback",
            scopes=["instagram_business_basic"],
        )
    else:
        payload["credential_id"] = "00000000-0000-0000-0000-000000000000"

    result = await proxy._route_event_impl(event, "test-sid", payload)

    assert result is None
    sent.assert_awaited_once()
    response = sent.await_args.args[2]
    assert response.request_id == payload["request_id"]
    assert response.data["message"] == "User not authenticated"
    verdict = "valid" if event.endswith(":validate") else "success"
    assert response.data[verdict] is False
    proxy._exit_request_context.assert_called_once_with(None)


@pytest.mark.parametrize(
    "relative_path",
    [
        "frontend/app/types/socket-events.generated.ts",
        "oss/overrides/frontend/app/types/socket-events.generated.ts",
    ],
)
def test_generated_frontends_route_instagram_login_to_api(relative_path):
    path = ROOT / relative_path
    if not path.exists() and relative_path.startswith("oss/"):
        pytest.skip("The exported edition has no override source directory")
    routing = path.read_text().split("export const EventRouting = {", 1)[1].split("}", 1)[0]
    for event in INSTAGRAM_EVENTS:
        assert f"'{event}': 'API'" in routing
