"""SMTPing routes, bodies, account evidence and failure handling; no live calls."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import smtping_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-smtping-key-42"
JOB = "0a710238-06a5-4e24-af2b-e8593fc644fc"
CREDENTIAL = {"credential_type": native.CREDENTIAL_TYPE, "api_key": TOKEN}


def node(config):
    return NodeFactory.create_node(node_id="smtping-test", node_type="automation-smtping",
                                 node_data={"config": config, "credentials": CREDENTIAL})


def transport(monkeypatch, status, body, headers=None):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body, headers=headers)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        assert kwargs["verify"] is True
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


CASES = [
    ("verify_single", {"email": "someone@example.com"}, "POST", "/verify/single", 200, {"email": "someone@example.com", "status": "unknown"}),
    ("create_bulk_job", {"emails": ["first@example.com", "second@example.org"]}, "POST", "/verify/bulk", 202, {"jobId": JOB, "status": "Queued"}),
    ("get_bulk_job", {"job_id": JOB}, "GET", f"/verify/bulk/{JOB}", 200, {"jobId": JOB, "status": "Processing"}),
    ("get_bulk_job_result", {"job_id": JOB}, "GET", f"/verify/bulk/{JOB}/result", 200, []),
    ("check_one", {"check": "spamtrap", "email": "someone@example.com"}, "POST", "/checks/spamtrap", 200, {"matched": False, "source": None}),
    ("check_batch", {"check": "disposable", "emails": ["a@example.com", "b@example.com"]}, "POST", "/checks/disposable/batch", 200, {"results": []}),
    ("create_check_job", {"check": "complainer", "emails": ["a@example.com"]}, "POST", "/checks/complainer/jobs", 202, {"jobId": JOB, "status": "Queued"}),
    ("get_check_job", {"job_id": JOB}, "GET", f"/checks/jobs/{JOB}", 200, {"status": "Succeeded"}),
    ("get_check_job_result", {"job_id": JOB}, "GET", f"/checks/jobs/{JOB}/result", 200, [{"email": "a@example.com", "matched": False, "source": None}]),
    ("check_flags", {"email": "someone@example.com"}, "POST", "/checks/flags", 200, {"spamtrap": False}),
    ("get_credits", {}, "GET", "/credits", 200, {"remaining": 8491109, "plan": "Free", "dailyRemaining": None}),
    ("get_usage", {}, "GET", "/usage", 200, {"totals": {}, "daily": []}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,fields,method,path,status,body", CASES)
async def test_one_contract_request_per_operation(monkeypatch, operation, fields, method, path, status, body):
    requests = transport(monkeypatch, status, body)
    result = await node({"operation": operation, **fields}).run({})
    assert result == {"action": operation, "status": "success", "data": body}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert str(request.url) == native.BASE_URL + path
    assert request.headers["X-API-Key"] == TOKEN and "Authorization" not in request.headers
    if method == "POST":
        assert json.loads(request.content) == {k: fields[k] for k in ("email", "emails") if k in fields}
    else:
        assert request.content == b""
    assert TOKEN not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("check", ["spamtrap", "disposable", "spambot", "complainer"])
async def test_all_check_selectors(monkeypatch, check):
    requests = transport(monkeypatch, 200, {"matched": False})
    await node({"operation": "check_one", "check": check, "email": "someone@example.com"}).run({})
    assert requests[0].url.path == "/api/v1/checks/" + check


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 400, 401, 402, 403, 404, 409, 429, 500])
async def test_refusal_pending_rate_limit_and_no_retries(monkeypatch, status):
    requests = transport(monkeypatch, status, {"error": "Provider refusal " + TOKEN},
                         {"Retry-After": "60", "Location": "https://example.org"})
    result = await node({"operation": "get_credits"}).run({})
    assert result["status"] == "error" and result["http_status"] == status
    assert TOKEN not in str(result) and "Provider refusal" in result["error"]
    assert len(requests) == 1
    if status == 429:
        assert result["retry_after"] == "60"
    if status == 409:
        assert result["pending"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,fields,body", [("get_credits", {}, []), ("get_credits", {}, None),
    ("get_credits", {}, {"error": "failed"}), ("get_bulk_job_result", {"job_id": JOB}, {})])
async def test_unexpected_envelopes_fail(monkeypatch, operation, fields, body):
    transport(monkeypatch, 200, body)
    assert (await node({"operation": operation, **fields}).run({}))["status"] == "error"


@pytest.mark.asyncio
async def test_transport_failure_is_not_success_and_not_retried(monkeypatch):
    calls = []
    def fail(request):
        calls.append(request)
        raise httpx.ReadTimeout("private " + TOKEN)
    monkeypatch.setattr(native, "guarded_async_client", lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(fail), **kw))
    result = await node({"operation": "create_bulk_job", "emails": ["a@example.com"]}).run({})
    assert result["status"] == "error" and TOKEN not in str(result) and len(calls) == 1


def test_manual_key_and_schema_contract():
    credential = native.SmtpingApiKeyCredential(api_key=TOKEN)
    assert credential.credential_type == native.CREDENTIAL_TYPE
    assert native.SmtpingNode.connection_evidence.operation == "get_credits"
    assert native.SmtpingNode.connection_evidence.proves == "reachability"
    assert len(native.ROUTES) == 12
    fixture = json.loads((Path(__file__).parent / "fixtures/smtping/contract.json").read_text())
    assert fixture["source"] == "https://smtping.com/openapi.json"
    assert set(fixture["operations"]) == set(native.ROUTES)
    for cls, fields in [
        (native.CheckBatch, {"check": "spamtrap", "emails": ["a@example.com"] * 1001}),
        (native.CreateBulkJob, {"emails": []}),
        (native.VerifySingle, {"email": "invalid"}),
        (native.GetBulkJob, {"job_id": "../credits"}),
        (native.CheckOne, {"check": "../credits", "email": "a@example.com"}),
    ]:
        with pytest.raises(ValidationError):
            cls(**fields)
    for value in ["https://example.com", "<token>", "some key\r\nHeader:value"]:
        with pytest.raises((ValueError, ValidationError)):
            native.SmtpingApiKeyCredential(api_key=value)
