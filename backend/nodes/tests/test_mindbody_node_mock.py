"""Unrun native Mindbody wire, privacy and schema regressions.

These use actual native configs/factory and synthetic HTTP only. They do not
activate a developer key, issue a staff token or create a provider client.
"""
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import TypeAdapter, ValidationError

from nodes import mindbody_node as native
from nodes.core.registry import NodeFactory


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credential=None):
    return NodeFactory.create_node(node_id="owned-fixture", node_type=native.NODE_TYPE,
        node_data={"config": config, "credentials": credential or {"credential_type": native.FAMILY,
            "site_id": 42, "api_key": "synthetic-developer-key", "user_authorization": "synthetic-staff-header"}})


def page(envelope="Clients", items=None, limit=25, offset=0, total=None):
    rows = [] if items is None else items
    return {envelope: rows, "PaginationResponse": {"RequestedLimit": limit, "RequestedOffset": offset,
        "PageSize": len(rows), "TotalResults": len(rows) + offset if total is None else total}}


def transport(monkeypatch, reply):
    requests = []
    def provider(request):
        requests.append(request)
        return reply(request) if callable(reply) else httpx.Response(200, json=reply)
    monkeypatch.setattr(native, "guarded_async_client", lambda **kwargs:
        httpx.AsyncClient(transport=httpx.MockTransport(provider), **kwargs))
    return requests


@pytest.mark.asyncio
async def test_api_key_public_read_is_not_staff_identity_or_owned_account(monkeypatch):
    requests = transport(monkeypatch, page("StaffMembers", [{"Id": 4, "FirstName": "Synthetic", "PayRate": "private", "Email": "private"}]))
    result = await node({"operation": "list_staff"}, {"site_id": 42, "api_key": "synthetic-key"}).run({})
    assert result["status"] == "success" and result["items"] == [{"Id": 4, "FirstName": "Synthetic"}]
    assert result["staff_identity_verified"] is False and result["ownership_verified"] is False
    assert "authorization" not in requests[0].headers


@pytest.mark.asyncio
async def test_missing_or_expired_staff_auth_never_attempts_protected_request(monkeypatch):
    requests = transport(monkeypatch, page(limit=1))
    for credential in ({"site_id": 42, "api_key": "synthetic-key"},
        {"site_id": 42, "api_key": "synthetic-key", "user_authorization": "synthetic", "user_expires_at": "2000-01-01T00:00:00Z"}):
        with pytest.raises(native.CredentialValidationUnverified):
            await node({"operation": "check_connection"}, credential).execute({})
    assert requests == []


@pytest.mark.asyncio
async def test_empty_protected_probe_is_reachability_and_does_not_output_clients(monkeypatch):
    requests = transport(monkeypatch, page(limit=1))
    result = await node({"operation": "check_connection"}).run({})
    assert result["status"] == "success" and result["accessible_client_count"] == 0
    assert "items" not in result and native.MindbodyNode.connection_evidence.proves == "reachability"
    assert requests[0].headers["Authorization"] == "synthetic-staff-header"
    assert requests[0].url.params["request.limit"] == "1"


@pytest.mark.asyncio
async def test_client_paging_query_false_and_deep_privacy_projection(monkeypatch):
    requests = transport(monkeypatch, page(items=[{"Id": "owned-42", "Active": False, "FirstName": "Synthetic", "ClientCreditCard": {"CardNumber": "private"},
        "Notes": "private", "AccountBalance": 99, "RedAlert": "private", "Email": "private", "CustomClientFields": ["private"]}], total=2))
    result = await node({"operation": "list_clients", "search": "Ada + fixture", "is_prospect": False}).run({})
    assert result["has_more"] is True and result["next_offset"] == 1
    assert result["items"] == [{"Id": "owned-42", "FirstName": "Synthetic", "Active": False}]
    assert requests[0].url.params["request.searchText"] == "Ada + fixture"
    assert requests[0].url.params["request.isProspect"] == "false"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["empty-before-total", "bool-total", "wrong-offset", "missing-page", "foreign-client", "foreign-site"])
async def test_incoherent_page_and_wrong_parent_fail_honestly(monkeypatch, failure):
    reply = page()
    config = {"operation": "list_clients"}
    if failure == "empty-before-total": reply["PaginationResponse"]["TotalResults"] = 1
    elif failure == "bool-total": reply["PaginationResponse"]["TotalResults"] = False
    elif failure == "wrong-offset": reply["PaginationResponse"]["RequestedOffset"] = 3
    elif failure == "missing-page": del reply["PaginationResponse"]
    elif failure == "foreign-client":
        config = {"operation": "get_client", "client_id": "owned-42"}
        reply = page(items=[{"Id": "foreign"}], limit=1)
    else:
        config = {"operation": "list_sites"}
        reply = page("Sites", [{"Id": 24}])
    transport(monkeypatch, reply)
    assert (await node(config).run({}))["status"] == "error"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,test", [("create_client", True), ("create_client", False), ("update_client", False), ("update_client_preferences", True)])
