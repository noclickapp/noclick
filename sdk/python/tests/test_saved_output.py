"""Outputs saved under a name (``noclick.SavedOutput``): the account's own, read and changed on the workflow they're
shown on."""

import pytest

import noclick as nc
from platform_helpers import body

WF = "wf_1"
ORDER = {"object": "saved_output", "id": "so_1", "name": "A paid order", "step_type": "automation-shopify",
         "output": {"ok": True}, "visibility": "user", "owner_id": "u_ada", "mine": True,
         "created_at": "2026-11-24T09:00:00+00:00", "updated_at": "2026-11-24T09:00:00+00:00"}


def test_list_reads_a_step_types_saved_outputs_on_the_workflow_as_the_account(api, client):
    read = api.get(f"/v1/workflows/{WF}/saved_outputs").respond(json={"object": "list", "data": [ORDER]})
    with nc.as_user("user_42"):
        saved = nc.SavedOutput.list(WF, "automation-shopify")
    assert [(s.name, s.step_type, s.visibility, s.mine, s.output) for s in saved] == [
        ("A paid order", "automation-shopify", "user", True, {"ok": True})]
    assert read.calls.last.request.url.params["step_type"] == "automation-shopify"
    assert "NoClick-User" not in read.calls.last.request.headers


def test_create_update_and_delete_and_a_plans_limit_raises_plan_required(api, client):
    made = api.post(f"/v1/workflows/{WF}/saved_outputs").respond(201, json=ORDER)
    patch = api.patch(f"/v1/workflows/{WF}/saved_outputs/so_1").respond(json={**ORDER, "visibility": "public"})
    removed = api.delete(f"/v1/workflows/{WF}/saved_outputs/so_1").respond(
        json={"object": "saved_output", "id": "so_1", "deleted": True})
    saved = nc.SavedOutput.create(WF, step_type="automation-shopify", name="A paid order", output={"ok": True})
    assert body(made.calls.last.request) == {"step_type": "automation-shopify", "name": "A paid order",
                                             "output": {"ok": True}}
    assert saved.update(visibility="public").visibility == "public"
    assert body(patch.calls.last.request) == {"visibility": "public"}
    saved.delete()
    assert removed.call_count == 1
    api.post(f"/v1/workflows/{WF}/saved_outputs").respond(402, json={"error": {
        "type": "plan_required", "message": "Plan limit reached"}})
    with pytest.raises(nc.PlanRequired):
        nc.SavedOutput.create(WF, step_type="automation-shopify", name="More", output={})
