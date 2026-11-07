"""Mirakl native contracts and staging authority/connect/socket seams.

Provider/DNS and storage/encryption boundaries are synthetic. Native factory,
dispatcher, repositories, admission and actual socket routing remain in path.
"""
from copy import deepcopy
from datetime import datetime, timezone
import ipaddress
import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID
import httpx
import pytest
from nodes import mirakl_node as native
from nodes.core.connection_evidence import collect_evidence
from nodes.core.credential_connect import validate_for_connect
from nodes.core.registry import NODE_REGISTRY, NodeFactory
from nodes.core.run_op import run_node_operation, run_node_lookup

NODE, FAMILY = native.NODE_TYPE, "mirakl_mas_token"
CID, USER, ORG, OWNER, WORKFLOW = (str(UUID(int=i)) for i in (42, 1, 3, 2, 4))
UPDATED = datetime(2026, 10, 6, tzinfo=timezone.utc)
CREDS = {"credential_type": FAMILY, "access_token": "offline-mirakl-fixture-42",
    "marketplace_url": "https://marketplace.example.test", "marketplace_id": "fixture-marketplace",
    "role": "seller", "shop_id": 17}
OPS = ["get_access_scope","get_shop","list_categories","list_product_attributes","list_channels","list_currencies","list_locales","list_offer_states","get_values_list","get_products","list_shop_offers","get_offer","list_orders","create_offer","replace_offer","delete_offer","get_offer_import"]
OPS = set(OPS)
@pytest.fixture
def ensure_native_db_pool():
    yield
