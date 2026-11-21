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
