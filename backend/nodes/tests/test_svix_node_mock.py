"""Svix contract fixtures retain the real public guarded HTTP client.

Only DNS and HTTP transport are synthetic. The native factory/configuration,
cursor binding, parent preflight, output projections and one-shot writes remain real.
"""
import json
from contextlib import contextmanager
from copy import deepcopy
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError
from nodes import svix_node as s
from nodes.core.registry import NodeFactory
from utils import ssrf

CREDS = {"credential_type": s.FAMILY, "region": "us", "api_key": "fixture.svix.key"}
APP, EP, MSG, ATTEMPT = "app_" + "A" * 27, "ep_" + "B" * 27, "msg_" + "C" * 27, "atmpt_" + "D" * 27
APP2, MSG2 = "app_" + "E" * 27, "msg_" + "F" * 27
DATE = "2026-10-06T00:00:00Z"
APPLICATION = {"id": APP, "name": "Owned application", "metadata": {"secret": "private-value"}, "createdAt": DATE, "updatedAt": DATE}
EVENT = {"name": "customer.created", "description": "Owned description", "createdAt": DATE, "updatedAt": DATE,
    "deprecated": False, "archived": False, "schemas": {"private": "hidden"}}
ENDPOINT = {"id": EP, "description": "private-description", "url": "https://private.invalid/?key=hidden", "metadata": {"secret": "hidden"},
    "createdAt": DATE, "updatedAt": DATE, "disabled": False, "channels": ["project:42"], "eventTypes": ["customer.created"],
    "secret": "whsec_hidden", "headers": {"Authorization": "private-header"}}
MESSAGE = {"id": MSG, "eventType": "customer.created", "timestamp": DATE, "payload": {"private": "hidden"}}
ATTEMPT_ROW = {"id": ATTEMPT, "msgId": MSG, "endpointId": EP, "timestamp": DATE, "status": 4, "statusText": "canceled",
    "responseDurationMs": 9007199254740993, "responseStatusCode": 0, "triggerType": 0,
    "response": "private response", "url": "https://private.invalid/?key=hidden", "msg": MESSAGE}


@pytest.fixture
def ensure_native_db_pool():
    yield


def page(rows, done=True, iterator=None):
    return {"data": rows, "done": done, "iterator": iterator}


@contextmanager
def transport(monkeypatch, replies, region="us"):
    calls = []
    def answer(request):
        calls.append(request)
        assert request.url.host == f"api.{region}.svix.com"
        assert request.headers["authorization"] == "Bearer fixture.svix.key"
        assert request.headers["accept"] == "application/json"
        response = replies.pop(0)
        if isinstance(response, Exception):
            raise response
        return response
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["8.8.8.8"]))
    factory = ssrf.guarded_async_client
    monkeypatch.setattr(s, "guarded_async_client", lambda **kwargs: factory(**kwargs, transport=httpx.MockTransport(answer)))
    yield calls


def node(operation, **arguments):
    return NodeFactory.create_node("fixture", "automation-svix",
        {"config": {"operation": operation, **arguments}, "credentials": CREDS})


@pytest.mark.asyncio
async def test_short_page_uses_returned_iterator_without_inventing_offsets(monkeypatch):
    with transport(monkeypatch, [httpx.Response(200, json=page([APPLICATION], False, APP)), httpx.Response(200, json=page([]))]) as calls:
        first = await node("list_applications").execute({})
        assert first["done"] is False and first["snapshot_verified"] is False
        second = await node("list_applications", next_page_token=first["next_page_token"]).execute({})
        assert second["items"] == [] and second["next_page_token"] is None
        assert dict(calls[1].url.params) == {"limit": "25", "iterator": APP}


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["region", "key", "size", "resource"])
async def test_continuation_is_bound_before_next_list_http(monkeypatch, change):
    session = s.SvixSession(s.SvixAPIKeyCredential.model_validate(CREDS))
    scope = session.scope("applications", "/app", 25, [])
    token = s.base64.urlsafe_b64encode(json.dumps({"scope": scope, "iterator": APP}).encode()).decode().rstrip("=")
    current = node("list_event_types" if change == "resource" else "list_applications", next_page_token=token,
        **({"page_size": 26} if change == "size" else {}))
    if change == "region":
        current.config.credentials.region = "eu"
    if change == "key":
        current.config.credentials.api_key = "different.fixture.key"
    with transport(monkeypatch, []) as calls:
        assert (await current.execute({}))["status"] == "error" and not calls


