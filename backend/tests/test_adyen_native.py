"""Adyen contracts through staging factory, credentials, selectors and transport."""
import asyncio
from copy import deepcopy
import json
import socket
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from nodes import adyen_node as ad
from nodes.core import connection_evidence as ce, credential_connect as cc, run_op
from nodes.core.registry import NodeFactory
from nodes.agent.node_op_tools import build_node_op_tools
from repositories.credential_approvals import CredentialApprovalRepo
from utils import credentials, ssrf

TYPE, FAMILY = "automation-adyen", "adyen_api_key"
ID, USER = "00000000-0000-4000-8000-000000000042", "00000000-0000-4000-8000-000000000001"
CREDS = {"api_key": "synthetic-adyen-private-key-canary", "environment": "test", "expected_api_credential_id": "API-1", "company_id": "COMPANY"}
ME = {"id": "API-1", "active": True, "username": "private-service-username", "roles": ["Management API—Account read", "Management API - Stores read and write"], "clientKey": "private-client-key-marker", "allowedIpAddresses": ["private-ip-marker"], "allowedOrigins": ["private-origin-marker"], "_links": {"self": {"href": "private-self-link"}, "company": {"href": "https://management-test.adyen.com/v3/companies/COMPANY"}}}
ROWS = {
    "company": {"id": "COMPANY", "name": "Fixture Company", "status": "Active", "description": "private-company-description", "dataCenters": [{"livePrefix": "private-prefix-marker"}]},
    "merchant": {"id": "MERCHANT", "companyId": "COMPANY", "name": "Fixture Merchant", "status": "Active", "settlementCurrency": "private-settlement-marker"},
    "store": {"id": "STORE", "merchantId": "MERCHANT", "reference": "fixture_store", "description": "private-original-description", "status": "active", "phoneNumber": "private-phone-marker", "address": {"street": "private-address-marker"}, "splitConfiguration": {"splitConfigurationId": "private-split-marker"}},
    "link": {"id": "LINK", "merchantAccount": "MERCHANT", "status": "completed", "url": "https://private-capability.example.test", "amount": {"value": 42, "currency": "EUR"}, "reference": "private-payment-reference", "shopperEmail": "private-shopper@example.test", "additionalData": {"cardSummary": "private-card-marker"}, "expiresAt": "2099-01-01T00:00:00Z"},
}


@pytest.fixture
def ensure_native_db_pool():
    yield


def factory(op, args=None, credential=None, current=None):
    data = {"config": {"operation": op, **(args or {})}, "credentials": deepcopy(CREDS if credential is None else credential)}
    if current:
        data.update(credential_id=ID, _approval_pool=current.pool)
    return NodeFactory.create_node(node_id="adyen-fixture", node_type=TYPE, node_data=data, user_id=USER)


@pytest.fixture
async def wire(monkeypatch):
    state = SimpleNamespace(calls=[], override=None, me=deepcopy(ME), rows=deepcopy(ROWS), address="8.8.8.8", patch_status=204)
    def respond(request):
        state.calls.append(request)
        assert request.url.scheme == "https" and not request.url.username
        assert request.url.host in {"management-test.adyen.com", "management-live.adyen.com", "checkout-test.adyen.com", "abc123-fixture-checkout-live.adyenpayments.com"}
        assert request.headers["X-API-Key"] == CREDS["api_key"] and "Authorization" not in request.headers
        assert set(request.url.params) <= {"pageNumber", "pageSize"}
        if state.override:
            response = state.override(request)
            if response is not None:
                return response
        path = request.url.path
        if path == "/v3/me":
            me = deepcopy(state.me)
            if "company" in me.get("_links", {}):
                me["_links"]["company"]["href"] = str(request.url.copy_with(path="/v3/companies/COMPANY"))
            return httpx.Response(200, json=me)
        singles = {"/v3/companies/COMPANY": "company", "/v3/merchants/MERCHANT": "merchant", "/v3/merchants/MERCHANT/stores/STORE": "store", "/v72/paymentLinks/LINK": "link", "/checkout/v72/paymentLinks/LINK": "link"}
        if path in singles:
            kind = singles[path]
            if request.method == "PATCH":
                assert kind == "store"
                body = json.loads(request.content)
                assert set(body) == {"description"}
                state.rows[kind]["description"] = body["description"]
                return httpx.Response(204) if state.patch_status == 204 else httpx.Response(200, json=state.rows[kind])
            assert request.method == "GET"
            return httpx.Response(200, json=state.rows[kind])
        lists = {"/v3/companies/COMPANY/merchants": "merchant", "/v3/merchants/MERCHANT/stores": "store"}
        if path in lists:
            return httpx.Response(200, json={"data": [state.rows[lists[path]]], "itemsTotal": 1, "pagesTotal": 1, "_links": {"next": {"href": "http://169.254.169.254/private-link"}}})
        return httpx.Response(404, json={"message": CREDS["api_key"]})
    async def dns(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (state.address, 443))]
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", dns)
    original = ssrf.guarded_async_client
    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return original(**kwargs, transport=httpx.MockTransport(respond))
    monkeypatch.setattr(ad, "guarded_async_client", client)
    return state


