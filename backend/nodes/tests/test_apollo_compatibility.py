"""Saved workflow compatibility and exact provider-authored response replays."""
import copy
import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from nodes.apollo_node import ApolloNode, ApolloNodeConfig


CREDENTIAL = {"credential_type": "apollo_api_key", "api_key": "fake"}


def node_for(config):
    return ApolloNode(node_id="compat", node_type="automation-apollo", node_data={},
                      sio=Mock(), config=ApolloNodeConfig(config=config, credentials=CREDENTIAL))


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["active", "paused", "bounced", "custom_saved_status"])
async def test_saved_sequence_status_keeps_original_request(status):
    config = {"operation": "update_contact_sequence_status", "contact_id": "contact",
              "sequence_id": "sequence", "status": status}
    node = node_for(config)
    assert node.config.config.model_dump()["status"] == status
    node._make_request = AsyncMock(return_value={})
    await node.execute({})
    request = node._make_request.call_args.kwargs
    assert request["endpoint"] == "/emailer_campaigns/update_contact_status"
    assert request["json_body"] == {"contact_id": "contact", "emailer_campaign_id": "sequence", "status": status}
    assert "params" not in request


@pytest.mark.asyncio
@pytest.mark.parametrize("status,mode", [("finished", "mark_as_finished"), ("stop", "stop"), ("remove", "remove")])
async def test_documented_sequence_modes(status, mode):
    node = node_for({"operation": "update_contact_sequence_status", "contact_id": "contact",
                     "sequence_id": "sequence", "status": status})
    node._make_request = AsyncMock(return_value={})
    await node.execute({})
    request = node._make_request.call_args.kwargs
    assert request["endpoint"] == "/emailer_campaigns/remove_or_stop_contact_ids"
    assert request["params"] == {"contact_ids[]": ["contact"], "emailer_campaign_ids[]": ["sequence"], "mode": mode}


@pytest.mark.asyncio
@pytest.mark.parametrize("widget,options", [("dropdown", ["one", "two"]), ("text", ["one"]), ("dropdown", []), ("custom_saved_widget", None)])
async def test_saved_widget_and_options_keep_original_request(widget, options):
    config = {"operation": "create_custom_field", "name": "Saved Field", "field_type": "contact",
              "widget_type": widget, "options": options}
    node = node_for(config)
    assert node.config.config.model_dump()["options"] == options
    assert node.config.config.model_dump()["widget_type"] == widget
    node._make_request = AsyncMock(return_value={})
    await node.execute({})
    request = node._make_request.call_args.kwargs
    assert request["endpoint"] == "/typed_custom_fields"
    expected = {"name": "Saved Field", "field_type": "contact", "widget_type": widget}
    if options is not None:
        expected["options"] = options
    assert request["json_body"] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("fixture,config,key", [
    ("bulk_create_accounts", {"operation": "create_multiple_accounts", "accounts": [{"name": "Acme Corporation"}]}, "accounts"),
    ("bulk_create_contacts", {"operation": "create_multiple_contacts", "contacts": [{"first_name": "John"}]}, "contacts"),
    ("create_custom_field", {"operation": "create_custom_field", "name": "Test Name", "field_type": "contact"}, "typed_custom_field"),
    ("usage_stats", {"operation": "get_api_usage_and_limits"}, "is_logged_in"),
])
async def test_provider_response_preserves_provider_fields_and_legacy_alias(fixture, config, key):
    # Exact examples copied from the published OpenAPI definition, with their
    # original documentation URLs retained in each fixture. No generated body.
    example = json.loads((Path(__file__).parent / "fixtures" / "apollo" / f"{fixture}.json").read_text())
    body = example["body"]
    original = copy.deepcopy(body)
    client = httpx.AsyncClient
    with patch("nodes.apollo_node.httpx.AsyncClient", lambda **kwargs: client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body)), trust_env=False
    )):
        output = await node_for(config).execute({})
    assert output["status"] == "success"
    for provider_key, value in original.items():
        assert output["data"][provider_key] == value
    if key in {"accounts", "contacts"}:
        assert output["data"][key] == original[f"created_{key}"] + original[f"existing_{key}"]
    elif key == "typed_custom_field":
        assert output["data"][key] == original["typed_custom_fields"][0]
    else:
        assert output["data"][key] is True


def test_schema_retains_saved_field_types_options_and_status_choices():
    schema = ApolloNodeConfig.model_json_schema()
    status = schema["$defs"]["ApolloUpdateContactSequenceStatusConfig"]["properties"]["status"]
    widget = schema["$defs"]["ApolloCreateCustomFieldConfig"]["properties"]["widget_type"]
    assert status["type"] == "string"
    assert {"active", "paused", "bounced", "finished"} <= set(status["enum"])
    assert "dropdown" in widget["enum"]
    assert "options" in schema["$defs"]["ApolloCreateCustomFieldConfig"]["properties"]
