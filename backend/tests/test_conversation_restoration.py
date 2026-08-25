"""
Restoration / lookup tests for the workflow builder handler.

Companion to test_conversation_persistence.py — that file covers
save/list/resume/delete primitives. This file covers the higher-level
restore flow used on workflow open:

  • conversation:get_latest_for_workflow lookup priority (paused > non-empty > most-recent)
  • _save_conversation: complete / paused / cancelled persistence + replace_pending semantic
  • Pending-ask round-trip integrity (pending_ask survives save → resume)
  • Lookup column denormalization (the pending_ask column tracks the trailing assistant)

After the builder_generations collapse:
  - <ask/> is a turn boundary; no in-flight serialization
  - The conversation row is the only persistent state
  - The trailing assistant of a paused conversation has `pending_ask` set
  - Lookup uses the denormalized `pending_ask` column, no JOIN

Each test is one discrete scenario.
"""
import asyncio
import json
import uuid
from types import SimpleNamespace

import pytest
import pytest_asyncio

from tests.utils.base_handler_test import BaseHandlerTest
from tests.fixtures.real_db_fixture import real_database  # noqa: F401
from wss.receiver.client_events import (
    GetLatestConversationForWorkflowRequest,
    ResumeConversationRequest,
    ListPendingBuilderRunsRequest,
)
from wss.sender import send_event
from wss.receiver.event_routing import Handler


TEST_USER_ID = "00000000-0000-0000-0000-000000000001"
TEST_USER_EMAIL = "test@example.com"


# ── Helpers ──────────────────────────────────────────────────────────────


def _find_response(events, request_id):
    for event in events:
        if event[1].get("request_id") == request_id:
            return event[1]
    return None


async def _setup_test_user(db, user_id=TEST_USER_ID, email=TEST_USER_EMAIL):
    await db.execute(
        """INSERT INTO auth.users (id, email) VALUES ($1, $2)
           ON CONFLICT (id) DO NOTHING""",
        user_id, email,
    )
    await db.execute("DELETE FROM conversations WHERE user_id = $1", user_id)


async def _make_workflow(db, user_id=TEST_USER_ID, name="Test Workflow") -> str:
    """Insert a minimal workflow row. Returns its UUID."""
    wf_id = str(uuid.uuid4())
    await db.execute(
        """
        INSERT INTO public.workflows (id, owner_id, name, workflow, created_at, updated_at)
        VALUES ($1, $2, $3, '{"nodes":[],"edges":[]}'::jsonb, NOW(), NOW())
        """,
        wf_id, user_id, name,
    )
    return wf_id


async def _insert_conversation(
    db, conversation_id, user_id, events,
    *, workflow_id=None, title="Test", preview="test",
    pending_ask=None,
    last_activity_offset_seconds=0,
):
    """Insert a conversation row at last_activity = NOW() + offset.

    Negative offsets put the row in the past (older); positive in the future.
    Sets the denormalized pending_ask column from the trailing assistant
    automatically when callers don't pass it explicitly.
    """
    if pending_ask is None:
        for msg in reversed(events):
            if msg.get("role") == "assistant" and msg.get("pending_ask"):
                pending_ask = msg["pending_ask"]
                break
    await db.execute(
        """
        INSERT INTO conversations (
            conversation_id, user_id, workflow_id, title, preview,
            events, pending_ask, created_at, last_activity
        )
        VALUES (
            $1, $2, $3, $4, $5,
            $6::jsonb, $7::jsonb, NOW(), NOW() + ($8 || ' seconds')::interval
        )
        """,
        conversation_id, user_id, workflow_id, title, preview,
        json.dumps(events),
        json.dumps(pending_ask) if pending_ask else None,
        str(last_activity_offset_seconds),
    )


async def _send_lookup(frontend_sio, sid, workflow_id, request_id):
    await send_event(
        frontend_sio, sid,
        GetLatestConversationForWorkflowRequest(
            event_name="conversation:get_latest_for_workflow",
            request_id=request_id,
            workflow_id=workflow_id,
        ),
    )
    await asyncio.sleep(0.3)


async def _send_resume(frontend_sio, sid, conversation_id, request_id):
    await send_event(
        frontend_sio, sid,
        ResumeConversationRequest(
            event_name="conversation:resume",
            request_id=request_id,
            session_id=conversation_id,
        ),
    )
    await asyncio.sleep(0.3)


