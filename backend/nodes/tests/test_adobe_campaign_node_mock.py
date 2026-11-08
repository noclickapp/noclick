"""Native Campaign contract regressions use the real guarded HTTP boundary.

Only DNS and transport are synthetic. These cases cover one-shot mutation
uncertainty, response paging, expiring access and response-provided PKeys.
"""
from contextlib import contextmanager
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import adobe_campaign_node as s
from utils import ssrf

CREDS = {"credential_type": s.FAMILY, "product_mode": "v8_fda", "tenant_id": "owned-mkt-stage",
         "api_key": "fixture.client", "access_token": "fixture.issued.token", "expires_at": 4102444800}
BASE = "https://mc.adobe.io/owned-mkt-stage/campaign/"
PROFILE = {"PKey": "@freshProfile", "firstName": "Owned", "lastName": "Fixture",
           "href": BASE + "profileAndServices/profile/@freshProfile"}
SERVICE = {"PKey": "@ownedService", "label": "Owned newsletter",
           "href": BASE + "profileAndServices/service/@ownedService"}


@pytest.fixture
def ensure_native_db_pool():
    yield


@contextmanager
def transport(monkeypatch, replies):
    calls = []
    def answer(request):
        calls.append(request)
        assert request.url.host == "mc.adobe.io" and request.url.path.startswith("/owned-mkt-stage/campaign/")
        assert request.headers["authorization"] == "Bearer fixture.issued.token"
        assert request.headers["x-api-key"] == "fixture.client"
        result = replies.pop(0)
        if isinstance(result, Exception):
            raise result
        return result
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["8.8.8.8"]))
    factory = ssrf.guarded_async_client
    monkeypatch.setattr(s, "guarded_async_client", lambda **kwargs: factory(**kwargs, transport=httpx.MockTransport(answer)))
    yield calls


def node(operation, **arguments):
    data = {"config": {"operation": operation, **arguments}, "credentials": CREDS}
    return s.AdobeCampaignNode("fixture", "automation-adobe-campaign", data,
        config=s.AdobeCampaignNode.parse_config(data))


@pytest.mark.asyncio
async def test_paging_uses_exact_returned_cursor_and_forces_large_table_pagination(monkeypatch):
    next_url = BASE + "profileAndServices/profile?_lineCount=25&_lineStart=@opaqueCursor&_forcePagination=true"
    with transport(monkeypatch, [httpx.Response(200, json={"content": [PROFILE], "next": {"href": next_url}}),
                                httpx.Response(200, json={"content": []})]) as calls:
        first = await node("list_profiles").execute({})
        assert first["next_page_url"] == next_url and first["snapshot_verified"] is False
        assert dict(calls[0].url.params) == {"_lineCount": "25", "_forcePagination": "true"}
        second = await node("list_profiles", next_page_url=first["next_page_url"]).execute({})
        assert second["items"] == [] and str(calls[1].url) == next_url


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [
    "https://evil.example/owned-mkt-stage/campaign/profileAndServices/profile?_lineCount=25&_lineStart=@x",
    BASE.replace("owned-mkt-stage", "foreign") + "profileAndServices/profile?_lineCount=25&_lineStart=@x",
    BASE + "workflow/execution?_lineCount=25&_lineStart=@x",
    BASE + "profileAndServices/profile?_lineCount=1000&_lineStart=@x",
    BASE + "profileAndServices/profile?_lineCount=25&_lineCount=25&_lineStart=@x",
    BASE + "profileAndServices/profile?_lineCount=25&_lineStart=@x&token=private",
])
async def test_unsafe_or_foreign_continuation_refuses_before_transport(monkeypatch, bad):
    with transport(monkeypatch, []) as calls:
        result = await node("list_profiles", next_page_url=bad).execute({})
        assert result["status"] == "error" and not calls


