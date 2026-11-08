"""Synthetic MaintainX wire contracts; no live account or credentials."""
import json

import httpx
import pytest
from pydantic import ValidationError

from nodes import maintainx_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-maintainx-token-42"
AUTH = {"credential_type": "maintainx_api_key", "api_key": TOKEN, "organization_id": 15}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credential=AUTH):
    return NodeFactory.create_node(
        node_id="maintainx-test",
        node_type="automation-maintainx",
        node_data={"config": config, "credentials": credential},
    )


def transport(monkeypatch, response):
    requests = []

    def handler(request):
        requests.append(request)
        return response

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


CASES = [
    (
        {"operation": "list_organizations"},
        "GET",
        "/organizations",
        {"limit": "100"},
        None,
        "organizations",
    ),
    (
        {
            "operation": "list_work_orders",
            "statuses": ["OPEN", "ON_HOLD"],
            "assets": [1, 2],
            "cursor": "opaque",
            "limit": 25,
        },
        "GET",
        "/workorders",
        {
            "limit": "25",
            "cursor": "opaque",
            "statuses": ["OPEN", "ON_HOLD"],
            "assets": ["1", "2"],
        },
        None,
        "workOrders",
    ),
    (
        {"operation": "get_work_order", "work_order_id": 159},
        "GET",
        "/workorders/159",
        {},
        None,
        "workOrder",
    ),
    (
        {
            "operation": "create_work_order",
            "title": "Inspect forklift",
            "asset_id": 843,
            "assignees": [{"type": "USER", "id": "user@example.com"}],
            "priority": "HIGH",
            "due_date": "2022-01-01T00:00:00Z",
        },
        "POST",
        "/workorders",
        {},
        {
            "title": "Inspect forklift",
            "assetId": 843,
            "assignees": [{"type": "USER", "id": "user@example.com"}],
            "priority": "HIGH",
            "dueDate": "2022-01-01T00:00:00Z",
        },
        "id",
    ),
    (
        {
            "operation": "update_work_order",
            "work_order_id": 159,
            "title": "Inspect forklift",
            "estimated_time": 3600,
        },
        "PATCH",
        "/workorders/159",
        {},
        {"title": "Inspect forklift", "estimatedTime": 3600},
        "workOrder",
    ),
    (
        {
            "operation": "update_work_order_status",
            "work_order_id": 159,
            "status": "DONE",
        },
        "PATCH",
        "/workorders/159/status",
        {},
        {"status": "DONE"},
        "workOrder",
    ),
    (
        {
            "operation": "create_work_order_comment",
            "work_order_id": 159,
            "content": "Inspection complete",
        },
        "POST",
        "/workorders/159/comments",
        {},
        {"content": "Inspection complete"},
        "id",
    ),
    (
        {"operation": "list_work_order_comments", "work_order_id": 159},
        "GET",
        "/workorders/159/comments",
        {"limit": "100"},
        None,
        "comments",
    ),
    ({"operation": "list_assets"}, "GET", "/assets", {"limit": "100"}, None, "assets"),
    (
        {"operation": "get_asset", "asset_id": 843},
        "GET",
        "/assets/843",
        {},
        None,
        "asset",
    ),
    (
        {"operation": "create_asset", "name": "Forklift"},
        "POST",
        "/assets",
        {},
        {"name": "Forklift"},
        "id",
    ),
    (
        {
            "operation": "update_asset",
            "asset_id": 843,
            "name": "Updated",
            "description": "Inspected",
        },
        "PATCH",
        "/assets/843",
        {},
        {"name": "Updated", "description": "Inspected"},
        "asset",
    ),
    (
        {"operation": "list_locations"},
        "GET",
        "/locations",
        {"limit": "100"},
        None,
        "locations",
    ),
    (
        {"operation": "get_location", "location_id": 843},
        "GET",
        "/locations/843",
        {},
        None,
        "location",
    ),
    (
        {"operation": "create_location", "name": "Forklift"},
        "POST",
        "/locations",
        {},
        {"name": "Forklift"},
        "id",
    ),
    (
        {
            "operation": "update_location",
            "location_id": 843,
            "name": "Updated",
            "description": "Inspected",
        },
        "PATCH",
        "/locations/843",
        {},
        {"name": "Updated", "description": "Inspected"},
        "location",
    ),
    ({"operation": "list_parts"}, "GET", "/parts", {"limit": "100"}, None, "parts"),
    ({"operation": "get_part", "part_id": 843}, "GET", "/parts/843", {}, None, "part"),
    (
        {"operation": "create_part", "name": "Forklift"},
        "POST",
        "/parts",
        {},
        {"name": "Forklift"},
        "id",
    ),
    (
        {
            "operation": "update_part",
            "part_id": 843,
            "name": "Updated",
            "description": "Inspected",
        },
        "PATCH",
        "/parts/843",
        {},
        {"name": "Updated", "description": "Inspected"},
        "part",
    ),
    (
        {"operation": "list_work_requests", "title": "Forklift"},
        "GET",
        "/workrequests",
        {"title": "Forklift", "limit": "100"},
        None,
        "workRequests",
    ),
    (
        {"operation": "get_work_request", "work_request_id": 963},
        "GET",
        "/workrequests/963",
        {},
        None,
        "workRequest",
    ),
    (
        {
            "operation": "create_work_request",
            "title": "Forklift",
            "approver_team_id": 254,
        },
        "POST",
        "/workrequests",
        {},
        {"title": "Forklift", "approverTeamId": 254},
        "id",
    ),
    ({"operation": "list_users"}, "GET", "/users", {"limit": "100"}, None, "users"),
    ({"operation": "list_teams"}, "GET", "/teams", {"limit": "100"}, None, "teams"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "config,method,path,query,body,key", CASES, ids=[c[0]["operation"] for c in CASES]
)
async def test_maintainx_wire_contract(
    monkeypatch, config, method, path, query, body, key
):
    listing = config["operation"].startswith("list_")
    payload = (
        {
            key: [{"id": 42, "name": "Factory"}],
            "nextCursor": "next-opaque",
            "nextPageUrl": "https://untrusted.test/never-follow",
        }
        if listing
        else {key: 42 if key == "id" else {"id": 42, "name": "Factory"}}
    )
    requests = transport(
        monkeypatch, httpx.Response(201 if method == "POST" else 200, json=payload)
    )
    result = await node(config).execute({})
    assert result["status"] == "success" and result["data"] == payload
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert str(request.url.copy_with(query=None)) == native.BASE_URL + path
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    actual = {
        k: request.url.params.get_list(k)
        if isinstance(v, list)
        else request.url.params[k]
        for k, v in query.items()
    }
    assert actual == query and set(request.url.params) == set(query)
    assert (json.loads(request.content) if request.content else None) == body
    scoped = len(path.strip("/").split("/")) == 1 and path != "/organizations"
    assert request.headers.get("x-organization-id") == ("15" if scoped else None)
    if listing:
        assert result["next_cursor"] == "next-opaque" and result["has_more"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [401, 403, 422, 429, 500, 302])
async def test_maintainx_errors_redact_tokens_and_never_retry_writes(monkeypatch, code):
    requests = transport(monkeypatch, httpx.Response(code, text="Rejected " + TOKEN))
    with pytest.raises(ValueError) as error:
        await node({"operation": "create_asset", "name": "Forklift"}).execute({})
    assert TOKEN not in str(error.value) and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="<html>Sign in</html>"),
        httpx.Response(200, json=[]),
        httpx.Response(200, json={}),
        httpx.Response(200, json={"organizations": [], "nextCursor": 17}),
        httpx.Response(
            200, json={"organizations": [], "nextCursor": None, "error": "invalid key"}
        ),
    ],
)
async def test_maintainx_bad_responses_cannot_prove_connection(monkeypatch, response):
    transport(monkeypatch, response)
    with pytest.raises(ValueError):
        await node({"operation": "list_organizations"}).execute({})


