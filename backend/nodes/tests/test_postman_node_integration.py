"""Postman API catalog, credential, URL, and response contracts."""

import re
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from nodes.core.binary_output import BinaryOutput, resolve_binary_outputs
from nodes.core.poll_trigger import poll_scope
from nodes.postman_node import (
    CONFIG_MODELS,
    PostmanApiKeyCredential,
    PostmanNode,
    PostmanNodeConfig,
)
from nodes.postman_node import OPERATIONS
from tests.utils.sweep import check_each


def documented_response(name):
    # Copied from Postman's OpenAPI 1.45.0 examples, published in its SDK repository:
    # https://github.com/postmanlabs/postman-api-sdk-ts/blob/main/tests/integration/openapi.yaml
    return json.loads((Path(__file__).parent / "fixtures" / "postman" / f"{name}.json").read_text())


@pytest.mark.parametrize("operation,fields,example,id_field,expected", [
    ("on_new_mock_call", {"mock_id": "a/b"}, "getMockCallLogs", "id", "POST /animals"),
    ("on_new_collection_fork", {"collection_id": "a/b"}, "getCollectionForks", "forkId", "Taylor Lee"),
])
@pytest.mark.asyncio
async def test_poll_documented_payload_baseline_dedup_and_agent_event(operation, fields, example, id_field, expected):
    node = node_for(operation, **fields)
    node.node_id = "postman-test"
    state = {}

    async def update(mutator, **kwargs):
        nonlocal state
        changed, result = mutator(state)
        if changed is not None:
            state = changed
        return result

    payload = documented_response(example)
    with patch.object(node, "_update_node_state", side_effect=update), patch.object(
        node, "_request", new_callable=AsyncMock, return_value=payload,
    ) as request:
        baseline = await node.execute({})
        assert baseline["new_item_count"] == 0
        assert not node.should_propagate_output(baseline, {"operation": operation})
        assert node.resolve_agent_event(baseline) is None
        # Simulate a persisted poll that saw nothing, then receive the provider's exact examples.
        state["seen_ids"] = []
        output = await node.execute({})
        assert output["new_item_count"] == len(output["items"]) > 0
        assert node.should_propagate_output(output, {"operation": operation})
        event = node.resolve_agent_event(output)
        assert expected in event["text"]
        assert output["items"][0][id_field] in event["text"]
        assert "a/b" in event["text"]
        assert (await node.execute({}))["new_item_count"] == 0
        args = request.await_args.args
        assert "a%2Fb" in args[1]
        assert args[3]["direction"] == "desc"
        if operation == "on_new_mock_call":
            assert args[3]["sort"] == "servedAt"
        # Changing the watched resource re-baselines; cosmetic fields don't.
        resource = next(iter(fields))
        original = {"operation": operation, **fields}
        assert poll_scope(PostmanNode, original) == poll_scope(PostmanNode, {**original, "label": "Renamed"})
        assert poll_scope(PostmanNode, original) != poll_scope(PostmanNode, {**original, resource: "different"})
        setattr(node._config.config, resource, "different")
        assert (await node.execute({}))["new_item_count"] == 0


@pytest.mark.asyncio
async def test_poll_paginates_before_recording_seen_items_and_refuses_cursor_loops():
    node = node_for("on_new_collection_fork", collection_id="source")
    page = documented_response("getCollectionForks")
    first = {"data": page["data"][:1], "meta": {"nextCursor": "next"}}
    last = {"data": page["data"][1:], "meta": {"nextCursor": None}}
    with patch.object(node, "_filter_unseen", new_callable=AsyncMock) as unseen, patch.object(
        node, "_request", new_callable=AsyncMock, side_effect=[first, last],
    ) as request:
        unseen.return_value = page["data"]
        result = await node.execute({})
        assert result["new_item_count"] == 2
        assert request.await_args.args[3]["cursor"] == "next"
        assert unseen.await_args.args[0] == page["data"]
    with patch.object(node, "_filter_unseen", new_callable=AsyncMock) as unseen, patch.object(
        node, "_request", new_callable=AsyncMock, return_value=first,
    ):
        with pytest.raises(ValueError, match="repeated a pagination cursor"):
            await node.execute({})
        unseen.assert_not_awaited()


@pytest.mark.asyncio
async def test_poll_rejects_invalid_payload_without_consuming_events():
    node = node_for("on_new_mock_call", mock_id="mock")
    for payload in ({"unexpected": []}, {"call-logs": [{}]}):
        with patch.object(node, "_filter_unseen", new_callable=AsyncMock) as unseen, patch.object(
            node, "_request", new_callable=AsyncMock, return_value=payload,
        ):
            with pytest.raises(ValueError, match="invalid trigger list|missing its identifier"):
                await node.execute({})
            unseen.assert_not_awaited()


def node_for(operation: str, **fields) -> PostmanNode:
    node = object.__new__(PostmanNode)
    node._config = PostmanNodeConfig.model_validate({
        "config": {"operation": operation, **fields},
        "credentials": {"credential_type": "postman_api_key", "api_key": "secret-key"},
    })
    node.node_data = {}
    node.user_id = None
    return node


