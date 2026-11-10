"""Offline factory, authentication, fixed routes and provider-envelope regressions."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import filevine_node as fv
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-filevine-token"
AUTH = {"credential_type": "filevine_access_token", "access_token": TOKEN, "org_id": 100}
FIXTURES = json.loads((Path(__file__).parent / "fixtures/filevine/responses.json").read_text())


def node(config, auth=AUTH):
    return NodeFactory.create_node(node_id="filevine-test", node_type="automation-filevine",
        node_data={"config": config, "credentials": auth})


@pytest.fixture
def wire(monkeypatch):
    requests, replies = [], []
    def send(request):
        requests.append(request)
        code, body = replies.pop(0)
        return httpx.Response(code, json=body)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(send), **kwargs)
    monkeypatch.setattr(fv, "guarded_async_client", client)
    return requests, replies


# These expectations are independent of the node's route/body tables.
CASES = [
    ("list_projects", {}, "GET", "/Projects", None),
    ("get_project", {"project_id": "100"}, "GET", "/Projects/100", None),
    ("create_project", {"project_type_id": "200", "client_id": "300", "project_name": "Smith"}, "POST", "/Projects", {"ProjectTypeId": {"Native": 200}, "ClientId": {"Native": 300}, "ProjectName": "Smith"}),
    ("update_project", {"project_id": "100", "phase_id": "400"}, "PATCH", "/Projects/100", {"PhaseId": {"Native": 400}}),
    ("list_contacts", {"search_term": "Smith"}, "GET", "/Contacts", None),
    ("get_contact", {"contact_id": "300"}, "GET", "/Contacts/300", None),
    ("create_contact", {"first_name": "Jane", "last_name": "Smith", "primary_email": "jane@example.test"}, "POST", "/Contacts", {"FirstName": "Jane", "LastName": "Smith", "PrimaryEmail": "jane@example.test"}),
    ("update_contact", {"contact_id": "300", "notes": "Changed"}, "PATCH", "/Contacts/300", {"Notes": "Changed"}),
    ("list_notes", {"offset": 25}, "GET", "/Notes", None),
    ("get_note", {"note_id": "123"}, "GET", "/Notes/123", None),
    ("create_note", {"project_id": "100", "body": "Discussed case strategy and next steps.", "subject": "Client intake call"}, "POST", "/Notes", {"ProjectId": {"Native": 100}, "Body": "Discussed case strategy and next steps.", "Subject": "Client intake call"}),
    ("list_project_notes", {"project_id": "100"}, "GET", "/Projects/100/Notes", None),
    ("list_tasks", {}, "GET", "/tasks", None),
    ("get_task", {"task_id": "123"}, "GET", "/tasks/123", None),
    ("create_task", {"project_id": "100", "body": "Review contract terms", "assignee_id": "300", "target_date": "2025-03-15T12:00:00Z"}, "POST", "/tasks", {"ProjectId": {"Native": 100}, "Body": "Review contract terms", "AssigneeId": {"Native": 300}, "TargetDate": "2025-03-15T12:00:00Z"}),
    ("assign_task", {"task_id": "123", "assignee_id": "300"}, "PATCH", "/tasks/123/assign/300", None),
    ("list_project_tasks", {"project_id": "100"}, "GET", "/projects/100/tasks", None),
    ("list_comments", {"note_id": "123"}, "GET", "/Notes/123/Comments", None),
    ("create_comment", {"note_id": "123", "body": "Reviewed the attached documents."}, "POST", "/Notes/123/Comments", {"Body": "Reviewed the attached documents."}),
    ("get_current_user", {}, "GET", "/Users/Me", None),
    ("list_project_types", {}, "GET", "/ProjectTypes", None),
    ("list_project_phases", {"project_type_id": "200"}, "GET", "/ProjectTypes/200/phases", None),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,arguments,method,path,body", CASES)
async def test_filevine_fixed_single_request_contract(wire, operation, arguments, method, path, body):
    requests, replies = wire
    payload = {"Items": [], "HasMore": False} if operation.startswith("list_") else FIXTURES["user" if operation == "get_current_user" else "note"]
    replies.append((200, payload))
    result = await node({"operation": operation, **arguments}).execute({})
    assert result["status"] == "success" and len(requests) == 1 and not replies
    request = requests[0]
    assert request.method == method and request.url.path == "/fv-app/v2" + path
    assert request.url.host == "api.filevineapp.com"
    assert request.headers["authorization"] == "Bearer " + TOKEN
    assert request.headers["x-fv-orgid"] == "100"
    assert TOKEN not in str(request.url) and "must-not-escape" not in json.dumps(result)
    if body is not None:
        assert json.loads(request.content) == body
    else:
        assert not request.content
    if operation == "list_contacts":
        assert request.url.params["searchTerm"] == "Smith"
    if operation == "list_notes":
        assert request.url.params["offset"] == "25" and "limit" not in request.url.params


@pytest.mark.asyncio
async def test_filevine_page_keeps_account_items_and_never_follows_links(wire):
    requests, replies = wire
    replies.append((200, FIXTURES["projects"]))
    result = await node({"operation": "list_projects", "offset": 10, "limit": 1}).execute({})
    assert result["items"][0]["ProjectName"] == "Smith matter"
    assert result["next_offset"] == 11 and result["has_more"] is True
    assert len(requests) == 1
    replies.append((200, {"Items": [], "HasMore": False}))
    assert (await node({"operation": "list_projects", "offset": 11}).execute({}))["next_offset"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
async def test_filevine_rejection_is_not_success_and_redacts_token(wire, status):
    requests, replies = wire
    replies.append((status, {"message": "Rejected " + TOKEN}))
    with pytest.raises(ValueError) as error:
        await node({"operation": "list_projects"}).execute({})
    assert str(status) in str(error.value) and TOKEN not in str(error.value)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [[], {}, {"Items": {}}, {"Items": [], "HasMore": "true"}, {"error": "denied"}])
async def test_filevine_bad_list_envelopes_fail(wire, payload):
    wire[1].append((200, payload))
    with pytest.raises(ValueError):
        await node({"operation": "list_projects"}).execute({})


@pytest.mark.parametrize("identifier", ["..", "0", "1/2", "123?x=1", "2147483648", "https://evil.example", "1\n"])
def test_filevine_invalid_native_ids(identifier):
    with pytest.raises(ValidationError):
        fv.FilevineGetProjectConfig(project_id=identifier)


def test_filevine_manual_credential_and_required_inputs():
    credential = fv.FilevineAccessTokenCredential(access_token="  " + TOKEN + "  ", org_id=100)
    assert credential.credential_type == "filevine_access_token" and credential.access_token == TOKEN
    for raw in [{**AUTH, "credential_type": "other"}, {**AUTH, "access_token": "Bearer " + TOKEN}, {**AUTH, "org_id": 0}]:
        with pytest.raises(ValidationError):
            fv.FilevineAccessTokenCredential.model_validate(raw)
    for config in [{"operation": "create_project", "project_name": "Missing identifiers"},
                   {"operation": "create_task", "project_id": "100", "body": "Missing assignee"},
                   {"operation": "update_project", "project_id": "100"},
                   {"operation": "update_contact", "contact_id": "300"},
                   {"operation": "list_projects", "offset": -1},
                   {"operation": "create_task", "project_id": "100", "assignee_id": "300", "body": "Task", "target_date": "tomorrow"}]:
        with pytest.raises(ValidationError):
            fv.FilevineFullConfig.model_validate({"config": config})


@pytest.mark.asyncio
async def test_filevine_connection_evidence_names_projects_and_empty_account(wire, monkeypatch):
    from nodes.core import run_op
    from nodes.core.connection_evidence import collect_evidence

    async def execute_native(**kwargs):
        return await node({"operation": kwargs["operation"], **kwargs["arguments"]}, kwargs["credential_data"]).execute({})

    monkeypatch.setattr(run_op, "run_node_operation", execute_native)
    requests, replies = wire
    replies.append((200, FIXTURES["projects"]))
    result = await collect_evidence(node_type="automation-filevine", user_id="fixture-user", credential_data=AUTH)
    assert result.reachable is True and result.samples[0].label == "Smith matter"
    replies.extend([(200, {"Items": [], "HasMore": False}), (200, FIXTURES["user"])])
    result = await collect_evidence(node_type="automation-filevine", user_id="fixture-user", credential_data=AUTH)
    assert result.reachable is True and result.account_label == "fixture-api-user"
    assert len(requests) == 3


@pytest.mark.asyncio
async def test_filevine_identity_refuses_an_empty_success(wire):
    wire[1].append((200, {}))
    with pytest.raises(ValueError, match="no account identity"):
        await node({"operation": "get_current_user"}).execute({})


EVENTS = json.loads((Path(__file__).parent / "fixtures/filevine/events.json").read_text())
TRIGGERS = list(fv.TRIGGER_EVENTS)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", TRIGGERS)
async def test_filevine_trigger_register_deliver_and_delete(wire, operation):
    requests, replies = wire
    kind, action, _ = fv.TRIGGER_EVENTS[operation]
    config = {"operation": operation, "event_id": "selected-provider-event"}
    # IDs are returned by the event catalogue, not derived from labels.
    replies.append((200, [{"Id": "selected-provider-event", "ObjectType": kind, "EventType": action, "Name": "Available event"},
                          {"Id": "unrelated", "ObjectType": "Document", "EventType": "Deleted"}]))
    options = await fv.FilevineNode.load_field_options(operation, AUTH)
    assert options == {"options": [{"value": "selected-provider-event", "label": "Available event"}]}
    replies.append((200, {"Id": "c75417d8-82ee-4d25-b4c4-ff412f153376"}))
    extra = await fv.FilevineNode._register_external_webhook(
        webhook_url="https://workflow.hooks.example.test/webhook", credential=AUTH, config=config, node_id="filevine-test")
    assert requests[0].url.path == "/fv-app/v2/webhooks/Events"
    assert requests[1].method == "POST" and requests[1].url.path == "/fv-app/v2/webhooks/subscription"
    body = json.loads(requests[1].content)
    assert body["EventIds"] == ["selected-provider-event"] and body["Endpoint"] == "https://workflow.hooks.example.test/webhook"
    assert requests[1].headers["x-fv-orgid"] == "100"
    for event_name, example in EVENTS.items():
        payload = example["body"]
        matched = event_name == f"{kind}.{action}"
        assert fv.FilevineNode.filter_trigger_payload(payload, config) is matched
        if matched:
            output = fv.FilevineNode.resolve_trigger_payload({**payload, "_webhook": {"headers": {"authorization": "secret"}}}, config)
            assert "_webhook" not in output["data"]
            event = fv.FilevineNode.resolve_agent_event(output)
            assert f"Filevine {kind} {action}" in event["text"]
            assert str(payload["OrgId"]) in event["conversation_key"]
            assert str(payload["UserId"]) in event["text"]
            if kind == "Contact":
                assert f"get_contact contact_id={payload['ObjectId']['PersonId']}" in event["text"]
            if kind == "Note":
                assert f"get_note note_id={payload['ObjectId']['NoteId']}" in event["text"]
            if action == "Assigned":
                assert str(payload["ObjectId"]["AssigneeId"]) in event["text"]
            if action == "PhaseChanged":
                assert str(payload["ObjectId"]["PhaseId"]) in event["text"]
    replies.append((200, True))
    await fv.FilevineNode._unregister_external_webhook(credential=AUTH, config={**config, **extra}, node_id="filevine-test")
    assert requests[-1].method == "DELETE"
    assert requests[-1].url.path == "/fv-app/v2/webhooks/subscription/" + extra["external_webhook_id"]
    assert not replies


@pytest.mark.asyncio
async def test_filevine_registration_failure_and_no_delivery(wire):
    wire[1].append((403, {"error": TOKEN}))
    with pytest.raises(ValueError, match="Filevine webhook HTTP 403") as exc:
        await fv.FilevineNode._register_external_webhook(webhook_url="https://workflow.hooks.example.test", credential=AUTH,
            config={"operation": "on_note_created", "event_id": "selected"}, node_id="test")
    assert TOKEN not in str(exc.value)
    wire[1].append((200, {}))
    with pytest.raises(ValueError, match="subscription ID"):
        await fv.FilevineNode._register_external_webhook(webhook_url="https://workflow.hooks.example.test", credential=AUTH,
            config={"operation": "on_note_created", "event_id": "selected"}, node_id="test")
    assert (await node({"operation": "on_note_created", "event_id": "selected"}).execute({"other-node": "private"}))["data"] == {}
    assert fv.FilevineNode.resolve_agent_event({"status": "success", "data": {}}) is None


@pytest.fixture
def signing_key(monkeypatch):
    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    jwk.update({"kid": "documented-identity-key", "alg": "RS512", "use": "sig"})
    client = fv._webhook_keys()
    monkeypatch.setattr(client, "fetch_data", lambda: {"keys": [jwk]})
    return key


def test_filevine_identity_signature_real_rsa(signing_key):
    import jwt
    import time
    claims = {"iss": "https://identity.filevine.com", "aud": "filevine-v2-webhooks", "exp": int(time.time()) + 300,
              "scope": ["filevine-v2-webhooks-access"]}
    def header(overrides=None, *, algorithm="RS512", key=signing_key):
        token = jwt.encode({**claims, **(overrides or {})}, key, algorithm=algorithm,
                           headers={"kid": "documented-identity-key"})
        return {"Authorization": "Bearer " + token}
    body = json.dumps(EVENTS["Note.Created"]["body"]).encode()
    assert fv.FilevineNode.verify_webhook_signature(body, header(), {})
    assert fv.FilevineNode.verify_webhook_signature(body, header({"scope": "filevine-v2-webhooks-access"}), {})
    for invalid in [{"iss": "https://attacker.example"}, {"aud": "other"}, {"scope": []}, {"scope": "prefix-filevine-v2-webhooks-access"},
                    {"exp": int(time.time()) - 1}, {"exp": None}]:
        assert not fv.FilevineNode.verify_webhook_signature(body, header(invalid), {})
    assert not fv.FilevineNode.verify_webhook_signature(body, header(algorithm="HS256", key="attacker-secret-at-least-32-bytes"), {})
    from cryptography.hazmat.primitives.asymmetric import rsa
    assert not fv.FilevineNode.verify_webhook_signature(body, header(key=rsa.generate_private_key(public_exponent=65537, key_size=2048)), {})
    for headers in [{}, {"authorization": "Bearer broken"}, {"Authorization": "Basic token"}]:
        assert not fv.FilevineNode.verify_webhook_signature(body, headers, {})