@pytest.fixture
def provider(monkeypatch):
    from utils import ssrf
    state = SimpleNamespace(requests=[], status=None, raw=None, media=None, target=None, target_method=None,
        timeout=False, after_response=None, empty=False, private_dns=False, existing=True)
    original_dns, original_client = ssrf._resolve_host_addresses, ssrf.guarded_async_client
    async def public_dns(host, port, **kwargs):
        assert kwargs.get("permit_non_public", False) is False
        try:
            ipaddress.ip_address(host)
        except ValueError:
            assert host == "marketplace.example.test"
            if state.private_dns:
                raise ssrf.SSRFError("Private DNS target")
            return ["93.184.216.34"]
        return await original_dns(host, port, **kwargs)
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", public_dns)
    async def respond(request):
        assert request.url.scheme == "https" and request.url.host == "marketplace.example.test"
        assert request.headers["authorization"] == "Bearer " + CREDS["access_token"]
        assert CREDS["access_token"] not in str(request.url) + request.content.decode()
        state.requests.append(request)
        if state.timeout:
            raise httpx.ReadTimeout("private " + CREDS["access_token"], request=request)
        path, status = request.url.path, 200
        headers = {"content-type": "application/json"}
        if path == "/api/account":
            assert request.url.params["shop_id"] == "17"
            raw = {"shop_id": 17, "shop_name": "Fixture shop", "shop_state": "OPEN", "model": "MARKETPLACE",
                "contact_informations": {"email": "private@example.invalid"}, "payment_details": "private"}
        elif path == "/api/hierarchies":
            raw = {"hierarchies": [{"code": "cat", "label": "Fixture category", "level": 0, "parent_code": None}]}
        elif path == "/api/products/attributes":
            assert request.url.params["hierarchy"] == "cat"
            raw = {"attributes": [{"code": "material", "unique_code": "cat-material", "label": "Material", "hierarchy_code": "cat", "type": "TEXT", "validations": "private"}]}
        elif path == "/api/channels":
            raw = {"channels": [{"code": "web", "label": "Web", "description": "private"}]}
        elif path == "/api/currencies":
            raw = {"currencies": [{"code": "EUR", "label": "Euro", "platform_default": True}]}
        elif path == "/api/locales":
            raw = {"locales": [{"code": "en", "label": "English", "platform_default": False}]}
        elif path == "/api/offers/states":
            raw = {"offer_states": [{"code": "11", "label": "New"}]}
        elif path == "/api/values_lists":
            assert request.url.params["code"] == "colors"
            raw = {"values_lists": [{"code": "colors", "label": "Colors", "values": [{"code": "red", "label": "Red"}]}]}
        elif path == "/api/products":
            assert request.url.params["product_references"] == "EAN|123"
            raw = {"products": [{"product_sku": "product-1", "product_title": "Fixture product", "product_id": "123", "product_id_type": "EAN"}]}
        elif path == "/api/products/offers":
            assert request.url.params["shop_ids"] == "17" and request.url.params["product_ids"] == "product-1"
            raw = {"products": [{"product_sku": "product-1", "offers": [{"offer_id": 22, "shop_id": 17, "shop_sku": "sku-1", "active": False, "price": 9.99}], "total_count": 1}]}
        elif path == "/api/offers/22":
            raw = {"offer_id": 22, "shop_sku": "sku-1", "product_sku": "product-1", "active": False, "quantity": 0,
                "price": 9.99, "offer_additional_fields": "private"}
        elif path == "/api/offers/imports/42":
            raw = {"import_id": 42, "status": "COMPLETE", "lines_in_error": 0, "lines_in_success": 1,
                "lines_in_pending": 0, "has_error_report": False, "error_report": "private"}
        elif path == "/api/orders":
            if "shop_ids" in request.url.params: assert request.url.params["shop_ids"] == "17"
            else: assert request.url.params["shop_id"] == "17"
            rows = [] if state.empty else [{"order_id": "order-1", "shop_id": 17, "shop_name": "Fixture shop",
                "order_state": "WAITING_ACCEPTANCE", "has_incident": False, "customer": {"email": "private@example.invalid"},
                "order_lines": "private", "transaction_number": "private", "shipping_tracking_url": "private"}]
            raw = {"orders": rows, "total_count": len(rows)}
        elif path == "/api/offers" and request.method == "POST":
            assert request.url.params["shop_id"] == "17"
            body = json.loads(request.content)
            assert set(body) == {"offers"} and len(body["offers"]) == 1
            offer = body["offers"][0]
            assert offer["shop_sku"] in ("sku-1", "new-sku") and offer["update_delete"] in ("update", "delete")
            raw, status = {"import_id": 42}, 201
            headers["location"] = "https://foreign.example.test/private-download"
        elif path == "/api/offers":
            rows = [] if state.empty or request.url.params.get("offset") == "100" or request.url.params.get("sku") == "new-sku" else [
                {"offer_id": 22, "shop_sku": "sku-1", "product_sku": "product-1", "active": False, "quantity": 0,
                    "price": 9.99, "offer_additional_fields": "private"}]
            raw = {"offers": rows, "total_count": len(rows)}
        else:
            raise AssertionError("Unexpected native route")
        content = json.dumps(raw).encode()
        if (state.target is None or state.target == path) and (state.target_method is None or state.target_method == request.method):
            if state.raw is not None: content = state.raw
            if state.media: headers["content-type"] = state.media
            if state.status: status = state.status
            if state.after_response: state.after_response()
        return httpx.Response(status, content=content, headers=headers, request=request)
    def guarded(**kwargs):
        assert kwargs == {"follow_redirects": False, "trust_env": False, "timeout": 20.0}
        return original_client(**kwargs, transport=httpx.MockTransport(respond))
    monkeypatch.setattr(native, "guarded_async_client", guarded)
    return state

async def run(op, args=None, **kwargs):
    return await run_node_operation(node_type=NODE, operation=op, arguments=args or {}, user_id=USER,
        credential_data=kwargs.pop("credential_data", CREDS), **kwargs)