async def _every_documented_action_can_dispatch(name):
    op = OPERATIONS[name]
    fields = {parameter: "a/b" for parameter in re.findall(r"\{([^}]+)\}", op.path)}
    if op.body_type != "none":
        fields["body_json"] = '{"example":"value"}'
    with patch.object(PostmanNode, "_request", new_callable=AsyncMock) as request:
        request.return_value = {"ok": True}
        result = await node_for(name, **fields).execute({})
    request.assert_awaited_once()
    called_op, path, credential, params, body = request.await_args.args
    assert called_op == op
    assert credential.api_key == "secret-key"
    assert path.startswith("/") and "{" not in path
    if fields and any(value == "a/b" for value in fields.values()):
        assert "a%2Fb" in path
    assert params == {}
    assert body == ({"example": "value"} if op.body_type != "none" else None)
    assert result == {"status": "success", "operation": name, "data": {"ok": True}}


@pytest.mark.asyncio
async def test_every_documented_action_can_dispatch():
    await check_each(OPERATIONS, _every_documented_action_can_dispatch)


def test_catalog_covers_core_postman_resources():
    assert len(OPERATIONS) == len(CONFIG_MODELS) == 173
    assert len({op.category for op in OPERATIONS.values()}) == 17
    assert PostmanNode.connection_evidence.operation == "get_authenticated_user"
    assert OPERATIONS["get_authenticated_user"].path == "/me"
    assert OPERATIONS["collections_create_collection"].path == "/collections"
    assert OPERATIONS["workspaces_get_workspaces"].path == "/workspaces"
    assert all(op.docs_url.startswith("https://learning.postman.com/api-docs/api-reference/")
               for op in OPERATIONS.values())


@pytest.mark.asyncio
async def test_api_key_region_and_json_request():
    seen = []
    original_client = httpx.AsyncClient

    def respond(request):
        seen.append(request)
        return httpx.Response(200, json={"collection": {"id": "col-1"}})

    credential = PostmanApiKeyCredential(api_key="secret-key", region="eu")
    op = OPERATIONS["collections_create_collection"]
    with patch("nodes.postman_node.httpx.AsyncClient", side_effect=lambda **kw: original_client(
            transport=httpx.MockTransport(respond), **kw)):
        data = await PostmanNode._request(
            op, "/collections", credential, {"workspace": "ws-1"},
            {"collection": {"info": {"name": "QA"}, "item": []}},
        )
    assert str(seen[0].url) == "https://api.eu.postman.com/collections?workspace=ws-1"
    assert seen[0].headers["x-api-key"] == "secret-key"
    assert seen[0].headers["Content-Type"] == "application/json"
    assert seen[0].method == "POST"
    assert data["collection"]["id"] == "col-1"


@pytest.mark.asyncio
async def test_workspace_update_uses_documented_merge_patch_content_type():
    # https://learning.postman.com/api-docs/api-reference/workspaces/patch-workspace-update
    original_client = httpx.AsyncClient
    seen = []

    def respond(request):
        seen.append(request)
        return httpx.Response(200, json={"id": 25})

    with patch("nodes.postman_node.httpx.AsyncClient", side_effect=lambda **kw: original_client(
        transport=httpx.MockTransport(respond), **kw,
    )):
        await node_for("workspaces_patch_workspace_update", workspaceId="workspace", updateId="25",
                       body_json='{"topic":"Update","description":"Details","category":"improvement"}').execute({})
    assert seen[0].headers["content-type"] == "application/merge-patch+json"


@pytest.mark.asyncio
async def test_url_encoding_query_validation_and_credential_requirement():
    with patch.object(PostmanNode, "_request", new_callable=AsyncMock) as request:
        request.return_value = {"collection": {"id": "col-1"}}
        await node_for("collections_get_collection", collectionId="a/b", query_json='{"foo":2}').execute({})
    assert request.await_args.args[1] == "/collections/a%2Fb"
    assert request.await_args.args[3] == {"foo": 2}
    assert PostmanNode._query_value(True) == "true"
    assert PostmanNode._query_value({"a": 1}) == '{"a":1}'
    assert PostmanNode._query_value([True, False]) == ["true", "false"]
    with pytest.raises(ValueError, match="Query Parameters JSON must be a JSON object"):
        await node_for("collections_get_collections", query_json="[]").execute({})
    with pytest.raises(ValueError, match="Request Body JSON must be valid JSON"):
        await node_for("collections_create_collection", body_json="{").execute({})
    node = node_for("get_authenticated_user")
    node._config = PostmanNodeConfig.model_validate({
        "config": {"operation": "get_authenticated_user"}, "credentials": None,
    })
    with pytest.raises(ValueError, match="Connect a Postman API key"):
        await node.execute({})