def _ask(ask_id="ask-1", title=None, inputs=None):
    return {"ask_id": ask_id, "title": title, "inputs": inputs or []}


# ── Lookup priority ──────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestLookupPriority(BaseHandlerTest):
    """conversation:get_latest_for_workflow chooses the right row out of N candidates."""

    def get_session_data(self, sid):
        return {"sid": sid, "user_id": TEST_USER_ID, "email": TEST_USER_EMAIL}

    async def test_no_conversations_returns_null(self, real_database, frontend_sio, sid):
        await _setup_test_user(real_database)
        wf_id = await _make_workflow(real_database)

        await _send_lookup(frontend_sio, sid, wf_id, "lp-empty")
        resp = _find_response(self.get_main_api_emitted_events("response"), "lp-empty")

        assert resp["data"]["conversation_id"] is None
        assert resp["data"]["has_user_messages"] is False
        assert resp["data"]["has_pending_ask"] is False

    async def test_picks_only_conversation_when_one_exists(
        self, real_database, frontend_sio, sid
    ):
        await _setup_test_user(real_database)
        wf_id = await _make_workflow(real_database)
        conv_id = f"c-{uuid.uuid4()}"
        await _insert_conversation(
            real_database, conv_id, TEST_USER_ID,
            [{"role": "user", "message": "hi"}],
            workflow_id=wf_id,
        )

        await _send_lookup(frontend_sio, sid, wf_id, "lp-one")
        resp = _find_response(self.get_main_api_emitted_events("response"), "lp-one")

        assert resp["data"]["conversation_id"] == conv_id
        assert resp["data"]["has_user_messages"] is True
        assert resp["data"]["has_pending_ask"] is False

    async def test_skips_empty_stub_in_favor_of_real_conversation(
        self, real_database, frontend_sio, sid
    ):
        """A more-recent empty stub must NOT shadow an older conversation with messages."""
        await _setup_test_user(real_database)
        wf_id = await _make_workflow(real_database)

        real_conv = f"c-real-{uuid.uuid4()}"
        stub_conv = f"c-stub-{uuid.uuid4()}"
        await _insert_conversation(
            real_database, real_conv, TEST_USER_ID,
            [{"role": "user", "message": "Build me a Slack thing"}],
            workflow_id=wf_id, last_activity_offset_seconds=-60,
        )
        await _insert_conversation(
            real_database, stub_conv, TEST_USER_ID,
            [],
            workflow_id=wf_id, last_activity_offset_seconds=0,
        )

        await _send_lookup(frontend_sio, sid, wf_id, "lp-stub")
        resp = _find_response(self.get_main_api_emitted_events("response"), "lp-stub")

        assert resp["data"]["conversation_id"] == real_conv, \
            "Should prefer the real conv over the empty stub"
        assert resp["data"]["has_user_messages"] is True

    async def test_prefers_paused_on_ask_over_more_recent_completed(
        self, real_database, frontend_sio, sid
    ):
        """Conversations with pending_ask trump completed/cancelled ones."""
        await _setup_test_user(real_database)
        wf_id = await _make_workflow(real_database)

        paused_conv = f"c-paused-{uuid.uuid4()}"
        completed_conv = f"c-completed-{uuid.uuid4()}"
        await _insert_conversation(
            real_database, paused_conv, TEST_USER_ID,
            [
                {"role": "user", "message": "build pipeline"},
                {"role": "assistant", "message": "", "edit_segments": [],
                 "pending_ask": _ask("ask-pause", inputs=[])},
            ],
            workflow_id=wf_id, last_activity_offset_seconds=-120,
        )
        await _insert_conversation(
            real_database, completed_conv, TEST_USER_ID,
            [
                {"role": "user", "message": "do something else"},
                {"role": "assistant", "message": "", "edit_segments": []},
            ],
            workflow_id=wf_id, last_activity_offset_seconds=0,
        )

        await _send_lookup(frontend_sio, sid, wf_id, "lp-paused")
        resp = _find_response(self.get_main_api_emitted_events("response"), "lp-paused")

        assert resp["data"]["conversation_id"] == paused_conv, \
            "Should prefer paused-on-ask over more-recent completed"
        assert resp["data"]["has_pending_ask"] is True

    async def test_user_isolation_lookup(self, real_database, frontend_sio, sid):
        """Looking up workflow X must not return another user's conversation on X."""
        await _setup_test_user(real_database)
        other_user = "00000000-0000-4000-8000-000000000099"
        await _setup_test_user(real_database, user_id=other_user, email="other@example.com")
        wf_id = await _make_workflow(real_database, user_id=other_user)

        other_conv = f"c-other-{uuid.uuid4()}"
        await _insert_conversation(
            real_database, other_conv, other_user,
            [{"role": "user", "message": "theirs"}],
            workflow_id=wf_id,
        )

        await _send_lookup(frontend_sio, sid, wf_id, "lp-iso")
        resp = _find_response(self.get_main_api_emitted_events("response"), "lp-iso")

        assert resp["data"]["conversation_id"] is None

    async def test_walks_top_n_for_user_messages(
        self, real_database, frontend_sio, sid
    ):
        """If the top rows are all empty stubs, the handler falls through to scan."""
        await _setup_test_user(real_database)
        wf_id = await _make_workflow(real_database)

        for i in range(3):
            await _insert_conversation(
                real_database, f"c-stub-{i}-{uuid.uuid4()}", TEST_USER_ID,
                [], workflow_id=wf_id, last_activity_offset_seconds=-i,
            )
        real_conv = f"c-real-{uuid.uuid4()}"
        await _insert_conversation(
            real_database, real_conv, TEST_USER_ID,
            [{"role": "user", "message": "the actual prompt"}],
            workflow_id=wf_id, last_activity_offset_seconds=-120,
        )

        await _send_lookup(frontend_sio, sid, wf_id, "lp-walk")
        resp = _find_response(self.get_main_api_emitted_events("response"), "lp-walk")

        assert resp["data"]["conversation_id"] == real_conv

    async def test_skips_soft_deleted(self, real_database, frontend_sio, sid):
        """A soft-deleted conversation must not be returned even if it's most-recent."""
        await _setup_test_user(real_database)
        wf_id = await _make_workflow(real_database)

        deleted_conv = f"c-deleted-{uuid.uuid4()}"
        kept_conv = f"c-kept-{uuid.uuid4()}"
        await real_database.execute(
            """
            INSERT INTO conversations
                (conversation_id, user_id, workflow_id, title, preview, events,
                 created_at, last_activity, deleted_at)
            VALUES ($1, $2, $3, 'Deleted', '', '[{"role":"user","message":"x"}]'::jsonb,
                    NOW(), NOW(), NOW())
            """,
            deleted_conv, TEST_USER_ID, wf_id,
        )
        await _insert_conversation(
            real_database, kept_conv, TEST_USER_ID,
            [{"role": "user", "message": "alive"}],
            workflow_id=wf_id, last_activity_offset_seconds=-60,
        )

        await _send_lookup(frontend_sio, sid, wf_id, "lp-deleted")
        resp = _find_response(self.get_main_api_emitted_events("response"), "lp-deleted")
        assert resp["data"]["conversation_id"] == kept_conv