CASES = [
    ("get_identity", {}, "/v3/me", "GET"), ("get_company", {}, "/v3/companies/COMPANY", "GET"),
    ("list_merchants", {}, "/v3/companies/COMPANY/merchants", "GET"),
    ("get_merchant", {"merchant_id": "MERCHANT"}, "/v3/merchants/MERCHANT", "GET"),
    ("list_stores", {"merchant_id": "MERCHANT"}, "/v3/merchants/MERCHANT/stores", "GET"),
    ("get_store", {"merchant_id": "MERCHANT", "store_id": "STORE"}, "/v3/merchants/MERCHANT/stores/STORE", "GET"),
    ("update_store_description", {"merchant_id": "MERCHANT", "store_id": "STORE", "description": "private-updated-description", "confirm_store_change": True}, "/v3/merchants/MERCHANT/stores/STORE", "PATCH"),
    ("get_payment_link_status", {"merchant_id": "MERCHANT", "link_id": "LINK"}, "/v72/paymentLinks/LINK", "GET"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("op,args,path,method", CASES)
async def test_actual_factory_run_all_eight_native_wire_contracts(wire, op, args, path, method):
    node = factory(op, args)
    assert isinstance(node, ad.AdyenNode)
    result = await node.run({})
    assert result["api_credential_id"] == "API-1" and result["company_id"] == "COMPANY" and result["principal_kind"] == "api_credential"
    assert any(r.url.path == path and r.method == method for r in wire.calls)
    output = json.dumps(result)
    for marker in (CREDS["api_key"], "private-service-username", "private-client-key-marker", "private-ip-marker", "private-origin-marker", "private-self-link", "private-company-description", "private-prefix-marker", "private-settlement-marker", "private-original-description", "private-updated-description", "private-phone-marker", "private-address-marker", "private-split-marker", "private-capability", "private-payment-reference", "private-shopper", "private-card-marker", "169.254.169.254"):
        assert marker not in output
    if method == "PATCH":
        assert result["http_status"] == 204 and result["acknowledged"] is True and wire.calls[-1].method == "GET"
    if op == "get_payment_link_status":
        assert result["data"]["status"] == "completed" and result["data"]["settlement_verified"] is False
        assert not set(result["data"]) & {"url", "amount", "reference", "shopperEmail", "additionalData"}


def test_actual_three_value_manual_shape_and_discriminated_schema():
    blob, errors, resolved = cc.shape_credential(FAMILY, CREDS)
    assert not errors and "credential_type" not in blob and "live_url_prefix" not in blob
    assert resolved == (TYPE, ad.AdyenApiKeyCredential)
    schema = ad.AdyenNodeConfig.model_json_schema()
    assert len(schema["properties"]["config"]["discriminator"]["mapping"]) == 8
    assert schema["$defs"]["AdyenApiKeyCredential"]["properties"]["api_key"]["ui:widget"] == "password"
    assert schema["$defs"]["GetStore"]["properties"]["store_id"]["x-dynamic-options"]["depends_on"] == "merchant_id"


@pytest.mark.parametrize("tag", [None, 42, [], {}, "foreign_api_key"])
def test_original_family_guard_before_factory_parse(tag):
    with pytest.raises(ValueError, match="native Adyen"):
        factory("get_identity", credential={**CREDS, "credential_type": tag})
    assert ad.AdyenNode.validate_config({"config": {"operation": "get_identity"}, "credentials": {**CREDS, "credential_type": tag}})["valid"] is False


@pytest.mark.parametrize("sidecar", [{"endpoint": "https://foreign.example.test"}, {"headers": {"X-API-Key": "foreign"}}, {"card": {}}, {"amount": 42}, {"capture": True}, {"path": "/payments"}, {"status": "closed"}])
def test_unknown_sidecars_cannot_turn_reads_into_financial_or_status_changes(sidecar):
    with pytest.raises(ValueError, match="configuration is invalid"):
        factory("get_company", sidecar)


@pytest.mark.asyncio
async def test_static_freshen_and_principal_company_parent_role_preflights(wire):
    snapshot = await ad.AdyenNode.freshen_credential(CREDS)
    assert snapshot["credential_type"] == FAMILY and wire.calls == []
    wire.me["id"] = "FOREIGN"
    with pytest.raises(ValueError, match="active principal"):
        await factory("get_company").run({})
    assert len(wire.calls) == 1
    wire.me, wire.calls = deepcopy(ME), []
    wire.rows["merchant"]["companyId"] = "OTHER"
    with pytest.raises(ValueError, match="another company"):
        await factory("get_payment_link_status", {"merchant_id": "MERCHANT", "link_id": "LINK"}).run({})
    assert not any("paymentLinks" in r.url.path for r in wire.calls)
    wire.rows["merchant"] = deepcopy(ROWS["merchant"])
    wire.rows["store"]["merchantId"] = "OTHER"
    with pytest.raises(ValueError, match="another merchant"):
        await factory("get_store", {"merchant_id": "MERCHANT", "store_id": "STORE"}).run({})
    wire.rows["store"] = deepcopy(ROWS["store"])
    wire.me["roles"] = ["Management API - Accounts read", "Management API - Stores read"]
    with pytest.raises(ValueError, match="required Management role"):
        await factory("update_store_description", CASES[6][1]).run({})
    assert not any(r.method == "PATCH" for r in wire.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 204])
async def test_store_write_actual_200_and_empty_204_plus_independent_readback(wire, status):
    wire.patch_status = status
    result = await factory("update_store_description", CASES[6][1]).run({})
    assert result["http_status"] == status and result["acknowledged"] is True
    writes = [r for r in wire.calls if r.method == "PATCH"]
    assert len(writes) == 1 and json.loads(writes[0].content) == {"description": "private-updated-description"}
    assert wire.calls[-1].method == "GET" and result["data"]["status"] == "active"


@pytest.mark.asyncio
async def test_exact_native_transport_rejects_financial_key_and_arbitrary_payloads(wire):
    client = ad._Client(ad._Authority(CREDS))
    await client.identity()
    wire.calls.clear()
    for method, path, service, body in [("POST", "/payments", "checkout", {}), ("POST", "/me/generateClientKey", "management", {}), ("GET", "/payouts", "checkout", None), ("PATCH", "/merchants/MERCHANT/stores/STORE", "management", {"status": "closed"}), ("GET", "/companies/COMPANY", "management", {"amount": 42})]:
        with pytest.raises(ValueError, match="native|typed|write payload"):
            await client._http(method, path, service=service, body=body)
    assert wire.calls == []


@pytest.mark.asyncio
async def test_live_hosts_prefix_and_payment_merchant_guard(wire):
    live = {**CREDS, "environment": "live", "live_url_prefix": "abc123-fixture"}
    result = await factory("get_payment_link_status", {"merchant_id": "MERCHANT", "link_id": "LINK"}, live).run({})
    assert result["data"]["status"] == "completed"
    assert wire.calls[-1].url.host == "abc123-fixture-checkout-live.adyenpayments.com" and wire.calls[-1].url.path == "/checkout/v72/paymentLinks/LINK"
    for prefix in ("https://foreign.example.test", "127.0.0.1", "abc-fixture/evil", "abc-fixture:443", "abc-fixture?key=secret"):
        with pytest.raises(ValueError):
            factory("get_identity", credential={**live, "live_url_prefix": prefix})
    wire.rows["link"]["merchantAccount"] = "OTHER"
    with pytest.raises(ValueError, match="merchant or status differs"):
        await factory("get_payment_link_status", {"merchant_id": "MERCHANT", "link_id": "LINK"}).run({})


@pytest.mark.asyncio
async def test_signed_paging_scope_size_cycle_and_unfollowed_links(wire):
    def pages(request):
        if request.url.path == "/v3/companies/COMPANY/merchants":
            number = int(request.url.params["pageNumber"])
            return httpx.Response(200, json={"data": [{**ROWS["merchant"], "id": "MERCHANT-" + str(number)}], "itemsTotal": 3, "pagesTotal": 3, "_links": {"next": {"href": "http://169.254.169.254/secret"}}})
    wire.override = pages
    first = await factory("list_merchants", {"page_size": 1}).run({})
    second = await factory("list_merchants", {"page_size": 1, "page_token": first["next_page_token"]}).run({})
    assert [first["data"][0]["id"], second["data"][0]["id"]] == ["MERCHANT-1", "MERCHANT-2"]
    with pytest.raises(ValueError, match="continuation"):
        await factory("list_merchants", {"page_size": 2, "page_token": first["next_page_token"]}).run({})
    wire.override = lambda r: httpx.Response(200, json={"data": [{**ROWS["merchant"], "id": "MERCHANT-1"}], "itemsTotal": 3, "pagesTotal": 3}) if r.url.path == "/v3/companies/COMPANY/merchants" else None
    with pytest.raises(ValueError, match="repeated"):
        await factory("list_merchants", {"page_size": 1, "page_token": first["next_page_token"]}).run({})
    assert all(r.url.host != "169.254.169.254" for r in wire.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [202, 204, 302, 400, 401, 403, 404, 422, 429, 500])
async def test_status_errors_sanitized_no_retry(wire, status):
    wire.override = lambda r: httpx.Response(status, json={"error": CREDS["api_key"]})
    with pytest.raises(ad.AdyenRequestError) as error:
        await factory("get_identity").run({})
    assert CREDS["api_key"] not in str(error.value) and error.value.status == status and len(wire.calls) == 1


@pytest.mark.asyncio
async def test_private_dns_rejected_by_staging_guard(wire, monkeypatch):
    monkeypatch.setattr(ssrf, "allow_private_hosts", lambda: False)
    wire.address = "169.254.169.254"
    with pytest.raises(ValueError, match="non-public address"):
        await factory("get_identity").run({})
    assert wire.calls == []


@pytest.mark.asyncio
async def test_nested_projected_key_and_uncertain_write_no_retry(wire):
    wire.rows["company"]["name"] = CREDS["api_key"]
    with pytest.raises(ValueError, match="protected credential"):
        await factory("get_company").run({})
    wire.rows["company"] = deepcopy(ROWS["company"])
    wire.calls.clear()
    def timeout(request):
        if request.method == "PATCH":
            raise httpx.ReadTimeout("private " + CREDS["api_key"], request=request)
    wire.override = timeout
    with pytest.raises(ad.AdyenRequestError, match="outcome is unknown") as error:
        await factory("update_store_description", CASES[6][1]).run({})
    assert CREDS["api_key"] not in str(error.value) and len([r for r in wire.calls if r.method == "PATCH"]) == 1
class Pool:
    def __init__(self, row):
        self.row, self.calls = row, []
    def acquire(self):
        return self
    async def __aenter__(self):
        return self
    async def __aexit__(self, *args):
        return False
    async def fetchrow(self, sql, *args):
        self.calls.append((sql, args))
        return self.row if "FROM credentials c" in sql else None


@pytest.fixture
def current(monkeypatch):
    row = {"credential_type": FAMILY, "credential": "synthetic-encrypted", "revoked_at": None, "owner_id": USER,
        "token_version": 7, "updated_at": "2026-10-06", "metadata": {}, "approval_operations": [], "approval_revision": 1}
    crypto = MagicMock()
    crypto.decrypt_credential.return_value = deepcopy(CREDS)
    monkeypatch.setattr(credentials, "get_encryption", lambda: crypto)
    monkeypatch.setattr("utils.encryption.get_encryption", lambda: crypto)
    return SimpleNamespace(row=row, pool=Pool(row), crypto=crypto)






@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["pending", "rejected"])
async def test_real_operation_lookup_and_identity_evidence_admission(wire, current, monkeypatch, status):
    from utils import credential_approval
    monkeypatch.setattr(CredentialApprovalRepo, "admit", AsyncMock(return_value={"id": ID, "status": status, "new_request": False}))
    monkeypatch.setattr(credential_approval, "get_frontend_url", lambda: "https://fixture.example.test")
    result = await run_op.run_node_operation(node_type=TYPE, operation="get_identity", arguments={}, user_id=USER, credential_id=ID, pool=current.pool)
    lookup = await run_op.run_node_lookup(node_type=TYPE, field_name="merchant_id", user_id=USER, credential_id=ID, pool=current.pool)
    assert result["executed"] is False and lookup["executed"] is False
    assert wire.calls == []


