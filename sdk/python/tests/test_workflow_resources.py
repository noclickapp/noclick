"""What workflows keep (their files and tables, a table's rows) and the account's own files, against the mocked
transport: the routes, query parameters and headers each call sends, and what it parses."""

import json

import httpx
import pytest

import noclick as nc

FILE = {
    "object": "workflow_file", "id": "res_f1", "name": "invoice.pdf",
    "workflow": {"id": "wf_1", "name": "Intake", "step_types": ["trigger-webhook", "agent:codex", "automation-gmail"]},
    "access": "editor", "step_id": "upload", "type": "document", "mime_type": "application/pdf", "size_bytes": 1024,
    "url": "https://api.noclick.com/f/sealed/invoice.pdf", "url_expires_at": "2026-11-19T11:00:00+00:00",
    "created_at": "2026-11-19T10:00:00+00:00", "updated_at": "2026-11-19T10:00:00+00:00",
}
TABLE = {
    "object": "workflow_table", "id": "res_t1", "name": "Orders", "workflow": {"id": "wf_1", "name": "Intake", "step_types": []},
    "access": "owner", "step_id": "table", "row_count": 3, "database_id": "db_1",
    "created_at": "2026-11-19T10:00:00+00:00", "updated_at": "2026-11-19T10:00:00+00:00",
}
WORKFLOW = {"object": "workflow", "id": "wf_1", "name": "Intake", "description": None, "access": "owner",
            "inputs": {}, "app_url": None, "created_at": None, "updated_at": None}


def _row(n):
    return {"object": "table_row", "id": f"row_{n}", "index": n, "data": {"n": n},
            "created_at": "2026-11-19T10:00:00+00:00"}


def test_a_workflows_files_list_with_their_workflow_and_a_link_and_never_act_for_a_user(api, client):
    listed = api.get("/v1/workflows/files").respond(json={"object": "list", "data": [FILE], "next_cursor": None})
    api.get("/v1/workflows", params={"name": "Intake"}).respond(json={"object": "list", "data": [WORKFLOW],
                                                                      "next_cursor": None})
    [invoice] = nc.WorkflowFile.list(workflow=nc.Workflow.from_name("Intake"), organization_id="none")
    request = listed.calls.last.request
    assert dict(request.url.params) == {"workflow_id": "wf_1", "organization_id": "none"}
    assert "noclick-user" not in request.headers
    assert (invoice.id, invoice.name, invoice.workflow, invoice.access, invoice.step_id) == (
        "res_f1", "invoice.pdf",
        {"id": "wf_1", "name": "Intake", "step_types": ["trigger-webhook", "agent:codex", "automation-gmail"]}, "editor",
        "upload")
    assert (invoice.type, invoice.size_bytes, invoice.url) == ("document", 1024, FILE["url"])
    assert invoice.url_expires_at.isoformat() == "2026-11-19T11:00:00+00:00"
    # A workflow named by id, and a page.
    page = nc.WorkflowFile.list_page(workflow="wf_2", cursor="res_f0", limit=10)
    assert dict(listed.calls.last.request.url.params) == {"workflow_id": "wf_2", "cursor": "res_f0", "limit": "10"}
    assert [f.id for f in page.data] == ["res_f1"] and page.next_cursor is None


def test_a_file_and_a_table_are_deleted_by_their_own_routes(api, client):
    api.get("/v1/workflows/files").respond(json={"object": "list", "data": [FILE], "next_cursor": None})
    api.get("/v1/workflows/tables").respond(json={"object": "list", "data": [TABLE], "next_cursor": None})
    gone_file = api.delete("/v1/workflows/files/res_f1").respond(
        json={"object": "workflow_file", "id": "res_f1", "deleted": True})
    gone_table = api.delete("/v1/workflows/tables/res_t1").respond(
        json={"object": "workflow_table", "id": "res_t1", "deleted": True})
    [invoice], [orders] = nc.WorkflowFile.list(), nc.WorkflowTable.list()
    assert invoice.delete() is None and orders.delete() is None
    assert gone_file.called and gone_table.called
    assert "noclick-user" not in gone_file.calls.last.request.headers


