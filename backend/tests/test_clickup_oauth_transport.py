"""Exercise the real OAuth HTTP serialization with synthetic transport only."""

import asyncio
import importlib.util
import json
from pathlib import Path
import sys

import httpx
import pytest


@pytest.fixture
def oauth():
    # This leaf module needs no node registry, database or hosted bootstrap.
    path = Path(__file__).parents[1] / "nodes/oauth/clickup_oauth.py"
    spec = importlib.util.spec_from_file_location("clickup_oauth_transport_test", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


def install_transport(monkeypatch, oauth, handler):
    client_class = httpx.AsyncClient
    monkeypatch.setattr(
        oauth.httpx,
        "AsyncClient",
        lambda **kwargs: client_class(transport=httpx.MockTransport(handler), **kwargs),
    )


@pytest.mark.parametrize("custom_client", [False, True])
def test_exchange_uses_json_body_and_preserves_identity(monkeypatch, oauth, custom_client):
    requests = []
    client_id = "custom-client" if custom_client else "hosted-client"
    client_secret = "synthetic-client-secret"
    code = "synthetic-authorization-code"
    redirect = "https://review.example.test/api/auth/clickup/callback"

    def handler(request):
        requests.append(request)
        if request.url.path == "/api/v2/oauth/token":
            assert request.method == "POST"
            assert request.url.query == b""
            assert request.headers["content-type"] == "application/json"
            assert json.loads(request.content) == {
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": redirect,
            }
            return httpx.Response(200, json={"access_token": "synthetic-access-token"})
        assert request.url.path == "/api/v2/user"
        assert request.headers["Authorization"] == "Bearer synthetic-access-token"
        return httpx.Response(200, json={"user": {
            "id": 42, "username": "Review User", "email": "review@example.test",
        }})

    monkeypatch.setenv("CLICKUP_CLIENT_ID", "hosted-client")
    monkeypatch.setenv("CLICKUP_CLIENT_SECRET", client_secret)
    install_transport(monkeypatch, oauth, handler)
    kwargs = {"client_id": client_id, "client_secret": client_secret} if custom_client else {}
    tokens, user = asyncio.run(oauth.exchange_code_for_tokens(code, redirect, **kwargs))
    assert len(requests) == 2
    assert tokens.access_token == "synthetic-access-token"
    assert tokens.refresh_token is None
    assert tokens.expires_at is None
    assert (user.id, user.name, user.email) == ("42", "Review User", "review@example.test")


@pytest.mark.parametrize("status,payload", [
    (400, {"error": "SYNTHETIC_PRIVATE_VALUE"}),
    (500, {"error_description": "SYNTHETIC_PRIVATE_VALUE"}),
    (200, {"err": "SYNTHETIC_PRIVATE_VALUE"}),
    (200, {"error": "SYNTHETIC_PRIVATE_VALUE"}),
    (200, ["SYNTHETIC_PRIVATE_VALUE"]),
    (200, {}),
    (200, {"access_token": 123}),
    (200, {"access_token": {"private": "SYNTHETIC_PRIVATE_VALUE"}}),
    (200, {"access_token": ""}),
    (200, {"access_token": "   "}),
    (200, {"access_token": "synthetic-token", "refresh_token": {"private": "SYNTHETIC_PRIVATE_VALUE"}}),
    (200, {"access_token": "synthetic-token", "token_type": {"private": "SYNTHETIC_PRIVATE_VALUE"}}),
])
def test_failed_exchange_is_secret_safe(monkeypatch, oauth, caplog, status, payload):
    seen = []

    def handler(request):
        seen.append(request.url.path)
        return httpx.Response(status, json=payload)

    install_transport(monkeypatch, oauth, handler)
    with pytest.raises(ValueError) as error:
        asyncio.run(oauth.exchange_code_for_tokens(
            "synthetic-code", "https://review.example.test/callback",
            client_id="synthetic-id", client_secret="synthetic-secret",
        ))
    assert seen == ["/api/v2/oauth/token"]
    assert "SYNTHETIC_PRIVATE_VALUE" not in str(error.value) + caplog.text


def test_invalid_json_does_not_echo_provider_body(monkeypatch, oauth, caplog):
    install_transport(monkeypatch, oauth, lambda request: httpx.Response(
        200, text="SYNTHETIC_PRIVATE_VALUE: not JSON",
    ))
    with pytest.raises(ValueError, match="invalid token response") as error:
        asyncio.run(oauth.exchange_code_for_tokens(
            "synthetic-code", "https://review.example.test/callback",
            client_id="synthetic-id", client_secret="synthetic-secret",
        ))
    assert "SYNTHETIC_PRIVATE_VALUE" not in str(error.value) + caplog.text


def test_failed_user_lookup_keeps_token_without_logging_response(monkeypatch, oauth, caplog):
    def handler(request):
        if request.url.path == "/api/v2/oauth/token":
            return httpx.Response(200, json={"access_token": "synthetic-access-token"})
        return httpx.Response(403, text="SYNTHETIC_PRIVATE_VALUE")

    install_transport(monkeypatch, oauth, handler)
    tokens, user = asyncio.run(oauth.exchange_code_for_tokens(
        "synthetic-code", "https://review.example.test/callback",
        client_id="synthetic-id", client_secret="synthetic-secret",
    ))
    assert tokens.access_token == "synthetic-access-token"
    assert user.id == "unknown"
    assert "SYNTHETIC_PRIVATE_VALUE" not in caplog.text
