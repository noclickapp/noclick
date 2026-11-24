"""Workflow folders (``GET``/``POST /v1/workflows/folders``, ``POST /v1/workflows/{id}/move``) and NoClick's example
workflows (``GET /v1/workflow_examples`` and ``/v1/workflow_examples/{id}``): what the client sends and how it reads
the answer, against the mocked transport."""

import httpx

import noclick as nc
from platform_helpers import body, listing

WF = "2e3a9296-1bf5-4088-a20d-7c31937380c4"
REPORTS = {"object": "workflow_folder", "id": "f1", "name": "Reports", "description": None, "parent_id": None,
           "depth": 0, "workflow_count": 2, "created_at": "2026-11-21T10:00:00Z", "updated_at": "2026-11-21T10:00:00Z"}
WEEKLY = {**REPORTS, "id": "f2", "name": "Weekly", "parent_id": "f1", "depth": 1, "workflow_count": 0}


def workflow(folder_id):
    return {"object": "workflow", "id": WF, "name": "Morning brief", "description": None, "version": 3,
            "access": "owner", "inputs": {}, "apps": [], "step_types": ["trigger-cron"], "starts": "Every day at 8",
            "app_url": "https://app.noclick.com/w", "folder_id": folder_id, "created_at": "2026-11-20T10:00:00Z",
            "updated_at": "2026-11-21T10:00:00Z"}


def test_folders_list_for_the_account_never_a_user(api, client):
    route = api.get("/v1/workflows/folders").respond(json=listing(REPORTS, WEEKLY))
    with nc.as_user("user_42"):
        found = nc.Workflow.folders()
    assert "NoClick-User" not in route.calls.last.request.headers
    reports, weekly = found
    assert (reports.id, reports.name, reports.parent_id, reports.depth, reports.workflow_count) == (
        "f1", "Reports", None, 0, 2)
    assert (weekly.parent_id, weekly.depth) == ("f1", 1)
    assert reports.created_at.year == 2026


def test_a_folder_is_made_at_the_top_or_in_its_parent(api, client):
    route = api.post("/v1/workflows/folders").mock(side_effect=[httpx.Response(201, json=REPORTS),
                                                                 httpx.Response(201, json=WEEKLY),
                                                                 httpx.Response(201, json={**WEEKLY, "id": "f3"})])
    reports = nc.Workflow.create_folder("Reports")
    weekly = nc.Workflow.create_folder("Weekly", description="Each week's", parent=reports)
    first, second = (body(call.request) for call in route.calls)
    assert first == {"name": "Reports"}
    assert second == {"name": "Weekly", "description": "Each week's", "parent_id": "f1"}
    assert weekly == nc.WorkflowFolder._from(WEEKLY)
    nc.Workflow.create_folder("Daily", parent="f2")
    assert body(route.calls.last.request)["parent_id"] == "f2"


def test_a_taken_name_raises_conflict_naming_the_folder(api, client):
    api.post("/v1/workflows/folders").respond(409, json={"error": {
        "type": "conflict", "message": "The account already has a folder named 'Reports' there.",
        "folder_id": "f1"}})
    try:
        nc.Workflow.create_folder("Reports")
    except nc.Conflict as refused:
        assert refused.details["folder_id"] == "f1"
    else:
        raise AssertionError("a taken name is refused")


def test_move_to_files_a_workflow_in_a_folder_and_out_to_the_top(api, client):
    route = api.post(f"/v1/workflows/{WF}/move").mock(side_effect=[httpx.Response(200, json=workflow("f2")),
                                                                   httpx.Response(200, json=workflow(None)),
                                                                   httpx.Response(200, json=workflow("f1"))])
    brief = nc.Workflow.from_id(WF)
    assert brief.move_to(nc.WorkflowFolder._from(WEEKLY)).folder_id == "f2"
    assert brief.move_to(None).folder_id is None
    brief.move_to("f1")
    assert [body(call.request) for call in route.calls] == [{"folder_id": "f2"}, {"folder_id": None},
                                                            {"folder_id": "f1"}]
    assert brief.folder_id == "f1" and brief.version == 3


EXAMPLE = {"object": "workflow_example", "id": "e1", "name": "Triage support email",
           "description": "When a support email arrives, an agent labels it and drafts a reply.", "has_text": True,
           "has_workflow": True, "step_types": ["trigger-email", "agent"], "updated_at": "2026-11-20T09:00:00Z"}
