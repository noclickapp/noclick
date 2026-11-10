"""Constant Contact OAuth, representative V3 contracts, and full schema coverage."""

import base64
import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest
import respx

from nodes.constant_contact_node import (
    API_BASE, CONFIG_MODELS, CONSTANT_CONTACT_SCOPES, OPERATIONS,
    ConstantContactNode, ConstantContactNodeConfig, ConstantContactOAuthCredential,
    ConstantContactOnNewContactConfig,
)
from nodes.oauth.constant_contact_oauth import OAUTH_PROVIDER, refresh_access_token


def node(operation: str, **values) -> ConstantContactNode:
    credential = ConstantContactOAuthCredential(
        access_token="access", refresh_token="refresh", expires_at="2099-01-01T00:00:00Z")
    return ConstantContactNode(
        node_id="constant-contact-test", node_type="automation-constant-contact", node_data={},
        config=ConstantContactNodeConfig(config=(
            ConstantContactOnNewContactConfig(**values) if operation == "on_new_contact"
            else CONFIG_MODELS[operation](**values)), credentials=credential),
        sio=Mock(), sid="sid", workflow_id="workflow", user_id="user")


@pytest.mark.asyncio
async def test_oauth_code_and_refresh_use_basic_auth_and_rotate(monkeypatch):
    monkeypatch.setenv("CONSTANT_CONTACT_CLIENT_ID", "client")
    monkeypatch.setenv("CONSTANT_CONTACT_CLIENT_SECRET", "secret")
    with respx.mock(assert_all_called=True) as router:
        route = router.post("https://authz.constantcontact.com/oauth2/default/v1/token").mock(side_effect=[
            httpx.Response(200, json={"access_token": "one", "refresh_token": "rotate-1", "expires_in": 86400,
                                      "scope": "contact_data offline_access"}),
            httpx.Response(200, json={"access_token": "two", "refresh_token": "rotate-2", "expires_in": 86400}),
        ])
        router.get(API_BASE + "/account/summary").mock(return_value=httpx.Response(200, json={"organization_name": "InstaPrinz"}))
        first, name = await OAUTH_PROVIDER.exchange("code", "https://example.com/callback")
        second = await refresh_access_token(first.refresh_token)
    assert name == "InstaPrinz"
    assert first.refresh_token == "rotate-1" and second.refresh_token == "rotate-2"
    assert route.call_count == 2
    expected = "Basic " + base64.b64encode(b"client:secret").decode()
    assert all(call.request.headers["Authorization"] == expected for call in route.calls)
    assert b"redirect_uri=https%3A%2F%2Fexample.com%2Fcallback" in route.calls[0].request.content
    assert b"grant_type=refresh_token" in route.calls[1].request.content


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", list(OPERATIONS))
async def test_every_operation_dispatches_with_valid_config_and_token(operation):
    op = OPERATIONS[operation]
    values = {key: "example" for key in (*op.path_fields, *op.required_query_fields)}
    if op.body_required:
        values["payload_json"] = '{"name":"Example"}'
    path = op.path
    for key in op.path_fields:
        path = path.replace("{" + key + "}", "example")
    with respx.mock(assert_all_called=True) as router:
        route = router.request(op.method, API_BASE + path).mock(
            return_value=httpx.Response(200, json={"items": []}))
        result = await node(operation, **values).execute({})
    request = route.calls[0].request
    assert request.headers["Authorization"] == "Bearer access"
    if op.body_required:
        assert json.loads(request.content) == {"name": "Example"}
    for key in op.required_query_fields:
        assert request.url.params[key] == "example"
    assert result["status"] == "success" and result["operation"] == operation


@pytest.mark.asyncio
async def test_contact_create_list_and_required_report_query():
    with respx.mock(assert_all_called=True) as router:
        create = router.post(API_BASE + "/contacts").mock(
            return_value=httpx.Response(201, json={"contact_id": "42"}))
        lists = router.get(API_BASE + "/contact_lists").mock(
            return_value=httpx.Response(200, json={"lists": [{"name": "Customers"}]}))
        report = router.get(API_BASE + "/reports/contact_reports/42/open_and_click_rates").mock(
            return_value=httpx.Response(200, json={"open_rate": 0.5}))
        created = await node("create_contact", payload_json='{"email_address":{"address":"ada@example.com"},"create_source":"Account"}').execute({})
        listed = await node("get_lists", query_json='{"limit":25}').execute({})
        rates = await node("get_contact_open_click_rate", contact_id="42", start="2026-01-01", end="2026-09-27").execute({})
    assert created["data"]["contact_id"] == "42" and create.call_count == 1
    assert listed["data"]["lists"][0]["name"] == "Customers"
    assert lists.calls[0].request.url.params["limit"] == "25"
    assert rates["data"]["open_rate"] == 0.5
    assert report.calls[0].request.url.params["start"] == "2026-01-01"


