"""Exercise native Power BI nodes with provider examples and an HTTP fake.

Tests assert routes, verbs, request bodies, response parsing and audience-safe
refresh behavior without using accounts or making live network requests.
"""
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import microsoft_power_bi_node as powerbi
from nodes.core.registry import NodeFactory
from nodes.scopes.microsoft_power_bi import CONNECT_SCOPES, RESOURCE_SCOPES
from utils import ssrf

GROUP = "f089354e-8366-4e18-aea3-4cb4a3a50b48"
DATASET = "cfafbeb1-8037-4d0c-896e-a46fb27ff229"
AUTH = {"credential_type": "microsoft_oauth", "access_token": "graph-fixture-token",
        "refresh_token": "refresh-fixture-token", "expires_at": "2099-01-01T00:00:00Z",
        "email": "fixture@example.test", "power_bi_access_token": "power-bi-fixture-token",
        "power_bi_expires_at": "2099-01-01T00:00:00Z"}
FIXTURE = json.loads((Path(__file__).parent / "fixtures/microsoft-power-bi/provider_examples.json").read_text())["examples"]


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))
    async def send(request):
        requests.append(request)
        assert request.url.host == "api.powerbi.com"
        assert request.headers["Authorization"] == "Bearer power-bi-fixture-token"
        assert "token" not in str(request.url)
        status, body, *headers = replies.pop(0)
        return httpx.Response(status, content=b"" if body is None else json.dumps(body).encode(),
                              headers={"Content-Type": "application/json", **(headers[0] if headers else {})})
    native = ssrf.guarded_async_client
    monkeypatch.setattr(powerbi, "guarded_async_client", lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)))
    return requests, replies


def node(operation, config=None, credential=None):
    return NodeFactory.create_node(node_id="power-bi-test", node_type="automation-microsoft-power-bi",
        node_data={"config": {"operation": operation, **(config or {})}, "credentials": deepcopy(credential or AUTH)})