WHOLE = {**EXAMPLE, "text": "Wire the trigger into the agent.",
         "graph": {"nodes": [{"id": "mail", "type": "trigger-email", "config": {"label": "Mail"}},
                             {"id": "agent", "type": "agent", "config": {"label": "Triage"}}],
                   "edges": [{"id": "mail-agent", "source": "mail", "target": "agent"}], "withheld": {}}}


def test_examples_read_every_page_and_send_the_query(api, client):
    route = api.get("/v1/workflow_examples").mock(side_effect=[
        httpx.Response(200, json=listing(EXAMPLE, next_cursor="e1")),
        httpx.Response(200, json=listing({**EXAMPLE, "id": "e2", "has_workflow": False, "step_types": []})),
    ])
    with nc.as_user("user_42"):
        found = nc.workflow_examples("support email")
    first, second = (call.request for call in route.calls)
    assert "NoClick-User" not in first.headers and first.url.params["q"] == "support email"
    assert second.url.params["cursor"] == "e1"
    triage, guidance = found
    assert (triage.name, triage.step_types, triage.has_text, triage.text, triage.graph) == (
        "Triage support email", ["trigger-email", "agent"], True, None, None)
    assert guidance.has_workflow is False


def test_one_example_reads_whole(api, client):
    api.get("/v1/workflow_examples/e1").respond(json=WHOLE)
    example = nc.workflow_example("e1")
    assert example.text == "Wire the trigger into the agent."
    assert [node["type"] for node in example.graph["nodes"]] == ["trigger-email", "agent"]
    assert example.updated_at.day == 20


def test_an_example_that_isnt_listed_raises_not_found(api, client):
    api.get("/v1/workflow_examples/nope").respond(404, json={"error": {
        "type": "not_found", "message": "No workflow example 'nope'."}})
    try:
        nc.workflow_example("nope")
    except nc.NotFound as missing:
        assert "nope" in str(missing)
    else:
        raise AssertionError("an unknown example is refused")


def test_delete_folder_deletes_one_and_answers_it_as_it_was(api, client):
    route = api.delete("/v1/workflows/folders/f2").respond(json={**WEEKLY, "deleted": True})
    with nc.as_user("user_42"):
        deleted = nc.Workflow.delete_folder(nc.WorkflowFolder._from(WEEKLY))
    assert "NoClick-User" not in route.calls.last.request.headers
    assert (deleted.id, deleted.name, deleted.raw["deleted"]) == ("f2", "Weekly", True)
    api.delete("/v1/workflows/folders/f1").respond(json={**REPORTS, "deleted": True})
    assert nc.Workflow.delete_folder("f1").id == "f1"


def test_list_sends_the_text_to_search_names_and_descriptions_for(api, client):
    route = api.get("/v1/workflows").respond(json=listing(workflow(None)))
    found = nc.Workflow.list(search="digest")
    assert route.calls.last.request.url.params["search"] == "digest" and found[0].id == WF
    nc.Workflow.list_page(search="brief", limit=5)
    assert route.calls.last.request.url.params["search"] == "brief"


def test_a_folders_workflows_list_as_the_automations_page_lists_them(api, client):
    preview = {"nodes": [{"id": "a", "type": "agent", "position": {"x": 0, "y": 0}, "config": {"model": "codex"}}],
               "edges": []}
    route = api.get("/v1/workflows").mock(side_effect=[
        httpx.Response(200, json={**listing({**workflow(None), "owner": None, "preview": preview}),
                                  "hidden_shared_count": 2}),
        httpx.Response(200, json={**listing({**workflow("f2"), "access": "viewer", "owner": {"name": "Ada"}}),
                                  "hidden_shared_count": 0})])
    top = nc.Workflow.in_folder(None, preview=True)
    params = route.calls.last.request.url.params
    assert (params["folder_id"], params["include"], "organization_id" in params) == ("top", "preview", False)
    assert top.hidden_shared_count == 2
    assert (top.workflows[0].owner, top.workflows[0].preview["nodes"][0]["type"]) == (None, "agent")
    inside = nc.Workflow.in_folder("f2", organization_id="team")
    params = route.calls.last.request.url.params
    assert (params["folder_id"], params["organization_id"], "include" in params) == ("f2", "team", False)
    assert inside.workflows[0].owner == {"name": "Ada"}


