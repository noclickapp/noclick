"""Smol Machines request mapping and failure semantics through the native factory."""
from copy import deepcopy
from unittest.mock import AsyncMock
import json

import httpx
import pytest
from pydantic import ValidationError

from nodes import smol_machines_node as sm
from nodes.core.run_op import run_node_operation
from nodes.core.credential_connect import shape_credential
from utils import ssrf

TOKEN = "smk_synthetic_not_live_12345"
AUTH = {"credential_type": "smol_machines_api_key", "api_key": TOKEN}
MACHINE = {"id": "m1", "state": "started", "ready": False}
JOB = {"id": "j1", "state": "running"}
GROUP = {"name": "workers", "count": 2}
IDENTITY = {"subject": "key1", "tenantId": "tenant1", "tenantName": "Example", "scopes": ["machine:read"]}

# Expected HTTP routes are independent of the node's dispatch table.
CASES = [
    ("get_identity", {}, "GET", "/v1/me", None, 200, IDENTITY),
    ("list_machines", {"label": ["team=ops", "env=test"]}, "GET", "/v1/machines", None, 200, [MACHINE]),
    ("get_machine", {"machine_id": "m1"}, "GET", "/v1/machines/m1", None, 200, MACHINE),
    ("create_machine", {"source": {"type": "image", "reference": "alpine"}, "resources": {"cpus": 1, "memoryMb": 256}, "ephemeral": False}, "POST", "/v1/machines", {"source": {"type": "image", "reference": "alpine"}, "resources": {"cpus": 1, "memoryMb": 256}, "ephemeral": False}, 201, MACHINE),
    ("delete_machine", {"machine_id": "m1"}, "DELETE", "/v1/machines/m1", None, 204, None),
    ("start_machine", {"machine_id": "m1"}, "POST", "/v1/machines/m1/start", None, 200, MACHINE),
    ("stop_machine", {"machine_id": "m1"}, "POST", "/v1/machines/m1/stop", None, 200, MACHINE),
    ("pause_machine", {"machine_id": "m1"}, "POST", "/v1/machines/m1/pause", None, 200, MACHINE),
    ("resume_machine", {"machine_id": "m1"}, "POST", "/v1/machines/m1/resume", None, 200, MACHINE),
    ("resize_machine", {"machine_id": "m1", "memoryMb": 512}, "POST", "/v1/machines/m1/resize", {"memoryMb": 512}, 200, MACHINE),
    ("execute_command", {"machine_id": "m1", "command": ["sh", "-c", "exit 7"], "stdin": "input", "timeoutSeconds": 0}, "POST", "/v1/machines/m1/exec", {"command": ["sh", "-c", "exit 7"], "stdin": "input", "timeoutSeconds": 0}, 200, {"exitCode": 7, "stdout": "", "stderr": "failed"}),
    ("execute_code", {"machine_id": "m1", "language": "python", "code": "print(1)"}, "POST", "/v1/machines/m1/code", {"language": "python", "code": "print(1)"}, 200, {"exitCode": 0, "stdout": "1\n", "stderr": ""}),
    ("list_machine_events", {"machine_id": "m1"}, "GET", "/v1/machines/m1/events", None, 200, []),
    ("get_machine_usage", {"machine_id": "m1"}, "GET", "/v1/machines/m1/usage", None, 200, {"cpuHours": 1}),
    ("list_jobs", {"machine_id": "m1"}, "GET", "/v1/machines/m1/jobs", None, 200, {"jobs": [JOB]}),
    ("create_job", {"machine_id": "m1", "command": "echo hello", "cwd": "/tmp", "env": {"MODE": "test"}, "user": "1000"}, "POST", "/v1/machines/m1/jobs", {"command": "echo hello", "cwd": "/tmp", "env": {"MODE": "test"}, "user": "1000"}, 202, JOB),
    ("get_job", {"machine_id": "m1", "job_id": "j1"}, "GET", "/v1/machines/m1/jobs/j1", None, 200, JOB),
    ("cancel_job", {"machine_id": "m1", "job_id": "j1"}, "POST", "/v1/machines/m1/jobs/j1/cancel", None, 200, JOB),
    ("get_job_output", {"machine_id": "m1", "job_id": "j1", "stream": "stderr", "offset": 3, "limit": 10}, "GET", "/v1/machines/m1/jobs/j1/output", None, 200, {"data": "hello", "nextOffset": 8, "eof": False}),
    ("list_groups", {}, "GET", "/v1/groups", None, 200, [GROUP]),
    ("get_group", {"group_name": "workers"}, "GET", "/v1/groups/workers", None, 200, GROUP),
    ("scale_group", {"group_name": "workers", "count": 0}, "POST", "/v1/groups/workers/scale", {"count": 0}, 200, {**GROUP, "count": 0}),
]


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def wire(monkeypatch):
    requests, responses = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))
    async def send(req):
        requests.append(req)
        assert req.url.host == "api.smolmachines.com"
        assert req.url.scheme == "https"
        assert req.headers["Authorization"] == "Bearer " + TOKEN
        assert TOKEN not in str(req.url)
        code, body = responses.pop(0)
        if isinstance(body, bytes) or body is None:
            return httpx.Response(code, content=body or b"")
        return httpx.Response(code, json=body)
    native = ssrf.guarded_async_client
    monkeypatch.setattr(sm, "guarded_async_client", lambda **kw: native(**kw, transport=httpx.MockTransport(send)))
    return requests, responses


