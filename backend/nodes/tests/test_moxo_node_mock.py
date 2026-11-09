"""Exercise the native node and connect seam with HTTP intercepted at transport."""
from copy import deepcopy
from unittest.mock import AsyncMock
import json

import httpx
import pytest
from pydantic import ValidationError

from nodes import moxo_node as moxo
from nodes.core.credential_connect import shape_credential
from nodes.core.run_op import run_node_operation
from utils import ssrf

AUTH = {"credential_type": "moxo_api_token", "api_token": "fixture-moxo-personal-token"}
USER = "00000000-0000-4000-8000-000000000001"


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))

    async def send(request):
        requests.append(request)
        assert request.headers["Authorization"] == "Bearer " + AUTH["api_token"]
        assert AUTH["api_token"] not in str(request.url)
        code, body = replies.pop(0)
        return httpx.Response(code, json=body)

    native = ssrf.guarded_async_client
    monkeypatch.setattr(moxo, "guarded_async_client", lambda **kw: native(**kw, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(operation, arguments=None, credential=AUTH):
    return await run_node_operation(node_type="automation-moxo", operation=operation,
        arguments=arguments or {}, credential_data=deepcopy(credential), user_id=USER)


CASES = [
    ("get_me", {}, "GET", "/v1/users/me", {}, None),
    ("list_users", {"kind": "external", "account_id": "acc_acme", "search": "Ana", "cursor": "page2"}, "GET", "/v1/users", {"limit": "50", "kind": "external", "accountId": "acc_acme", "search": "Ana", "cursor": "page2"}, None),
    ("get_user", {"user_id": "ana@example.com"}, "GET", "/v1/users/ana%40example.com", {}, None),
    ("list_templates", {}, "GET", "/v1/templates", {"limit": "50", "kind": "process"}, None),
    ("get_template", {"template_id": "tmpl_123", "expand": "dependencies"}, "GET", "/v1/templates/tmpl_123", {"copy": "published", "expand": "dependencies"}, None),
    ("start_flow", {"template_id": "tmpl_123", "name": "Acme onboarding", "role_assignments": [{"roleId": "role-customer", "email": "ana@example.com"}], "custom_fields": [{"key": "deal_size", "value": 250000}]}, "POST", "/v1/templates/tmpl_123/start", {}, {"name": "Acme onboarding", "roleAssignments": [{"roleId": "role-customer", "email": "ana@example.com"}], "customFields": [{"key": "deal_size", "value": 250000}]}),
    ("list_flows", {"template_id": "tmpl_123", "status": "IN_PROGRESS,PAUSED", "lifecycle": "all", "offset": 50}, "GET", "/v1/flows", {"limit": "50", "templateId": "tmpl_123", "status": "IN_PROGRESS,PAUSED", "lifecycle": "all", "offset": "50"}, None),
    ("get_flow", {"flow_id": "flow_123"}, "GET", "/v1/flows/flow_123", {}, None),
    ("update_flow", {"flow_id": "flow_123", "name": "Renamed", "clear_due_date": True}, "PATCH", "/v1/flows/flow_123", {}, {"name": "Renamed", "dueAt": None}),
    ("cancel_flow", {"flow_id": "flow_123", "reason": "No longer needed"}, "POST", "/v1/flows/flow_123/cancel", {}, {"reason": "No longer needed"}),
    ("archive_flow", {"flow_id": "flow_123"}, "POST", "/v1/flows/flow_123/archive", {}, None),
    ("unarchive_flow", {"flow_id": "flow_123"}, "POST", "/v1/flows/flow_123/unarchive", {}, None),
    ("pause_flow", {"flow_id": "flow_123", "reason": "Waiting on the client's bank to confirm the transfer."}, "POST", "/v1/flows/flow_123/pause", {}, {"reason": "Waiting on the client's bank to confirm the transfer."}),
    ("resume_flow", {"flow_id": "flow_123"}, "POST", "/v1/flows/flow_123/resume", {}, None),
    ("list_steps", {"flow_id": "flow_123", "status": "IN_PROGRESS"}, "GET", "/v1/flows/flow_123/steps", {"limit": "50", "status": "IN_PROGRESS"}, None),
    ("get_step", {"flow_id": "flow_123", "step_id": "step-2"}, "GET", "/v1/flows/flow_123/steps/step-2", {}, None),
    ("complete_step", {"flow_id": "flow_123", "step_id": "step-2", "result_data": {"decision": "APPROVED"}, "time_entry": {"minutes": 10, "billable": False}}, "POST", "/v1/flows/flow_123/steps/step-2/complete", {}, {"resultData": {"decision": "APPROVED"}, "timeEntry": {"minutes": 10, "billable": False}}),
    ("list_flow_messages", {"flow_id": "flow_123", "cursor": "opaque-cursor"}, "GET", "/v1/flows/flow_123/messages", {"limit": "50", "cursor": "opaque-cursor"}, None),
    ("post_flow_message", {"flow_id": "flow_123", "body": "The signed copy is uploaded.", "target_step_execution_id": "step-2", "mentions": ["usr_123"]}, "POST", "/v1/flows/flow_123/messages", {}, {"body": "The signed copy is uploaded.", "targetStepExecutionId": "step-2", "mentions": ["usr_123"]}),
    ("get_flow_summary", {"flow_id": "flow_123"}, "GET", "/v1/flows/flow_123/summary", {}, None),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,args,method,path,query,body", CASES)
async def test_every_operation_exact_wire_contract(transport, operation, args, method, path, query, body):
    requests, replies = transport
    response = {"success": True, "data": [{"id": "tmpl_123", "name": "Onboarding"}], "pagination": {"nextCursor": "opaque-next", "hasMore": True}}
    replies.append((201 if operation == "post_flow_message" else 200, response))
    result = await run(operation, args)
    assert result["status"] == "success"
    assert result["data"] == response["data"]
    assert result["pagination"] == response["pagination"]
    assert len(requests) == 1 and not replies
    request = requests[0]
    assert request.method == method
    assert request.url.raw_path.decode().split("?")[0] == path
    assert dict(request.url.params) == query
    assert (json.loads(request.content) if request.content else None) == body


@pytest.mark.asyncio
async def test_step_completion_empty_body_and_async_acceptance(transport):
    requests, replies = transport
    replies.append((202, {"success": True}))
    result = await run("complete_step", {"flow_id": "flow_123", "step_id": "step-2"})
    assert result["http_status"] == 202 and "data" not in result
    assert json.loads(requests[0].content) == {}


@pytest.mark.asyncio
async def test_summary_null_and_mutation_ack_without_data(transport):
    _, replies = transport
    replies.extend([(200, {"success": True, "data": None}), (200, {"success": True, "changed": False, "message": "No change"})])
    assert (await run("get_flow_summary", {"flow_id": "flow_123"}))["data"] is None
    assert (await run("update_flow", {"flow_id": "flow_123", "name": "Existing"}))["changed"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("host", ["https://api.moxo.com", "https://api.eu.moxo.com", "https://api.au.moxo.com", "https://api.sg.moxo.com"])
async def test_documented_regions(transport, host):
    requests, replies = transport
    replies.append((200, {"success": True, "data": {"id": "usr_123", "name": "Ana"}}))
    await run("get_me", credential={**AUTH, "api_base_url": host})
    assert str(requests[0].url).startswith(host + "/v1/users/me")


@pytest.mark.asyncio
async def test_idempotency_header_and_datetime_query(transport):
    requests, replies = transport
    replies.extend([(200, {"success": True, "data": {}}), (200, {"success": True, "data": []})])
    await run("start_flow", {"template_id": "tmpl_123", "idempotency_key": "request-123"})
    assert requests[0].headers["Idempotency-Key"] == "request-123"
    assert "idempotency_key" not in json.loads(requests[0].content)
    await run("list_flows", {"updated_since": "2026-01-01T00:00:00Z"})
    assert requests[1].url.params["updatedSince"] == "2026-01-01T00:00:00Z"


@pytest.mark.asyncio
@pytest.mark.parametrize("code,body", [(401, {"success": False, "error": {"message": "Invalid token"}}), (403, {"error": {"message": "PERSON_TOKEN_REQUIRED"}}), (200, {"success": False, "error": {"message": "Denied"}}), (302, {"success": True})])
async def test_provider_failures_never_report_success(transport, code, body):
    requests, replies = transport
    replies.append((code, body))
    with pytest.raises(ValueError):
        await run("get_me")
    assert len(requests) == 1


@pytest.mark.parametrize("change", [{"api_base_url": "https://evil.test"}, {"api_base_url": "http://api.moxo.com"}, {"api_base_url": "https://api.moxo.com@evil.test"}, {"api_token": "Bearer mxo_pat_123"}, {"credential_type": "other_token"}])
def test_invalid_credentials(change):
    with pytest.raises(ValidationError):
        moxo.MoxoCredential.model_validate({**AUTH, **change})


def test_hand_connect_defaults_and_fields():
    shaped, errors, resolved = shape_credential("moxo_api_token", {"api_token": AUTH["api_token"]})
    assert not errors
    assert resolved[1] is moxo.MoxoCredential
    credential = moxo.MoxoCredential.model_validate(shaped)
    assert credential.credential_type == "moxo_api_token"
    assert credential.api_base_url == "https://api.moxo.com"


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["..", "a/b", "a%2Fb", "id?query", "https://evil.test", "x\n"])
async def test_path_injection_refused(transport, bad):
    with pytest.raises(ValueError):
        await run("get_flow", {"flow_id": bad})
    assert not transport[0]


def test_role_assignment_needs_exactly_one_person_and_due_date_choice():
    for value in [{"roleId": "buyer"}, {"roleId": "buyer", "email": "ana@example.com", "userId": "usr_123"}]:
        with pytest.raises(ValidationError):
            moxo.RoleAssignment.model_validate(value)
    with pytest.raises(ValidationError):
        moxo.UpdateFlow(flow_id="flow_123", due_at="2030-01-01T00:00:00Z", clear_due_date=True)


@pytest.mark.parametrize("args", [{"cursor": "next"}, {"updated_since": "2026-01-01T00:00:00Z", "offset": 0}])
def test_flow_paging_modes_cannot_be_mixed(args):
    with pytest.raises(ValidationError):
        moxo.ListFlows(**args)
