"""Clio Manage v4 route, regional OAuth, and request transport contracts."""

import base64
import json
import re
from pathlib import Path
from unittest.mock import Mock
from urllib.parse import quote

import httpx
import pytest
import respx

from nodes.clio_node import (
    CONFIG_MODELS, OPERATIONS, ClioNode, ClioNodeConfig, ClioOAuthCredential,
)
from nodes.oauth.clio_oauth import OAUTH_PROVIDER
from nodes.core.binary_output import BinaryOutput


def make_node(config, credential=None):
    return ClioNode(
        node_id="clio-test", node_type="automation-clio", node_data={},
        config=ClioNodeConfig(config=config, credentials=credential or
                              ClioOAuthCredential(access_token="access", refresh_token="refresh",
                                                  expires_at="2099-01-01T00:00:00Z")),
        sio=Mock(), sid="sid", workflow_id="workflow", user_id="user",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("name,spec", list(OPERATIONS.items()))
async def test_every_action_dispatches_to_official_route(name, spec, monkeypatch):
    path_args = {field: "sample/id" for field in re.findall(r"\{([^}]+)\}", spec.path)}
    query = {field: "required-value" for field in spec.required_query}
    config = CONFIG_MODELS[name](
        operation=name, **path_args,
        **({"query_json": json.dumps(query)} if spec.required_query else {}),
    )
    node = make_node(config)
    async def token(_credential):
        return "access"
    monkeypatch.setattr(node, "_access_token", token)
    path = spec.path
    for field, value in path_args.items():
        path = path.replace("{" + field + "}", quote(value, safe=""))
    with respx.mock(assert_all_called=True) as router:
        route = router.request(spec.method, "https://app.clio.com/api/v4" + path).mock(
            return_value=httpx.Response(200, json={"data": {"id": 1}}))
        result = await node.execute({})
    assert route.called
    request = route.calls[0].request
    assert request.headers["Authorization"] == "Bearer access"
    for field in spec.required_query:
        assert request.url.params[field] == "required-value"
    assert result["data"] == {"data": {"id": 1}}


@pytest.mark.asyncio
async def test_docket_preview_accepts_only_required_query_parameters(monkeypatch):
    # Clio documents service_type[id] and start_time as optional:
    # https://docs.developers.clio.com/clio-manage/api-reference/#tag/Matter-Dockets/operation/MatterDocket%23preview
    query = {"jurisdiction[id]": 0, "start_date": "2019-08-24", "trigger[id]": 0}
    node = make_node(CONFIG_MODELS["matter_docket_preview"](query_json=json.dumps(query)))

    async def token(_credential):
        return "access"

    monkeypatch.setattr(node, "_access_token", token)
    response = json.loads((Path(__file__).parent / "fixtures" / "clio" / "matter_docket_preview.json").read_text())
    with respx.mock(assert_all_called=True) as router:
        route = router.get("https://app.clio.com/api/v4/court_rules/matter_dockets/preview.json").mock(
            return_value=httpx.Response(200, json=response))
        await node.execute({})
    assert dict(route.calls[0].request.url.params) == {key: str(value) for key, value in query.items()}


@pytest.mark.asyncio
async def test_multipart_upload(monkeypatch):
    name = "document_create"
    assert name in OPERATIONS
    config = CONFIG_MODELS[name](headers_json='{"If-Match":"etag-1"}', form_json=json.dumps({
        "data[file]": {"base64": base64.b64encode(b"hello").decode(),
                       "filename": "a.txt", "content_type": "text/plain"},
    }))
    credential = ClioOAuthCredential(
        access_token="eu-access", refresh_token="eu-refresh", region="us")
    node = make_node(config, credential)
    async def token(_credential):
        return "eu-access"
    monkeypatch.setattr(node, "_access_token", token)
    with respx.mock(assert_all_called=True) as router:
        route = router.post("https://app.clio.com/api/v4/documents.json").mock(
            return_value=httpx.Response(201, json={"data": {"id": 2}}))
        await node.execute({})
    request = route.calls[0].request
    assert b"hello" in request.content
    assert request.headers["Authorization"] == "Bearer eu-access"
    assert request.headers["If-Match"] == "etag-1"


@pytest.mark.asyncio
async def test_auth_header_cannot_be_overridden(monkeypatch):
    node = make_node(CONFIG_MODELS["user_who_am_i"](
        headers_json='{"Authorization":"Bearer attacker"}'))
    async def token(_credential):
        return "access"
    monkeypatch.setattr(node, "_access_token", token)
    with pytest.raises(ValueError, match="cannot be overridden"):
        await node.execute({})


@pytest.mark.asyncio
async def test_urlencoded_body_transport(monkeypatch):
    node = make_node(CONFIG_MODELS["activity_create"](
        form_json='{"data[date]":"2026-09-28", "data[quantity]":2}',
        form_encoding="urlencoded"))
    async def token(_credential):
        return "access"
    monkeypatch.setattr(node, "_access_token", token)
    with respx.mock(assert_all_called=True) as router:
        route = router.post("https://app.clio.com/api/v4/activities.json").mock(
            return_value=httpx.Response(201, json={"data": {"id": 8}}))
        await node.execute({})
    request = route.calls[0].request
    assert request.headers["Content-Type"] == "application/x-www-form-urlencoded"
    assert dict(httpx.QueryParams(request.content.decode())) == {
        "data[date]": "2026-09-28", "data[quantity]": "2"}


@pytest.mark.asyncio
async def test_binary_response(monkeypatch):
    name = next(n for n, op in OPERATIONS.items() if op.method == "GET" and "download" in n)
    spec = OPERATIONS[name]
    kwargs = {field: "sample" for field in re.findall(r"\{([^}]+)\}", spec.path)}
    if spec.required_query:
        kwargs["query_json"] = json.dumps({field: "x" for field in spec.required_query})
    node = make_node(CONFIG_MODELS[name](**kwargs))
    async def token(_credential):
        return "access"
    monkeypatch.setattr(node, "_access_token", token)
    path = spec.path
    for field in kwargs:
        if "{" + field + "}" in path:
            path = path.replace("{" + field + "}", "sample")
    with respx.mock(assert_all_called=True) as router:
        router.get("https://app.clio.com/api/v4" + path).mock(
            return_value=httpx.Response(200, content=b"\x00\x01", headers={"content-type": "application/pdf"}))
        result = await node.execute({})
    assert isinstance(result["data"], BinaryOutput)
    assert result["data"].data == b"\x00\x01"
    assert result["data"].content_type == "application/pdf"




@pytest.mark.asyncio
async def test_declared_oauth_exchange_and_refresh(monkeypatch):
    monkeypatch.setenv("CLIO_CLIENT_ID", "client")
    monkeypatch.setenv("CLIO_CLIENT_SECRET", "secret")
    with respx.mock(assert_all_called=True) as router:
        token = router.post(OAUTH_PROVIDER.token_url).mock(side_effect=[
            httpx.Response(200, json={"access_token": "first", "refresh_token": "renew", "expires_in": 2592000}),
            httpx.Response(200, json={"access_token": "second", "expires_in": 2592000}),
        ])
        identity = router.get(OAUTH_PROVIDER.identity_url).mock(
            return_value=httpx.Response(200, json={"data": {"id": 7, "name": "Test User"}}))
        first, name = await OAUTH_PROVIDER.exchange("code", "https://example.com/callback")
        second = await OAUTH_PROVIDER.refresh(first.refresh_token)
    assert name == "Test User"
    assert first.access_token == "first" and second.access_token == "second"
    assert identity.calls[0].request.headers["Authorization"] == "Bearer first"
    assert dict(httpx.QueryParams(token.calls[0].request.content.decode()))["grant_type"] == "authorization_code"
    assert dict(httpx.QueryParams(token.calls[1].request.content.decode()))["grant_type"] == "refresh_token"
