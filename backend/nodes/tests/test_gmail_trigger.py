"""Gmail "poll for new emails" trigger.

The trigger fires for emails that ARRIVED since the last poll — new messages and
replies to existing threads alike — and never drains an existing backlog. Dedup
is by Gmail's ``internalDate`` (arrival time) high-water-mark, persisted in node
state; the first poll baselines (emits nothing). These tests drive the poll with
a mocked Gmail API and an in-memory state store.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from nodes.gmail_node import GmailNode, GmailNodeConfig, GmailOAuthCredential, GmailTriggerListenConfig

pytestmark = pytest.mark.asyncio

GMAIL_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"


def _credentials():
    return GmailOAuthCredential(
        access_token="tok", refresh_token="r", expires_at="2099-12-31T23:59:59Z",
        email="me@gmail.com",
    )


def _node(state_store):
    """Gmail trigger node whose state I/O is backed by ``state_store`` (both the
    pre-page read and the CAS update mutate the same dict)."""
    cfg = GmailNodeConfig(config=GmailTriggerListenConfig(), credentials=_credentials())
    node = GmailNode(
        node_id="n", node_type="automation-gmail", node_data={},
        config=cfg, sio=None, sid=None, workflow_id="wf",
    )
    node.emit = AsyncMock()

    async def _load():
        return dict(state_store)

    async def _update(mutator, *, max_retries=4, skip_result=None):
        new_state, result = mutator(dict(state_store))
        if new_state is not None:
            state_store.clear()
            state_store.update(new_state)
        return result

    node._load_node_state = _load
    node._update_node_state = _update
    return node


def _resp(json_data):
    r = MagicMock()
    r.status_code = 200
    r.json.return_value = json_data
    r.text = str(json_data)
    return r


def _msg(msg_id, internal_ms, thread_id, subject="hi"):
    return {
        "id": msg_id,
        "threadId": thread_id,
        "internalDate": str(internal_ms),
        "snippet": subject,
        "labelIds": ["INBOX"],
        "payload": {"headers": [
            {"name": "Subject", "value": subject},
            {"name": "From", "value": "sender@x.com"},
        ]},
    }


def _patch_gmail(messages):
    """Patch httpx so `messages.list` returns the given messages (most-recent
    first) and `messages/{id}` returns each message's detail."""
    by_id = {m["id"]: m for m in messages}

    async def _get(url, headers=None, params=None):
        if url.endswith("/messages"):
            return _resp({"messages": [{"id": m["id"]} for m in messages]})
        return _resp(by_id[url.rsplit("/", 1)[-1]])

    client = MagicMock()
    client.get = AsyncMock(side_effect=_get)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=None)
    return patch("nodes.gmail_node.httpx.AsyncClient", return_value=ctx)


async def test_first_poll_baselines_and_emits_nothing():
    """Turning the trigger on must NOT drain the existing inbox — it records the
    newest arrival and fires for nothing."""
    store = {}
    node = _node(store)
    inbox = [_msg("m3", 300, "t3"), _msg("m2", 200, "t2"), _msg("m1", 100, "t1")]
    with _patch_gmail(inbox):
        out = await node.execute({})

    assert out["operation"] == "poll_for_new_emails"
    assert out["email_count"] == 0
    assert out["emails"] == []
    assert node.trigger_produced_no_event(out) is True
    # Watermark seeded to the newest existing message.
    assert store["last_internal_date"] == 300


async def test_second_poll_emits_only_new_arrivals():
    store = {"last_internal_date": 300, "last_internal_ids": ["m3"]}
    node = _node(store)
    inbox = [_msg("m4", 400, "t4"), _msg("m3", 300, "t3"), _msg("m2", 200, "t2")]
    with _patch_gmail(inbox):
        out = await node.execute({})

    assert out["email_count"] == 1
    assert [e["id"] for e in out["emails"]] == ["m4"]
    assert store["last_internal_date"] == 400
    assert store["last_internal_ids"] == ["m4"]


async def test_reply_to_old_thread_fires():
    """A reply lands in an OLD thread but has a fresh internalDate — dedup is
    per-message, so it must trigger just like a brand-new email."""
    store = {"last_internal_date": 400, "last_internal_ids": ["m4"]}
    node = _node(store)
    reply = _msg("m5", 500, "t2", subject="Re: old thread")  # thread t2 is old
    inbox = [reply, _msg("m4", 400, "t4")]
    with _patch_gmail(inbox):
        out = await node.execute({})

    assert [e["id"] for e in out["emails"]] == ["m5"]
    assert out["emails"][0]["thread_id"] == "t2"
    assert store["last_internal_date"] == 500


async def test_no_new_mail_emits_nothing_and_keeps_watermark():
    store = {"last_internal_date": 500, "last_internal_ids": ["m5"]}
    node = _node(store)
    inbox = [_msg("m5", 500, "t2"), _msg("m4", 400, "t4")]
    with _patch_gmail(inbox):
        out = await node.execute({})

    assert out["emails"] == []
    assert node.trigger_produced_no_event(out) is True
    assert store["last_internal_date"] == 500  # unchanged


async def test_multiple_new_arrivals_delivered_oldest_first():
    store = {"last_internal_date": 100, "last_internal_ids": ["m1"]}
    node = _node(store)
    inbox = [_msg("m3", 300, "t3"), _msg("m2", 200, "t2"), _msg("m1", 100, "t1")]
    with _patch_gmail(inbox):
        out = await node.execute({})

    assert [e["id"] for e in out["emails"]] == ["m2", "m3"]  # ascending internalDate
    assert store["last_internal_date"] == 300


async def test_same_millisecond_new_message_fires():
    """A genuinely-new message sharing the watermark's exact ms must still fire —
    it's distinguished from the already-emitted boundary message by id."""
    store = {"last_internal_date": 500, "last_internal_ids": ["m5"]}
    node = _node(store)
    # m6 arrives at the SAME internalDate as the watermark message m5.
    inbox = [_msg("m6", 500, "t6"), _msg("m5", 500, "t5"), _msg("m4", 400, "t4")]
    with _patch_gmail(inbox):
        out = await node.execute({})

    assert [e["id"] for e in out["emails"]] == ["m6"]  # m5 (boundary) not re-emitted
    assert set(store["last_internal_ids"]) == {"m5", "m6"}  # both now at the boundary


async def test_state_read_failure_skips_tick_without_raising():
    """A transient state-read failure skips the tick cleanly (no event, no
    exception) instead of failing the scheduled run."""
    store = {"last_internal_date": 300, "last_internal_ids": ["m3"]}
    node = _node(store)

    async def _boom():
        raise RuntimeError("pooler timeout")

    node._load_node_state = _boom
    inbox = [_msg("m4", 400, "t4")]
    with _patch_gmail(inbox):
        out = await node.execute({})

    assert out["email_count"] == 0
    assert out["emails"] == []
    assert store["last_internal_date"] == 300  # watermark untouched


async def test_empty_inbox_baseline_stays_unbaselined():
    """Baselining on an empty inbox must NOT store 0 (which would make every
    later poll a full `after:0` scan) — it stays unbaselined until real mail."""
    store = {}
    node = _node(store)
    with _patch_gmail([]):  # empty inbox
        out = await node.execute({})
    assert out["email_count"] == 0
    assert store == {}  # nothing persisted — still unbaselined
