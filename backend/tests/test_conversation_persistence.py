"""
Tests for conversation persistence in the workflow builder handler.

Verifies that agentic builder conversations are correctly saved to, listed from,
resumed from, and deleted in the PostgreSQL conversations table.
"""
import asyncio
import json
import uuid

import pytest
import pytest_asyncio

from tests.utils.base_handler_test import BaseHandlerTest
from tests.fixtures.real_db_fixture import real_database  # noqa: F401
from wss.receiver.client_events import (
    ListConversationsRequest,
    ResumeConversationRequest,
    DeleteConversationRequest,
)
from wss.sender import send_event
from wss.sender.events import ConversationListEvent
from wss.receiver.event_routing import Handler

# Use the user id seeded in postgres_fixtures._initialize_database_once
TEST_USER_ID = "00000000-0000-0000-0000-000000000001"
TEST_USER_EMAIL = "test@example.com"


def _find_response(events, request_id):
    """Find a response event by request_id."""
    for event in events:
        if event[1].get("request_id") == request_id:
            return event[1]
    return None


def _find_conversation_list(events, request_id):
    """Find a conversations:list event by request_id."""
    for event in events:
        if event[1].get("request_id") == request_id:
            return event[1]
    return None


async def _setup_test_user(db, user_id=TEST_USER_ID, email=TEST_USER_EMAIL):
    """Ensure a test user exists and clean up stale conversations."""
    await db.execute(
        """INSERT INTO auth.users (id, email) VALUES ($1, $2)
           ON CONFLICT (id) DO NOTHING""",
        user_id,
        email,
    )
    await db.execute("DELETE FROM conversations WHERE user_id = $1", user_id)



async def _insert_conversation(db, conversation_id, user_id, messages, title="Test", preview="test"):
    """Insert a conversation directly into the database."""
    await db.execute(
        """
        INSERT INTO conversations (conversation_id, user_id, title, preview, events, created_at, last_activity)
        VALUES ($1, $2, $3, $4, $5::jsonb, NOW(), NOW())
        """,
        conversation_id,
        user_id,
        title,
        preview,
        json.dumps(messages),
    )


# ── Direct database tests (no socket layer) ─────────────────────────────


@pytest.mark.asyncio
class TestSaveConversation(BaseHandlerTest):
    """Test _save_conversation writes correct data to the conversations table."""

    def get_session_data(self, sid):
        return {"sid": sid, "user_id": TEST_USER_ID, "email": TEST_USER_EMAIL}

    async def test_save_new_conversation(self, real_database, frontend_sio, sid):
        """_save_conversation creates a new row with correct fields."""
        await _setup_test_user(real_database)

        handler = self.handlers[Handler.WORKFLOW_BUILDER]
        conv_id = f"conv-{uuid.uuid4()}"
        messages = [
            {"role": "user", "message": "Add a Slack node"},
            {"role": "assistant", "message": "", "edit_segments": [
                {"type": "text", "text": "Adding Slack..."},
                {"type": "events", "events": [{"type": "node_added", "nodeType": "automation-slack"}]},
            ]},
        ]

        await handler._save_conversation(conv_id, TEST_USER_ID, messages, title="Add Slack")
        await asyncio.sleep(0.3)

        row = await real_database.fetchrow(
            "SELECT * FROM conversations WHERE conversation_id = $1", conv_id
        )
        assert row is not None, "Conversation should be created"
        assert row["user_id"] == uuid.UUID(TEST_USER_ID)
        assert row["title"] == "Add Slack"
        assert row["preview"] == "Add a Slack node"
        assert row["deleted_at"] is None

        events = row["events"]
        if isinstance(events, str):
            events = json.loads(events)
        assert isinstance(events, list)
        assert len(events) == 2
        assert events[0]["role"] == "user"
        assert events[0]["message"] == "Add a Slack node"
        assert events[1]["role"] == "assistant"
        assert events[1]["edit_segments"][0]["type"] == "text"
        assert events[1]["edit_segments"][1]["type"] == "events"

    async def test_save_appends_to_existing_conversation(self, real_database, frontend_sio, sid):
        """Multi-turn: second call appends messages to existing events array."""
        await _setup_test_user(real_database)

        handler = self.handlers[Handler.WORKFLOW_BUILDER]
        conv_id = f"conv-{uuid.uuid4()}"

        # Turn 1
        turn1 = [
            {"role": "user", "message": "Add webhook"},
            {"role": "assistant", "message": "", "edit_segments": [{"type": "text", "text": "Done"}]},
        ]
        await handler._save_conversation(conv_id, TEST_USER_ID, turn1)
        await asyncio.sleep(0.3)

        # Turn 2
        turn2 = [
            {"role": "user", "message": "Now add Slack"},
            {"role": "assistant", "message": "", "edit_segments": [{"type": "text", "text": "Added"}]},
        ]
        await handler._save_conversation(conv_id, TEST_USER_ID, turn2)
        await asyncio.sleep(0.3)

        row = await real_database.fetchrow(
            "SELECT events, preview FROM conversations WHERE conversation_id = $1", conv_id
        )
        events = row["events"]
        if isinstance(events, str):
            events = json.loads(events)

        assert len(events) == 4, f"Expected 4 messages (2 turns × 2), got {len(events)}"
        assert events[0]["message"] == "Add webhook"
        assert events[2]["message"] == "Now add Slack"
        # Preview should be updated to the latest user message
        assert row["preview"] == "Now add Slack"

    async def test_save_auto_generates_title_from_prompt(self, real_database, frontend_sio, sid):
        """When title is None, it is derived from the first user message."""
        await _setup_test_user(real_database)

        handler = self.handlers[Handler.WORKFLOW_BUILDER]
        conv_id = f"conv-{uuid.uuid4()}"
        messages = [
            {"role": "user", "message": "Connect Google Sheets to Slack"},
            {"role": "assistant", "message": "", "edit_segments": []},
        ]
        await handler._save_conversation(conv_id, TEST_USER_ID, messages)
        await asyncio.sleep(0.3)

        row = await real_database.fetchrow(
            "SELECT title FROM conversations WHERE conversation_id = $1", conv_id
        )
        assert row["title"] == "Connect Google Sheets to Slack"

    async def test_save_truncates_long_preview(self, real_database, frontend_sio, sid):
        """Preview is truncated to 100 characters."""
        await _setup_test_user(real_database)

        handler = self.handlers[Handler.WORKFLOW_BUILDER]
        conv_id = f"conv-{uuid.uuid4()}"
        long_prompt = "A" * 200
        messages = [
            {"role": "user", "message": long_prompt},
            {"role": "assistant", "message": "", "edit_segments": []},
        ]
        await handler._save_conversation(conv_id, TEST_USER_ID, messages)
        await asyncio.sleep(0.3)

        row = await real_database.fetchrow(
            "SELECT preview, title FROM conversations WHERE conversation_id = $1", conv_id
        )
        assert len(row["preview"]) == 100
        assert len(row["title"]) == 50