@pytest.mark.asyncio
async def test_maintainx_terminal_page_and_connection_evidence(monkeypatch):
    transport(
        monkeypatch,
        httpx.Response(
            200,
            json={
                "organizations": [{"id": 15, "name": "My Organization"}],
                "nextCursor": None,
                "nextPageUrl": None,
            },
        ),
    )
    from nodes.core.connection_evidence import collect_evidence

    result = await collect_evidence(
        node_type="automation-maintainx",
        credential_data=AUTH,
        user_id="00000000-0000-0000-0000-000000000001",
    )
    assert result.reachable is True
    assert any("My Organization" in str(sample) for sample in result.samples)


@pytest.mark.parametrize(
    "value", ["Bearer token", "https://example.com/token", "bad\r\nheader"]
)
def test_maintainx_refuses_pasted_headers_urls_and_controls(value):
    with pytest.raises(ValidationError):
        native.MaintainxApiKey(api_key=value)


@pytest.mark.parametrize("value", ["../users", "1/other", "1?x=1", 0, -1])
def test_maintainx_ids_cannot_change_routes(value):
    with pytest.raises(ValidationError):
        native.GetAsset(asset_id=value)


@pytest.mark.asyncio
async def test_maintainx_rejects_start_date_without_due_date_before_transport(
    monkeypatch,
):
    requests = transport(monkeypatch, httpx.Response(200, json={"id": 42}))
    with pytest.raises(ValueError, match="due_date"):
        await node(
            {
                "operation": "create_work_order",
                "title": "Inspection",
                "start_date": "2022-01-01T00:00:00Z",
            }
        ).execute({})
    assert not requests


def test_maintainx_closed_inputs_and_required_fields():
    with pytest.raises(ValidationError):
        native.CreateWorkOrder()
    with pytest.raises(ValidationError):
        native.CreatePart(name="Part", unknown_field="refused")


@pytest.mark.parametrize("field", ["due_date", "start_date"])
def test_maintainx_timestamps_require_a_timezone(field):
    with pytest.raises(ValidationError):
        native.CreateWorkOrder(title="Inspection", **{field: "2026-11-08T10:00:00"})


@pytest.mark.asyncio
async def test_maintainx_partial_update_preserves_unsupplied_fields(monkeypatch):
    requests = transport(
        monkeypatch,
        httpx.Response(200, json={"part": {"id": 843, "availableQuantity": 0}}),
    )
    await node(
        {"operation": "update_part", "part_id": 843, "available_quantity": 0}
    ).execute({})
    assert json.loads(requests[0].content) == {"availableQuantity": 0}
    with pytest.raises(ValidationError, match="at least one"):
        native.UpdatePart(part_id=843)
