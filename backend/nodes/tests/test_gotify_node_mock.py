"""Gotify wire behavior, public-destination protection and scheduled polling."""
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import gotify_node as gotify
from nodes.core.run_op import run_node_operation
from utils import ssrf

AUTH = {"credential_type": "gotify_client_token", "server_url": "https://push.example.de/gotify", "client_token": "Cfixture-not-live"}
MESSAGE = json.loads((Path(__file__).parent / "fixtures/gotify/message.json").read_text())["body"]


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def wire(monkeypatch):
    requests, responses = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))
    async def send(request):
        requests.append(request)
        assert request.url.host == "push.example.de"
        assert request.headers["X-Gotify-Key"] == AUTH["client_token"]
        assert AUTH["client_token"] not in str(request.url)
        status, body = responses.pop(0)
        return httpx.Response(status, content=body) if isinstance(body, bytes) else httpx.Response(status, json=body)
    native = ssrf.guarded_async_client
    monkeypatch.setattr(gotify, "guarded_async_client", lambda **kw: native(**kw, transport=httpx.MockTransport(send)))
    return requests, responses


def page(rows, next_link="", since=0):
    return {"messages": rows, "paging": {"limit": 200, "size": len(rows), "since": since, "next": next_link}}


async def run(operation, arguments=None):
    return await run_node_operation(node_type="automation-gotify", operation=operation, arguments=arguments or {}, credential_data=AUTH, user_id="00000000-0000-4000-8000-000000000001")


# Explicit expected paths catch a wrong route/method or accidental additional request.
CASES = [
    ("send_message", {"appid": 2, "message": "hi", "extras": MESSAGE["extras"]}, "POST", "/message", MESSAGE),
    ("list_messages", {"since": 55, "limit": 10}, "GET", "/message", page([MESSAGE])),
    ("delete_message", {"message_id": 55}, "DELETE", "/message/55", b""),
    ("delete_all_messages", {}, "DELETE", "/message", b""),
    ("list_applications", {}, "GET", "/application", [{"id": 2, "name": "Backup", "token": "hide-existing-token"}]),
    ("create_application", {"name": "Backup", "defaultPriority": 5}, "POST", "/application", {"id": 2, "name": "Backup", "token": "new-app-token"}),
    ("update_application", {"application_id": 2, "name": "Backup"}, "PUT", "/application/2", {"id": 2, "name": "Backup"}),
    ("delete_application", {"application_id": 2}, "DELETE", "/application/2", b""),
    ("remove_application_image", {"application_id": 2}, "DELETE", "/application/2/image", b""),
    ("list_application_messages", {"application_id": 2}, "GET", "/application/2/message", page([MESSAGE])),
    ("delete_application_messages", {"application_id": 2}, "DELETE", "/application/2/message", b""),
    ("list_clients", {}, "GET", "/client", [{"id": 2, "name": "Client", "token": "hide-existing-token"}]),
    ("create_client", {"name": "Client", "expiresAfterInactivitySeconds": 0}, "POST", "/client", {"id": 2, "token": "new-client-token"}),
    ("update_client", {"client_id": 2, "name": "Client"}, "PUT", "/client/2", {"id": 2}),
    ("delete_client", {"client_id": 2}, "DELETE", "/client/2", b""),
    ("list_plugins", {}, "GET", "/plugin", [{"id": 2, "name": "RSS", "token": "hide-existing-token"}]),
    ("get_current_user", {}, "GET", "/current/user", {"id": 2, "name": "admin", "admin": True}),
    ("enable_plugin", {"plugin_id": 2}, "POST", "/plugin/2/enable", b""),
    ("disable_plugin", {"plugin_id": 2}, "POST", "/plugin/2/disable", b""),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,arguments,method,path,response", CASES)
async def test_actions_through_native_factory(wire, operation, arguments, method, path, response):
    requests, responses = wire
    responses.append((200, deepcopy(response)))
    result = await run(operation, arguments)
    assert result["status"] == "success"
    assert len(requests) == 1 and not responses
    req = requests[0]
    assert (req.method, req.url.path) == (method, "/gotify" + path)
    assert "hide-existing-token" not in json.dumps(result)
    if operation in {"send_message", "create_application", "create_client"}:
        assert json.loads(req.content) == arguments
    if operation == "list_messages":
        assert dict(req.url.params) == {"limit": "10", "since": "55"}
    if operation == "create_application":
        assert result["data"]["token"] == "new-app-token"


@pytest.mark.parametrize("url", ["http://push.example.de", "https://user:pass@push.example.de", "https://push.example.de?token=bad", "https://push.example.de/#secret", "https://push.example.de/../other", "https://push.example.de/%2e%2e"])
def test_reject_unsafe_server_values(url):
    with pytest.raises(ValidationError):
        gotify.GotifyClientToken(**{**AUTH, "server_url": url})


def test_hand_connect_defaults_and_paste_cleanup():
    cred = gotify.GotifyClientToken(server_url=" https://PUSH.example.de/gotify/ ", client_token=" Cfixture-not-live\n")
    assert cred.credential_type == "gotify_client_token"
    assert cred.server_url == AUTH["server_url"] and cred.client_token == AUTH["client_token"]


@pytest.mark.parametrize("token", ["https://gotify.net", "<token>", "Bearer secret", "secret\r\ninjected", "clé"])
def test_reject_bad_token(token):
    with pytest.raises(ValidationError):
        gotify.GotifyClientToken(**{**AUTH, "client_token": token})


@pytest.mark.asyncio
async def test_private_server_is_guarded(wire, monkeypatch):
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(side_effect=ssrf.SSRFError("Refusing non-public address 127.0.0.1")))
    with pytest.raises(ValueError, match="could not be completed"):
        await run("list_applications")
    assert wire[0] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 401, 403, 429, 500])
