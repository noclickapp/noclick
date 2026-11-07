"""API2Cart factory, socket picker and admission with synthetic rows.

The storage double checks bound canonical SQL, not actual PostgreSQL ACLs.
No credentials, requests or logs outside these local literals are used.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import httpx
import pytest
from nodes import api2cart_node as v
from nodes.core.registry import NodeFactory
from repositories.credentials import credential_access_predicate
from wss.receiver.client_events import CredentialValidateAccessRequest, WorkflowNodeLoadOptionsRequest

CID, USER, ORG, WS, ITEM, ACCESS = [str(UUID(int=n)) for n in range(41, 47)]
UPDATED = datetime(2026, 10, 6, tzinfo=timezone.utc)
SECRET = "synthetic-api2cart-authority-key"
CRED = {"credential_type": v.FAMILY, "api_key": SECRET, "store_key": "synthetic-api2cart-authority-store-key", "platform_id": "Shopify", "store_id": "1"}


@pytest.fixture
def ensure_native_db_pool():
    yield


class _Scope:
    def __init__(self, value): self.value = value
    async def __aenter__(self): return self.value
    async def __aexit__(self, *_): return False


class Storage:
    def __init__(self):
        self.row = {"id": CID, "name": "API2Cart fixture", "credential": b"fixture-ciphertext",
            "owner_id": USER, "credential_type": v.FAMILY, "token_version": 7,
            "updated_at": UPDATED, "revoked_at": None, "approval_revision": 1, "approval_operations": []}
        self.blob, self.allowed, self.calls, self.grants = deepcopy(CRED), True, [], {}

    def acquire(self): return _Scope(self)
    def transaction(self): return _Scope(self)

    async def fetchrow(self, sql, *args):
        self.calls.append((sql, args))
        if "SELECT c.credential" in sql:
            assert credential_access_predicate() in sql
            assert args[:2] == (CID, USER) and args[2] in {ORG, None}
            if len(args) == 6:
                assert args[3] == USER and args[5] is None
            return deepcopy(self.row) if self.allowed else None
        if "SELECT name,owner_id,approval_operations" in sql:
            assert args == (CID,) and "FOR UPDATE" in sql
            return deepcopy(self.row) if self.allowed else None
        if "SELECT id,status,consumed_at,expires_at" in sql:
            row = self.grants.get(args[1])
            return row if row and row["consumed_at"] is None else None
        if "INSERT INTO approval_requests" in sql:
            row = {"id": UUID(int=90 + len(self.grants)), "status": "pending", "consumed_at": None,
                   "expires_at": UPDATED + timedelta(days=1)}
            self.grants[args[-2]] = row
            return row
        raise AssertionError("Unexpected fixture query")

    async def fetchval(self, sql, *args):
        assert args == (CID,)
        if "cardinality(approval_operations)" in sql: return bool(self.row["approval_operations"])
        assert "SELECT count(*) FROM approval_requests" in sql
        return len(self.grants)

    async def execute(self, sql, identifier):
        assert sql == "UPDATE approval_requests SET consumed_at=now() WHERE id=$1"
        for row in self.grants.values():
            if row["id"] == identifier:
                row["consumed_at"] = UPDATED
                return "UPDATE 1"
        raise AssertionError("Unexpected fixture write")


@pytest.fixture
def native(monkeypatch):
    from utils import credentials, credential_approval
    from repositories.organization import OrgRepo
    from wss.handlers import credentials_handler, workflow_handler
    from wss.receiver.chunk_reassembly import ChunkReassemblyManager
    from wss.receiver.event_routing import EVENT_ROUTING, Handler
    from wss.receiver.receiver import SocketIOProxy
    from wss.receiver.rate_limiter import RateLimiter
    from wss.receiver.rate_limits import get_rate_limit_config

    state = SimpleNamespace(storage=Storage(), requests=[], responses=[], on_request=None)
    crypto = MagicMock()
    crypto.decrypt_credential.side_effect = lambda _: deepcopy(state.storage.blob)
    state.crypto = crypto
    monkeypatch.setattr("utils.encryption.get_encryption", lambda: crypto)
    monkeypatch.setattr(credentials, "get_encryption", lambda: crypto)
    monkeypatch.setattr(credentials_handler, "get_encryption", lambda: crypto)
    monkeypatch.setattr(workflow_handler, "get_encryption", lambda: crypto, raising=False)
    monkeypatch.setattr(workflow_handler, "get_user_org_context", AsyncMock(return_value=ORG))
    monkeypatch.setattr(OrgRepo, "get_primary_org_id", AsyncMock(return_value=ORG))
    monkeypatch.setattr(credential_approval, "notify_created", AsyncMock())

    async def provider(request):
        state.requests.append(request)
        if state.on_request: state.on_request(request)
        assert request.url.host == "api.api2cart.com" and request.headers["x-api-key"] == SECRET
        assert SECRET not in str(request.url)
        path = request.url.path
        if path == "/v1.1/account.cart.list.json":
            payload = {"carts_count": 1, "carts": [{"id": "connection-owned", "store_key": CRED["store_key"], "cart_id": "Shopify"}]}
        elif path == "/v1.1/cart.info.json":
            payload = {"stores_info": [{"store_id": "1", "name": "Owned fixture"}]}
        elif path == "/v1.1/cart.methods.json": payload = {"method": ["order.list", "product.list", "cart.info", "cart.methods"]}
        elif path in {"/v1.1/order.list.json", "/v1.1/product.list.json"}:
            assert request.url.params["store_id"] == "1"
            product = path.endswith("product.list.json")
            payload = {"product" if product else "order": [{"id": "p-owned" if product else "order-owned", "name": "Owned product", "order_id": "ORDER-FIXTURE", "store_id": "1", "stores_ids": ["1"], "email": SECRET}],
                "products_count" if product else "orders_count": 1}
        else: raise AssertionError("Unexpected fixture native route")
        return httpx.Response(200, json={"return_code": 0, "return_message": SECRET, "result": payload, "pagination": {"next": None}})
    original_client = httpx.AsyncClient
    monkeypatch.setattr(v.httpx, "AsyncClient", lambda **kw: original_client(transport=httpx.MockTransport(provider), **kw))

    async def capture(_sio, sid, event, **_kw):
        assert sid == "fixture-sid"
        state.responses.append(event.model_dump()["data"])
    monkeypatch.setattr(credentials_handler, "send_event", capture)
    monkeypatch.setattr(workflow_handler, "send_event", capture)
    sio = SimpleNamespace(get_session=AsyncMock(return_value={"user_id": USER}))
    monkeypatch.setattr("utils.user_presence.touch_user_presence", lambda _user: None)
    credential_handler, workflow = credentials_handler.CredentialsHandler(sio), workflow_handler.WorkflowHandler(sio)
    credential_handler.get_pool = workflow.get_pool = AsyncMock(return_value=state.storage)
    proxy = SocketIOProxy.__new__(SocketIOProxy)
    proxy.sio, proxy.SOCKET_PROXY_ENV = sio, "API"
    proxy.chunk_manager, proxy.rate_limiter = ChunkReassemblyManager(), RateLimiter(get_rate_limit_config())
    assert EVENT_ROUTING["API"]["credential:validate_access"] == Handler.CREDENTIALS
    assert EVENT_ROUTING["API"]["workflow:node:load_options"] == Handler.WORKFLOW
    proxy.config = SimpleNamespace(event_handlers={"API": {
        "credential:validate_access": [credential_handler], "workflow:node:load_options": [workflow]}})
    proxy.frontend_request_pydantic_models = {
        "credential:validate_access": CredentialValidateAccessRequest,
        "workflow:node:load_options": WorkflowNodeLoadOptionsRequest}
    proxy._last_heavy_completion = {}
    state.proxy = proxy
    return state


async def route(state, event, **kwargs):
    await state.proxy._route_event_impl(event, "fixture-sid", {
        "request_id": "fixture-request", "node_type": v.TYPE, "credential_id": CID, **kwargs})
    return state.responses[-1]


def saved(state, operation="list_orders"):
    return NodeFactory.create_node(node_id="api2cart-fixture", node_type=v.TYPE, node_data={"config": {"operation": operation},
        "credentials": deepcopy(CRED), "credential_id": CID, "_approval_pool": state.storage},
        user_id=USER, organization_id=ORG)


@pytest.mark.asyncio
async def test_actual_socket_picker_uses_credential_store_and_canonical_actor(native):
    result = await route(native, "workflow:node:load_options", field_name="product_id",
        context={"store_id": "foreign", "_user_id": "forged", "organization_id": "forged"})
    assert result["success"] is True and [(row["value"], row["label"]) for row in result["options"]] == [("p-owned", "Owned product")]
    assert SECRET not in str(result)
    assert native.requests[-1].url.params["store_id"] == "1"


@pytest.mark.asyncio
async def test_actual_native_admission_parks_before_provider_and_restricted_picker_refuses(native):
    native.storage.row["approval_operations"] = ["*"]
    result = await saved(native).run({})
    assert result["status"] == "pending_approval" and not native.requests
    assert len(native.storage.grants) == 1
    with pytest.raises(ValueError, match="picker unavailable"):
        await v.API2CartNode.freshen_credential(CRED, pool=native.storage, user_id=USER,
            credential_id=CID)
    assert not native.requests


@pytest.mark.asyncio
async def test_actual_approved_exact_call_is_consumed_once_without_replay(native):
    native.storage.row["approval_operations"] = ["*"]
    assert (await saved(native).run({}))["status"] == "pending_approval"
    grant = next(iter(native.storage.grants.values()))
    grant["status"] = "approved"
    assert (await saved(native).run({}))["status"] == "success"
    assert grant["consumed_at"] == UPDATED
    before = len(native.requests)
    assert (await saved(native).run({}))["status"] == "pending_approval"
    assert len(native.requests) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["key", "store_key", "platform", "store", "revoked", "acl", "family"])
async def test_current_row_change_after_response_stops_following_request(native, change):
    def mutate(request):
        if request.url.path != "/v1.1/account.cart.list.json": return
        row = native.storage.row
        if change == "key": native.storage.blob["api_key"] += "-changed"
        if change == "store_key": native.storage.blob["store_key"] += "-changed"
        if change == "platform": native.storage.blob["platform_id"] = "Magento"
        if change == "store": native.storage.blob["store_id"] = "foreign"
        if change == "revoked": row["revoked_at"] = UPDATED
        if change == "acl": native.storage.allowed = False
        if change == "family": row["credential_type"] = "other_key"
    native.on_request = mutate
    with pytest.raises((ValueError, PermissionError)):
        await saved(native).run({})
    assert [request.url.path for request in native.requests] == ["/v1.1/account.cart.list.json"]


def test_raw_foreign_family_cannot_be_reconciled_into_api2cart():
    data = {"id": "fixture", "type": v.TYPE, "config": {"operation": "test_connection"},
            "credentials": {**CRED, "credential_type": "foreign"}}
    assert v.API2CartNode.validate_config(data)["valid"] is False
    with pytest.raises(ValueError, match="requires an API2Cart"):
        NodeFactory.create_node(node_id="fixture", node_type=v.TYPE, node_data=data)


@pytest.mark.asyncio
@pytest.mark.parametrize("include_type", [True, False])
async def test_native_validation_hook_reports_reachability_without_principal(native, include_type):
    data = deepcopy(CRED)
    if not include_type: data.pop("credential_type")
    result = await v.API2CartNode.validate_credential_access(data)
    assert result["valid"] is True and result["evidence"]["reachable"] is True
    assert result["evidence"]["account_label"] is None
    assert v.API2CartNode.connection_evidence.proves == "reachability"
    assert SECRET not in str(result) and len(native.requests) == 3
