"""The migration that moves saved agent nodes off the old video ids
(infra/supabase/migrations/20261009130000_agent_video_openrouter_models.sql).

The agent's video model runs only through OpenRouter now. The migration renames
saved ids and the run renames an old id an older client still writes, both by
one table (``utils.model_catalog.LEGACY_VIDEO_MODELS``, which the migration's
literal must equal): every target must be a model in OpenRouter's video catalog
that the agent routes to its video path, and the rewrite must reach both stored
node shapes and touch nothing else.
"""

import json
import re
import uuid
from pathlib import Path

import pytest

from nodes.agent.config.base import infer_model_type
from tests.test_video_model_ids import OPENROUTER_VIDEO_IDS
from utils.model_catalog import LEGACY_VIDEO_MODELS, current_video_model

MIGRATION = (Path(__file__).resolve().parents[2] / "infra" / "supabase" / "migrations"
             / "20261009130000_agent_video_openrouter_models.sql")
PREFIXES = ("", "gemini/", "google/", "vertex_ai/")


def renames() -> dict:
    literal = re.search(r"SELECT '(\{.*?\})'::jsonb", MIGRATION.read_text(), re.S)
    assert literal, "the migration's rename table moved"
    return json.loads(literal.group(1))


@pytest.mark.parametrize("target", sorted(set(renames().values())))
def test_every_target_is_an_openrouter_video_model_the_agent_runs_as_video(target):
    assert target in OPENROUTER_VIDEO_IDS
    assert infer_model_type({"model": target})["model_type"] == "video"
    assert infer_model_type({"model": f"openrouter/{target}"})["model_type"] == "video"


def test_the_run_renames_an_old_id_by_the_migrations_own_table():
    """One table: the migration's literal is the run's, and the run applies it the way the
    migration does (lower-cased, behind any route prefix), leaving every other id alone."""
    assert renames() == LEGACY_VIDEO_MODELS
    for old, new in LEGACY_VIDEO_MODELS.items():
        for prefix in (PREFIXES if "/" not in old else ("",)):
            assert current_video_model(f"{prefix}{old}") == new
            assert current_video_model(f"{prefix}{old}".upper()) == new
    for kept in ("google/veo-3.1-fast", "openrouter/google/veo-3.1", "openai/sora-2", "kwaivgi/kling-v3.0-pro"):
        assert current_video_model(kept) == kept


def test_the_ids_production_holds_are_renamed():
    table = renames()
    # 23 saved agent nodes in production name this one (2026-10-08).
    assert table["veo-3.1-fast-generate-001"] == "google/veo-3.1-fast"
    assert table["veo-3"] == "google/veo-3.1-fast"  # the old default


def agent(node_id, model, *, shape):
    """An agent node in one of the stored shapes (utils/graph_nodes.py)."""
    if shape == "save":
        return {"id": node_id, "type": "agent", "config": {"model": model, "message": "make a clip"}}
    if shape == "canvas":
        return {"id": node_id, "type": "agent", "position": {"x": 1, "y": 2},
                "data": {"label": "Clip", "config": {"model": model, "message": "make a clip"}}}
    return {"id": node_id, "type": "agent", "data": {"label": "Clip", "model": model, "config": {"message": "x"}}}


async def test_the_migration_renames_both_node_shapes_and_touches_nothing_else(postgres_db):
    db = postgres_db
    owner = str(await db.fetchval("INSERT INTO auth.users (email) VALUES ($1) RETURNING id",
                                  f"{uuid.uuid4().hex[:10]}@example.com"))
    old_ids = [(f"{prefix}{old}", new) for old, new in renames().items() for prefix in
               (PREFIXES if "/" not in old else ("",))]
    nodes = [agent(f"n{i}", old, shape=("save", "canvas", "data")[i % 3]) for i, (old, _) in enumerate(old_ids)]
    keep = [
        agent("current", "google/veo-3.1-fast", shape="save"),
        agent("routed", "openrouter/google/veo-3.1", shape="canvas"),
        agent("chat", "openrouter/anthropic/claude-sonnet-4.6", shape="canvas"),
        agent("sora", "openai/sora-2", shape="save"),       # nothing on OpenRouter: refused by name at run time
        {"id": "other", "type": "http", "config": {"model": "gemini/veo-3.1-generate-001"}},
    ]
    graph = {"nodes": nodes + keep, "edges": [{"id": "e1", "source": "n0", "target": "n1"}], "viewport": {"zoom": 1}}
    insert = "INSERT INTO workflows (owner_id, name, workflow) VALUES ($1::uuid, $2, $3) RETURNING id"
    renamed_wf = await db.fetchval(insert, owner, "Clips", graph)
    untouched_wf = await db.fetchval(insert, owner, "Notes", {"nodes": keep, "edges": []})
    checkpoint = await db.fetchval(
        "INSERT INTO workflow_checkpoints (user_id, workflow_id, name, workflow) VALUES ($1::uuid, $2, 'before', $3) "
        "RETURNING id", owner, renamed_wf, {"nodes": [agent("c", "gemini/veo-3.1-fast-generate-001", shape="save")]})
    before = await db.fetchrow("SELECT ctid::text, graph_version FROM workflows WHERE id = $1", untouched_wf)
    version = await db.fetchval("SELECT graph_version FROM workflows WHERE id = $1", renamed_wf)

    await db.execute(MIGRATION.read_text())

    row = await db.fetchrow("SELECT workflow, graph_version FROM workflows WHERE id = $1", renamed_wf)
    expected = [agent(f"n{i}", new, shape=("save", "canvas", "data")[i % 3]) for i, (_, new) in enumerate(old_ids)]
    assert row["workflow"] == {**graph, "nodes": expected + keep}  # order, edges and every other key as they were
    assert row["graph_version"] == version + 1
    saved = await db.fetchval("SELECT workflow FROM workflow_checkpoints WHERE id = $1", checkpoint)
    assert saved["nodes"][0]["config"]["model"] == "google/veo-3.1-fast"
    # A workflow with nothing to rename isn't written at all.
    assert dict(await db.fetchrow("SELECT ctid::text, graph_version FROM workflows WHERE id = $1", untouched_wf)) == \
        dict(before)

    # Run again, it finds nothing left to do.
    renamed_row = await db.fetchval("SELECT ctid::text FROM workflows WHERE id = $1", renamed_wf)
    await db.execute(MIGRATION.read_text())
    assert await db.fetchval("SELECT ctid::text FROM workflows WHERE id = $1", renamed_wf) == renamed_row
