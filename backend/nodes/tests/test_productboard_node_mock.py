"""Contract tests against Productboard's checked-in official API v2 catalog.

Every action reaches the documented method and route with a mocked HTTP
response. OAuth tests exercise the exchange and single-use refresh contract.
No Productboard workspace or network access is required.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock
from urllib.parse import quote

import httpx
import pytest

from nodes.oauth import productboard_oauth as oauth
from nodes.productboard_node import (
    PRODUCTBOARD_API_BASE,
    PRODUCTBOARD_CONFIGS,
    PRODUCTBOARD_OPERATIONS,
    ProductboardNode,
    ProductboardNodeConfig,
)

CREDENTIAL = {"credential_type": "productboard_api_token", "access_token": "pat-test"}


def _node(operation: str, **fields):
    return ProductboardNode(
        node_id="productboard-test",
        node_type="automation-productboard",
        node_data={},
        config=ProductboardNodeConfig(
            config={"operation": operation, **fields}, credentials=CREDENTIAL
        ),
        sio=Mock(),
        sid="test-sid",
        workflow_id="workflow",
        user_id="user",
    )


def _fields(spec):
    fields = {name: f"{name}/with space" for name in spec["path_parameters"]}
    if spec["body_required"]:
        fields["body_json"] = '{"type":"feature"}'
    for query in spec["query_fields"]:
        if not query["required"]:
            continue
        fields[query["field"]] = {"boolean": True, "integer": 1, "array": ["one"]}.get(
            query["type"], "sample"
        )
    return fields


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", sorted(PRODUCTBOARD_OPERATIONS))
async def test_every_official_operation_uses_its_method_route_and_auth(
    monkeypatch, operation
):
    spec = PRODUCTBOARD_OPERATIONS[operation]
    calls = []

    async def fake_request(self, method, url, **kwargs):
        calls.append((method, url, kwargs))
        return httpx.Response(
            200, json={"data": [{"id": "record-1"}], "links": {"next": None}}
        )

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    fields = _fields(spec)
    result = await _node(operation, **fields).execute({})
    assert result["status"] == "success"
    assert result["data"] == {"items": [{"id": "record-1"}], "links": {"next": None}}
    assert result["action"] == operation
    assert len(calls) == 1
    method, url, kwargs = calls[0]
    expected_path = spec["path"]
    for name in spec["path_parameters"]:
        expected_path = expected_path.replace(
            "{" + name + "}", quote(fields[name], safe="")
        )
    assert (method, url) == (spec["method"], PRODUCTBOARD_API_BASE + expected_path)
    assert kwargs["headers"]["Authorization"] == "Bearer pat-test"
    assert kwargs["headers"]["Accept"] == "application/json"
    assert kwargs["json"] == ({"type": "feature"} if spec["body_required"] else None)


def test_catalog_schema_and_registration_contract():
    assert len(PRODUCTBOARD_OPERATIONS) == len(PRODUCTBOARD_CONFIGS) == 59
    assert len({spec["category"] for spec in PRODUCTBOARD_OPERATIONS.values()}) == 9
    assert all(
        spec["reference"].startswith("https://developer.productboard.com/reference/")
        for spec in PRODUCTBOARD_OPERATIONS.values()
    )
    schema = ProductboardNode.get_config_schema()
    variants = schema["properties"]["config"].get("oneOf") or schema["properties"][
        "config"
    ].get("anyOf")
    assert len(variants) == 59
    credentials = schema["properties"]["credentials"].get("oneOf") or schema[
        "properties"
    ]["credentials"].get("anyOf")
    assert len([item for item in credentials if "$ref" in item]) == 2
    frontend = json.loads(
        (Path(__file__).resolve().parents[3] / "frontend/app/schemas/nodes/productboard.json").read_text()
    )
    assert (
        len(
            frontend["properties"]["config"].get("oneOf")
            or frontend["properties"]["config"].get("anyOf")
        )
        == 59
    )


@pytest.mark.asyncio
async def test_query_body_and_path_values_are_encoded(monkeypatch):
    captured = {}

    async def fake_request(self, method, url, **kwargs):
        captured.update(method=method, url=url, **kwargs)
        return httpx.Response(200, json={"data": {"id": "x"}})

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    result = await _node(
        "get_entity", id="a/b ?#", query_json='{"include":"fields","pageCursor":"one"}'
    ).execute({})
    assert result["status"] == "success"
    assert captured["url"].endswith("/entities/a%2Fb%20%3F%23")
    assert captured["params"] == {"include": "fields", "pageCursor": "one"}
    assert result["data"] == {"data": {"id": "x"}}


@pytest.mark.asyncio
async def test_error_response_and_malformed_json(monkeypatch):
    async def fake_request(self, method, url, **kwargs):
        return httpx.Response(
            422,
            json={
                "errors": [
                    {
                        "code": "validation.failed",
                        "title": "Validation failed",
                        "detail": "Content can't be blank",
                        "source": {"pointer": "/data/fields/content"},
                    }
                ]
            },
        )

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    result = await _node("list_teams").execute({})
    assert result["status"] == "error" and result["status_code"] == 422
    assert result["error"] == "Content can't be blank"
    assert result["error_details"]["errors"][0]["source"] == {
        "pointer": "/data/fields/content"
    }
    with pytest.raises(ValueError, match="query must be valid JSON"):
        await _node("list_teams", query_json="[").execute({})
    with pytest.raises(ValueError, match="body must be a JSON object or array"):
        await _node("create_note", body_json='"string"').execute({})


@pytest.mark.asyncio
async def test_oauth_exchange_and_rotating_refresh(monkeypatch):
    monkeypatch.setenv("PRODUCTBOARD_CLIENT_ID", "client-id")
    monkeypatch.setenv("PRODUCTBOARD_CLIENT_SECRET", "client-secret")
    calls = []

    async def fake_post(self, url, **kwargs):
        calls.append((url, kwargs["params"]))
        if kwargs["params"]["grant_type"] == "authorization_code":
            return httpx.Response(
                200,
                json={
                    "access_token": "access-1",
                    "refresh_token": "refresh-1",
                    "expires_in": 60,
                },
            )
        return httpx.Response(
            200,
            json={
                "access_token": "access-2",
                "refresh_token": "refresh-2",
                "expires_in": 60,
            },
        )

    async def fake_get(self, url, **kwargs):
        assert kwargs["params"] == {"access_token": "access-1"}
        return httpx.Response(
            200,
            json={
                "space": {"name": "Demo space", "domain": "demo"},
                "resource_owner": {"email": "test@example.com"},
            },
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    tokens, name = await oauth.OAUTH_PROVIDER.exchange(
        "code", "https://example.com/callback", "a" * 43
    )
    assert (tokens.access_token, tokens.refresh_token, name) == (
        "access-1",
        "refresh-1",
        "Demo space",
    )
    renewed = await oauth.refresh_access_token("refresh-1")
    assert (renewed.access_token, renewed.refresh_token) == ("access-2", "refresh-2")
    assert calls[0][1]["client_secret"] == "client-secret"
    assert calls[0][1]["code_verifier"] == "a" * 43
    assert calls[1][1]["refresh_token"] == "refresh-1"


@pytest.mark.asyncio
async def test_refresh_rejects_missing_rotated_token(monkeypatch):
    monkeypatch.setenv("PRODUCTBOARD_CLIENT_ID", "id")
    monkeypatch.setenv("PRODUCTBOARD_CLIENT_SECRET", "secret")

    async def fake_post(self, url, **kwargs):
        return httpx.Response(200, json={"access_token": "new"})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    with pytest.raises(ValueError, match="refresh_token"):
        await oauth.refresh_access_token("used")


def test_json_fields_describe_their_wire_shapes():
    schema = PRODUCTBOARD_CONFIGS["create_note_comment"].model_json_schema()
    assert schema["properties"]["query_json"]["contentSchema"] == {"type": "object"}
    body = schema["properties"]["body_json"]
    assert body["contentMediaType"] == "application/json"
    assert body["contentSchema"]["properties"]["data"]["required"] == ["content"]
    assert schema["properties"]["id"]["format"] == "uuid"


@pytest.mark.asyncio
@pytest.mark.parametrize("payload,status", [({}, 200), ({"space": {"name": ""}}, 200), ({}, 401)])
async def test_oauth_requires_verified_workspace_without_exposing_token(monkeypatch, payload, status):
    async def fake_get(self, url, **kwargs):
        return httpx.Response(status, json=payload)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    with pytest.raises(ValueError) as error:
        await oauth.OAUTH_PROVIDER.account_name("private-access-token")
    assert "private-access-token" not in str(error.value)


@pytest.mark.asyncio
async def test_query_scalar_is_still_rejected():
    with pytest.raises(ValueError, match="query must be a JSON object"):
        await _node("list_notes", query_json="1").execute({})


@pytest.mark.asyncio
async def test_oauth_transport_error_does_not_expose_query_secrets(monkeypatch):
    monkeypatch.setenv("PRODUCTBOARD_CLIENT_ID", "id")
    monkeypatch.setenv("PRODUCTBOARD_CLIENT_SECRET", "secret")

    async def fake_post(self, **kwargs):
        raise httpx.ConnectError("https://app.productboard.com/oauth2/token?client_secret=secret")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    with pytest.raises(ValueError, match="token request failed") as error:
        await oauth.refresh_access_token("refresh-private")
    assert "secret" not in str(error.value)
    assert "refresh-private" not in str(error.value)