# ── Handler tests (via socket events) ───────────────────────────────────


@pytest.mark.asyncio
class TestListConversations(BaseHandlerTest):
    """Test handle_list_conversations returns correct data via socket."""

    def get_session_data(self, sid):
        return {"sid": sid, "user_id": TEST_USER_ID, "email": TEST_USER_EMAIL}

    async def test_list_empty(self, real_database, frontend_sio, sid):
        """Returns empty list when user has no conversations."""
        await _setup_test_user(real_database)

        request = ListConversationsRequest(
            event_name="conversations:list",
            request_id="list-empty-1",
        )
        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.3)

        event = _find_conversation_list(
            self.get_main_api_emitted_events("conversations:list"), "list-empty-1"
        )
        assert event is not None, "Should receive conversations:list event"
        assert event["conversations"] == []

    async def test_list_returns_conversations_sorted_by_activity(
        self, real_database, frontend_sio, sid
    ):
        """Returns conversations ordered by last_activity DESC."""
        await _setup_test_user(real_database)

        # Insert two conversations with different timestamps
        conv_old = f"conv-old-{uuid.uuid4()}"
        conv_new = f"conv-new-{uuid.uuid4()}"

        await real_database.execute(
            """
            INSERT INTO conversations (conversation_id, user_id, title, preview, events, created_at, last_activity)
            VALUES ($1, $2, 'Old Conv', 'old', '[]'::jsonb, NOW() - interval '2 hours', NOW() - interval '2 hours')
            """,
            conv_old, TEST_USER_ID,
        )
        await real_database.execute(
            """
            INSERT INTO conversations (conversation_id, user_id, title, preview, events, created_at, last_activity)
            VALUES ($1, $2, 'New Conv', 'new', '[]'::jsonb, NOW(), NOW())
            """,
            conv_new, TEST_USER_ID,
        )

        request = ListConversationsRequest(
            event_name="conversations:list",
            request_id="list-sorted-1",
        )
        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.3)

        event = _find_conversation_list(
            self.get_main_api_emitted_events("conversations:list"), "list-sorted-1"
        )
        assert len(event["conversations"]) == 2
        assert event["conversations"][0]["conversation_id"] == conv_new
        assert event["conversations"][1]["conversation_id"] == conv_old

    async def test_list_excludes_deleted(self, real_database, frontend_sio, sid):
        """Soft-deleted conversations are excluded from list."""
        await _setup_test_user(real_database)

        conv_active = f"conv-active-{uuid.uuid4()}"
        conv_deleted = f"conv-deleted-{uuid.uuid4()}"

        await _insert_conversation(
            real_database, conv_active, TEST_USER_ID,
            [{"role": "user", "message": "active"}], title="Active",
        )
        await real_database.execute(
            """
            INSERT INTO conversations (conversation_id, user_id, title, preview, events, created_at, last_activity, deleted_at)
            VALUES ($1, $2, 'Deleted', 'deleted', '[]'::jsonb, NOW(), NOW(), NOW())
            """,
            conv_deleted, TEST_USER_ID,
        )

        request = ListConversationsRequest(
            event_name="conversations:list",
            request_id="list-no-deleted-1",
        )
        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.3)

        event = _find_conversation_list(
            self.get_main_api_emitted_events("conversations:list"), "list-no-deleted-1"
        )
        ids = [c["conversation_id"] for c in event["conversations"]]
        assert conv_active in ids
        assert conv_deleted not in ids

    async def test_list_excludes_other_users(self, real_database, frontend_sio, sid):
        """User only sees their own conversations."""
        await _setup_test_user(real_database)
        other_user = "00000000-0000-4000-8000-000000000099"
        await _setup_test_user(real_database, user_id=other_user, email="other@example.com")

        my_conv = f"conv-mine-{uuid.uuid4()}"
        other_conv = f"conv-other-{uuid.uuid4()}"

        await _insert_conversation(
            real_database, my_conv, TEST_USER_ID,
            [{"role": "user", "message": "mine"}], title="My conv",
        )
        await _insert_conversation(
            real_database, other_conv, other_user,
            [{"role": "user", "message": "theirs"}], title="Other conv",
        )

        request = ListConversationsRequest(
            event_name="conversations:list",
            request_id="list-user-iso-1",
        )
        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.3)

        event = _find_conversation_list(
            self.get_main_api_emitted_events("conversations:list"), "list-user-iso-1"
        )
        ids = [c["conversation_id"] for c in event["conversations"]]
        assert my_conv in ids
        assert other_conv not in ids

    async def test_list_returns_metadata_fields(self, real_database, frontend_sio, sid):
        """Each conversation in the list has required metadata fields."""
        await _setup_test_user(real_database)

        conv_id = f"conv-meta-{uuid.uuid4()}"
        await _insert_conversation(
            real_database, conv_id, TEST_USER_ID,
            [{"role": "user", "message": "test"}], title="Meta Test", preview="test",
        )

        request = ListConversationsRequest(
            event_name="conversations:list",
            request_id="list-meta-1",
        )
        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.3)

        event = _find_conversation_list(
            self.get_main_api_emitted_events("conversations:list"), "list-meta-1"
        )
        conv = event["conversations"][0]
        assert conv["conversation_id"] == conv_id
        assert conv["title"] == "Meta Test"
        assert conv["preview"] == "test"
        assert "last_activity" in conv
        assert "created_at" in conv


