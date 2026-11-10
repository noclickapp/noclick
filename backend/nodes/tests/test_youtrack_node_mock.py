"""YouTrack transport, manual connection, pagination and poll regressions.

Provider examples are cited in fixtures; other responses are synthetic. No
provider account or token is used by this suite.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import youtrack_node as native
from nodes.core.poll_trigger import poll_scope
from nodes.core.registry import NodeFactory

TOKEN = "perm:synthetic-token-for-unit-tests"
CREDENTIAL = {"credential_type": "youtrack_token", "server_url": "https://example.youtrack.cloud", "api_token": TOKEN}
EXAMPLES = json.loads((Path(__file__).parent / "fixtures/youtrack/provider_examples.json").read_text())


def node(operation, **values):
    return NodeFactory.create_node(node_id="youtrack-test", node_type="automation-youtrack",
        node_data={"config": {"operation": operation, **values}, "credentials": CREDENTIAL})


def transport(monkeypatch, reply):
    requests = []
    def handle(request):
        requests.append(request)
        return reply(request) if callable(reply) else httpx.Response(200, json=reply)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handle), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,method,path,body", [
    ("create_issue", {"summary": "Houston!", "description": "We have a problem!", "project_id": "0-0"}, "POST", "/issues", EXAMPLES["create_issue"]["request"]),
    ("update_issue", {"issue_id": "SP-39", "summary": "Resolved", "clear_description": True}, "POST", "/issues/SP-39", {"summary": "Resolved", "description": ""}),
    ("apply_command", {"issue_id": "2-15", "command": "for me ", "comment": "Still cannot reproduce."}, "POST", "/commands", {"query": "for me ", "issues": [{"id": "2-15"}], "comment": "Still cannot reproduce."}),
    ("apply_command", {"issue_id": "SP-17", "command": "Fixed"}, "POST", "/commands", {"query": "Fixed", "issues": [{"idReadable": "SP-17"}]}),
    ("add_comment", {"issue_id": "SP-39", "text": "Fixed in production"}, "POST", "/issues/SP-39/comments", {"text": "Fixed in production"}),
    ("update_comment", {"issue_id": "SP-39", "comment_id": "4-7", "text": "Confirmed"}, "POST", "/issues/SP-39/comments/4-7", {"text": "Confirmed"}),
    ("create_tag", {"name": "urgent"}, "POST", "/tags", {"name": "urgent"}),
    ("add_issue_tag", {"issue_id": "NP-12", "tag_id": "146-25"}, "POST", "/issues/NP-12/tags", EXAMPLES["add_tag"]["request"]),
    ("delete_issue", {"issue_id": "SP-39"}, "DELETE", "/issues/SP-39", None),
    ("delete_comment", {"issue_id": "SP-39", "comment_id": "4-7"}, "DELETE", "/issues/SP-39/comments/4-7", None),
    ("remove_issue_tag", {"issue_id": "SP-39", "tag_id": "146-25"}, "DELETE", "/issues/SP-39/tags/146-25", None),
])
async def test_writes_use_documented_method_path_and_body(monkeypatch, operation, config, method, path, body):
    requests = transport(monkeypatch, lambda r: httpx.Response(200) if method == "DELETE" else httpx.Response(200, json={"id": "result"}))
    out = await node(operation, **config).execute({})
    request = requests[0]
    assert request.method == method and request.url.path == "/api" + path
    assert request.headers["authorization"] == "Bearer " + TOKEN
    assert (json.loads(request.content) if request.content else None) == body
    assert out == ({"deleted": True} if method == "DELETE" else {"data": {"id": "result"}})


@pytest.mark.asyncio
async def test_documented_issue_response_and_explicit_pagination(monkeypatch):
    requests = transport(monkeypatch, EXAMPLES["issue_list"]["body"])
    out = await node("list_issues", query="for: me #Unresolved", offset=20, limit=2).execute({})
    assert out["data"] == EXAMPLES["issue_list"]["body"] and out["next_offset"] == 22
    params = requests[0].url.params
    assert params["$skip"] == "20" and params["$top"] == "2" and params["query"] == "for: me #Unresolved"
    assert params["fields"] == native.ISSUE_FIELDS
    transport(monkeypatch, [])
    assert (await node("list_issues").execute({}))["next_offset"] is None


@pytest.mark.asyncio
async def test_provider_examples_parse_and_identity_fallback(monkeypatch):
    transport(monkeypatch, EXAMPLES["create_issue"]["body"])
    assert (await node("create_issue", summary="Houston!", project_id="0-0").execute({}))["data"]["idReadable"] == "SP-39"
    transport(monkeypatch, EXAMPLES["add_tag"]["body"])
    assert (await node("add_issue_tag", issue_id="NP-12", tag_id="146-25").execute({}))["data"]["name"] == "productivity"
    transport(monkeypatch, {"id": "1-1", "login": "root", "fullName": "Example User"})
    assert (await node("get_current_user").execute({}))["data"]["login"] == "root"
    assert native.YouTrackNode.connection_evidence.operation == "list_projects"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 302, 401, 403, 404, 429, 500])
async def test_errors_and_redirects_refused_and_tokens_redacted(monkeypatch, status):
    requests = transport(monkeypatch, lambda r: httpx.Response(status, json={"error_description": "Rejected " + TOKEN}, headers={"Location": "https://other.test/"}))
    with pytest.raises(ValueError) as error:
        await node("get_current_user").execute({})
    assert str(status) in str(error.value) and TOKEN not in str(error.value) and len(requests) == 1


@pytest.mark.asyncio
async def test_context_path_and_path_identifier_encoding(monkeypatch):
    requests = transport(monkeypatch, {"id": "2-1"})
    test_node = node("get_issue", issue_id="SP-1/a?b#c")
    test_node.config.credentials.server_url = "https://example.youtrack.cloud/youtrack"
    await test_node.execute({})
    assert requests[0].url.raw_path.startswith(b"/youtrack/api/issues/SP-1%2Fa%3Fb%23c?")
    assert requests[0].url.host == "example.youtrack.cloud"


def test_manual_credential_url_shaping_and_required_fields():
    shaped = native.YouTrackTokenCredential(server_url="https://Example.YouTrack.Cloud/youtrack/api/", api_token="  " + TOKEN + " ")
    assert shaped.credential_type == "youtrack_token" and shaped.server_url == "https://example.youtrack.cloud/youtrack"
    assert shaped.api_token == TOKEN
    for url in ["http://example.youtrack.cloud", "https://user:pass@example.youtrack.cloud", "https://example.youtrack.cloud?x=y", "https://example.youtrack.cloud/../evil"]:
        with pytest.raises((ValueError, ValidationError)):
            native.YouTrackTokenCredential(server_url=url, api_token=TOKEN)
    with pytest.raises(ValidationError):
        native.YouTrackTokenCredential(server_url="https://example.youtrack.cloud", api_token="https://example.com/token")


@pytest.mark.asyncio
async def test_poll_baseline_updates_paging_and_agent_event(monkeypatch):
    # Shape and timestamps follow the published Issue schema. Synthetic values
    # let the regression exercise an actual update rather than an invented event.
    row = {"id": "2-42", "idReadable": "SP-38", "summary": "Sprint 3. Task 2", "description": "A new update", "created": 1700000000000,
           "updated": 1700000001000, "reporter": {"login": "root"}, "updater": {"login": "jane.doe"}, "project": {"id": "0-0", "name": "Sample Project"}}
    response = [row]
    requests = transport(monkeypatch, lambda r: httpx.Response(200, json=response))
    test_node = node("on_issue_changed", query="project: SP")
    state = {}
    async def update(mutator, **kwargs):
        new, result = mutator(state)
        if new is not None:
            state.update(new)
        return result
    test_node._update_node_state = update
    assert (await test_node.execute({}))["issue_count"] == 0
    assert test_node.trigger_produced_no_event({})
    assert (await test_node.execute({}))["issue_count"] == 0
    row["updated"] += 1
    out = await test_node.execute({})
    assert out["issue_count"] == 1 and test_node.trigger_emitted_event(out)
    text = native.YouTrackNode.resolve_agent_event(out)["text"]
    assert all(value in text for value in ("jane.doe", "SP-38", "Sample Project", "Sprint 3. Task 2", "A new update", "2-42", "0-0"))
    assert (await test_node.execute({}))["issue_count"] == 0
    assert requests[0].url.params["query"] == "project: SP"
    assert poll_scope(native.YouTrackNode, {"operation": "on_issue_changed", "query": "project: SP"}) != poll_scope(native.YouTrackNode, {"operation": "on_issue_changed", "query": "project: OTHER"})
    # No state change after a malformed read.
    before = state.copy()
    response[:] = [{"id": "2-42"}]
    with pytest.raises(ValueError, match="timestamp"):
        await test_node.execute({})
    assert state == before


@pytest.mark.asyncio
async def test_poll_reads_all_pages_before_dedup_and_fails_closed_on_overflow(monkeypatch):
    calls = []
    async def request(credential, method, path, *, params, body=None):
        calls.append(params["$skip"])
        return [{"id": str(params["$skip"] + n), "updated": 1} for n in range(100)] if params["$skip"] == 0 else []
    monkeypatch.setattr(native.YouTrackNode, "_request", staticmethod(request))
    test_node = node("on_issue_changed")
    async def unseen(items, id_fn):
        assert len(items) == 100
        return items
    test_node._filter_unseen = unseen
    assert (await test_node.execute({}))["issue_count"] == 100 and calls == [0, 100]
    async def huge(*args, **kwargs):
        return [{"id": str(n), "updated": 1} for n in range(100)]
    monkeypatch.setattr(native.YouTrackNode, "_request", staticmethod(huge))
    with pytest.raises(ValueError, match="narrow"):
        await test_node.execute({})
