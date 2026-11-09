"""Exercise Synap's real factory and HTTP serialization without an account.

Request/response shapes come from the pinned v3 contract; webhook field layouts
come from the provider's Academy interfaces, linked beside the fixtures.
"""
import base64
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import synap_node as native
from nodes.core.registry import NodeFactory

AUTH = {"credential_type": "synap_pat", "api_token": "p:test-secret", "portal_id": "FID001"}
FIXTURES = Path(__file__).parent / "fixtures" / "synap"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    original = httpx.AsyncClient
    def handle(request):
        requests.append(request)
        assert request.url.host == "api.synap.ac"
        assert request.headers["Authorization"] == "Bearer p:test-secret"
        assert request.headers["X-Syn-Portal-Id"] == "FID001"
        assert request.headers["Accept"] == "application/vnd.api+json"
        code, payload = replies.pop(0)
        return httpx.Response(code, json=payload) if code != 204 else httpx.Response(204)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return original(transport=httpx.MockTransport(handle), **kwargs)
    monkeypatch.setattr(native.httpx, "AsyncClient", client)
    return requests, replies


def node(config):
    instance = NodeFactory.create_node(node_id="synap-fixture", node_type="automation-synap", node_data={"config": config, "credentials": AUTH})
    instance.emit = AsyncMock()
    return instance


