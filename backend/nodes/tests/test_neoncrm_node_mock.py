"""Unrun native Neon CRM transport and public-contract regressions.
Exercises real factory parsing and execution against an in-memory HTTP transport.
It never invokes a provider endpoint or creates an account.
"""
import json
from contextlib import asynccontextmanager
from base64 import b64encode
import httpx
import pytest
from nodes.core.registry import NodeFactory
from nodes import neoncrm_node as native

CREDENTIAL = {"credential_type": native.FAMILY, "org_id": "owned-org", "api_key": "fixture-native-secret", "instance": "production"}
PAGE = {"currentPage": 0, "pageSize": 20, "totalPages": 1, "totalResults": 1}
PERSON = {"first_name": "Owned", "last_name": "Fixture"}
ACTIVITY = {"subject": "Owned Fixture", "start_date": "2026-10-06T12:00:00Z", "timezone_id": "4", "status_id": "5"}
CASES = [
    ("get_organization_profile", {}, "GET", "/properties/organizationProfile", {"orgId": "owned-org", "name": "Owned Org"}),
    ("get_current_user", {}, "GET", "/properties/currentSystemUser", {"id": "1", "firstName": "Owner"}),
    ("list_accounts", {}, "GET", "/accounts", {"accounts": [{"accountId": "11", "firstName": "Owned", "email": "hidden@example.test"}], "pagination": PAGE}),
    ("get_account", {"account_id": "11"}, "GET", "/accounts/11", {"individualAccount": {"accountId": "11", "primaryContact": {"firstName": "Owned", "email1": "hidden@example.test"}, "login": {"password": "hidden"}}}),
    ("create_individual_account", PERSON, "POST", "/accounts", {"id": "11"}),
    ("create_company_account", {"name": "Owned Company"}, "POST", "/accounts", {"id": "11"}),
    ("update_individual_account", {**PERSON, "account_id": "11"}, "PATCH", "/accounts/11", {"accountId": "11"}),
    ("update_company_account", {"name": "Owned Company", "account_id": "11"}, "PATCH", "/accounts/11", {"accountId": "11"}),
    ("list_contacts", {"account_id": "11"}, "GET", "/accounts/11/contacts", {"accountId": "11", "contacts": [{"contactId": "21", "accountId": "99", "firstName": "Owned"}], "pagination": PAGE}),
    ("get_contact", {"account_id": "11", "contact_id": "21"}, "GET", "/accounts/11/contacts/21", {"contactId": "21", "accountId": "99", "firstName": "Owned"}),
    ("create_contact", {**PERSON, "account_id": "11"}, "POST", "/accounts/11/contacts", {"id": "21", "accountId": "99"}),
    ("update_contact", {"first_name": "Changed", "account_id": "11", "contact_id": "21"}, "PATCH", "/accounts/11/contacts/21", {"accountId": "99"}),
    ("delete_contact", {"account_id": "11", "contact_id": "21"}, "DELETE", "/accounts/11/contacts/21", {"accountId": "99"}),
    ("get_activity", {"activity_id": "31"}, "GET", "/activities/31", {"id": "31", "subject": "Owned", "note": "private", "location": "private", "reminders": {"email": True}}),
    ("create_activity", ACTIVITY, "POST", "/activities", {"ids": ["31"]}),
    ("update_activity", {**ACTIVITY, "activity_id": "31"}, "PATCH", "/activities/31", {"ids": ["31"]}),
    ("delete_activity", {"activity_id": "31"}, "DELETE", "/activities/31", {"id": "31"}),
    ("list_events", {}, "GET", "/events", {"events": [{"id": 41, "name": "Owned Event", "thumbnailUrl": "https://private.example.test", "addressLine1": "private"}], "pagination": PAGE}),
    ("get_event", {"event_id": "41"}, "GET", "/events/41", {"id": "41", "name": "Owned Event", "financialSettings": {"fee": 500}}),
    ("list_activity_statuses", {}, "GET", "/properties/activityStatuses", [{"id": "5", "name": "Open"}]),
    ("list_activity_types", {}, "GET", "/properties/activityTypes", [{"id": "6", "name": "Call"}]),
    ("list_timezones", {}, "GET", "/properties/systemTimezones", [{"id": "4", "name": "UTC"}]),
    ("list_activity_search_fields", {}, "GET", "/activities/search/searchFields", {"standardFields": [{"fieldName": "Subject", "operators": ["EQUAL"]}]}),
    ("list_activity_output_fields", {}, "GET", "/activities/search/outputFields", {"standardFields": ["Subject"], "customFields": [{"id": 77}]}),
]


def node(operation, arguments=None, credentials=None, **extra):
    return NodeFactory.create_node(node_id="native-fixture", node_type="automation-neoncrm",
        node_data={"config": {"operation": operation, **(arguments or {})}, "credentials": credentials or dict(CREDENTIAL), **extra},
        user_id="fixture-caller", organization_id=None)