@pytest.mark.asyncio
async def test_update_gets_fresh_pkey_and_has_separate_readback(monkeypatch):
    with transport(monkeypatch, [httpx.Response(200, json={"content": [PROFILE]}),
        httpx.Response(200, json={"PKey": "@newResponseKey", "href": BASE + "profileAndServices/profile/@newResponseKey"})]) as calls:
        result = await node("update_profile", profile_pkey="@earlierKey", first_name="Changed", confirm_profile_change=True).execute({})
        assert [request.method for request in calls] == ["GET", "PATCH"]
        assert calls[1].url.path.endswith("/@freshProfile") and json.loads(calls[1].content) == {"firstName": "Changed"}
        assert result["record"]["PKey"] == "@newResponseKey" and result["readback_verified"] is False


@pytest.mark.asyncio
async def test_create_and_delete_respect_documented_envelopes(monkeypatch):
    with transport(monkeypatch, [httpx.Response(201, json=PROFILE), httpx.Response(200, json=PROFILE),
                                httpx.Response(200, content=b"")]) as calls:
        create = await node("create_profile", last_name="Fixture", confirm_profile_change=True).execute({})
        delete = await node("delete_profile", profile_pkey=create["record"]["PKey"], confirm_profile_change=True).execute({})
        assert create["provider_acknowledged"] and delete["status_code"] == 200
        assert delete["deleted_pkey"] == "@freshProfile" and delete["readback_verified"] is False
        assert [request.method for request in calls] == ["POST", "GET", "DELETE"]


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", [httpx.Response(200, json={"success": False, "PKey": "@bad"}),
    httpx.Response(200, content=b'{"PKey":"@bad","value":NaN}', headers={"Content-Type": "application/json"}),
    httpx.Response(200, content=b'{"PKey":"@bad","value":1e309}', headers={"Content-Type": "application/json"}),
    httpx.Response(200, content=b'{"PKey":"@one","PKey":"@two"}', headers={"Content-Type": "application/json"}),
    httpx.Response(200, json={"PKey": "@bad", "href": BASE.replace("owned", "foreign") + "profileAndServices/profile/@bad"}),
    httpx.Response(200, json={}), httpx.Response(204), httpx.Response(429), httpx.ReadTimeout("synthetic")])
async def test_mutation_uncertainty_no_retry_and_sanitized_errors(monkeypatch, reply):
    with transport(monkeypatch, [reply]) as calls:
        result = await node("create_profile", last_name="Fixture", confirm_profile_change=True).execute({})
        assert result["status"] == "error" and result["uncertain_outcome"] is True and len(calls) == 1
        assert "fixture.issued.token" not in str(result) and "synthetic" not in str(result)


@pytest.mark.asyncio
async def test_expired_access_no_mint_or_transport(monkeypatch):
    creds = s.AdobeCampaignAccessTokenCredential.model_validate({**CREDS, "expires_at": 1})
    with transport(monkeypatch, []) as calls:
        with pytest.raises(s.CampaignError):
            await s.CampaignSession(creds).list_page("profileAndServices/service", 5)
        assert not calls


@pytest.mark.parametrize("changes", [{"access_token": "bad\nheader"}, {"api_key": "ünicode"}, {"tenant_id": "../other"},
    {"product_mode": "v8_ffda"}, {"credential_type": "adobe_oauth"}, {"expires_at": "4102444800"}])
def test_typed_credential_authority_and_secret_representation(changes):
    with pytest.raises(ValidationError):
        s.AdobeCampaignAccessTokenCredential.model_validate({**CREDS, **changes})
    assert "fixture.issued.token" not in repr(s.AdobeCampaignAccessTokenCredential.model_validate(CREDS))


