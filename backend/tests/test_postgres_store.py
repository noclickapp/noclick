"""
Tests for the `conversations` table's SQL surface.

Validates that conversation events + agent state can be written to and
read back from PostgreSQL — the same table now backs both the chat
UI's `events` array (rendered by the frontend) and the new agent's
`metadata.sdk_history` (consumed by `coder/openai_agent/session.py`).
"""

import pickle
import base64
import uuid

import pytest
import pytest_asyncio

from tests.fixtures.real_db_fixture import real_database  # noqa: F401

TEST_USER_ID = "00000000-0000-0000-0000-000000000001"
TEST_WORKFLOW_ID = str(uuid.uuid4())
TEST_NODE_ID = "agent-node-abc123"


async def _setup_test_user(db, user_id=TEST_USER_ID):
    """Ensure test user exists and clean up stale conversations."""
    await db.execute(
        """INSERT INTO auth.users (id, email) VALUES ($1, $2)
           ON CONFLICT (id) DO NOTHING""",
        user_id, "test@example.com",
    )
    await db.execute("DELETE FROM conversations WHERE user_id = $1", user_id)


def _make_event(event_id: int, action: str = "message", source: str = "user", content: str = "hello") -> dict:
    """Create a minimal OpenHands-style event dict."""
    return {
        "id": event_id,
        "action": action,
        "_source": source,
        "args": {"content": content},
        "timestamp": "2025-01-01T00:00:00Z",
    }


def _make_agent_state(iteration: int = 5, history_len: int = 10) -> dict:
    """Create a minimal agent state dict that mimics what State.save_to_session produces."""
    return {
        "iteration": iteration,
        "history_length": history_len,
        "agent_state": "FINISHED",
        "resume_state": None,
    }


# ============================================================================
# Test: conversation row lifecycle (insert, append events, soft delete)
# ============================================================================


