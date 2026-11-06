"""Offline wire and parser checks against RingCentral's published HTTP examples.

Source: https://netstorage.ringcentral.com/dpw/api-reference/specs/public/office/api-reference.444b23.json
Each fixture also records its human-facing API reference URL. No provider calls.
"""

import json
from email.parser import BytesParser
from email.policy import default
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
import pytest
from pydantic import ValidationError

from nodes.ringcentral_node import (
    ENDPOINTS, RingCentralAccessTokenCredential, RingCentralNode,
    RingCentralNodeConfig,
)

FIXTURES = json.loads((Path(__file__).parent / "fixtures/ringcentral/documented_responses.json").read_text())
TOKEN = "ringcentral-test-token"


def node(config, credentials=True):
    return RingCentralNode(
        node_id="ringcentral-test", node_type="automation-ringcentral", node_data={},
        config=RingCentralNodeConfig.model_validate({
            "config": config,
            "credentials": {"access_token": TOKEN} if credentials else None,
        }), sio=None, sid=None, workflow_id="test-workflow",
    )


async def run(config, response=None, status_code=200, handler=None):
    requests = []

    def respond(request):
        requests.append(request)
        return handler(request) if handler else httpx.Response(status_code, json=response, request=request)

    real_client = httpx.AsyncClient
    with patch("nodes.ringcentral_node.httpx.AsyncClient", side_effect=lambda **kwargs: real_client(
        **kwargs, transport=httpx.MockTransport(respond)
    )):
        result = await node(config).execute({})
    return result, requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", FIXTURES)
async def test_documented_operation(operation):
    fixture = FIXTURES[operation]
    config = {"operation": operation, **fixture["config"]}
    result, requests = await run(config, fixture["body"], fixture["status_code"])
    assert result["status"] == "success"
    assert result["action"] == operation
    assert result["data"] == (fixture["body"] if fixture["body"] is not None else {})
    assert result["status_code"] == fixture["status_code"]
    assert result["timing_ms"]["api_request"] >= 0
    assert len(requests) == 1
    request = requests[0]
    assert request.method == fixture["method"]
    path = fixture["path"].replace("{accountId}", "~").replace("{extensionId}", "~")
    for api_name, config_name in [("callRecordId", "call_record_id"), ("ringoutId", "ringout_id"), ("messageId", "message_id"), ("contactId", "contact_id")]:
        if config_name in config:
            path = path.replace("{" + api_name + "}", config[config_name])
    assert str(request.url).split("?", 1)[0] == "https://platform.ringcentral.com" + path
    assert request.headers["authorization"] == "Bearer " + TOKEN
    assert request.headers["accept"] == "application/json"


@pytest.mark.asyncio
async def test_sms_wire_uses_array_recipients():
    f = FIXTURES["send_sms"]
    _, requests = await run({"operation": "send_sms", **f["config"]}, f["body"])
    assert json.loads(requests[0].content) == {
        "from": {"phoneNumber": "+18559100010"},
        "to": [{"phoneNumber": "+18551003738"}],
        "text": "Test SMS message from Platform server",
    }


@pytest.mark.asyncio
async def test_ringout_wire_uses_single_caller_and_callee():
    f = FIXTURES["create_ringout"]
    _, requests = await run({"operation": "create_ringout", **f["config"]}, f["body"])
    assert json.loads(requests[0].content) == {
        "from": {"phoneNumber": "+12053320032"}, "to": {"phoneNumber": "+16052160005"}, "playPrompt": True,
    }


@pytest.mark.asyncio
async def test_contact_create_and_partial_update():
    for operation in ["create_contact", "update_contact"]:
        f = FIXTURES[operation]
        _, requests = await run({"operation": operation, **f["config"]}, f["body"])
        expected = {"firstName": "Charlie", "lastName": "Williams", "businessPhone": "+15551234567"} if operation == "create_contact" else {
            "firstName": "John", "lastName": "Smith", "company": "MyCompany",
        }
        assert json.loads(requests[0].content) == expected


@pytest.mark.asyncio
async def test_message_update_uses_body_and_delete_uses_purge_query():
    _, requests = await run({"operation": "update_message", "message_id": "402412194008", "read_status": "Unread"}, FIXTURES["update_message"]["body"])
    assert json.loads(requests[0].content) == {"readStatus": "Unread"}
    assert not requests[0].url.params
    _, requests = await run({"operation": "delete_message", "message_id": "315433012010", "purge": True}, None, 204)
    assert dict(requests[0].url.params) == {"purge": "true"}


@pytest.mark.asyncio
async def test_list_filters_and_paging_preserve_navigation():
    f = FIXTURES["list_messages"]
    result, requests = await run({"operation": "list_messages", "message_type": "Fax", "read_status": "Unread", "page": 2, "per_page": 25}, f["body"])
    assert dict(requests[0].url.params) == {"messageType": "Fax", "readStatus": "Unread", "page": "2", "perPage": "25"}
    assert result["data"]["paging"] == f["body"]["paging"]
    assert result["data"]["navigation"] == f["body"]["navigation"]
    _, requests = await run({"operation": "list_call_logs", "date_from": "2017-09-03T12:34:00.000Z", "direction": "Inbound", "page": 3}, FIXTURES["list_call_logs"]["body"])
    assert dict(requests[0].url.params) == {"dateFrom": "2017-09-03T12:34:00.000Z", "direction": "Inbound", "view": "Detailed", "page": "3", "perPage": "100"}