CASES = [
    ("get_access_scope", {}, "GET", "/api/account"), ("get_shop", {}, "GET", "/api/account"),
    ("list_categories", {}, "GET", "/api/hierarchies"),
    ("list_product_attributes", {"hierarchy": "cat"}, "GET", "/api/products/attributes"),
    ("list_channels", {}, "GET", "/api/channels"), ("list_currencies", {}, "GET", "/api/currencies"),
    ("list_locales", {}, "GET", "/api/locales"), ("list_offer_states", {}, "GET", "/api/offers/states"),
    ("get_values_list", {"code": "colors"}, "GET", "/api/values_lists"),
    ("get_products", {"references": [{"type": "EAN", "value": "123"}]}, "GET", "/api/products"),
    ("list_shop_offers", {}, "GET", "/api/offers"),
    ("get_offer", {"offer_id": 22, "product_sku": "product-1"}, "GET", "/api/offers/22"),
    ("list_orders", {}, "GET", "/api/orders"),
    ("create_offer", {"shop_sku": "new-sku", "state_code": "11", "price": 9.99, "quantity": 0, "product_id": "123", "product_id_type": "EAN"}, "POST", "/api/offers"),
    ("replace_offer", {"offer_id": 22, "shop_sku": "sku-1", "state_code": "11", "price": 9.99, "quantity": 0, "acknowledge_field_resets": True}, "POST", "/api/offers"),
    ("delete_offer", {"offer_id": 22, "shop_sku": "sku-1"}, "POST", "/api/offers"),
    ("get_offer_import", {"import_id": 42}, "GET", "/api/offers/imports/42"),
]
@pytest.mark.asyncio
@pytest.mark.parametrize("op,args,method,path", CASES)
async def test_actual_factory_seventeen_native_contracts(provider, op, args, method, path):
    assert NODE_REGISTRY[NODE] is native.MiraklNode
    result = await run(op, args)
    assert result["status"] == "success"
    assert (provider.requests[-1].method, provider.requests[-1].url.path) == (method, path)
    assert provider.requests[0].url.path == "/api/account"
    rendered = json.dumps(result)
    for private in (CREDS["access_token"], "private", "customer", "contact_informations", '"price":', "payment_details", "transaction_number", "shipping_tracking_url"):
        assert private not in rendered
    if op in {"create_offer", "replace_offer", "delete_offer"}:
        assert result["data"]["accepted"] is True and result["data"]["completed"] is False and result["data"]["readback_verified"] is False
    if op == "get_offer":
        assert result["data"]["active"] is False and result["data"]["quantity"] == 0

@pytest.mark.asyncio
async def test_actual_manual_connect_protected_shop_and_operator_empty_evidence(provider):
    verdict = await validate_for_connect(credential_type=FAMILY, credential_data=CREDS, user_id=USER)
    assert verdict.ok and verdict.evidence.samples[0].label == "Fixture shop"
    provider.empty = True
    operator = {**CREDS, "role": "operator"}
    evidence = await collect_evidence(node_type=NODE, credential_data=operator, user_id=USER)
    assert evidence.reachable is True and evidence.samples == [] and evidence.account_label is None
    assert provider.requests[-1].url.params["shop_ids"] == "17"
    with pytest.raises(ValueError): await run("get_shop", credential_data=operator)

@pytest.mark.asyncio
async def test_paging_empty_remaining_and_parent_boundaries(provider):
    provider.empty = True
    assert (await run("list_shop_offers"))["data"]["items"] == []
    assert await native.MiraklNode.load_field_options("offer_id", CREDS, page_token="100") == {"options": [], "next_page_token": None}
    provider.empty, provider.target = False, "/api/offers"
    provider.raw = json.dumps({"offers": [{"offer_id": 22, "shop_sku": "sku-1"}], "total_count": 2}).encode()
    assert (await run("list_shop_offers", {"limit": 1}))["data"]["next_offset"] == 1
    provider.raw = b'{"offers":[],"total_count":2}'
    assert (await run("list_shop_offers"))["data"]["continuation_blocked"] is True
    provider.target, provider.raw = "/api/products/offers", json.dumps({"products": [{"product_sku": "product-1", "offers": [{"offer_id": 22, "shop_id": 99}]}]}).encode()
    with pytest.raises(ValueError): await run("get_offer", {"offer_id": 22, "product_sku": "product-1"})
    assert all(request.method == "GET" for request in provider.requests)
    provider.target, provider.raw = "/api/account", b'{"shop_id":99,"shop_name":"Foreign shop"}'
    with pytest.raises(ValueError): await run("list_orders")