@pytest.mark.asyncio
async def test_actual_connect_and_admitted_picker(wire, current, monkeypatch):
    monkeypatch.setattr(cc, "_collect_evidence", ce.collect_evidence)
    verdict = await cc.validate_for_connect(credential_type=FAMILY, credential_data=CREDS, user_id=USER, pool=current.pool)
    assert not verdict.field_errors and verdict.evidence.reachable is True
    monkeypatch.setattr(CredentialApprovalRepo, "admit", AsyncMock(return_value=None))
    result = await run_op.run_node_lookup(node_type=TYPE, field_name="merchant_id", user_id=USER, credential_id=ID, pool=current.pool)
    assert result["options"] == [{"label": "Fixture Merchant", "value": "MERCHANT"}]


@pytest.mark.asyncio
async def test_actual_socket_picker_on_staging(wire, current, monkeypatch):
    status = None
    from wss.handlers import workflow_handler as wh
    from wss.receiver.client_events import WorkflowNodeLoadOptionsRequest
    from utils import credential_approval
    monkeypatch.setattr("utils.database_pool.get_native_pool", lambda: current.pool)
    monkeypatch.setattr(wh, "get_user_org_context", AsyncMock(return_value=None))
    monkeypatch.setattr(wh, "get_encryption", lambda: current.crypto)
    monkeypatch.setattr(credential_approval, "get_frontend_url", lambda: "https://fixture.example.test")
    monkeypatch.setattr(CredentialApprovalRepo, "admit", AsyncMock(return_value=None if status is None else {"id": ID, "status": status, "new_request": False}))
    sent = AsyncMock()
    monkeypatch.setattr(wh, "send_event", sent)
    handler = wh.WorkflowHandler.__new__(wh.WorkflowHandler)
    handler.sio = SimpleNamespace(get_session=AsyncMock(return_value={"user_id": USER}))
    await handler.load_node_options("fixture-sid", WorkflowNodeLoadOptionsRequest(request_id="adyen-fixture", node_type=TYPE, field_name="merchant_id", credential_id=ID))
    data = sent.call_args.args[2].data
    assert data["success"] is (status is None)
    if status is None:
        assert data["options"][0]["value"] == "MERCHANT"
    else:
        assert wire.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("tag", [None, 42, [], {}, "foreign"])