@pytest.mark.asyncio
class TestConversationRowLifecycle:
    """Tests for basic conversation row operations in the conversations table."""

    async def test_insert_new_conversation(self, postgres_db, real_database):
        """A new conversation row can be created with all required fields."""
        await _setup_test_user(real_database)

        conv_id = f"conv-{uuid.uuid4()}"
        await postgres_db.execute(
            """
            INSERT INTO conversations (conversation_id, user_id, workflow_id, node_id)
            VALUES ($1, $2, $3, $4)
            """,
            conv_id, TEST_USER_ID, TEST_WORKFLOW_ID, TEST_NODE_ID,
        )

        row = await postgres_db.fetchrow(
            "SELECT * FROM conversations WHERE conversation_id = $1", conv_id,
        )
        assert row is not None
        assert row["conversation_id"] == conv_id
        assert str(row["user_id"]) == TEST_USER_ID
        assert row["workflow_id"] == TEST_WORKFLOW_ID
        assert row["node_id"] == TEST_NODE_ID
        assert row["events"] == []
        assert row["deleted_at"] is None

    async def test_append_events_to_conversation(self, postgres_db, real_database):
        """Events can be appended one-by-one to the JSONB array."""
        await _setup_test_user(real_database)

        conv_id = f"conv-{uuid.uuid4()}"
        await postgres_db.execute(
            "INSERT INTO conversations (conversation_id, user_id) VALUES ($1, $2)",
            conv_id, TEST_USER_ID,
        )

        # Append 3 events sequentially
        for i in range(3):
            event = _make_event(i, content=f"message {i}")
            await postgres_db.execute(
                """
                UPDATE conversations
                SET events = events || jsonb_build_array($1::jsonb),
                    last_activity = NOW()
                WHERE conversation_id = $2
                """,
                event, conv_id,
            )

        row = await postgres_db.fetchrow(
            "SELECT events FROM conversations WHERE conversation_id = $1", conv_id,
        )
        events = row["events"]
        assert len(events) == 3
        assert events[0]["args"]["content"] == "message 0"
        assert events[1]["args"]["content"] == "message 1"
        assert events[2]["args"]["content"] == "message 2"

    async def test_soft_delete_hides_conversation(self, postgres_db, real_database):
        """Soft-deleted conversations are excluded from active queries."""
        await _setup_test_user(real_database)

        conv_id = f"conv-{uuid.uuid4()}"
        await postgres_db.execute(
            "INSERT INTO conversations (conversation_id, user_id) VALUES ($1, $2)",
            conv_id, TEST_USER_ID,
        )

        # Soft delete
        await postgres_db.execute(
            "UPDATE conversations SET deleted_at = NOW() WHERE conversation_id = $1",
            conv_id,
        )

        # Should not appear in active conversation queries
        row = await postgres_db.fetchrow(
            "SELECT * FROM conversations WHERE conversation_id = $1 AND deleted_at IS NULL",
            conv_id,
        )
        assert row is None

        # But should still exist in the table
        row = await postgres_db.fetchrow(
            "SELECT * FROM conversations WHERE conversation_id = $1",
            conv_id,
        )
        assert row is not None
        assert row["deleted_at"] is not None

    async def test_conversation_workflow_association(self, postgres_db, real_database):
        """Conversations can be queried by workflow_id for cleanup."""
        await _setup_test_user(real_database)

        workflow_id = str(uuid.uuid4())

        # Create 3 conversations for the same workflow
        conv_ids = []
        for i in range(3):
            conv_id = f"conv-wf-{uuid.uuid4()}"
            conv_ids.append(conv_id)
            await postgres_db.execute(
                """
                INSERT INTO conversations (conversation_id, user_id, workflow_id, node_id)
                VALUES ($1, $2, $3, $4)
                """,
                conv_id, TEST_USER_ID, workflow_id, f"node-{i}",
            )

        # Create a conversation for a different workflow
        other_conv = f"conv-other-{uuid.uuid4()}"
        await postgres_db.execute(
            """
            INSERT INTO conversations (conversation_id, user_id, workflow_id, node_id)
            VALUES ($1, $2, $3, $4)
            """,
            other_conv, TEST_USER_ID, str(uuid.uuid4()), "node-other",
        )

        # Query by workflow_id
        rows = await postgres_db.fetch(
            "SELECT conversation_id FROM conversations WHERE workflow_id = $1",
            workflow_id,
        )
        found_ids = {row["conversation_id"] for row in rows}
        assert found_ids == set(conv_ids)
        assert other_conv not in found_ids

    async def test_delete_conversations_by_workflow(self, postgres_db, real_database):
        """All conversations for a workflow can be soft-deleted in one query."""
        await _setup_test_user(real_database)

        workflow_id = str(uuid.uuid4())
        for i in range(3):
            await postgres_db.execute(
                """
                INSERT INTO conversations (conversation_id, user_id, workflow_id)
                VALUES ($1, $2, $3)
                """,
                f"conv-del-{uuid.uuid4()}", TEST_USER_ID, workflow_id,
            )

        # Soft-delete all conversations for this workflow
        await postgres_db.execute(
            """
            UPDATE conversations SET deleted_at = NOW()
            WHERE workflow_id = $1 AND deleted_at IS NULL
            """,
            workflow_id,
        )

        active = await postgres_db.fetch(
            "SELECT * FROM conversations WHERE workflow_id = $1 AND deleted_at IS NULL",
            workflow_id,
        )
        assert len(active) == 0


# ============================================================================
# Test: agent state persistence (store & restore pickled state via Postgres)
# ============================================================================