@pytest.mark.asyncio
async def test_error_and_json_validation():
    with pytest.raises(ValueError, match="Request JSON must be a JSON object"):
        await node("create_contact", payload_json="[]").execute({})
    with pytest.raises(ValueError, match="Query Parameters JSON must be valid JSON"):
        await node("get_contacts", query_json="{").execute({})
    with respx.mock:
        respx.get(API_BASE + "/contact_lists").mock(
            return_value=httpx.Response(403, json=[{"error_message": "Missing contact_data scope"}]))
        with pytest.raises(ValueError, match="Constant Contact API error 403: Missing contact_data scope"):
            await node("get_lists").execute({})


@pytest.mark.asyncio
async def test_on_new_contact_paginates_and_filters_seen_ids():
    with respx.mock(assert_all_called=True) as router:
        route = router.get(API_BASE + "/contacts").mock(side_effect=[
            httpx.Response(200, json={"contacts": [{"contact_id": "1"}],
                                      "_links": {"next": {"href": "/v3/contacts?cursor=next"}}}),
            httpx.Response(200, json={"contacts": [{"contact_id": "2"}], "_links": {}}),
        ])
        with patch.object(ConstantContactNode, "_filter_unseen",
                          AsyncMock(return_value=[{"contact_id": "2"}])) as unseen:
            result = await node("on_new_contact", list_id="my-list").execute({})
    assert route.call_count == 2
    assert route.calls[0].request.url.params["lists"] == "my-list"
    assert "created_after" in route.calls[0].request.url.params
    assert route.calls[1].request.url.params["cursor"] == "next"
    assert len(unseen.call_args.args[0]) == 2
    assert result["new_contact_count"] == 1
    assert ConstantContactNode.should_propagate_output(result, {"operation": "on_new_contact"})
    assert not ConstantContactNode.should_propagate_output(
        {"new_contact_count": 0}, {"operation": "on_new_contact"})


def test_schema_has_all_95_actions_and_poll_trigger_with_published_scopes():
    assert len(OPERATIONS) == 95
    assert set(CONSTANT_CONTACT_SCOPES.declared_scopes()) == {
        "account_read", "account_update", "campaign_data", "contact_data", "offline_access"}
    schema = ConstantContactNode.get_config_schema()
    credential = schema["$defs"]["ConstantContactOAuthCredential"]
    assert credential["x-oauth-provider"] == "constant_contact"
    assert set(credential["x-oauth-scopes"]) == {
        "offline_access", "account_read", "account_update", "campaign_data", "contact_data", "offline_access"}
    for model in CONFIG_MODELS.values():
        assert model.__name__ in schema["$defs"]
    assert schema["$defs"]["ConstantContactOnNewContactConfig"]["properties"]["operation"]["x-is-trigger"]


@pytest.mark.asyncio
async def test_contact_poll_uses_documented_payload_and_summarizes_agent_event():
    # Copied verbatim from the provider page named in this fixture.
    fixture = json.loads((Path(__file__).parent / "fixtures/constant-contact/contacts.json").read_text())
    body = fixture["body"]
    with respx.mock(assert_all_called=True) as router:
        router.get(API_BASE + "/contacts").mock(return_value=httpx.Response(200, json=body))
        with patch.object(ConstantContactNode, "_filter_unseen", AsyncMock(return_value=body["contacts"])) as unseen:
            result = await node("on_new_contact").execute({})
    assert unseen.call_args.args[1](body["contacts"][0]) == body["contacts"][0]["contact_id"]
    event = ConstantContactNode.resolve_agent_event(result)
    assert body["contacts"][0]["contact_id"] in event["text"]
    assert body["contacts"][0]["email_address"]["address"] in event["text"]
    assert "new contact" in event["text"]
    assert ConstantContactNode.resolve_agent_event({"contacts": [], "new_contact_count": 0}) is None


@pytest.mark.asyncio
async def test_poll_rejects_untrusted_page_link():
    with respx.mock(assert_all_called=True) as router:
        router.get(API_BASE + "/contacts").mock(return_value=httpx.Response(200, json={
            "contacts": [], "_links": {"next": {"href": "https://example.com/v3/contacts?cursor=x"}},
        }))
        with pytest.raises(ValueError, match="invalid contacts page link"):
            await node("on_new_contact").execute({})


@pytest.mark.asyncio
async def test_execute_retains_refreshed_credentials():
    instance = node("get_lists")

    async def refresh(**kwargs):
        kwargs["credential"].update(access_token="new-access", refresh_token="new-refresh",
                                    expires_at="2099-02-01T00:00:00Z", scope="contact_data")
        return "new-access"

    with patch("nodes.core.oauth_refresh.ensure_fresh_oauth_token", side_effect=refresh), respx.mock:
        route = respx.get(API_BASE + "/contact_lists").mock(return_value=httpx.Response(200, json={"lists": []}))
        await instance.execute({})
    assert route.calls[0].request.headers["Authorization"] == "Bearer new-access"
    assert instance.config.credentials.refresh_token == "new-refresh"
    assert instance.config.credentials.access_token == "new-access"
    assert instance.config.credentials.scope == "contact_data"