CASES = [
    ("list_workspaces", {}, "GET", "/groups", {"value": []}, None),
    ("list_datasets", {"workspace_id": GROUP}, "GET", f"/groups/{GROUP}/datasets", {"value": []}, None),
    ("get_dataset", {"workspace_id": GROUP, "dataset_id": DATASET}, "GET", f"/groups/{GROUP}/datasets/{DATASET}", {"id": DATASET, "name": "SalesMarketing"}, None),
    ("create_push_dataset", {"workspace_id": GROUP, "name": "SalesMarketing", "tables": [{"name": "Product", "columns": [{"name": "ProductID", "dataType": "Int64"}]}]}, "POST", f"/groups/{GROUP}/datasets", {"id": DATASET, "name": "SalesMarketing"}, {"name": "SalesMarketing", "defaultMode": "Push", "tables": [{"name": "Product", "columns": [{"name": "ProductID", "dataType": "Int64"}]}]}),
    ("delete_dataset", {"workspace_id": GROUP, "dataset_id": DATASET}, "DELETE", f"/groups/{GROUP}/datasets/{DATASET}", None, None),
    ("list_tables", {"workspace_id": GROUP, "dataset_id": DATASET}, "GET", f"/groups/{GROUP}/datasets/{DATASET}/tables", {"value": []}, None),
    ("add_rows", {"workspace_id": GROUP, "dataset_id": DATASET, "table_name": "Product", "rows": [{"ProductID": 1, "Name": "Adjustable Race"}]}, "POST", f"/groups/{GROUP}/datasets/{DATASET}/tables/Product/rows", None, {"rows": [{"ProductID": 1, "Name": "Adjustable Race"}]}),
    ("delete_rows", {"workspace_id": GROUP, "dataset_id": DATASET, "table_name": "Product"}, "DELETE", f"/groups/{GROUP}/datasets/{DATASET}/tables/Product/rows", None, None),
    ("get_refresh_history", {"workspace_id": GROUP, "dataset_id": DATASET, "top": 3}, "GET", f"/groups/{GROUP}/datasets/{DATASET}/refreshes", {"value": []}, None),
    ("refresh_dataset", {"workspace_id": GROUP, "dataset_id": DATASET}, "POST", f"/groups/{GROUP}/datasets/{DATASET}/refreshes", None, {"notifyOption": "NoNotification"}),
    ("execute_query", {"workspace_id": GROUP, "dataset_id": DATASET, "query": "EVALUATE VALUES(MyTable)", "include_nulls": True}, "POST", f"/groups/{GROUP}/datasets/{DATASET}/executeQueries", FIXTURE["Datasets_ExecuteQueriesInGroup"]["Execute queries example"]["responses"]["200"]["body"], {"queries": [{"query": "EVALUATE VALUES(MyTable)"}], "serializerSettings": {"includeNulls": True}}),
    ("list_reports", {"workspace_id": GROUP}, "GET", f"/groups/{GROUP}/reports", {"value": []}, None),
    ("get_report", {"workspace_id": GROUP, "report_id": DATASET}, "GET", f"/groups/{GROUP}/reports/{DATASET}", {"id": DATASET, "name": "Sales"}, None),
    ("delete_report", {"workspace_id": GROUP, "report_id": DATASET}, "DELETE", f"/groups/{GROUP}/reports/{DATASET}", None, None),
    ("clone_report", {"workspace_id": GROUP, "report_id": DATASET, "name": "New Report Name", "target_workspace_id": "2f42a406-a075-4a15-bbf2-97ef958c94cb", "target_dataset_id": "8e4d5880-81d6-4804-ab97-054665050799"}, "POST", f"/groups/{GROUP}/reports/{DATASET}/Clone", {}, {"name": "New Report Name", "targetWorkspaceId": "2f42a406-a075-4a15-bbf2-97ef958c94cb", "targetModelId": "8e4d5880-81d6-4804-ab97-054665050799"}),
    ("rebind_report", {"workspace_id": GROUP, "report_id": DATASET, "target_dataset_id": DATASET}, "POST", f"/groups/{GROUP}/reports/{DATASET}/Rebind", None, {"datasetId": DATASET}),
    ("list_report_pages", {"workspace_id": GROUP, "report_id": DATASET}, "GET", f"/groups/{GROUP}/reports/{DATASET}/pages", {"value": []}, None),
    ("list_dashboards", {"workspace_id": GROUP}, "GET", f"/groups/{GROUP}/dashboards", {"value": []}, None),
    ("create_dashboard", {"workspace_id": GROUP, "name": "Sales"}, "POST", f"/groups/{GROUP}/dashboards", {"id": DATASET, "displayName": "Sales"}, {"name": "Sales"}),
    ("list_tiles", {"workspace_id": GROUP, "dashboard_id": DATASET}, "GET", f"/groups/{GROUP}/dashboards/{DATASET}/tiles", {"value": []}, None),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,method,path,response,body", CASES)
async def test_every_operation_exact_request_and_parser(transport, operation, config, method, path, response, body):
    requests, replies = transport
    replies.append((202 if operation == "refresh_dataset" else 201 if operation == "create_push_dataset" else 200, response))
    result = await node(operation, config).execute({})
    assert len(requests) == 1 and replies == []
    request = requests[0]
    assert (request.method, request.url.path) == (method, "/v1.0/myorg" + path)
    assert (json.loads(request.content) if request.content else None) == body
    assert result["status"] == "success" and result["operation"] == operation
    if response is not None:
        assert result["data"] == response
    if operation == "refresh_dataset":
        assert result["refresh_requested"] is True and result["refresh_completed"] is False
    if operation == "get_refresh_history":
        assert dict(request.url.params) == {"$top": "3"}


@pytest.mark.asyncio
async def test_workspace_pagination_and_connection_evidence(transport):
    requests, replies = transport
    # The publisher's documented list is the account-specific proof.
    response = FIXTURE["Groups_GetGroups"]["Example"]["responses"]["200"]
    replies.append((200, response))
    result = await node("list_workspaces", {"top": 3, "skip": 6, "filter": "contains(name,'marketing')"}).execute({})
    assert result["items"] == response["value"] and result["count"] == 3
    assert result["next_skip"] == 9
    assert dict(requests[0].url.params) == {"$top": "3", "$skip": "6", "$filter": "contains(name,'marketing')"}
    evidence = powerbi.MicrosoftPowerBINode.connection_evidence
    assert evidence.operation == "list_workspaces" and evidence.proves != "reachability"


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    {"error": {"code": "InvalidRequest", "message": "invalid DAX"}},
    {"results": [{"error": {"message": "Dataset permission denied"}}]},
    {"results": [{"tables": [{"error": {"message": "More than 100000 rows"}}]}]},
])
async def test_query_error_inside_http_200_is_not_success(transport, payload):
    transport[1].append((200, payload))
    with pytest.raises(ValueError, match="Power BI"):
        await node("execute_query", {"workspace_id": GROUP, "dataset_id": DATASET, "query": "EVALUATE VALUES(MyTable)"}).execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 400, 401, 403, 404, 429, 500])
