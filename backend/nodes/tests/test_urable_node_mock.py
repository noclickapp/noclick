"""Urable wire contracts with synthetic credentials; no live account is used."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import urable_node as native
from nodes.core.registry import NodeFactory

CASES = json.loads(
    (Path(__file__).parent / "fixtures/urable/requests.json").read_text()
)
TOKEN = "synthetic-urable-key-42"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credential=None):
    return NodeFactory.create_node(
        node_id="urable-test",
        node_type="automation-urable",
        node_data={
            "config": config,
            "credentials": credential
            or {"credential_type": "urable_api_key", "api_key": TOKEN},
        },
    )


def transport(monkeypatch, body, status=200):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body)

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["config"]["operation"])
async def test_urable_exact_request_and_documented_envelope(monkeypatch, case):
    cfg = case["config"]
    listing = cfg["operation"].startswith("list_")
    data = (
        [{"id": "resource-42", "name": "Owned resource"}]
        if listing
        else {"id": "resource-42"}
    )
    requests = transport(monkeypatch, {"success": True, "data": data})
    result = await node(cfg).execute({})
    assert result["success"] is True and result["data"] == data
    assert len(requests) == 1
    request = requests[0]
    assert request.url.host == "app.urable.com"
    assert (request.method, request.url.path) == (case["method"], case["path"])
    assert request.headers["authorization"] == "Bearer " + TOKEN
    assert TOKEN not in str(result)
    expected = {k: v for k, v in cfg.items() if k not in {"operation", "id"}}
    if request.method == "GET":
        assert dict(request.url.params) == {k: str(v) for k, v in expected.items()}
        assert not request.content
    else:
        assert json.loads(request.content) == expected
        assert not request.url.query


@pytest.mark.asyncio
async def test_urable_patch_preserves_omitted_and_explicit_false_fields(monkeypatch):
    requests = transport(monkeypatch, {"success": True, "data": {"id": "customer-42"}})
    await node(
        {
            "operation": "update_customer",
            "id": "customer-42",
            "taxExempt": False,
            "emails": [],
        }
    ).execute({})
    assert json.loads(requests[0].content) == {
        "taxExempt": False,
        "emails": [],
    }


@pytest.mark.asyncio
async def test_urable_cursor_direction_and_lookup_filter(monkeypatch):
    rows = [{"id": "first"}, {"id": "last"}]
    transport(monkeypatch, {"success": True, "data": rows})
    result = await node({"operation": "list_customers", "limit": 2}).execute({})
    assert result["possible_next_start_after"] == "last"
    result = await node(
        {"operation": "list_customers", "limit": 2, "endBefore": "earlier"}
    ).execute({})
    assert (
        result["possible_previous_end_before"] == "first"
        and result["possible_next_start_after"] is None
    )
    result = await node(
        {"operation": "list_customers", "limit": 2, "email": "a+b@example.test"}
    ).execute({})
    assert result["possible_next_start_after"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
async def test_urable_rejections_never_report_success(monkeypatch, status):
    requests = transport(monkeypatch, {"success": False, "error": "Denied"}, status)
    with pytest.raises((ValueError, httpx.HTTPStatusError)):
        await node({"operation": "list_customers"}).execute({})
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {},
        {"success": False, "error": "Denied"},
        {"success": True, "data": {}},
        {"success": True, "data": [None]},
    ],
)
async def test_urable_invalid_list_and_error_envelopes_fail_closed(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError):
        await node({"operation": "list_customers"}).execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cfg",
    [
        {"operation": "get_customer", "id": "../other"},
        {"operation": "update_customer", "id": "customer-42"},
        {"operation": "create_event", "name": "Meeting", "start": 2, "end": 1},
        {
            "operation": "create_event",
            "name": "Meeting",
            "start": 1,
            "end": 2,
            "private": True,
        },
        {
            "operation": "create_item",
            "name": "Lawn",
            "customerId": "customer-42",
            "industry": "lawnCare",
        },
        {"operation": "update_job", "id": "job-42", "itemIds": ["item-42"]},
    ],
)
async def test_urable_invalid_write_or_path_never_sends(monkeypatch, cfg):
    requests = transport(monkeypatch, {"success": True, "data": {"id": "42"}})
    with pytest.raises(ValueError):
        await node(cfg).execute({})
    assert requests == []


def test_urable_schema_required_fields_defaults_and_credentials():
    assert (
        native.UrableAPIKeyCredential(api_key=TOKEN).credential_type == "urable_api_key"
    )
    for cfg in [
        {"operation": "create_customer"},
        {"operation": "create_job"},
        {"operation": "list_customers", "limit": 101},
        {"operation": "list_customers", "startAfter": "a", "endBefore": "b"},
    ]:
        with pytest.raises(ValidationError):
            native.UrableFullConfig(config=cfg)
    assert len(CASES) == len(native.OPERATIONS) == 25
