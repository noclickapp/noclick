"""Native Fountain factory, consent, parent, transport and authority regressions.

HTTP and storage are synthetic boundaries; dispatcher/model/collector and native
grant checks are real. These fixtures do not prove provider or SQL ACL behavior.
"""
import json
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
import httpx
import pytest
from nodes import fountain_api as api
from nodes.fountain_node import FountainNode, _saved_lease
from nodes.core.registry import NodeFactory, NODE_REGISTRY
from nodes.core.run_op import run_node_operation
from nodes.core.connection_evidence import collect_evidence
from nodes.core.credential_connect import shape_credential, validate_for_connect

USER = "00000000-0000-4000-8000-000000000001"
CID = "00000000-0000-4000-8000-000000000002"
OPENING = "00000000-0000-4000-8000-000000000003"
APPLICANT = "00000000-0000-4000-8000-000000000004"
STAGE = "00000000-0000-4000-8000-000000000005"
OTHER = "00000000-0000-4000-8000-000000000006"
CREDENTIAL = {"credential_type": "fountain_private_hire", "tenant": "main", "api_key": "fixture-private-key"}
OPENING_ROW = {"id": OPENING, "title": "Fixture opening", "active": True}
APPLICANT_ROW = {"id": APPLICANT, "name": "Owned fixture", "email": "fixture@example.test", "funnel": {"id": OPENING, "title": "Fixture opening"}, "stage": {"id": STAGE, "title": "Start", "type": "custom"}}
STAGE_ROW = {"id": STAGE, "title": "Start", "type": "custom", "parent_id": None}


@pytest.fixture
def ensure_native_db_pool():
    yield  # Never initialize DB; the repository storage boundary is controlled.


@pytest.fixture
def transport(monkeypatch):
    calls, custom = [], {}
    def handle(request):
        calls.append(request)
        if custom.get("handler"):
            return custom["handler"](request)
        if request.method == "DELETE":
            return httpx.Response(204)
        path = request.url.path
        if path.endswith("/funnels"):
            payload = {"funnels": [OPENING_ROW], "pagination": {"current": 1, "next": None, "last": 1}}
        elif path.endswith("/stages"):
            payload = {"stages": [STAGE_ROW]}
        elif "/stages/" in path:
            payload = STAGE_ROW
        elif "/funnels/" in path:
            payload = OPENING_ROW
        elif path.endswith("/applicants") and request.method == "GET":
            payload = {"applicants": [APPLICANT_ROW], "pagination": {"next_cursor": None}}
        else:
            payload = APPLICANT_ROW
        return httpx.Response(201 if request.method == "POST" else 200, json=payload)
    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handle), **kwargs)
    monkeypatch.setattr(api, "guarded_async_client", client)
    return calls, custom


async def run(operation, arguments=None):
    return await run_node_operation(node_type="automation-fountain", operation=operation,
                                   arguments=arguments or {}, user_id=USER, credential_data=CREDENTIAL)


def test_actual_registration_schema_manual_tag_and_saved_canvas_shape():
    assert NODE_REGISTRY["automation-fountain"] is FountainNode
    schema = FountainNode.get_config_schema()
    assert len(schema["properties"]["config"]["discriminator"]["mapping"]) == 9
    assert schema["$defs"]["ApplicantCreate"]["required"] == ["name", "email", "phone_number"]
    assert schema["$defs"]["FountainPrivateHireCredential"]["properties"]["api_key"]["ui:widget"] == "password"
    shaped, errors, resolved = shape_credential("fountain_private_hire", {"api_key": CREDENTIAL["api_key"]})
    assert not errors and resolved[0] == "automation-fountain"
    assert shaped["credential_type"] == "fountain_private_hire"
    node = NodeFactory.create_node("fixture", "automation-fountain", {"config": {"operation": "list_openings", "label": "Saved canvas", "_settings": {"retryOnFail": "false"}}, "credentials": CREDENTIAL}, user_id=USER)
    assert isinstance(node.config.config.page, int)