async def test_provider_rejections_are_preserved_without_retry(transport, status):
    transport[1].append((status, {"error": {"message": "PowerBINotAuthorizedException"}}))
    with pytest.raises(ValueError, match=f"{status}.*PowerBINotAuthorizedException"):
        await node("list_workspaces").execute({})
    assert len(transport[0]) == 1


@pytest.mark.parametrize("bad", ["..", "https://foreign.test", "a/b", "a%2Fb", "x?y", "x\ny"])
def test_reject_path_injection(bad):
    with pytest.raises(ValueError):
        node("get_dataset", {"workspace_id": bad, "dataset_id": DATASET})


@pytest.mark.asyncio
@pytest.mark.parametrize("expired", [False, True])
async def test_power_bi_grant_keeps_graph_identity_and_uses_shared_refresh(monkeypatch, expired):
    auth = {**AUTH, "power_bi_access_token": "old-power-bi-token" if expired else None,
            "power_bi_expires_at": "2000-01-01T00:00:00Z" if expired else None}
    from nodes.oauth import microsoft_oauth
    refresh = AsyncMock(return_value=SimpleNamespace(access_token="new-power-bi-token", refresh_token="rotated-refresh-token",
                          expires_at="2099-02-01T00:00:00Z", scope=RESOURCE_SCOPES, token_type="Bearer"))
    monkeypatch.setattr(microsoft_oauth, "refresh_access_token", refresh)
    n = node("list_workspaces", credential=auth)
    assert await n._token() == "new-power-bi-token"
    refresh.assert_awaited_once_with("refresh-fixture-token", scope=RESOURCE_SCOPES)
    assert n.config.credentials.access_token == "graph-fixture-token"
    assert n.config.credentials.expires_at == "2099-01-01T00:00:00Z"
    assert n.config.credentials.refresh_token == "rotated-refresh-token"
    assert n.config.credentials.power_bi_expires_at == "2099-02-01T00:00:00Z"
    assert CONNECT_SCOPES[0] == "https://graph.microsoft.com/User.Read"
    assert all(s in CONNECT_SCOPES for s in RESOURCE_SCOPES.split())


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [None, {}, {"value": "unexpected"}, []])
async def test_incomplete_workspace_response_cannot_prove_connection(transport, body):
    transport[1].append((200, body))
    with pytest.raises(ValueError, match="Power BI"):
        await node("list_workspaces").execute({})


def test_scopes_satisfy_each_provider_operation_permission_contract():
    contract = json.loads((Path(__file__).parent / "fixtures/microsoft-power-bi/permission_contract.json").read_text())["operations"]
    assert {spec.operation_id for spec in powerbi.OPERATIONS.values()} == set(contract)
    for operation, spec in powerbi.OPERATIONS.items():
        alternatives = contract[spec.operation_id]["alternatives"]
        # Get Tables' pinned Swagger has an empty Required Scope section;
        # the other 19 provide literal scope alternatives.
        if not alternatives:
            assert spec.operation_id == "Datasets_GetTablesInGroup"
            continue
        declared = powerbi.POWER_BI_SCOPES.require(operation).scopes
        assert len(declared) == 1
        assert declared[0].rsplit("/", 1)[-1] in alternatives, operation
