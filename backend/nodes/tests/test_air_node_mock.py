"""Air wire contract and poll lifecycle, using the published OpenAPI fields."""
import copy
import json
import re
from pathlib import Path
from jsonschema import Draft4Validator, RefResolver
from unittest.mock import Mock
import httpx
import pytest
import respx
from nodes.air_node import AirAPIKeyCredential, AirNode, AirNodeConfig
from nodes.core.poll_trigger import poll_scope


def node(operation, **values):
    return AirNode(node_id="air-test", node_type="automation-air", node_data={}, sio=Mock(),
        config=AirNode.parse_config({"config": {"operation": operation, **values},
            "credentials": {"api_key": "test-air-key", "workspace_id": "workspace-id"}}))


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,method,path,body", [
    ("list_assets", {"limit": 10, "search": "Brand"}, "GET", "/assets", None),
    ("get_asset", {"assetId": "asset-id"}, "GET", "/assets/asset-id", None),
    ("list_asset_versions", {"assetId": "asset-id"}, "GET", "/assets/asset-id/versions", None),
    ("get_asset_version", {"assetId": "asset-id", "versionId": "version-id"}, "GET", "/assets/asset-id/versions/version-id", None),
    ("update_asset_version", {"assetId": "asset-id", "versionId": "version-id", "title": "Updated Title"}, "PATCH", "/assets/asset-id/versions/version-id", {"title": "Updated Title"}),
    ("add_version_tag", {"assetId": "asset-id", "versionId": "version-id", "id": "tag-id"}, "POST", "/assets/asset-id/versions/version-id/tags", {"id": "tag-id"}),
    ("remove_version_tag", {"assetId": "asset-id", "versionId": "version-id", "tagId": "tag-id"}, "DELETE", "/assets/asset-id/versions/version-id/tags/tag-id", None),
    ("list_boards", {"limit": 10}, "GET", "/boards", None),
    ("get_board", {"boardId": "board-id"}, "GET", "/boards/board-id", None),
    ("create_board", {"title": "Brand Assets"}, "POST", "/boards", {"title": "Brand Assets"}),
    ("update_board", {"boardId": "board-id", "parentBoardId": None}, "PATCH", "/boards/board-id", {"parentBoardId": None}),
    ("delete_board", {"boardId": "board-id"}, "DELETE", "/boards/board-id", None),
    ("add_board_assets", {"boardId": "board-id", "assetIds": ["asset-id-1", "asset-id-2"]}, "POST", "/boards/board-id/assets", {"assetIds": ["asset-id-1", "asset-id-2"]}),
    ("remove_board_asset", {"boardId": "board-id", "assetId": "asset-id"}, "DELETE", "/boards/board-id/assets/asset-id", None),
    ("list_tags", {"name": "Brand"}, "GET", "/tags", None),
    ("create_tag", {"name": "New Tag"}, "POST", "/tags", {"name": "New Tag"}),
    ("update_tag", {"tagId": "tag-id", "name": "Updated Tag"}, "PATCH", "/tags/tag-id", {"name": "Updated Tag"}),
    ("delete_tag", {"tagId": "tag-id"}, "DELETE", "/tags/tag-id", None),
    ("import_asset", {"sourceUrl": "https://example.com/image.jpg", "fileName": "image.jpg"}, "POST", "/imports", {"sourceUrl": "https://example.com/image.jpg", "fileName": "image.jpg"}),
    ("get_import_status", {"importId": "import-id"}, "GET", "/imports/import-id/status", None),
    ("list_libraries", {"search": "Brand"}, "GET", "/libraries", None),
])
async def test_wire_contract(operation, config, method, path, body):
    with respx.mock(assert_all_called=True) as router:
        route = router.request(method, "https://api.air.inc/v1" + path).mock(return_value=httpx.Response(204))
        assert await node(operation, **config).execute({}) == {"ok": True}
    request = route.calls[0].request
    contract = json.loads((Path(__file__).parent / "fixtures/air/openapi.json").read_text())
    matches = [(template, item) for template, item in contract["paths"].items()
               if re.fullmatch(re.sub(r"\{[^}]+\}", "[^/]+", template), request.url.path)
               and method.lower() in item]
    assert len(matches) == 1
    template, item = matches[0]
    published = item[method.lower()]
    parameters = item.get("parameters", []) + published.get("parameters", [])
    assert set(request.url.params) <= {p["name"] for p in parameters if p["in"] == "query"}
    for parameter in parameters:
        if parameter["in"] == "query" and parameter["name"] in request.url.params:
            Draft4Validator(parameter["schema"]).validate(request.url.params[parameter["name"]])
    if body is not None:
        schema = published["requestBody"]["content"]["application/json"]["schema"]
        # OAS 3.0 nullable extends JSON Schema Draft 4.
        schema = copy.deepcopy(schema)
        for prop in schema.get("properties", {}).values():
            if prop.get("nullable") and "type" in prop:
                prop["type"] = [prop["type"], "null"]
        Draft4Validator(schema, resolver=RefResolver.from_schema(contract)).validate(json.loads(request.content))
    assert request.headers["x-api-key"] == "test-air-key"
    assert request.headers["x-air-workspace-id"] == "workspace-id"
    assert "authorization" not in request.headers
    assert (json.loads(request.content) if request.content else None) == body
    if "limit" in config:
        assert request.url.params["limit"] == "10"
    for field in ("search", "name"):
        if method == "GET" and field in config:
            assert request.url.params[field] == config[field]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