@pytest.mark.asyncio
class TestAgentStatePersistence:
    """Tests for storing and restoring agent state (previously agent_state.pkl on filesystem)."""

    async def test_save_agent_state(self, postgres_db, real_database):
        """Agent state can be saved as base64-encoded pickled bytes."""
        await _setup_test_user(real_database)

        conv_id = f"conv-state-{uuid.uuid4()}"
        await postgres_db.execute(
            "INSERT INTO conversations (conversation_id, user_id) VALUES ($1, $2)",
            conv_id, TEST_USER_ID,
        )

        # Simulate what State.save_to_session does: pickle + base64 encode
        state_data = _make_agent_state(iteration=7, history_len=20)
        pickled = pickle.dumps(state_data)
        encoded = base64.b64encode(pickled).decode("utf-8")

        await postgres_db.execute(
            "UPDATE conversations SET agent_state = $1 WHERE conversation_id = $2",
            encoded, conv_id,
        )

        row = await postgres_db.fetchrow(
            "SELECT agent_state FROM conversations WHERE conversation_id = $1", conv_id,
        )
        assert row["agent_state"] is not None

        # Decode and verify
        restored = pickle.loads(base64.b64decode(row["agent_state"]))
        assert restored["iteration"] == 7
        assert restored["history_length"] == 20
        assert restored["agent_state"] == "FINISHED"

    async def test_restore_agent_state_returns_none_for_new_conversation(self, postgres_db, real_database):
        """A conversation with no saved state returns NULL agent_state."""
        await _setup_test_user(real_database)

        conv_id = f"conv-nostate-{uuid.uuid4()}"
        await postgres_db.execute(
            "INSERT INTO conversations (conversation_id, user_id) VALUES ($1, $2)",
            conv_id, TEST_USER_ID,
        )

        row = await postgres_db.fetchrow(
            "SELECT agent_state FROM conversations WHERE conversation_id = $1", conv_id,
        )
        assert row["agent_state"] is None

    async def test_overwrite_agent_state(self, postgres_db, real_database):
        """Agent state can be overwritten on subsequent saves."""
        await _setup_test_user(real_database)

        conv_id = f"conv-overwrite-{uuid.uuid4()}"
        await postgres_db.execute(
            "INSERT INTO conversations (conversation_id, user_id) VALUES ($1, $2)",
            conv_id, TEST_USER_ID,
        )

        # Save initial state
        state_v1 = _make_agent_state(iteration=3)
        encoded_v1 = base64.b64encode(pickle.dumps(state_v1)).decode("utf-8")
        await postgres_db.execute(
            "UPDATE conversations SET agent_state = $1 WHERE conversation_id = $2",
            encoded_v1, conv_id,
        )

        # Save updated state
        state_v2 = _make_agent_state(iteration=10)
        encoded_v2 = base64.b64encode(pickle.dumps(state_v2)).decode("utf-8")
        await postgres_db.execute(
            "UPDATE conversations SET agent_state = $1 WHERE conversation_id = $2",
            encoded_v2, conv_id,
        )

        # Should have the latest state
        row = await postgres_db.fetchrow(
            "SELECT agent_state FROM conversations WHERE conversation_id = $1", conv_id,
        )
        restored = pickle.loads(base64.b64decode(row["agent_state"]))
        assert restored["iteration"] == 10


# ============================================================================
# Test: event read-back (simulating FileStore.read / FileStore.list)
# ============================================================================


