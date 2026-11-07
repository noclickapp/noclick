"""Coda API token, operation, picker and request contracts."""

import json
from unittest.mock import Mock

import httpx
import pytest
import respx

from nodes.coda_node import CONFIG_MODELS, OPERATIONS, CodaAPITokenCredential, CodaNode, CodaNodeConfig


def node(operation: str, **values) -> CodaNode:
    return CodaNode(
        node_id="coda-test", node_type="automation-coda", node_data={},
        config=CodaNodeConfig(
            config=CONFIG_MODELS[operation](**values),
            credentials=CodaAPITokenCredential(api_token="coda-token"),
        ),
        sio=Mock(), sid="sid", workflow_id="workflow", user_id="user",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,values,method,path,body", [
    ("get_current_user", {}, "GET", "/whoami", None),
    ("list_docs", {"query": "Roadmap", "limit": 25}, "GET", "/docs", None),
    ("get_doc", {"doc_id": "AbC"}, "GET", "/docs/AbC", None),
    ("create_doc", {"title": "Roadmap"}, "POST", "/docs", {"title": "Roadmap"}),
    ("publish_doc", {"doc_id": "AbC", "slug": "roadmap", "discoverable": False,
                     "category_names_json": '["Planning"]'},
     "PUT", "/docs/AbC/publish", {"slug": "roadmap", "discoverable": False,
                                     "categoryNames": ["Planning"]}),
    ("create_page", {"doc_id": "AbC", "name": "Plan"}, "POST", "/docs/AbC/pages", {"name": "Plan"}),
    ("begin_page_export", {"doc_id": "AbC", "page_id": "p-1", "output_format": "markdown"},
     "POST", "/docs/AbC/pages/p-1/export", {"outputFormat": "markdown"}),
    ("delete_page_content", {"doc_id": "AbC", "page_id": "p-1", "element_ids_json": '["cl-1"]'},
     "DELETE", "/docs/AbC/pages/p-1/content", {"elementIds": ["cl-1"]}),
    ("list_rows", {"doc_id": "AbC", "table_id": "grid-1", "value_format": "simple"},
     "GET", "/docs/AbC/tables/grid-1/rows", None),
    ("upsert_rows", {"doc_id": "AbC", "table_id": "grid-1",
                     "rows_json": '[{"cells":[{"column":"c-1","value":"Done"}]}]',
                     "key_columns_json": '["c-1"]'},
     "POST", "/docs/AbC/tables/grid-1/rows",
     {"rows": [{"cells": [{"column": "c-1", "value": "Done"}]}], "keyColumns": ["c-1"]}),
    ("update_row", {"doc_id": "AbC", "table_id": "grid-1", "row_id": "i-1",
                    "row_json": '{"cells":[{"column":"c-1","value":"Done"}]}'},
     "PUT", "/docs/AbC/tables/grid-1/rows/i-1",
     {"row": {"cells": [{"column": "c-1", "value": "Done"}]}}),
    ("delete_rows", {"doc_id": "AbC", "table_id": "grid-1", "row_ids_json": '["i-1","i-2"]'},
     "DELETE", "/docs/AbC/tables/grid-1/rows", {"rowIds": ["i-1", "i-2"]}),
    ("add_permission", {"doc_id": "AbC", "access": "readonly",
                        "principal_json": '{"type":"email","email":"a@example.com"}',
                        "suppress_email": True},
     "POST", "/docs/AbC/acl/permissions",
     {"access": "readonly", "principal": {"type": "email", "email": "a@example.com"},
      "suppressEmail": True}),
    ("update_sharing_settings", {"doc_id": "AbC", "allow_copying": False},
     "PATCH", "/docs/AbC/acl/settings", {"allowCopying": False}),
    ("trigger_automation", {"doc_id": "AbC", "rule_id": "rule-1",
                            "payload_json": '{"message":"Ready"}'},
     "POST", "/docs/AbC/hooks/automation/rule-1", {"message": "Ready"}),
    ("resolve_browser_link", {"url": "https://coda.io/d/_dAbC/Tasks_suA"},
     "GET", "/resolveBrowserLink", None),
])
async def test_request_shape(operation, values, method, path, body):
    with respx.mock(assert_all_called=True) as router:
        route = router.request(method, "https://docs.superhuman.com/apis/v1" + path).mock(
            return_value=httpx.Response(202 if operation in {"upsert_rows", "update_row", "delete_rows"} else 200,
                                        json={"requestId": "req-1"} if operation in {"upsert_rows", "update_row", "delete_rows"}
                                        else {"id": "result"}))
        result = await node(operation, **values).execute({})
    request = route.calls[0].request
    assert request.headers["Authorization"] == "Bearer coda-token"
    if body is not None:
        assert json.loads(request.content) == body
    if operation == "list_docs":
        assert request.url.params["query"] == "Roadmap"
        assert request.url.params["limit"] == "25"
    if operation == "resolve_browser_link":
        assert request.url.params["url"] == "https://coda.io/d/_dAbC/Tasks_suA"
    assert result["status"] == "success"
    if operation in {"upsert_rows", "update_row", "delete_rows"}:
        assert result["data"]["requestId"] == "req-1"
    else:
        assert result["data"]["id"] == "result"


@pytest.mark.asyncio
async def test_dynamic_doc_and_table_pickers():
    with respx.mock(assert_all_called=True) as router:
        docs = router.get("https://docs.superhuman.com/apis/v1/docs").mock(
            return_value=httpx.Response(200, json={"items": [{"id": "AbC", "name": "Roadmap"}],
                                                     "nextPageToken": "next"}))
        tables = router.get("https://docs.superhuman.com/apis/v1/docs/AbC/tables").mock(
            return_value=httpx.Response(200, json={"items": [{"id": "grid-1", "name": "Tasks"}]}))
        doc_result = await CodaNode.load_field_options("doc_id", {"api_token": "coda-token"}, search="Roadmap")
        table_result = await CodaNode.load_field_options(
            "table_id", {"api_token": "coda-token"}, context={"config": {"doc_id": "AbC"}})
    assert docs.calls[0].request.url.params["query"] == "Roadmap"
    assert doc_result == {"options": [{"value": "AbC", "label": "Roadmap"}], "next_page_token": "next"}
    assert tables.calls[0].request.url.params["limit"] == "100"
    assert table_result["options"] == [{"value": "grid-1", "label": "Tasks"}]


@pytest.mark.asyncio
async def test_api_errors_and_bad_json_are_visible():
    with respx.mock:
        respx.get("https://docs.superhuman.com/apis/v1/whoami").mock(
            return_value=httpx.Response(401, json={"message": "Invalid API token"}))
        with pytest.raises(ValueError, match="Coda API error 401: Invalid API token"):
            await node("get_current_user").execute({})
    with pytest.raises(ValueError, match="rows_json must contain valid JSON"):
        await node("upsert_rows", doc_id="AbC", table_id="grid-1", rows_json="{").execute({})
    with pytest.raises(ValueError, match="Rows JSON must be an array"):
        await node("upsert_rows", doc_id="AbC", table_id="grid-1", rows_json="{}").execute({})


def test_all_operations_in_schema_and_credential_is_secret():
    schema = CodaNode.get_config_schema()
    assert len(OPERATIONS) == 48
    for model in CONFIG_MODELS.values():
        assert model.__name__ in schema["$defs"]
    assert schema["$defs"]["CodaAPITokenCredential"]["properties"]["api_token"]["ui:widget"] == "password"