def test_what_others_shared_lists_with_who_shared_it(api, client):
    shared = {"object": "workflow", "id": WF, "name": "Their brief", "description": None, "access": "editor",
              "owner": {"name": "Ada"}, "shared_at": "2026-11-22T10:00:00Z", "organization": None}
    workflows = api.get("/v1/workflows").respond(json=listing(shared))
    folders = api.get("/v1/workflows/folders").respond(json=listing(
        {**REPORTS, "access": "viewer", "owner": {"name": "Ada"}, "shared_at": "2026-11-22T10:00:00Z"}))
    (brief,) = nc.Workflow.shared_with_me()
    assert workflows.calls.last.request.url.params["shared_with_me"] == "true"
    assert (brief.owner, brief.shared_at.day, brief.access) == ({"name": "Ada"}, 22, "editor")
    (folder,) = nc.Workflow.folders(shared_with_me=True, organization_id="team")
    params = folders.calls.last.request.url.params
    assert (params["shared_with_me"], params["organization_id"]) == ("true", "team")
    assert (folder.access, folder.owner, folder.shared_at.day) == ("viewer", {"name": "Ada"}, 22)


def test_update_folder_renames_and_moves_none_taking_it_to_the_top(api, client):
    route = api.patch("/v1/workflows/folders/f2").mock(side_effect=[
        httpx.Response(200, json={**WEEKLY, "name": "Each week"}),
        httpx.Response(200, json={**WEEKLY, "parent_id": None, "depth": 0})])
    assert nc.Workflow.update_folder("f2", name="Each week").name == "Each week"
    assert nc.Workflow.update_folder("f2", parent=None, organization_id="team").parent_id is None
    assert [body(call.request) for call in route.calls] == [{"name": "Each week"},
                                                            {"organization_id": "team", "parent_id": None}]


def test_fork_copies_a_workflow_and_move_and_delete_name_a_team_workspace(api, client):
    fork = api.post(f"/v1/workflows/{WF}/fork").respond(
        201, json={**workflow(None), "id": "copy", "name": "Copy of Morning brief"})
    move = api.post(f"/v1/workflows/{WF}/move").respond(json=workflow("f2"))
    delete = api.delete("/v1/workflows/folders/f2").respond(json={**WEEKLY, "deleted": True})
    copy = nc.Workflow.from_id(WF).fork(name="Mine", organization_id="team")
    assert body(fork.calls.last.request) == {"name": "Mine", "organization_id": "team"}
    assert (copy.id, copy.name) == ("copy", "Copy of Morning brief")
    nc.Workflow.from_id(WF).move_to("f2", organization_id="team")
    assert body(move.calls.last.request) == {"folder_id": "f2", "organization_id": "team"}
    nc.Workflow.delete_folder("f2", organization_id="team")
    assert delete.calls.last.request.url.params["organization_id"] == "team"


def test_trashed_lists_the_trash_and_delete_for_good_deletes_one(api, client):
    trash = api.get("/v1/workflows/trash").respond(json=listing(
        {"object": "workflow", "id": WF, "name": "Old digest", "description": None,
         "deleted_at": "2026-11-20T10:00:00Z", "purge_after": "2026-12-20T10:00:00Z"}))
    purge = api.delete(f"/v1/workflows/{WF}/trash").respond(json={"object": "workflow", "id": WF, "deleted": True})
    with nc.as_user("user_42"):
        (old,) = nc.Workflow.trashed()
    assert "NoClick-User" not in trash.calls.last.request.headers
    assert (old.id, old.name, old.raw["purge_after"]) == (WF, "Old digest", "2026-12-20T10:00:00Z")
    old.delete_for_good()
    assert purge.call_count == 1
    try:
        nc.Workflow.from_name("Old digest").delete_for_good()
    except nc.NotFound:
        pass
    else:
        raise AssertionError("a workflow named, not by id, isn't deleted for good")


def test_create_sends_no_name_for_the_next_free_untitled_and_files_it_in_a_folder_of_a_workspace(api, client):
    route = api.post("/v1/workflows").mock(side_effect=[
        httpx.Response(201, json={**workflow(None), "name": "Untitled 2"}),
        httpx.Response(201, json=workflow("f1"))])
    assert nc.Workflow.create().name == "Untitled 2"
    nc.Workflow.create(folder=nc.WorkflowFolder._from(REPORTS), organization_id="org_1")
    assert [body(call.request) for call in route.calls] == [{}, {"folder_id": "f1", "organization_id": "org_1"}]