async def test_saved_original_bad_tag_and_freshen_lookup_before_provider(wire, current, tag):
    for method in (ad.AdyenNode.freshen_credential, ad.AdyenNode.validate_credential_access):
        with pytest.raises(ValueError, match="native Adyen"):
            await method({**CREDS, "credential_type": tag})
    with pytest.raises(ValueError, match="native Adyen"):
        await ad.AdyenNode.load_field_options("store_id", {**CREDS, "credential_type": tag})
    assert wire.calls == []




@pytest.mark.asyncio
async def test_admitted_child_picker_exact_merchant_readback_and_missing_parent(wire, current, monkeypatch):
    monkeypatch.setattr(CredentialApprovalRepo, "admit", AsyncMock(return_value=None))
    result = await run_op.run_node_lookup(node_type=TYPE, field_name="store_id", context={"merchant_id": "MERCHANT"}, user_id=USER, credential_id=ID, pool=current.pool)
    assert result["options"] == [{"value": "STORE", "label": "fixture_store"}]
    wire.calls.clear()
    with pytest.raises(ValueError, match="resource ID"):
        await run_op.run_node_lookup(node_type=TYPE, field_name="store_id", context={}, user_id=USER, credential_id=ID, pool=current.pool)
    assert wire.calls == []




@pytest.mark.asyncio
@pytest.mark.parametrize("change", [{"active": False}, {"roles": None}, {"roles": [None]}, {"id": "FOREIGN"}])
async def test_identity_and_observed_role_contract_fails_before_company(wire, change):
    wire.me.update(change)
    with pytest.raises(ValueError, match="active principal"):
        await factory("get_identity").run({})
    assert len(wire.calls) == 1