@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 302, 202, 401, 403, 404, 422, 429, 500])
async def test_fixed_errors_no_secret_echo_retry_or_redirect(provider, status, caplog):
    provider.status = status
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(ValueError) as failure: await run("get_access_scope")
    assert CREDS["access_token"] not in str(failure.value) + caplog.text
    assert len(provider.requests) == 1

@pytest.mark.asyncio
async def test_media_json_token_and_private_dns_boundaries(provider):
    for raw, media in [(b'{"error":"private"}', "application/json"), (b'{"shop_id":17,"shop_id":17}', "application/json"),
        (b"NaN", "application/json"), (b"{}", "text/html"), (b"x" * (native.MAX_BYTES + 1), "application/json"),
        (json.dumps({"shop_id": 17, "token": CREDS["access_token"]}).encode(), "application/json")]:
        provider.raw, provider.media = raw, media
        with pytest.raises(ValueError): await run("get_access_scope")
    provider.raw, provider.media, provider.private_dns = None, None, True
    provider.requests.clear()
    with pytest.raises(ValueError): await run("get_access_scope")
    assert provider.requests == []

@pytest.mark.parametrize("change", [{"access_token": "Bearer pasted-token"}, {"access_token": "bad\r\nheader"},
    {"access_token": "https://foreign.invalid"}, {"marketplace_url": "https://x.test/?secret"},
    {"marketplace_url": "http://marketplace.example.test"}, {"marketplace_url": "https://127.0.0.1"},
    {"marketplace_id": "../foreign"}, {"shop_id": True}, {"credential_type": "foreign"}])
def test_strict_credentials_before_provider(change):
    with pytest.raises(ValueError): native._credential({**CREDS, **change})

@pytest.mark.asyncio
async def test_expiry_and_import_reset_acknowledgment_before_http(provider):
    with pytest.raises(ValueError): await run("get_access_scope", credential_data={**CREDS, "expires_at": 1})
    with pytest.raises(ValueError): await run("replace_offer", {"offer_id": 22, "shop_sku": "sku-1", "state_code": "11", "price": 9.99, "quantity": 0})
    assert provider.requests == []
    with pytest.raises(ValueError): native.GetProducts(references=[{"type": "SHOP_SKU", "value": "123"}])

def test_actual_catalog_factory_has_only_prepared_native_scope():
    from coder.workflow.operation_catalog import get_operations_for_node_type
    operations = get_operations_for_node_type(NODE)
    assert {operation.name for operation in operations} == OPS
    assert not any(operation.is_trigger for operation in operations)
    instance = NodeFactory.create_node(node_id="fixture", node_type=NODE,
        node_data={"config": {"operation": "get_access_scope"}, "credentials": CREDS},
        sio=None, sid=None, workflow_id=None, user_id=USER, conversation_id=None, organization_id=ORG)
    assert isinstance(instance.config, native.MiraklNodeConfig)

@pytest.mark.asyncio
async def test_actual_resolver_uses_authoritative_family(stored, provider):
    result = await run("list_shop_offers", credential_data=None, credential_id=CID, pool=stored.storage, organization_id=ORG)
    assert result["data"]["items"][0]["offer_id"] == 22 and stored.crypto.decrypt_credential.called

class _Context:
    def __init__(self, value): self.value = value
    async def __aenter__(self): return self.value
    async def __aexit__(self, *_args): return False


