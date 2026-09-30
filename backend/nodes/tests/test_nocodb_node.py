"""NocoDB v3 request contracts and credential safety."""

import json

import httpx
import pytest

from nodes.nocodb_node import (
    NocoDBNode,
    NocoDBNodeConfig,
    NocoDBTokenCredential,
    OPERATIONS,
)


IDS = {
    "workspace_id": "w 1",
    "base_id": "b 2",
    "table_id": "t 3",
    "record_id": "r/4",
    "field_id": "f 5",
    "view_id": "v 6",
    "hook_id": "h 7",
    "comment_id": "c 8",
    "link_field_id": "l 9",
}


def node_for(operation, **overrides):
    spec = OPERATIONS[operation]
    config = {
        "operation": operation,
        **{name: IDS[name] for name in spec.fields.split()},
    }
    if spec.body:
        config[spec.body] = json.dumps(
            {"fields": {"Title": "test"}}
            if spec.body == "records"
            else {"title": "test"}
        )
    config.update(overrides)
    parsed = NocoDBNodeConfig.model_validate(
        {
            "config": config,
            "credentials": {"api_token": "secret-test-token"},
        }
    )
    return NocoDBNode("test", "automation-nocodb", {}, config=parsed)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", list(OPERATIONS))
async def test_each_operation_uses_documented_method_path_and_token(
    operation, monkeypatch
):
    requests = []

    async def send(self, method, url, **kwargs):
        requests.append((method, url, kwargs))
        return httpx.Response(
            200, json={"id": "owned-resource"}, request=httpx.Request(method, url)
        )

    monkeypatch.setattr(httpx.AsyncClient, "request", send)
    result = await node_for(operation).execute({})
    method, url, options = requests[0]
    assert result["status"] == "success"
    assert result["data"]["id"] == "owned-resource"
    assert method == OPERATIONS[operation].method
    assert url.startswith("https://app.nocodb.com/api/v3/")
    assert "{" not in url and "}" not in url
    assert options["headers"] == {"xc-token": "secret-test-token"}
    if OPERATIONS[operation].body:
        assert isinstance(options["json"], dict)


@pytest.mark.asyncio
async def test_record_payload_query_and_error_are_preserved(monkeypatch):
    captured = []

    async def send(self, method, url, **kwargs):
        captured.append(kwargs)
        return httpx.Response(
            403, json={"msg": "Permission denied"}, request=httpx.Request(method, url)
        )

    monkeypatch.setattr(httpx.AsyncClient, "request", send)
    result = await node_for(
        "list_records", page_size=25, page=2, where="(Title,eq,test)"
    ).execute({})
    assert captured[0]["params"] == {
        "where": "(Title,eq,test)",
        "page": 2,
        "pageSize": 25,
    }
    assert result["status"] == "error"
    assert result["status_code"] == 403
    assert result["error"] == "Permission denied"
    assert result["timing_ms"]["api_request"] >= 0


def test_invalid_json_and_origin_rejected():
    with pytest.raises(ValueError, match="HTTPS origin"):
        NocoDBTokenCredential(api_token="x", base_url="http://localhost:8080")
    with pytest.raises(ValueError, match="HTTPS origin"):
        NocoDBTokenCredential(api_token="x", base_url="https://app.nocodb.com/api/v3")
    node = node_for("create_records", records="not-json")
    with pytest.raises(ValueError, match="valid JSON"):
        import asyncio

        asyncio.run(node.execute({}))


@pytest.mark.asyncio
async def test_owned_workspace_options_are_connection_evidence(monkeypatch):
    async def get(self, url, **kwargs):
        assert kwargs["headers"] == {"xc-token": "secret-test-token"}
        return httpx.Response(
            200,
            json={"list": [{"id": "w123", "title": "My Workspace"}]},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", get)
    options = await NocoDBNode.load_field_options(
        "workspace_id", {"api_token": "secret-test-token"}
    )
    assert options == [{"value": "w123", "label": "My Workspace"}]
    assert NocoDBNode.connection_evidence.noun == "workspaces"


@pytest.mark.asyncio
async def test_field_and_record_pickers_use_selected_table(monkeypatch):
    async def get(self, url, **kwargs):
        if url.endswith("/records?pageSize=100"):
            body = {"records": [{"id": 7, "fields": {"Title": "Customer A"}}]}
        else:
            body = {"fields": [{"id": "fld1", "title": "Email"}]}
        return httpx.Response(200, json=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", get)
    credentials = {"api_token": "secret-test-token"}
    context = {"base_id": "base", "table_id": "table"}
    assert await NocoDBNode.load_field_options("field_id", credentials, context) == [
        {"value": "fld1", "label": "Email"}
    ]
    assert await NocoDBNode.load_field_options("record_id", credentials, context) == [
        {"value": "7", "label": "Customer A"}
    ]
