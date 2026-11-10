"""Contract request tests and provider response examples; no live account required."""
import json
from copy import deepcopy
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

import nodes.hetzner_node as native
from nodes.core.poll_trigger import poll_scope

TOKEN = "hetzner-test-token-123456789"
EXAMPLES = json.loads((Path(__file__).parent / "fixtures/hetzner/documented_responses.json").read_text())


def node(operation, **fields):
    data = {"config": {"operation": operation, **fields},
        "credentials": {"credential_type": "hetzner_api_token", "api_token": TOKEN}}
    return native.HetznerNode("hetzner-test", native.HetznerNode.integration_type, data,
        native.HetznerNode.parse_config(data), user_id="test-user")


def transport(monkeypatch, handler):
    monkeypatch.setattr(native, "guarded_async_client", lambda **kwargs:
        httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs))


@pytest.mark.asyncio
async def test_project_evidence_exact_bearer_pagination_and_filters(monkeypatch):
    def respond(request):
        assert request.method == "GET"
        assert request.url.host == "api.hetzner.cloud"
        assert request.url.path == "/v1/servers"
        assert request.headers["Authorization"] == "Bearer " + TOKEN
        assert dict(request.url.params) == {"page": "2", "per_page": "50", "sort": "created:desc", "label_selector": "environment=prod"}
        return httpx.Response(200, json={"servers": [EXAMPLES["server"]], "meta": {"pagination": {"next_page": None}}})
    transport(monkeypatch, respond)
    result = await node("list_servers", page=2, per_page=50, sort="created:desc", label_selector="environment=prod").execute({})
    assert result["data"]["servers"][0]["name"] == "my-resource"
    assert native.HetznerNode.connection_evidence.operation == "list_servers"


@pytest.mark.asyncio
async def test_create_server_body_and_async_acknowledgement(monkeypatch):
    def respond(request):
        assert request.method == "POST" and request.url.path == "/v1/servers"
        assert json.loads(request.content) == {"name": "my-server", "server_type": "cpx22", "image": "ubuntu-24.04", "location": "nbg1", "ssh_keys": ["my-ssh-key"], "start_after_create": False}
        return httpx.Response(201, json=EXAMPLES["poweron"])
    transport(monkeypatch, respond)
    result = await node("create_server", name="my-server", server_type="cpx22", image="ubuntu-24.04", location="nbg1", ssh_keys=["my-ssh-key"], start_after_create=False).execute({})
    assert result["data"]["action"]["status"] == "running"


@pytest.mark.asyncio
async def test_volume_attach_uses_current_required_assignee(monkeypatch):
    def respond(request):
        assert request.method == "POST" and request.url.path == "/v1/volumes/554/actions/attach"
        assert json.loads(request.content) == {"assignee": {"id": 43, "type": "server"}, "automount": False}
        return httpx.Response(201, json=EXAMPLES["attach"])
    transport(monkeypatch, respond)
    result = await node("attach_volume", volume_id=554, server_id=43).execute({})
    assert result["data"]["action"]["command"] == "attach_volume"


@pytest.mark.asyncio
async def test_clear_labels_preserves_empty_object(monkeypatch):
    def respond(request):
        assert request.method == "PUT" and request.url.path == "/v1/servers/42"
        assert json.loads(request.content) == {"labels": {}}
        return httpx.Response(200, json={"server": EXAMPLES["server"]})
    transport(monkeypatch, respond)
    await node("update_server", server_id=42, labels={}).execute({})


@pytest.mark.asyncio
async def test_delete_empty_response_and_no_body(monkeypatch):
    def respond(request):
        assert request.method == "DELETE" and request.url.path == "/v1/ssh_keys/42"
        assert not request.content
        return httpx.Response(204)
    transport(monkeypatch, respond)
    assert (await node("delete_ssh_key", ssh_key_id=42).execute({}))["data"] == {}


@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
@pytest.mark.asyncio
async def test_rejections_no_retry_no_redirect_and_redaction(monkeypatch, status):
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(status, json={"error": {"message": "denied " + TOKEN}}, headers={"Location": "https://example.com"})
    transport(monkeypatch, respond)
    with pytest.raises(ValueError, match=f"HTTP {status}") as error:
        await node("list_servers").execute({})
    assert TOKEN not in str(error.value)
    assert len(calls) == 1


@pytest.mark.parametrize("operation,fields", [
    ("get_server", {"server_id": "../../account"}),
    ("get_server", {"server_id": 0}),
    ("get_server", {"server_id": 9007199254740992}),
    ("list_servers", {"per_page": 51}),
    ("update_server", {"server_id": 42}),
    ("create_ssh_key", {"name": "private", "public_key": "-----BEGIN PRIVATE KEY-----"}),
])
def test_invalid_config_cannot_reach_network(operation, fields):
    with pytest.raises((ValidationError, ValueError)):
        node(operation, **fields)


@pytest.mark.asyncio
async def test_poll_paginates_baselines_deduplicates_and_emits_agent_event(monkeypatch):
    first = deepcopy(EXAMPLES["server"])
    second = {**first, "id": 43, "name": "new-server"}
    rows = [first]
    calls = []
    def respond(request):
        calls.append(request)
        assert request.url.params["sort"] == "created:desc"
        assert request.url.params["label_selector"] == "environment=prod"
        page = int(request.url.params["page"])
        return httpx.Response(200, json={"servers": rows[page-1:page], "meta": {"pagination": {"next_page": page+1 if page < len(rows) else None}}})
    transport(monkeypatch, respond)
    n = node("on_new_server", label_selector="environment=prod")
    state = {}
    async def update(mutator, **kwargs):
        changed, result = mutator(dict(state))
        if changed is not None:
            state.clear(); state.update(changed)
        return result
    n._update_node_state = update
    assert (await n.execute({}))["new_server_count"] == 0
    rows.extend([second, second])
    output = await n.execute({})
    assert output["servers"] == [second]
    assert native.HetznerNode.should_propagate_output(output, {"operation": "on_new_server"})
    assert "new-server (server 43)" in native.HetznerNode.resolve_agent_event(output)["text"]
    assert (await n.execute({}))["new_server_count"] == 0
    assert native.HetznerNode.resolve_agent_event({"servers": [], "new_server_count": 0}) is None
    assert len(calls) == 7
    assert poll_scope(native.HetznerNode, {"operation": "on_new_server", "label_selector": "environment=prod"}) != poll_scope(native.HetznerNode, {"operation": "on_new_server", "label_selector": "environment=dev"})


@pytest.mark.asyncio
async def test_poll_repeated_page_does_not_consume_seen_state(monkeypatch):
    transport(monkeypatch, lambda request: httpx.Response(200, json={"servers": [EXAMPLES["server"]], "meta": {"pagination": {"next_page": 1}}}))
    n = node("on_new_server")
    with pytest.raises(ValueError, match="pagination did not advance"):
        await n.execute({})
