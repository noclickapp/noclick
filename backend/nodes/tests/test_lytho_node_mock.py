"""Exercise Lytho's real factory, wire operations, and scoped poll baseline.

Responses below are synthetic instances of the published OpenAPI schemas, not
recorded account responses; conformance validates the full provider contract.
"""
import copy
import json
from datetime import datetime
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import lytho_node as native
from nodes.core.poll_trigger import poll_scope
from nodes.core.registry import NODE_REGISTRY, NodeFactory

TOKEN = "synthetic-lytho-key"
CREDENTIAL = {"credential_type": "lytho_api_key", "api_key": TOKEN}
ASSET = json.loads((Path(__file__).parent / "fixtures/lytho/asset.json").read_text())["body"]


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="lytho-test", node_type="automation-lytho",
        node_data={"config": config, "credentials": CREDENTIAL})


def transport(monkeypatch, reply):
    requests = []
    def respond(request):
        requests.append(request)
        return reply(request) if callable(reply) else httpx.Response(200, json=reply)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", native.OPERATIONS)
async def test_all_lytho_operations_real_factory_wire_and_body(monkeypatch, operation):
    method, route, query_fields, body_fields = native.OPERATIONS[operation]
    config = {"operation": operation, "asset_id": "asset-42", "tag_id": "tag-1",
              "collection_id": "collection-9", "name": "Brand kit", "locale": "en",
              "searchQuery": "brand", "page": 2, "size": 50,
              "description": "Approved", "visibleToEveryone": False,
              "assets": ["asset-42"], "permissions": [1]}
    # Retain only this operation's declared fields.
    cls = next(c for c in native.LythoConfig.__args__[0].__args__
               if c.model_fields["operation"].default == operation)
    config = {k: v for k, v in config.items() if k in cls.model_fields}
    result_body = {"content": [ASSET], "last": True} if "page" in query_fields else ASSET
    requests = transport(monkeypatch, lambda r: httpx.Response(
        204 if operation in {"delete_asset", "delete_collection", "delete_tag"} else
        201 if method == "POST" else 200,
        **({} if operation in {"delete_asset", "delete_collection", "delete_tag"} else {"json": result_body})))
    result = await node(config).execute({})
    assert NODE_REGISTRY["automation-lytho"] is native.LythoNode
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.host == "openapi.lytho.io"
    for key, value in config.items():
        route = route.replace("{" + key + "}", str(value))
    assert request.url.path == "/v1" + route
    assert request.headers["x-api-key"] == TOKEN
    assert dict(request.url.params) == {key: str(config[key]) for key in query_fields if key in config}
    assert (json.loads(request.content) if request.content else None) == (
        {key: config[key] for key in body_fields if key in config} if body_fields else None)
    assert result["data"] == ({"deleted": True} if operation.startswith("delete_") else result_body)
    assert TOKEN not in str(result)


@pytest.mark.asyncio
async def test_lytho_filters_and_manual_credential(monkeypatch):
    assert native.LythoAPIKeyCredential(api_key=TOKEN).credential_type == "lytho_api_key"
    requests = transport(monkeypatch, {"content": [], "last": True})
    await node({"operation": "list_assets", "tagIds": ["one", "two"],
                "creationDateFrom": "2026-11-01T00:00:00Z"}).execute({})
    assert requests[0].url.params.get_list("tagIds") == ["one", "two"]
    assert datetime.fromisoformat(requests[0].url.params["creationDateFrom"]) is not None
    assert native.LythoNode.connection_evidence.operation == "list_collections"
    for key in ["https://example.com/key", "Bearer token with spaces"]:
        with pytest.raises(ValidationError):
            native.LythoAPIKeyCredential(api_key=key)
    with pytest.raises(ValidationError):
        native.LythoGetAssetConfig(asset_id="../tags")


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
async def test_lytho_failure_never_retries_or_leaks_key(monkeypatch, status):
    requests = transport(monkeypatch, lambda r: httpx.Response(status, json={"message": TOKEN}))
    with pytest.raises(ValueError) as exc:
        await node({"operation": "create_tag", "name": "Brand"}).execute({})
    assert TOKEN not in str(exc.value) and str(status) in str(exc.value)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"content": "not a list"}, []])
