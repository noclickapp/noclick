"""past.dev's published request/response examples through the actual node factory."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import past_dev_node as native
from nodes.core.registry import NodeFactory

TOKEN = "past_sk_fixture_not_a_live_key"
CASES = json.loads((Path(__file__).parent / "fixtures/past-dev/wire.json").read_text())["cases"]


def node(config):
    return NodeFactory.create_node(node_id="past-dev-test", node_type="automation-past-dev", node_data={
        "config": config, "credentials": {"credential_type": "past_dev_api_key", "api_key": TOKEN},
    })


def transport(monkeypatch, status, body):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body) if body is not None else httpx.Response(status)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda case: case["config"]["operation"])
async def test_past_dev_documented_wire_and_responses(monkeypatch, case):
    requests = transport(monkeypatch, case["status"], case["response"])
    result = await node(case["config"]).execute({})
    assert result["status"] == "success"
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"]
    assert request.url.host == "api.past.dev" and request.url.path == case["path"]
    query = dict(case["query"])
    if case["config"]["operation"] == "list_identities":
        query.setdefault("limit", "100")
    assert dict(request.url.params) == query
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert TOKEN not in str(request.url)
    assert (json.loads(request.content) if request.content else None) == case["body"]
    if case["status"] == 204:
        assert result["completed"] is True
    else:
        assert result["data"] == case["response"]
        if case["config"]["operation"] in {"ingest", "ingest_batch", "delete_data_point", "delete_data_points", "retry_ingestion"}:
            assert result["http_status"] == 202 and "completed" not in result


@pytest.mark.asyncio
async def test_past_dev_patch_keeps_explicit_null_and_omits_unsupplied_traits(monkeypatch):
    requests = transport(monkeypatch, 200, {"identity": "dana@example.com"})
    await node({"operation": "patch_identity", "identity": "dana@example.com", "traits": {"team": None}}).execute({})
    assert json.loads(requests[0].content) == {"traits": {"team": None}}
    await node({"operation": "patch_identity", "identity": "dana@example.com"}).execute({})
    assert json.loads(requests[1].content) == {}


@pytest.mark.asyncio
async def test_past_dev_opaque_cursor_and_trait_filter(monkeypatch):
    requests = transport(monkeypatch, 200, {"identities": [{"identity": "dana@example.com"}], "hasMore": True, "endCursor": "cursor+/="})
    result = await node({"operation": "list_identities", "after": "previous+/=", "traitKey": "company", "traitValue": "acme"}).execute({})
    assert dict(requests[0].url.params) == {"limit": "100", "after": "previous+/=", "traitKey": "company", "traitValue": "acme"}
    assert result["next_page_token"] == "cursor+/=" and result["has_more"] is True
    assert result["items"] == [{"identity": "dana@example.com"}]


@pytest.mark.asyncio
async def test_past_dev_empty_identity_directory_and_connection_evidence(monkeypatch):
    transport(monkeypatch, 200, {"identities": [], "hasMore": False, "endCursor": None})
    result = await node({"operation": "list_identities"}).execute({})
    assert result["items"] == [] and result["has_more"] is False
    assert result["next_page_token"] is None
    assert native.PastDevNode.connection_evidence.operation == "list_identities"
    assert native.PastDevNode.connection_evidence.label_keys == ("identity",)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
async def test_past_dev_rejection_preserves_provider_message_and_redacts_key(monkeypatch, status):
    requests = transport(monkeypatch, status, {"code": "unauthorized", "status": status, "debugMessage": "Rejected " + TOKEN})
    result = await node({"operation": "get_usage"}).execute({})
    assert result == {"status": "error", "http_status": status, "error": "Rejected [redacted]"}
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, [], {"identities": [], "hasMore": True, "endCursor": None}, {"code": "unauthorized"}])
async def test_past_dev_invalid_identity_pages_fail(monkeypatch, body):
    transport(monkeypatch, 200, body)
    assert (await node({"operation": "list_identities"}).execute({}))["status"] == "error"


@pytest.mark.asyncio
async def test_past_dev_path_identifier_is_one_encoded_segment(monkeypatch):
    requests = transport(monkeypatch, 200, {"identity": "dana/emea?admin=true"})
    await node({"operation": "get_identity", "identity": "dana/emea?admin=true"}).execute({})
    assert requests[0].url.raw_path == b"/api/v1/identities/dana%2Femea%3Fadmin%3Dtrue"


@pytest.mark.parametrize("config", [
    {"operation": "ingest", "content": "  "},
    {"operation": "ingest", "content": "fact", "id": "a/b"},
    {"operation": "ingest_batch", "items": []},
    {"operation": "get_ingestion", "ingestion_id": "invalid"},
    {"operation": "recall", "query": "budget", "identity": "dana", "level": "low", "maxTokens": 100},
    {"operation": "put_audience", "slug": "acme", "kind": "fixed"},
    {"operation": "put_audience", "slug": "acme", "kind": "rule", "identities": []},
    {"operation": "delete_audience", "slug": "project"},
    {"operation": "list_identities", "limit": 1001},
])
def test_past_dev_invalid_configs(config):
    with pytest.raises(ValueError):
        node(config)


@pytest.mark.parametrize("key", ["Bearer secret", "https://example.com/key", "key\nheader", "<token>"])
def test_past_dev_bad_manual_keys(key):
    with pytest.raises(ValidationError):
        native.PastDevAPIKeyCredential(api_key=key)


def test_past_dev_hand_connect_default():
    credential = native.PastDevAPIKeyCredential(api_key=TOKEN)
    assert credential.credential_type == "past_dev_api_key"
    assert native.PastDevAPIKeyCredential.model_json_schema()["required"] == ["api_key"]


@pytest.mark.asyncio
async def test_past_dev_null_metadata_is_retained_but_absent_text_is_omitted(monkeypatch):
    requests = transport(monkeypatch, 202, {"status": "queued"})
    await node({"operation": "ingest", "content": "fact", "metadata": None, "label": None}).execute({})
    assert json.loads(requests[0].content) == {"content": "fact", "metadata": None}
    await node({"operation": "ingest_batch", "items": [{"content": "fact", "metadata": None, "label": None}]}).execute({})
    assert json.loads(requests[1].content) == {"items": [{"content": "fact", "metadata": None}]}
