"""Zoho CRM OAuth regions and V8 operation contracts."""

import json
from unittest.mock import Mock

import httpx
import pytest
import respx

from nodes.oauth.zoho_crm_oauth import (
    OAUTH_PROVIDER,
    validate_accounts_server, validate_api_domain,
)
from nodes.zoho_crm_node import (
    CreateRecord, DeleteRecord, GetCurrentUser, GetRecord, ListFields,
    ListModules, ListRecords, SearchRecords, UpdateRecord, UpsertRecord,
    ZohoCRMNode, ZohoCRMNodeConfig, ZohoCRMOAuthCredential,
)

API = "https://www.zohoapis.eu/crm/v8"


def make_node(operation):
    credential = ZohoCRMOAuthCredential(
        access_token="access", refresh_token="refresh", expires_at="2099-01-01T00:00:00Z",
        api_domain="https://www.zohoapis.eu", accounts_server="https://accounts.zoho.eu",
        user_id="u-1", email="ava@example.com",
    )
    return ZohoCRMNode(
        node_id="zoho-test", node_type="automation-zoho-crm", node_data={},
        config=ZohoCRMNodeConfig(config=operation, credentials=credential),
        sio=Mock(), sid="sid", workflow_id="workflow", user_id="user",
    )


@pytest.fixture(autouse=True)
def mock_guard_transport(monkeypatch):
    # Preserve respx HTTP assertions without making DNS requests in unit tests.
    monkeypatch.setattr("utils.ssrf.guarded_async_client", httpx.AsyncClient)
    monkeypatch.setattr("nodes.zoho_crm_node.guarded_async_client", httpx.AsyncClient)


@pytest.mark.asyncio
async def test_oauth_discovers_regional_user_and_refreshes(monkeypatch):
    monkeypatch.setenv("ZOHO_CRM_CLIENT_ID", "client")
    monkeypatch.setenv("ZOHO_CRM_CLIENT_SECRET", "secret")
    with respx.mock(assert_all_called=True) as router:
        token = router.post("https://accounts.zoho.eu/oauth/v2/token").mock(side_effect=[
            httpx.Response(200, json={"access_token": "first", "refresh_token": "renew", "expires_in": 3600,
                                      "api_domain": "https://www.zohoapis.eu"}),
            httpx.Response(200, json={"access_token": "second", "expires_in": 3600}),
        ])
        identity = router.get(API + "/users?type=CurrentUser").mock(return_value=httpx.Response(200, json={
            "users": [{"id": "u-1", "full_name": "Ava Stone", "email": "ava@example.com"}],
        }))
        tokens, name = await OAUTH_PROVIDER.exchange(
            "code", "https://www.noclick.com/api/auth/oauth/zoho_crm/callback",
            context={"accounts_server": "https://accounts.zoho.eu"})
        renewed = await OAUTH_PROVIDER.bind_refresh(tokens.model_dump())(tokens.refresh_token)
    assert token.call_count == 2
    assert dict(httpx.QueryParams(token.calls[0].request.content.decode()))["grant_type"] == "authorization_code"
    assert identity.calls[0].request.headers["Authorization"] == "Zoho-oauthtoken first"
    assert name == "Ava Stone"
    assert ZohoCRMOAuthCredential(**tokens.model_dump()).user_id is None
    assert tokens.api_domain == renewed.api_domain == "https://www.zohoapis.eu"
    assert renewed.accounts_server == "https://accounts.zoho.eu"
    assert renewed.access_token == "second"
    assert OAUTH_PROVIDER.public_metadata()["scopeSeparator"] == ","


@pytest.mark.parametrize("value", [
    "http://accounts.zoho.eu", "https://accounts.zoho.eu.evil.example",
    "https://accounts.zoho.eu:8443", "https://user@accounts.zoho.eu",
    "https://accounts.zoho.eu/path",
])
def test_untrusted_account_host_is_rejected(value):
    with pytest.raises(ValueError, match="invalid regional endpoint"):
        validate_accounts_server(value)