@pytest.mark.asyncio
@pytest.mark.parametrize("malformed", [{"data": [], "done": True}, {"data": [], "done": "true", "iterator": None},
    page([], False, APP), page([APPLICATION, APPLICATION]), page([APPLICATION], False, "bad")])
async def test_truncated_pages_do_not_become_exhausted_picker_success(monkeypatch, malformed):
    with transport(monkeypatch, [httpx.Response(200, json=malformed)]) as calls:
        result = await node("list_applications").execute({})
        assert result["status"] == "error" and result["status_code"] == 200 and len(calls) == 1


@pytest.mark.asyncio
async def test_message_filters_repeat_and_attempts_preserve_canceled_without_content(monkeypatch):
    with transport(monkeypatch, [httpx.Response(200, json=APPLICATION), httpx.Response(200, json=page([MESSAGE])),
        httpx.Response(200, json=APPLICATION), httpx.Response(200, json=MESSAGE), httpx.Response(200, json=page([ATTEMPT_ROW]))]) as calls:
        messages = await node("list_messages", application_id=APP, event_types=["customer.created", "customer.updated"]).execute({})
        assert calls[1].url.params.get_list("event_types") == ["customer.created", "customer.updated"]
        assert calls[1].url.params["with_content"] == "false" and "payload" not in messages["items"][0]
        result = await node("list_message_attempts", application_id=APP, message_id=MSG, delivery_status=4).execute({})
        assert dict(calls[-1].url.params) == {"limit": "25", "with_content": "false", "expanded_statuses": "true", "status": "4"}
        assert result["items"][0]["statusText"] == "canceled" and result["items"][0]["responseDurationMs"] == "9007199254740993"
        assert all(word not in str(result) for word in ("private response", "private.invalid", "payload", "hidden"))


@pytest.mark.asyncio
async def test_endpoint_projection_never_returns_or_calls_destination(monkeypatch):
    with transport(monkeypatch, [httpx.Response(200, json=APPLICATION), httpx.Response(200, json=ENDPOINT)]) as calls:
        result = await node("get_endpoint", application_id=APP, endpoint_id=EP).execute({})
        assert result["record"]["disabled"] is False and result["record"]["eventTypes"] == ["customer.created"]
        assert all(key not in result["record"] for key in ("url", "secret", "headers", "metadata", "description"))
        assert len(calls) == 2 and all(request.method == "GET" for request in calls)


@pytest.mark.asyncio
async def test_actual_attempt_parent_mismatch_and_endpoint_status_malformed_fail_closed(monkeypatch):
    with transport(monkeypatch, [httpx.Response(200, json=APPLICATION), httpx.Response(200, json=MESSAGE),
        httpx.Response(200, json={**ATTEMPT_ROW, "msgId": MSG2}), httpx.Response(200, json=APPLICATION),
        httpx.Response(200, json={**ENDPOINT, "disabled": "false"})]) as calls:
        assert (await node("get_attempt", application_id=APP, message_id=MSG, attempt_id=ATTEMPT).execute({}))["status"] == "error"
        assert (await node("get_endpoint", application_id=APP, endpoint_id=EP).execute({}))["status"] == "error"
        assert len(calls) == 5


@pytest.mark.asyncio
async def test_picker_missing_parent_precedes_client_and_foreign_parent_precedes_child(monkeypatch):
    with transport(monkeypatch, []) as calls:
        with pytest.raises(ValueError):
            await s.SvixNode.load_field_options("attempt_id", CREDS, {"message_id": MSG})
        assert not calls
    with transport(monkeypatch, [httpx.Response(200, json={**APPLICATION, "id": APP2})]) as calls:
        with pytest.raises(s.SvixError):
            await s.SvixNode.load_field_options("endpoint_id", CREDS, {"application_id": APP})
        assert len(calls) == 1 and calls[0].url.path == "/api/v1/app/" + APP