@pytest.mark.asyncio
async def test_known_empty_observed_roles_do_not_claim_company_privilege(wire):
    wire.me["roles"] = []
    with pytest.raises(ValueError, match="required Management role"):
        await factory("get_identity").run({})
    assert len(wire.calls) == 1

@pytest.mark.asyncio
@pytest.mark.parametrize("href", ["https://foreign.example.test/v3/companies/COMPANY", "https://management-test.adyen.com/v3/companies/OTHER", "http://management-test.adyen.com/v3/companies/COMPANY"])
async def test_returned_principal_company_link_cannot_override_binding(wire, href):
    wire.override = lambda request: httpx.Response(200, json={**ME, "_links": {"company": {"href": href}}}) if request.url.path == "/v3/me" else None
    with pytest.raises(ValueError, match="company link differs"):
        await factory("get_identity").run({})
    assert len(wire.calls) == 1


@pytest.mark.asyncio
async def test_documented_legacy_link_is_identity_metadata_never_a_transport_route(wire):
    wire.override = lambda request: httpx.Response(200, json={**ME, "_links": {"company": {"href": "https://management-test.adyen.com/v1/companies/COMPANY"}}}) if request.url.path == "/v3/me" else None
    assert (await factory("get_identity").run({}))["company_id"] == "COMPANY"
    assert all(request.url.path.startswith("/v3/") for request in wire.calls)


