"""A space template added as a new space (``Workspace.from_template``) or into one you have (``add_template``): the
dry run's page of asks, then the operation whose result names what arrived."""

import httpx

import noclick as nc
from platform_helpers import body

ADDRESS = "https://api.noclick.com/v1/public/git/3f2a1b0c-9d8e-4f7a-8b6c-5d4e3f2a1b0c.git"
PLAN = {
    "object": "space_template_plan", "dry_run": True,
    "template": {"name": "Social media team", "description": "Posts for your brand.", "word": "Social"},
    "target": {"workspace_id": None, "name": "Social media team", "new": True},
    "parts": [{"kind": "agent", "name": "Writer", "as": "Social Writer", "line": "Drafts posts", "needs": [],
               "included": True},
              {"kind": "channel", "name": "ideas", "as": "ideas", "line": None, "members": ["Social Writer"],
               "included": True}],
    "short": [], "secrets": [{"name": "unsplash", "keys": ["UNSPLASH_ACCESS_KEY"], "for": ["Designer"],
                              "held": None, "given": False}],
    "connections": [{"integration": "canva", "label": "Canva", "node_type": "automation-canva", "for": ["Designer"],
                     "connected": None},
                    {"integration": "linkedin", "label": "LinkedIn", "node_type": "automation-linkedin",
                     "for": ["Scheduler"], "connected": {"ref": "credential:cr_1", "name": None, "id": "cr_1"}}],
    "cap": {"usd_per_month": 40, "from": "template", "agents": [{"name": "Social Writer", "usd_per_month": 40}]},
    "app": None, "estimate": {"monthly_usd": 1.2, "items": [], "agents": {"up_to_usd": 40}},
    "funds": {"ok": True}, "refused": None, "summary": "Adds Social media team to a new space.",
}
OPERATION = {"object": "operation", "id": "op_1", "kind": "workspace.template_add", "status": "queued",
             "workspace_id": None, "channel_id": None, "created_at": "2026-11-27T10:00:00Z"}
ADDED = {"object": "space_template_added", "workspace": {"id": "ws_1", "name": "Social media team", "new": True},
         "channel": {"id": "ch_noclick", "name": "noclick"}, "message_id": "msg_1",
         "agents": [{"id": "ag_1", "name": "Writer"}], "channels": [{"id": "ch_1", "name": "ideas"}],
         "app": None, "waiting": [{"integration": "canva", "label": "Canva", "for": ["Designer"]}]}


def test_a_template_is_read_as_its_page_of_asks_then_added_as_a_new_space(api, client):
    route = api.post("/v1/workspaces/from_template").mock(side_effect=lambda request: httpx.Response(
        200 if body(request).get("dry_run") else 202,
        json=PLAN if body(request).get("dry_run") else {"object": "space_template_add", "operation": OPERATION}))
    plan = nc.Workspace.from_template(ADDRESS, dry_run=True, cap_usd_per_month=30)
    assert body(route.calls.last.request) == {"source": {"url": ADDRESS}, "cap_usd_per_month": 30, "dry_run": True}
    assert isinstance(plan, nc.TemplatePlan) and plan.target["new"] is True
    assert [(p.kind, p.name, p.named) for p in plan.parts] == [("agent", "Writer", "Social Writer"),
                                                               ("channel", "ideas", "ideas")]
    assert [(a.label, a.connected is None) for a in plan.connections] == [("Canva", True), ("LinkedIn", False)]

    api.get("/v1/operations/op_1/wait").respond(json={**OPERATION, "status": "succeeded", "workspace_id": "ws_1",
                                                 "channel_id": "ch_noclick", "result": ADDED})
    adding = nc.Workspace.from_template(ADDRESS, secrets={"unsplash": {"UNSPLASH_ACCESS_KEY": "key"}},
                                        leave_out=[{"kind": "app"}])
    assert body(route.calls.last.request) == {"source": {"url": ADDRESS}, "leave_out": [{"kind": "app"}],
                                              "secrets": {"unsplash": {"UNSPLASH_ACCESS_KEY": "key"}}}
    assert isinstance(adding, nc.TemplateAdd)
    added = adding.wait()
    assert (added.workspace_id, added.channel_id, added.agents[0]["name"]) == ("ws_1", "ch_noclick", "Writer")


def test_a_template_goes_into_a_space_you_have(api, client):
    into = api.post("/v1/workspaces/ws_9/template/add").respond(json={**PLAN, "target": {
        "workspace_id": "ws_9", "name": "Lumen Coffee", "new": False}})
    plan = nc.Workspace.from_id("ws_9").add_template("social-media-team", dry_run=True)
    assert body(into.calls.last.request) == {"source": {"repo": "social-media-team"}, "dry_run": True}
    assert plan.target["name"] == "Lumen Coffee"
