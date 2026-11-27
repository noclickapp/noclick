"""An agent's instructions and their versions (parity with the TypeScript client, test/agent_instructions.test.ts):
``instructions_history()`` read with each version's diff and who made it, and a change made on what was read,
refused with ``Conflict`` carrying them as they are now when they changed since."""

import pytest

import noclick as nc
from platform_helpers import agent_row, body

NOW = "Write posts.\nNo emoji."
HISTORY = {
    "object": "agent_instructions", "agent_id": "ag_1", "instructions": NOW, "digest": "d" * 64, "kept_days": 90,
    "versions": [
        {"version": 42, "instructions": NOW, "diff": "@@ -1,2 +1,2 @@\n Write posts.\n-One emoji.\n+No emoji.",
         "added": 1, "removed": 1, "source": "coordinator", "author": {"user_id": "usr_1", "key_id": "key_grant"},
         "said": "Drop the emoji.", "restored_from": None, "changed_at": "2026-11-27T09:00:00Z"},
        {"version": 40, "instructions": "Write posts.\nOne emoji.", "diff": None, "added": 0, "removed": 0,
         "source": "baseline", "author": None, "said": None, "restored_from": None,
         "changed_at": "2026-11-20T10:00:00Z"},
    ],
}


def test_instructions_history_reads_each_version_with_what_it_changed_and_who_made_it(api, client):
    api.get("/v1/agents/ag_1").respond(json=agent_row(instructions=NOW))
    read = api.get("/v1/agents/ag_1/instructions").respond(json=HISTORY)
    history = nc.Agent.from_id("ag_1").instructions_history(limit=5)
    assert read.calls.last.request.url.params["limit"] == "5"
    assert (history.instructions, history.digest, history.kept_days) == (NOW, "d" * 64, 90)
    noclicks, first = history.versions
    assert (noclicks.version, noclicks.source, noclicks.said, noclicks.added, noclicks.removed) == (
        42, "coordinator", "Drop the emoji.", 1, 1)
    assert noclicks.changed_at.isoformat().startswith("2026-11-27T09:00:00")
    assert (first.source, first.diff, first.author) == ("baseline", None, None)


def test_a_change_names_what_it_was_made_on_and_one_made_on_stale_instructions_is_a_conflict(api, client):
    api.get("/v1/agents/ag_1").respond(json=agent_row(instructions=NOW))
    patch = api.patch("/v1/agents/ag_1").respond(409, json={"error": {
        "type": "conflict", "message": "Its instructions changed since this change was started from them.",
        "field": "instructions", "instructions": NOW, "digest": "e" * 64}})
    with pytest.raises(nc.Conflict) as refused:
        nc.Agent.from_id("ag_1").update(instructions="Write posts.\nTwo emoji.", if_instructions="d" * 64)
    assert body(patch.calls.last.request) == {"instructions": "Write posts.\nTwo emoji.", "if_instructions": "d" * 64}
    assert (refused.value.instructions, refused.value.digest) == (NOW, "e" * 64)