@pytest.mark.asyncio
async def test_fax_wire_uses_documented_json_metadata_file_part():
    f = FIXTURES["send_fax"]
    _, requests = await run({"operation": "send_fax", **f["config"], "cover_page_text": "Hello"}, f["body"])
    request = requests[0]
    message = BytesParser(policy=default).parsebytes(
        b"Content-Type: " + request.headers["content-type"].encode() + b"\r\n\r\n" + request.content
    )
    parts = {p.get_param("name", header="content-disposition"): p for p in message.iter_parts()}
    # https://developers.ringcentral.com/guide/messaging/fax/sending-faxes
    assert parts["json"].get_filename() == "request.json"
    assert parts["json"].get_content_type() == "application/json"
    assert json.loads(parts["json"].get_payload(decode=True)) == {
        "to": [{"phoneNumber": "+18774880001"}],
        "faxResolution": "High", "coverIndex": 2, "coverPageText": "Hello",
    }
    assert parts["attachment"].get_filename() == "fax.txt"
    assert parts["attachment"].get_payload(decode=True) == b"attachment1"



@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 401, 403, 429, 500])
async def test_http_failures_do_not_reflect_secrets(status):
    result, _ = await run({"operation": "get_extension"}, {"message": TOKEN}, status)
    assert result["status"] == "error"
    assert result["status_code"] == status
    assert TOKEN not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [b"", b"<html>login</html>", b"[]", b"{}", b'{"errorCode":"OAU-232"}'])
async def test_invalid_json_is_not_success(body):
    result, _ = await run({"operation": "get_extension"}, handler=lambda req: httpx.Response(200, content=body, request=req))
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_transport_failure_is_sanitized():
    def fail(request):
        raise httpx.ConnectError(TOKEN, request=request)
    result, _ = await run({"operation": "get_extension"}, handler=fail)
    assert result["status"] == "error"
    assert TOKEN not in str(result)


@pytest.mark.asyncio
async def test_missing_credentials_and_unsafe_path_segment():
    with pytest.raises(ValueError, match="Credentials are required"):
        await node({"operation": "get_extension"}, credentials=False).execute({})
    result, requests = await run({"operation": "get_contact", "contact_id": "123?purge=true"}, FIXTURES["get_contact"]["body"])
    assert "%3Fpurge%3Dtrue" in str(requests[0].url)
    assert not requests[0].url.params


def test_all_operations_have_provider_fixtures_and_contact_edits_are_required():
    assert set(FIXTURES) == set(ENDPOINTS)
    for operation in ["create_contact", "update_contact"]:
        with pytest.raises(ValidationError, match="Supply at least one"):
            node({"operation": operation, "contact_id": "1707266004"})
    assert RingCentralAccessTokenCredential.model_json_schema()["title"] == "Ringcentral Access Token"


@pytest.mark.asyncio
async def test_connection_evidence_names_the_extension_from_real_response():
    from nodes.core.connection_evidence import collect_evidence
    real_client = httpx.AsyncClient
    with patch("nodes.ringcentral_node.httpx.AsyncClient", side_effect=lambda **kwargs: real_client(
        **kwargs, transport=httpx.MockTransport(lambda req: httpx.Response(200, json=FIXTURES["get_extension"]["body"], request=req))
    )):
        result = await collect_evidence(node_type="automation-ringcentral", credential_data={"access_token": TOKEN}, user_id="user-1", pool=Mock())
    assert result.reachable is True
    assert result.account_label == "Alice Smith"


@pytest.mark.asyncio
async def test_connection_evidence_rejects_expired_token():
    from nodes.core.connection_evidence import collect_evidence
    real_client = httpx.AsyncClient
    with patch("nodes.ringcentral_node.httpx.AsyncClient", side_effect=lambda **kwargs: real_client(
        **kwargs, transport=httpx.MockTransport(lambda req: httpx.Response(401, json={"errorCode": "OAU-232"}, request=req))
    )):
        result = await collect_evidence(node_type="automation-ringcentral", credential_data={"access_token": TOKEN}, user_id="user-1", pool=Mock())
    assert result.reachable is False


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{"id": 123}, {"id": 123, "name": " "}, {"name": "Alice Smith"}])
async def test_unexpected_identity_cannot_verify_token(body):
    result, _ = await run({"operation": "get_extension"}, body)
    assert result["status"] == "error"


def test_scopes_cover_every_operation_and_match_credential_permissions():
    from nodes.scopes.ringcentral import RINGCENTRAL_SCOPES
    assert set(RINGCENTRAL_SCOPES) == set(ENDPOINTS)
    assert RingCentralAccessTokenCredential.model_json_schema()["x-oauth-scopes"] == [
        "Contacts", "EditMessages", "Faxes", "ReadAccounts", "ReadCallLog",
        "ReadContacts", "ReadMessages", "RingOut", "SMS",
    ]
    assert RINGCENTRAL_SCOPES.require("send_fax").scopes == ("Faxes",)
    assert RINGCENTRAL_SCOPES.require("list_fax_cover_pages").scopes == ()
