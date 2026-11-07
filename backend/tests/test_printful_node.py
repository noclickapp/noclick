"""Unrun native Printful factory, transport, parent and connect regressions.

Only HTTP/storage boundaries are synthetic. No account, token mint, media or
provider mutation is authorized by preparing this fixture source.
"""
import json
from copy import deepcopy

import httpx
import pytest
from pydantic import TypeAdapter, ValidationError

from nodes import printful_node as native
from nodes.core.registry import NodeFactory
from nodes.core.run_op import run_node_operation, run_node_lookup
from nodes.core.connection_evidence import collect_evidence
from nodes.core.credential_connect import validate_for_connect

USER = "11111111-1111-4111-8111-111111111111"
TYPE = "automation-printful"
PRIVATE = {"credential_type": "printful_private_token", "private_token": "PFT_fixture_only", "access_level": "account", "store_id": 10}
OAUTH = {"credential_type": "printful_oauth_access_token", "access_token": "PFO_fixture_only", "token_type": "bearer", "expires_at": "4102444800", "store_id": 10}
SCOPES = ["stores_list", "sync_products", "orders"]
STORE = {"id": 10, "name": "Owned fixture store", "type": "native"}
PRODUCT = {"id": 13, "name": "Owned fixture product", "variants": 1, "synced": 1, "thumbnail_url": "https://media.example.invalid/private"}
VARIANT = {"id": 71, "sync_product_id": 13, "name": "Fixture variant", "synced": True, "variant_id": 100, "files": [{"url": "private-design"}]}
ORDER = {"id": 50, "store": 10, "status": "draft", "created": 1700000000, "updated": 1700000001,
         "external_id": "fixture-reference", "recipient": {"name": "private recipient", "email": "private@example.invalid"}, "costs": {"total": "999"}}
DRAFT = {"external_id": "fixture-reference", "recipient": {"name": "Owned Fixture", "address1": "1 Fixture Road", "city": "Fixture", "state_code": "CA", "country_code": "US", "zip": "00000"},
         "items": [{"sync_product_id": 13, "sync_variant_id": 71, "quantity": 1}]}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    # Override the repository's real database fixture for this offline source suite.
    yield


def wire(monkeypatch, routes=None, on_request=None):
    requests, replies = [], deepcopy(routes or {})
    def handle(request):
        assert request.url.scheme == "https" and request.url.host == "api.printful.com"
        assert request.url.port in (None, 443)
        assert request.headers["authorization"].startswith("Bearer ")
        assert request.url.path not in {"/orders/50/confirm", "/oauth/token", "/shipping/rates"}
        requests.append(request)
        if on_request:
            on_request(request)
        key = (request.method, request.url.path)
        if key in replies:
            value = replies[key]
            if isinstance(value, list):
                value = value.pop(0)
            if isinstance(value, httpx.Response):
                return value
            return httpx.Response(200, json={"code": 200, **value})
        if request.url.path == "/oauth/scopes":
            return httpx.Response(200, json={"code": 200, "result": {"scopes": [{"scope": s} for s in SCOPES]}})
        if request.url.path == "/stores/10":
            return httpx.Response(200, json={"code": 200, "result": STORE})
        raise AssertionError(f"Unexpected native route: {key}")
    def client(**kwargs):
        assert kwargs == {"timeout": 20, "follow_redirects": False, "trust_env": False}
        return httpx.AsyncClient(transport=httpx.MockTransport(handle), timeout=20, follow_redirects=False, trust_env=False)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


async def run(operation, arguments=None, credential=None):
    return await run_node_operation(node_type=TYPE, operation=operation, arguments=arguments or {}, user_id=USER,
                                    credential_data=deepcopy(credential or PRIVATE))


@pytest.mark.asyncio
@pytest.mark.parametrize("credential", [PRIVATE, OAUTH])
async def test_execute_uses_validated_config_credentials_without_node_data(monkeypatch, credential):
    requests = wire(monkeypatch)
    config = native.PrintfulNodeConfig.model_validate({"config": {"operation": "get_store"}, "credentials": credential})
    node = native.PrintfulNode(node_id="configured", node_type=TYPE, node_data={}, config=config, user_id=USER)
    result = await node.execute({})
    assert result["success"] and result["data"]["store"]["id"] == credential["store_id"]
    assert [r.url.path for r in requests] == ["/oauth/scopes", "/stores/10"]
    token = credential.get("private_token") or credential["access_token"]
    assert all(r.headers["authorization"] == f"Bearer {token}" for r in requests)


@pytest.mark.asyncio
async def test_execute_does_not_replace_explicitly_missing_runtime_credentials(monkeypatch):
    requests = wire(monkeypatch)
    config = native.PrintfulNodeConfig.model_validate({"config": {"operation": "get_store"}, "credentials": PRIVATE})
    node = native.PrintfulNode(node_id="removed", node_type=TYPE, node_data={"credentials": None}, config=config, user_id=USER)
    with pytest.raises(ValueError, match="credential family"):
        await node.execute({})
    assert requests == []


