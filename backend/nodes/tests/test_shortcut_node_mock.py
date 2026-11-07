"""Contract and transport coverage for all Shortcut REST v3 canvas actions."""

import json
from pathlib import Path
from urllib.parse import quote

import httpx
import pytest

from nodes.shortcut_node import (
    OPERATION_MODELS,
    ShortcutApiTokenCredential,
    ShortcutNode,
    ShortcutNodeConfig,
)
from nodes.shortcut_node import OPERATIONS
from tests.utils.sweep import check_each


def make_node(action: str, **fields) -> ShortcutNode:
    operation = OPERATION_MODELS[action](**fields)
    config = ShortcutNodeConfig(
        config=operation,
        credentials=ShortcutApiTokenCredential(api_token="secret-test-token"),
    )
    return ShortcutNode("test", "automation-shortcut", {}, config=config)


def _required_fields(contract):
    fields = {}
    for parameter in contract["parameters"]:
        if not parameter["required"]:
            continue
        name = f"{parameter['location']}_{parameter['name'].replace('-', '_')}"
        fields[name] = 123 if parameter["type"] == "integer" else "test"
    if contract["body_type"] == "json":
        scalar_names = {field["name"] for field in contract["body_fields"]}
        for field in contract["body_fields"]:
            if field["required"]:
                fields[f"body_{field['name']}"] = {
                    "integer": 123,
                    "number": 1.5,
                    "boolean": True,
                }.get(field["type"], "test")
        fields["body_json"] = json.dumps(
            {name: [] for name in contract["body_required"] if name not in scalar_names}
        )
    elif contract["body_type"] == "multipart":
        fields["file_base64"] = "aGVsbG8="
    return fields


async def _every_published_operation_uses_its_documented_route(action, monkeypatch):
    """Each of the 143 actions must dispatch to its pinned method and safe path."""
    contract = OPERATIONS[action]
    fields = _required_fields(contract)
    if action == "create_story":
        fields["body_workflow_state_id"] = 500000006
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        "nodes.shortcut_node.httpx.AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    result = await make_node(action, **fields).execute({})
    assert result["status"] == "success"
    assert result["action"] == action
    assert result["data"] == {"ok": True}
    assert result["timing_ms"]["api_request"] >= 0
    assert len(seen) == 1
    request = seen[0]
    assert request.method == contract["method"]
    expected_path = contract["path"]
    for parameter in contract["parameters"]:
        if parameter["location"] == "path":
            key = f"path_{parameter['name'].replace('-', '_')}"
            expected_path = expected_path.replace(
                "{" + parameter["name"] + "}", quote(str(fields[key]), safe="")
            )
    assert request.url.path == "/api/v3" + expected_path
    assert request.headers["Shortcut-Token"] == "secret-test-token"


@pytest.mark.asyncio
async def test_every_published_operation_uses_its_documented_route():
    async def one(action):
        # Each case patches what it needs afresh, undone before the next, as its own test once did.
        with pytest.MonkeyPatch.context() as monkeypatch:
            await _every_published_operation_uses_its_documented_route(action, monkeypatch)

    await check_each(sorted(OPERATIONS), one)


@pytest.mark.asyncio
async def test_create_story_merges_fields_and_json_body(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(201, json={"id": 42, "name": "From canvas"})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        "nodes.shortcut_node.httpx.AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    result = await make_node(
        "create_story",
        body_name="From canvas",
        body_workflow_state_id=500000006,
        body_description="Customer issue",
        body_json='{"name":"Old name","owner_ids":["member-1"]}',
    ).execute({})
    assert result["status"] == "success"
    assert result["status_code"] == 201
    assert json.loads(seen[0].content) == {
        "name": "From canvas",
        "workflow_state_id": 500000006,
        "description": "Customer issue",
        "owner_ids": ["member-1"],
    }


@pytest.mark.asyncio
async def test_search_stories_query_and_error(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(429, text="Rate limit exceeded")

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        "nodes.shortcut_node.httpx.AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    result = await make_node(
        "search_stories",
        query_query="customer",
        query_page_size=20,
        query_entity_types="story, epic",
    ).execute({})
    assert result["status"] == "error"
    assert result["status_code"] == 429
    assert seen[0].url.params["query"] == "customer"
    assert seen[0].url.params["page_size"] == "20"
    assert seen[0].url.params.get_list("entity_types") == ["story", "epic"]


