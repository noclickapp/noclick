"""Inbound WhatsApp media rehosting.

Provider media URLs require service credentials and are not safe to expose to
an agent. transform_trigger_payload eagerly rehosts the bytes to workflow
resources at delivery time, and resolve_agent_event hands the agent a fetchable
capability URL.
"""

import os
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest

from nodes.core.base import WorkflowNode
from nodes.whatsapp_node import WhatsAppNode
from utils.ssrf import SSRFError

WA_CFG = {"operation": "receive_message"}


def _media_payload(url="https://api.wahooks.com/api/connections/c1/media/f1.jpg", **media_extra):
    return {
        "event": "message",
        "session": "u_x_s_y",
        "payload": {
            "id": "msg-1",
            "from": "123@c.us",
            "fromMe": False,
            "body": "look at this",
            "hasMedia": True,
            "media": {"url": url, "mimetype": "image/jpeg", "filename": "f1.jpg", **media_extra},
        },
    }


class _FakeStreamResponse:
    def __init__(self, chunks):
        self._chunks = chunks
        self.headers = {"content-type": "image/jpeg"}

    def raise_for_status(self):
        pass

    async def aiter_bytes(self):
        for c in self._chunks:
            yield c

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _FakeClient:
    def __init__(self, chunks):
        self._chunks = chunks
        self.requests = []

    def __call__(self, timeout=None):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def stream(self, method, url, headers=None):
        self.requests.append((method, url, headers))
        return _FakeStreamResponse(self._chunks)


def _pool(owner="0b129266-59d2-4ab8-9e19-6e6342d67270"):
    pool = MagicMock()
    pool.fetchrow = AsyncMock(return_value={"owner_id": owner, "organization_id": None})
    return pool


@pytest.mark.asyncio
async def test_media_rehosted_and_url_swapped(monkeypatch):
    monkeypatch.setenv("WAHOOKS_API_KEY", "platform-key")
    payload = _media_payload()
    client = _FakeClient(chunks=[b"jpeg-bytes"])
    store = AsyncMock(return_value={
        "resource_id": "res-1", "name": "f1.jpg", "mime_type": "image/jpeg",
        "size_bytes": 10, "storage_ref": "o/w/res-1/f1.jpg",
        "download_url": "https://assets.example.test/o/w/res-1/f1.jpg",
    })
    with patch("nodes.whatsapp_node.guarded_async_client", client), \
         patch("utils.resource_store.create_resource_from_bytes", store):
        out = await WhatsAppNode.transform_trigger_payload(
            payload, WA_CFG, pool=_pool(), workflow_id="wf-1", node_id="wa-1",
        )

    assert out is payload
    media = out["payload"]["media"]
    assert media["url"] == "https://assets.example.test/o/w/res-1/f1.jpg"
    assert media["rehosted"] is True
    assert media["resource_id"] == "res-1"
    # The platform key authenticated the fetch but never leaks into the payload.
    method, url, headers = client.requests[0]
    assert headers["Authorization"] == "Bearer platform-key"
    assert "platform-key" not in str(out)
    store.assert_awaited_once_with(
        user_id="0b129266-59d2-4ab8-9e19-6e6342d67270", workflow_id="wf-1",
        node_id="wa-1", organization_id=None, body=b"jpeg-bytes",
        content_type="image/jpeg", filename="f1.jpg",
        metadata={"source": "whatsapp_inbound_media"},
    )


@pytest.mark.asyncio
async def test_non_media_and_non_message_untouched(monkeypatch):
    monkeypatch.setenv("WAHOOKS_API_KEY", "k")
    no_media = {"event": "message", "session": "s", "payload": {"from": "1@c.us", "body": "hi"}}
    assert await WhatsAppNode.transform_trigger_payload(
        no_media, WA_CFG, pool=_pool(), workflow_id="wf-1", node_id="n",
    ) is None
    status = {"event": "session.status", "session": "s", "payload": {"status": "WORKING"}}
    assert await WhatsAppNode.transform_trigger_payload(
        status, WA_CFG, pool=_pool(), workflow_id="wf-1", node_id="n",
    ) is None


