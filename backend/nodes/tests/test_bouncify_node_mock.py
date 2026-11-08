"""Bouncify provider examples and request/error regressions; no live account."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import bouncify_node as native
from nodes.core.binary_output import BinaryOutput
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-bouncify-key-42"
RESPONSES = json.loads((Path(__file__).parent / "fixtures/bouncify/responses.json").read_text())
JOB = RESPONSES["POST /bulk"]["job_id"]


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="bouncify-test", node_type="automation-bouncify",
        node_data={"config": config, "credentials": {"credential_type": "bouncify_api_key", "api_key": TOKEN}})


def transport(monkeypatch, body, *, status=200, mime="application/json"):
    requests = []
    def respond(request):
        requests.append(request)
        if isinstance(body, Exception):
            raise body
        return httpx.Response(status, json=body, headers={"Content-Type": mime}) if mime == "application/json" else httpx.Response(status, text=body, headers={"Content-Type": mime})
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        assert kwargs["timeout"] > 180
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,method,path,config", [
    ("get_credit_balance", "GET", "/info", {}),
    ("verify_email", "GET", "/verify", {"email": "support@bouncify.io"}),
    ("create_bulk_job", "POST", "/bulk", {"emails": [{"email": "test1@example.com", "firstname": "John"}], "auto_verify": True}),
    ("get_bulk_job", "GET", "/bulk", {"job_id": JOB}),
    ("start_bulk_job", "PATCH", "/bulk", {"job_id": JOB}),
    ("delete_bulk_job", "DELETE", "/bulk", {"job_id": JOB}),
    ("download_bulk_results", "POST", "/download", {"job_id": JOB}),
])
async def test_all_seven_documented_operations(monkeypatch, operation, method, path, config):
    csv = operation == "download_bulk_results"
    requests = transport(monkeypatch, RESPONSES[method + " " + path], mime="text/plain" if csv else "application/json")
    result = await node({"operation": operation, **config}).execute({})
    assert result["status"] == "success"
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.host == "api.bouncify.io"
    expected_path = path + "/" + JOB if operation in {"get_bulk_job", "start_bulk_job", "delete_bulk_job"} else path
    assert request.url.path == "/v1" + expected_path
    params = {"apikey": TOKEN}
    if operation == "verify_email":
        params.update(email=config["email"], timeout="180000")
    if csv:
        params["jobId"] = JOB
        assert isinstance(result["file"], BinaryOutput)
        assert result["file"].data.decode() == RESPONSES["POST /download"]
        assert json.loads(request.content) == {"filterResult": ["deliverable", "undeliverable", "accept_all", "unknown"]}
    assert dict(request.url.params) == params
    if operation == "create_bulk_job":
        assert json.loads(request.content) == {"emails": config["emails"], "auto_verify": "true"}
    elif operation == "start_bulk_job":
        assert json.loads(request.content) == {"action": "start"}
    elif operation == "delete_bulk_job":
        assert result["deletion_acknowledged"] is True and result["deletion_completed"] is False
    elif not csv:
        assert request.content == b""


@pytest.mark.asyncio
async def test_optional_query_and_download_filter(monkeypatch):
    requests = transport(monkeypatch, RESPONSES["GET /verify"])
    await node({"operation": "verify_email", "email": "plus+tag@example.com", "timeout": 30000}).execute({})
    assert requests[0].url.params["email"] == "plus+tag@example.com"
    assert requests[0].url.params["timeout"] == "30000"
    requests = transport(monkeypatch, RESPONSES["POST /download"], mime="text/csv")
    await node({"operation": "download_bulk_results", "job_id": JOB, "filter_results": ["deliverable"]}).execute({})
    assert json.loads(requests[0].content) == {"filterResult": ["deliverable"]}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 301, 401, 403, 404, 429, 500])
async def test_error_envelope_http_status_and_secret_redaction(monkeypatch, status):
    requests = transport(monkeypatch, {"success": False, "result": "Invalid API Key " + TOKEN}, status=status)
    result = await node({"operation": "get_credit_balance"}).execute({})
    assert result["status"] == "error" and TOKEN not in str(result) and len(requests) == 1
    assert result["error"] == "Invalid API Key [redacted]"


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"success": True}, {"success": True, "credits_info": {"credits_remaining": True}}, {"success": True, "credits_info": None}])
async def test_incomplete_evidence_is_never_success(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError):
        await node({"operation": "get_credit_balance"}).execute({})


@pytest.mark.asyncio
async def test_cross_job_and_download_json_error(monkeypatch):
    transport(monkeypatch, {"success": True, "job_id": "other", "status": "completed"})
    with pytest.raises(ValueError, match="different job"):
        await node({"operation": "get_bulk_job", "job_id": JOB}).execute({})
    transport(monkeypatch, {"success": False, "result": "Job is being verified"})
    result = await node({"operation": "download_bulk_results", "job_id": JOB}).execute({})
    assert result["status"] == "error" and "file" not in result


@pytest.mark.asyncio
async def test_transport_exception_never_exposes_query_credential(monkeypatch):
    transport(monkeypatch, httpx.ConnectError("https://api.bouncify.io/?apikey=" + TOKEN))
    with pytest.raises(ValueError) as exc:
        await node({"operation": "get_credit_balance"}).execute({})
    assert TOKEN not in str(exc.value)


def test_manual_credential_and_validation():
    credential = native.BouncifyAPIKeyCredential(api_key=TOKEN)
    assert credential.credential_type == "bouncify_api_key"
    for config in [
        {"operation": "get_bulk_job", "job_id": "../other"},
        {"operation": "verify_email", "email": "test@example.com", "timeout": 29999},
        {"operation": "create_bulk_job", "emails": []},
        {"operation": "create_bulk_job", "emails": [{"firstname": "John"}]},
        {"operation": "download_bulk_results", "job_id": JOB, "filter_results": ["invalid"]},
    ]:
        with pytest.raises(ValidationError):
            native.BouncifyFullConfig(config=config, credentials=credential)