@pytest.mark.asyncio
async def test_rejects_invalid_body_before_network():
    with pytest.raises(ValueError, match="valid JSON"):
        await make_node("create_multiple_stories", body_json="{").execute({})
    with pytest.raises(ValueError, match="missing: stories"):
        await make_node("create_multiple_stories").execute({})
    with pytest.raises(ValueError, match="Project ID or Workflow State ID"):
        await make_node("create_story", body_name="Needs a workflow").execute({})


@pytest.mark.asyncio
async def test_upload_files_is_multipart_and_bounded(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=[{"id": 5}])

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        "nodes.shortcut_node.httpx.AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    result = await make_node(
        "upload_files",
        file_base64="aGVsbG8=",
        filename="hello.txt",
        body_story_id=42,
    ).execute({})
    assert result["data"] == {"items": [{"id": 5}]}
    assert "multipart/form-data" in seen[0].headers["content-type"]
    assert b'name="file0"' in seen[0].content
    assert b'name="story_id"\r\n\r\n42' in seen[0].content
    assert b"hello.txt" in seen[0].content
    assert b"hello" in seen[0].content
    with pytest.raises(ValueError, match="valid Base64"):
        await make_node("upload_files", file_base64="not base64!").execute({})


def test_schema_and_auth_are_available_to_flow_canvas():
    schema = ShortcutNode.get_config_schema()
    assert len(OPERATION_MODELS) == len(OPERATIONS) == 143
    assert len(schema["$defs"]) == 144  # 143 actions and the token credential
    credential = schema["$defs"]["ShortcutApiTokenCredential"]
    assert credential["x-credential-url"].endswith("/api-tokens")
    assert credential["properties"]["api_token"]["ui:widget"] == "password"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("action", "method", "status_code"),
    [
        ("create_story_reaction", "POST", 201),
        ("delete_story_reaction", "DELETE", 204),
    ],
)
async def test_story_reactions_send_required_emoji_body(
    action, method, status_code, monkeypatch
):
    """Use Shortcut's documented reaction request and create-response examples.

    https://developer.shortcut.com/api/rest/v3#Create-Story-Reaction
    https://developer.shortcut.com/api/rest/v3#Delete-Story-Reaction
    """
    seen = []

    def handler(request):
        seen.append(request)
        if status_code == 204:
            return httpx.Response(204)
        return httpx.Response(
            201,
            json=[
                {
                    "emoji": "foo",
                    "permission_ids": ["12345678-9012-3456-7890-123456789012"],
                }
            ],
        )

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        "nodes.shortcut_node.httpx.AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    result = await make_node(
        action,
        path_story_public_id=123,
        path_comment_public_id=123,
        body_emoji="foo",
    ).execute({})
    assert result["status"] == "success"
    assert result["status_code"] == status_code
    assert len(seen) == 1
    assert seen[0].method == method
    assert seen[0].url.path == "/api/v3/stories/123/comments/123/reactions"
    assert json.loads(seen[0].content) == {"emoji": "foo"}
    assert result["data"] == (
        {}
        if status_code == 204
        else {
            "items": [
                {
                    "emoji": "foo",
                    "permission_ids": ["12345678-9012-3456-7890-123456789012"],
                }
            ]
        }
    )


@pytest.mark.parametrize("action", ["create_story_reaction", "delete_story_reaction"])
def test_story_reactions_require_emoji(action):
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="body_emoji"):
        make_node(action, path_story_public_id=123, path_comment_public_id=123)


DOCUMENTED_RESPONSES = json.loads(
    (Path(__file__).parent / "fixtures/shortcut/documented_responses.json").read_text()
)


@pytest.mark.asyncio
@pytest.mark.parametrize("route", sorted(DOCUMENTED_RESPONSES))
async def test_parses_exact_provider_documented_responses(route, monkeypatch):
    """Keep the API parser compatible with exact examples, including spec defects."""
    method, path = route.split(" ", 1)
    action, contract = next(
        (action, contract)
        for action, contract in OPERATIONS.items()
        if contract["method"] == method and "/api/v3" + contract["path"] == path
    )
    payload = DOCUMENTED_RESPONSES[route]["body"]
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        "nodes.shortcut_node.httpx.AsyncClient",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)),
            **kwargs,
        ),
    )
    result = await make_node(action, **_required_fields(contract)).execute({})
    assert result["status"] == "success"
    assert result["data"] == (
        {"items": payload} if isinstance(payload, list) else payload
    )