@pytest.mark.asyncio
class TestResumeConversation(BaseHandlerTest):
    """Test handle_resume_conversation restores messages correctly."""

    def get_session_data(self, sid):
        return {"sid": sid, "user_id": TEST_USER_ID, "email": TEST_USER_EMAIL}

    async def test_resume_returns_messages(self, real_database, frontend_sio, sid):
        """Resume returns the full events array as messages."""
        await _setup_test_user(real_database)

        conv_id = f"conv-resume-{uuid.uuid4()}"
        messages = [
            {"role": "user", "message": "Add Slack node"},
            {
                "role": "assistant",
                "message": "",
                "edit_segments": [
                    {"type": "text", "text": "I'll add a Slack notification node."},
                    {"type": "events", "events": [
                        {"type": "node_added", "nodeType": "automation-slack", "nodeLabel": "Slack", "status": "completed"},
                    ]},
                ],
            },
        ]
        await _insert_conversation(real_database, conv_id, TEST_USER_ID, messages, title="Slack")

        request = ResumeConversationRequest(
            event_name="conversation:resume",
            request_id="resume-1",
            session_id=conv_id,
        )
        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.3)

        resp = _find_response(self.get_main_api_emitted_events("response"), "resume-1")
        assert resp is not None, "Should receive response event"
        assert resp["data"]["session_id"] == conv_id

        restored = resp["data"]["messages"]
        assert len(restored) == 2
        assert restored[0]["role"] == "user"
        assert restored[0]["message"] == "Add Slack node"
        assert restored[1]["role"] == "assistant"
        assert restored[1]["edit_segments"][0]["type"] == "text"
        assert restored[1]["edit_segments"][1]["events"][0]["nodeType"] == "automation-slack"

    async def test_resume_multi_turn(self, real_database, frontend_sio, sid):
        """Resume returns all turns from a multi-turn conversation."""
        await _setup_test_user(real_database)

        conv_id = f"conv-multi-{uuid.uuid4()}"
        messages = [
            {"role": "user", "message": "Turn 1"},
            {"role": "assistant", "message": "", "edit_segments": [{"type": "text", "text": "Reply 1"}]},
            {"role": "user", "message": "Turn 2"},
            {"role": "assistant", "message": "", "edit_segments": [{"type": "text", "text": "Reply 2"}]},
        ]
        await _insert_conversation(real_database, conv_id, TEST_USER_ID, messages)

        request = ResumeConversationRequest(
            event_name="conversation:resume",
            request_id="resume-multi-1",
            session_id=conv_id,
        )
        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.3)

        resp = _find_response(self.get_main_api_emitted_events("response"), "resume-multi-1")
        assert len(resp["data"]["messages"]) == 4

    async def test_resume_nonexistent_returns_empty(self, real_database, frontend_sio, sid):
        """Resuming a conversation that doesn't exist returns empty messages."""
        await _setup_test_user(real_database)

        request = ResumeConversationRequest(
            event_name="conversation:resume",
            request_id="resume-missing-1",
            session_id="nonexistent-conv-id",
        )
        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.3)

        resp = _find_response(self.get_main_api_emitted_events("response"), "resume-missing-1")
        assert resp["data"]["messages"] == []

    async def test_resume_deleted_returns_empty(self, real_database, frontend_sio, sid):
        """Resuming a soft-deleted conversation returns empty messages."""
        await _setup_test_user(real_database)

        conv_id = f"conv-del-resume-{uuid.uuid4()}"
        await real_database.execute(
            """
            INSERT INTO conversations (conversation_id, user_id, title, preview, events, created_at, last_activity, deleted_at)
            VALUES ($1, $2, 'Deleted', '', $3::jsonb, NOW(), NOW(), NOW())
            """,
            conv_id, TEST_USER_ID, json.dumps([{"role": "user", "message": "old"}]),
        )

        request = ResumeConversationRequest(
            event_name="conversation:resume",
            request_id="resume-deleted-1",
            session_id=conv_id,
        )
        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.3)

        resp = _find_response(self.get_main_api_emitted_events("response"), "resume-deleted-1")
        assert resp["data"]["messages"] == []

    async def test_resume_other_users_conversation_returns_empty(
        self, real_database, frontend_sio, sid
    ):
        """Cannot resume another user's conversation."""
        await _setup_test_user(real_database)
        other_user = "00000000-0000-4000-8000-000000000099"
        await _setup_test_user(real_database, user_id=other_user, email="other@example.com")

        conv_id = f"conv-other-{uuid.uuid4()}"
        await _insert_conversation(
            real_database, conv_id, other_user,
            [{"role": "user", "message": "secret"}], title="Other",
        )

        request = ResumeConversationRequest(
            event_name="conversation:resume",
            request_id="resume-other-1",
            session_id=conv_id,
        )
        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.3)

        resp = _find_response(self.get_main_api_emitted_events("response"), "resume-other-1")
        assert resp["data"]["messages"] == []