def test_native_factory_and_closed_declaration():
    node = NodeFactory.create_node(node_id="fixture", node_type=TYPE, node_data={"config": {"operation": "get_store", "label": "saved metadata"}, "credentials": PRIVATE}, user_id=USER)
    assert isinstance(node, native.PrintfulNode)
    assert node.config.config.operation == "get_store"
    assert len(native.OPERATIONS) == 20
    assert not {"confirm_order", "cancel_order", "create_webhook", "upload_file", "estimate_costs"} & native.OPERATIONS
    with pytest.raises(ValueError):
        NodeFactory.create_node(node_id="foreign", node_type=TYPE, node_data={"config": {"operation": "get_store"}, "credentials": {**PRIVATE, "credential_type": "printify_api_key"}}, user_id=USER)


@pytest.mark.parametrize("patch", [{"refresh_token": ""}, {"base_url": "https://other.invalid"}, {"access_token": "other"}, {"store_id": False}, {"expires_at": "0"}, {"private_token": "Bearer fixture"}])
def test_invalid_private_grants_fail_before_transport(patch):
    with pytest.raises(ValueError):
        native._credential({**PRIVATE, **patch})


@pytest.mark.parametrize("patch", [{"token_type": None}, {"token_type": "Basic"}, {"access_level": "account"}, {"expires_at": "1"}, {"expires_at": False}])
def test_manual_oauth_does_not_invent_family_type_expiry_or_refresh(patch):
    with pytest.raises(ValueError):
        native._credential({**OAUTH, **patch})


def test_validation_errors_do_not_print_tokens_or_recipient_inputs():
    with pytest.raises(ValidationError) as error:
        native.PrintfulOAuthAccessTokenCredential.model_validate({**OAUTH, "store_id": None})
    assert OAUTH["access_token"] not in str(error.value)
    with pytest.raises(ValidationError) as error:
        native.DraftRecipient.model_validate({**DRAFT["recipient"], "unexpected": "private fixture data"})
    assert "private fixture data" not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("credential,expected_header", [(PRIVATE, "10"), ({**PRIVATE, "access_level": "store"}, None), (OAUTH, None)])
async def test_actual_bearer_family_and_store_header(monkeypatch, credential, expected_header):
    requests = wire(monkeypatch, {("GET", "/orders/50"): {"result": ORDER}})
    result = await run("get_order", {"order_id": 50, "store_id": 999, "confirm": True}, credential)
    assert result["success"] and result["store_id"] == 10
    assert requests[-1].headers.get("x-pf-store-id") == expected_header
    assert requests[-1].headers.get("x-postscript-shop-token") is None
    text = json.dumps(result)
    assert all(s not in text for s in ("private recipient", "private@example.invalid", "costs", "999", "external_id"))


@pytest.mark.asyncio
async def test_real_connect_collector_uses_bound_store_identity(monkeypatch):
    from nodes.core import credential_connect
    monkeypatch.setattr(credential_connect, "_collect_evidence", collect_evidence)
    requests = wire(monkeypatch)
    verdict = await validate_for_connect(credential_type=PRIVATE["credential_type"], credential_data=PRIVATE, user_id=USER)
    assert verdict.ok and verdict.evidence.reachable is True
    assert verdict.evidence.account_label == STORE["name"] or STORE["name"] in [s.label for s in verdict.evidence.samples]
    assert all(r.method == "GET" for r in requests)


@pytest.mark.asyncio
@pytest.mark.parametrize("response,expected", [(httpx.Response(401, json={"code": 401, "result": "Invalid token"}), False),
    (httpx.Response(429, json={"code": 429, "result": "slow down"}), None), (httpx.Response(503, text="temporary"), None),
    (httpx.Response(200, json={}), None), (httpx.Response(204), None)])
async def test_real_collector_never_proves_empty_or_unsupported_contract(monkeypatch, response, expected):
    requests = wire(monkeypatch, {("GET", "/oauth/scopes"): response})
    evidence = await collect_evidence(node_type=TYPE, user_id=USER, credential_data=PRIVATE)
    assert evidence.reachable is expected
    assert not evidence.samples and len(requests) <= 2  # shared identity fallback may retry the distinct probe, not the transport.


@pytest.mark.asyncio
async def test_verified_scope_alternatives_do_not_grant_write_from_read(monkeypatch):
    routes = {("GET", "/oauth/scopes"): {"result": {"scopes": [{"scope": s} for s in ("stores_list", "orders/read")]}}}
    requests = wire(monkeypatch, routes)
    result = await run("update_draft_reference", {"order_id": 50, "external_id": "new", "allow_writes": True})
    assert result["success"] is False and result["status_code"] == 403
    assert [r.url.path for r in requests] == ["/oauth/scopes"]