@pytest.mark.asyncio
async def test_provider_errors_redact_key_and_binary_response_is_bounded():
    original_client = httpx.AsyncClient
    op = OPERATIONS["get_authenticated_user"]
    credential = PostmanApiKeyCredential(api_key="secret-key")

    def forbidden(_request):
        return httpx.Response(403, json={"error": {"message": "invalid secret-key"}})

    with patch("nodes.postman_node.httpx.AsyncClient", side_effect=lambda **kw: original_client(
            transport=httpx.MockTransport(forbidden), **kw)):
        with pytest.raises(ValueError, match="Postman API error 403: invalid \\[redacted\\]") as error:
            await PostmanNode._request(op, "/me", credential, {}, None)
    assert "secret-key" not in str(error.value)

    def binary(_request):
        return httpx.Response(200, content=b"abc", headers={"content-type": "application/octet-stream"})

    with patch("nodes.postman_node.httpx.AsyncClient", side_effect=lambda **kw: original_client(
            transport=httpx.MockTransport(binary), **kw)):
        data = await PostmanNode._request(op, "/me", credential, {}, None)
    assert isinstance(data, BinaryOutput)
    assert data.data == b"abc"
    assert data.content_type == "application/octet-stream"
    assert data.filename == "postman-response"

    with patch("nodes.postman_node._MAX_RESPONSE_BYTES", 2), patch(
        "nodes.postman_node.httpx.AsyncClient", side_effect=lambda **kw: original_client(
            transport=httpx.MockTransport(binary), **kw)
    ):
        with pytest.raises(ValueError, match="Postman response exceeds the 20 MB workflow limit"):
            await PostmanNode._request(op, "/me", credential, {}, None)


@pytest.mark.parametrize("content_type", ["application/octet-stream", ""])
@pytest.mark.asyncio
async def test_binary_response_resolves_to_a_usable_file_reference(content_type):
    original_client = httpx.AsyncClient

    def binary(_request):
        return httpx.Response(200, content=b"abc", headers={"content-type": content_type})

    with patch("nodes.postman_node.httpx.AsyncClient", side_effect=lambda **kw: original_client(
            transport=httpx.MockTransport(binary), **kw)):
        output = await node_for("get_authenticated_user").execute({})
    assert isinstance(output["data"], BinaryOutput)
    assert output["data"].data == b"abc"
    assert output["data"].content_type == "application/octet-stream"

    with patch("nodes.core.binary_output.create_resource_from_bytes", new_callable=AsyncMock) as store:
        store.return_value = {
            "download_url": "https://assets.test/postman-response",
            "mime_type": "application/octet-stream",
            "name": "postman-response",
            "size_bytes": 3,
        }
        resolved = await resolve_binary_outputs(output, user_id="user", workflow_id="workflow")
    store.assert_awaited_once_with(
        user_id="user", workflow_id="workflow", node_id=None, organization_id=None,
        body=b"abc", content_type="application/octet-stream", filename="postman-response",
    )
    assert resolved == {
        "status": "success", "operation": "get_authenticated_user",
        "data": {
            "url": "https://assets.test/postman-response",
            "mime_type": "application/octet-stream", "name": "postman-response", "size_bytes": 3,
        },
    }


def test_invalid_credential_region_rejected():
    with pytest.raises(ValueError):
        PostmanApiKeyCredential(api_key="secret-key", region="untrusted.example.com")


@pytest.mark.parametrize("operation", [
    "ap_is_get_apis", "ap_is_create_api", "ap_is_get_api",
    "ap_is_create_update_api_schema_file", "tags_get_api_tags",
    "tags_update_api_tags", "specs_get_migration_status",
    "specs_migrate_api_to_spec_hub", "collections_get_collections",
    "ap_is_get_api_comments",
])
@pytest.mark.asyncio
async def test_operation_specific_accept_header(operation):
    """API Builder v10 endpoints require their versioned media type on the wire."""
    original_client = httpx.AsyncClient
    seen = []

    def respond(request):
        seen.append(request)
        return httpx.Response(200, json={})

    fields = {
        parameter: "example-id"
        for parameter in re.findall(r"\{([^}]+)\}", OPERATIONS[operation].path)
    }
    with patch("nodes.postman_node.httpx.AsyncClient", side_effect=lambda **kw: original_client(
            transport=httpx.MockTransport(respond), **kw)):
        await node_for(operation, **fields).execute({})

    expected = (
        "application/json"
        if operation in {"collections_get_collections", "ap_is_get_api_comments"}
        else "application/vnd.api.v10+json"
    )
    assert seen[0].headers["Accept"] == expected
    assert seen[0].headers["x-api-key"] == "secret-key"


@pytest.mark.parametrize("operation", [
    "ap_is_create_update_api_schema_file", "ap_is_get_api_schema_file_contents",
    "ap_is_delete_api_schema_file",
])
@pytest.mark.asyncio
async def test_schema_file_path_is_one_encoded_parameter(operation):
    original_client = httpx.AsyncClient
    seen = []

    def respond(request):
        seen.append(request)
        return httpx.Response(200, json={})

    with patch("nodes.postman_node.httpx.AsyncClient", side_effect=lambda **kw: original_client(
            transport=httpx.MockTransport(respond), **kw)):
        await node_for(operation, apiId="api-id", schemaId="schema-id", **{
            "file-path": "postman/collection/c1.json",
        }).execute({})

    assert seen[0].url.raw_path == (
        b"/apis/api-id/schemas/schema-id/files/postman%2Fcollection%2Fc1.json"
    )