# ── Persistence — _save_conversation contract ────────────────────────────


@pytest.mark.asyncio
class TestSaveConversation(BaseHandlerTest):
    """The unified _save_conversation: complete, paused, cancelled, replace_pending."""

    def get_session_data(self, sid):
        return {"sid": sid, "user_id": TEST_USER_ID, "email": TEST_USER_EMAIL}

    async def test_save_complete_turn_writes_pair(
        self, real_database, frontend_sio, sid
    ):
        await _setup_test_user(real_database)
        handler = self.handlers[Handler.WORKFLOW_BUILDER]
        conv_id = f"c-complete-{uuid.uuid4()}"

        await handler._save_conversation(conv_id, TEST_USER_ID, [
            {"role": "user", "message": "build slack digest"},
            {"role": "assistant", "message": "", "edit_segments": [
                {"type": "text", "text": "done"},
            ]},
        ])
        await asyncio.sleep(0.3)

        await _send_resume(frontend_sio, sid, conv_id, "save-complete")
        resp = _find_response(self.get_main_api_emitted_events("response"), "save-complete")
        msgs = resp["data"]["messages"]
        assert len(msgs) == 2
        assert msgs[1]["edit_segments"][0]["text"] == "done"
        # No pending_ask on complete turns
        assert msgs[1].get("pending_ask") is None

    async def test_save_paused_turn_persists_pending_ask(
        self, real_database, frontend_sio, sid
    ):
        """A paused turn carries pending_ask on the assistant + the column is set."""
        await _setup_test_user(real_database)
        wf_id = await _make_workflow(real_database)
        handler = self.handlers[Handler.WORKFLOW_BUILDER]
        conv_id = str(uuid.uuid4())

        await handler._save_conversation(conv_id, TEST_USER_ID, [
            {"role": "user", "message": "connect slack"},
            {
                "role": "assistant", "message": "",
                "edit_segments": [{"type": "text", "text": "asking..."}],
                "edit_steps": ["Searching credentials"],
                "llm_messages": [{"role": "assistant", "content": "<ask id='a1'>...</ask>"}],
                "pending_ask": _ask("a1", inputs=[{"id": "ask_0", "type": "credential"}]),
            },
        ], workflow_id=wf_id)
        await asyncio.sleep(0.3)

        # Resume returns the paused assistant with pending_ask intact.
        await _send_resume(frontend_sio, sid, conv_id, "save-paused")
        resp = _find_response(self.get_main_api_emitted_events("response"), "save-paused")
        asst = resp["data"]["messages"][1]
        assert asst["pending_ask"]["ask_id"] == "a1"
        assert asst["edit_steps"] == ["Searching credentials"]
        assert asst["llm_messages"][0]["content"].startswith("<ask")

        # Lookup picks it up via the pending_ask column priority.
        await _send_lookup(frontend_sio, sid, wf_id, "save-paused-lookup")
        lookup = _find_response(
            self.get_main_api_emitted_events("response"), "save-paused-lookup",
        )
        assert lookup["data"]["conversation_id"] == conv_id
        assert lookup["data"]["has_pending_ask"] is True

    async def test_replace_pending_merges_resume_into_prior_assistant(
        self, real_database, frontend_sio, sid
    ):
        """Resume-after-ask: the new turn's content MERGES into the prior
        paused assistant, producing one continuous bubble. The prior turn's
        work (segments, edit_steps, llm_messages) is preserved; the new
        turn's content appends; the pending_ask field clears.

        This is what makes Skip All / credential-submit visually continue
        the same bubble rather than open a new turn.
        """
        await _setup_test_user(real_database)
        handler = self.handlers[Handler.WORKFLOW_BUILDER]
        conv_id = f"c-resume-{uuid.uuid4()}"

        # Pause snapshot — prior turn produced one text segment + edit_steps.
        await handler._save_conversation(conv_id, TEST_USER_ID, [
            {"role": "user", "message": "connect slack"},
            {"role": "assistant", "message": "",
             "edit_segments": [{"type": "text", "text": "starting work"}],
             "edit_steps": ["Modifying workflow"],
             "pending_ask": _ask("a1")},
        ])
        await asyncio.sleep(0.2)

        # Resume completes — replace_pending=True. New turn carries its
        # OWN new content (no need to re-include the prior asking text).
        await handler._save_conversation(conv_id, TEST_USER_ID, [
            {"role": "user", "message": "connect slack"},
            {"role": "assistant", "message": "",
             "edit_segments": [
                 {"type": "events", "events": [
                     {"type": "node_added", "nodeType": "automation-slack",
                      "nodeLabel": "Slack", "status": "completed"},
                 ]},
                 {"type": "text", "text": "Done!"},
             ],
             "edit_steps": ["Thinking after skip"]},
        ], replace_pending=True)
        await asyncio.sleep(0.3)

        await _send_resume(frontend_sio, sid, conv_id, "rs-merge")
        resp = _find_response(self.get_main_api_emitted_events("response"), "rs-merge")
        msgs = resp["data"]["messages"]
        assert len(msgs) == 2, f"Expected 2 messages, got {len(msgs)}"
        assert msgs[1].get("pending_ask") is None, "pending_ask cleared on resume"
        # Merged: prior 1 segment + new 2 segments = 3 total
        assert len(msgs[1]["edit_segments"]) == 3, \
            f"Expected merged segments (prior + new), got {len(msgs[1]['edit_segments'])}"
        assert msgs[1]["edit_segments"][0]["text"] == "starting work", \
            "First segment is the prior turn's content"
        assert msgs[1]["edit_segments"][1]["type"] == "events", \
            "Second segment is the new turn's events"
        # edit_steps concatenated in order
        assert msgs[1]["edit_steps"] == ["Modifying workflow", "Thinking after skip"]

    async def test_replace_pending_false_appends_new_turn(
        self, real_database, frontend_sio, sid
    ):
        """replace_pending=False (default) appends a new turn — multi-turn conversations."""
        await _setup_test_user(real_database)
        handler = self.handlers[Handler.WORKFLOW_BUILDER]
        conv_id = f"c-multi-{uuid.uuid4()}"

        await handler._save_conversation(conv_id, TEST_USER_ID, [
            {"role": "user", "message": "first"},
            {"role": "assistant", "message": "",
             "edit_segments": [{"type": "text", "text": "first done"}]},
        ])
        await asyncio.sleep(0.2)

        await handler._save_conversation(conv_id, TEST_USER_ID, [
            {"role": "user", "message": "second"},
            {"role": "assistant", "message": "",
             "edit_segments": [{"type": "text", "text": "second done"}]},
        ])
        await asyncio.sleep(0.3)

        await _send_resume(frontend_sio, sid, conv_id, "rs-multi")
        resp = _find_response(self.get_main_api_emitted_events("response"), "rs-multi")
        msgs = resp["data"]["messages"]
        assert len(msgs) == 4
        assert msgs[0]["message"] == "first"
        assert msgs[2]["message"] == "second"

    async def test_cancelled_turn_persists_with_cancelled_flag(
        self, real_database, frontend_sio, sid
    ):
        await _setup_test_user(real_database)
        handler = self.handlers[Handler.WORKFLOW_BUILDER]
        conv_id = f"c-cancel-{uuid.uuid4()}"

        await handler._save_conversation(conv_id, TEST_USER_ID, [
            {"role": "user", "message": "halt me"},
            {"role": "assistant", "message": "",
             "edit_segments": [{"type": "text", "text": "partial"}],
             "edit_steps": ["Modifying workflow"],
             "cancelled": True},
        ])
        await asyncio.sleep(0.3)

        await _send_resume(frontend_sio, sid, conv_id, "rs-cancel")
        resp = _find_response(self.get_main_api_emitted_events("response"), "rs-cancel")
        asst = resp["data"]["messages"][1]
        assert asst["cancelled"] is True
        assert asst["edit_segments"][0]["text"] == "partial"

    async def test_billing_accumulators_increment(
        self, real_database, frontend_sio, sid
    ):
        """cost_delta / token_delta / turn_delta sum across saves."""
        await _setup_test_user(real_database)
        handler = self.handlers[Handler.WORKFLOW_BUILDER]
        conv_id = f"c-billing-{uuid.uuid4()}"

        await handler._save_conversation(conv_id, TEST_USER_ID, [
            {"role": "user", "message": "first"},
            {"role": "assistant", "message": "", "edit_segments": []},
        ], cost_delta=0.01, token_delta=100, turn_delta=1)
        await asyncio.sleep(0.2)

        await handler._save_conversation(conv_id, TEST_USER_ID, [
            {"role": "user", "message": "second"},
            {"role": "assistant", "message": "", "edit_segments": []},
        ], cost_delta=0.02, token_delta=250, turn_delta=2)
        await asyncio.sleep(0.3)

        row = await real_database.fetchrow(
            "SELECT total_cost, total_tokens, turn_count FROM conversations "
            "WHERE conversation_id = $1", conv_id,
        )
        assert float(row["total_cost"]) == pytest.approx(0.03)
        assert row["total_tokens"] == 350
        assert row["turn_count"] == 3