@pytest.mark.asyncio
async def test_registration_matches_provider_cookbook_and_supports_background_jobs(transport):
    requests, replies = transport
    replies.append((201, {"data": {"id": "FID_USER", "type": "UserRegistration"}}))
    cfg = {"operation": "create_user", "name": "First Last", "email": "f.last@domain.com", "password": "PasswordABC123!", "group_id": "FID_EDU_001"}
    result = await node(cfg).execute({})
    assert result["pending"] is False
    assert requests[0].method == "POST" and requests[0].url.path == "/v3/user-registrations"
    assert json.loads(requests[0].content) == {"data": {"type": "UserRegistration", "attributes": {"name": "First Last", "emailAddress": "f.last@domain.com", "password": "PasswordABC123!", "welcomeEmailDisabled": True}, "relationships": {"userGroups": {"data": [{"type": "UserGroup", "id": "FID_EDU_001"}]}}}}
    replies.append((202, {"data": {"id": "JOB001", "type": "BackgroundJob"}}))
    result = await node(cfg).execute({})
    assert result["pending"] is True and result["data"]["type"] == "BackgroundJob"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,method,path,config,expected", [
    ("update_user", "PATCH", "/users/FID001", {"user_id": "FID001", "email": "first@example.test", "is_disabled": False}, {"data": {"type": "User", "id": "FID001", "attributes": {"emailAddress": "first@example.test", "isDisabled": False}}}),
    ("create_group", "POST", "/user-groups", {"name": "Students", "user_type_id": "FID_STUDENT"}, {"data": {"type": "UserGroup", "attributes": {"name": "Students"}, "relationships": {"userType": {"data": {"type": "UserType", "id": "FID_STUDENT"}}}}}),
    ("update_group", "PATCH", "/user-groups/FID001", {"group_id": "FID001", "name": "Renamed"}, {"data": {"type": "UserGroup", "id": "FID001", "attributes": {"name": "Renamed"}}}),
    ("add_user_to_group", "POST", "/user-groups/FID001/relationships/users", {"group_id": "FID001", "user_id": "FID002"}, {"data": [{"type": "User", "id": "FID002"}]}),
    ("remove_user_from_group", "DELETE", "/user-groups/FID001/relationships/users", {"group_id": "FID001", "user_id": "FID002"}, {"data": [{"type": "User", "id": "FID002"}]}),
    ("invite_user_to_group", "POST", "/user-groups/FID001/relationships/users", {"group_id": "FID001", "email": "invite@example.test", "personal_message": "Welcome"}, {"data": [{"type": "Invite", "attributes": {"email": "invite@example.test", "personalMessage": "Welcome"}}]}),
    ("create_learning_record", "POST", "/learning-records", {"user_id": "FID002", "name": "First aid", "achieved_on": "2026-11-09", "score": 80}, {"data": {"type": "LearningRecord", "attributes": {"name": "First aid", "achievedOn": "2026-11-09", "score": 80, "visibleToStudent": True}, "relationships": {"owner": {"data": {"type": "User", "id": "FID002"}}}}}),
    ("update_learning_record", "PATCH", "/learning-records/FID001", {"record_id": "FID001", "name": "First aid", "visible_to_student": False}, {"data": {"type": "LearningRecord", "id": "FID001", "attributes": {"name": "First aid", "visibleToStudent": False}}}),
    ("delete_learning_record", "DELETE", "/learning-records/FID001", {"record_id": "FID001"}, None),
])
async def test_write_routes_jsonapi_linkage_and_false_values(transport, operation, method, path, config, expected):
    requests, replies = transport
    status = 204 if operation in {"add_user_to_group", "remove_user_from_group", "invite_user_to_group", "delete_learning_record"} else 201 if method == "POST" else 200
    payload = None if status == 204 else {"data": {"id": "FID001", "type": native.ACTIONS[operation].kind}}
    replies.append((status, payload))
    result = await node({"operation": operation, **config}).execute({})
    request = requests[0]
    assert request.method == method and request.url.path == "/v3" + path
    assert (json.loads(request.content) if request.content else None) == expected
    if expected:
        assert request.headers["Content-Type"] == "application/vnd.api+json"
    assert result["http_status"] == status


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,path,config,params", [
    ("list_users", "/users", {"email": "first+test@example.test"}, {"limit": "50", "offset": "0", "filter": "userGroupType,allUsers,emailAddress,first+test@example.test"}),
    ("list_groups", "/user-groups", {"search": "A group"}, {"limit": "50", "offset": "0", "search": "A group"}),
    ("list_exams", "/exam-v-2s", {"search": "Physics"}, {"limit": "50", "offset": "0", "search": "Physics"}),
    ("list_attempts", "/attempts", {"exam_id": "EX001", "user_id": "U001", "is_completed": False}, {"limit": "50", "offset": "0", "filter": "examId,EX001,owner,U001,isCompleted,false"}),
])
async def test_published_openapi_form_query_serialization(transport, operation, path, config, params):
    requests, replies = transport
    replies.append((200, {"data": []}))
    result = await node({"operation": operation, **config}).execute({})
    assert requests[0].url.path == "/v3" + path and dict(requests[0].url.params) == params
    assert result["data"] == [] and result["next_offset"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,path", [("user", "users"), ("group", "user-groups"), ("exam", "exam-v-2s"), ("attempt", "attempts"), ("assignment", "assignments"), ("learning_record", "learning-records")])
async def test_get_resources_and_jsonapi_envelope(transport, kind, path):
    requests, replies = transport
    replies.append((200, {"data": {"id": "FID001", "type": native.ACTIONS["get_" + kind].kind, "attributes": {"name": "Fixture"}}}))
    config = {"operation": "get_" + kind, ("record_id" if kind == "learning_record" else kind + "_id"): "FID001"}
    result = await node(config).execute({})
    assert result["data"]["id"] == "FID001" and requests[0].url.path == "/v3/" + path + "/FID001"


@pytest.mark.asyncio
async def test_connection_evidence_recognisable_groups_and_offset_paging(transport):
    _, replies = transport
    replies.append((200, {"data": [{"type": "UserGroup", "id": "G001", "attributes": {"name": "Physics learners"}}]}))
    assert await native.SynapNode.load_field_options("group_id", AUTH) == {"options": [{"value": "G001", "label": "Physics learners"}], "next_page_token": None}
    replies.append((200, {"data": [{"id": "G001", "type": "UserGroup"}]}))
    result = await node({"operation": "list_groups", "limit": 1, "offset": 2}).execute({})
    assert result["next_offset"] == 3


@pytest.mark.parametrize("credential", [{"api_token": "p:test"}, {"portal_id": "FID001"}, {"api_token": "p:test\nInjected", "portal_id": "FID001"}, {**AUTH, "credential_type": "other"}])
def test_hand_connect_requires_both_fields_and_rejects_header_injection(credential):
    with pytest.raises((ValidationError, ValueError)):
        native.SynapPATCredential.model_validate(credential)
    assert native.SynapPATCredential(api_token="p:test", portal_id="FID001").credential_type == "synap_pat"


@pytest.mark.parametrize("bad", ["../other", "a/b", "a%2Fb", "x?y=1", "x\n"])
def test_bad_ids_before_http(bad):
    with pytest.raises(ValueError):
        native.SynapNode.parse_config({"config": {"operation": "get_user", "user_id": bad}, "credentials": AUTH})


@pytest.mark.asyncio
@pytest.mark.parametrize("code,payload", [(401, {"errors": [{"detail": "p:test-secret rejected"}]}), (200, {"errors": []}), (200, {}), (302, {})])
async def test_errors_never_become_success_or_leak_token(transport, code, payload):
    _, replies = transport
    replies.append((code, payload))
    with pytest.raises(ValueError) as exc:
        await node({"operation": "list_groups"}).execute({})
    assert AUTH["api_token"] not in str(exc.value)


@pytest.mark.asyncio
async def test_webhook_register_authenticate_and_unregister(transport):
    requests, replies = transport
    replies.append((201, {"data": {"type": "WebhookSubscription", "id": "WH001"}}))
    cfg = {"event_type": "user.updated"}
    state = await native.SynapNode._register_external_webhook(webhook_url="https://hooks.hooks.example.test/synap", credential=AUTH, config=cfg, node_id="fixture")
    attrs = json.loads(requests[0].content)["data"]["attributes"]
    assert attrs["eventName"] == "user.updated" and attrs["targetUrl"] == "https://hooks.hooks.example.test/synap"
    assert attrs["basicAuth"] == {"username": "noclick", "password": state["signing_secret"]}
    header = "Basic " + base64.b64encode(("noclick:" + state["signing_secret"]).encode()).decode()
    assert native.SynapNode.verify_webhook_signature(b"{}", {"Authorization": header}, state)
    assert not native.SynapNode.verify_webhook_signature(b"{}", {}, state)
    assert not native.SynapNode.verify_webhook_signature(b"{}", {"authorization": header + "x"}, state)
    assert not native.SynapNode.verify_webhook_signature(b"{}", {"authorization": header}, {})
    replies.append((204, None))
    await native.SynapNode._unregister_external_webhook(credential=AUTH, config=state, node_id="fixture")
    assert requests[-1].method == "DELETE" and requests[-1].url.path == "/v3/webhook-subscriptions/WH001"
    assert native.SynapNode.registration_fingerprint_fields(cfg) != native.SynapNode.registration_fingerprint_fields({"event_type": "user.registered"})


@pytest.mark.asyncio
async def test_pending_subscription_does_not_claim_registration(transport):
    _, replies = transport
    replies.append((202, {"data": {"type": "BackgroundJob", "id": "JOB001"}}))
    with pytest.raises(ValueError, match="did not confirm"):
        await native.SynapNode._register_external_webhook(webhook_url="https://hooks.hooks.example.test/synap", credential=AUTH, config={}, node_id="fixture")


@pytest.mark.asyncio
@pytest.mark.parametrize("event,filename,expected", [("user.registered", "user-registered.json", "user_id=FID_USER"), ("user.updated", "user-updated.json", "user_id=FID_USER"), ("attempt.complete", "attempt-completed.json", "attempt_id=FID_ATTEMPT")])
async def test_documented_webhook_interfaces_become_human_agent_turns(event, filename, expected):
    payload = json.loads((FIXTURES / filename).read_text())
    result = native.SynapNode.resolve_trigger_payload(payload, {"event_type": event})
    turn = native.SynapNode.resolve_agent_event(result)
    assert expected in turn["text"] and "Learner" in turn["title"]
    assert turn["conversation_key"] and turn["title"]
    assert "learner@example.test" in turn["text"]


@pytest.mark.asyncio
async def test_trigger_manual_run_waits_for_an_event():
    result = await node({"operation": "on_event"}).execute({})
    assert result["status"] == "no_event"


@pytest.mark.parametrize("event,filename", [("learningRecord.updated", "learning-record-updated.json"), ("learningRecord.deleted", "learning-record-deleted.json")])
def test_provider_authored_learning_record_examples(event, filename):
    payload = json.loads((FIXTURES / filename).read_text())
    assert native.SynapNode.filter_trigger_payload(payload, {"event_type": event})
    assert not native.SynapNode.filter_trigger_payload(payload, {"event_type": "user.registered"})
    result = native.SynapNode.resolve_trigger_payload({**payload, "_webhook": {"headers": {"authorization": "secret"}}}, {"event_type": event})
    assert "_webhook" not in result["data"]
    turn = native.SynapNode.resolve_agent_event(result)
    assert "Charlotte Blue" in turn["title"] and "record_id=lcfdxBQ13vT" in turn["text"]


@pytest.mark.asyncio
async def test_provider_error_cannot_echo_a_quoted_initial_password(transport):
    _, replies = transport
    password = 'Quoted"Password123'
    replies.append((400, {"errors": [{"detail": f"Invalid password: {password}"}]}))
    with pytest.raises(ValueError) as exc:
        await node({"operation": "create_user", "name": "Learner", "email": "learner@example.test", "password": password}).execute({})
    assert password not in str(exc.value)
    assert json.dumps(password)[1:-1] not in str(exc.value)
    assert "[redacted]" in str(exc.value)
