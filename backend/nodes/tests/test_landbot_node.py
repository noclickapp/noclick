"""Landbot Platform contracts using synthetic HTTP, never a workspace."""
import json
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import landbot_node as node
from utils import ssrf

CREDENTIAL = {"credential_type": "landbot_agent_token", "agent_token": "fixture-landbot-agent-token-89ba"}
CHANNEL = {"id": 12, "name": "Fixture Channel", "type": "landbot", "active": True, "token": "private-channel-token", "image": "private-image"}
CUSTOMER = {"id": 34, "name": "Fixture Customer", "channel_id": 12, "archived": False, "unread": True, "avatar": "private-avatar", "meta_data": {"private": "content"}, "custom_fields": {"tier": {"type": "string", "value": "private-field-value"}}}
FIELD_ROUTE = "/v1/customers/34/fields/tier/"


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    calls, replies = [], {
        ("GET", "/v1/channels/12/"): {"success": True, "channel": CHANNEL},
        ("GET", "/v1/customers/34/"): {"success": True, "customer": CUSTOMER},
    }
    async def handler(request):
        calls.append(request)
        assert request.url.scheme == "https" and request.url.host == "api.landbot.io"
        assert request.headers["Authorization"] == "Token " + CREDENTIAL["agent_token"]
        assert CREDENTIAL["agent_token"] not in str(request.url)
        reply = replies[(request.method, request.url.path)]
        return reply(request) if callable(reply) else httpx.Response(200, json=reply)
    actual_client = ssrf.guarded_async_client
    monkeypatch.setattr(ssrf, "assert_url_allowed", AsyncMock())
    monkeypatch.setattr(node, "allow_private_hosts", lambda: False)
    monkeypatch.setattr(node, "guarded_async_client", lambda **kwargs: actual_client(transport=httpx.MockTransport(handler), **kwargs))
    return calls, replies


async def test_platform_token_list_and_numeric_paging_omit_channel_secrets(transport):
    calls, replies = transport
    replies[("GET", "/v1/channels/")] = {"success": True, "total": 2, "channels": [CHANNEL]}
    result = await node.request_operation(CREDENTIAL, node.ListChannels(limit=1, active=False, channel_type="landbot"))
    assert result["data"]["items"] == [{"id": "12", "name": "Fixture Channel", "type": "landbot", "active": True}]
    assert result["data"]["next_offset"] == 1
    assert dict(calls[0].url.params) == {"limit": "1", "offset": "0", "active": "false", "type": "landbot"}
    assert len(calls) == 1 and calls[0].headers["Accept"] == "application/json"


async def test_zero_limit_is_count_only_without_synthesizing_a_next_page(transport):
    _, replies = transport
    replies[("GET", "/v1/channels/")] = {"success": True, "total": 2, "channels": []}
    result = await node.request_operation(CREDENTIAL, node.ListChannels(limit=0))
    assert result["data"] == {"items": [], "total": 2, "offset": 0, "limit": 0, "next_offset": None}


async def test_execute_with_preparsed_config_and_no_raw_node_data(transport):
    calls, replies = transport
    replies[("GET", "/v1/channels/")] = {"success": True, "total": 1, "channels": [CHANNEL]}
    config = node.LandbotNodeConfig.model_validate({"config": {"operation": "list_channels"}, "credentials": CREDENTIAL})
    instance = node.LandbotNode(node_id="landbot", node_type="automation-landbot", node_data={}, config=config)
    result = await instance.execute({})
    assert result["status"] == "success" and result["data"]["items"][0]["id"] == "12"
    assert len(calls) == 1


async def test_execute_preparsed_config_still_rejects_raw_controls(transport):
    calls, _ = transport
    config = node.LandbotNodeConfig.model_validate({"config": {"operation": "list_channels"}, "credentials": CREDENTIAL})
    instance = node.LandbotNode(node_id="landbot", node_type="automation-landbot", node_data={"url": "https://foreign.example.test"}, config=config)
    with pytest.raises(ValueError, match="arbitrary API"):
        await instance.execute({})
    assert calls == []


async def test_customer_list_checks_channel_and_uses_only_typed_query(transport):
    calls, replies = transport
    replies[("GET", "/v1/customers/")] = {"success": True, "total": 1, "customers": [CUSTOMER]}
    result = await node.request_operation(CREDENTIAL, node.ListCustomers(channel_id="12", archived=True))
    assert result["data"]["items"][0] == {"id": "34", "name": "Fixture Customer", "channel_id": "12", "archived": False, "unread": True}
    assert dict(calls[-1].url.params) == {"channel_id": "12", "limit": "20", "offset": "0", "archived": "true"}
    assert [call.url.path for call in calls] == ["/v1/channels/12/", "/v1/customers/"]


@pytest.mark.parametrize("parent", [None, 13])
async def test_missing_or_foreign_customer_parent_stops_before_field_write(transport, parent):
    calls, replies = transport
    replies[("GET", "/v1/customers/34/")] = {"success": True, "customer": {**CUSTOMER, "channel_id": parent}}
    with pytest.raises(ValueError):
        await node.request_operation(CREDENTIAL, node.CreateCustomerField(channel_id="12", customer_id="34", field_name="tier", field_type="string", value_json='"new"'))
    assert len(calls) == 2 and all(call.method == "GET" for call in calls)