# ── Pending-ask column denormalization ──────────────────────────────────


@pytest.mark.asyncio
class TestPendingAskColumn(BaseHandlerTest):
    """The denormalized pending_ask column tracks the trailing assistant."""

    def get_session_data(self, sid):
        return {"sid": sid, "user_id": TEST_USER_ID, "email": TEST_USER_EMAIL}

    async def test_column_set_when_assistant_has_pending_ask(
        self, real_database, frontend_sio, sid
    ):
        await _setup_test_user(real_database)
        handler = self.handlers[Handler.WORKFLOW_BUILDER]
        conv_id = f"c-col-set-{uuid.uuid4()}"

        await handler._save_conversation(conv_id, TEST_USER_ID, [
            {"role": "user", "message": "ask me"},
            {"role": "assistant", "message": "", "edit_segments": [],
             "pending_ask": _ask("ask-x", title="Connect")},
        ])
        await asyncio.sleep(0.3)

        row = await real_database.fetchrow(
            "SELECT pending_ask FROM conversations WHERE conversation_id = $1", conv_id,
        )
        ask = row["pending_ask"]
        if isinstance(ask, str):
            ask = json.loads(ask)
        assert ask is not None
        assert ask["ask_id"] == "ask-x"

    async def test_column_cleared_on_resume_completion(
        self, real_database, frontend_sio, sid
    ):
        """Completing the resumed turn clears pending_ask on the column."""
        await _setup_test_user(real_database)
        handler = self.handlers[Handler.WORKFLOW_BUILDER]
        conv_id = f"c-col-clear-{uuid.uuid4()}"

        # Pause
        await handler._save_conversation(conv_id, TEST_USER_ID, [
            {"role": "user", "message": "ask me"},
            {"role": "assistant", "message": "", "edit_segments": [],
             "pending_ask": _ask("ask-y")},
        ])
        await asyncio.sleep(0.2)

        # Complete (replace_pending=True). The new assistant has no pending_ask.
        await handler._save_conversation(conv_id, TEST_USER_ID, [
            {"role": "user", "message": "ask me"},
            {"role": "assistant", "message": "", "edit_segments": [
                {"type": "text", "text": "done"}]},
        ], replace_pending=True)
        await asyncio.sleep(0.3)

        row = await real_database.fetchrow(
            "SELECT pending_ask FROM conversations WHERE conversation_id = $1", conv_id,
        )
        assert row["pending_ask"] is None