@pytest.mark.asyncio
async def test_actual_connect_collector_and_create_only_refusal(transport, monkeypatch):
    monkeypatch.setattr("nodes.core.credential_connect._collect_evidence", collect_evidence)
    verdict = await validate_for_connect(credential_type="fountain_private_hire", credential_data=CREDENTIAL, user_id=USER)
    assert verdict.evidence.reachable is True
    assert FountainNode.connection_evidence.proves == "reachability"
    assert verdict.evidence.samples[0].label == "Fixture opening"
    transport[1]["handler"] = lambda _: httpx.Response(403, json={"secret": CREDENTIAL["api_key"]})
    evidence = await collect_evidence(node_type="automation-fountain", credential_data=CREDENTIAL, user_id=USER)
    assert evidence.reachable is False and CREDENTIAL["api_key"] not in str(evidence)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,arguments", [
    ("list_openings", {}), ("get_opening", {"opening_id": OPENING}),
    ("list_stages", {"opening_id": OPENING}), ("get_stage", {"opening_id": OPENING, "stage_id": STAGE}),
    ("list_applicants", {"opening_id": OPENING}), ("get_applicant", {"opening_id": OPENING, "applicant_id": APPLICANT}),
    ("create_applicant", {"opening_id": OPENING, "body": {"name": "Fixture", "email": "fixture@example.test", "phone_number": "+15550000000"}}),
    ("update_applicant", {"opening_id": OPENING, "applicant_id": APPLICANT, "body": {"phone_number": None}}),
    ("delete_applicant", {"opening_id": OPENING, "applicant_id": APPLICANT}),
])
async def test_nine_actual_dispatch_operations(transport, operation, arguments):
    output = await run(operation, arguments)
    assert "error" not in output
    assert all(request.headers["X-ACCESS-TOKEN"] == CREDENTIAL["api_key"] for request in transport[0])
    assert all("Authorization" not in request.headers for request in transport[0])
    if operation == "create_applicant":
        body = json.loads(transport[0][-1].content)
        assert body["funnel_id"] == OPENING and body["check_if_applicant_is_duplicate"] is True
        assert all(body[field] is False for field in api.CONSENT_FIELDS)
        assert "can_receive_sms" not in body and "secure_data" not in body
        assert output["applied"] is None and output["readback_required"] is True
    if operation == "update_applicant":
        assert json.loads(transport[0][-1].content) == {"phone_number": None}
    if operation == "delete_applicant":
        assert output["deletion_verified"] is None and transport[0][-1].content == b""


@pytest.mark.asyncio
async def test_regional_host_and_no_subaccount_expansion(transport):
    await run_node_operation(node_type="automation-fountain", operation="list_applicants", arguments={"opening_id": OPENING}, user_id=USER, credential_data={**CREDENTIAL, "tenant": "us-2"})
    assert transport[0][-1].url.host == "us-2.fountain.com" and transport[0][-1].url.path == "/api/v2/applicants"
    assert transport[0][-1].url.params["include_subaccounts"] == "false"


@pytest.mark.asyncio
async def test_wrong_parent_prevents_write_and_sensitive_projection(transport):
    def reply(request):
        return httpx.Response(200, json=OPENING_ROW if "/funnels/" in request.url.path else {**APPLICANT_ROW, "funnel": {"id": OTHER}})
    transport[1]["handler"] = reply
    with pytest.raises(ValueError, match="belongs to a different opening"):
        await run("update_applicant", {"opening_id": OPENING, "applicant_id": APPLICANT, "body": {"name": "New"}})
    assert all(call.method == "GET" for call in transport[0])
    projection = api.project({**APPLICANT_ROW, "secure_data": {"ssn": "private"}, "data": {"secret": "x"}, "video_urls": ["https://private.test"], "i9_status": {"status": "complete"}}, "applicant", opening_id=OPENING)
    assert not {"secure_data", "data", "video_urls", "i9_status", "key"} & projection.keys()


@pytest.mark.parametrize("change", [{"body": {"name": "x", "consent_sms_transactional": True}}, {"body": {"secure_data": {}}}, {"opening_id": None}])
def test_model_blocks_consent_secure_fields_and_missing_opening(change):
    raw = {"operation": "create_applicant", "opening_id": OPENING, "body": {"name": "x", "email": "a@example.test", "phone_number": "+15550000000"}, **change}
    with pytest.raises(ValueError):
        FountainNode.parse_config({"config": raw, "credentials": CREDENTIAL})


@pytest.mark.parametrize("credential", [{**CREDENTIAL, "credential_type": "fountain_trusted_party"}, {**CREDENTIAL, "tenant": "evil.example"}, {**CREDENTIAL, "api_key": "secret\r\nheader"}])
def test_foreign_tags_hosts_and_credentials_are_safely_rejected(credential):
    with pytest.raises(ValueError) as error:
        FountainNode.parse_config({"config": {"operation": "list_openings"}, "credentials": credential})
    assert credential["api_key"] not in str(error.value)


def test_pagination_unknown_cursor_and_bad_boundaries():
    result = api.page({"funnels": []}, "funnels", "opening")
    assert result["pagination"] is None and result["complete"] is None
    result = api.page({"applicants": [APPLICANT_ROW], "pagination": {"current": 1, "next": 2, "next_cursor": "opaque=="}}, "applicants", "applicant", opening_id=OPENING)
    assert result["next_cursor"] == "opaque==" and result["next_page"] == 2 and result["complete"] is False
    with pytest.raises(ValueError):
        api.page({"funnels": [OPENING_ROW], "pagination": {"current": 2, "next": 1}}, "funnels", "opening")
    with pytest.raises(ValueError):
        api.page({"funnels": [OPENING_ROW, OPENING_ROW]}, "funnels", "opening")
    with pytest.raises(ValueError):
        api.page({"funnels": [], "pagination": {"current": 1, "last": 2, "next": None}}, "funnels", "opening")
    assert api.retry_after("7") == 7
    future = datetime.now(timezone.utc) + timedelta(seconds=90)
    assert 89 <= api.retry_after(future.strftime("%a, %d %b %Y %H:%M:%S GMT")) <= 90


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [httpx.Response(200, text="<html>", headers={"Content-Type": "text/html"}), httpx.Response(200, content=b'{"funnels":[],"funnels":[]}', headers={"Content-Type": "application/json"}), httpx.Response(200, json={"error": CREDENTIAL["api_key"]}), httpx.Response(429, headers={"Retry-After": "10"}, json={"secret": CREDENTIAL["api_key"]})])
async def test_media_error_and_quota_never_become_success(transport, response):
    transport[1]["handler"] = lambda _: response
    with pytest.raises(ValueError) as error:
        await run("list_openings")
    assert CREDENTIAL["api_key"] not in str(error.value)
    assert len(transport[0]) == 1