class _Storage:
    """Synthetic SQL boundary; the real repositories enforce admission/authority."""
    def __init__(self):
        self.row = {"credential_type": FAMILY, "owner_id": USER, "token_version": 7, "updated_at": UPDATED, "approval_revision": 1, "revoked_at": None, "credential": b"synthetic-ciphertext"}
        self.access, self.authorized, self.owner_fallback, self.decision = True, True, False, None
    def acquire(self): return _Context(self)
    def transaction(self): return _Context(self)
    async def fetchrow(self, sql, *args):
        if sql.startswith("SELECT owner_id, settings") or sql.startswith("SELECT owner_id FROM workflows"): return {"owner_id": OWNER}
        if sql.startswith("SELECT 1 FROM workflow_authorized_credentials"): return {"one": 1} if self.authorized else None
        if sql.startswith("SELECT name,owner_id,approval_operations"):
            return {"name": "Fixture", "owner_id": self.row["owner_id"], "approval_operations": ["*"] if self.decision else [], "approval_revision": self.row["approval_revision"], "revoked_at": self.row["revoked_at"]}
        if sql.startswith("SELECT id,status,consumed_at,expires_at"):
            return {"id": UUID(int=100), "status": self.decision, "consumed_at": None, "expires_at": UPDATED.replace(year=2099)}
        if "AS revoked," in sql:
            return {"name": "Fixture", "revoked": self.row["revoked_at"] is not None, "owner_id": self.row["owner_id"], "workflow_owner_id": OWNER}
        if "FROM credentials c" in sql:
            return None if not self.access or self.owner_fallback and args[1] == USER else deepcopy(self.row)
        raise AssertionError("Unexpected synthetic storage query")
    async def fetchval(self, sql, *args):
        # No workflow-lent credential in this synthetic boundary.
        return None
    async def execute(self, sql, *args):
        assert sql.startswith("UPDATE approval_requests SET consumed_at")
        self.decision = None
        return "UPDATE 1"


@pytest.fixture
def stored(monkeypatch):
    from utils import credentials
    from wss.handlers import workflow_handler
    storage, crypto = _Storage(), MagicMock()
    crypto.decrypt_credential.side_effect = lambda _: {**CREDS, "credential_type": "foreign-blob"}
    monkeypatch.setattr("utils.encryption.get_encryption", lambda: crypto)
    monkeypatch.setattr(credentials, "get_encryption", lambda: crypto)
    monkeypatch.setattr(workflow_handler, "get_encryption", lambda: crypto)
    monkeypatch.setattr(workflow_handler, "get_user_org_context", AsyncMock(return_value=ORG))
    return SimpleNamespace(storage=storage, crypto=crypto)



@pytest.mark.asyncio
@pytest.mark.parametrize("family", [None, "foreign-family", FAMILY])
async def test_authoritative_family_never_rescued_by_native_blob(stored, provider, family):
    stored.storage.row["credential_type"] = family
    stored.crypto.decrypt_credential.side_effect = lambda _: dict(CREDS)
    if family == FAMILY:
        assert (await run("get_access_scope", credential_id=CID, pool=stored.storage, organization_id=ORG))["data"]["items"][0]["shop_id"] == 17
    else:
        with pytest.raises(ValueError): await run("get_access_scope", credential_id=CID, pool=stored.storage, organization_id=ORG)
        assert provider.requests == [] and not stored.crypto.decrypt_credential.called
@pytest.mark.asyncio
@pytest.mark.parametrize("change,value", [("token_version", 99), ("approval_revision", 99), ("owner_id", OWNER), ("updated_at", UPDATED.replace(year=2027)), ("revoked_at", UPDATED), ("credential_type", None)])
async def test_acceptance_rechecks_current_row(stored, provider, change, value):
    provider.after_response = lambda: stored.storage.row.update({change: value})
    with pytest.raises(ValueError): await run("get_access_scope", credential_id=CID, pool=stored.storage, organization_id=ORG)
    assert len(provider.requests) == 1