# ── list_pending against conversations.pending_ask ───────────────────────


@pytest.mark.asyncio
class TestListPending(BaseHandlerTest):
    """workflow:builder:list_pending reads the pending_ask column."""

    def get_session_data(self, sid):
        return {"sid": sid, "user_id": TEST_USER_ID, "email": TEST_USER_EMAIL}

    async def test_list_returns_paused_conversations(
        self, real_database, frontend_sio, sid
    ):
        await _setup_test_user(real_database)
        wf_id = await _make_workflow(real_database)

        paused_conv = str(uuid.uuid4())
        completed_conv = f"c-comp-{uuid.uuid4()}"
        await _insert_conversation(
            real_database, paused_conv, TEST_USER_ID,
            [
                {"role": "user", "message": "ask me"},
                {"role": "assistant", "message": "", "edit_segments": [],
                 "pending_ask": _ask("a1", title="Need cred")},
            ],
            workflow_id=wf_id,
        )
        await _insert_conversation(
            real_database, completed_conv, TEST_USER_ID,
            [
                {"role": "user", "message": "regular"},
                {"role": "assistant", "message": "", "edit_segments": []},
            ],
            workflow_id=wf_id,
        )

        await send_event(
            frontend_sio, sid,
            ListPendingBuilderRunsRequest(
                event_name="workflow:builder:list_pending",
                request_id="lp-1",
            ),
        )
        await asyncio.sleep(0.3)

        resp = _find_response(self.get_main_api_emitted_events("response"), "lp-1")
        runs = resp["data"]["runs"]
        ids = [r["conversation_id"] for r in runs]
        assert paused_conv in ids
        assert completed_conv not in ids
        run = next(r for r in runs if r["conversation_id"] == paused_conv)
        assert run["pending_ask"]["ask_id"] == "a1"
        assert run["workflow_id"] == wf_id

    async def test_list_filters_by_workflow_id(
        self, real_database, frontend_sio, sid
    ):
        await _setup_test_user(real_database)
        wf_a = await _make_workflow(real_database)
        wf_b = await _make_workflow(real_database)

        conv_a = str(uuid.uuid4())
        conv_b = str(uuid.uuid4())
        for conv, wf in [(conv_a, wf_a), (conv_b, wf_b)]:
            await _insert_conversation(
                real_database, conv, TEST_USER_ID,
                [
                    {"role": "user", "message": "x"},
                    {"role": "assistant", "message": "", "edit_segments": [],
                     "pending_ask": _ask(f"ask-{conv[:4]}")},
                ],
                workflow_id=wf,
            )

        await send_event(
            frontend_sio, sid,
            ListPendingBuilderRunsRequest(
                event_name="workflow:builder:list_pending",
                request_id="lp-flt",
                workflow_id=wf_a,
            ),
        )
        await asyncio.sleep(0.3)

        resp = _find_response(self.get_main_api_emitted_events("response"), "lp-flt")
        ids = [r["conversation_id"] for r in resp["data"]["runs"]]
        assert ids == [conv_a]


