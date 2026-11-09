"""Exercise all native operations and account verification through the real factory."""
import json
from pathlib import Path
from unittest.mock import AsyncMock
import httpx
import pytest
from pydantic import ValidationError
from nodes import ezekia_node as ez
from nodes.core.run_op import run_node_operation
from nodes.core.connection_evidence import collect_evidence

TOKEN = "fixture-ezekia-token"
AUTH = {"credential_type": ez.CREDENTIAL_TYPE, "api_token": TOKEN}
USER = "00000000-0000-4000-8000-000000000001"
FIXTURES = json.loads((Path(__file__).parent / "fixtures/ezekia/responses.json").read_text())


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    async def send(request):
        requests.append(request)
        assert request.url.host == "ezekia.com"
        assert request.headers["Authorization"] == "Bearer " + TOKEN
        assert TOKEN not in str(request.url)
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        code, payload = reply
        return httpx.Response(code, json=payload)
    monkeypatch.setattr(ez, "guarded_async_client", lambda **kwargs: httpx.AsyncClient(**kwargs, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(operation, config=None, auth=AUTH):
    return await run_node_operation(node_type="automation-ezekia", operation=operation,
        arguments=config or {}, credential_data=auth, user_id=USER)


CASES = [("get_me", {}, "GET", "/me", None, FIXTURES["me"])]
for kind, plural in (("person", "people"), ("company", "companies"), ("project", "projects")):
    record = FIXTURES[kind]
    CASES.extend([
        ("list_" + plural, {"page": 2, "count": 10, "query": "Jane Doe"}, "GET", "/" + plural,
            {"page": "2", "count": "10", "query": "Jane Doe"}, {"data": [record], "meta": {"current_page": 2}, "links": {"next": "https://evil.test/"}}),
        ("get_" + kind, {kind + "_id": 1234}, "GET", "/" + plural + "/1234", {}, {"data": record}),
    ])
    fields = {"firstName": "Jane", "lastName": "Doe", "companyName": "Amazon", "email": "me@example.com", "phone": "+123 456 789"} if kind == "person" else {"name": "Amazon" if kind == "company" else "Regional Manager"}
    if kind == "project": fields["label"] = "assignment"
    body = dict(fields)
    if kind == "person":
        body["emails"] = [{"address": body.pop("email"), "label": "work", "isDefault": True}]
        body["phones"] = [{"number": body.pop("phone"), "label": "work", "isDefault": True}]
    else: body["_type"] = "info"
    CASES.append(("create_" + kind, fields, "POST", "/" + plural, body, {"data": record}))
    if kind != "person":
        update = {k: v for k, v in fields.items() if k != "label"}
        CASES.append(("update_" + kind, {**update, kind + "_id": 1234}, "PUT", "/" + plural + "/1234", {**update, "_type": "info"}, {"data": record}))
CASES.extend([
    ("list_tasks", {"page": 2, "done": False}, "GET", "/tasks", {"page": "2", "done": "false", "order": "asc", "sort": "start_date_utc"}, {"data": [FIXTURES["task"]]}),
    ("get_task", {"task_id": 1234}, "GET", "/tasks/1234", {}, {"data": [FIXTURES["task"]]}),
    ("set_task_done", {"task_id": 1234, "done": True}, "PUT", "/tasks/1234/done", {"done": True}, {"data": FIXTURES["task"]}),
    ("set_task_pinned", {"task_id": 1234, "pinned": False}, "PUT", "/tasks/1234/pinned", {"pinned": False}, {"data": FIXTURES["task"]}),
    ("delete_task", {"task_id": 1234}, "DELETE", "/tasks/1234", None, {"success": True}),
])


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,method,path,wire,payload", CASES)
async def test_ezekia_documented_request_and_response(transport, operation, config, method, path, wire, payload):
    requests, replies = transport
    replies.append((200, payload))
    result = await run(operation, config)
    assert result["status"] == "success", result
    assert len(requests) == 1 and not replies
    request = requests[0]
    assert (request.method, request.url.path) == (method, "/api/v4" + path)
    if method == "GET": assert dict(request.url.params) == (wire or {})
    elif wire is not None: assert json.loads(request.content) == wire
    else: assert not request.content
    if operation == "get_me": assert result["fullName"] == "John Doe"
    elif operation == "delete_task": assert result["deleted"] is True
    else: assert result["data"] == payload["data"]
    if "meta" in payload: assert result["meta"] == payload["meta"]


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [301, 401, 403, 404, 422, 429, 500])
async def test_ezekia_errors_do_not_retry_writes_or_expose_token(transport, code):
    requests, replies = transport
    replies.append((code, {"message": "Rejected " + TOKEN}))
    result = await run("set_task_done", {"task_id": 1234, "done": True})
    assert result["success"] is False and result["http_status"] == code
    assert TOKEN not in json.dumps(result) and len(requests) == 1
    assert result["error"] == "Rejected [redacted]"


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"errors": ["bad"]}, {"data": "wrong"}, {"success": False}])
async def test_ezekia_unconfirmed_write_is_not_success(transport, payload):
    transport[1].append((200, payload))
    result = await run("set_task_done", {"task_id": 1234, "done": True})
    assert result["success"] is False and result["write_outcome"] == "unverified"


@pytest.mark.asyncio
async def test_ezekia_timeout_keeps_write_outcome_unverified(transport):
    transport[1].append(httpx.ReadTimeout("secret " + TOKEN))
    result = await run("set_task_done", {"task_id": 1234, "done": True})
    assert result["write_outcome"] == "unverified" and TOKEN not in json.dumps(result)
    assert len(transport[0]) == 1


@pytest.mark.parametrize("token", ["", "https://ezekia.com", "Bearer bad", "bad\r\nvalue", "<token>"])
def test_ezekia_manual_credential_rejects_placeholder_and_header(token):
    with pytest.raises((ValidationError, ValueError)):
        ez.EzekiaAPITokenCredential(api_token=token)


def test_ezekia_manual_credential_defaults_type():
    assert ez.EzekiaAPITokenCredential(api_token="  " + TOKEN + "  ").model_dump() == AUTH


@pytest.mark.asyncio
async def test_ezekia_connection_evidence_names_account(transport):
    transport[1].append((200, FIXTURES["me"]))
    result = await collect_evidence(node_type="automation-ezekia", credential_data=AUTH, user_id=USER)
    assert result.reachable is True
    assert "John Doe" in str(result)


@pytest.mark.asyncio
async def test_ezekia_connection_rejection_is_definitive(transport):
    transport[1].append((401, {"message": "Unauthenticated"}))
    result = await collect_evidence(node_type="automation-ezekia", credential_data=AUTH, user_id=USER)
    assert result.reachable is False
    assert "Unauthenticated" in str(result)


def test_ezekia_rejects_path_injection_and_foreign_credentials():
    from nodes.core.registry import NodeFactory
    for data in [
        {"config": {"operation": "get_person", "person_id": "../me"}, "credentials": AUTH},
        {"config": {"operation": "get_me"}, "credentials": {**AUTH, "credential_type": "other_token"}},
    ]:
        with pytest.raises(ValueError):
            NodeFactory.create_node(node_id="invalid", node_type="automation-ezekia", node_data=data)