def transport(monkeypatch, handler):
    monkeypatch.setattr(native, "guarded_async_client", lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(handler), **kw))


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,args,method,path,response", CASES)
async def test_real_factory_native_contract(monkeypatch, operation, args, method, path, response):
    calls = []
    def handler(request):
        calls.append(request)
        assert request.method == method and request.url.path == "/v2" + path
        assert request.url.host == "api.neoncrm.com"
        assert request.headers["authorization"] == "Basic " + b64encode(b"owned-org:fixture-native-secret").decode()
        assert request.headers["neon-api-version"] == "2.12"
        assert "api_key" not in request.url.params
        return httpx.Response(200, json=response)
    transport(monkeypatch, handler)
    instance = node(operation, args)
    assert isinstance(instance, native.NeonCRMNode)
    result = await instance.execute({})
    assert result["success"] is True and len(calls) == 1
    rendered = json.dumps(result)
    assert "fixture-native-secret" not in rendered
    assert "hidden@example.test" not in rendered and "private.example.test" not in rendered
    if operation.startswith(("create_", "update_", "delete_")):
        assert result["data"]["write_acknowledged"] is True
        assert result["data"]["readback_verified"] is False
    if operation.startswith("create_") and "_account" in operation:
        payload = json.loads(calls[0].content)
        account = next(iter(payload.values()))
        assert account["sendSystemEmail"] is False and account["sendTextOptIn"] is False
    if operation == "get_contact":
        assert result["data"]["accountId"] == "99" and result["data"]["company_account_id"] == "11"


@pytest.mark.asyncio
async def test_report_uses_real_catalogues_and_only_requested_columns(monkeypatch):
    requests = []
    def handler(request):
        requests.append(request)
        if request.url.path.endswith("outputFields"):
            return httpx.Response(200, json={"standardFields": ["Subject"]})
        if request.url.path.endswith("searchFields"):
            return httpx.Response(200, json={"standardFields": [{"fieldName": "Subject", "operators": ["EQUAL"]}]})
        body = json.loads(request.content)
        assert body == {"searchFields": [{"field": "Subject", "operator": "EQUAL", "value": "Owned"}], "outputFields": ["Subject"], "pagination": {"currentPage": 0, "pageSize": 20}}
        return httpx.Response(200, json={"searchResults": [{"Subject": "Owned", "Private": "omit"}], "pagination": PAGE})
    transport(monkeypatch, handler)
    out = await node("search_activities", {"output_fields": ["Subject"], "search_field": "Subject", "value": "Owned"}).execute({})
    assert out["data"]["items"] == [{"Subject": "Owned"}]
    assert [r.method for r in requests] == ["GET", "GET", "POST"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status,canonical", [(200, "11"), (222, "12")])
async def test_merged_account_preserves_requested_and_canonical_ids(monkeypatch, status, canonical):
    transport(monkeypatch, lambda r: httpx.Response(status, json={"companyAccount": {"accountId": canonical, "name": "Owned"}}))
    out = await node("get_account", {"account_id": "11"}).execute({})
    assert out["data"]["account_id"] == canonical
    assert out["data"]["requested_account_id"] == "11"
    assert out["data"]["merged_account"] is (status == 222)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,args,status", [
    ("create_company_account", {"name": "Owned"}, 201),
    ("update_company_account", {"name": "Owned", "account_id": "11"}, 204),
    ("delete_contact", {"account_id": "11", "contact_id": "21"}, 204),
])
async def test_documented_empty_ack_does_not_invent_resource_id(monkeypatch, operation, args, status):
    transport(monkeypatch, lambda r: httpx.Response(status))
    data = (await node(operation, args).execute({}))["data"]
    assert data["write_acknowledged"] and not data["readback_verified"]
    assert "id" not in data and "accountId" not in data


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 503])
async def test_uncertain_write_is_never_retried(monkeypatch, status):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, headers={"location": "https://elsewhere.example.test"}, json={"error": CREDENTIAL["api_key"]})
    transport(monkeypatch, handler)
    with pytest.raises(ValueError, match="outcome is unknown; read back"):
        await node("create_company_account", {"name": "Owned"}).execute({})
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_unsaved_org_change_during_write_withholds_ack(monkeypatch):
    instance = node("create_company_account", {"name": "Owned"})
    def handler(request):
        instance.config.credentials.org_id = "another-org"
        return httpx.Response(200, json={"id": "11"})
    transport(monkeypatch, handler)
    with pytest.raises(ValueError, match="outcome is unknown"):
        await instance.execute({})


@pytest.mark.asyncio
async def test_pending_reference_preserved_by_factory_then_blocks_network(monkeypatch):
    instance = node("get_account", {"account_id": "{{nodes.source.output.id}}"})
    assert instance.config.config.account_id.startswith("{{")
    monkeypatch.setattr(native, "guarded_async_client", lambda **kw: pytest.fail("unresolved reference reached transport"))
    with pytest.raises(ValueError, match="Resolve"):
        await instance.execute({})


@pytest.mark.parametrize("change", [
    {"credential_type": "other_api_key"}, {"api_key": 123}, {"org_id": 123},
    {"credential_type": None, "token_version": 1},
])
def test_original_credential_admission_before_coercing_lens(change):
    data = {"config": {"operation": "get_current_user"}, "credentials": {**CREDENTIAL, **change}}
    assert native.NeonCRMNode.validate_config(data)["valid"] is False
    with pytest.raises(ValueError):
        native.NeonCRMNode.parse_config(data)


@pytest.mark.asyncio
async def test_unknown_success_shape_and_reflected_escaped_secret_are_not_evidence(monkeypatch):
    escaped = 'fixture-"secret'
    instance = node("get_current_user", credentials={**CREDENTIAL, "api_key": escaped})
    transport(monkeypatch, lambda r: httpx.Response(200, json={"id": "1", "firstName": escaped}))
    with pytest.raises(ValueError, match="authentication material"):
        await instance.execute({})