async def test_field_metadata_does_not_export_all_customer_values(transport):
    _, _ = transport
    result = await node.request_operation(CREDENTIAL, node.ListCustomerFields(channel_id="12", customer_id="34"))
    assert result["data"] == {"channel_id": "12", "customer_id": "34", "items": [{"name": "tier", "type": "string"}]}
    assert "private-field-value" not in repr(result) and "private-avatar" not in repr(result)


@pytest.mark.parametrize("cls,method", [(node.CreateCustomerField, "POST"), (node.UpdateCustomerField, "PUT")])
async def test_field_create_and_update_use_distinct_200_contracts(transport, cls, method):
    calls, replies = transport
    replies[("GET", FIELD_ROUTE)] = {"success": True, "field": {"name": "tier", "type": "string", "value": "old"}}
    def write(request):
        assert json.loads(request.content) == {"type": "object", "value": {"tiers": ["new", 2]}, "extra": {}}
        return httpx.Response(200, json={"success": True, "field": {"name": "tier", "type": "object", "value": {"tiers": ["new", 2]}}})
    replies[(method, FIELD_ROUTE)] = write
    result = await node.request_operation(CREDENTIAL, cls(channel_id="12", customer_id="34", field_name="tier", field_type="object", value_json='{"tiers":["new",2]}'))
    assert result["data"]["value"] == {"tiers": ["new", 2]}
    assert [call.method for call in calls] == (["GET", "GET", "POST"] if method == "POST" else ["GET", "GET", "GET", "PUT"])


@pytest.mark.parametrize("cls,status", [(node.CreateCustomerField, 412), (node.UpdateCustomerField, 404)])
async def test_existing_create_or_missing_update_never_changes_verb(transport, cls, status):
    calls, replies = transport
    method = "POST" if cls is node.CreateCustomerField else "GET"
    replies[(method, FIELD_ROUTE)] = lambda _: httpx.Response(status, text="<html>private provider error</html>")
    with pytest.raises(node.LandbotAPIError) as failure:
        await node.request_operation(CREDENTIAL, cls(channel_id="12", customer_id="34", field_name="tier", field_type="string", value_json='"new"'))
    assert failure.value.http_status == status and "private" not in str(failure.value)
    assert all(call.method != "PUT" for call in calls) and len(calls) == 3


async def test_delete_confirmed_field_accepts_204_without_json_parsing(transport):
    calls, replies = transport
    replies[("GET", FIELD_ROUTE)] = {"success": True, "field": {"name": "tier", "type": "string", "value": "old"}}
    replies[("DELETE", FIELD_ROUTE)] = lambda _: httpx.Response(204, content=b"")
    result = await node.request_operation(CREDENTIAL, node.DeleteCustomerField(channel_id="12", customer_id="34", field_name="tier", confirm_delete=True))
    assert result["data"] == {"channel_id": "12", "customer_id": "34", "field_name": "tier", "deleted": True, "http_status": 204}
    assert [call.method for call in calls] == ["GET", "GET", "GET", "DELETE"]


@pytest.mark.parametrize("confirmation", [None, False, 1, "true"])
def test_delete_requires_literal_boolean_confirmation(confirmation):
    with pytest.raises(ValueError):
        node.DeleteCustomerField(channel_id="12", customer_id="34", field_name="tier", confirm_delete=confirmation)


async def test_nested_boolean_coercion_is_not_accepted_as_confirmed_field_value(transport):
    calls, replies = transport
    replies[("POST", FIELD_ROUTE)] = {"success": True, "field": {"name": "tier", "type": "object", "value": {"n": True}}}
    with pytest.raises(ValueError, match="exact field type and value"):
        await node.request_operation(CREDENTIAL, node.CreateCustomerField(channel_id="12", customer_id="34", field_name="tier", field_type="object", value_json='{"n":1}'))
    assert len(calls) == 3


@pytest.mark.parametrize("target,cls", [(True, node.ArchiveCustomer), (False, node.UnarchiveCustomer)])
async def test_archive_transition_uses_metadata_readback_and_no_message_endpoint(transport, target, cls):
    calls, replies = transport
    state = {"archived": not target}
    replies[("GET", "/v1/customers/34/")] = lambda _: httpx.Response(200, json={"success": True, "customer": {**CUSTOMER, **state}})
    def change(_):
        state["archived"] = target
        return httpx.Response(200, json={"success": True})
    replies[("PUT", f"/v1/customers/34/{'archive' if target else 'unarchive'}/")] = change
    result = await node.request_operation(CREDENTIAL, cls(channel_id="12", customer_id="34"))
    assert result["changed"] is True and result["data"]["archived"] is target
    assert [call.method for call in calls] == ["GET", "GET", "PUT", "GET", "GET"]
    assert all("message" not in call.url.path for call in calls)


