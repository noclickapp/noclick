"""Braze official action catalog, credential, and request contract tests."""

import json
import re
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from pydantic import ValidationError

from nodes.braze_node import BrazeApiKeyCredential, BrazeNode, BrazeNodeConfig, CONFIG_MODELS, _field_name
from nodes.braze_node import OPERATIONS


CREDENTIAL = {
    "credential_type": "braze_api_key",
    "api_key": "sensitive-test-key",
    "rest_endpoint": "https://rest.iad-01.braze.com",
}


def node_for(operation: str, **fields):
    node = object.__new__(BrazeNode)
    node._config = BrazeNodeConfig.model_validate({
        "config": {"operation": operation, **fields}, "credentials": CREDENTIAL,
    })
    node.node_data = {}
    node.user_id = None
    return node


def fields_for(op):
    values = {key: "id/with space" for key in re.findall(r"\{([^}]+)\}", op.path)}
    for key, required, _, _ in op.query:
        if required:
            values[_field_name(key)] = "sample"
    if op.body:
        values["body_json"] = '{"example":"value"}'
    return values


@pytest.mark.parametrize("name", OPERATIONS)
@pytest.mark.asyncio
async def test_every_documented_braze_action_dispatches(name):
    op = OPERATIONS[name]
    node = node_for(name, **fields_for(op))
    with patch.object(BrazeNode, "_request", new_callable=AsyncMock) as request:
        request.return_value = {"message": "success"}
        result = await node.execute({})
    request.assert_awaited_once()
    method, path, credential, params, body = request.await_args.args
    assert method == op.method
    assert path.startswith("/") and "{" not in path
    if "{" in op.path:
        assert "%2F" in path
    assert credential.api_key == CREDENTIAL["api_key"]
    assert set(params) == {key for key, required, _, _ in op.query if required}
    assert body == ({"example": "value"} if op.body else None)
    assert result == {"status": "success", "operation": name, "data": {"message": "success"}}


def test_catalog_is_official_and_complete():
    assert len(OPERATIONS) == len(CONFIG_MODELS) == 150
    assert BrazeNode.connection_evidence.operation in OPERATIONS
    assert len({(op.method, op.path) for op in OPERATIONS.values()}) == len(OPERATIONS)
    for op in OPERATIONS.values():
        assert op.docs_url.startswith("https://www.braze.com/docs/api/endpoints/")
        assert op.path.startswith("/")
        assert op.method in {"GET", "POST", "PUT", "PATCH", "DELETE"}


@pytest.mark.parametrize("endpoint", [
    "http://rest.iad-01.braze.com",
    "https://evil.example.com",
    "https://rest.iad-01.braze.com.evil.test",
    "https://rest.iad-01.braze.com/path",
    "https://rest.iad-01.braze.com?next=x",
    "https://user:pass@rest.iad-01.braze.com",
    "https://rest.iad-01.braze.com:8443",
])
def test_rejects_untrusted_rest_endpoint(endpoint):
    with pytest.raises(ValidationError):
        BrazeApiKeyCredential(api_key="key", rest_endpoint=endpoint)


def test_accepts_documented_us_eu_and_other_rest_endpoints():
    for endpoint in ["https://rest.iad-01.braze.com", "https://rest.fra-01.braze.eu",
                     "https://rest.jp-01.braze.com"]:
        assert BrazeApiKeyCredential(api_key="key", rest_endpoint=endpoint + "/").rest_endpoint == endpoint


@pytest.mark.asyncio
async def test_query_json_and_path_encoding():
    node = node_for("export_export_campaign_details", query_campaign_id="campaign", query_json=json.dumps({"include_archived": True}))
    with patch.object(BrazeNode, "_request", new_callable=AsyncMock) as request:
        await node.execute({})
    assert request.await_args.args[3]["include_archived"] == "true"
    with pytest.raises(ValueError, match="valid JSON"):
        await node_for("list_campaigns", query_json="{").execute({})
    with pytest.raises(ValueError, match="JSON object"):
        await node_for("track_users", body_json="[]").execute({})


@pytest.mark.asyncio
async def test_braze_http_request_and_partial_errors():
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(200, json={"message": "success", "errors": ["one user skipped"]})
    client = httpx.AsyncClient
    with patch("nodes.braze_node.httpx.AsyncClient",
               side_effect=lambda **kw: client(transport=httpx.MockTransport(respond), **kw)):
        result = await node_for("track_users", body_json='{"attributes":[{"external_id":"user-1"}]}').execute({})
    assert calls[0].url.path == "/users/track"
    assert calls[0].headers["Authorization"] == "Bearer sensitive-test-key"
    assert json.loads(calls[0].content)["attributes"][0]["external_id"] == "user-1"
    assert result["status"] == "partial"


@pytest.mark.asyncio
async def test_braze_error_never_echoes_api_key():
    def respond(request):
        return httpx.Response(401, json={"message": "Unauthorized"})
    client = httpx.AsyncClient
    with patch("nodes.braze_node.httpx.AsyncClient",
               side_effect=lambda **kw: client(transport=httpx.MockTransport(respond), **kw)):
        with pytest.raises(ValueError, match="Braze API error 401") as exc:
            await node_for("list_campaigns").execute({})
    assert "sensitive-test-key" not in str(exc.value)