async def test_documented_write_body_explicit_false_test_mode_and_projection(monkeypatch, operation, test):
    requests = transport(monkeypatch, {"Client": {"Id": "owned-42", "Active": False, "Notes": "private", "ClientCreditCard": {"CardNumber": "private"}}})
    config = {"operation": operation, "active": False, "test": test, "transaction_key": "owned-fixture-42"}
    if operation == "create_client": config.update(first_name="Owned", last_name="Fixture", home_location_id=9)
    elif operation == "update_client": config.update(client_id="owned-42", first_name="Owned")
    else: config.update(client_id="owned-42", promotional_emails=False)
    result = await node(config).run({})
    body = json.loads(requests[0].content)
    assert result["status"] == ("validated" if test else "success") and result["write_verified"] is False
    assert body["Test"] is test and requests[0].headers["Transaction-Key"] == "owned-fixture-42"
    if operation == "create_client":
        assert requests[0].url.path.endswith("/client/addclient") and body["Active"] is False and body["HomeLocation"] == {"Id": 9}
        assert "Client" not in body
    else:
        assert requests[0].url.path.endswith("/client/updateclient") and body["Client"]["Active"] is False
        assert body["Client"]["Id"] == "owned-42" and body["CrossRegionalUpdate"] is False
        if operation == "update_client_preferences": assert body["Client"]["SendPromotionalEmails"] is False
    assert "private" not in json.dumps(result)
    if test: assert "client" not in result


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [202, 204, 302, 400, 401, 403, 404, 429, 500])
async def test_read_status_contract_no_redirect_and_no_provider_error_reflection(monkeypatch, code):
    requests = transport(monkeypatch, lambda _: httpx.Response(code, json={"Error": {"Message": "synthetic-staff-header private"}}, headers={"Location": "https://foreign.example.test", "Retry-After": "12"}))
    result = await node({"operation": "list_clients"}).run({})
    assert result["status"] == "error" and result["http_status"] == code and len(requests) == 1
    assert "synthetic-staff-header" not in json.dumps(result) and "private" not in json.dumps(result)


@pytest.mark.asyncio
async def test_uncertain_write_retains_correlation_and_target_without_retry(monkeypatch):
    calls = []
    def timeout(request):
        calls.append(request)
        raise httpx.ReadTimeout("synthetic secret", request=request)
    transport(monkeypatch, timeout)
    result = await node({"operation": "update_client", "client_id": "owned-42", "first_name": "Synthetic", "active": False, "test": False, "transaction_key": "owned-uncertain"}).execute({})
    assert result["write_outcome_unknown"] is True and result["client_id"] == "owned-42"
    assert result["transaction_key"] == "owned-uncertain" and len(calls) == 1


@pytest.mark.parametrize("tag", [None, "", "foreign", 42])
def test_original_family_guard_precedes_inherited_reconciliation(tag):
    data = {"config": {"operation": "list_clients"}, "credentials": {"site_id": 42, "api_key": "synthetic-key", "credential_type": tag},
        "credentialIds": {native.FAMILY: "00000000-0000-4000-8000-000000000042"}}
    assert native.MindbodyNode.validate_config(data)["valid"] is False
    with pytest.raises(ValueError): native.MindbodyNode.parse_config(data)


def test_schema_validation_defaults_constraints_and_typed_operation_boundaries():
    schema = native.MindbodyNode.get_config_schema()
    assert schema["$defs"]["MindbodyAPIKeyCredential"]["title"] == "Mindbody Public API"
    assert schema["$defs"]["MindbodyAPIKeyCredential"]["properties"]["api_key"]["ui:widget"] == "password"
    assert schema["$defs"]["MindbodyCreateClientConfig"]["properties"]["test"]["default"] is True
    assert native.MindbodyCreateClientConfig(first_name="Owned", last_name="Fixture", active=False).test is True
    assert native.MindbodyCreateClientConfig(first_name="Owned", last_name="Fixture", active=False, home_location_id="9").home_location_id == 9
    assert native.MindbodyPreferencesConfig(client_id="owned-42", active=False, promotional_emails=False).promotional_emails is False
    with pytest.raises(ValidationError): native.MindbodyPreferencesConfig(client_id="owned-42", active=False)
    with pytest.raises(ValidationError): native.MindbodyClientsConfig(offset=True)
    with pytest.raises(ValidationError): native.MindbodyClassesConfig(start="2026-01-01", end="2026-03-01")
    with pytest.raises(ValidationError): native.MindbodyUpdateClientConfig(client_id="owned-42", active=False, first_name="Owned", SiteId=24)


def test_actual_factory_accepts_combobox_string_and_nested_save_labels_without_allowing_arbitrary_fields():
    data = {"credentials": {"credential_type": native.FAMILY, "site_id": "42", "api_key": "synthetic-key"},
        "config": {"operation": "list_classes", "start": "2026-10-01T09:00:00", "end": "2026-10-02T09:00:00", "location_id": "9",
            "location_id__label": "Owned room", "credentialIds": {native.FAMILY: "00000000-0000-4000-8000-000000000042"}}}
    instance = NodeFactory.create_node(node_id="owned", node_type=native.NODE_TYPE, node_data=data)
    assert instance.config.config.location_id == 9 and instance.config.credentials.site_id == 42
    assert data["config"]["location_id__label"] == "Owned room"
    assert "credentialIds" not in instance.config.config.model_dump()
    data["config"]["arbitrary_body"] = {"SiteId": 24}
    with pytest.raises(ValueError):
        NodeFactory.create_node(node_id="owned", node_type=native.NODE_TYPE, node_data=data)


def test_discriminated_union_keeps_operation_literal_while_parsing_numeric_form_values():
    adapter = TypeAdapter(native.MindbodyConfig)
    config = adapter.validate_python({"operation": "list_classes", "start": "2026-10-01T09:00:00", "end": "2026-10-02T09:00:00",
        "location_id": "9", "staff_id": "4", "limit": "25", "offset": "0"})
    assert isinstance(config, native.MindbodyClassesConfig) and config.operation == "list_classes"
    assert (config.location_id, config.staff_id, config.limit, config.offset) == (9, 4, 25, 0)
    with pytest.raises(ValidationError):
        adapter.validate_python({"operation": "9"})
    schema = native.MindbodyNode.get_config_schema()
    assert schema["properties"]["config"]["discriminator"]["propertyName"] == "operation"
    assert len(schema["properties"]["config"]["discriminator"]["mapping"]) == 14