@pytest.mark.asyncio
class TestDeleteConversation(BaseHandlerTest):
    """Test handle_delete_conversation soft-deletes correctly."""

    def get_session_data(self, sid):
        return {"sid": sid, "user_id": TEST_USER_ID, "email": TEST_USER_EMAIL}

    async def test_delete_soft_deletes(self, real_database, frontend_sio, sid):
        """Delete sets deleted_at instead of removing the row."""
        await _setup_test_user(real_database)

        conv_id = f"conv-del-{uuid.uuid4()}"
        await _insert_conversation(
            real_database, conv_id, TEST_USER_ID,
            [{"role": "user", "message": "doomed"}], title="To Delete",
        )

        request = DeleteConversationRequest(
            event_name="conversation:delete",
            request_id="delete-1",
            conversation_id=conv_id,
        )
        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.3)

        resp = _find_response(self.get_main_api_emitted_events("response"), "delete-1")
        assert resp is not None
        assert resp["data"]["success"] is True

        # Row still exists but has deleted_at set
        row = await real_database.fetchrow(
            "SELECT deleted_at FROM conversations WHERE conversation_id = $1", conv_id
        )
        assert row is not None, "Row should still exist (soft delete)"
        assert row["deleted_at"] is not None

    async def test_delete_nonexistent_returns_failure(self, real_database, frontend_sio, sid):
        """Deleting a nonexistent conversation returns not-found error."""
        await _setup_test_user(real_database)

        request = DeleteConversationRequest(
            event_name="conversation:delete",
            request_id="delete-missing-1",
            conversation_id="does-not-exist",
        )
        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.3)

        resp = _find_response(self.get_main_api_emitted_events("response"), "delete-missing-1")
        assert resp["data"]["success"] is False

    async def test_delete_other_users_conversation_returns_failure(
        self, real_database, frontend_sio, sid
    ):
        """Cannot delete another user's conversation."""
        await _setup_test_user(real_database)
        other_user = "00000000-0000-4000-8000-000000000099"
        await _setup_test_user(real_database, user_id=other_user, email="other@example.com")

        conv_id = f"conv-other-del-{uuid.uuid4()}"
        await _insert_conversation(
            real_database, conv_id, other_user,
            [{"role": "user", "message": "not yours"}], title="Other",
        )

        request = DeleteConversationRequest(
            event_name="conversation:delete",
            request_id="delete-other-1",
            conversation_id=conv_id,
        )
        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.3)

        resp = _find_response(self.get_main_api_emitted_events("response"), "delete-other-1")
        assert resp["data"]["success"] is False

        # Verify the row is NOT deleted
        row = await real_database.fetchrow(
            "SELECT deleted_at FROM conversations WHERE conversation_id = $1", conv_id
        )
        assert row["deleted_at"] is None

    async def test_delete_already_deleted_returns_failure(self, real_database, frontend_sio, sid):
        """Deleting an already-deleted conversation returns failure (idempotent guard)."""
        await _setup_test_user(real_database)

        conv_id = f"conv-double-del-{uuid.uuid4()}"
        await real_database.execute(
            """
            INSERT INTO conversations (conversation_id, user_id, title, preview, events, created_at, last_activity, deleted_at)
            VALUES ($1, $2, 'Already Deleted', '', '[]'::jsonb, NOW(), NOW(), NOW())
            """,
            conv_id, TEST_USER_ID,
        )

        request = DeleteConversationRequest(
            event_name="conversation:delete",
            request_id="delete-double-1",
            conversation_id=conv_id,
        )
        await send_event(frontend_sio, sid, request)
        await asyncio.sleep(0.3)

        resp = _find_response(self.get_main_api_emitted_events("response"), "delete-double-1")
        assert resp["data"]["success"] is False


