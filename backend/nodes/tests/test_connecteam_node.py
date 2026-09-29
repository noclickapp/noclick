"""Contract tests for every documented Connecteam action, with no live account."""

import json
import re
from urllib.parse import quote

import httpx
import pytest

from nodes import connecteam_node as module
from nodes.connecteam_node import (
    CONNECTEAM_CONFIGS,
    CONNECTEAM_OPERATIONS,
    ConnecteamApiKeyCredential,
    ConnecteamNode,
    ConnecteamNodeConfig,
    ConnecteamOAuthClientCredential,
)


def _node(operation: str, credential=None, **values):
    config = CONNECTEAM_CONFIGS[operation](**values)
    full = ConnecteamNodeConfig(
        config=config,
        credentials=credential or ConnecteamApiKeyCredential(api_key="test-key"),
    )
    return ConnecteamNode("test", "automation-connecteam", {}, config=full)


def _required_values(spec):
    values = {}
    for parameter in spec["parameters"]:
        if not parameter["required"]:
            continue
        kind = parameter["type"]
        values[parameter["name"]] = {
            "integer": 17,
            "boolean": True,
            "array": ["a", "b"],
        }.get(kind, "test value")
    if spec["body_required"]:
        values["body"] = json.dumps({"example": True})
    return values


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", CONNECTEAM_OPERATIONS)
async def test_documented_operation_routes_to_its_method_path_and_auth(
    operation, monkeypatch
):
    spec = CONNECTEAM_OPERATIONS[operation]
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"data": {"ok": True}})

    real_client = httpx.AsyncClient
    transport = httpx.MockTransport(respond)
    monkeypatch.setattr(
        module.httpx, "AsyncClient", lambda **kw: real_client(transport=transport, **kw)
    )
    values = _required_values(spec)
    result = await _node(operation, **values).execute({})
    assert result["status"] == "success"
    assert result["action"] == operation
    assert result["timing_ms"]["api_request"] >= 0
    assert len(requests) == 1
    request = requests[0]
    assert request.method == spec["method"]
    assert request.url.host == "api.connecteam.com"
    expected_path = spec["path"]
    for parameter in spec["parameters"]:
        if parameter["in"] == "path":
            expected_path = expected_path.replace(
                "{" + parameter["name"] + "}",
                quote(str(values[parameter["name"]]), safe=""),
            )
        elif parameter["in"] == "query" and parameter["required"]:
            assert parameter["name"] in request.url.params
    assert request.url.raw_path.split(b"?")[0].decode() == expected_path
    assert not re.search(r"{[^}]+}", request.url.path)
    assert request.headers["X-API-KEY"] == "test-key"
    if spec["body_required"]:
        assert json.loads(request.content) == {"example": True}
    assert operation in CONNECTEAM_CONFIGS


@pytest.mark.asyncio
async def test_path_is_encoded_and_australian_host_is_used(monkeypatch):
    operation = next(
        name
        for name, spec in CONNECTEAM_OPERATIONS.items()
        if any(p["in"] == "path" and p["type"] == "string" for p in spec["parameters"])
    )
    spec = CONNECTEAM_OPERATIONS[operation]
    values = _required_values(spec)
    path_parameter = next(
        p for p in spec["parameters"] if p["in"] == "path" and p["type"] == "string"
    )
    values[path_parameter["name"]] = "a/b ?"
    urls = []
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        module.httpx,
        "AsyncClient",
        lambda **kw: real_client(
            transport=httpx.MockTransport(
                lambda request: (
                    urls.append(request.url),
                    httpx.Response(200, json={}),
                )[-1]
            ),
            **kw,
        ),
    )
    credential = ConnecteamApiKeyCredential(api_key="key", region="australia")
    assert (await _node(operation, credential, **values).execute({}))[
        "status"
    ] == "success"
    assert urls[0].host == "api-au.connecteam.com"
    assert "a%2Fb%20%3F" in str(urls[0])


@pytest.mark.asyncio
async def test_client_credentials_token_is_reused_until_expiry(monkeypatch):
    module._TOKEN_CACHE.clear()
    seen = []

    def respond(request):
        seen.append(request)
        if request.url.path == "/oauth/v1/token":
            assert request.method == "POST"
            assert request.content == b"grant_type=client_credentials"
            assert request.headers["Authorization"].startswith("Basic ")
            return httpx.Response(
                200, json={"access_token": "token-1", "expires_in": 3600}
            )
        assert request.headers["Authorization"] == "Bearer token-1"
        return httpx.Response(200, json={"data": {"id": 5}})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        module.httpx,
        "AsyncClient",
        lambda **kw: real_client(transport=httpx.MockTransport(respond), **kw),
    )
    credential = ConnecteamOAuthClientCredential(client_id="id", client_secret="secret")
    node = _node("get_account_information_me_get", credential)
    assert (await node.execute({}))["status"] == "success"
    assert (await node.execute({}))["status"] == "success"
    assert [r.url.path for r in seen] == ["/oauth/v1/token", "/me", "/me"]


@pytest.mark.asyncio
async def test_client_credentials_rejection_preserves_provider_status(monkeypatch):
    module._TOKEN_CACHE.clear()
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        module.httpx,
        "AsyncClient",
        lambda **kw: real_client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(401, json={"error": "invalid_client"})
            ),
            **kw,
        ),
    )
    credential = ConnecteamOAuthClientCredential(
        client_id="wrong", client_secret="wrong"
    )
    result = await _node("get_account_information_me_get", credential).execute({})
    assert result["status"] == "error"
    assert result["status_code"] == 401
    assert result["error"] == {"error": "invalid_client"}


@pytest.mark.asyncio
async def test_http_error_and_invalid_json_are_reported(monkeypatch):
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        module.httpx,
        "AsyncClient",
        lambda **kw: real_client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(429, json={"error": "rate limited"})
            ),
            **kw,
        ),
    )
    result = await _node("get_account_information_me_get").execute({})
    assert result["status"] == "error"
    assert result["status_code"] == 429
    assert result["error"]["error"] == "rate limited"
    operation = next(
        name for name, spec in CONNECTEAM_OPERATIONS.items() if spec["body_required"]
    )
    with pytest.raises(ValueError, match="valid JSON"):
        await _node(
            operation,
            **{**_required_values(CONNECTEAM_OPERATIONS[operation]), "body": "{"},
        ).execute({})


def test_catalog_matches_schema_and_uses_only_documented_hosts():
    schema = ConnecteamNode.get_config_schema()
    assert len(CONNECTEAM_OPERATIONS) == 154
    assert len(CONNECTEAM_CONFIGS) == len(CONNECTEAM_OPERATIONS)
    assert "ConnecteamApiKeyCredential" in schema["$defs"]
    assert "ConnecteamOAuthClientCredential" in schema["$defs"]
    for spec in CONNECTEAM_OPERATIONS.values():
        assert spec["reference"].startswith(
            "https://developer.connecteam.com/reference/"
        )
        assert spec["path"].startswith("/")
        assert spec["method"] in {"GET", "POST", "PUT", "DELETE"}
