"""``Human.ask`` with ``connect`` (which connection a workflow step uses) and ``secret`` (a secret's values), and
``HumanRequest.answer`` from code: what the calls send and how the answers read, against the mocked transport."""

import noclick as nc
from platform_helpers import body, operation

CREATED = {**operation(op_id="op_h", kind="human.ask"),
           "request": {"id": "hr_1", "url": None, "delivered_via": ["web"], "undelivered": []}}


def test_connect_names_the_step_and_the_answer_its_connection(api, client):
    create = api.post("/v1/humans/requests").respond(json=CREATED)
    api.get("/v1/operations/op_h/wait").respond(json=operation(
        op_id="op_h", kind="human.ask", status="succeeded",
        result={"choice": "Slack", "value": "credential:c1", "connection": "credential:c1", "version": 3},
    ))
    wf = nc.Workflow.from_id("wf_1")
    request = nc.Human.owner().ask("Which Slack should Post use?",
                                   connect={"integration": "slack", "step": {"workflow": wf, "step_id": "post"}})
    assert body(create.calls.last.request) == {
        "kind": "ask", "to": {"owner": True}, "message": "Which Slack should Post use?",
        "connect": {"integration": "slack", "step": {"workflow_id": "wf_1", "step_id": "post"}}, "via": "auto",
    }
    answer = request.wait()
    assert (answer.connection, answer.value, answer.choice, answer.secret) == (
        "credential:c1", "credential:c1", "Slack", None)


def test_secret_names_its_keys_and_the_answer_only_the_secret(api, client):
    create = api.post("/v1/humans/requests").respond(json=CREATED)
    api.get("/v1/operations/op_h/wait").respond(json=operation(
        op_id="op_h", kind="human.ask", status="succeeded",
        result={"secret": "warehouse", "secret_id": "sec_1", "keys": ["WAREHOUSE_TOKEN"]},
    ))
    request = nc.Human(email="dev@acme.com").ask(
        "The warehouse token, please.", secret={"name": "warehouse", "keys": ("WAREHOUSE_TOKEN",)})
    assert body(create.calls.last.request) == {
        "kind": "ask", "to": {"email": "dev@acme.com"}, "message": "The warehouse token, please.",
        "secret": {"name": "warehouse", "keys": ["WAREHOUSE_TOKEN"]}, "via": "auto",
    }
    answer = request.wait()
    assert (answer.secret, answer.connection, str(answer)) == ("warehouse", None, "warehouse")


def test_code_answers_with_a_connection_or_the_values(api, client):
    api.post("/v1/humans/requests").respond(json=CREATED)
    answered = api.post("/v1/humans/requests/hr_1/answer").respond(json={"id": "hr_1", "status": "answered"})
    request = nc.Human.owner().ask("Which Slack?", connect={"integration": "slack",
                                                            "step": {"workflow_id": "wf_1", "step_id": "post"}})
    request.answer(connection=nc.Connection.from_id("con_9"))
    assert body(answered.calls.last.request) == {"connection": "con_9"}
    request.answer(secret_values={"WAREHOUSE_TOKEN": "v"})
    assert body(answered.calls.last.request) == {"secret_values": {"WAREHOUSE_TOKEN": "v"}}
    assert request.request_status == "answered"
    request.approve(note="fine")
    assert body(answered.calls.last.request) == {"approved": True, "note": "fine"}
