"""eSputnik requests, strict parsing, projection and staging admission checks."""
import base64
import logging
from contextlib import asynccontextmanager
from copy import deepcopy
from unittest.mock import AsyncMock

import httpx
import pytest
from nodes import esputnik_node as native
from nodes.core.registry import NodeFactory
from nodes.core.run_op import run_node_operation
from nodes.core.credential_connect import validate_for_connect

NT = "automation-esputnik"
USER = "11111111-1111-4111-8111-111111111111"
CID = "22222222-2222-4222-8222-222222222222"
TOKEN = {"credential_type": native.TYPE, "api_key": "synthetic-key", "username": "noclick"}
ACCOUNT = {"userEmail": "fixture@example.test", "organisationName": "Synthetic Organization"}
CONTACT = {"id": 91, "addressBookId": 21, "firstName": "omit-name", "lastName": "omit-family", "externalCustomerId": "omit-external", "channels": [{"type": "email", "value": "omit-email"}, {"type": "sms", "value": "omit-phone"}, {"type": "mobilepush", "value": "omit-token", "device": {"ip": "omit-ip"}}, {"type": "webpush", "value": "omit-private-url"}], "fields": [{"id": 7, "value": "omit-private-value"}], "address": {"street": "omit-address"}, "groups": [{"id": 4, "name": "Synthetic segment", "type": "Static"}], "suppressionStatus": "omit-guessed-consent"}
BROADCAST = {"broadcastId": "bc-7", "title": "Synthetic broadcast", "messageId": "msg-2", "groupId": "group-3", "startDate": "2026-10-06T12:00:00Z", "batchSize": 20, "batchIntervalUnit": "MINUTE", "html": "omit-content", "recordingUrl": "omit-private-url"}
FIELDS = {"additionalFieldsLists": [{"name": "Synthetic fields", "personalisationKey": "fixture", "additionalFields": [{"id": 7, "name": "Options", "fieldKey": "choice", "description": {"type": "checkboxlist", "required": False, "readonly": True, "allowedValues": {"possibleValues": ["First", "Second"], "minValue": 0, "maxValue": 2}}, "secret": "omit-extra"}]}]}


def node(operation="get_account_info", raw=TOKEN, **args):
    return NodeFactory.create_node(node_id="esputnik-fixture", node_type=NT, node_data={"config": {"operation": operation, **args}, "credentials": deepcopy(raw)}, sio=None, sid=None, user_id=USER)


@pytest.fixture(autouse=True)
def admission(monkeypatch):
    monkeypatch.setattr("utils.credential_approval.admit_node", AsyncMock(return_value=None))


@pytest.fixture
def transport(monkeypatch):
    calls, responses = [], []

    async def receive(request):
        assert request.url.host == "esputnik.com" and request.url.scheme == "https"
        assert request.method == "GET" and request.content == b""
        assert not request.url.username and not request.url.password
        assert request.headers["authorization"] == "Basic " + base64.b64encode((TOKEN["username"] + ":" + TOKEN["api_key"]).encode()).decode()
        assert TOKEN["api_key"] not in str(request.url)
        calls.append(request)
        value = responses.pop(0)
        if callable(value):
            value = value(request)
        return value if isinstance(value, httpx.Response) else httpx.Response(200, json=value)

    original_client = httpx.AsyncClient

    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs == {"timeout": 30, "follow_redirects": False, "trust_env": False}
        async with original_client(transport=httpx.MockTransport(receive)) as value:
            yield value

    monkeypatch.setattr(native.httpx, "AsyncClient", client)
    return calls, responses


@pytest.mark.parametrize("value", [True, "20", "20x", "20.5", 20.5, 0, 501, 9007199254740993])
def test_actual_factory_page_refusal_before_transport(transport, value):
    with pytest.raises(ValueError):
        node("list_broadcasts", max_rows=value)
    assert transport[0] == []


@pytest.mark.parametrize("operation,fields", [("list_broadcasts", {"start_index": 0}), ("list_broadcasts", {"start_index": "1"}), ("list_broadcasts", {"start_index": 1000001}), ("get_contact", {"contact_id": True}), ("get_contact", {"contact_id": "91"}), ("get_broadcast", {"broadcast_id": "../other"}), ("get_broadcast", {"broadcast_id": "https://esputnik.com"}), ("search_contacts", {}), ("search_contacts", {"email": "  "}), ("search_contacts", {"email": "fixture@example.test", "include_personal_data": "false"}), ("get_account_info", {"host": "https://evil.example.test"})])
def test_actual_factory_ids_filters_boolean_and_extra_refusal(transport, operation, fields):
    with pytest.raises(ValueError):
        node(operation, **fields)
    assert transport[0] == []


