"""Contract routes and provider response forms through the native runner."""
import base64
import json
from copy import deepcopy
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import apptivegrid_node as ag
from nodes.core.run_op import run_node_operation
from nodes.core.connection_evidence import collect_evidence
from utils import ssrf

AUTH = {
    "credential_type": "apptivegrid_api_key",
    "api_key": "fixture-key",
    "api_secret": "fixture-secret",
    "user_id": "64f1a2b3c4d5e6f708091a2b",
}
USER = "00000000-0000-4000-8000-000000000001"


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(
        ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"])
    )

    async def send(request):
        requests.append(request)
        assert request.url.host == "app.apptivegrid.de"
        assert (
            request.headers["Authorization"]
            == "Basic " + base64.b64encode(b"fixture-key:fixture-secret").decode()
        )
        assert "fixture-key" not in str(request.url)
        return replies.pop(0)

    native = ssrf.guarded_async_client
    monkeypatch.setattr(
        ag,
        "guarded_async_client",
        lambda **kw: native(**kw, transport=httpx.MockTransport(send)),
    )
    return requests, replies


async def run(operation, arguments=None):
    return await run_node_operation(
        node_type=ag.ApptivegridNode.integration_type,
        operation=operation,
        arguments=arguments or {},
        credential_data=deepcopy(AUTH),
        user_id=USER,
    )


PAGE = {
    "page": 1,
    "pageSize": 100,
    "size": 1,
    "numberOfItems": 101,
    "numberOfPages": 2,
    "items": [
        {"_representation": "summary", "id": "s1", "name": "Projects", "_links": {}}
    ],
}
CASES = [
    ("get_user", {}, "GET", "", 200, {}),
    ("list_spaces", {}, "GET", "/spaces", 200, PAGE),
    ("create_space", {"name": "API-Test"}, "POST", "/spaces", 201, {}),
    ("get_space", {"space_id": "s1"}, "GET", "/spaces/s1", 200, {}),
    (
        "rename_space",
        {"space_id": "s1", "name": "API-Test"},
        "POST",
        "/spaces/s1/Rename",
        200,
        {},
    ),
    ("delete_space", {"space_id": "s1"}, "DELETE", "/spaces/s1", 200, {}),
    ("list_grids", {"space_id": "s1"}, "GET", "/spaces/s1/grids", 200, PAGE),
    (
        "create_grid",
        {"space_id": "s1", "name": "API-Test"},
        "POST",
        "/spaces/s1/grids",
        201,
        {},
    ),
    (
        "get_grid",
        {"space_id": "s1", "grid_id": "g1"},
        "GET",
        "/spaces/s1/grids/g1",
        200,
        {},
    ),
    (
        "rename_grid",
        {"space_id": "s1", "grid_id": "g1", "name": "API-Test"},
        "POST",
        "/spaces/s1/grids/g1/Rename",
        200,
        {},
    ),
    (
        "delete_grid",
        {"space_id": "s1", "grid_id": "g1"},
        "DELETE",
        "/spaces/s1/grids/g1",
        200,
        {},
    ),
    (
        "get_grid_schema",
        {"space_id": "s1", "grid_id": "g1"},
        "GET",
        "/spaces/s1/grids/g1/schema",
        200,
        {},
    ),
    (
        "list_entries",
        {"space_id": "s1", "grid_id": "g1"},
        "GET",
        "/spaces/s1/grids/g1/entities",
        200,
        PAGE,
    ),
    (
        "create_entry",
        {"space_id": "s1", "grid_id": "g1", "values": {"field1": "First task"}},
        "POST",
        "/spaces/s1/grids/g1/entities",
        201,
        {},
    ),
    (
        "get_entry",
        {"space_id": "s1", "grid_id": "g1", "entity_id": "e1"},
        "GET",
        "/spaces/s1/grids/g1/entities/e1",
        200,
        {},
    ),
    (
        "update_entry",
        {
            "space_id": "s1",
            "grid_id": "g1",
            "entity_id": "e1",
            "values": {"field1": "First task"},
        },
        "PUT",
        "/spaces/s1/grids/g1/entities/e1",
        200,
        {},
    ),
    (
        "partial_update_entry",
        {
            "space_id": "s1",
            "grid_id": "g1",
            "entity_id": "e1",
            "values": {"field1": "First task"},
        },
        "POST",
        "/spaces/s1/grids/g1/entities/e1/update",
        200,
        {},
    ),
    (
        "delete_entry",
        {"space_id": "s1", "grid_id": "g1", "entity_id": "e1"},
        "DELETE",
        "/spaces/s1/grids/g1/entities/e1",
        200,
        "deleted",
    ),
    (
        "list_views",
        {"space_id": "s1", "grid_id": "g1"},
        "GET",
        "/spaces/s1/grids/g1/sviews",
        200,
        PAGE,
    ),
    (
        "list_forms",
        {"space_id": "s1", "grid_id": "g1"},
        "GET",
        "/spaces/s1/grids/g1/forms",
        200,
        PAGE,
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,arguments,method,suffix,status,body", CASES)
async def test_every_operation_one_contract_request(
    transport, operation, arguments, method, suffix, status, body
):
    requests, replies = transport
    location = "/api/users/" + AUTH["user_id"] + suffix + "/new-id"
    replies.append(
        httpx.Response(
            status,
            text="Created " + location,
            headers={"Content-Type": "text/plain", "Location": location},
        )
        if status == 201
        else httpx.Response(status, json=body)
    )
    output = await run(operation, arguments)
    assert output["status"] == "success"
    assert len(requests) == 1
    req = requests[0]
    assert req.method == method
    assert req.url.path == "/api/users/" + AUTH["user_id"] + suffix
    if operation.startswith("list_"):
        assert (
            req.url.params["pageIndex"] == "1" and req.url.params["pageSize"] == "100"
        )
        assert output["next_page_index"] == 2 and output["data"] == PAGE
    if "values" in arguments:
        assert json.loads(req.content) == arguments["values"]
        if operation != "partial_update_entry":
            assert req.url.params["layout"] == "field"
        else:
            assert "layout" not in req.url.params
    if "name" in arguments:
        assert json.loads(req.content) == {
            "name": "API-Test",
            **({"createView": True} if operation == "create_grid" else {}),
        }
    if status == 201:
        assert output["data"] == {
            "location": location,
            "message": "Created " + location,
        }


@pytest.mark.asyncio
async def test_filter_sort_and_pagination_encoded_once(transport):
    requests, replies = transport
    replies.append(httpx.Response(200, json={**PAGE, "page": 2, "items": []}))
    filt = {"field1": {"$eq": "open & urgent"}}
    sort = [{"field1": {"$order": "descending"}}]
    out = await run(
        "list_entries",
        {
            "space_id": "s1",
            "grid_id": "g1",
            "filter": filt,
            "sorting": sort,
            "compose": False,
            "view_id": "v1",
            "page_index": 2,
        },
    )
    q = requests[0].url.params
    assert json.loads(q["filter"]) == filt and json.loads(q["sorting"]) == sort
    assert q["compose"] == "false" and q["viewId"] == "v1" and q["pageIndex"] == "2"
    assert out["next_page_index"] is None


@pytest.mark.asyncio
async def test_indexed_values_and_explicit_nulls(transport):
    requests, replies = transport
    replies.append(httpx.Response(200, json={"_id": "e1"}))
    values = {"fields": ["First task", None, 3]}
    await run(
        "update_entry",
        {
            "space_id": "s1",
            "grid_id": "g1",
            "entity_id": "e1",
            "layout": "indexed",
            "values": values,
        },
    )
    assert json.loads(requests[0].content) == values
    assert requests[0].url.params["layout"] == "indexed"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 401, 403, 429, 500])