async def test_fail_closed_without_retry_and_redact_errors(wire, status):
    wire[1].append((status, {"errorDescription": "Rejected " + AUTH["client_token"]}))
    with pytest.raises(ValueError, match=f"HTTP {status}") as error:
        await run("send_message", {"appid": 2, "message": "hi"})
    assert AUTH["client_token"] not in str(error.value) and len(wire[0]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [b"<html>login</html>", {"messages": {}, "paging": {}}, {"messages": [{"message": "no id"}], "paging": {}}])
async def test_reject_bad_response_without_advancing_poll(wire, payload):
    wire[1].append((200, payload))
    with pytest.raises(ValueError):
        await run("list_messages")


def poll_node():
    config = gotify.GotifyNode.parse_config({"config": {"operation": "on_new_message"}, "credentials": AUTH})
    return gotify.GotifyNode(node_id="gotify", node_type="automation-gotify", node_data={}, config=config)


def attach_state(node, initial=None):
    state = {} if initial is None else deepcopy(initial)
    async def update(mutator, **kwargs):
        replacement, result = mutator(deepcopy(state))
        if replacement is not None:
            state.clear()
            state.update(replacement)
        return result
    node._update_node_state = update
    return state


@pytest.mark.asyncio
async def test_documented_message_baselines_then_fires_once_and_reaches_agent(wire):
    node = poll_node()
    state = attach_state(node)
    wire[1].append((200, page([MESSAGE])))
    assert (await node.execute({}))["messages"] == []
    assert state["seen_ids"] == ["55"]
    fresh = {**MESSAGE, "id": 56}
    wire[1].append((200, page([fresh, MESSAGE])))
    result = await node.execute({})
    assert result["messages"] == [fresh]
    assert node.trigger_emitted_event(result)
    event = node.resolve_agent_event(result)["text"]
    assert all(text in event for text in ["Application 2", "hi", "2017-01-02", "56"])
    wire[1].append((200, page([fresh, MESSAGE])))
    result = await node.execute({})
    assert node.trigger_produced_no_event(result) and node.resolve_agent_event(result) is None


@pytest.mark.asyncio
async def test_poll_pages_backwards_without_following_response_url(wire):
    node = poll_node()
    attach_state(node, {"seen_ids": []})
    rows = [{**MESSAGE, "id": identifier} for identifier in range(300, 100, -1)]
    wire[1].extend([(200, page(rows, "https://evil.example/message?token=steal", 101)), (200, page([MESSAGE]))])
    result = await node.execute({})
    assert len(result["messages"]) == 201
    assert result["messages"][0]["id"] == 55
    assert dict(wire[0][1].url.params) == {"limit": "200", "since": "101"}


@pytest.mark.asyncio
async def test_nonadvancing_page_does_not_mark_anything_seen(wire):
    node = poll_node()
    state = attach_state(node, {"seen_ids": []})
    rows = [{**MESSAGE, "id": identifier} for identifier in range(300, 100, -1)]
    wire[1].extend([(200, page(rows, "/message?since=101", 101)), (200, page([rows[-1]]))])
    with pytest.raises(ValueError, match="did not advance"):
        await node.execute({})
    assert state == {"seen_ids": []}


@pytest.mark.asyncio
async def test_connection_evidence_shows_account_applications(wire):
    from nodes.core.connection_evidence import collect_evidence
    wire[1].append((200, [{"id": 2, "name": "Backup server"}]))
    evidence = await collect_evidence(node_type="automation-gotify", credential_data=AUTH, user_id="00000000-0000-4000-8000-000000000001")
    assert evidence.reachable is True
    assert "Backup server" in str(evidence)