def documented(name):
    from pathlib import Path
    return json.loads((Path(__file__).parent / 'fixtures' / 'adyen' / (name + '.json')).read_text())['body']


def test_documented_merchant_parent_comes_from_company_collection():
    credential = ad._credential({**CREDS, 'company_id': 'YOUR_COMPANY_ACCOUNT'})
    row = documented('merchant')
    assert 'companyId' not in row
    assert ad._project('merchant', row, credential, credential.company_id)['company_id'] == credential.company_id
    with pytest.raises(ValueError, match='another company'):
        ad._project('merchant', row, credential, 'OTHER')


@pytest.mark.asyncio
async def test_documented_single_store_without_id_is_bound_to_requested_route(wire):
    row = documented('store')
    assert 'id' not in row
    identifier = row['_links']['self']['href'].rsplit('/', 1)[1]
    client = ad._Client(ad._Authority(CREDS))
    await client.identity()
    wire.override = lambda request: httpx.Response(200, json=row)
    _, result = await client.one('store', identifier, row['merchantId'])
    assert result['id'] == identifier and result['merchant_id'] == row['merchantId']
    with pytest.raises(ValueError, match='self link changed identity'):
        await client.one('store', 'OTHER', row['merchantId'])


@pytest.mark.asyncio
async def test_documented_merchant_membership_checked_before_single_read(wire):
    collection = documented('merchants')
    client = ad._Client(ad._Authority({**CREDS, 'company_id': 'YOUR_COMPANY_ACCOUNT'}))
    client.company = {'id': 'YOUR_COMPANY_ACCOUNT'}
    client.roles = set(ad.ACCOUNT_READ)
    wire.override = lambda request: httpx.Response(200, json=collection)
    member = collection['data'][0]['id']
    # The published collection is page 1 of 3 with pageSize=10.
    page = await client.page('merchant', 10)
    assert page['data'][0]['id'] == member and page['next_page_token']
    # An unrelated company cannot be inferred from an unscoped merchant read.
    wire.rows['merchant'].pop('companyId')
    wire.override = lambda request: httpx.Response(200, json={"data": [wire.rows["merchant"]], "itemsTotal": 1, "pagesTotal": 1})
    with pytest.raises(ValueError, match='not in the authorized company'):
        await client.one('merchant', 'OTHER')


@pytest.mark.asyncio
async def test_saved_credential_binding_and_revocation_through_staging_resolver(wire, current, monkeypatch):
    monkeypatch.setattr(CredentialApprovalRepo, "admit", AsyncMock(return_value=None))
    node = factory("get_identity", current=current)
    # The response changes authority after admission and before company access.
    def change(request):
        if request.url.path == "/v3/me":
            current.crypto.decrypt_credential.return_value = {**CREDS, "api_key": "synthetic-replacement-key-canary"}
            return httpx.Response(200, json=ME)
    wire.override = change
    with pytest.raises(ValueError, match="binding changed"):
        await node.run({})
    assert len(wire.calls) == 1
    wire.calls.clear()
    wire.override = None
    current.crypto.decrypt_credential.return_value = {**CREDS, "api_key": "synthetic-replacement-key-canary"}
    with pytest.raises(ValueError, match="binding changed"):
        await factory("get_identity", current=current).run({})
    current.crypto.decrypt_credential.return_value = deepcopy(CREDS)
    current.row["revoked_at"] = "revoked"
    with pytest.raises(ValueError, match="unavailable or revoked"):
        await factory("get_identity", current=current).run({})
    assert wire.calls == []
