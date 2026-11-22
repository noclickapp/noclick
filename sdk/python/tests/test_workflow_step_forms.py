"""What a step's form shows beside its settings (``POST /v1/workflows/{id}/steps/{step}/options`` and ``.../values``):
what the client sends and how it reads the answer, against the mocked transport."""

import httpx
import pytest

import noclick as nc
from platform_helpers import body

WF = "wf_1"


def test_a_steps_choices_page_through_with_its_unsaved_settings_and_no_user(api, client):
    route = api.post(f"/v1/workflows/{WF}/steps/read_sheet/options").mock(side_effect=[
        httpx.Response(200, json={"object": "step_options", "workflow_id": WF, "step_id": "read_sheet",
                                  "field": "spreadsheet_id", "next_page_token": "2", "withheld": [],
                                  "options": [{"value": "sp_1", "label": "Budget", "metadata": {"icon": "s"}}]}),
        httpx.Response(200, json={"object": "step_options", "workflow_id": WF, "step_id": "read_sheet",
                                  "field": "sheet_name", "next_page_token": None, "withheld": ["options[1]"],
                                  "options": [{"value": "Q3", "label": "Q3", "metadata": None}]}),
    ])
    sheet = nc.Workflow.from_id(WF).step("read_sheet")
    with nc.as_user("user_42"):
        first = sheet.options("spreadsheet_id", search="budget")
    assert body(route.calls[0].request) == {"field": "spreadsheet_id", "search": "budget"}
    assert "NoClick-User" not in route.calls[0].request.headers
    assert (first.field, first.next_page_token, first.withheld) == ("spreadsheet_id", "2", [])
    [choice] = first.options
    assert (choice.value, choice.label, choice.metadata) == ("sp_1", "Budget", {"icon": "s"})

    tabs = sheet.options("sheet_name", settings={"spreadsheet_id": "sp_1"}, page_token="2")
    assert body(route.calls[1].request) == {"field": "sheet_name", "settings": {"spreadsheet_id": "sp_1"},
                                            "page_token": "2"}
    assert tabs.next_page_token is None and tabs.withheld == ["options[1]"] and tabs.options[0].metadata is None


def test_a_widgets_value_reads_one_value_or_several_and_what_was_withheld(api, client):
    hook = api.post(f"/v1/workflows/{WF}/steps/hook/values").respond(json={
        "object": "step_value", "workflow_id": WF, "step_id": "hook", "field": "webhook_url", "value": None,
        "values": {"webhook_url": "https://wf-1.noclick.run", "trigger_registered": True},
        "withheld": ["signing_secret"]})
    found = nc.Workflow.from_id(WF).step("hook").value("webhook_url", settings={"operation": "on_order"})
    assert body(hook.calls.last.request) == {"field": "webhook_url", "settings": {"operation": "on_order"}}
    assert found.values == {"webhook_url": "https://wf-1.noclick.run", "trigger_registered": True}
    assert (found.field, found.value, found.withheld) == ("webhook_url", None, ["signing_secret"])

    api.post(f"/v1/workflows/{WF}/steps/disk/values").respond(json={
        "object": "step_value", "workflow_id": WF, "step_id": "disk", "field": "file_browser",
        "value": {"files": [{"path": "notes.md"}], "count": 1}, "values": None, "withheld": []})
    disk = nc.Workflow.from_id(WF).step("disk").value("file_browser")
    assert disk.value == {"files": [{"path": "notes.md"}], "count": 1} and disk.values is None


def test_a_step_id_is_one_path_segment_and_a_refusal_is_typed(api, client):
    api.post(f"/v1/workflows/{WF}/steps/a%2Fb/values").respond(404, json={"error": {
        "type": "not_found", "message": "No step 'a/b' in 'Orders'.",
        "next_step": "Read its steps with GET /v1/workflows/{id}/graph."}})
    with pytest.raises(nc.NotFound, match="No step 'a/b'"):
        nc.Workflow.from_id(WF).step("a/b").value("webhook_url")
    api.post(f"/v1/workflows/{WF}/steps/mcp/values").respond(403, json={"error": {
        "type": "permission_denied", "message": "Loading a hosted MCP link is out of reach over MCP."}})
    with pytest.raises(nc.PermissionDenied):
        nc.Workflow.from_id(WF).step("mcp").value("hosted_url")


def test_a_step_not_saved_yet_lists_its_choices_by_its_type_through_the_account_its_form_holds(api, client):
    route = api.post(f"/v1/workflows/{WF}/steps/new_sheet/options").respond(json={
        "object": "step_options", "workflow_id": WF, "step_id": "new_sheet", "field": "spreadsheet_id",
        "next_page_token": None, "withheld": [], "options": [{"value": "sp_1", "label": "Budget", "metadata": None}]})
    found = nc.Workflow.from_id(WF).step("new_sheet").options(
        "spreadsheet_id", type="automation-google-sheets", connection="credential:cred_1",
        settings={"operation": "read_sheet_data"})
    assert body(route.calls.last.request) == {
        "field": "spreadsheet_id", "settings": {"operation": "read_sheet_data"},
        "type": "automation-google-sheets", "connection": "credential:cred_1"}
    assert [o.value for o in found.options] == ["sp_1"]


async def test_both_read_the_same_in_async_code(api, client):
    api.post(f"/v1/workflows/{WF}/steps/post/options").respond(json={
        "object": "step_options", "field": "channel", "next_page_token": None, "withheld": [],
        "options": [{"value": "C1", "label": "#team", "metadata": None}]})
    found = await nc.Workflow.from_id(WF).step("post").options.aio("channel")
    assert [o.value for o in found.options] == ["C1"]