@pytest.mark.asyncio
async def test_raw_foreign_type_before_reconciliation_and_preparsed_execute(transport):
    with pytest.raises(ValueError):
        NodeFactory.create_node(node_id="foreign", node_type=NT, node_data={"config": {"operation": "get_account_info"}, "credentials": {**TOKEN, "credential_type": "foreign"}, "credentialIds": {native.TYPE: CID}}, sio=None, sid=None)
    parsed = node()
    parsed.node_data["credentials"]["credential_type"] = "foreign"
    with pytest.raises(ValueError):
        await parsed.execute({})
    assert transport[0] == []


@pytest.mark.asyncio
async def test_actual_visible_form_connect_literal_and_protected_account_witness(transport):
    transport[1].append(ACCOUNT)
    verdict = await validate_for_connect(credential_type=native.TYPE, credential_data={"api_key": TOKEN["api_key"]}, user_id=USER)
    assert verdict.ok and verdict.credential_data["credential_type"] == native.TYPE
    assert verdict.evidence.reachable is True and native.ESputnikNode.connection_evidence.proves == "account"
    assert verdict.evidence.account_label == ACCOUNT["organisationName"]
    assert transport[0][0].url.path == "/api/v1/account/info" and not transport[0][0].url.query


@pytest.mark.asyncio
async def test_connect_present_foreign_type_is_rejected_before_probe(transport):
    verdict = await validate_for_connect(credential_type=native.TYPE, credential_data={**TOKEN, "credential_type": "foreign"}, user_id=USER)
    assert not verdict.ok and verdict.field_errors and transport[0] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", [{}, {"userEmail": "fixture@example.test"}, {"userEmail": "", "organisationName": "Synthetic"}, {"userEmail": "fixture@example.test", "organisationName": "  "}, [], None])
async def test_missing_account_witness_never_becomes_identity(transport, raw):
    transport[1].append(raw)
    assert (await native.ESputnikNode.validate_credential_access(TOKEN))[0] is None


@pytest.mark.asyncio
async def test_optional_org_id_and_expected_name_are_honest(transport):
    transport[1].extend([ACCOUNT, {**ACCOUNT, "orgId": 4}, ACCOUNT])
    assert "orgId" not in (await node().execute({}))["data"]
    assert (await node().execute({}))["data"]["orgId"] == 4
    with pytest.raises(native.OutcomeUnverified):
        await node(raw={**TOKEN, "expected_organisation_name": "Different organization"}).execute({})


@pytest.mark.asyncio
async def test_actual_dispatch_search_route_filters_paging_and_private_projection(transport):
    transport[1].append(httpx.Response(200, json=[CONTACT], headers={"TotalCount": "3"}))
    result = await run_node_operation(node_type=NT, operation="search_contacts", arguments={"external_customer_id": "fixture-ext", "email": "fixture@example.test", "sms": "12345", "first_name": "Fixture", "last_name": "Only", "start_index": 1, "max_rows": 1}, user_id=USER, credential_data=TOKEN)
    request = transport[0][0]
    assert request.url.path == "/api/v1/contacts"
    assert dict(request.url.params) == {"externalCustomerId": "fixture-ext", "email": "fixture@example.test", "sms": "12345", "firstname": "Fixture", "lastname": "Only", "startindex": "1", "maxrows": "1"}
    assert result["data"]["contacts"] == [{"id": 91, "addressBookId": 21}]
    assert "omit" not in repr(result) and result["data"]["suppression_status"] == "not_provided"
    assert result["data"]["pagination"]["total_count"] == 3 and result["data"]["pagination"]["next_start_index_candidate"] == 2
    assert result["data"]["pagination"]["snapshot_consistent"] is False and len(transport[0]) == 1


@pytest.mark.asyncio
async def test_single_contact_explicit_details_still_omit_push_device_address_and_consent(transport):
    transport[1].append(CONTACT)
    result = await node("get_contact", contact_id=91, include_personal_data=True, include_additional_values=True).execute({})
    card = result["data"]["contact"]
    assert card["firstName"] == CONTACT["firstName"] and card["fields"] == CONTACT["fields"]
    assert card["channels"] == CONTACT["channels"][:2]
    assert "omit-token" not in repr(result) and "omit-address" not in repr(result) and "omit-guessed-consent" not in repr(result)
    assert transport[0][0].url.path == "/api/v1/contact/91"


@pytest.mark.asyncio
async def test_nested_field_schema_preserves_typed_values_without_contact_lookup(transport):
    transport[1].append(FIELDS)
    result = await node("get_additional_fields").execute({})
    description = result["data"]["additionalFieldsLists"][0]["additionalFields"][0]["description"]
    assert description["required"] is False and description["readonly"] is True
    assert description["allowedValues"] == {"possibleValues": ["First", "Second"], "minValue": 0, "maxValue": 2}
    assert "omit" not in repr(result) and transport[0][0].url.path == "/api/v1/additionalfields"