@pytest.mark.asyncio
@pytest.mark.parametrize("decision", ["pending", "rejected"])
async def test_real_admission_never_calls_provider(stored, provider, decision):
    stored.storage.decision = decision
    result = await run("get_access_scope", credential_id=CID, pool=stored.storage, organization_id=ORG)
    assert result["status"] == ("pending_approval" if decision == "pending" else "rejected") and result["executed"] is False
    evidence = await collect_evidence(node_type=NODE, credential_id=CID, pool=stored.storage, user_id=USER)
    assert evidence.reachable is None and provider.requests == []
@pytest.mark.asyncio
async def test_trusted_hook_and_native_lookup(stored, provider):
    result = await run_node_lookup(node_type=NODE, field_name="hierarchy", credential_id=CID, user_id=USER, pool=stored.storage, organization_id=ORG)
    assert result["options"][0]["value"] == "cat"
    assert await native.MiraklNode.validate_credential_access(CREDS) == {"valid": True}
    assert (await native.MiraklNode.validate_credential_access({**CREDS, "access_token": "bad header"}))["valid"] is False


async def _route(monkeypatch, stored, event, request_model, handler_class, module, payload):
    from wss.receiver.chunk_reassembly import ChunkReassemblyManager
    from wss.receiver.event_routing import EVENT_ROUTING, Handler
    from wss.receiver.receiver import SocketIOProxy
    from wss.receiver.rate_limiter import RateLimiter
    from wss.receiver.rate_limits import get_rate_limit_config
    responses = []
    async def capture(_sio, _sid, event, **_kwargs): responses.append(event.model_dump())
    monkeypatch.setattr(module, "send_event", capture)
    monkeypatch.setattr("utils.user_presence.touch_user_presence", lambda _: None)
    sio = SimpleNamespace(get_session=AsyncMock(return_value={"user_id": USER}))
    handler = handler_class.__new__(handler_class)
    handler.sio, handler.get_pool = sio, AsyncMock(return_value=stored.storage)
    assert EVENT_ROUTING["API"][event] == (Handler.CREDENTIALS if event == "credential:validate_access" else Handler.WORKFLOW)
    proxy = SocketIOProxy.__new__(SocketIOProxy)
    proxy.sio, proxy.SOCKET_PROXY_ENV = sio, "API"
    proxy.chunk_manager, proxy.rate_limiter = ChunkReassemblyManager(), RateLimiter(get_rate_limit_config())
    proxy.config = SimpleNamespace(event_handlers={"API": {event: [handler]}})
    proxy.frontend_request_pydantic_models, proxy._last_heavy_completion = {event: request_model}, {}
    await proxy._route_event_impl(event, "fixture-sid", {"request_id": "fixture", "node_type": NODE, "credential_id": CID, **payload})
    return responses[-1]["data"]



@pytest.mark.asyncio
@pytest.mark.parametrize("family,decision", [(FAMILY, None), (None, None), ("foreign-family", None)])
async def test_actual_stored_socket_picker(stored, provider, monkeypatch, family, decision):
    from wss.handlers import workflow_handler
    from wss.receiver.client_events import WorkflowNodeLoadOptionsRequest
    stored.storage.row["credential_type"], stored.storage.decision = family, decision
    stored.crypto.decrypt_credential.side_effect = lambda _: dict(CREDS)
    data = await _route(monkeypatch, stored, "workflow:node:load_options", WorkflowNodeLoadOptionsRequest, workflow_handler.WorkflowHandler, workflow_handler, {"field_name": "hierarchy"})
    allowed = family == FAMILY and decision is None
    assert data["success"] is allowed and bool(provider.requests) is allowed
    assert data["options"] == ([{"value": "cat", "label": "Fixture category", "metadata": None}] if allowed else [])
    assert CREDS["access_token"] not in json.dumps(data)