def test_a_view_only_workflows_file_refuses_its_deletion(api, client):
    api.get("/v1/workflows/files").respond(json={"object": "list", "data": [{**FILE, "access": "viewer"}],
                                                 "next_cursor": None})
    api.delete("/v1/workflows/files/res_f1").respond(403, json={"error": {
        "type": "permission_denied", "message": "'Intake' is shared with this account to view.",
        "next_step": "Ask the workflow's owner."}})
    [invoice] = nc.WorkflowFile.list()
    with pytest.raises(nc.PermissionDenied):
        invoice.delete()


def test_a_tables_rows_read_by_page_and_whole(api, client):
    api.get("/v1/workflows/tables").respond(json={"object": "list", "data": [TABLE], "next_cursor": None})
    rows = api.get("/v1/workflows/tables/res_t1/rows").mock(side_effect=[
        httpx.Response(200, json={"object": "list", "data": [_row(0), _row(1)], "total_count": 3, "next_cursor": "2"}),
        httpx.Response(200, json={"object": "list", "data": [_row(2)], "total_count": 3, "next_cursor": None}),
        httpx.Response(200, json={"object": "list", "data": [_row(0)], "total_count": 3, "next_cursor": "1"}),
    ])
    [orders] = nc.WorkflowTable.list(workflow="wf_1")
    assert (orders.row_count, orders.database_id, orders.access) == (3, "db_1", "owner")
    every = orders.rows()
    assert [(r.id, r.index, r.data) for r in every] == [("row_0", 0, {"n": 0}), ("row_1", 1, {"n": 1}),
                                                       ("row_2", 2, {"n": 2})]
    # Read whole, a page holds the most a page may: 10,000 rows.
    assert [dict(c.request.url.params) for c in rows.calls] == [{"limit": "10000"}, {"limit": "10000", "cursor": "2"}]
    page = orders.rows_page(limit=1)
    assert dict(rows.calls.last.request.url.params) == {"limit": "1"}
    assert [r.index for r in page.data] == [0] and page.next_cursor == "1" and page.total_count == 3


def test_rows_stop_at_a_limit(api, client):
    api.get("/v1/workflows/tables").respond(json={"object": "list", "data": [TABLE], "next_cursor": None})
    rows = api.get("/v1/workflows/tables/res_t1/rows").respond(json={
        "object": "list", "data": [_row(0), _row(1)], "total_count": 3, "next_cursor": "2"})
    [orders] = nc.WorkflowTable.list()
    assert [r.index for r in orders.rows(limit=2)] == [0, 1]
    assert dict(rows.calls.last.request.url.params) == {"limit": "2"} and rows.call_count == 1


def test_the_accounts_files_page_by_cursor_and_are_deleted_as_the_account(api, client):
    made = {"object": "attachment", "id": "res_1", "name": "cake.png", "mime_type": "image/png", "size_bytes": 900,
            "kind": "image", "voice": False, "url": "https://assets.example/u/account/res_1/cake.png",
            "duration_ms": None, "peaks": None, "created_at": "2026-11-19T10:00:00+00:00",
            "updated_at": "2026-11-19T10:30:00+00:00"}
    listed = api.get("/v1/attachments").respond(json={"object": "list", "data": [made], "next_cursor": "res_1"})
    page = nc.attachments_page(query="cake", cursor="res_0", limit=1)
    assert dict(listed.calls.last.request.url.params) == {"query": "cake", "cursor": "res_0", "limit": "1"}
    assert [f.id for f in page.data] == ["res_1"] and page.next_cursor == "res_1"
    assert (page.data[0].created_at.isoformat(), page.data[0].updated_at.isoformat()) == (
        "2026-11-19T10:00:00+00:00", "2026-11-19T10:30:00+00:00")
    gone = api.delete("/v1/attachments/res_1").respond(json={"object": "attachment", "id": "res_1", "deleted": True})
    nc.delete_attachment(page.data[0])
    nc.delete_attachment("res_1")
    assert gone.call_count == 2 and "noclick-user" not in gone.calls.last.request.headers
    with pytest.raises(TypeError):
        nc.delete_attachment(nc.Attachment("sent.png", "https://x", "image/png"))


def test_through_mcp_a_deletion_waiting_for_the_owner_raises_as_one(api, client):
    api.get("/v1/workflows/tables").respond(json={"object": "list", "data": [TABLE], "next_cursor": None})
    api.delete("/v1/workflows/tables/res_t1").respond(402, json={"error": {
        "type": "approval_required", "message": "This waits for the account's owner.",
        "approval_id": "apr_1", "summary": "Delete workflow table 'Orders'", "sent_to": ["email"]}})
    [orders] = nc.WorkflowTable.list()
    with pytest.raises(nc.ApprovalRequired):
        orders.delete()