@pytest.mark.parametrize("config", [
    {"operation": "update_profile", "profile_pkey": "@x", "confirm_profile_change": True},
    {"operation": "create_profile", "last_name": "Owned", "confirm_profile_change": "true"},
    {"operation": "update_profile", "profile_pkey": "@x", "first_name": "Owned", "confirm_profile_change": True, "blackList": True},
    {"operation": "get_custom_record", "resource_api": "customResources", "resource_name": "workflow", "record_pkey": "@x"},
])
def test_closed_changes_never_allow_empty_patch_consent_or_arbitrary_resources(config):
    with pytest.raises(ValidationError):
        s.AdobeCampaignNodeConfig.model_validate({"config": config, "credentials": CREDS})


@pytest.mark.asyncio
async def test_custom_parent_catalog_metadata_and_scalar_privacy(monkeypatch):
    metadata = {"name": "cusProduct", "content": {"label": {"apiName": "label", "type": "string"},
        "secretToken": {"type": "string"}, "owner": {"type": "link"}}}
    catalog = {"apiName": "resourceType", "cusProduct": {"name": "cusProduct", "type": "collection",
        "data": "/customResources/cusProduct/", "href": BASE + "customResources/cusProduct/metadata", "help": "Owned Products"}}
    record = {"PKey": "@record", "href": BASE + "customResources/cusProduct/@record",
              "label": "Owned Product", "secretToken": "private", "owner": {"href": "https://private.example"}}
    with transport(monkeypatch, [httpx.Response(200, json=catalog), httpx.Response(200, json=metadata),
                                httpx.Response(200, json={"content": [record]})]) as calls:
        result = await node("list_custom_records", resource_api="customResources", resource_name="cusProduct").execute({})
        assert result["items"] == [{"PKey": "@record", "href": record["href"], "label": "Owned Product"}]
        assert len(calls) == 3 and "private" not in str(result)


@pytest.mark.asyncio
async def test_parent_picker_is_enforced_before_provider(monkeypatch):
    with transport(monkeypatch, []) as calls:
        with pytest.raises(ValueError):
            await s.AdobeCampaignNode.load_field_options("resource_name", CREDS, {})
        assert not calls


@pytest.mark.asyncio
async def test_services_evidence_and_local_picker_search_never_sends_private_query(monkeypatch):
    with transport(monkeypatch, [httpx.Response(200, json={"content": [SERVICE]})]) as calls:
        result = await s.AdobeCampaignNode.load_field_options("service_pkey", CREDS, search="newsletter")
        assert result["options"] == [{"value": "@ownedService", "label": "Owned newsletter"}]
        assert "newsletter" not in str(calls[0].url)
    assert s.AdobeCampaignNode.connection_evidence.operation == "list_services"
    assert s.AdobeCampaignNode.connection_evidence.identity_operation is None


@pytest.mark.parametrize("data", [{"content": [PROFILE, PROFILE]}, {"content": [], "next": {"href": BASE}},
    {"content": [PROFILE], "serverSidePagination": "true"}, {"content": [{}]}])
def test_response_paging_shape_and_duplicate_ids(data):
    with pytest.raises(s.CampaignError):
        s.CampaignSession(s.AdobeCampaignAccessTokenCredential.model_validate(CREDS)).page(data, "profileAndServices/profile", 25)


def test_product_mode_does_not_claim_generic_adobe_identity_or_token_refresh():
    schema = s.AdobeCampaignNode.get_config_schema()
    assert len(s.OPERATIONS) == 14 and all(name not in s.OPERATIONS for name in ("send_message", "run_workflow", "subscribe", "privacy_delete", "mint_token"))
    assert "refresh_token" not in schema["$defs"]["AdobeCampaignAccessTokenCredential"]["properties"]


def test_custom_resource_schema_exposes_the_existing_name_constraint():
    schema = s.AdobeCampaignNode.get_config_schema()
    for config in ("CustomMetadata", "CustomRecords", "CustomRecord"):
        assert schema["$defs"][config]["properties"]["resource_name"]["pattern"] == r"^cus[A-Za-z][A-Za-z0-9_]{0,100}$"
