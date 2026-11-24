"""The skills NoClick's builder loads (``noclick.BuilderSkill``): the account's, never a user's, so none sends
``NoClick-User`` inside ``as_user``."""

import httpx
import pytest

import noclick as nc
from platform_helpers import body

VOICE = {"object": "builder_skill", "id": "6c1f0e9a-0000-4000-8000-0000000000a1", "name": "Brand voice",
         "description": "How we write.", "scope": "owned", "owner_id": "u_ada", "enabled": True, "muted": False,
         "has_text": True, "has_workflow": False, "created_at": "2026-11-14T09:00:00+00:00",
         "updated_at": "2026-11-14T09:00:00+00:00"}
TONE = {**VOICE, "id": "6c1f0e9a-0000-4000-8000-0000000000a2", "name": "Support tone", "scope": "shared",
        "owner_id": "u_priya"}


def test_list_reads_the_accounts_own_and_those_shared_with_it(api, client):
    read = api.get("/v1/builder_skills").respond(json={"object": "list", "data": [VOICE, TONE]})
    with nc.as_user("user_42"):
        skills = nc.BuilderSkill.list()
    assert [(s.name, s.scope, s.enabled, s.muted, s.has_text) for s in skills] == [
        ("Brand voice", "owned", True, False, True), ("Support tone", "shared", True, False, True)]
    assert skills[0].body_text is None
    assert "NoClick-User" not in read.calls.last.request.headers


def test_create_sends_what_it_says_and_get_reads_it_whole(api, client):
    made = api.post("/v1/builder_skills").respond(201, json={**VOICE, "body_text": "Short sentences.",
                                                             "body_workflow": None})
    api.get(f"/v1/builder_skills/{VOICE['id']}").respond(json={**VOICE, "body_text": "Short sentences.",
                                                               "body_workflow": {"nodes": []}})
    skill = nc.BuilderSkill.create("Brand voice", description="How we write.", body_text="Short sentences.")
    assert body(made.calls.last.request) == {"name": "Brand voice", "description": "How we write.",
                                             "body_text": "Short sentences."}
    assert skill.body_text == "Short sentences."
    assert nc.BuilderSkill.get(VOICE["id"]).body_workflow == {"nodes": []}


def test_update_sends_only_what_changes_and_delete_names_it(api, client):
    api.get("/v1/builder_skills").respond(json={"object": "list", "data": [VOICE, TONE]})
    patch = api.patch(f"/v1/builder_skills/{TONE['id']}").respond(json={**TONE, "muted": True})
    removed = api.delete(f"/v1/builder_skills/{VOICE['id']}").respond(
        json={"object": "builder_skill", "id": VOICE["id"], "deleted": True})
    voice, tone = nc.BuilderSkill.list()
    assert tone.update(muted=True).muted is True
    assert body(patch.calls.last.request) == {"muted": True}
    voice.delete()
    assert removed.call_count == 1


def test_changing_one_shared_to_read_raises_permission_denied(api, client):
    api.patch(f"/v1/builder_skills/{TONE['id']}").respond(403, json={"error": {
        "type": "permission_denied", "message": "shared with the account to read"}})
    with pytest.raises(nc.PermissionDenied):
        nc.BuilderSkill._from(TONE).update(enabled=False)


def test_save_workflow_saves_on_the_version_it_was_read_at_and_a_stale_one_raises_conflict(api, client):
    put = api.put(f"/v1/builder_skills/{VOICE['id']}/workflow").mock(side_effect=[
        httpx.Response(200, json={"object": "builder_skill_workflow", "skill_id": VOICE["id"], "version": 3,
                                  "changed": True}),
        httpx.Response(409, json={"error": {"type": "conflict", "message": "it changed since it was read",
                                            "version": 4, "workflow": {"nodes": [{"id": "a"}]}}}),
    ])
    saved = nc.BuilderSkill.save_workflow(VOICE["id"], {"nodes": [], "edges": []}, if_version=2,
                                          changes={"steps": ["b"]})
    assert saved == {"version": 3, "changed": True}
    assert body(put.calls.last.request) == {"workflow": {"nodes": [], "edges": []}, "if_version": 2,
                                            "changes": {"steps": ["b"]}}
    with pytest.raises(nc.Conflict) as stale:
        nc.BuilderSkill.save_workflow(VOICE["id"], {"nodes": []}, if_version=2)
    assert stale.value.details["version"] == 4
