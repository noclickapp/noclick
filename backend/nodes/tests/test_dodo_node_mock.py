"""Offline regressions against Nookipedia's published v1.7.0 schema examples."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import dodo_node as native
from nodes.core.registry import NodeFactory

KEY = "12345678-1234-4234-8234-123456789abc"
EXAMPLES = json.loads(
    (Path(__file__).parent / "fixtures/dodo/schema_examples.json").read_text()
)["operations"]


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(
        node_id="dodo-test",
        node_type="automation-dodo",
        node_data={"config": config, "credentials": {"api_key": KEY}},
    )


def transport(monkeypatch, body, status=200):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(status, json=body)

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", native.ROUTES)
async def test_each_operation_preserves_published_property_examples(
    monkeypatch, operation
):
    path, fields = native.ROUTES[operation]
    body = EXAMPLES[operation]
    name = body.get("name", "sea bass") if isinstance(body, dict) else None
    config = {"operation": operation, **{field: name for field in fields}}
    calls = transport(monkeypatch, body)
    result = await node(config).execute({})
    assert result["status"] == "success" and result["data"] == body
    assert result["source_url"] == "https://nookipedia.com/"
    assert len(calls) == 1 and calls[0].method == "GET"
    assert calls[0].url.host == "api.nookipedia.com"
    assert calls[0].headers["X-API-KEY"] == KEY
    assert calls[0].headers["Accept-Version"] == "1.7.0"
    for field in fields:
        path = path.replace("{" + field + "}", name)
    assert calls[0].url.path == path
    assert KEY not in json.dumps(result)


@pytest.mark.asyncio
async def test_filters_array_explode_and_false(monkeypatch):
    calls = transport(monkeypatch, ["Lily"])
    result = await node(
        {
            "operation": "list_villagers",
            "species": "frog",
            "game": ["NH", "PC"],
            "nhdetails": "false",
            "excludedetails": "true",
            "thumbsize": 128,
        }
    ).execute({})
    assert result["data"] == ["Lily"]
    assert calls[0].url.params.get_list("game") == ["NH", "PC"]
    assert dict(calls[0].url.params) == {
        "species": "frog",
        "game": "NH",
        "nhdetails": "false",
        "excludedetails": "true",
        "thumbsize": "128",
    }


@pytest.mark.asyncio
async def test_name_is_single_encoded_path_segment(monkeypatch):
    calls = transport(monkeypatch, {})
    await node({"operation": "get_item", "item": "A/B ?#% café"}).execute({})
    assert calls[0].url.raw_path == b"/nh/items/A%2FB%20%3F%23%25%20caf%C3%A9"


@pytest.mark.asyncio
@pytest.mark.parametrize("name", [".", "..", "bad\r\nname"])
async def test_rejects_unsafe_path_names_before_request(monkeypatch, name):
    calls = transport(monkeypatch, {})
    with pytest.raises(ValueError):
        await node({"operation": "get_item", "item": name}).execute({})
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
async def test_provider_failures_never_return_success(monkeypatch, status):
    transport(monkeypatch, {"error": "Request rejected"}, status)
    with pytest.raises(httpx.HTTPStatusError):
        await node({"operation": "list_villagers"}).execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "config,body",
    [
        ({"operation": "list_villagers"}, {}),
        ({"operation": "get_item", "item": "acorn"}, []),
        ({"operation": "get_item", "item": "acorn"}, {"error": "rejected"}),
    ],
)
async def test_unexpected_shapes_fail(monkeypatch, config, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError):
        await node(config).execute({})


def test_manual_credential_default_type_and_uuid_validation():
    credential = native.DodoAPIKeyCredential(api_key="  " + KEY + "  ")
    assert credential.credential_type == "dodo_api_key" and credential.api_key == KEY
    assert KEY not in repr(credential)
    for value in ["https://api.nookipedia.com/", "not-a-uuid", "", None]:
        with pytest.raises((ValueError, TypeError)):
            native.DodoAPIKeyCredential(api_key=value)


def test_contract_is_read_only_and_evidence_is_reachability():
    assert len(native.ROUTES) == 25
    evidence = native.DodoNode.connection_evidence
    assert evidence.operation == "list_villagers" and evidence.proves == "reachability"
    for config in [
        {"operation": "get_item"},
        {"operation": "list_events", "day": 32},
        {"operation": "list_fish", "thumbsize": 0},
        {"operation": "list_fish", "made_up": "x"},
    ]:
        with pytest.raises(ValidationError):
            native.DodoFullConfig(config=config)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["list_fish", "list_bugs", "list_sea"])
async def test_documented_current_month_hemisphere_shape(monkeypatch, operation):
    # The parameter's published prose specifies north/south arrays; their rows
    # use the same component property examples as the ordinary list response.
    body = {"north": EXAMPLES[operation], "south": []}
    calls = transport(monkeypatch, body)
    result = await node({"operation": operation, "month": "current"}).execute({})
    assert result["data"] == body and calls[0].url.params["month"] == "current"
    transport(monkeypatch, {"north": []})
    with pytest.raises(ValueError):
        await node({"operation": operation, "month": "current"}).execute({})