@pytest.fixture
def saved(monkeypatch):
    from utils import credential_loader, credentials
    box = {"data": deepcopy(CREDENTIAL)}
    async def load(*_args, **_kwargs):
        return deepcopy(box["data"])
    monkeypatch.setattr(credential_loader, "load_credential", load)
    monkeypatch.setattr(credentials, "resolve_credential_with_owner_fallback", load)
    return box


@pytest.mark.asyncio
async def test_saved_grant_or_access_change_withholds_output(saved):
    lease = await _saved_lease(CREDENTIAL, pool=object(), user_id=USER, credential_id=CID)
    saved["data"]["tenant"] = "us-2"
    with pytest.raises(ValueError, match="authority changed"):
        await lease.recheck()
    saved["data"] = None
    with pytest.raises(ValueError, match="authority changed"):
        await lease.recheck()
    with pytest.raises(ValueError, match="access denied"):
        await _saved_lease(CREDENTIAL, pool=object(), user_id=USER, credential_id=CID)


@pytest.mark.asyncio
async def test_picker_current_parent_and_post_http_access_race(saved, transport):
    credential = await FountainNode.freshen_credential({**CREDENTIAL, "token_version": 7}, pool=object(), user_id=USER, credential_id=CID)
    result = await FountainNode.load_field_options("stage_id", credential, {"opening_id": OPENING})
    assert result["options"] == [{"value": STAGE, "label": "Start"}]
    with pytest.raises(ValueError):
        await FountainNode.load_field_options("stage_id", credential, {})
    count = len(transport[0])
    def raced(_):
        saved["data"] = None
        return httpx.Response(200, json={"funnels": [OPENING_ROW]})
    transport[1]["handler"] = raced
    with pytest.raises(ValueError, match="authority changed"):
        await FountainNode.load_field_options("opening_id", credential)
    assert len(transport[0]) == count + 1


@pytest.mark.asyncio
async def test_actual_socket_picker_native_parent(monkeypatch, saved, transport):
    from wss.handlers import workflow_handler
    from wss.receiver.client_events import WorkflowNodeLoadOptionsRequest
    from utils import credential_loader
    responses = []
    async def capture(_sio, _sid, event, **_kwargs):
        responses.append(event.model_dump())
    monkeypatch.setattr(workflow_handler, "send_event", capture)
    monkeypatch.setattr(credential_loader, "load_credential", AsyncMock(return_value={**CREDENTIAL, "token_version": 7}))
    @asynccontextmanager
    async def acquire():
        yield SimpleNamespace(fetchrow=AsyncMock(return_value={"credential": b"fixture"}))
    pool = SimpleNamespace(acquire=acquire)
    monkeypatch.setattr(workflow_handler, "get_user_org_context", AsyncMock(return_value=None))
    monkeypatch.setattr(workflow_handler, "get_encryption", lambda: SimpleNamespace(
        decrypt_credential=lambda _: deepcopy(CREDENTIAL)))
    handler = workflow_handler.WorkflowHandler.__new__(workflow_handler.WorkflowHandler)
    handler.sio = SimpleNamespace(get_session=AsyncMock(return_value={"user_id": USER}))
    handler.get_pool = AsyncMock(return_value=pool)
    request = WorkflowNodeLoadOptionsRequest(request_id="fixture", node_type="automation-fountain", credential_id=CID,
                                           field_name="stage_id", context={"opening_id": OPENING})
    await handler.load_node_options("fixture-sid", request)
    assert responses[-1]["data"]["success"] is True
    assert responses[-1]["data"]["options"] == [{"value": STAGE, "label": "Start", "metadata": None}]


@pytest.mark.asyncio
async def test_post_connect_checks_private_hire_reachability(transport):
    result = await FountainNode.validate_credential_access(CREDENTIAL)
    assert result == {"valid": True, "reachable": True, "proves": "reachability"}
    transport[1]["handler"] = lambda _: httpx.Response(403)
    with pytest.raises(ValueError):
        await FountainNode.validate_credential_access(CREDENTIAL)


@pytest.mark.asyncio
async def test_escaped_json_credential_echo_withheld(transport):
    secret = 'fixture"private-key'
    transport[1]["handler"] = lambda _: httpx.Response(200, json={"funnels": [], "extra": secret})
    with pytest.raises(ValueError, match="credential material") as error:
        await run_node_operation(node_type="automation-fountain", operation="list_openings", arguments={}, user_id=USER,
                                 credential_data={**CREDENTIAL, "api_key": secret})
    assert secret not in str(error.value)