async def test_already_archived_does_not_issue_write(transport):
    calls, replies = transport
    replies[("GET", "/v1/customers/34/")] = {"success": True, "customer": {**CUSTOMER, "archived": True}}
    assert (await node.request_operation(CREDENTIAL, node.ArchiveCustomer(channel_id="12", customer_id="34")))["changed"] is False
    assert [call.method for call in calls] == ["GET", "GET"]


async def test_hooks_are_endpoint_catalog_metadata_without_secret_or_url(transport):
    calls, replies = transport
    replies[("GET", "/v1/channels/12/message_hooks/")] = {"success": True, "hooks": [{"id": 56, "name": "Fixture hook", "channel_id": 12, "url": "https://private.example.test", "shared_token": "private-hook-secret", "created_at": 123}]}
    result = await node.request_operation(CREDENTIAL, node.ListMessageHooks(channel_id="12"))
    assert result["data"]["items"] == [{"id": "56", "name": "Fixture hook", "channel_id": "12", "created_at": 123}]
    assert result["data"]["pagination"] == "not documented by endpoint spec"
    assert not calls[-1].url.params and "private" not in repr(result)


async def test_incomplete_paginated_hooks_fail_loudly_without_guessed_next_request(transport):
    calls, replies = transport
    replies[("GET", "/v1/channels/12/message_hooks/")] = {"success": True, "hooks": [], "total": 2}
    with pytest.raises(ValueError, match="no partial catalog"):
        await node.request_operation(CREDENTIAL, node.ListMessageHooks(channel_id="12"))
    assert len(calls) == 2


@pytest.mark.parametrize("status", [201, 202, 204, 308, 401, 403, 429, 500])
async def test_get_status_errors_are_private_and_no_redirect_or_retry(transport, status):
    calls, replies = transport
    replies[("GET", "/v1/channels/12/")] = lambda _: httpx.Response(status, text=CREDENTIAL["agent_token"], headers={"Location": "https://private.example.test", "Retry-After": "17"})
    with pytest.raises(node.LandbotAPIError) as failure:
        await node.request_operation(CREDENTIAL, node.GetChannel(channel_id="12"))
    assert failure.value.http_status == status and failure.value.retry_after == 17
    assert CREDENTIAL["agent_token"] not in str(failure.value) and "private" not in str(failure.value)
    assert len(calls) == 1


@pytest.mark.parametrize("raw", [b'{"success":true,"success":true}', b'{"success":true,"channel":NaN}', b'{"success":true,"channel":1e999}', b'not-json', b'{"success":false}', b'{"success":true,"errors":{"private":"content"}}'])
async def test_malformed_or_false_success_envelope_is_not_accepted(transport, raw):
    _, replies = transport
    replies[("GET", "/v1/channels/12/")] = lambda _: httpx.Response(200, content=raw, headers={"Content-Type": "application/json"})
    with pytest.raises(ValueError):
        await node.request_operation(CREDENTIAL, node.GetChannel(channel_id="12"))


async def test_decoded_response_size_is_bounded_before_partial_projection(transport):
    calls, replies = transport
    replies[("GET", "/v1/channels/12/")] = lambda _: httpx.Response(200, content=b"x" * (node.MAX_BYTES + 1), headers={"Content-Type": "application/json"})
    with pytest.raises(ValueError, match="2 MiB"):
        await node.request_operation(CREDENTIAL, node.GetChannel(channel_id="12"))
    assert len(calls) == 1


@pytest.mark.parametrize("kind,value", [("integer", "true"), ("boolean", "1"), ("date", '"2026-02-30"'), ("object", '"text"'), ("float", "NaN"), ("object", '{"n":1,"n":2}')])
def test_field_json_is_finite_unique_and_matches_documented_type(kind, value):
    with pytest.raises(ValueError):
        node.CreateCustomerField(channel_id="12", customer_id="34", field_name="tier", field_type=kind, value_json=value)


async def test_private_override_and_cross_token_or_parent_picker_cursor_precede_io(transport, monkeypatch):
    calls, _ = transport
    monkeypatch.setattr(node, "allow_private_hosts", lambda: True)
    with pytest.raises(ValueError, match="overrides"):
        await node.request_operation(CREDENTIAL, node.GetChannel(channel_id="12"))
    with pytest.raises(ValueError, match="different current"):
        await node.LandbotNode.load_field_options("channel_id", CREDENTIAL, page_token="forged:100")
    with pytest.raises(ValueError):
        await node.LandbotNode.load_field_options("customer_id", CREDENTIAL, context={"_channel_id": "12"})
    assert calls == []


def test_field_and_metadata_projection_scrub_agent_token_and_shared_secret_keys():
    credential = node.credential_value(CREDENTIAL)
    result = node.field_record({"name": "tier", "type": "object", "value": {"secret": "private", "nested": [credential.agent_token, "token=private"]}}, credential, "tier")
    assert result["value"] == {"secret": "[redacted]", "nested": ["[redacted]", "token=[redacted]"]}
    assert credential.agent_token not in repr(credential)