# ── Round-trip integrity ────────────────────────────────────────────────


@pytest.mark.asyncio
class TestRoundTripIntegrity(BaseHandlerTest):
    """Persisted shape must match what the FE expects to render."""

    def get_session_data(self, sid):
        return {"sid": sid, "user_id": TEST_USER_ID, "email": TEST_USER_EMAIL}

    async def test_node_updated_event_includes_node_type_and_label(
        self, real_database, frontend_sio, sid
    ):
        await _setup_test_user(real_database)
        handler = self.handlers[Handler.WORKFLOW_BUILDER]
        conv_id = f"c-icon-{uuid.uuid4()}"

        await handler._save_conversation(conv_id, TEST_USER_ID, [
            {"role": "user", "message": "tweak slack"},
            {"role": "assistant", "message": "", "edit_segments": [
                {"type": "events", "events": [
                    {"type": "node_updated", "nodeId": "slack_send",
                     "nodeType": "automation-slack", "nodeLabel": "Slack",
                     "operation": "send_email_message", "config": {"channel": "#ops"},
                     "status": "completed"},
                ]},
            ]},
        ])
        await asyncio.sleep(0.3)

        await _send_resume(frontend_sio, sid, conv_id, "rt-icon")
        resp = _find_response(self.get_main_api_emitted_events("response"), "rt-icon")
        ev = resp["data"]["messages"][1]["edit_segments"][0]["events"][0]
        assert ev.get("nodeType") == "automation-slack"
        assert ev.get("nodeLabel") == "Slack"

    async def test_edit_steps_round_trip(self, real_database, frontend_sio, sid):
        await _setup_test_user(real_database)
        handler = self.handlers[Handler.WORKFLOW_BUILDER]
        conv_id = f"c-steps-{uuid.uuid4()}"
        steps = ["Modifying workflow", "Thinking", "Looking up node info"]

        await handler._save_conversation(conv_id, TEST_USER_ID, [
            {"role": "user", "message": "x"},
            {"role": "assistant", "message": "", "edit_segments": [], "edit_steps": steps},
        ])
        await asyncio.sleep(0.3)

        await _send_resume(frontend_sio, sid, conv_id, "rt-steps")
        resp = _find_response(self.get_main_api_emitted_events("response"), "rt-steps")
        assert resp["data"]["messages"][1]["edit_steps"] == steps

    async def test_llm_messages_round_trip(self, real_database, frontend_sio, sid):
        """llm_messages on the assistant survive — needed for resume-after-ask context."""
        await _setup_test_user(real_database)
        handler = self.handlers[Handler.WORKFLOW_BUILDER]
        conv_id = f"c-llm-{uuid.uuid4()}"
        llm = [
            {"role": "user", "content": "make a slack bot"},
            {"role": "assistant", "content": "<add_node id='slack' type='automation-slack'/>"},
        ]

        await handler._save_conversation(conv_id, TEST_USER_ID, [
            {"role": "user", "message": "make a slack bot"},
            {"role": "assistant", "message": "", "edit_segments": [],
             "llm_messages": llm},
        ])
        await asyncio.sleep(0.3)

        await _send_resume(frontend_sio, sid, conv_id, "rt-llm")
        resp = _find_response(self.get_main_api_emitted_events("response"), "rt-llm")
        assert resp["data"]["messages"][1]["llm_messages"] == llm

    async def test_resume_answer_lands_in_brain_history(
        self, real_database, frontend_sio, sid
    ):
        """B2: the user's <ask/> answer must survive into the brain's restored
        history. The resume path injects the answer as the *current* user
        message while persisting the ORIGINAL prompt as the visible user event,
        so the answer is captured ONLY via ``_new_turn_llm_messages`` ->
        the assistant's ``llm_messages``. Exercises the real helper +
        ``_save_conversation`` (replace_pending merge) + ``_load_conversation_history``.
        """
        await _setup_test_user(real_database)
        handler = self.handlers[Handler.WORKFLOW_BUILDER]
        conv_id = f"c-answer-{uuid.uuid4()}"
        original = "connect google sheet to retell"
        answer = "[System: User Input Response]\n- ask_0: +12025550137"

        # Turn 1: initial prompt; brain pauses on an <ask/>.
        await handler._save_conversation(conv_id, TEST_USER_ID, [
            {"role": "user", "message": original},
            {"role": "assistant", "message": "",
             "edit_segments": [{"type": "text", "text": "Which number?"}],
             "llm_messages": [{"role": "assistant", "content": "<ask field='to_number'/>"}],
             "pending_ask": _ask("a1", inputs=[{"id": "ask_0"}])},
        ])
        await asyncio.sleep(0.2)

        # Turn 2 (resume): builder.messages models what the brain saw this turn —
        # system + loaded history (user + assistant) + the INJECTED answer +
        # this turn's output. conversation_history_len = 2 (user, assistant).
        builder = SimpleNamespace(messages=[
            {"role": "system", "content": "<system prompt>"},
            {"role": "user", "content": original},                          # history[0]
            {"role": "assistant", "content": "<ask field='to_number'/>"},   # history[1]
            {"role": "user", "content": answer},                            # current_user = answer
            {"role": "assistant", "content": "<field node='retell' name='to_number'/>"},
            {"role": "user", "content": "[System: Execution Result]\nSet retell.to_number"},
        ])
        # The resume persists the ORIGINAL prompt as the visible message, so the
        # injected answer differs from it and the helper MUST include it.
        llm = handler._new_turn_llm_messages(builder, 2, original)
        assert any(m.get("content") == answer for m in llm), (
            f"the injected answer must be included in the turn's llm_messages; got {llm}"
        )

        await handler._save_conversation(conv_id, TEST_USER_ID, [
            {"role": "user", "message": original},
            {"role": "assistant", "message": "",
             "edit_segments": [{"type": "text", "text": "Done"}],
             "llm_messages": llm},
        ], replace_pending=True)
        await asyncio.sleep(0.3)

        # Reload the brain history exactly as the NEXT resume would, and assert
        # the answer is present (so the brain won't re-ask for it).
        history = await handler._load_conversation_history(conv_id, TEST_USER_ID)
        contents = [m.get("content", "") for m in history]
        assert any(answer in c for c in contents), (
            f"brain history must contain the user's answer; got {contents}"
        )

    async def test_new_turn_llm_messages_excludes_normal_edit_prompt(
        self, real_database, frontend_sio, sid
    ):
        """Normal-edit turns must NOT double-persist the user prompt: the helper
        skips current_user when it equals the visible message (no DB needed)."""
        handler = self.handlers[Handler.WORKFLOW_BUILDER]
        typed = "make a slack bot"
        builder = SimpleNamespace(messages=[
            {"role": "system", "content": "<system>"},
            {"role": "user", "content": typed},          # current_user == visible message
            {"role": "assistant", "content": "<add_node id='slack'/>"},
        ])
        llm = handler._new_turn_llm_messages(builder, 0, typed)
        assert [m["content"] for m in llm] == ["<add_node id='slack'/>"], (
            f"normal-edit current_user must be excluded to avoid duplication; got {llm}"
        )

    async def test_new_turn_llm_messages_handles_selected_node_suffix(
        self, real_database, frontend_sio, sid
    ):
        """A selected-node edit appends a context suffix to the prompt, so
        current_user != the visible message verbatim. A prefix match must still
        treat it as already-persisted (no duplication)."""
        handler = self.handlers[Handler.WORKFLOW_BUILDER]
        typed = "make the label bold"
        builder = SimpleNamespace(messages=[
            {"role": "system", "content": "<system>"},
            {"role": "user", "content": typed + '\nThe user has selected node "x" (...).'},
            {"role": "assistant", "content": "<field .../>"},
        ])
        llm = handler._new_turn_llm_messages(builder, 0, typed)
        assert [m["content"] for m in llm] == ["<field .../>"], (
            f"selected-node current_user must be excluded (prefix match); got {llm}"
        )
