"""Native factory and actual guarded-request fixtures; not collected or run."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import logging
from urllib.parse import parse_qs
from unittest.mock import AsyncMock

import httpx
import pytest
from nodes import zuora_node as F
from nodes.core.registry import NodeFactory
from utils import ssrf

USER = "00000000-0000-4000-8000-000000000001"
ACCOUNT, CONTACT, PRODUCT, PLAN, SUBSCRIPTION, INVOICE = [f"{n:032x}" for n in range(10, 16)]
AUTH = {"credential_type": F.FAMILY, "environment": "us2_sandbox", "client_id": "00000000-0000-4000-8000-000000000042", "client_secret": "synthetic-client-secret-42"}
SCOPE = "entity.00000000-0000-4000-8000-000000000002 service.genesis.read service.genesis.write tenant.42 user.00000000000040008000000000000003"
TOKEN = {"access_token": "synthetic-access-token-42", "expires_in": 3598, "token_type": "bearer", "scope": SCOPE}


def cached():
    scope, tenant, user, entities = F.scope_claims(SCOPE)
    return F.credential({**AUTH, "access_token": TOKEN["access_token"], "expires_at": (datetime.now(timezone.utc)+timedelta(minutes=30)).isoformat(), "scope": scope, "token_type": "bearer", "tenant_id": tenant, "api_user_id": user, "entity_ids": entities})


class World:
    def __init__(self):
        self.calls, self.override, self.after_request, self.next_page = [], None, None, None
        self.token = deepcopy(TOKEN)
        self.data = {
            "accounts": {ACCOUNT: {"id": ACCOUNT, "name": "Fixture Account", "accountNumber": "A00042", "currency": "USD", "notes": "Before", "billTo": {"email": "PRIVATE-SENTINEL"}, "balance": 123}},
            "contacts": {CONTACT: {"id": CONTACT, "accountId": ACCOUNT, "firstName": "Fixture", "lastName": "Contact", "email": "PRIVATE-SENTINEL", "address1": "PRIVATE-SENTINEL"}},
            "products": {PRODUCT: {"id": PRODUCT, "name": "Fixture Catalog", "sKU": "SKU42", "description": "Before", "effectiveStartDate": "2026-01-01", "effectiveEndDate": "2027-01-01", "productRatePlans": [{"price": 123}]}},
            "product-rate-plans": {PLAN: {"id": PLAN, "productId": PRODUCT, "name": "Fixture Plan", "productRatePlanCharges": [{"price": 123}]}},
            "subscriptions": {SUBSCRIPTION: {"id": SUBSCRIPTION, "accountId": ACCOUNT, "name": "S42", "status": "Active", "version": 1, "isLatestVersion": True, "notes": "Before", "mrr": 123}},
            "invoices": {INVOICE: {"id": INVOICE, "accountId": ACCOUNT, "invoiceNumber": "INV42", "status": "Draft", "currency": "USD", "invoiceDate": "2026-10-06", "amount": 123, "invoiceFiles": "PRIVATE-SENTINEL"}},
        }

    async def respond(self, request):
        self.calls.append(request)
        assert request.url.host in {httpx.URL(v).host for v in F.ORIGINS.values()} and request.url.scheme == "https"
        assert not any(k in request.url.params for k in ("client_secret", "access_token", "scope", "expand[]", "filter[]"))
        logging.getLogger("httpx").warning("%s %s", request.url, request.headers)
        if self.after_request: self.after_request(request)
        if self.override:
            result = self.override(request)
            if result is not None: return result
        if request.url.path == "/oauth/token":
            assert request.method == "POST" and request.headers["Content-Type"].startswith("application/x-www-form-urlencoded")
            assert "Authorization" not in request.headers and "Zuora-Version" not in request.headers
            assert parse_qs(request.content.decode()) == {"grant_type": ["client_credentials"], "client_id": [AUTH["client_id"]], "client_secret": [AUTH["client_secret"]]}
            return httpx.Response(200, json=deepcopy(self.token))
        assert request.headers["Authorization"] == "Bearer "+TOKEN["access_token"]
        assert request.headers["Zuora-Version"] == F.VERSION
        path = request.url.path
        if path.startswith("/object-query/"):
            segments = path.split("/")[2:]; kind = segments[0]
            assert request.method == "GET" and set(request.url.params.get_list("fields[]")) <= set(F.FIELDS[kind]) | {"notes"}
            if len(segments) == 2: payload = deepcopy(self.data[kind][segments[1]])
            else:
                payload = {"data": deepcopy(list(self.data[kind].values())[:int(request.url.params["pageSize"])])}
                if self.next_page: payload["nextPage"] = self.next_page
            return httpx.Response(200, json=payload)
        kind, rid = path.split("/")[-2:]
        if kind == "product":
            row = self.data["products"][rid]
            if request.method == "GET":
                assert request.url.params["fields"] == ",".join(F.PRODUCT_FIELDS)
                return httpx.Response(200, json={"Id": rid, "Name": row["name"], "SKU": row["sKU"], "Description": row["description"], "EffectiveStartDate": row["effectiveStartDate"], "EffectiveEndDate": row["effectiveEndDate"], "Private": "PRIVATE-SENTINEL"})
            assert request.method == "PUT" and request.url.params["rejectUnknownFields"] == "true"
            body = json.loads(request.content); assert set(body) == {"Description"}
            row["description"] = body["Description"]
            return httpx.Response(200, json={"Id": rid, "Success": True})
        assert request.method == "PUT" and kind in {"accounts", "contacts", "subscriptions"}
        body = json.loads(request.content)
        if kind == "accounts": assert set(body) <= {"name", "notes"}
        elif kind == "contacts": assert set(body) == {"firstName", "lastName"}
        else: assert set(body) == {"notes", "collect", "runBilling"} and body["collect"] is False and body["runBilling"] is False
        self.data[kind][rid].update({k: v for k, v in body.items() if k not in {"collect", "runBilling"}})
        return httpx.Response(200, json={"success": True, **({"accountId": ACCOUNT} if kind == "contacts" else {"subscriptionId": SUBSCRIPTION} if kind == "subscriptions" else {})})


@pytest.fixture
def ensure_native_db_pool(): yield


@pytest.fixture
def world(monkeypatch):
    value = World()
    value.dns = AsyncMock(return_value=["8.8.8.8"])
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", value.dns)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return ssrf.guarded_async_client(transport=httpx.MockTransport(value.respond), **kwargs)
    monkeypatch.setattr(F, "guarded_async_client", client)
    return value


def node(op, **values):
    return NodeFactory.create_node(node_id="synthetic-zuora", node_type="automation-zuora", user_id=USER, sio=None, sid=None,
        node_data={"config": {"operation": op, **values}, "credentials": deepcopy(AUTH)})


CASES = [("check_connection", {}), ("list_accounts", {}), ("get_account", {"account_id": ACCOUNT}),
    ("list_contacts", {"account_id": ACCOUNT}), ("get_contact", {"account_id": ACCOUNT, "contact_id": CONTACT}),
    ("list_products", {}), ("get_product", {"product_id": PRODUCT}),
    ("list_product_rate_plans", {"product_id": PRODUCT}), ("get_product_rate_plan", {"product_id": PRODUCT, "product_rate_plan_id": PLAN}),
    ("list_subscriptions", {"account_id": ACCOUNT}), ("get_subscription", {"account_id": ACCOUNT, "subscription_id": SUBSCRIPTION}),
    ("list_invoices", {"account_id": ACCOUNT}), ("get_invoice", {"account_id": ACCOUNT, "invoice_id": INVOICE}),
    ("update_account_metadata", {"account_id": ACCOUNT, "name": "Changed", "notes": "Internal"}),
    ("update_contact_name", {"account_id": ACCOUNT, "contact_id": CONTACT, "first_name": "Changed", "last_name": "Name"}),
    ("update_product_description", {"product_id": PRODUCT, "description": "Changed"}),
    ("update_subscription_notes", {"account_id": ACCOUNT, "subscription_id": SUBSCRIPTION, "notes": "Internal"})]


@pytest.mark.asyncio
@pytest.mark.parametrize("op,values", CASES)
async def test_actual_factory_all_17_ops_and_minimal_projection(world, caplog, op, values):
    with caplog.at_level(logging.WARNING): result = await node(op, **values, arbitrary_body={"collect": True}, _settings={"send": True}).execute({})
    assert result and "PRIVATE-SENTINEL" not in json.dumps(result) and AUTH["client_secret"] not in caplog.text and TOKEN["access_token"] not in caplog.text
    assert world.calls[0].url.path == "/oauth/token" and all(call.kwargs.get("permit_non_public") is not True for call in world.dns.call_args_list)
    if op.startswith("update_"): assert result["readback_verified"] is True and world.calls[-1].method == "GET" and sum(r.method == "PUT" for r in world.calls) == 1
    if op == "check_connection": assert result["reachable"] is True and result["identity_verified"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [{"scope": None}, {"scope": "service.genesis.read"}, {"scope": SCOPE+" tenant.99"}, {"scope": SCOPE+"\nPRIVATE-SENTINEL"}, {"token_type": "Basic"}, {"expires_in": True}, {"expires_in": 0}, {"access_token": "https://private.invalid/token"}])
async def test_actual_token_contract_refuses_before_resource_transport(world, bad):
    world.token.update(bad)
    with pytest.raises(RuntimeError) as error: await node("check_connection").execute({})
    assert len(world.calls) == 1 and "PRIVATE-SENTINEL" not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [202, 302, 401, 403, 404, 429, 503])
async def test_native_http_status_never_returns_raw_provider_body(world, status):
    world.override = lambda r: None if r.url.path == "/oauth/token" else httpx.Response(status, json={"reasons": [{"message": "PRIVATE-SENTINEL"}]})
    with pytest.raises(F.ZuoraHTTPError) as error: await node("list_accounts").execute({})
    assert error.value.status_code == status and "PRIVATE-SENTINEL" not in str(error.value)


@pytest.mark.asyncio
async def test_http200_business_refusal_stops_independent_readback(world):
    world.override = lambda r: httpx.Response(200, json={"success": False, "reasons": [{"message": "PRIVATE-SENTINEL"}]}) if r.method == "PUT" else None
    with pytest.raises(RuntimeError): await node("update_account_metadata", account_id=ACCOUNT, name="Changed").execute({})
    assert world.calls[-1].method == "PUT"


@pytest.mark.asyncio
async def test_parent_witness_refuses_before_contact_write(world):
    world.data["contacts"][CONTACT]["accountId"] = PRODUCT
    with pytest.raises(RuntimeError): await node("update_contact_name", account_id=ACCOUNT, contact_id=CONTACT, first_name="Changed", last_name="Name").execute({})
    assert all(r.method != "PUT" for r in world.calls)


@pytest.mark.asyncio
async def test_cursor_and_local_parent_page_are_honest_and_not_followed_urls(world):
    world.next_page = "opaque-cursor-42"
    other = "f"*32
    world.data["contacts"][other] = {"id": other, "accountId": PRODUCT, "firstName": "Off Parent"}
    result = await node("list_contacts", account_id=ACCOUNT).execute({})
    assert [r["id"] for r in result["records"]] == [CONTACT] and result["parent_filter"] == "local_page"
    with pytest.raises(RuntimeError, match="repeated Object Query cursor"):
        await node("list_contacts", account_id=ACCOUNT, cursor=result["next_page_token"]).execute({})
    world.next_page = None
    last_page = await node("list_contacts", account_id=ACCOUNT, cursor=result["next_page_token"]).execute({})
    assert world.calls[-1].url.params["cursor"] == "opaque-cursor-42"
    assert last_page["next_page_token"] is None
    world.next_page = "https://private.invalid/?access_token=PRIVATE-SENTINEL"
    with pytest.raises(RuntimeError): await node("list_accounts").execute({})


@pytest.mark.asyncio
async def test_metadata_write_mismatch_is_not_verified_or_automatically_retried(world):
    def mismatch(request):
        if request.method == "GET" and any(r.method == "PUT" for r in world.calls):
            return httpx.Response(200, json={"id": ACCOUNT, "name": "Old"})
    world.override = mismatch
    with pytest.raises(RuntimeError, match="readback"): await node("update_account_metadata", account_id=ACCOUNT, name="Changed").execute({})
    assert sum(r.method == "PUT" for r in world.calls) == 1


@pytest.mark.parametrize("bad", [True, 9007199254740993, "A00042", "https://private.invalid", "../contact", "{{vars.id}}"])
def test_actual_config_requires_string_record_ids(bad):
    with pytest.raises(ValueError): node("get_account", account_id=bad)
