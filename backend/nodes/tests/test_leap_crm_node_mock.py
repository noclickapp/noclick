"""Wire checks against the provider's published example responses."""
import json
from copy import deepcopy
from email.parser import BytesParser
from email.policy import default
from pathlib import Path
from unittest.mock import AsyncMock
from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import ValidationError

from nodes import leap_crm_node as leap
from nodes.core.run_op import run_node_operation
from utils import ssrf

AUTH = {"credential_type": "leap_crm_token", "access_token": "synthetic-leap-api-token"}
RESPONSES = json.loads((Path(__file__).parent / "fixtures/leap-crm/responses.json").read_text())
CUSTOMER = {"first_name": "John", "last_name": "Doe", "phone_number": "7656565757"}
JOB = {"customer_id": "25", "description": "Carpentry Job", "trade_id": 1}
CASES = [
    ("list_customers", {}, "GET", "/customers", {"page": "1", "limit": "50"}),
    ("get_customer", {"customer_id": "375"}, "GET", "/customers/375", {}),
    ("create_customer", CUSTOMER, "POST", "/customers", {"first_name": "John", "last_name": "Doe", "phones[0][label]": "cell", "phones[0][number]": "7656565757"}),
    ("update_customer", {**CUSTOMER, "customer_id": "70"}, "PUT", "/customers/70", {"first_name": "John", "last_name": "Doe", "phones[0][label]": "cell", "phones[0][number]": "7656565757"}),
    ("list_jobs", {"customer_id": "25", "page": 2}, "GET", "/jobs", {"page": "2", "limit": "50", "customer_id": "25"}),
    ("get_job", {"job_id": "60"}, "GET", "/jobs/60", {}),
    ("create_job", JOB, "POST", "/jobs", {"customer_id": "25", "description": "Carpentry Job", "trades[]": "1", "same_as_customer_address": "1"}),
    ("update_job", {**JOB, "job_id": "178"}, "PUT", "/jobs/178", {"customer_id": "25", "description": "Carpentry Job", "trades[]": "1", "same_as_customer_address": "1"}),
    ("get_job_financial_summary", {"job_id": "5368305"}, "GET", "/jobs/5368305/financial_summary", {}),
    ("get_job_workflow_history", {"job_id": "60"}, "GET", "/jobs/60/workflow_history", {}),
    ("list_job_notes", {"job_id": "60"}, "GET", "/jobs/60/notes", {}),
    ("add_job_note", {"job_id": "60", "note": "Todo"}, "POST", "/jobs/60/notes", {"note": "Todo"}),
    ("update_job_note", {"note_id": "2", "note": "Updated Todo"}, "PUT", "/jobs/notes/2", {"note": "Updated Todo"}),
    ("list_contacts", {"email": "john@example.com"}, "GET", "/contacts", {"email": "john@example.com", "limit": "50"}),
    ("list_trades", {}, "GET", "/company/trades", {"page": "1", "limit": "50"}),
    ("list_users", {}, "GET", "/company/users", {"page": "1", "limit": "50"}),
    ("list_workflow_stages", {}, "GET", "/workflow/stages", {"page": "1", "limit": "50"}),
]


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def wire(monkeypatch):
    requests, responses = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))

    async def send(request):
        requests.append(request)
        assert request.url.host == "api.jobprogress.com"
        assert request.headers["authorization"] == "Bearer " + AUTH["access_token"]
        assert AUTH["access_token"] not in str(request.url)
        return responses.pop(0)

    native = ssrf.guarded_async_client
    monkeypatch.setattr(leap, "guarded_async_client", lambda **kw: native(**kw, transport=httpx.MockTransport(send)))
    return requests, responses


async def run(operation, arguments=None):
    return await run_node_operation(node_type="automation-leap-crm", operation=operation,
        arguments=deepcopy(arguments or {}), credential_data=deepcopy(AUTH),
        user_id="00000000-0000-4000-8000-000000000001")


@pytest.mark.parametrize("operation,arguments,method,path,fields", CASES)
async def test_documented_operations(wire, operation, arguments, method, path, fields):
    requests, responses = wire
    payload = RESPONSES[operation]["body"]
    # Preserve the JSON body even when the provider labels it text/plain.
    responses.append(httpx.Response(200, text=json.dumps(payload), headers={"content-type": "text/plain"}))
    result = await run(operation, arguments)
    assert result["status"] == "success"
    for key, value in payload.items():
        if key != "status":
            assert result[key] == value
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == "/api/v3" + path
    if method == "GET":
        actual = dict(request.url.params)
        assert not request.content
    elif operation == "add_job_note":
        message = BytesParser(policy=default).parsebytes(
            b"Content-Type: " + request.headers["content-type"].encode() + b"\r\n\r\n" + request.content)
        actual = {part.get_param("name", header="content-disposition"): part.get_content().decode()
                  if isinstance(part.get_content(), bytes) else part.get_content() for part in message.iter_parts()}
    else:
        assert request.headers["content-type"].startswith("application/x-www-form-urlencoded")
        actual = {key: values[0] for key, values in parse_qs(request.content.decode(), keep_blank_values=True).items()}
    assert actual == fields


async def test_connection_evidence_uses_account_customers(wire):
    from nodes.core.connection_evidence import collect_evidence
    requests, responses = wire
    responses.append(httpx.Response(200, json={"data": [{"id": 171, "company_name": "Teasley Lane"}]}))
    proof = await collect_evidence(node_type="automation-leap-crm", credential_data=AUTH,
        user_id="00000000-0000-4000-8000-000000000001")
    assert proof.reachable is True
    assert any(sample.label == "Teasley Lane" for sample in proof.samples)
    assert requests[0].url.path == "/api/v3/customers"


@pytest.mark.parametrize("code", [301, 401, 403, 404, 429, 500])
async def test_provider_rejection_and_redirect_are_not_success(wire, code):
    requests, responses = wire
    responses.append(httpx.Response(code, text="Access denied " + AUTH["access_token"], headers={"location": "https://example.com"}))
    result = await run("list_customers")
    assert result["status"] == "error" and result["http_status"] == code
    assert result["error"] == "Access denied <redacted>"
    assert len(requests) == 1


@pytest.mark.parametrize("payload", [{"errors": {"email": "Invalid email"}}, {"success": False, "message": "Rejected"}])
async def test_error_envelope(wire, payload):
    _, responses = wire
    responses.append(httpx.Response(200, json=payload))
    assert (await run("list_customers"))["status"] == "error"


@pytest.mark.parametrize("payload", ["<html>Sign in</html>", "[]", "{}", "null"])
async def test_malformed_response_is_not_accepted(wire, payload):
    _, responses = wire
    responses.append(httpx.Response(200, text=payload))
    with pytest.raises(ValueError):
        await run("list_customers")


@pytest.mark.parametrize("value", ["../1", "1?other=2", "https://example.com", "0", "-1"])
def test_resource_ids_cannot_change_routes(value):
    with pytest.raises(ValidationError):
        leap.GetJob(job_id=value)


def test_manual_token_has_default_type_and_validates_secret():
    assert leap.LeapCRMTokenCredential(access_token=AUTH["access_token"]).credential_type == "leap_crm_token"
    for value in ["Bearer abc", "https://example.com", "<token>"]:
        with pytest.raises(ValidationError):
            leap.LeapCRMTokenCredential(access_token=value)