@pytest.mark.asyncio
async def test_attempt_picker_preflights_both_parents_and_filters_only_labels(monkeypatch):
    with transport(monkeypatch, [httpx.Response(200, json=APPLICATION), httpx.Response(200, json=MESSAGE),
        httpx.Response(200, json=page([ATTEMPT_ROW]))]) as calls:
        result = await s.SvixNode.load_field_options("attempt_id", CREDS, {"application_id": APP, "message_id": MSG}, search="canceled")
        assert result["options"] == [{"value": ATTEMPT, "label": "canceled · " + ATTEMPT}]
        assert calls[-1].url.path == f"/api/v1/app/{APP}/attempt/msg/{MSG}"


@pytest.mark.asyncio
async def test_application_create_and_patch_are_exact_acknowledgments_not_readback(monkeypatch):
    with transport(monkeypatch, [httpx.Response(201, json={**APPLICATION, "uid": "owned-fixture"}),
        httpx.Response(200, json=APPLICATION), httpx.Response(200, json={**APPLICATION, "name": "Renamed"})]) as calls:
        created = await node("create_application", name="Owned application", uid="owned-fixture", confirm_metadata_change=True).execute({})
        updated = await node("update_application", application_id=APP, name="Renamed", confirm_metadata_change=True).execute({})
        assert json.loads(calls[0].content) == {"name": "Owned application", "uid": "owned-fixture"}
        assert calls[-1].method == "PATCH" and json.loads(calls[-1].content) == {"name": "Renamed"}
        assert created["provider_acknowledged"] and updated["readback_verified"] is False and updated["preflight_atomic"] is False


@pytest.mark.asyncio
async def test_empty_application_delete_is_bounded_and_nonempty_refuses(monkeypatch):
    with transport(monkeypatch, [httpx.Response(200, json=APPLICATION), httpx.Response(200, json=page([])),
        httpx.Response(200, json=page([])), httpx.Response(204)]) as calls:
        result = await node("delete_application", application_id=APP, expected_name="Owned application", confirm_metadata_change=True).execute({})
        assert result["deleted_application_id"] == APP and result["readback_verified"] is False
        assert [r.method for r in calls] == ["GET", "GET", "GET", "DELETE"]
        assert calls[2].url.params["with_content"] == "false" and calls[1].url.params["limit"] == "1"
    with transport(monkeypatch, [httpx.Response(200, json=APPLICATION), httpx.Response(200, json=page([ENDPOINT]))]) as calls:
        result = await node("delete_application", application_id=APP, expected_name="Owned application", confirm_metadata_change=True).execute({})
        assert result["status"] == "error" and result["uncertain_outcome"] is False and all(r.method == "GET" for r in calls)


@pytest.mark.asyncio
async def test_event_create_description_update_and_archive_do_not_send(monkeypatch):
    with transport(monkeypatch, [httpx.Response(201, json=EVENT), httpx.Response(200, json=EVENT),
        httpx.Response(200, json={**EVENT, "description": "Updated"}), httpx.Response(200, json=EVENT), httpx.Response(204)]) as calls:
        created = await node("create_event_type", name=EVENT["name"], description=EVENT["description"],
            confirm_metadata_change=True, acknowledge_possible_unarchive=True).execute({})
        updated = await node("update_event_type", event_type_name=EVENT["name"], description="Updated", confirm_metadata_change=True).execute({})
        archived = await node("archive_event_type", event_type_name=EVENT["name"], confirm_metadata_change=True, acknowledge_send_restriction=True).execute({})
        assert created["status"] == updated["status"] == archived["status"] == "success"
        assert archived["archived_event_type"] == EVENT["name"] and "deleted" not in str(archived)
        assert all(r.url.path.startswith("/api/v1/event-type") for r in calls)
        assert all("schemas" not in json.loads(r.content) for r in calls if r.content)


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", [httpx.Response(201, json={"error": "secret", **APPLICATION}),
    httpx.Response(201, json={"executed": False, **APPLICATION}), httpx.Response(201, json={**APPLICATION, "id": "bad"}),
    httpx.Response(201, content=b'{"id":"app_AAAAAAAAAAAAAAAAAAAAAAAAAAA","id":"duplicate"}', headers={"content-type": "application/json"}),
    httpx.Response(201, content=b'{"unknown":1e309}', headers={"content-type": "application/json"}),
    httpx.Response(201, content=b'{"unknown":NaN}', headers={"content-type": "application/json"}),
    httpx.Response(201, content=b'{"unknown":Infinity}', headers={"content-type": "application/json"}),
    httpx.Response(201, content=b'x' * (s.MAX_BYTES + 1), headers={"content-type": "application/json"})])