@pytest.mark.asyncio
class TestEventReadBack:
    """Tests for reading events back from Postgres (replaces filesystem reads)."""

    async def test_read_single_event_by_index(self, postgres_db, real_database):
        """Individual events can be read by their index in the JSONB array."""
        await _setup_test_user(real_database)

        conv_id = f"conv-read-{uuid.uuid4()}"
        await postgres_db.execute(
            "INSERT INTO conversations (conversation_id, user_id) VALUES ($1, $2)",
            conv_id, TEST_USER_ID,
        )

        # Insert 5 events
        for i in range(5):
            event = _make_event(i, content=f"event-{i}")
            await postgres_db.execute(
                """
                UPDATE conversations
                SET events = events || jsonb_build_array($1::jsonb)
                WHERE conversation_id = $2
                """,
                event, conv_id,
            )

        # Read event at index 3 using JSONB array indexing
        row = await postgres_db.fetchrow(
            "SELECT events->3 as event FROM conversations WHERE conversation_id = $1",
            conv_id,
        )
        event = row["event"]
        assert event["id"] == 3
        assert event["args"]["content"] == "event-3"

    async def test_list_event_count(self, postgres_db, real_database):
        """Can determine event count (equivalent to FileStore.list for events dir)."""
        await _setup_test_user(real_database)

        conv_id = f"conv-count-{uuid.uuid4()}"
        await postgres_db.execute(
            "INSERT INTO conversations (conversation_id, user_id) VALUES ($1, $2)",
            conv_id, TEST_USER_ID,
        )

        for i in range(7):
            event = _make_event(i)
            await postgres_db.execute(
                """
                UPDATE conversations
                SET events = events || jsonb_build_array($1::jsonb)
                WHERE conversation_id = $2
                """,
                event, conv_id,
            )

        row = await postgres_db.fetchrow(
            "SELECT jsonb_array_length(events) as count FROM conversations WHERE conversation_id = $1",
            conv_id,
        )
        assert row["count"] == 7

    async def test_read_all_events_preserves_order(self, postgres_db, real_database):
        """All events can be read back in insertion order."""
        await _setup_test_user(real_database)

        conv_id = f"conv-order-{uuid.uuid4()}"
        await postgres_db.execute(
            "INSERT INTO conversations (conversation_id, user_id) VALUES ($1, $2)",
            conv_id, TEST_USER_ID,
        )

        for i in range(10):
            event = _make_event(i, content=f"ordered-{i}")
            await postgres_db.execute(
                """
                UPDATE conversations
                SET events = events || jsonb_build_array($1::jsonb)
                WHERE conversation_id = $2
                """,
                event, conv_id,
            )

        row = await postgres_db.fetchrow(
            "SELECT events FROM conversations WHERE conversation_id = $1", conv_id,
        )
        events = row["events"]
        assert len(events) == 10
        for i, event in enumerate(events):
            assert event["id"] == i
            assert event["args"]["content"] == f"ordered-{i}"

    async def test_read_event_from_nonexistent_conversation(self, postgres_db, real_database):
        """Reading from a nonexistent conversation returns None."""
        await _setup_test_user(real_database)

        row = await postgres_db.fetchrow(
            "SELECT events FROM conversations WHERE conversation_id = $1",
            "nonexistent-conv-id",
        )
        assert row is None

    async def test_read_events_with_mixed_types(self, postgres_db, real_database):
        """Events of different types (message, observation, action) are preserved."""
        await _setup_test_user(real_database)

        conv_id = f"conv-mixed-{uuid.uuid4()}"
        await postgres_db.execute(
            "INSERT INTO conversations (conversation_id, user_id) VALUES ($1, $2)",
            conv_id, TEST_USER_ID,
        )

        events_data = [
            {"id": 0, "action": "message", "_source": "user", "args": {"content": "hello"}},
            {"id": 1, "action": "run", "_source": "agent", "args": {"command": "ls -la"}},
            {"id": 2, "observation": "run", "_source": "agent", "content": "file1.txt\nfile2.txt"},
            {"id": 3, "action": "message", "_source": "agent", "args": {"content": "Found 2 files"}},
        ]

        for event in events_data:
            await postgres_db.execute(
                """
                UPDATE conversations
                SET events = events || jsonb_build_array($1::jsonb)
                WHERE conversation_id = $2
                """,
                event, conv_id,
            )

        row = await postgres_db.fetchrow(
            "SELECT events FROM conversations WHERE conversation_id = $1", conv_id,
        )
        stored = row["events"]
        assert len(stored) == 4
        assert stored[0]["action"] == "message"
        assert stored[1]["action"] == "run"
        assert stored[2]["observation"] == "run"
        assert stored[3]["args"]["content"] == "Found 2 files"


# ============================================================================
# Test: full round-trip (write events + state, read back, verify integrity)
# ============================================================================


