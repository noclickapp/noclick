"""An agent step's chats (``Step.conversations``, ``Step.conversation``, ``Step.delete_conversation``,
``Step.message``): what each call sends and how it reads the answer, against the mocked transport."""

import json

import noclick as nc
from platform_helpers import USER_ID

CHAT = {"object": "step_conversation", "conversation": "orders", "title": "Orders", "preview": "Where's 1042?",
        "turns": 2, "last_activity": "2026-11-24T10:00:00+00:00", "created_at": "2026-11-24T09:00:00+00:00",
        "agent_model": "openrouter/x", "shared": False}
OP = {"object": "operation", "id": "op_1", "kind": "workflow.run", "status": "queued", "result": None,
      "error": None}


def test_a_steps_chats_are_listed_and_read_for_the_person(api, client):
    listed = api.get("/v1/workflows/wf_1/steps/helper/conversations").respond(json={"object": "list", "data": [
        CHAT, {**CHAT, "conversation": "share:l:v:c", "shared": True}]})
    with nc.as_user(USER_ID):
        chats = nc.Workflow.from_id("wf_1").step("helper").conversations(limit=20)
    assert "NoClick-User" not in listed.calls.last.request.headers
    assert listed.calls.last.request.url.params["limit"] == "20"
    assert [(c.conversation, c.title, c.turns, c.shared, c.messages) for c in chats] == [
        ("orders", "Orders", 2, False, None), ("share:l:v:c", "Orders", 2, True, None)]
    messages = [{"role": "user", "message": "Where's 1042?"}, {"role": "assistant", "message": "Shipped."}]
    read = api.get("/v1/workflows/wf_1/steps/helper/conversations/a%2Fb").respond(json={
        "object": "step_conversation_thread", "conversation": "a/b", "messages": messages})
    thread = nc.Workflow.from_id("wf_1").step("helper").conversation("a/b")
    assert read.called and (thread.conversation, thread.messages) == ("a/b", messages)


def test_deleting_a_chat(api, client):
    route = api.delete("/v1/workflows/wf_1/steps/helper/conversations/orders").respond(json={
        "object": "step_conversation", "conversation": "orders", "deleted": True})
    assert nc.Workflow.from_id("wf_1").step("helper").delete_conversation("orders") is None
    assert route.called


def test_saying_something_is_a_run_from_the_step(api, client):
    route = api.post("/v1/workflows/wf_1/steps/helper/messages").respond(
        status_code=202, json={"object": "step_message", "conversation": "orders", "run": OP})
    op = nc.Workflow.from_id("wf_1").step("helper").message(
        "Total {{ x }}", conversation="orders", model="openrouter/x", attachments=[{"resource_id": "r1"}])
    assert json.loads(route.calls.last.request.content) == {
        "message": "Total {{ x }}", "conversation": "orders", "model": "openrouter/x",
        "attachments": [{"resource_id": "r1"}]}
    assert (op.id, op.kind) == ("op_1", "workflow.run")
    nc.Workflow.from_id("wf_1").step("helper").message("hi")
    assert json.loads(route.calls.last.request.content) == {"message": "hi"}


SHARE = {"object": "share_link", "url": "https://noclick.test/a/l1", "enabled": True, "workflow_id": "wf_1",
         "step_id": "helper", "created_at": "2026-11-24T09:00:00+00:00"}


def test_a_steps_chat_page_turns_on_off_and_rotates(api, client):
    on = api.post("/v1/workflows/wf_1/steps/helper/share").respond(json=SHARE)
    link = nc.Workflow.from_id("wf_1").step("helper").share()
    assert on.called and (link.url, link.enabled, link.step_id, link.agent_id) == (SHARE["url"], True, "helper", None)
    off = api.patch("/v1/workflows/wf_1/steps/helper/share").respond(json={**SHARE, "enabled": False})
    assert link.disable().enabled is False
    assert json.loads(off.calls.last.request.content) == {"enabled": False}
    api.post("/v1/workflows/wf_1/steps/helper/share/rotate").respond(json={**SHARE, "url": "https://noclick.test/a/l2"})
    assert link.rotate().url == "https://noclick.test/a/l2"
    api.get("/v1/workflows/wf_1/steps/helper/share").respond(404, json={"error": {"type": "not_found", "message": "no"}})
    assert nc.Workflow.from_id("wf_1").step("helper").share_link() is None
