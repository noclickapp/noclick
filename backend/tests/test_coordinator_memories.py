"""Exercise real memory persistence, ownership, retrieval, and stale writes.
The prompt tests verify that semantic headers survive intact while full bodies
stay outside initial context, including after the recent history window expires.
"""

import json
import uuid
from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest
from litellm import token_counter
from pydantic import ValidationError

from coder.coordinator.memory import CATALOG_TOKEN_BUDGET, memory_context, render_catalog
from coder.coordinator.tools import CoordinatorTools
from repositories.conversation import ConversationRepo
from repositories.coordinator_memories import CoordinatorMemoryRepo, MemoryConflict
from utils.coordinator_memory import CoordinatorMemoryWrite

USER = "00000000-0000-0000-0000-000000000001"
OTHER = "00000000-0000-0000-0000-000000000002"
MODEL = "gpt-4o"


@pytest.fixture
def memory_pool(postgres_db):
    class Pool:
        @asynccontextmanager
        async def acquire(self):
            yield postgres_db
    return Pool()


def draft(**fields):
    return CoordinatorMemoryWrite.model_validate(dict(
        name="release-preferences", description="Review preferences to consult before opening a pull request.",
        memory_type="feedback", content="Open ready for review. Watch CI until the current head finishes.",
    ) | fields)


async def test_headers_are_semantic_and_bodies_load_only_on_demand(memory_pool):
    repo = CoordinatorMemoryRepo(memory_pool)
    entry = await repo.save(USER, draft(content="Rarekeyword lives deep in the body."), origin_conversation_id=f"coordinator:{USER}")
    page = await repo.list_headers(USER, query="rarekeyword")
    assert page["memories"][0]["id"] == entry["id"]
    assert "content" not in page["memories"][0]
    prompt = await memory_context(memory_pool, USER, model=MODEL)
    assert entry["description"] in prompt and "Rarekeyword" not in prompt
    header = json.loads(prompt.splitlines()[3])
    assert header["metadata"] == {"node_type": "memory", "type": "feedback", "originSessionId": f"coordinator:{USER}"}
    assert (await repo.get(USER, entry["id"]))["content"] == "Rarekeyword lives deep in the body."


async def test_account_isolation_covers_search_read_update_and_delete(memory_pool, postgres_db):
    await postgres_db.execute("INSERT INTO auth.users(id,email) VALUES ($1::uuid,'other-memory@example.test') ON CONFLICT DO NOTHING", OTHER)
    repo = CoordinatorMemoryRepo(memory_pool)
    entry = await repo.save(USER, draft())
    assert (await repo.list_headers(OTHER))["memories"] == []
    with pytest.raises(ValueError, match="not found"):
        await repo.get(OTHER, entry["id"])
    with pytest.raises(MemoryConflict):
        await repo.save(OTHER, draft(memory_id=entry["id"], expected_version=1))
    with pytest.raises(MemoryConflict):
        await repo.delete(OTHER, entry["id"], 1)
    assert (await repo.get(USER, entry["id"]))["version"] == 1


async def test_user_edits_win_and_forgetting_cannot_be_undone_by_stale_writes(memory_pool, postgres_db):
    repo = CoordinatorMemoryRepo(memory_pool)
    entry = await repo.save(USER, draft())
    edit = draft(memory_id=entry["id"], expected_version=1, description="Updated retrieval description", content="New details")
    saved = await repo.save(USER, edit)
    assert saved["version"] == 2 and saved["description"] == "Updated retrieval description"
    with pytest.raises(MemoryConflict):
        await repo.save(USER, edit)
    with pytest.raises(MemoryConflict):
        await repo.delete(USER, entry["id"], 1)
    await repo.delete(USER, entry["id"], 2)
    assert (await repo.list_headers(USER))["memories"] == []
    with pytest.raises(ValueError, match="not found"):
        await repo.get(USER, entry["id"])
    with pytest.raises(MemoryConflict):
        await repo.save(USER, draft(memory_id=entry["id"], expected_version=2))
    with pytest.raises(MemoryConflict, match="forgotten"):
        await repo.save(USER, draft())
    tombstone = await postgres_db.fetchrow("SELECT content, description, search_document FROM coordinator_memories WHERE id=$1::uuid", entry["id"])
    assert tombstone["content"] == tombstone["description"] == ""
    assert "details" not in str(tombstone["search_document"])