@pytest.mark.asyncio
class TestFullRoundTrip:
    """End-to-end tests simulating the full write→read cycle for agent conversations."""

    async def test_full_conversation_round_trip(self, postgres_db, real_database):
        """Complete conversation with events and state can be stored and restored."""
        await _setup_test_user(real_database)

        conv_id = f"conv-roundtrip-{uuid.uuid4()}"
        workflow_id = str(uuid.uuid4())
        node_id = "agent-roundtrip-1"

        # 1. Create conversation
        await postgres_db.execute(
            """
            INSERT INTO conversations (conversation_id, user_id, workflow_id, node_id, title, preview)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            conv_id, TEST_USER_ID, workflow_id, node_id, "Test Chat", "User says hello",
        )

        # 2. Append events (simulating a multi-turn conversation)
        events_data = [
            _make_event(0, "message", "user", "What is 2+2?"),
            _make_event(1, "message", "agent", "2+2 equals 4."),
            _make_event(2, "message", "user", "And 3+3?"),
            _make_event(3, "message", "agent", "3+3 equals 6."),
        ]
        for event in events_data:
            await postgres_db.execute(
                """
                UPDATE conversations
                SET events = events || jsonb_build_array($1::jsonb),
                    last_activity = NOW()
                WHERE conversation_id = $2
                """,
                event, conv_id,
            )

        # 3. Save agent state
        state = {"iteration": 4, "history_length": 4, "agent_state": "FINISHED"}
        encoded_state = base64.b64encode(pickle.dumps(state)).decode("utf-8")
        await postgres_db.execute(
            "UPDATE conversations SET agent_state = $1 WHERE conversation_id = $2",
            encoded_state, conv_id,
        )

        # 4. Read everything back (simulating state restoration)
        row = await postgres_db.fetchrow(
            """
            SELECT conversation_id, user_id, workflow_id, node_id,
                   title, preview, events, agent_state,
                   jsonb_array_length(events) as event_count
            FROM conversations
            WHERE conversation_id = $1 AND deleted_at IS NULL
            """,
            conv_id,
        )

        # 5. Verify everything
        assert row["conversation_id"] == conv_id
        assert row["workflow_id"] == workflow_id
        assert row["node_id"] == node_id
        assert row["title"] == "Test Chat"
        assert row["event_count"] == 4

        # Verify events
        events = row["events"]
        assert events[0]["args"]["content"] == "What is 2+2?"
        assert events[3]["args"]["content"] == "3+3 equals 6."

        # Verify agent state
        restored_state = pickle.loads(base64.b64decode(row["agent_state"]))
        assert restored_state["iteration"] == 4

    async def test_conversation_resume_after_soft_delete_fails(self, postgres_db, real_database):
        """Soft-deleted conversations cannot be resumed."""
        await _setup_test_user(real_database)

        conv_id = f"conv-resume-del-{uuid.uuid4()}"
        await postgres_db.execute(
            "INSERT INTO conversations (conversation_id, user_id) VALUES ($1, $2)",
            conv_id, TEST_USER_ID,
        )

        # Add events
        event = _make_event(0, content="important message")
        await postgres_db.execute(
            """
            UPDATE conversations
            SET events = events || jsonb_build_array($1::jsonb)
            WHERE conversation_id = $2
            """,
            event, conv_id,
        )

        # Soft delete
        await postgres_db.execute(
            "UPDATE conversations SET deleted_at = NOW() WHERE conversation_id = $1",
            conv_id,
        )

        # Attempting to read active conversation should return None
        row = await postgres_db.fetchrow(
            "SELECT events FROM conversations WHERE conversation_id = $1 AND deleted_at IS NULL",
            conv_id,
        )
        assert row is None

    async def test_no_event_append_to_deleted_conversation(self, postgres_db, real_database):
        """Events cannot be appended to soft-deleted conversations."""
        await _setup_test_user(real_database)

        conv_id = f"conv-no-append-{uuid.uuid4()}"
        await postgres_db.execute(
            "INSERT INTO conversations (conversation_id, user_id) VALUES ($1, $2)",
            conv_id, TEST_USER_ID,
        )

        # Soft delete
        await postgres_db.execute(
            "UPDATE conversations SET deleted_at = NOW() WHERE conversation_id = $1",
            conv_id,
        )

        # Try to append — the WHERE clause should prevent the update
        event = _make_event(0, content="should not be stored")
        result = await postgres_db.execute(
            """
            UPDATE conversations
            SET events = events || jsonb_build_array($1::jsonb)
            WHERE conversation_id = $2 AND deleted_at IS NULL
            """,
            event, conv_id,
        )

        # Verify no rows were updated
        assert result == "UPDATE 0"

    async def test_multiple_conversations_same_workflow(self, postgres_db, real_database):
        """Multiple agent nodes in the same workflow each get their own conversation."""
        await _setup_test_user(real_database)

        workflow_id = str(uuid.uuid4())
        conversations = {}

        for node_id in ["agent-1", "agent-2", "agent-3"]:
            conv_id = f"conv-multi-{uuid.uuid4()}"
            conversations[node_id] = conv_id

            await postgres_db.execute(
                """
                INSERT INTO conversations (conversation_id, user_id, workflow_id, node_id)
                VALUES ($1, $2, $3, $4)
                """,
                conv_id, TEST_USER_ID, workflow_id, node_id,
            )

            # Each gets different events
            event = _make_event(0, content=f"hello from {node_id}")
            await postgres_db.execute(
                """
                UPDATE conversations
                SET events = events || jsonb_build_array($1::jsonb)
                WHERE conversation_id = $2
                """,
                event, conv_id,
            )

        # Verify each conversation is independent
        for node_id, conv_id in conversations.items():
            row = await postgres_db.fetchrow(
                "SELECT events, node_id FROM conversations WHERE conversation_id = $1",
                conv_id,
            )
            assert row["node_id"] == node_id
            assert row["events"][0]["args"]["content"] == f"hello from {node_id}"

    async def test_large_event_stream(self, postgres_db, real_database):
        """Conversations with many events (100+) are stored and read correctly."""
        await _setup_test_user(real_database)

        conv_id = f"conv-large-{uuid.uuid4()}"
        await postgres_db.execute(
            "INSERT INTO conversations (conversation_id, user_id) VALUES ($1, $2)",
            conv_id, TEST_USER_ID,
        )

        # Insert 100 events
        num_events = 100
        for i in range(num_events):
            event = _make_event(i, content=f"event number {i}")
            await postgres_db.execute(
                """
                UPDATE conversations
                SET events = events || jsonb_build_array($1::jsonb)
                WHERE conversation_id = $2
                """,
                event, conv_id,
            )

        row = await postgres_db.fetchrow(
            "SELECT jsonb_array_length(events) as count, events FROM conversations WHERE conversation_id = $1",
            conv_id,
        )
        assert row["count"] == num_events
        # Verify first and last
        assert row["events"][0]["args"]["content"] == "event number 0"
        assert row["events"][99]["args"]["content"] == "event number 99"


# ============================================================================
# Test: user isolation
# ============================================================================


@pytest.mark.asyncio
class TestUserIsolation:
    """Tests ensuring conversations are properly isolated between users."""

    async def test_different_users_same_workflow(self, postgres_db, real_database):
        """Two users can have separate conversations for the same workflow/node."""
        user_a = TEST_USER_ID
        user_b = "00000000-0000-0000-0000-000000000002"

        await _setup_test_user(real_database, user_a)
        # Create second user
        await real_database.execute(
            "INSERT INTO auth.users (id, email) VALUES ($1, $2) ON CONFLICT (id) DO NOTHING",
            user_b, "user-b@example.com",
        )

        workflow_id = str(uuid.uuid4())

        conv_a = f"conv-user-a-{uuid.uuid4()}"
        conv_b = f"conv-user-b-{uuid.uuid4()}"

        await postgres_db.execute(
            """
            INSERT INTO conversations (conversation_id, user_id, workflow_id, node_id)
            VALUES ($1, $2, $3, $4)
            """,
            conv_a, user_a, workflow_id, "agent-1",
        )
        await postgres_db.execute(
            """
            INSERT INTO conversations (conversation_id, user_id, workflow_id, node_id)
            VALUES ($1, $2, $3, $4)
            """,
            conv_b, user_b, workflow_id, "agent-1",
        )

        # Each user only sees their own
        rows_a = await postgres_db.fetch(
            "SELECT * FROM conversations WHERE user_id = $1 AND workflow_id = $2",
            user_a, workflow_id,
        )
        rows_b = await postgres_db.fetch(
            "SELECT * FROM conversations WHERE user_id = $1 AND workflow_id = $2",
            user_b, workflow_id,
        )

        assert len(rows_a) == 1
        assert rows_a[0]["conversation_id"] == conv_a
        assert len(rows_b) == 1
        assert rows_b[0]["conversation_id"] == conv_b