# ── End-to-end lifecycle test ────────────────────────────────────────────


@pytest.mark.asyncio
class TestConversationLifecycle(BaseHandlerTest):
    """Full round-trip: save → list → resume → delete → verify gone from list."""

    def get_session_data(self, sid):
        return {"sid": sid, "user_id": TEST_USER_ID, "email": TEST_USER_EMAIL}

    async def test_full_lifecycle(self, real_database, frontend_sio, sid):
        """Save a conversation, list it, resume it, delete it, verify it's gone."""
        await _setup_test_user(real_database)

        conv_id = f"conv-lifecycle-{uuid.uuid4()}"
        messages = [
            {"role": "user", "message": "Build a webhook workflow"},
            {
                "role": "assistant",
                "message": "",
                "edit_segments": [
                    {"type": "text", "text": "Creating a webhook trigger..."},
                    {"type": "events", "events": [
                        {"type": "node_added", "nodeType": "trigger-webhook", "nodeLabel": "Webhook", "status": "completed"},
                        {"type": "node_added", "nodeType": "automation-slack", "nodeLabel": "Slack", "status": "completed"},
                        {"type": "edge_added", "source": "node-1", "target": "node-2", "status": "completed"},
                    ]},
                    {"type": "text", "text": "Done! Your workflow is ready."},
                ],
            },
        ]

        # 1. Save via handler method
        handler = self.handlers[Handler.WORKFLOW_BUILDER]
        await handler._save_conversation(conv_id, TEST_USER_ID, messages, title="Webhook Workflow")
        await asyncio.sleep(0.3)

        # 2. List — should contain our conversation
        await send_event(frontend_sio, sid, ListConversationsRequest(
            event_name="conversations:list", request_id="lc-lifecycle-list",
        ))
        await asyncio.sleep(0.3)

        list_event = _find_conversation_list(
            self.get_main_api_emitted_events("conversations:list"), "lc-lifecycle-list"
        )
        ids = [c["conversation_id"] for c in list_event["conversations"]]
        assert conv_id in ids
        matching = [c for c in list_event["conversations"] if c["conversation_id"] == conv_id][0]
        assert matching["title"] == "Webhook Workflow"

        # 3. Resume — should return full messages with editSegments
        await send_event(frontend_sio, sid, ResumeConversationRequest(
            event_name="conversation:resume", request_id="lc-lifecycle-resume", session_id=conv_id,
        ))
        await asyncio.sleep(0.3)

        resume_resp = _find_response(self.get_main_api_emitted_events("response"), "lc-lifecycle-resume")
        restored = resume_resp["data"]["messages"]
        assert len(restored) == 2
        assert restored[0]["role"] == "user"
        assert restored[1]["edit_segments"][1]["events"][0]["nodeType"] == "trigger-webhook"
        assert restored[1]["edit_segments"][2]["text"] == "Done! Your workflow is ready."

        # 4. Delete
        await send_event(frontend_sio, sid, DeleteConversationRequest(
            event_name="conversation:delete", request_id="lc-lifecycle-delete", conversation_id=conv_id,
        ))
        await asyncio.sleep(0.3)

        del_resp = _find_response(self.get_main_api_emitted_events("response"), "lc-lifecycle-delete")
        assert del_resp["data"]["success"] is True

        # 5. List again — should NOT contain the deleted conversation
        await send_event(frontend_sio, sid, ListConversationsRequest(
            event_name="conversations:list", request_id="lc-lifecycle-list2",
        ))
        await asyncio.sleep(0.3)

        list_event2 = _find_conversation_list(
            self.get_main_api_emitted_events("conversations:list"), "lc-lifecycle-list2"
        )
        ids2 = [c["conversation_id"] for c in list_event2["conversations"]]
        assert conv_id not in ids2

        # 6. Resume after delete — should return empty
        await send_event(frontend_sio, sid, ResumeConversationRequest(
            event_name="conversation:resume", request_id="lc-lifecycle-resume2", session_id=conv_id,
        ))
        await asyncio.sleep(0.3)

        resume_resp2 = _find_response(self.get_main_api_emitted_events("response"), "lc-lifecycle-resume2")
        assert resume_resp2["data"]["messages"] == []


