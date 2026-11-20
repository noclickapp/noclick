"""Approvals: the calls NoClick holds for the account's owner's yes, listed, read and answered from code (a key that
names ``approvals:answer``), always as the account, against the mocked transport."""

import pytest

import noclick as nc
from platform_helpers import body, listing

APPROVAL = {
    "object": "approval", "id": "apr_1", "status": "pending", "action": "Buy +1 567 483 3618", "summary": None,
    "subject": None, "price": {"amount_usd": 1.15, "recurrence": "monthly", "terms": None, "renewal": None},
    "operation": "phone_numbers_create", "method": "POST", "path": "/v1/phone_numbers",
    "arguments": {"number": "+15674833618"}, "reason": "Purchases through an API key always ask.",
    "connection": {"kind": "agent", "name": "Support", "grant_id": None, "agent_id": "agt_1"}, "user_id": None,
    "operation_id": "op_held", "held_call_status": "awaiting_human", "created_at": "2026-11-19T10:00:00Z",
    "expires_at": "2026-11-20T10:00:00Z", "decided_at": None, "decided_by": None, "decided_by_key": None,
    "note": None, "sent_to": ["email"], "impact": None, "consent": [],
}


def test_pending_approvals_list_and_one_loads_by_id(api, client):
    listed = api.get("/v1/approvals").respond(json=listing(APPROVAL))
    api.get("/v1/approvals/apr_1").respond(json=APPROVAL)
    [approval] = nc.Approval.list(status="pending")
    assert listed.calls.last.request.url.params["status"] == "pending"
    assert (approval.id, approval.status, approval.operation, approval.operation_id) == (
        "apr_1", "pending", "phone_numbers_create", "op_held")
    assert approval.price["amount_usd"] == 1.15 and approval.connection["kind"] == "agent"
    assert approval.expires_at.day == 20 and approval.decided_by is None
    lazy = nc.Approval.from_id("apr_1")
    assert (lazy.action, lazy.sent_to) == ("Buy +1 567 483 3618", ["email"])


def test_code_approves_and_declines_as_the_account_never_as_a_user(api, client):
    decided = {**APPROVAL, "status": "approved", "decided_at": "2026-11-19T10:05:00Z", "decided_by": "code",
               "decided_by_key": {"key_id": "key_9", "key_name": "approver"}, "note": "Fine."}
    answer = api.post("/v1/approvals/apr_1/answer").respond(json=decided)
    with nc.as_user("user_42"):
        approval = nc.Approval.from_id("apr_1").approve(note="Fine.")
    request = answer.calls.last.request
    assert body(request) == {"approved": True, "note": "Fine."} and "NoClick-User" not in request.headers
    assert (approval.status, approval.decided_by, approval.decided_by_key["key_id"], approval.note) == (
        "approved", "code", "key_9", "Fine.")

    api.post("/v1/approvals/apr_2/answer").respond(json={**APPROVAL, "id": "apr_2", "status": "declined"})
    assert nc.Approval.from_id("apr_2").decline().status == "declined"


def test_a_key_without_the_scope_or_that_made_the_call_is_refused(api, client):
    api.post("/v1/approvals/apr_1/answer").respond(403, json={"error": {
        "type": "permission_denied", "message": "This key lacks the 'approvals:answer' scope.",
        "scope": "approvals:answer"}})
    with pytest.raises(nc.PermissionDenied, match="approvals:answer"):
        nc.Approval.from_id("apr_1").approve()


POLICY = {
    "object": "approval_policy",
    "callers": {"agent": "A platform agent's NoClick tools, and its own tool calls.", "key": "A key used through MCP."},
    "kinds": [
        {"kind": "purchase", "description": "A call with a price.", "approver": "owner", "outside_only": False,
         "defaults": {"connected_app": "under_auto_approve", "agent": "ask", "app": "allow"}},
        {"kind": "outside_other_connection", "description": "A stranger's turn beyond what it answers on.",
         "approver": "connection_owner", "outside_only": True, "defaults": {"agent": "ask"}},
    ],
}


def test_the_default_policy_reads_kind_by_kind_and_caller_by_caller(api, client):
    read = api.get("/v1/approvals/policy").respond(json=POLICY)
    with nc.as_user("user_42"):
        policy = nc.ApprovalPolicy.get()
    assert "NoClick-User" not in read.calls.last.request.headers
    assert [k.kind for k in policy.kinds] == ["purchase", "outside_other_connection"]
    assert policy.default("purchase", "agent") == "ask"
    assert policy.default("purchase", "connected_app") == "under_auto_approve"
    assert policy.default("purchase", "code") is None
    stranger = policy.kinds[1]
    assert (stranger.approver, stranger.outside_only, stranger.defaults) == ("connection_owner", True, {"agent": "ask"})
    assert policy.callers["agent"].startswith("A platform agent's")
    with pytest.raises(KeyError, match="no kind 'refund'"):
        policy.default("refund", "agent")
