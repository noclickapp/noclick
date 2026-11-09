"""Exercise Cloze through the native factory with fixture-only HTTP.

Account examples are copied from the pinned provider OpenAPI contract; writes
also verify exact request shape and that failures cannot become successes.
"""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import cloze_node as cloze
from nodes.core.registry import NodeFactory
from utils import ssrf

AUTH = {"credential_type": "cloze_api_key", "api_key": "cloze-unit-test-secret"}
DOCS = json.loads((Path(__file__).parent / "fixtures/cloze/documented_responses.json").read_text())


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def wire(monkeypatch):
    requests, responses = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))
    async def send(request):
        requests.append(request)
        assert request.url.host == "api.cloze.com"
        assert request.headers["Authorization"] == "Bearer " + AUTH["api_key"]
        assert AUTH["api_key"] not in str(request.url)
        code, body = responses.pop(0)
        return httpx.Response(code, json=body)
    native = ssrf.guarded_async_client
    monkeypatch.setattr(cloze, "guarded_async_client", lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)))
    return requests, responses


async def run(config):
    node = NodeFactory.create_node(node_id="cloze-test", node_type="automation-cloze",
        node_data={"config": config, "credentials": AUTH})
    return await node.execute({})


CASES = [
    ("list_people", "GET", "/v1/people/feed", {'freeformquery': 'Lucy', 'cursor': 'returned-cursor'}),
    ("get_person", "GET", "/v1/people/get", {'id': 'abc:123', 'team': True}),
    ("create_person", "POST", "/v1/people/create", {'name': 'Lucy Gregorian'}),
    ("update_person", "POST", "/v1/people/update", {'syncKey': 'abc123', 'notes': 'Follow up'}),
    ("delete_person", "DELETE", "/v1/people/delete", {'id': 'abc:123'}),
    ("list_companies", "GET", "/v1/companies/feed", {'freeformquery': 'Lucy', 'cursor': 'returned-cursor'}),
    ("get_company", "GET", "/v1/companies/get", {'id': 'abc:123', 'team': True}),
    ("create_company", "POST", "/v1/companies/create", {'name': 'Lucy Gregorian'}),
    ("update_company", "POST", "/v1/companies/update", {'syncKey': 'abc123', 'notes': 'Follow up'}),
    ("delete_company", "DELETE", "/v1/companies/delete", {'id': 'abc:123'}),
    ("list_projects", "GET", "/v1/projects/feed", {'freeformquery': 'Lucy', 'cursor': 'returned-cursor'}),
    ("get_project", "GET", "/v1/projects/get", {'id': 'abc:123', 'team': True}),
    ("create_project", "POST", "/v1/projects/create", {'name': 'Lucy Gregorian'}),
    ("update_project", "POST", "/v1/projects/update", {'syncKey': 'abc123', 'notes': 'Follow up'}),
    ("delete_project", "DELETE", "/v1/projects/delete", {'id': 'abc:123'}),
    ("get_profile", "GET", "/v1/user/profile", {}),
    ("get_tags", "GET", "/v1/user/keywords", {}),
    ("get_custom_fields", "GET", "/v1/user/fields", {}),
    ("get_steps", "GET", "/v1/user/steps", {}),
    ("create_todo", "POST", "/v1/timeline/todo/create", {"subject": "Call Lucy", "when": "2026-12-01T12:00:00Z"}),
    ("create_note", "POST", "/v1/timeline/content/create", {"uniqueid": "note-1", "source": "example.org", "subject": "Meeting", "body": "Discussed terms"}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,method,path,args", CASES)
async def test_cloze_operation_wire_contract(wire, operation, method, path, args):
    requests, responses = wire
    responses.append((200, DOCS["profile"] if operation == "get_profile" else {"errorcode": 0}))
    result = await run({"operation": operation, **args})
    assert result["status"] == "success"
    assert len(requests) == 1 and not responses
    request = requests[0]
    assert (request.method, request.url.path) == (method, path)
    payload = json.loads(request.content) if method == "POST" else dict(request.url.params)
    for key, value in args.items():
        assert payload[key] == (str(value).lower() if method != "POST" and isinstance(value, bool) else str(value) if method != "POST" else value)
    if operation.startswith("update_"):
        assert payload == {"syncKey": "abc123", "notes": "Follow up", "dryrun": False}
    if operation == "create_note":
        assert payload["style"] == "note" and payload["bodytype"] == "text"
    assert "operation" not in payload and "api_key" not in payload


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,fixture", [("get_profile", "profile"), ("get_tags", "tags"), ("get_custom_fields", "fields"), ("get_steps", "steps")])
async def test_cloze_documented_responses(wire, operation, fixture):
    wire[1].append((200, DOCS[fixture]))
    assert await run({"operation": operation}) == {**DOCS[fixture], "status": "success"}


@pytest.mark.asyncio
@pytest.mark.parametrize("code,body", [(200, {"errorcode": 1, "message": "Permission denied"}), (401, {"errorcode": 401, "message": "Invalid API key"}), (429, {"errorcode": 429, "message": "Rate limit exceeded"}), (200, {}), (200, []), (200, {"errorcode": False}), (200, {"errorcode": 0})])
async def test_cloze_rejections_and_invalid_envelopes(wire, code, body):
    wire[1].append((code, body))
    result = await run({"operation": "get_profile"})
    assert result["status"] == "error"
    assert len(wire[0]) == 1
    if code >= 400:
        assert result["status_code"] == code
    if isinstance(body, dict) and body.get("message"):
        assert result["error"] == body["message"]


@pytest.mark.asyncio
async def test_cloze_redacts_echoed_secrets(wire):
    wire[1].append((200, {"errorcode": 1, "message": "Rejected " + AUTH["api_key"]}))
    assert AUTH["api_key"] not in json.dumps(await run({"operation": "get_profile"}))


@pytest.mark.parametrize("key", ["", "https://example.org/key", "<token>", "Bearer token with spaces", "abc\nxyz"])
def test_cloze_invalid_manual_keys(key):
    with pytest.raises(ValidationError):
        cloze.ClozeAPIKeyCredential(api_key=key)


def test_cloze_manual_credential_default_and_evidence():
    credential = cloze.ClozeAPIKeyCredential(api_key=AUTH["api_key"])
    assert credential.credential_type == "cloze_api_key"
    assert cloze.ClozeNode.connection_evidence.identity_operation == "get_profile"
    assert cloze.ClozeFullConfig(config={"operation": "get_profile"}, credentials=credential).credentials == credential
