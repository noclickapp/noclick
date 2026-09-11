"""Exercise real HubSpot OAuth serialization with synthetic HTTP transport."""

import asyncio
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sys
import traceback
from urllib.parse import parse_qs

import httpx
import pytest


@pytest.fixture
def oauth(monkeypatch):
    path = Path(__file__).parents[1] / "nodes/oauth/hubspot_oauth.py"
    spec = importlib.util.spec_from_file_location("hubspot_transport_test", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    monkeypatch.setenv("HUBSPOT_CLIENT_ID", "synthetic-client")
    monkeypatch.setenv("HUBSPOT_CLIENT_SECRET", "synthetic-secret")
    yield module
    sys.modules.pop(spec.name, None)


def install_transport(monkeypatch, oauth, handler):
    client_class = httpx.AsyncClient
    monkeypatch.setattr(oauth.httpx, "AsyncClient", lambda **kwargs: client_class(
        transport=httpx.MockTransport(handler), **kwargs,
    ))


def call(oauth, grant):
    if grant == "authorization_code":
        return asyncio.run(oauth.exchange_code_for_tokens(
            "synthetic-code", "https://review.example.test/callback",
        ))
    return asyncio.run(oauth.refresh_access_token("synthetic-refresh"))


def response_payload(**updates):
    return {
        "access_token": "synthetic-access", "refresh_token": "synthetic-rotated",
        "token_type": "bearer", "expires_in": 1800, "hub_id": 42,
        **updates,
    }


@pytest.mark.parametrize("grant", ["authorization_code", "refresh_token"])
def test_versioned_endpoint_form_body_and_token_result(monkeypatch, oauth, grant):
    requests = []

    def handler(request):
        requests.append(request)
        assert request.method == "POST"
        assert str(request.url) == "https://api.hubapi.com/oauth/2026-03/token"
        assert request.url.query == b""
        assert request.headers["content-type"] == "application/x-www-form-urlencoded"
        fields = {key: values[0] for key, values in parse_qs(request.content.decode()).items()}
        expected = {
            "client_id": "synthetic-client", "client_secret": "synthetic-secret",
            "grant_type": grant,
        }
        if grant == "authorization_code":
            expected.update(code="synthetic-code", redirect_uri="https://review.example.test/callback")
        else:
            expected["refresh_token"] = "synthetic-refresh"
        assert fields == expected
        return httpx.Response(200, json=response_payload(expires_in=600))

    install_transport(monkeypatch, oauth, handler)
    before = datetime.now(timezone.utc).timestamp()
    result = call(oauth, grant)
    if grant == "authorization_code":
        tokens, identity = result
        assert identity.hub_id == "42"
    else:
        tokens = result
    assert len(requests) == 1
    assert tokens.access_token == "synthetic-access"
    assert tokens.refresh_token == "synthetic-rotated"
    assert tokens.token_type == "bearer"
    assert before + 600 <= datetime.fromisoformat(tokens.expires_at).timestamp() <= datetime.now(timezone.utc).timestamp() + 600


@pytest.mark.parametrize("grant", ["authorization_code", "refresh_token"])
@pytest.mark.parametrize("status,payload", [
    (400, {"error": "invalid_grant", "error_description": "SYNTHETIC_PRIVATE_VALUE"}),
    (500, {"error": "SYNTHETIC_PRIVATE_VALUE"}),
    (200, ["SYNTHETIC_PRIVATE_VALUE"]),
    (200, {"error": "SYNTHETIC_PRIVATE_VALUE"}),
    (200, response_payload(access_token={"private": "SYNTHETIC_PRIVATE_VALUE"})),
    (200, response_payload(access_token="")),
    (200, response_payload(refresh_token=None)),
    (200, response_payload(refresh_token="   ")),
    (200, response_payload(expires_in="SYNTHETIC_PRIVATE_VALUE")),
    (200, response_payload(expires_in=None)),
    (200, response_payload(expires_in=True)),
    (200, response_payload(expires_in=-1)),
    (200, response_payload(expires_in=10**100)),
    (200, response_payload(hub_id={"private": "SYNTHETIC_PRIVATE_VALUE"})),
    (200, response_payload(hub_domain={"private": "SYNTHETIC_PRIVATE_VALUE"})),
])
def test_failure_does_not_echo_provider_data(monkeypatch, oauth, caplog, grant, status, payload):
    install_transport(monkeypatch, oauth, lambda request: httpx.Response(status, json=payload))
    with pytest.raises(ValueError) as error:
        call(oauth, grant)
    rendered = "".join(traceback.format_exception(error.value))
    assert "SYNTHETIC_PRIVATE_VALUE" not in rendered + caplog.text
    if status == 400:
        assert "invalid_grant" in str(error.value)


@pytest.mark.parametrize("grant", ["authorization_code", "refresh_token"])
@pytest.mark.parametrize("failure", ["json", "timeout", "network"])
def test_parse_and_transport_errors_are_safe(monkeypatch, oauth, caplog, grant, failure):
    def handler(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("SYNTHETIC_PRIVATE_VALUE", request=request)
        if failure == "network":
            raise httpx.ConnectError("SYNTHETIC_PRIVATE_VALUE", request=request)
        return httpx.Response(200, text="SYNTHETIC_PRIVATE_VALUE")

    install_transport(monkeypatch, oauth, handler)
    with pytest.raises(ValueError) as error:
        call(oauth, grant)
    assert "SYNTHETIC_PRIVATE_VALUE" not in "".join(traceback.format_exception(error.value)) + caplog.text