@pytest.mark.asyncio
async def test_broadcast_list_and_single_use_exact_contracts_and_unknown_continuation(transport):
    transport[1].extend([[BROADCAST], BROADCAST, []])
    listed = await node("list_broadcasts", start_index=1, max_rows=1).execute({})
    assert dict(transport[0][0].url.params) == {"startindex": "1", "maxrows": "1"}
    assert listed["data"]["pagination"]["more_results"] is None and listed["data"]["pagination"]["next_start_index_candidate"] == 2
    single = await node("get_broadcast", broadcast_id="bc-7").execute({})
    assert single["data"]["broadcastId"] == "bc-7" and "omit" not in repr(single)
    assert transport[0][1].url.path == "/api/v1/broadcast/bc-7"
    empty = await node("list_broadcasts", start_index=2).execute({})
    assert empty["data"]["broadcasts"] == [] and empty["data"]["pagination"]["total_count"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,args,payload", [("get_contact", {"contact_id": 91}, {"id": 92}), ("get_contact", {"contact_id": 91}, {"id": True}), ("get_broadcast", {"broadcast_id": "bc-7"}, {"broadcastId": "wrong"}), ("list_broadcasts", {}, {"broadcasts": []}), ("list_broadcasts", {}, [None]), ("list_broadcasts", {}, [BROADCAST, BROADCAST]), ("get_additional_fields", {}, {"additionalFields": []}), ("get_additional_fields", {}, {"additionalFieldsLists": [None]}), ("get_additional_fields", {}, {"additionalFieldsLists": [{"additionalFields": [{"id": True}]}]})])
async def test_malformed_shape_or_wrong_exact_id_is_unverified(transport, operation, args, payload):
    transport[1].append(payload)
    with pytest.raises(native.OutcomeUnverified):
        await node(operation, **args).execute({})
    assert len(transport[0]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("count", ["-1", "1x", "1.5", "9007199254740993", "0"])
async def test_invalid_total_count_does_not_fabricate_pagination(transport, count):
    transport[1].append(httpx.Response(200, json=[CONTACT], headers={"TotalCount": count}))
    with pytest.raises(native.OutcomeUnverified):
        await node("search_contacts", email="fixture@example.test").execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("body,content_type", [(b'{"userEmail":"first","userEmail":"second"}', 'application/json'), (b'{"orgId":NaN}', 'application/json'), (b'not-json', 'application/json'), (b'{}', 'text/html')])
async def test_ambiguous_json_and_html_never_become_success(transport, body, content_type):
    transport[1].append(httpx.Response(200, content=body, headers={"Content-Type": content_type}))
    with pytest.raises(native.OutcomeUnverified):
        await node().execute({})


@pytest.mark.asyncio
async def test_page_and_byte_bounds_are_enforced_without_traversal(transport):
    transport[1].append([BROADCAST, {**BROADCAST, "broadcastId": "bc-8"}])
    with pytest.raises(native.OutcomeUnverified):
        await node("list_broadcasts", max_rows=1).execute({})
    transport[1].append(httpx.Response(200, content=b" " * (native.MAX_BODY + 1), headers={"Content-Type": "application/json"}))
    with pytest.raises(native.OutcomeUnverified):
        await node().execute({})
    assert len(transport[0]) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("status,expected", [(401, False), (403, False), (400, None), (404, None), (429, None), (500, None), (302, None)])
async def test_provider_error_bodies_and_redirects_never_leak_or_retry(transport, status, expected):
    transport[1].append(httpx.Response(status, json={"error": TOKEN["api_key"] + "omit-private"}, headers={"Location": "https://evil.example.test"}))
    result = await native.ESputnikNode.validate_credential_access(TOKEN)
    assert result[0] is expected and TOKEN["api_key"] not in repr(result) and "omit" not in repr(result)
    assert len(transport[0]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["pending_approval", "rejected"])
async def test_actual_run_admission_has_zero_provider_io(monkeypatch, transport, status):
    monkeypatch.setattr("utils.credential_approval.admit_node", AsyncMock(return_value={"status": status, "message": "Owner review is required"}))
    result = await node().run({})
    assert result["status"] == status and transport[0] == []


@pytest.mark.asyncio
async def test_request_local_diagnostics_hide_key_search_pii_and_response_bodies(transport, caplog):
    logger = logging.getLogger("httpx")

    def observe(request):
        logger.warning("%s %s %s", request.headers["authorization"], request.url, "omit-private")
        return [CONTACT]

    transport[1].append(observe)
    with caplog.at_level(logging.WARNING):
        await node("search_contacts", email="private-search@example.test").execute({})
        logger.warning("Ordinary unrelated message")
    assert "eSputnik transport activity" in caplog.text and "Ordinary unrelated message" in caplog.text
    assert TOKEN["api_key"] not in caplog.text and "private-search" not in caplog.text and "omit-private" not in caplog.text


def test_basic_username_validator_is_callable_and_rejects_colons():
    assert native.ESputnikAPIKeyCredential(api_key="issued-key", username="custom-user").username == "custom-user"
    with pytest.raises(ValueError):
        native.ESputnikAPIKeyCredential(api_key="issued-key", username="bad:user")