async def test_lytho_connection_evidence_refuses_malformed_pages(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError, match="unexpected JSON"):
        await node({"operation": "list_collections"}).execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,date_filter", [("on_new_asset", "creationDateFrom"),
                                                   ("on_updated_asset", "modificationDateFrom")])
async def test_lytho_poll_baseline_dedup_updates_and_human_event(monkeypatch, operation, date_filter):
    rows = [copy.deepcopy(ASSET)]
    requests = transport(monkeypatch, lambda r: httpx.Response(200, json={"content": rows, "last": True}))
    instance = node({"operation": operation, "fileName": "brand.png", "lookback_hours": 24})
    state = {}
    async def update(mutator, **kwargs):
        nonlocal state
        new_state, result = mutator(state)
        if new_state is not None:
            state = new_state
        return result
    monkeypatch.setattr(instance, "_update_node_state", update)
    first = await instance.execute({})
    assert first["assets"] == [] and instance.trigger_produced_no_event(first)
    assert date_filter in requests[0].url.params and requests[0].url.params["fileName"] == "brand.png"
    rows.append({**ASSET, "id": "asset-new", "name": "New brand"})
    second = await instance.execute({})
    assert [a["id"] for a in second["assets"]] == ["asset-new"]
    assert instance.trigger_emitted_event(second)
    event = native.LythoNode.resolve_agent_event(second)
    assert "New brand" in event["text"] and "asset-new" in event["text"]
    assert "creator-1" in event["text"]
    assert (await instance.execute({}))["assets"] == []
    rows[0]["modificationDate"] = "2026-11-09T20:00:00Z"
    third = await instance.execute({})
    assert len(third["assets"]) == (1 if operation == "on_updated_asset" else 0)
    base = {"operation": operation}
    assert poll_scope(native.LythoNode, base) == poll_scope(native.LythoNode, {**base, "label": "Cosmetic"})
    assert poll_scope(native.LythoNode, base) != poll_scope(native.LythoNode, {**base, "fileName": "other.png"})


@pytest.mark.asyncio
async def test_lytho_poll_reads_all_pages_before_advancing_state(monkeypatch):
    first = [{**ASSET, "id": f"asset-{i}"} for i in range(50)]
    requests = transport(monkeypatch, lambda r: httpx.Response(200, json={
        "content": first if r.url.params["page"] == "0" else [ASSET],
        "last": r.url.params["page"] == "1"}))
    instance = node({"operation": "on_new_asset"})
    captured = []
    async def filter_items(items, id_fn):
        captured.extend(items)
        return items
    monkeypatch.setattr(instance, "_filter_unseen", filter_items)
    assert (await instance.execute({}))["asset_count"] == 51
    assert len(requests) == 2 and len(captured) == 51
    transport(monkeypatch, {"content": first, "last": False})
    with pytest.raises(ValueError, match="500"):
        await instance.execute({})
    assert len(captured) == 51  # Failure never consumes a partial poll.


@pytest.mark.asyncio
async def test_lytho_poll_uses_page_count_when_last_flag_is_omitted(monkeypatch):
    # All page metadata is optional in PageAssetExternalResponse. A short
    # intermediate page must not hide later assets when totalPages is present.
    requests = transport(monkeypatch, lambda r: httpx.Response(200, json={
        "content": [{**ASSET, "id": "asset-" + r.url.params["page"]}],
        "totalPages": 3}))
    instance = node({"operation": "on_new_asset"})
    async def filter_items(items, id_fn):
        return items
    monkeypatch.setattr(instance, "_filter_unseen", filter_items)
    assert (await instance.execute({}))["asset_count"] == 3
    assert [r.url.params["page"] for r in requests] == ["0", "1", "2"]