@pytest.mark.asyncio
class TestEditSegmentsAccumulation(BaseHandlerTest):
    """Test that _save_conversation stores various editSegment shapes correctly."""

    def get_session_data(self, sid):
        return {"sid": sid, "user_id": TEST_USER_ID, "email": TEST_USER_EMAIL}

    async def test_mixed_text_and_events_segments(self, real_database, frontend_sio, sid):
        """Interleaved text + events segments survive round-trip through DB."""
        await _setup_test_user(real_database)

        conv_id = f"conv-segments-{uuid.uuid4()}"
        segments = [
            {"type": "text", "text": "First I'll add the trigger..."},
            {"type": "events", "events": [
                {"type": "node_added", "nodeType": "trigger-webhook", "status": "completed"},
            ]},
            {"type": "text", "text": "Now connecting to Slack..."},
            {"type": "events", "events": [
                {"type": "node_added", "nodeType": "automation-slack", "status": "completed"},
                {"type": "edge_added", "source": "n1", "target": "n2", "status": "completed"},
            ]},
            {"type": "text", "text": "All done!"},
        ]
        messages = [
            {"role": "user", "message": "Build it"},
            {"role": "assistant", "message": "", "edit_segments": segments},
        ]

        handler = self.handlers[Handler.WORKFLOW_BUILDER]
        await handler._save_conversation(conv_id, TEST_USER_ID, messages)
        await asyncio.sleep(0.3)

        # Resume and verify round-trip fidelity
        await send_event(frontend_sio, sid, ResumeConversationRequest(
            event_name="conversation:resume", request_id="seg-roundtrip", session_id=conv_id,
        ))
        await asyncio.sleep(0.3)

        resp = _find_response(self.get_main_api_emitted_events("response"), "seg-roundtrip")
        restored_segments = resp["data"]["messages"][1]["edit_segments"]
        assert len(restored_segments) == 5
        assert restored_segments[0]["type"] == "text"
        assert restored_segments[1]["type"] == "events"
        assert len(restored_segments[1]["events"]) == 1
        assert restored_segments[3]["type"] == "events"
        assert len(restored_segments[3]["events"]) == 2
        assert restored_segments[4]["text"] == "All done!"

    async def test_empty_segments_still_saved(self, real_database, frontend_sio, sid):
        """Conversations with empty edit_segments are stored and retrievable."""
        await _setup_test_user(real_database)

        conv_id = f"conv-empty-seg-{uuid.uuid4()}"
        messages = [
            {"role": "user", "message": "Help"},
            {"role": "assistant", "message": "I can help!", "edit_segments": []},
        ]

        handler = self.handlers[Handler.WORKFLOW_BUILDER]
        await handler._save_conversation(conv_id, TEST_USER_ID, messages)
        await asyncio.sleep(0.3)

        await send_event(frontend_sio, sid, ResumeConversationRequest(
            event_name="conversation:resume", request_id="empty-seg-1", session_id=conv_id,
        ))
        await asyncio.sleep(0.3)

        resp = _find_response(self.get_main_api_emitted_events("response"), "empty-seg-1")
        assert resp["data"]["messages"][1]["edit_segments"] == []
        assert resp["data"]["messages"][1]["message"] == "I can help!"


# ── Conversation history loading tests ────────────────────────────────────


