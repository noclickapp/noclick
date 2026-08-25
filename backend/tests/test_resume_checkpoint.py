"""Tests for the cache-tier builder resume checkpoint (coder/workflow/resume_checkpoint).

Covers the roundtrip (plan + per-node cursor), the new-plan-resets-cursor
invariant, TTL, and — most importantly — that every op is graceful when Redis
is absent (returns None / no-op, never raises), since the checkpoint must be a
pure optimization and never a correctness dependency.
"""
from __future__ import annotations

import fakeredis.aioredis
import pytest

from coder.workflow import resume_checkpoint as rc
from coder.workflow.workflow_xml import XmlOp


@pytest.fixture
def fake_redis(monkeypatch):
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(rc, "_client", lambda: client)
    return client


async def test_roundtrip_plan_and_cursor(fake_redis):
    cid = "conv-1"
    ops = [
        XmlOp(tag="add_node", attrs={"name": "n1", "type": "gmail"}),
        XmlOp(tag="field", attrs={"node": "n1", "name": "x"}, body="v"),
    ]
    await rc.save_plan(cid, turn=1, prompt="do it", ops=ops)

    cp = await rc.load_checkpoint(cid)
    assert cp is not None
    assert cp["turn"] == 1
    assert cp["prompt"] == "do it"
    assert cp["ops"][0] == {"tag": "add_node", "attrs": {"name": "n1", "type": "gmail"}, "body": None}
    assert cp["ops"][1]["body"] == "v"
    assert cp["completed_node_ids"] == []  # cursor starts empty

    await rc.mark_node_completed(cid, "n1")
    cp2 = await rc.load_checkpoint(cid)
    assert cp2["completed_node_ids"] == ["n1"]

    await rc.clear_checkpoint(cid)
    assert await rc.load_checkpoint(cid) is None


async def test_new_plan_resets_cursor(fake_redis):
    cid = "conv-2"
    await rc.save_plan(cid, turn=1, prompt="p", ops=[XmlOp(tag="add_node", attrs={"name": "n1"})])
    await rc.mark_node_completed(cid, "n1")
    # A fresh plan (next turn) must not inherit the prior turn's completed cursor.
    await rc.save_plan(cid, turn=2, prompt="p", ops=[XmlOp(tag="add_node", attrs={"name": "n2"})])
    cp = await rc.load_checkpoint(cid)
    assert cp["turn"] == 2
    assert cp["completed_node_ids"] == []


async def test_ttl_is_set(fake_redis):
    cid = "conv-ttl"
    await rc.save_plan(cid, turn=1, prompt="p", ops=[])
    ttl = await fake_redis.ttl(rc._plan_key(cid))
    assert 0 < ttl <= rc.CHECKPOINT_TTL_SECONDS


async def test_accepts_dict_ops(fake_redis):
    cid = "conv-dict"
    await rc.save_plan(cid, turn=1, prompt="p", ops=[{"tag": "add_node", "attrs": {"name": "n1"}, "body": None}])
    cp = await rc.load_checkpoint(cid)
    assert cp["ops"][0]["attrs"]["name"] == "n1"


async def test_graceful_without_redis(monkeypatch):
    # No client → every op no-ops, load returns None, nothing raises.
    monkeypatch.setattr(rc, "_client", lambda: None)
    await rc.save_plan("c", turn=1, prompt="p", ops=[XmlOp(tag="add_node", attrs={})])
    await rc.mark_node_completed("c", "n1")
    assert await rc.load_checkpoint("c") is None
    await rc.clear_checkpoint("c")  # must not raise


async def test_empty_conversation_id_is_noop(fake_redis):
    await rc.save_plan(None, turn=1, prompt="p", ops=[])
    assert await rc.load_checkpoint(None) is None
    assert await rc.load_checkpoint("") is None


# ── Epoch fence ─────────────────────────────────────────────────────────────

async def test_claim_attempt_is_monotonic(fake_redis):
    cid = "conv-epoch"
    assert await rc.claim_attempt(cid) == 1
    assert await rc.claim_attempt(cid) == 2
    assert await rc.claim_attempt(cid) == 3
    # TTL is set so the key doesn't linger forever.
    assert 0 < await fake_redis.ttl(rc._attempt_key(cid)) <= rc.CHECKPOINT_TTL_SECONDS


async def test_is_superseded(fake_redis):
    cid = "conv-sup"
    a1 = await rc.claim_attempt(cid)          # 1 (the "original")
    assert await rc.is_superseded(cid, a1) is False   # still latest
    a2 = await rc.claim_attempt(cid)          # 2 (the "resume")
    assert await rc.is_superseded(cid, a1) is True    # original now superseded
    assert await rc.is_superseded(cid, a2) is False   # resume is latest
    # Unknown epoch / missing key never reports superseded (fail-open).
    assert await rc.is_superseded(cid, None) is False
    assert await rc.is_superseded("conv-none", 1) is False


async def test_is_current_attempt(fake_redis):
    cid = "conv-cur"
    a1 = await rc.claim_attempt(cid)          # 1
    assert await rc.is_current_attempt(cid, a1) is True    # latest → may clear
    a2 = await rc.claim_attempt(cid)          # 2 supersedes
    assert await rc.is_current_attempt(cid, a1) is False   # superseded → must NOT clear
    assert await rc.is_current_attempt(cid, a2) is True
    # No epoch / no key → clear as before (legacy behavior).
    assert await rc.is_current_attempt(cid, None) is True
    assert await rc.is_current_attempt("conv-none", 5) is True


async def test_epoch_graceful_without_redis(monkeypatch):
    monkeypatch.setattr(rc, "_client", lambda: None)
    assert await rc.claim_attempt("c") is None          # can't claim → fencing off
    assert await rc.is_superseded("c", 1) is False       # never cancels a live run
    assert await rc.is_current_attempt("c", 1) is True   # clears as before
    await rc.refresh_checkpoint_ttl("c")                  # must not raise