async def test_errors_redact_credentials_no_redirects(transport, status):
    requests, replies = transport
    replies.append(
        httpx.Response(
            status,
            text="Denied fixture-key fixture-secret",
            headers={"Location": "https://example.test/"},
        )
    )
    out = await run("get_user")
    assert out["status"] == "error" and out["http_status"] == status
    assert "fixture-key" not in json.dumps(out) and "fixture-secret" not in json.dumps(
        out
    )
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_identity_connection_evidence(transport):
    requests, replies = transport
    replies.append(
        httpx.Response(
            200, json={"id": AUTH["user_id"], "name": "Fixture account", "_links": {}}
        )
    )
    evidence = await collect_evidence(
        node_type=ag.ApptivegridNode.integration_type,
        credential_data=AUTH,
        user_id=USER,
    )
    assert evidence.reachable is True
    assert len(requests) == 1 and requests[0].url.path.endswith(AUTH["user_id"])


@pytest.mark.parametrize(
    "field,value",
    [
        ("user_id", "../other"),
        ("api_key", "https://example.test/key"),
        ("api_secret", "Basic abc:def"),
    ],
)
def test_invalid_credential_fields(field, value):
    with pytest.raises(ValidationError):
        ag.ApptivegridAPIKeyCredential.model_validate({**AUTH, field: value})


def test_manual_type_default():
    assert (
        ag.ApptivegridAPIKeyCredential.model_validate(
            {k: v for k, v in AUTH.items() if k != "credential_type"}
        ).credential_type
        == "apptivegrid_api_key"
    )