@pytest.mark.asyncio
async def test_actual_socket_offer_picker_keeps_numeric_wire_parent(stored, provider, monkeypatch):
    from wss.handlers import workflow_handler
    from wss.receiver.client_events import WorkflowNodeLoadOptionsRequest
    data = await _route(monkeypatch, stored, "workflow:node:load_options", WorkflowNodeLoadOptionsRequest,
        workflow_handler.WorkflowHandler, workflow_handler, {"field_name": "offer_id"})
    assert data["success"] is True
    assert data["options"] == [{"value": "22", "label": "sku-1", "metadata": None}]
    picked = native.GetOffer(offer_id=data["options"][0]["value"], product_sku="product-1")
    assert picked.offer_id == 22
    assert (await run("get_offer", {"offer_id": data["options"][0]["value"], "product_sku": "product-1"}))["data"]["offer_id"] == 22
    assert provider.requests[-1].url.path == "/api/offers/22"


@pytest.mark.asyncio
@pytest.mark.parametrize("authorized", [False, True])
async def test_workflow_owner_acl_and_native_lookup(stored, provider, authorized):
    stored.storage.owner_fallback, stored.storage.authorized, stored.storage.row["owner_id"] = True, authorized, OWNER
    if authorized:
        result = await run_node_lookup(node_type=NODE, field_name="hierarchy", credential_id=CID, user_id=USER, pool=stored.storage, organization_id=ORG, workflow_id=WORKFLOW)
        assert result["options"][0]["value"] == "cat"
    else:
        with pytest.raises(ValueError):
            await run_node_lookup(node_type=NODE, field_name="hierarchy", credential_id=CID, user_id=USER, pool=stored.storage, organization_id=ORG, workflow_id=WORKFLOW)
        assert provider.requests == []

@pytest.mark.asyncio
async def test_account_key_and_actor_org_changes_refuse_acceptance(stored, provider, monkeypatch):
    from wss.handlers import workflow_handler
    provider.after_response = lambda: monkeypatch.setattr(workflow_handler, "get_user_org_context", AsyncMock(return_value=str(UUID(int=9))))
    with pytest.raises(ValueError, match="binding changed"):
        await run("get_access_scope", credential_id=CID, pool=stored.storage, organization_id=ORG)
    monkeypatch.setattr(workflow_handler, "get_user_org_context", AsyncMock(return_value=ORG))
    provider.after_response = lambda: setattr(stored.crypto.decrypt_credential, "side_effect", lambda _: {**CREDS, "shop_id": 99})
    provider.requests.clear()
    with pytest.raises(ValueError, match="binding changed"):
        await run("list_shop_offers", credential_id=CID, pool=stored.storage, organization_id=ORG)
    assert len(provider.requests) == 1

@pytest.mark.asyncio
async def test_inaccessible_revoked_and_invalid_plaintext_before_http(stored, provider):
    for kind in ("inaccessible", "revoked", "invalid"):
        stored.storage.access = kind != "inaccessible"
        stored.storage.row["revoked_at"] = UPDATED if kind == "revoked" else None
        stored.crypto.decrypt_credential.side_effect = lambda _: {**CREDS, "access_token": "bad header"} if kind == "invalid" else dict(CREDS)
        with pytest.raises((ValueError, PermissionError)):
            await run("get_access_scope", credential_id=CID, pool=stored.storage, organization_id=ORG)
        assert provider.requests == []
@pytest.mark.asyncio
@pytest.mark.parametrize("timeout,status,expected", [(False, None, True), (True, None, None), (False, 401, False), (False, 403, False), (False, 500, None)])
async def test_staging_validation_hook_provider_outcomes(provider, timeout, status, expected):
    provider.timeout, provider.status = timeout, status
    result = await native.MiraklNode.validate_credential_access(CREDS)
    assert result["valid"] is expected
    assert len(provider.requests) == 1
    assert CREDS["access_token"] not in json.dumps(result)
