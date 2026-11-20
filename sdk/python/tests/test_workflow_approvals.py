"""A workflow's Approval steps, listed, read and answered from code (a key that names ``approvals:answer``), always
as the account, against the mocked transport."""

import pytest

import noclick as nc
from platform_helpers import body, listing

APPROVAL = {
    "object": "workflow_approval", "id": "wa_1", "workflow_id": "wf_1", "workflow_name": "Invoices",
    "run_id": "run_1", "step": "gate", "title": "Pay invoice 1042",
    "fields": [{"name": "amount", "type": "number", "label": "Amount", "description": "", "required": True,
                "options": None}],
    "values": {"amount": "420"}, "status": "pending", "created_at": "2026-11-20T09:00:00Z",
    "expires_at": "2026-11-27T09:00:00Z", "decided_at": None, "decided_by": None, "decided_by_key": None,
    "note": None, "sent_to": ["email"],
}
WORKFLOW = {"object": "workflow", "id": "wf_1", "name": "Invoices", "version": 3}


def test_a_workflows_waiting_steps_list_and_one_loads_by_id(api, client):
    api.get("/v1/workflows", params={"name": "Invoices"}).respond(json=listing(WORKFLOW))
    api.get("/v1/workflows/wf_1").respond(json=WORKFLOW)
    listed = api.get("/v1/workflows/wf_1/approvals").respond(json=listing(APPROVAL))
    [approval] = nc.Workflow.from_name("Invoices").approvals(status="pending")
    assert listed.calls.last.request.url.params["status"] == "pending"
    assert "NoClick-User" not in listed.calls.last.request.headers
    assert (approval.id, approval.workflow_id, approval.run_id, approval.step, approval.status) == (
        "wa_1", "wf_1", "run_1", "gate", "pending")
    assert approval.values == {"amount": "420"} and approval.fields[0]["label"] == "Amount"
    assert approval.expires_at.day == 27 and approval.decided_by is None and approval.sent_to == ["email"]

    api.get("/v1/workflows/wf_1/approvals/wa_1").respond(json=APPROVAL)
    lazy = nc.WorkflowApproval.from_id("wf_1", "wa_1")
    assert (lazy.title, lazy.workflow_name) == ("Pay invoice 1042", "Invoices")
    assert [a.id for a in nc.WorkflowApproval.list("wf_1")] == ["wa_1"]


def test_code_approves_with_values_and_declines_as_the_account_never_as_a_user(api, client):
    decided = {**APPROVAL, "status": "approved", "decided_at": "2026-11-20T09:05:00Z", "decided_by": "code",
               "decided_by_key": {"key_id": "key_9", "key_name": "approver"}, "note": "Checked.",
               "values": {"amount": "400"}}
    answer = api.post("/v1/workflows/wf_1/approvals/wa_1/answer").respond(json=decided)
    with nc.as_user("user_42"):
        approval = nc.WorkflowApproval.from_id("wf_1", "wa_1").approve(note="Checked.", values={"amount": "400"})
    request = answer.calls.last.request
    assert body(request) == {"approved": True, "note": "Checked.", "values": {"amount": "400"}}
    assert "NoClick-User" not in request.headers
    assert (approval.status, approval.decided_by, approval.decided_by_key["key_id"], approval.values) == (
        "approved", "code", "key_9", {"amount": "400"})

    declined = api.post("/v1/workflows/wf_1/approvals/wa_2/answer").respond(
        json={**APPROVAL, "id": "wa_2", "status": "declined"})
    assert nc.WorkflowApproval.from_id(nc.Workflow.from_id("wf_1"), "wa_2").decline().status == "declined"
    assert body(declined.calls.last.request) == {"approved": False}


def test_a_key_without_the_scope_a_second_answer_and_a_late_one_are_refused(api, client):
    route = api.post("/v1/workflows/wf_1/approvals/wa_1/answer")
    route.respond(403, json={"error": {"type": "permission_denied", "scope": "approvals:answer",
                                       "message": "This key lacks the 'approvals:answer' scope."}})
    with pytest.raises(nc.PermissionDenied, match="approvals:answer"):
        nc.WorkflowApproval.from_id("wf_1", "wa_1").approve()
    route.respond(409, json={"error": {"type": "conflict", "message": "This approval was already answered."}})
    with pytest.raises(nc.Conflict, match="already answered"):
        nc.WorkflowApproval.from_id("wf_1", "wa_1").decline()
    route.respond(410, json={"error": {"type": "expired", "message": "This approval expired."}})
    with pytest.raises(nc.Expired):
        nc.WorkflowApproval.from_id("wf_1", "wa_1").approve()