async def test_memory_tools_recall_old_decisions_and_survive_chat_reset(memory_pool, postgres_db):
    cid = f"coordinator:{USER}"
    events = [{"role": "user", "message": "The launch codename is apricot."}]
    events += [{"role": "assistant", "message": f"An unrelated update {i}"} for i in range(100)]
    await postgres_db.execute(
        "INSERT INTO conversations(conversation_id,user_id,events) VALUES($1,$2,$3)", cid, USER, events,
    )
    tools = CoordinatorTools(pool=memory_pool, sio=None, user_id=USER, organization_id=None, conversation_id=cid)
    with patch("coder.coordinator.tools.record_tool_call"):
        saved = await tools.execute("save_memory", draft().model_dump(mode="json", exclude_none=True))
        assert saved["success"] and "content" not in saved["memory"]
        recalled = await tools.execute("read_memory", {"memory_id": saved["memory"]["id"]})
        assert recalled["memory"]["content"] == draft().content
        history = await tools.execute("search_history", {"query": "apricot"})
        assert history["matches"][0]["position"] == 1
        assert "apricot" in history["matches"][0]["excerpt"]
        assert (await ConversationRepo(memory_pool).search_messages(cid, OTHER, "apricot"))["matches"] == []
        assert await ConversationRepo(memory_pool).reset_conversation(cid, USER)
        assert (await tools.execute("search_history", {"query": "apricot"}))["matches"] == []
        assert (await tools.execute("read_memory", {"memory_id": saved["memory"]["id"]}))["success"]


async def test_history_and_memory_search_paginate_without_repeating_results(memory_pool, postgres_db):
    repo = CoordinatorMemoryRepo(memory_pool)
    for i in range(3):
        await repo.save(USER, draft(name=f"topic-{i}"))
    page = await repo.list_headers(USER, limit=2)
    rest = await repo.list_headers(USER, limit=2, offset=2)
    assert page["has_more"] and not rest["has_more"]
    assert len({r["id"] for r in page["memories"] + rest["memories"]}) == 3
    events = [{"role": "user", "message": f"launch decision {i}"} for i in range(25)]
    cid = f"coordinator:{USER}"
    await postgres_db.execute("INSERT INTO conversations(conversation_id,user_id,events) VALUES($1,$2,$3)", cid, USER, events)
    conversations = ConversationRepo(memory_pool)
    first = await conversations.search_messages(cid, USER, "launch")
    second = await conversations.search_messages(cid, USER, "launch", before=first["next_before"])
    assert len(first["matches"]) == 20 and len(second["matches"]) == 5
    assert len({r["position"] for r in first["matches"] + second["matches"]}) == 25


async def test_memory_table_has_no_public_data_api_access(postgres_db):
    assert await postgres_db.fetchval("SELECT relrowsecurity FROM pg_class WHERE oid='public.coordinator_memories'::regclass")
    for role in ("anon", "authenticated"):
        assert not await postgres_db.fetchval("SELECT has_table_privilege($1,'public.coordinator_memories','SELECT,INSERT,UPDATE,DELETE')", role)


def test_catalog_budget_preserves_complete_headers_and_never_injects_content():
    headers = [{"id": str(uuid.uuid4()), "name": f"topic-{i}", "description": f"Description {i}: " + "semantic meaning " * 25,
                "memory_type": "project", "origin_conversation_id": "origin", "content": "SECRET BODY"} for i in range(100)]
    prompt = render_catalog(headers, has_more=False, model=MODEL)
    assert token_counter(model=MODEL, text=prompt) <= CATALOG_TOKEN_BUDGET
    loaded = [json.loads(line) for line in prompt.splitlines() if line.startswith('{')]
    assert 0 < len(loaded) < len(headers)
    assert all(row["description"] == headers[i]["description"] for i, row in enumerate(loaded))
    assert "SECRET BODY" not in prompt and "search_memories" in prompt


@pytest.mark.parametrize("fields", [{"description": " "}, {"content": " "}, {"memory_id": str(uuid.uuid4())},
                                   {"expected_version": 1}, {"name": "Not a slug"}, {"description": "x" * 601}])
def test_memory_contract_requires_explicit_description_and_safe_update_version(fields):
    with pytest.raises(ValidationError):
        draft(**fields)