async def test_provider_errors_are_rejected_and_redacted(status):
    with respx.mock:
        respx.get("https://api.air.inc/v1/boards").mock(return_value=httpx.Response(status, json={"message": "Rejected test-air-key"}))
        with pytest.raises(ValueError, match=f"Air API error {status}: Rejected \\[redacted\\]"):
            await node("list_boards").execute({})


def state_store(monkeypatch, instance):
    state = {}
    async def update(mutator, **kwargs):
        new, result = mutator(copy.deepcopy(state))
        if new is not None:
            state.clear()
            state.update(new)
        return result
    monkeypatch.setattr(instance, "_update_node_state", update)
    return state


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["asset", "board"])
async def test_poll_baseline_updates_scope_and_agent_event(monkeypatch, kind):
    # These fields and envelopes are defined in GET /v1/assets and /v1/boards.
    # Asset changes use coverVersion (updatedAt is absent from that schema).
    instance = node("on_new_or_updated_" + kind, parentBoardId="board-id")
    state_store(monkeypatch, instance)
    row = {"id": kind + "-id", **({"coverVersion": {"id": "version-id", "title": "Brand Assets", "description": "Logos"}} if kind == "asset" else {"title": "Brand Assets", "updatedAt": "2024-01-01T00:00:00Z"})}
    with respx.mock as router:
        route = router.get("https://api.air.inc/v1/" + kind + "s").mock(return_value=httpx.Response(200, json={"data": [row], "pagination": {"hasMore": False, "cursor": None}, "total": 1}))
        assert (await instance.execute({}))["event_count"] == 0
        assert (await instance.execute({}))["event_count"] == 0
        if kind == "asset":
            row["coverVersion"]["title"] = "Updated Title"
        else:
            row["updatedAt"] = "2024-01-02T00:00:00Z"
        route.mock(return_value=httpx.Response(200, json={"data": [row], "pagination": {"hasMore": False, "cursor": None}, "total": 1}))
        output = await instance.execute({})
        assert output["event_count"] == 1
        event = instance.resolve_agent_event(output)
        assert kind + "-id" in event["text"] and "board-id" in event["text"]
        assert instance.should_propagate_output(output, {"operation": "on_new_or_updated_" + kind})
        assert (await instance.execute({}))["event_count"] == 0
        if kind == "asset":
            row["coverVersion"]["title"] = "Brand Assets"
        else:
            row["updatedAt"] = "2024-01-03T00:00:00Z"
        route.mock(return_value=httpx.Response(200, json={"data": [row], "pagination": {"hasMore": False, "cursor": None}, "total": 1}))
        assert (await instance.execute({}))["event_count"] == 1
    assert route.calls[0].request.url.params["parentBoardId"] == "board-id"
    assert poll_scope(AirNode, {"operation": "on_new_or_updated_" + kind, "parentBoardId": "one"}) != poll_scope(AirNode, {"operation": "on_new_or_updated_" + kind, "parentBoardId": "two"})


@pytest.mark.asyncio
async def test_poll_pagination_failure_never_records_partial_baseline(monkeypatch):
    instance = node("on_new_or_updated_board")
    state = state_store(monkeypatch, instance)
    with respx.mock:
        respx.get("https://api.air.inc/v1/boards").mock(side_effect=[
            httpx.Response(200, json={"data": [{"id": "one"}], "pagination": {"hasMore": True, "cursor": "next"}}),
            httpx.Response(200, json={"data": [{"id": "two"}], "pagination": {"hasMore": True, "cursor": "next"}}),
        ])
        with pytest.raises(ValueError, match="nonadvancing"):
            await instance.execute({})
    assert state == {}


def test_manual_credential_and_write_validation():
    credential = AirAPIKeyCredential(api_key=" key ", workspace_id=" workspace ")
    assert credential.credential_type == "air_api_key" and credential.api_key == "key"
    with pytest.raises(ValueError):
        AirAPIKeyCredential(api_key="key\ninjected", workspace_id="workspace")
    with pytest.raises(ValueError, match="parent board or a library"):
        node("create_board", title="Brand", parentBoardId="one", libraryId="two")
    with pytest.raises(ValueError, match="at least one"):
        node("update_board", boardId="one")


def test_path_traversal_is_rejected():
    with pytest.raises(ValueError, match="resource ID"):
        node("get_asset", assetId="..")
