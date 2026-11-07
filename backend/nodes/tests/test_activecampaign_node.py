"""ActiveCampaign API contracts, credentials, and poll trigger."""

import json
import re
from unittest.mock import AsyncMock, Mock, patch

from pydantic import ValidationError

import httpx
import pytest

from nodes.activecampaign_node import (
    ActiveCampaignApiKeyCredential,
    ActiveCampaignNode,
    ActiveCampaignNodeConfig,
    CONFIG_MODELS,
    OPERATIONS,
    _base_url,
)


def node(operation: str, **overrides) -> ActiveCampaignNode:
    fields = {"operation": operation}
    if operation in CONFIG_MODELS:
        spec = OPERATIONS[operation]
        fields.update({key: "sample" for key in re.findall(r"\{([^}]+)\}", spec.path)})
        fields.update({key: "sample" for key in spec.required_query})
        if spec.body_required:
            fields["payload_json"] = '{"name":"Sample"}'
    fields.update(overrides)
    return ActiveCampaignNode(
        node_id="activecampaign-test", node_type="automation-activecampaign", node_data={},
        config=ActiveCampaignNodeConfig.model_validate({
            "config": fields,
            "credentials": {"credential_type": "activecampaign_api_key",
                            "api_url": "https://example.api-us1.com/api/3", "api_key": "secret"},
        }),
        sio=Mock(), sid="sid", workflow_id="workflow", user_id="user",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("name", OPERATIONS)
async def test_every_operation_routes_to_published_method_path_and_envelope(name):
    spec = OPERATIONS[name]
    expected_path = re.sub(r"\{[^}]+\}", "sample", spec.path)
    api = AsyncMock(return_value={"ok": True})
    with patch.object(ActiveCampaignNode, "_request", api):
        result = await node(name).execute({})
    assert result["operation"] == name
    assert result["data"] == {"ok": True}
    args, kwargs = api.call_args
    assert args[1:] == (spec.method, expected_path)
    if spec.body_required:
        expected = {"name": "Sample"}
        if spec.body_root:
            expected = {spec.body_root: expected}
        assert kwargs["body"] == expected
    else:
        assert kwargs["body"] is None


@pytest.mark.asyncio
async def test_account_url_and_api_token_are_sent_to_guarded_client():
    credential = ActiveCampaignApiKeyCredential(
        api_url="https://example.api-us1.com/api/3", api_key="secret"
    )
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.request.return_value = httpx.Response(
        200, json={"contacts": [{"id": "1", "email": "a@example.com"}]},
        request=httpx.Request("GET", "https://example.api-us1.com/api/3/contacts"),
    )
    with patch("nodes.activecampaign_node.guarded_async_client", return_value=client):
        data = await ActiveCampaignNode._request(credential, "GET", "/contacts",
                                                  params={"limit": 20})
    assert data["contacts"][0]["id"] == "1"
    args, kwargs = client.request.call_args
    assert args == ("GET", "https://example.api-us1.com/api/3/contacts")
    assert kwargs["headers"]["Api-Token"] == "secret"
    assert kwargs["params"] == {"limit": 20}


@pytest.mark.parametrize("url", [
    "http://example.api-us1.com/api/3", "https://localhost/api/3?x=1",
    "https://example.api-us1.com/", "https://user:pass@example.api-us1.com/api/3",
    "https://example.api-us1.com/api/3#fragment",
])
def test_api_url_rejects_noncanonical_hosts_and_paths(url):
    with pytest.raises(ValueError):
        _base_url(url)


@pytest.mark.asyncio
async def test_json_validation_and_contact_tags_request():
    with patch.object(ActiveCampaignNode, "_request", AsyncMock(return_value={"ok": True})) as api:
        await node("add_contact_tags", contactId="42", payload_json='{"tags":["VIP"]}').execute({})
    assert api.call_args.args[2] == "/contacts/42/tags"
    assert api.call_args.kwargs["body"] == {"tags": ["VIP"]}
    with pytest.raises(ValueError, match="valid JSON"):
        await node("create_contact", payload_json="not JSON").execute({})
    with pytest.raises(ValueError, match="JSON object"):
        await node("create_contact", payload_json="[]").execute({})


@pytest.mark.asyncio
async def test_poller_pages_and_filters_new_contacts():
    rows = {"contacts": [{"id": "42", "email": "new@example.com"}]}
    with patch.object(ActiveCampaignNode, "_request", AsyncMock(return_value=rows)) as api, \
         patch.object(ActiveCampaignNode, "_filter_unseen", AsyncMock(return_value=rows["contacts"])):
        output = await node("on_new_contact", list_id="7").execute({})
    assert output["new_contact_count"] == 1
    assert api.call_args.kwargs["params"]["listid"] == "7"
    assert ActiveCampaignNode.should_propagate_output(output, {"operation": "on_new_contact"})
    assert not ActiveCampaignNode.should_propagate_output(
        {"new_contact_count": 0}, {"operation": "on_new_contact"})


def test_schema_has_all_actions_trigger_and_api_key():
    schema = ActiveCampaignNode.get_config_schema()
    assert len(OPERATIONS) == 77
    assert len(CONFIG_MODELS) == len(OPERATIONS)
    assert "ActiveCampaignApiKeyCredential" in json.dumps(schema)
    assert "on_new_contact" in json.dumps(schema)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,fields,path,query", [
    ("remove_contact_tag_by_name", {"contactId": "1", "tag": "Newsletter"},
     "/contacts/1/tags", {"tag": "Newsletter"}),
    ("remove_contact_from_automation", {"contact": "117", "automation": "42"},
     "/contactAutomations", {"contact": "117", "automation": "42"}),
])
async def test_removals_send_required_query_without_optional_json(operation, fields, path, query):
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.request.return_value = httpx.Response(204, request=httpx.Request(
        "DELETE", "https://example.api-us1.com/api/3" + path))
    with patch("nodes.activecampaign_node.guarded_async_client", return_value=client):
        await node(operation, **fields).execute({})
    assert client.request.call_args.args == ("DELETE", "https://example.api-us1.com/api/3" + path)
    assert client.request.call_args.kwargs["params"] == query
    for key in query:
        with pytest.raises(ValidationError):
            node(operation, **{**fields, key: None})