async def test_malformed_success_is_uncertain_preserves_status_and_never_replays(monkeypatch, reply):
    with transport(monkeypatch, [reply]) as calls:
        result = await node("create_application", name="Owned application", confirm_metadata_change=True).execute({})
        assert result["status"] == "error" and result["status_code"] == 201 and result["uncertain_outcome"] is True
        assert len(calls) == 1 and "secret" not in result["error"]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [httpx.ReadTimeout("private-token-and-url"), httpx.Response(429, json={"detail": "private"}),
    httpx.Response(500, json={"detail": "private"}), httpx.Response(403, json={"detail": "private"})])
async def test_write_transport_error_is_sanitized_without_automatic_retries(monkeypatch, failure):
    with transport(monkeypatch, [failure]) as calls:
        result = await node("create_application", name="Owned application", confirm_metadata_change=True).execute({})
        assert result["status"] == "error" and len(calls) == 1 and "private" not in str(result)
        assert result["uncertain_outcome"] is (not isinstance(failure, httpx.Response) or failure.status_code in (429, 500))


@pytest.mark.asyncio
@pytest.mark.parametrize("region", ["us", "eu", "ca", "au", "in"])
async def test_only_documented_regional_origin_and_truthful_reachability(monkeypatch, region):
    with transport(monkeypatch, [httpx.Response(200, json=page([]))], region) as calls:
        verdict = await s.SvixNode.validate_credential_access({**CREDS, "region": region})
        assert verdict == {"valid": True, "name": None} and calls[0].url.path == "/api/v1/app"
        assert s.SvixNode.connection_evidence.proves == "reachability" and s.SvixNode.connection_evidence.identity_operation is None


@pytest.mark.parametrize("key", ["bad\nkey", "bad key", "é", "bad\x7fkey"])
def test_header_invalid_keys_hide_input_and_never_construct_client(key):
    with pytest.raises(ValidationError) as error:
        s.SvixAPIKeyCredential.model_validate({**CREDS, "api_key": key})
    assert key not in str(error.value)
    assert CREDS["api_key"] not in repr(s.SvixAPIKeyCredential.model_validate(CREDS))
    with pytest.raises(ValidationError) as outer:
        s.SvixNodeConfig.model_validate({"config": {"operation": "list_applications"}, "credentials": {**CREDS, "api_key": key}})
    assert key not in str(outer.value)


@pytest.mark.asyncio
async def test_finite_unknown_metadata_is_omitted_and_known_key_echo_is_redacted(monkeypatch):
    row = {**APPLICATION, "name": "Owned " + CREDS["api_key"], "unknown": {"nested": 1.25}, "secret": "private-value"}
    with transport(monkeypatch, [httpx.Response(200, json=page([row]))]) as calls:
        result = await node("list_applications").execute({})
        assert result["status"] == "success" and result["items"][0]["name"] == "Owned [redacted]"
        assert "private-value" not in str(result) and "unknown" not in str(result) and len(calls) == 1


@pytest.mark.parametrize("operation,arguments", [("send_message", {}), ("recover_endpoint", {}),
    ("get_endpoint_secret", {}), ("create_application", {"name": "Owned", "confirm_metadata_change": 1}),
    ("get_event_type", {"event_type_name": ".."}), ("list_applications", {"page_size": True}),
    ("create_event_type", {"name": "test.event", "description": "", "confirm_metadata_change": True, "acknowledge_possible_unarchive": 1})])
def test_closed_configs_reject_unsupported_effects_and_coerced_confirmations(operation, arguments):
    with pytest.raises((ValidationError, ValueError)):
        node(operation, **arguments)
