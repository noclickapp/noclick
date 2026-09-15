"""Slack shared files reach the agent digest.

Slack's file URLs are private (they need the workspace bot token), and Slack
triggers fire through the app-event fan-out, which had no delivery-time
transform. Now ``_fire_subscription`` runs the node class's
``transform_trigger_payload`` after every filter, and ``SlackNode``'s
implementation rehosts the message's files with the node's credential
through the shared ``utils.inbound_media`` seam — copying the envelope first,
because the fan-out hands every subscribed workflow the same payload object
and a capability URL minted for one owner must not reach another's run.
``resolve_agent_event`` then names the rehosted file with its URL and hands
the digest a media entry.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nodes.slack_node import SlackNode
from utils.ssrf import SSRFError

SLACK_CFG = {"operation": "on_channel_message", "credentialIds": {"slack_oauth": "cred-1"}}
TOKEN = "xoxb-secret-token"


def _file(n=1, url="https://files.slack.com/files-pri/T1-F1/download/memo.m4a", **extra):
    return {
        "id": f"F{n}", "name": "memo.m4a", "title": "memo", "mimetype": "audio/mp4",
        "filetype": "m4a", "size": 9000, "url_private": url.replace("/download", ""),
        "url_private_download": url, **extra,
    }


def _envelope(files, subtype="file_share"):
    return {
        "type": "event_callback", "team_id": "T1", "api_app_id": "A1",
        "event": {"type": "message", "subtype": subtype, "user": "U1", "channel": "C1",
                  "text": "here", "ts": "4.4", "files": files},
    }


class _FakeStreamResponse:
    def __init__(self, chunks):
        self._chunks = chunks
        self.headers = {"content-type": "audio/mp4"}

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

    def __call__(self, timeout=None, **kwargs):
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


def _store(n):
    return {
        "resource_id": f"res-{n}", "name": "memo.m4a", "mime_type": "audio/mp4", "size_bytes": 9,
        "storage_ref": f"o/w/res-{n}/memo.m4a", "download_url": f"https://assets.example.test/o/w/res-{n}/memo.m4a",
    }


# ── transform ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_files_rehosted_on_a_copy_with_the_bot_token_that_never_rides_the_payload():
    payload = _envelope([_file()])
    client = _FakeClient(chunks=[b"m4a-bytes"])
    store = AsyncMock(return_value=_store(1))
    with patch("nodes.slack_node.SlackNode._delivery_bot_token", AsyncMock(return_value=TOKEN)), \
         patch("utils.inbound_media.guarded_async_client", client), \
         patch("utils.resource_store.create_resource_from_bytes", store):
        out = await SlackNode.transform_trigger_payload(
            payload, SLACK_CFG, pool=_pool(), workflow_id="wf-1", node_id="slack-1",
        )

    assert out is not payload and "media" not in payload["event"]["files"][0]  # the shared object stays clean
    media = out["event"]["files"][0]["media"]
    assert media["url"] == "https://assets.example.test/o/w/res-1/memo.m4a"
    assert media["rehosted"] is True and media["resource_id"] == "res-1"
    _, url, headers = client.requests[0]
    assert url == "https://files.slack.com/files-pri/T1-F1/download/memo.m4a"
    assert headers["Authorization"] == f"Bearer {TOKEN}"
    assert TOKEN not in str(out)
    store.assert_awaited_once_with(
        user_id="0b129266-59d2-4ab8-9e19-6e6342d67270", workflow_id="wf-1", node_id="slack-1",
        organization_id=None, body=b"m4a-bytes", content_type="audio/mp4", filename="memo.m4a",
        metadata={"source": "slack_inbound_media"},
    )


@pytest.mark.asyncio
async def test_bot_token_only_goes_to_slacks_file_host():
    pool = _pool()
    store = AsyncMock()
    with patch("nodes.slack_node.SlackNode._delivery_bot_token", AsyncMock(return_value=TOKEN)), \
         patch("utils.resource_store.create_resource_from_bytes", store):
        with pytest.raises(SSRFError, match="outside"):
            await SlackNode.transform_trigger_payload(
                _envelope([_file(url="https://files.slack.com.attacker.example/steal")]),
                SLACK_CFG, pool=pool, workflow_id="wf-1", node_id="n",
            )
    store.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_files_or_no_credential_leaves_the_delivery_untouched():
    token = AsyncMock(return_value=None)
    with patch("nodes.slack_node.SlackNode._delivery_bot_token", token):
        assert await SlackNode.transform_trigger_payload(
            _envelope([], subtype=None), SLACK_CFG, pool=_pool(), workflow_id="wf-1", node_id="n",
        ) is None
        token.assert_not_awaited()
        assert await SlackNode.transform_trigger_payload(
            _envelope([_file()]), SLACK_CFG, pool=_pool(), workflow_id="wf-1", node_id="n",
        ) is None
        token.assert_awaited_once()


@pytest.mark.asyncio
async def test_at_most_three_files_are_rehosted():
    files = [_file(n, url=f"https://files.slack.com/files-pri/T1-F{n}/download/memo.m4a") for n in range(1, 6)]
    client = _FakeClient(chunks=[b"x"])
    store = AsyncMock(side_effect=[_store(n) for n in range(1, 6)])
    with patch("nodes.slack_node.SlackNode._delivery_bot_token", AsyncMock(return_value=TOKEN)), \
         patch("utils.inbound_media.guarded_async_client", client), \
         patch("utils.resource_store.create_resource_from_bytes", store):
        out = await SlackNode.transform_trigger_payload(
            _envelope(files), SLACK_CFG, pool=_pool(), workflow_id="wf-1", node_id="n",
        )
    assert [("media" in f) for f in out["event"]["files"]] == [True, True, True, False, False]
    assert store.await_count == SlackNode.MEDIA_REHOST_MAX_FILES


@pytest.mark.asyncio
async def test_delivery_token_manual_credential_and_oauth_chain():
    pool = _pool()
    manual = AsyncMock(return_value=({"credential_type": "slack_bot_token", "bot_token": "xoxb-manual"}, "owner-1"))
    with patch("utils.inbound_media.resolve_delivery_credential", manual):
        assert await SlackNode._delivery_bot_token(SLACK_CFG, pool, "wf-1") == "xoxb-manual"
    manual.assert_awaited_once_with(pool, SLACK_CFG, "wf-1", "slack_oauth", "slack_bot_token")

    oauth = {"credential_type": "slack_oauth", "access_token": "stale", "refresh_token": "r", "team_id": "T1"}
    fresh = AsyncMock(return_value="xoxb-fresh")
    with patch("utils.inbound_media.resolve_delivery_credential", AsyncMock(return_value=(oauth, "owner-1"))), \
         patch("nodes.slack_node.ensure_fresh_slack_bot_token", fresh):
        assert await SlackNode._delivery_bot_token(SLACK_CFG, pool, "wf-1") == "xoxb-fresh"
    fresh.assert_awaited_once_with(
        pool, oauth, user_id="owner-1", credential_id="cred-1", caller_path="media_rehost",
    )


# ── the app-event fan-out runs the hook ─────────────────────────────────────

@pytest.mark.asyncio
async def test_fan_out_transforms_after_the_filters_and_before_the_run():
    from utils.webhook_routes import _fire_subscription

    sub = {"provider": "slack", "workflow_id": uuid.uuid4(), "node_id": "slack_trigger", "user_id": uuid.uuid4()}
    workflow = {"nodes": [{"id": "slack_trigger", "type": "automation-slack", "config": {}}], "edges": []}
    pool = MagicMock()
    pool.fetchrow = AsyncMock(return_value={"workflow": workflow})
    tasks = MagicMock()
    payload = _envelope([_file()])
    seen = []

    async def fake_transform(cls, p, config, *, pool, workflow_id, node_id):
        seen.append((p is payload, node_id))
        return {"rewritten": True}

    with patch("utils.webhook_routes.get_native_pool", return_value=pool), \
         patch("utils.fire_budget.over_fire_budget", new=AsyncMock(return_value=False)), \
         patch.object(SlackNode, "transform_trigger_payload", classmethod(fake_transform)):
        assert await _fire_subscription(tasks, sub, payload, "C1") is True
    assert seen == [(True, "slack_trigger")]
    node = tasks.add_task.call_args.kwargs["nodes"][0]
    assert node["config"]["_triggerPayload"] == {"rewritten": True}

    # A filtered delivery never reaches the transform (nothing is fetched).
    seen.clear()
    with patch("utils.webhook_routes.get_native_pool", return_value=pool), \
         patch("utils.fire_budget.over_fire_budget", new=AsyncMock(return_value=True)), \
         patch.object(SlackNode, "transform_trigger_payload", classmethod(fake_transform)):
        assert await _fire_subscription(tasks, sub, payload, "C1") is False
    assert seen == []


# ── agent-facing rendering ──────────────────────────────────────────────────

def test_agent_event_names_the_rehosted_file_with_its_url_and_a_media_entry():
    f = _file()
    f["media"] = {"url": "https://assets.example.test/o/w/r/memo.m4a", "mimetype": "audio/mp4",
                  "filename": "memo.m4a", "size": 9000, "rehosted": True, "resource_id": "res-1"}
    event = SlackNode.resolve_agent_event({"type": "slack", "data": _envelope([f])})
    assert "📎 memo (m4a): https://assets.example.test/o/w/r/memo.m4a" in event["text"]
    assert "url_private" not in event["text"]
    (entry,) = event["media"]
    assert entry["resource_id"] == "res-1" and entry["mime_type"] == "audio/mp4"
    assert entry["record"] is f["media"]


def test_agent_event_without_rehost_keeps_the_bare_name():
    event = SlackNode.resolve_agent_event({"type": "slack", "data": _envelope([_file()])})
    assert "📎 memo (m4a)" in event["text"]
    assert "files.slack.com" not in event["text"]
    assert event["media"] == []
