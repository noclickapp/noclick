"""Exercise the native AgentMail node against an intercepted HTTP transport."""
import json

import httpx
import pytest

from nodes import agent_mail_node as am
from nodes.core.registry import NodeFactory
from nodes.core.connection_evidence import collect_evidence

AUTH = {"credential_type": "agent_mail_api_key", "api_key": "am_fixture_key_abc123"}


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    native = httpx.AsyncClient

    def send(request):
        requests.append(request)
        assert request.url.host == "api.agentmail.to"
        assert request.headers["Authorization"] == "Bearer " + AUTH["api_key"]
        assert AUTH["api_key"] not in str(request.url)
        code, body = replies.pop(0)
        return httpx.Response(code, content=body) if isinstance(body, bytes) else httpx.Response(code, json=body)

    monkeypatch.setattr(am.httpx, "AsyncClient", lambda **kw: native(**kw, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(operation, **arguments):
    node = NodeFactory.create_node(node_id="agent-mail-test", node_type="automation-agent-mail",
        node_data={"config": {"operation": operation, **arguments}, "credentials": AUTH})
    return await node.execute({})


CASES = [
    ("get_identity", {}, "GET", "/v0/auth/me"),
    ("list_inboxes", {}, "GET", "/v0/inboxes"),
    ("create_inbox", {"username": "support", "display_name": "Support"}, "POST", "/v0/inboxes"),
    ("get_inbox", {}, "GET", "/v0/inboxes/{inbox_id}"),
    ("update_inbox", {"display_name": "Support"}, "PATCH", "/v0/inboxes/{inbox_id}"),
    ("delete_inbox", {}, "DELETE", "/v0/inboxes/{inbox_id}"),
    ("list_threads", {}, "GET", "/v0/inboxes/{inbox_id}/threads"),
    ("get_thread", {}, "GET", "/v0/inboxes/{inbox_id}/threads/{thread_id}"),
    ("update_thread", {"add_labels": ["triaged"]}, "PATCH", "/v0/inboxes/{inbox_id}/threads/{thread_id}"),
    ("delete_thread", {}, "DELETE", "/v0/inboxes/{inbox_id}/threads/{thread_id}"),
    ("list_messages", {}, "GET", "/v0/inboxes/{inbox_id}/messages"),
    ("get_message", {}, "GET", "/v0/inboxes/{inbox_id}/messages/{message_id}"),
    ("update_message", {"remove_labels": ["unread"]}, "PATCH", "/v0/inboxes/{inbox_id}/messages/{message_id}"),
    ("delete_message", {}, "DELETE", "/v0/inboxes/{inbox_id}/messages/{message_id}"),
    ("send_message", {"to": ["human@example.com"], "subject": "Hello", "text": "Hello there"}, "POST", "/v0/inboxes/{inbox_id}/messages/send"),
    ("reply_to_message", {"text": "Thanks!", "reply_all": False}, "POST", "/v0/inboxes/{inbox_id}/messages/{message_id}/reply"),
    ("reply_all_message", {"html": "<p>Thanks!</p>"}, "POST", "/v0/inboxes/{inbox_id}/messages/{message_id}/reply-all"),
    ("forward_message", {"to": ["teammate@example.com"]}, "POST", "/v0/inboxes/{inbox_id}/messages/{message_id}/forward"),
    ("list_drafts", {}, "GET", "/v0/inboxes/{inbox_id}/drafts"),
    ("create_draft", {"to": ["human@example.com"], "text": "Review this"}, "POST", "/v0/inboxes/{inbox_id}/drafts"),
    ("get_draft", {}, "GET", "/v0/inboxes/{inbox_id}/drafts/{draft_id}"),
    ("update_draft", {"to": [], "subject": "Revised"}, "PATCH", "/v0/inboxes/{inbox_id}/drafts/{draft_id}"),
    ("delete_draft", {}, "DELETE", "/v0/inboxes/{inbox_id}/drafts/{draft_id}"),
    ("send_draft", {"add_labels": ["sent-by-agent"]}, "POST", "/v0/inboxes/{inbox_id}/drafts/{draft_id}/send"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,arguments,method,path", CASES)
async def test_native_request_and_response(transport, operation, arguments, method, path):
    requests, replies = transport
    ids = {"inbox_id": "support@agentmail.to", "thread_id": "thread-1", "message_id": "<message@example.com>", "draft_id": "draft-1"}
    config = {**{k: v for k, v in ids.items() if "{" + k + "}" in path}, **arguments}
    payload = {"message_id": "returned-message", "thread_id": "thread-1", "next_page_token": "next-opaque"}
    replies.append((200, b"" if method == "DELETE" else payload))
    result = await run(operation, **config)
    assert result == ({"success": True} if method == "DELETE" else payload)
    assert len(requests) == 1 and not replies
    req = requests[0]
    assert req.method == method and req.url.path == path.format(**ids)
    if method in {"POST", "PATCH"}:
        assert json.loads(req.content) == arguments
    else:
        assert req.content == b""


@pytest.mark.asyncio
async def test_filter_pagination_and_path_encoding(transport):
    requests, replies = transport
    replies.extend([(200, {"messages": [], "count": 0, "next_page_token": "next?&="}), (200, {"message_id": "a/b?#%"})])
    await run("list_messages", inbox_id="support@agentmail.to", limit=5, page_token="next?&=", labels=["unread", "important"], ascending=False, before="2026-10-01T12:00:00Z")
    params = requests[-1].url.params
    assert params["page_token"] == "next?&=" and params["ascending"] == "false"
    assert params.get_list("labels") == ["unread", "important"]
    assert params["before"] == "2026-10-01T12:00:00Z"
    await run("get_message", inbox_id="support@agentmail.to", message_id="a/b?#%")
    assert requests[-1].url.raw_path.endswith(b"/messages/a%2Fb%3F%23%25")


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 401, 403, 404, 429, 500])
async def test_provider_errors_are_not_success_or_retried(transport, status):
    requests, replies = transport
    replies.append((status, {"message": "Provider refuses " + AUTH["api_key"]}))
    with pytest.raises(ValueError) as exc:
        await run("get_identity")
    assert str(status) in str(exc.value) and "Provider refuses" in str(exc.value)
    assert AUTH["api_key"] not in str(exc.value) and len(requests) == 1


@pytest.mark.asyncio
async def test_connection_evidence_for_empty_account(transport):
    requests, replies = transport
    replies.append((200, {"scope_type": "organization", "scope_id": "org-123", "organization_id": "org-123"}))
    result = await collect_evidence(node_type="automation-agent-mail", user_id="fixture-user", pool=None, credential_data=AUTH)
    assert result.reachable is True and result.account_label == "org-123"
    assert [r.url.path for r in requests] == ["/v0/auth/me"]


@pytest.mark.asyncio
async def test_non_object_is_not_success(transport):
    transport[1].append((200, []))
    with pytest.raises(ValueError, match="JSON object"):
        await run("get_identity")
