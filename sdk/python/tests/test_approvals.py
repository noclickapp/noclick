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


CHANGE = {
    "object": "approval_policy_change", "id": "chg_1", "batch_id": "bat_1", "kind": "purchase", "target": "setting",
    "before": None, "after": {"disposition": "allow", "under_usd": 20.0, "until": None}, "loosens": True,
    "changed_by": "key", "key_id": "key_9", "effective_at": "2026-11-21T09:10:00+00:00", "until": None,
    "pending": True, "undone_at": None, "undone_by": None, "created_at": "2026-11-21T09:00:00+00:00",
}
SET = {**POLICY, "spend_cap_set": True, "changes": [CHANGE], "kinds": [
    {**POLICY["kinds"][0], "settable": True,
     "setting": {"disposition": "allow", "under_usd": 20.0, "until": None, "pending": True},
     "ceiling": None, "effective": {"connected_app": "under_auto_approve", "agent": "ask", "app": "allow"}},
    POLICY["kinds"][1]]}


def test_the_account_switches_kinds_as_the_account_and_reads_back_what_changed(api, client):
    from datetime import datetime, timezone

    put = api.put("/v1/approvals/policy").respond(json=SET)
    until = datetime(2026, 11, 22, tzinfo=timezone.utc)
    with nc.as_user("user_42"):
        policy = nc.ApprovalPolicy.set(settings={"purchase": {"disposition": "allow", "under_usd": 20},
                                                 "purge": {"disposition": "allow", "until": until}, "delete": None})
    request = put.calls.last.request
    assert "NoClick-User" not in request.headers
    assert body(request) == {"settings": {"purchase": {"disposition": "allow", "under_usd": 20},
                                          "purge": {"disposition": "allow", "until": until.isoformat()},
                                          "delete": None}}
    [change] = policy.changes
    assert (change.kind, change.loosens, change.pending, change.changed_by) == ("purchase", True, True, "key")
    assert change.effective_at.minute == 10 and policy.spend_cap_set is True
    assert policy.kinds[0].settable and policy.kinds[0].setting["under_usd"] == 20.0
    assert policy.effective("purchase", "agent") == "ask"


def test_a_switch_needs_a_cap_explain_reads_and_undo_takes_one_back(api, client):
    api.put("/v1/approvals/policy").respond(403, json={"error": {
        "type": "permission_denied", "message": "Letting a purchase through past NoClick's default needs a cap.",
        "reason": "spend_cap_required", "field": "settings.purchase"}})
    with pytest.raises(nc.PermissionDenied, match="needs a cap"):
        nc.ApprovalPolicy.set(settings={"purchase": "allow"})
    explained = api.post("/v1/approvals/policy/explain").respond(json={
        "object": "approval_explanation", "kind": "purchase", "caller": "agent", "disposition": "ask",
        "source": "default", "why": "Purchases through an API key always ask.", "setting": None, "bounds": False})
    seen = nc.ApprovalPolicy.explain("purchase", "agent", amount_usd=12)
    assert body(explained.calls.last.request) == {"kind": "purchase", "caller": "agent", "amount_usd": 12,
                                                  "quoted": True, "previewed": True}
    assert (seen.disposition, seen.source, seen.why) == ("ask", "default", "Purchases through an API key always ask.")
    listed = api.get("/v1/approvals/policy/changes").respond(json=listing(CHANGE))
    [change] = nc.ApprovalPolicy.history(limit=5)
    assert listed.calls.last.request.url.params["limit"] == "5" and change.id == "chg_1"
    api.post("/v1/approvals/policy/changes/chg_1/undo").respond(json={
        **CHANGE, "pending": False, "undone_at": "2026-11-21T09:02:00+00:00", "undone_by": "owner"})
    undone = nc.ApprovalPolicy.undo("chg_1")
    assert (undone.undone_by, undone.pending) == ("owner", False)
