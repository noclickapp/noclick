"""A coding agent's permission mode per conversation, and answering what its harness asks a person (an approval, a
question) from code."""

import noclick as nc
from platform_helpers import agent_row, body

AGENT = agent_row(id="ag_1", name="coder", harness="claude_code")
ASKED = {"object": "harness_request", "id": "req_1", "kind": "approval", "action": "command",
         "title": "Run git push origin main", "detail": "git push origin main", "status": "pending",
         "options": [{"option_id": "allow_once", "name": "Approve", "kind": "allow_once"}],
         "operation_id": "op_1", "created_at": "2026-11-10T10:00:00Z", "expires_at": "2026-11-10T10:20:00Z"}


def test_a_conversations_permission_mode_is_set_and_read_back(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    route = api.patch("/v1/agents/ag_1/conversations/main%2F1").respond(json={
        "object": "conversation_settings", "permission_mode": "auto", "effective_permission_mode": "approval-required",
        "permission_modes": ["approval-required", "auto-accept-edits", "full-access"],
        "not_supported": {"auto": "No automatic review here."}})
    settings = nc.Agent.from_id("ag_1").set_permission_mode("main/1", "auto")
    assert body(route.calls.last.request) == {"permission_mode": "auto"}
    assert (settings.permission_mode, settings.effective_permission_mode) == ("auto", "approval-required")
    assert settings.permission_modes == ["approval-required", "auto-accept-edits", "full-access"]
    assert "auto" in settings.not_supported


def test_what_the_harness_asks_is_listed_and_answered(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    listed = api.get("/v1/agents/ag_1/conversations/main/requests").respond(json={"object": "list", "data": [ASKED]})
    coder = nc.Agent.from_id("ag_1")
    [asked] = coder.requests("main", status="pending")
    assert listed.calls.last.request.url.params["status"] == "pending"
    assert (asked.id, asked.kind, asked.action, asked.title, asked.status) == (
        "req_1", "approval", "command", "Run git push origin main", "pending")
    assert asked.expires_at.isoformat().startswith("2026-11-10T10:20")
    answered = api.post("/v1/agents/ag_1/conversations/main/requests/req_1").respond(json={
        **ASKED, "status": "answered", "answer": {"decision": "reject_once", "note": "Use a branch."}})
    done = coder.answer("main", "req_1", "reject_once", note="Use a branch.")
    assert body(answered.calls.last.request) == {"decision": "reject_once", "note": "Use a branch."}
    assert done.status == "answered" and done.answer["note"] == "Use a branch."


def test_a_question_is_answered_with_its_answers(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    route = api.post("/v1/agents/ag_1/conversations/main/requests/req_q").respond(json={
        **ASKED, "id": "req_q", "kind": "question", "status": "answered"})
    nc.Agent.from_id("ag_1").answer("main", "req_q", "allow_once", answers={"Which color?": ["Blue"]})
    assert body(route.calls.last.request) == {"decision": "allow_once", "answers": {"Which color?": ["Blue"]}}