@pytest.mark.asyncio
class TestConversationHistoryLoading(BaseHandlerTest):
    """Test _load_conversation_history and _summarize_assistant_turn for LLM context."""

    def get_session_data(self, sid):
        return {"sid": sid, "user_id": TEST_USER_ID, "email": TEST_USER_EMAIL}

    async def test_load_empty_history(self, real_database, frontend_sio, sid):
        """Returns empty list when no conversation exists."""
        await _setup_test_user(real_database)

        handler = self.handlers[Handler.WORKFLOW_BUILDER]
        result = await handler._load_conversation_history("nonexistent-id", TEST_USER_ID)
        assert result == []

    async def test_load_single_turn_history(self, real_database, frontend_sio, sid):
        """Single user+assistant pair returns 2 LLM messages."""
        await _setup_test_user(real_database)

        conv_id = f"conv-hist-single-{uuid.uuid4()}"
        messages = [
            {"role": "user", "message": "Add a webhook trigger"},
            {"role": "assistant", "message": "", "edit_segments": [
                {"type": "text", "text": "I'll add a webhook trigger node."},
                {"type": "events", "events": [
                    {"type": "node_added", "nodeType": "trigger-webhook", "nodeLabel": "Webhook", "status": "completed"},
                ]},
            ]},
        ]
        await _insert_conversation(real_database, conv_id, TEST_USER_ID, messages)

        handler = self.handlers[Handler.WORKFLOW_BUILDER]
        history = await handler._load_conversation_history(conv_id, TEST_USER_ID)

        assert len(history) == 2
        assert history[0]["role"] == "user"
        assert history[0]["content"] == "Add a webhook trigger"
        assert history[1]["role"] == "assistant"
        assert "webhook trigger node" in history[1]["content"]
        assert "[Added node: Webhook (trigger-webhook)]" in history[1]["content"]

    async def test_load_multi_turn_history(self, real_database, frontend_sio, sid):
        """Multiple turns return all messages in order."""
        await _setup_test_user(real_database)

        conv_id = f"conv-hist-multi-{uuid.uuid4()}"
        messages = [
            {"role": "user", "message": "Add a webhook"},
            {"role": "assistant", "message": "", "edit_segments": [
                {"type": "text", "text": "Added webhook."},
            ]},
            {"role": "user", "message": "Now add Slack"},
            {"role": "assistant", "message": "", "edit_segments": [
                {"type": "text", "text": "Added Slack."},
                {"type": "events", "events": [
                    {"type": "node_added", "nodeType": "automation-slack", "nodeLabel": "Slack", "status": "completed"},
                ]},
            ]},
        ]
        await _insert_conversation(real_database, conv_id, TEST_USER_ID, messages)

        handler = self.handlers[Handler.WORKFLOW_BUILDER]
        history = await handler._load_conversation_history(conv_id, TEST_USER_ID)

        assert len(history) == 4
        assert history[0] == {"role": "user", "content": "Add a webhook"}
        assert history[1] == {"role": "assistant", "content": "Added webhook."}
        assert history[2] == {"role": "user", "content": "Now add Slack"}
        assert "Added Slack." in history[3]["content"]
        assert "[Added node: Slack (automation-slack)]" in history[3]["content"]

    async def test_load_deleted_conversation_returns_empty(self, real_database, frontend_sio, sid):
        """Deleted conversations are not loaded."""
        await _setup_test_user(real_database)

        conv_id = f"conv-hist-del-{uuid.uuid4()}"
        await real_database.execute(
            """
            INSERT INTO conversations (conversation_id, user_id, title, preview, events, created_at, last_activity, deleted_at)
            VALUES ($1, $2, 'Deleted', '', $3::jsonb, NOW(), NOW(), NOW())
            """,
            conv_id, TEST_USER_ID, json.dumps([{"role": "user", "message": "old"}]),
        )

        handler = self.handlers[Handler.WORKFLOW_BUILDER]
        result = await handler._load_conversation_history(conv_id, TEST_USER_ID)
        assert result == []

    async def test_load_other_users_history_returns_empty(self, real_database, frontend_sio, sid):
        """Cannot load another user's conversation history."""
        await _setup_test_user(real_database)
        other_user = "00000000-0000-4000-8000-000000000099"
        await _setup_test_user(real_database, user_id=other_user, email="other@example.com")

        conv_id = f"conv-hist-other-{uuid.uuid4()}"
        await _insert_conversation(
            real_database, conv_id, other_user,
            [{"role": "user", "message": "secret"}],
        )

        handler = self.handlers[Handler.WORKFLOW_BUILDER]
        result = await handler._load_conversation_history(conv_id, TEST_USER_ID)
        assert result == []

    def test_summarize_text_only(self):
        """Text-only edit_segments produce plain text summary."""
        from wss.handlers.workflow_builder_handler import WorkflowBuilderHandler

        msg = {
            "role": "assistant",
            "message": "",
            "edit_segments": [
                {"type": "text", "text": "I'll add a trigger."},
                {"type": "text", "text": "Then connect it to Slack."},
            ],
        }
        result = WorkflowBuilderHandler._summarize_assistant_turn(msg)
        assert "I'll add a trigger." in result
        assert "Then connect it to Slack." in result

    def test_summarize_events_produces_readable_text(self):
        """Event segments are summarized as readable action descriptions."""
        from wss.handlers.workflow_builder_handler import WorkflowBuilderHandler

        msg = {
            "role": "assistant",
            "message": "",
            "edit_segments": [
                {"type": "text", "text": "Adding nodes..."},
                {"type": "events", "events": [
                    {"type": "node_added", "nodeType": "trigger-webhook", "nodeLabel": "Webhook", "status": "completed"},
                    {"type": "node_added", "nodeType": "automation-slack", "nodeLabel": "Slack", "status": "completed"},
                    {"type": "edge_added", "sourceNodeLabel": "Webhook", "targetNodeLabel": "Slack", "status": "completed"},
                ]},
                {"type": "text", "text": "All connected!"},
            ],
        }
        result = WorkflowBuilderHandler._summarize_assistant_turn(msg)
        assert "Adding nodes..." in result
        assert "[Added node: Webhook (trigger-webhook)]" in result
        assert "[Added node: Slack (automation-slack)]" in result
        assert "[Added edge: Webhook → Slack]" in result
        assert "All connected!" in result

    def test_summarize_node_removed_and_updated(self):
        """Node removal and update events are summarized correctly."""
        from wss.handlers.workflow_builder_handler import WorkflowBuilderHandler

        msg = {
            "role": "assistant",
            "message": "",
            "edit_segments": [
                {"type": "events", "events": [
                    {"type": "node_removed", "nodeId": "node-123", "status": "completed"},
                    {"type": "node_updated", "nodeId": "node-456", "status": "completed"},
                    {"type": "edge_removed", "edgeId": "edge-789", "status": "completed"},
                ]},
            ],
        }
        result = WorkflowBuilderHandler._summarize_assistant_turn(msg)
        assert "[Removed node: node-123]" in result
        assert "[Updated node: node-456]" in result
        assert "[Removed edge: edge-789]" in result

    def test_summarize_with_top_level_message(self):
        """Top-level message field is included in summary."""
        from wss.handlers.workflow_builder_handler import WorkflowBuilderHandler

        msg = {
            "role": "assistant",
            "message": "Here's what I did:",
            "edit_segments": [
                {"type": "text", "text": "Added a node."},
            ],
        }
        result = WorkflowBuilderHandler._summarize_assistant_turn(msg)
        assert result.startswith("Here's what I did:")
        assert "Added a node." in result

    def test_summarize_empty_message_returns_empty(self):
        """Empty assistant message with no segments returns empty string."""
        from wss.handlers.workflow_builder_handler import WorkflowBuilderHandler

        msg = {"role": "assistant", "message": "", "edit_segments": []}
        result = WorkflowBuilderHandler._summarize_assistant_turn(msg)
        assert result == ""

    async def test_load_history_uses_llm_messages_when_available(self, real_database, frontend_sio, sid):
        """When llm_messages is present, raw LLM messages are used instead of summaries."""
        await _setup_test_user(real_database)

        conv_id = f"conv-hist-llm-{uuid.uuid4()}"
        raw_assistant_response = (
            'I\'ll replace Google Sheets with Excel.\n'
            '<remove_node name="sheets" />\n'
            '<add_node type="automation-excel" name="excel" label="Excel" goal="Export data" />\n'
            '<add_edge from="trigger" to="excel" />\n'
            '<done/>'
        )
        raw_execution_result = (
            '[System: Execution Result]\n'
            'Removed node sheets. Added node excel (automation-excel). Added edge trigger→excel.'
        )
        messages = [
            {"role": "user", "message": "Replace Google Sheets with Excel"},
            {
                "role": "assistant",
                "message": "",
                "edit_segments": [
                    {"type": "text", "text": "I'll replace Google Sheets with Excel."},
                    {"type": "events", "events": [
                        {"type": "node_removed", "nodeId": "sheets", "status": "completed"},
                        {"type": "node_added", "nodeType": "automation-excel", "nodeLabel": "Excel", "status": "completed"},
                    ]},
                ],
                "llm_messages": [
                    {"role": "assistant", "content": raw_assistant_response},
                    {"role": "user", "content": raw_execution_result},
                ],
            },
        ]
        await _insert_conversation(real_database, conv_id, TEST_USER_ID, messages)

        handler = self.handlers[Handler.WORKFLOW_BUILDER]
        history = await handler._load_conversation_history(conv_id, TEST_USER_ID)

        # Should have: user + assistant (raw) + execution result = 3 messages
        assert len(history) == 3
        assert history[0] == {"role": "user", "content": "Replace Google Sheets with Excel"}
        # Raw assistant response includes XML commands
        assert '<remove_node name="sheets" />' in history[1]["content"]
        assert '<add_node type="automation-excel"' in history[1]["content"]
        assert history[1]["role"] == "assistant"
        # Execution result is included
        assert "Execution Result" in history[2]["content"]
        assert history[2]["role"] == "user"

    async def test_load_history_falls_back_to_summary_without_llm_messages(
        self, real_database, frontend_sio, sid
    ):
        """Older conversations without llm_messages fall back to summarized text."""
        await _setup_test_user(real_database)

        conv_id = f"conv-hist-fallback-{uuid.uuid4()}"
        messages = [
            {"role": "user", "message": "Add a webhook"},
            {
                "role": "assistant",
                "message": "",
                "edit_segments": [
                    {"type": "text", "text": "Added a webhook trigger."},
                    {"type": "events", "events": [
                        {"type": "node_added", "nodeType": "trigger-webhook", "nodeLabel": "Webhook", "status": "completed"},
                    ]},
                ],
                # No llm_messages — older format
            },
        ]
        await _insert_conversation(real_database, conv_id, TEST_USER_ID, messages)

        handler = self.handlers[Handler.WORKFLOW_BUILDER]
        history = await handler._load_conversation_history(conv_id, TEST_USER_ID)

        # Fallback: user + summarized assistant = 2 messages
        assert len(history) == 2
        assert history[0] == {"role": "user", "content": "Add a webhook"}
        assert "Added a webhook trigger." in history[1]["content"]
        assert "[Added node: Webhook (trigger-webhook)]" in history[1]["content"]

    async def test_load_multi_turn_with_llm_messages(self, real_database, frontend_sio, sid):
        """Multi-turn conversation with llm_messages produces correct message ordering."""
        await _setup_test_user(real_database)

        conv_id = f"conv-hist-multi-llm-{uuid.uuid4()}"
        messages = [
            {"role": "user", "message": "Add a webhook"},
            {
                "role": "assistant", "message": "", "edit_segments": [],
                "llm_messages": [
                    {"role": "assistant", "content": '<add_node type="trigger-webhook" name="wh" />\n<done/>'},
                    {"role": "user", "content": "[System: Execution Result]\nAdded webhook."},
                ],
            },
            {"role": "user", "message": "Now add Slack"},
            {
                "role": "assistant", "message": "", "edit_segments": [],
                "llm_messages": [
                    {"role": "assistant", "content": '<add_node type="automation-slack" name="slack" />\n<done/>'},
                    {"role": "user", "content": "[System: Execution Result]\nAdded slack."},
                ],
            },
        ]
        await _insert_conversation(real_database, conv_id, TEST_USER_ID, messages)

        handler = self.handlers[Handler.WORKFLOW_BUILDER]
        history = await handler._load_conversation_history(conv_id, TEST_USER_ID)

        # 2 turns × (user + assistant + exec_result) = 6 messages
        assert len(history) == 6
        assert history[0] == {"role": "user", "content": "Add a webhook"}
        assert "trigger-webhook" in history[1]["content"]
        assert history[2]["content"] == "[System: Execution Result]\nAdded webhook."
        assert history[3] == {"role": "user", "content": "Now add Slack"}
        assert "automation-slack" in history[4]["content"]