@pytest.mark.asyncio
async def test_pagination_privacy_and_real_dependent_picker(monkeypatch):
    requests = wire(monkeypatch, {("GET", "/orders"): {"result": [ORDER], "paging": {"offset": 0, "limit": 1, "total": 2}},
        ("GET", "/products/13"): {"result": {"product": {"id": 13, "title": "Fixture"}, "variants": [{"id": 100, "product_id": 13, "name": "Small", "image": "private-media"}]}}})
    result = await run("list_orders", {"limit": 1})
    assert result["data"]["next_page_token"] == "1"
    options = await native.PrintfulNode.load_field_options("catalog_variant_id", PRIVATE, context={"catalog_product_id": 13})
    assert options == {"options": [{"value": "100", "label": "Small"}], "next_page_token": None}
    with pytest.raises(ValueError, match="parent"):
        await native.PrintfulNode.load_field_options("catalog_variant_id", PRIVATE, {})
    assert len(requests) == 5


@pytest.mark.asyncio
@pytest.mark.parametrize("wrong_parent", [99, None])
async def test_variant_parent_refusal_uses_actual_factory(monkeypatch, wrong_parent):
    wire(monkeypatch, {("GET", "/products/variant/100"): {"result": {"product": {"id": 13}, "variant": {"id": 100, "product_id": wrong_parent}}}})
    result = await run("get_catalog_variant", {"catalog_product_id": 13, "catalog_variant_id": 100})
    assert result["success"] is False


@pytest.mark.asyncio
async def test_categories_and_manual_update_use_actual_bare_shapes(monkeypatch):
    new = {**PRODUCT, "name": "Renamed fixture"}
    requests = wire(monkeypatch, {("GET", "/categories"): {"result": [{"id": 24, "title": "T-shirts", "image_url": "private-media"}]},
        ("GET", "/store/products/13"): [{"result": {"sync_product": PRODUCT, "sync_variants": [VARIANT]}}, {"result": {"sync_product": new, "sync_variants": [VARIANT]}}],
        ("PUT", "/store/products/13"): {"result": new}})
    result = await run("list_catalog_categories")
    assert result["data"]["items"] == [{"id": 24, "title": "T-shirts"}]
    result = await run("update_manual_product_name", {"manual_product_id": 13, "name": "Renamed fixture", "allow_writes": True})
    assert result["success"] and result["data"]["persisted_readback_verified"] is True
    put = next(r for r in requests if r.method == "PUT")
    assert json.loads(put.content) == {"sync_product": {"name": "Renamed fixture"}}


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,args", [("create_draft_order", DRAFT), ("update_draft_reference", {"order_id": 50, "external_id": "new"}),
                                          ("update_manual_product_name", {"manual_product_id": 13, "name": "new"})])
async def test_all_write_defaults_refuse_without_any_request(monkeypatch, operation, args):
    requests = wire(monkeypatch)
    result = await run(operation, args)
    assert result["success"] is False and not result["mutation_outcome_unknown"] and requests == []


@pytest.mark.asyncio
async def test_draft_create_is_unconfirmed_closed_and_independently_read_back(monkeypatch):
    requests = wire(monkeypatch, {("GET", "/store/products/13"): {"result": {"sync_product": PRODUCT, "sync_variants": [VARIANT]}},
        ("POST", "/orders"): {"result": ORDER}, ("GET", "/orders/50"): {"result": ORDER}})
    result = await run("create_draft_order", {**DRAFT, "allow_writes": True, "confirm": True, "update_existing": True})
    assert result["success"] and result["data"]["order"]["status"] == "draft"
    post = next(r for r in requests if r.method == "POST")
    assert dict(post.url.params) == {"confirm": "false", "update_existing": "false"}
    assert json.loads(post.content)["items"] == [{"sync_variant_id": 71, "quantity": 1}]
    assert result["data"]["persisted_readback_verified"] is True
    assert "recipient" not in json.dumps(result)


@pytest.mark.asyncio
async def test_non_draft_and_mutation_readback_race_are_not_retried(monkeypatch):
    requests = wire(monkeypatch, {("GET", "/orders/50"): {"result": {**ORDER, "status": "pending"}}})
    result = await run("update_draft_reference", {"order_id": 50, "external_id": "new", "allow_writes": True})
    assert not result["success"] and not any(r.method != "GET" for r in requests)
    requests = wire(monkeypatch, {("GET", "/orders/50"): [{"result": ORDER}, {"result": {**ORDER, "status": "pending"}}],
        ("PUT", "/orders/50"): {"result": {**ORDER, "external_id": "new"}}})
    result = await run("update_draft_reference", {"order_id": 50, "external_id": "new", "allow_writes": True})
    assert not result["success"] and result["mutation_outcome_unknown"] and not result["retry_attempted"]
    assert len([r for r in requests if r.method == "PUT"]) == 1