async def run(operation, arguments):
    return await run_node_operation(node_type=sm.SmolMachinesNode.integration_type,
        operation=operation, arguments=arguments, credential_data=deepcopy(AUTH),
        user_id="00000000-0000-4000-8000-000000000001")


@pytest.mark.parametrize("operation,arguments,method,path,body,status,response", CASES)
@pytest.mark.asyncio
async def test_native_operation(wire, operation, arguments, method, path, body, status, response):
    requests, responses = wire
    responses.append((status, response))
    output = await run(operation, arguments)
    assert output == {"data": response, "http_status": status}
    assert len(requests) == 1
    req = requests[0]
    assert (req.method, req.url.path) == (method, path)
    assert (json.loads(req.content) if req.content else None) == body
    if operation == "list_machines":
        assert req.url.params.get_list("label") == ["team=ops", "env=test"]
    elif operation == "get_job_output":
        assert dict(req.url.params) == {"stream": "stderr", "offset": "3", "limit": "10"}
    else:
        assert not req.url.query


@pytest.mark.parametrize("status", [301, 401, 403, 429, 503])
@pytest.mark.asyncio
async def test_provider_rejection_no_retry_and_redaction(wire, status):
    requests, responses = wire
    responses.append((status, {"code": "machine_interrupted", "detail": "Rejected " + TOKEN}))
    with pytest.raises(ValueError) as exc:
        await run("execute_command", {"machine_id": "m1", "command": "echo hello"})
    assert str(status) in str(exc.value)
    assert "machine_interrupted" in str(exc.value)
    assert TOKEN not in str(exc.value)
    assert len(requests) == 1


@pytest.mark.parametrize("operation,payload", [("get_identity", {}), ("get_identity", []), ("list_machines", {}), ("get_identity", b"<html>login</html>")])
@pytest.mark.asyncio
async def test_unexpected_success_shape_is_not_connection_proof(wire, operation, payload):
    wire[1].append((200, payload))
    with pytest.raises(ValueError):
        await run(operation, {})


@pytest.mark.asyncio
async def test_token_redacted_in_success(wire):
    wire[1].append((200, {**IDENTITY, "tenantName": TOKEN}))
    output = await run("get_identity", {})
    assert TOKEN not in json.dumps(output)


def test_credential_connect_fills_tag_and_only_requires_a_persons_key():
    shaped, errors, resolved = shape_credential("smol_machines_api_key", {"api_key": " " + TOKEN + " "})
    assert errors == {}
    assert shaped["api_key"] == TOKEN
    assert sm.SmolMachinesAPIKeyCredential.model_validate(shaped).credential_type == "smol_machines_api_key"
    assert resolved[0] == "automation-smol-machines"


@pytest.mark.parametrize("field,value", [("machine_id", "../other"), ("machine_id", ".."), ("job_id", "a?x=1"), ("group_name", "a/b")])
def test_resource_paths_cannot_escape(field, value):
    cls = sm.GetGroup if field == "group_name" else sm.GetJob if field == "job_id" else sm.GetMachine
    arguments = {"machine_id": "m1", "job_id": "j1"} if field == "job_id" else {}
    with pytest.raises(ValidationError):
        cls(**{**arguments, field: value})


def test_resize_and_output_bounds():
    with pytest.raises(ValidationError):
        sm.ResizeMachine(machine_id="m1")
    with pytest.raises(ValidationError):
        sm.GetJobOutput(machine_id="m1", job_id="j1", limit=1048577)


def test_saved_canvas_metadata_is_accepted_without_becoming_api_input():
    parsed = sm.SmolMachinesNode.parse_config({
        "credentials": AUTH,
        "config": {"operation": "get_identity", "label": "Saved canvas",
                   "disabled": False, "_settings": {"retryOnFail": False}},
    })
    assert parsed.config.model_dump() == {"operation": "get_identity"}