@pytest.mark.parametrize("value", [
    "http://www.zohoapis.eu", "https://www.zohoapis.eu.evil.example",
    "https://www.zohoapis.eu:8443", "https://www.zohoapis.eu/path",
])
def test_untrusted_api_host_is_rejected(value):
    with pytest.raises(ValueError, match="invalid regional endpoint"):
        validate_api_domain(value)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,path,params", [
    (ListModules(), "/settings/modules", None),
    (ListFields(module="Contacts"), "/settings/fields", {"module": "Contacts"}),
    (GetCurrentUser(), "/users", {"type": "CurrentUser"}),
    (ListRecords(module="Contacts", fields="Last_Name,Email"), "/Contacts",
     {"fields": "Last_Name,Email", "page": "1", "per_page": "50"}),
    (GetRecord(module="Contacts", record_id="123"), "/Contacts/123", None),
    (SearchRecords(module="Contacts", search_by="email", search_term="ava@example.com"), "/Contacts/search",
     {"email": "ava@example.com", "page": "1", "per_page": "50"}),
])
async def test_read_operations(operation, path, params):
    node = make_node(operation)
    with respx.mock(assert_all_called=True) as router:
        route = router.get(API + path).mock(return_value=httpx.Response(200, json={"data": [{"id": "123"}]}))
        result = await node.execute({})
    assert route.called
    assert route.calls[0].request.headers["Authorization"] == "Zoho-oauthtoken access"
    if params:
        assert dict(route.calls[0].request.url.params) == params
    assert result["data"]["data"][0]["id"] == "123"


@pytest.mark.asyncio
async def test_module_options_accept_canvas_pagination_and_search():
    credential = make_node(ListModules()).config.credentials.model_dump()
    with respx.mock(assert_all_called=True) as router:
        router.get(API + "/settings/modules").mock(return_value=httpx.Response(200, json={
            "modules": [
                {"api_name": "Leads", "module_name": "Leads"},
                {"api_name": "Contacts", "module_name": "Contacts"},
            ],
        }))
        options = await ZohoCRMNode.load_field_options(
            "module", credential, page_token=None, search="cont",
        )
    assert options == [{"value": "Contacts", "label": "Contacts"}]


@pytest.mark.asyncio
async def test_create_update_upsert_and_delete_records():
    operations = [
        (CreateRecord(module="Leads", record_json='{"Last_Name":"Stone","Company":"Acme"}'),
         "POST", "/Leads", {"data": [{"Last_Name": "Stone", "Company": "Acme"}]}),
        (UpdateRecord(module="Leads", record_id="123", record_json='{"Lead_Status":"Qualified"}'),
         "PUT", "/Leads/123", {"data": [{"Lead_Status": "Qualified"}]}),
        (UpsertRecord(module="Leads", record_json='{"Email":"ava@example.com"}', duplicate_check_fields="Email, Phone"),
         "POST", "/Leads/upsert", {"data": [{"Email": "ava@example.com"}],
                                    "duplicate_check_fields": ["Email", "Phone"]}),
        (DeleteRecord(module="Leads", record_id="123"), "DELETE", "/Leads/123", None),
    ]
    for operation, method, path, body in operations:
        node = make_node(operation)
        with respx.mock(assert_all_called=True) as router:
            route = router.request(method, API + path).mock(return_value=httpx.Response(200, json={
                "data": [{"status": "success", "details": {"id": "123"}}],
            }))
            result = await node.execute({})
        assert result["status"] == "success"
        assert route.called
        if body is not None:
            assert json.loads(route.calls[0].request.content) == body


@pytest.mark.asyncio
async def test_empty_search_and_per_record_errors():
    node = make_node(SearchRecords(module="Contacts", search_term="absent"))
    with respx.mock(assert_all_called=True) as router:
        router.get(API + "/Contacts/search").mock(return_value=httpx.Response(204))
        result = await node.execute({})
    assert result["data"]["data"] == []

    node = make_node(CreateRecord(module="Leads", record_json='{"Last_Name":"Stone"}'))
    with respx.mock(assert_all_called=True) as router:
        router.post(API + "/Leads").mock(return_value=httpx.Response(200, json={
            "data": [{"status": "error", "code": "MANDATORY_NOT_FOUND", "message": "Company required"}],
        }))
        with pytest.raises(ValueError, match="Company required"):
            await node.execute({})