@pytest.mark.asyncio
async def test_oversized_media_not_rehosted(monkeypatch):
    monkeypatch.setenv("WAHOOKS_API_KEY", "k")
    huge = _FakeClient(chunks=[b"x" * (WhatsAppNode.MEDIA_REHOST_MAX_BYTES + 1)])
    with patch("nodes.whatsapp_node.guarded_async_client", huge):
        out = await WhatsAppNode.transform_trigger_payload(
            _media_payload(), WA_CFG, pool=_pool(), workflow_id="wf-1", node_id="n",
        )
    assert out is None  # delivery proceeds with the original payload


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data",
        "https://api.wahooks.com.attacker.example/steal",
        "https://attacker.example/steal",
    ],
)
async def test_media_url_cannot_redirect_shared_bearer_to_untrusted_origin(
    monkeypatch, url
):
    monkeypatch.setenv("WAHOOKS_API_KEY", "platform-key")
    pool = _pool()

    with pytest.raises(SSRFError, match="outside"):
        await WhatsAppNode.transform_trigger_payload(
            _media_payload(url=url),
            WA_CFG,
            pool=pool,
            workflow_id="wf-1",
            node_id="wa-1",
        )

    pool.fetchrow.assert_not_awaited()


# ── agent-facing rendering ──────────────────────────────────────────────────


def test_agent_event_renders_rehosted_media():
    payload = _media_payload(rehosted=True)
    payload["payload"]["media"]["url"] = "https://assets.example.test/o/w/r/f1.jpg"
    event = WhatsAppNode.resolve_agent_event(payload)
    assert "look at this" in event["text"]  # caption preserved
    assert "https://assets.example.test/o/w/r/f1.jpg" in event["text"]
    assert "image/jpeg" in event["text"]
    assert "curl" in event["text"]
    assert event["conversation_key"] == "123@c.us"


def test_agent_event_honest_when_media_not_retrieved():
    payload = _media_payload()  # rehosted flag absent — provider URL is useless
    event = WhatsAppNode.resolve_agent_event(payload)
    assert "could not be retrieved" in event["text"]
    assert "wahooks.com" not in event["text"]  # never dangle the authed URL


def test_agent_event_media_without_caption():
    payload = _media_payload(rehosted=True)
    payload["payload"]["body"] = None
    event = WhatsAppNode.resolve_agent_event(payload)
    assert "[media message]" in event["text"]


# ── delivery-seam contract ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_seam_base_hook_costs_nothing_and_failures_keep_original():
    from utils.webhook_routes import _transform_trigger_payload

    # Base no-op class: fast path, no pool resolution.
    class PlainNode(WorkflowNode):
        pass

    node = {"id": "n1", "type": "automation-x", "config": {}}
    payload = {"a": 1}
    with patch("utils.webhook_routes.get_native_pool", side_effect=AssertionError("must not resolve pool")):
        assert await _transform_trigger_payload(PlainNode, node, payload, "wf") is payload

    # Overriding class that raises: original payload stands, nothing re-injected.
    class ExplodingNode(WorkflowNode):
        @classmethod
        async def transform_trigger_payload(cls, payload, config, *, pool, workflow_id, node_id):
            raise RuntimeError("boom")

    with patch("utils.webhook_routes.get_native_pool", return_value=MagicMock()):
        assert await _transform_trigger_payload(ExplodingNode, node, payload, "wf") is payload
    assert "_triggerPayload" not in node["config"]

    # Overriding class that transforms: result re-injected as _triggerPayload.
    class RewritingNode(WorkflowNode):
        @classmethod
        async def transform_trigger_payload(cls, payload, config, *, pool, workflow_id, node_id):
            return {**payload, "rewritten": True}

    with patch("utils.webhook_routes.get_native_pool", return_value=MagicMock()):
        out = await _transform_trigger_payload(RewritingNode, node, payload, "wf")
    assert out["rewritten"] is True
    assert node["config"]["_triggerPayload"] is out