def test_a_team_workspace_is_made_a_teammate_invited_and_the_session_switched(api, client):
    made = api.post("/v1/organizations").respond(201, json={"object": "organization", "organization": {
        "id": "org_1", "name": "Acme Ops", "slug": "acme-ops"}})
    invited = api.post("/v1/organizations/org_1/members").respond(201, json={
        "object": "organization_invite", "invite": {"id": "inv_1", "email": "sam@example.com", "role": "admin"},
        "email_sent": True})
    api.get("/v1/organizations/org_1/members").respond(json={"object": "list", "data": [
        {"user_id": "u_1", "email": "olu@example.com", "role": "owner"}], "next_cursor": None})
    switched = api.post("/v1/me/organization").respond(json={"object": "organization_switch"})
    acme = nc.Organization.create("Acme Ops")
    assert json.loads(made.calls.last.request.content) == {"name": "Acme Ops"}
    assert (acme.id, acme.role) == ("org_1", "owner")
    invite = nc.Organization.invite(acme, "sam@example.com", role="admin")
    assert (invite["id"], invite["email_sent"]) == ("inv_1", True)
    assert json.loads(invited.calls.last.request.content) == {"email": "sam@example.com", "role": "admin"}
    assert [m["role"] for m in nc.Organization.members("org_1")] == ["owner"]
    nc.Organization.switch_to(None)
    assert json.loads(switched.calls.last.request.content) == {}
def test_a_workflow_is_shared_changed_and_unshared_and_a_person_leaves_one(api, client):
    share = {"object": "share", "id": "sh_1", "resource_type": "workflow", "resource_id": "wf_1", "with": "user",
             "user_id": "u_2", "email": "sam@example.com", "organization_id": None, "name": "Sam", "access": "edit",
             "pending": False, "url": None, "created_at": "2026-11-24T10:00:00+00:00"}
    made = api.post("/v1/shares").respond(201, json=share)
    api.get("/v1/shares").respond(json={"object": "list", "data": [share], "next_cursor": None})
    changed = api.patch("/v1/shares/sh_1").respond(json={**share, "access": "view"})
    gone = api.delete("/v1/shares/sh_1").respond(json={"object": "share", "id": "sh_1", "deleted": True})
    left = api.post("/v1/shares/leave").respond(json={"object": "share_leave", "left": True})
    created = nc.Share.create(nc.Workflow.from_id("wf_1"), email="sam@example.com", access="edit")
    assert json.loads(made.calls.last.request.content) == {
        "resource_type": "workflow", "resource_id": "wf_1", "access": "edit", "with": "user",
        "email": "sam@example.com"}
    assert (created.with_, created.name, created.access) == ("user", "Sam", "edit")
    [listed] = nc.Share.list("wf_1", resource_type="workflow")
    assert listed.update("view").access == "view"
    assert json.loads(changed.calls.last.request.content) == {"access": "view"}
    listed.delete()
    assert gone.called
    assert nc.Share.leave("db_1", resource_type="database") is True
    assert json.loads(left.calls.last.request.content) == {"resource_type": "database", "resource_id": "db_1"}


def test_an_agent_steps_workspaces_list_as_resources_lists_them_each_reading_its_files(api, client):
    place = {"object": "step_workspace", "workflow": {"id": "wf_1", "name": "Intake", "step_types": ["agent"]},
             "step_id": "helper", "step_name": "Helper", "model": "claude-code", "conversation": "orders",
             "title": "Orders", "last_activity": "2026-11-24T10:00:00+00:00"}
    listed = api.get("/v1/workflows/workspaces").respond(json={"object": "list", "data": [place], "next_cursor": None})
    files = api.get("/v1/workflows/wf_1/steps/helper/workspace").respond(json={
        "object": "list", "data": [], "workspace": "/workspace", "exists": True, "truncated": False,
        "upload_url": None})
    [orders] = nc.AgentStepWorkspace.list(organization_id="none")
    assert dict(listed.calls.last.request.url.params) == {"organization_id": "none"}
    assert (orders.step_id, orders.step_name, orders.conversation, orders.workflow["id"]) == (
        "helper", "Helper", "orders", "wf_1")
    assert orders.files().workspace == "/workspace"
    assert dict(files.calls.last.request.url.params) == {"conversation": "orders"}
