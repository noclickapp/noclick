"""Projul wire regressions. All traffic is synthetic and stays in MockTransport."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import projul_node as native
from nodes.core.registry import NodeFactory

TOKEN = "prjl_live_synthetic_regression_secret"
CUSTOMER = "cus_0000004Kx7Qm2Bv1LpZq8T"
PROJECT = "prj_00000Nv8Rt3Zc6Hd1Mq4Xw"
TASK = "tsk_00000Nv8Rt3Zc6Hd1Mq4Xw"
MESSAGE = "msg_00000Hs5Yc2Mp9Tv4Kb7Rd"
VERSION = "a" * 32


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(
        node_id="projul-test",
        node_type="automation-projul",
        node_data={
            "config": config,
            "credentials": {"credential_type": "projul_api_key", "api_key": TOKEN},
        },
    )


def transport(monkeypatch, response, status=200, headers=None):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=response, headers=headers)

    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    json.loads((Path(__file__).parent / "fixtures/projul/operations.json").read_text()),
)
async def test_every_operation_uses_its_published_method_path_and_headers(
    monkeypatch, case
):
    requests = transport(monkeypatch, case["response"], case["http_status"])
    result = await node(case["config"]).execute({})
    assert result["status"] == "success", result
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"] and request.url.path == case["path"]
    assert request.url.host == "connect.projul.com"
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert dict(request.url.params) == {}
    if case.get("body") is not None:
        assert json.loads(request.content) == case["body"]
    else:
        assert not request.content
    for k, v in case.get("headers", {}).items():
        assert request.headers[k] == v
    assert TOKEN not in str(result)


@pytest.mark.asyncio
async def test_page_cursor_filters_false_and_incremental_timestamp(monkeypatch):
    requests = transport(
        monkeypatch,
        {
            "data": [{"id": CUSTOMER, "company_name": "Whitfield"}],
            "has_more": True,
            "next_cursor": "opaque+cursor/=",
        },
    )
    result = await node(
        {
            "operation": "list_customers",
            "limit": 10,
            "after": "opaque+cursor/=",
            "include_archived": False,
            "updated_since": "2026-08-05T15:12:00.000Z",
            "email": "dana+sync@example.com",
        }
    ).execute({})
    assert result["status"] == "success" and not result["complete"]
    assert result["next_cursor"] == "opaque+cursor/="
    params = dict(requests[0].url.params)
    assert (
        params["include_archived"] == "false" and params["after"] == "opaque+cursor/="
    )
    assert params["limit"] == "10" and params["email"] == "dana+sync@example.com"
    assert params["updated_since"].startswith("2026-08-05T15:12:00")


@pytest.mark.asyncio
async def test_create_or_match_customer_does_not_claim_new_creation(monkeypatch):
    transport(monkeypatch, {"id": CUSTOMER, "matched": True}, 200)
    result = await node(
        {
            "operation": "create_customer",
            "first_name": "Dana",
            "idempotency_key": "job-123",
        }
    ).execute({})
    assert result["data"]["matched"] is True and result["http_status"] == 200


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,code",
    [
        (401, "invalid_api_key"),
        (403, "insufficient_access"),
        (412, "stale_version"),
        (429, "rate_limited"),
        (500, "internal_error"),
        (302, "redirect"),
    ],
)
async def test_provider_rejections_preserve_details_redact_secret_and_never_retry(
    monkeypatch, status, code
):
    requests = transport(
        monkeypatch,
        {"code": code, "detail": "Rejected " + TOKEN, "request_id": "req-test"},
        status,
        {"Retry-After": "7"},
    )
    result = await node({"operation": "get_account"}).execute({})
    assert (
        result["status"] == "error"
        and result["code"] == code
        and result["http_status"] == status
    )
    assert result["request_id"] == "req-test" and result["retry_after"] == "7"
    assert TOKEN not in str(result) and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {},
        {"data": [], "has_more": True, "next_cursor": None},
        {"data": {}, "has_more": False, "next_cursor": None},
        {"error": "failed"},
    ],
)
async def test_malformed_success_is_not_working_evidence(monkeypatch, body):
    transport(monkeypatch, body)
    assert (await node({"operation": "list_customers"}).execute({}))[
        "status"
    ] == "error"


@pytest.mark.asyncio
async def test_mismatched_identity_and_transport_failure_are_not_success(monkeypatch):
    transport(monkeypatch, {"id": "cus_0000000000000000000000"})
    assert (
        await node({"operation": "get_customer", "customer_id": CUSTOMER}).execute({})
    )["status"] == "error"

    def fail(**kwargs):
        raise httpx.ConnectError("private " + TOKEN)

    monkeypatch.setattr(native, "guarded_async_client", fail)
    result = await node({"operation": "get_account"}).execute({})
    assert result["status"] == "error" and TOKEN not in str(result)


@pytest.mark.parametrize(
    "config",
    [
        {"operation": "create_customer", "idempotency_key": "job-123"},
        {
            "operation": "create_customer",
            "first_name": "Dana",
            "idempotency_key": "bad\nheader",
        },
        {"operation": "update_project", "project_id": PROJECT, "name": "Kitchen"},
        {
            "operation": "update_project",
            "project_id": PROJECT,
            "if_match": "*",
            "name": "Kitchen",
        },
        {"operation": "get_customer", "customer_id": "../foreign"},
        {
            "operation": "create_message",
            "parent_type": "project",
            "parent_id": CUSTOMER,
            "body": "Note",
            "idempotency_key": "job-123",
        },
        {"operation": "list_customers", "limit": 101},
        {"operation": "list_customers", "unknown": "typo"},
        {"operation": "update_task", "task_id": TASK, "if_match": VERSION},
    ],
)
def test_invalid_inputs_refused_before_traffic(config):
    with pytest.raises((ValueError, ValidationError)):
        node(config)


def test_manual_key_has_default_tag_and_only_one_required_secret():
    credential = native.ProjulAPIKeyCredential(api_key=" " + TOKEN + " ")
    assert (
        credential.credential_type == "projul_api_key" and credential.api_key == TOKEN
    )
    assert {n for n, f in credential.model_fields.items() if f.is_required()} == {
        "api_key"
    }


@pytest.mark.asyncio
async def test_merge_patch_explicit_null_and_required_nested_nulls_survive(monkeypatch):
    requests = transport(monkeypatch, {"id": CUSTOMER})
    result = await node(
        {
            "operation": "update_customer",
            "customer_id": CUSTOMER,
            "description": None,
            "if_match": None,
        }
    ).execute({})
    assert result["status"] == "success"
    assert json.loads(requests[0].content) == {"description": None}
    assert "If-Match" not in requests[0].headers
    requests = transport(monkeypatch, {"id": CUSTOMER, "matched": False}, 201)
    address = {
        "street1": "1400 W Bannock St",
        "city": "Boise",
        "state": "ID",
        "postal_code": "83702",
        "latitude": None,
        "longitude": None,
    }
    result = await node(
        {
            "operation": "create_customer",
            "idempotency_key": "job-123",
            "first_name": "Dana",
            "address": address,
            "emails": [{"email": None, "type": "Work"}],
        }
    ).execute({})
    assert result["status"] == "success"
    assert json.loads(requests[0].content)["address"] == address
    assert json.loads(requests[0].content)["emails"] == [
        {"email": None, "type": "Work"}
    ]


def test_nested_task_ids_are_validated():
    with pytest.raises((ValueError, ValidationError)):
        node(
            {
                "operation": "create_task",
                "task_type": "Task",
                "idempotency_key": "job-123",
                "assignments": [{"user_ids": ["1"]}],
            }
        )
