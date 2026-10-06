"""Prepared Adapty contracts through actual native/connect/socket seams.
Only provider transport, SQL/encryption and socket delivery boundaries are synthetic.
These source fixtures are unrun and do not prove provider or database behavior.
"""
from copy import deepcopy
from datetime import datetime, timezone
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import quote

import httpx
import pytest
from pydantic import ValidationError
from nodes import adapty_node as ad
from nodes.core.registry import NODE_REGISTRY, NodeFactory
from tests.test_oauth_refresh_authority import _Storage as AuthorityStorage, CID, USER, OWNER, ORG, WF
from tests.test_post_connect_validation_context import _Storage as AdmissionStorage
from wss.receiver.client_events import WorkflowNodeLoadOptionsRequest, CredentialValidateAccessRequest

NODE = "automation-adapty"
APP = '14c3d333-2f3a-455a-aa86-ef83dff6913b'
PID = 'd8533a10-bcce-4e33-8c9d-88b05ac56559'
OTHER = '3286abd3-48b0-4e9c-a5f6-ac0a006804a6'
DEVICE = '3fa85f64-5717-4562-b3fc-2c963f66afa6'

@pytest.fixture
def ensure_native_db_pool():
    yield


def credential(**updates):
    return {"credential_type": "adapty_api_key", "secret_key": "fixture-secret", "app_id": APP,
        "verification_profile_id": PID, **updates}


def profile(**updates):
    return {"data": {"app_id": APP, "profile_id": PID, "customer_user_id": "customer-fixture",
        "timestamp": 1791244800000, "custom_attributes": [{"key": "fixture", "value": "blue"}],
        "access_levels": [{"access_level_id": "premium", "starts_at": None, "expires_at": None,
            "is_in_grace_period": False, "store_transaction_id": "private-transaction"}],
        "subscriptions": [{"secret": "private"}], "total_revenue_usd": 99.9, "segment_hash": "private",
        **updates}}


def make_node(operation, data=None, **config):
    target = {} if operation == "check_connection" else {"identifier_kind": "profile_id", "profile_identifier": PID}
    return NodeFactory.create_node("fixture", NODE, {"config": {"operation": operation, **target, **config},
        "credentials": credential() if data is None else data}, user_id=USER)


@pytest.fixture
def http(monkeypatch):
    state = SimpleNamespace(calls=[], client_options=[], responses=[])
    async def respond(request):
        state.calls.append(request)
        assert state.responses, "Unexpected HTTP request"
        status, payload = state.responses.pop(0)
        return httpx.Response(status, content=payload) if isinstance(payload, (str, bytes)) else httpx.Response(status, json=payload) if payload is not None else httpx.Response(status)
    def client(**kwargs):
        state.client_options.append(kwargs)
        assert kwargs.pop("require_public") is True
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(ad, "guarded_async_client", client)
    return state


class Storage(AuthorityStorage):
    def __init__(self, grant):
        super().__init__()
        self.grant = deepcopy(grant)
        self.row.update(id=CID, credential_type="adapty_api_key",
            name="Fixture", approval_operations=[], approval_revision=1)
        self.allowed = self.access
        self.grants, self.timeline, self.transactions = {}, [], 0
        self.on_load = self.on_resolve = self.on_admit = None

    def transaction(self):
        self.transactions += 1
        return self.acquire()

    async def fetchrow(self, sql, *args):
        if ("SELECT c.credential" in sql and len(args) == 3 or
            "approval_requests" in sql or "SELECT name,owner_id,approval_operations" in sql):
            return await AdmissionStorage.fetchrow(self, sql, *args)
        return await super().fetchrow(sql, *args)

    async def fetchval(self, sql, *args):
        return await AdmissionStorage.fetchval(self, sql, *args)

    async def execute(self, sql, *args):
        if "UPDATE approval_requests" in sql:
            return await AdmissionStorage.execute(self, sql, *args)
        return await super().execute(sql, *args)


@pytest.fixture
def saved(monkeypatch, http):
    storage = Storage(credential())
    crypto = MagicMock()
    crypto.decrypt_credential.side_effect = lambda _: deepcopy(storage.grant)
    crypto.encrypt_credential.side_effect = lambda data: json.dumps(data).encode()
    monkeypatch.setattr("utils.encryption.get_encryption", lambda: crypto)
    from utils import credentials
    monkeypatch.setattr(credentials, "get_encryption", lambda: crypto)
    monkeypatch.setattr("wss.handlers.workflow_handler.get_user_org_context", AsyncMock(return_value=ORG))
    return SimpleNamespace(storage=storage, crypto=crypto, http=http)


@pytest.fixture
def sockets(saved, monkeypatch):
    from wss.handlers import credentials_handler, workflow_handler
    from wss.receiver.receiver import SocketIOProxy
    from wss.receiver.event_routing import EVENT_ROUTING, Handler
    from wss.receiver.chunk_reassembly import ChunkReassemblyManager
    from wss.receiver.rate_limiter import RateLimiter
    from wss.receiver.rate_limits import get_rate_limit_config
    responses = []
    async def capture(_sio, _sid, event, **kwargs):
        if not kwargs.get("user_id"):
            responses.append(event.model_dump())
    for module in (credentials_handler, workflow_handler):
        monkeypatch.setattr(module, "send_event", capture)
    monkeypatch.setattr("wss.sender.send_event", capture)
    monkeypatch.setattr(credentials_handler, "get_encryption", lambda: saved.crypto)
    sio = SimpleNamespace(get_session=AsyncMock(return_value={"user_id": USER}))
    monkeypatch.setattr("utils.socket_singleton.get_sio", lambda: sio)
    monkeypatch.setattr("utils.user_presence.touch_user_presence", lambda _: None)
    workflow = workflow_handler.WorkflowHandler.__new__(workflow_handler.WorkflowHandler)
    workflow.sio, workflow.get_pool = sio, AsyncMock(return_value=saved.storage)
    credentials = credentials_handler.CredentialsHandler(sio)
    credentials.get_pool = AsyncMock(return_value=saved.storage)
    proxy = SocketIOProxy.__new__(SocketIOProxy)
    proxy.sio, proxy.SOCKET_PROXY_ENV = sio, "API"
    proxy.chunk_manager = ChunkReassemblyManager()
    proxy.rate_limiter = RateLimiter(get_rate_limit_config())
    proxy._last_heavy_completion = {}
    routes = {"workflow:node:load_options": (workflow, WorkflowNodeLoadOptionsRequest, Handler.WORKFLOW),
        "credential:validate_access": (credentials, CredentialValidateAccessRequest, Handler.CREDENTIALS)}
    for event, (_, _, handler) in routes.items():
        assert EVENT_ROUTING["API"][event] == handler
    proxy.config = SimpleNamespace(event_handlers={"API": {event: [v[0]] for event, v in routes.items()}})
    proxy.frontend_request_pydantic_models = {event: v[1] for event, v in routes.items()}
    return SimpleNamespace(proxy=proxy, responses=responses, saved=saved)


async def socket_call(sockets, event, **kwargs):
    await sockets.proxy._route_event_impl(event, "fixture-sid", {"request_id": "fixture",
        "node_type": NODE, "credential_id": CID, **kwargs})
    return sockets.responses[-1]["data"]


def test_actual_factory_schema_and_required_device_contract():
    assert NODE_REGISTRY[NODE] is ad.AdaptyNode
    schema = ad.AdaptyNode.get_config_schema()
    defs = schema["$defs"]
    ops = {defs[ref["$ref"].split("/")[-1]]["properties"]["operation"]["const"] for ref in schema["properties"]["config"]["oneOf"]}
    assert len(ops) == 10 and {"get_profile", "create_profile", "update_profile", "delete_profile", "grant_access_level", "revoke_access_level"} <= ops
    assert not any(word in op for op in ops for word in ("transaction", "stripe", "refund", "mail"))
    assert defs["AdaptyAPIKeyCredential"]["required"] == ["secret_key", "app_id", "verification_profile_id"]
    assert "installation_meta" in defs["AdaptyCreateProfileConfig"]["required"]
    assert defs["AdaptyInstallationMeta"]["required"] == ["device_id"]
    for config in ({"operation": "get_profile", "profile_identifier": "not-uuid"},
            {"operation": "create_profile", "profile_identifier": PID},
            {"operation": "update_profile", "profile_identifier": PID, "installation_meta": {}},
            {"operation": "grant_access_level", "profile_identifier": PID, "access_level_id": "premium", "expires_at": "2026-10-06"}):
        with pytest.raises(ValidationError):
            ad.AdaptyNodeConfig(config=config, credentials=credential())


@pytest.mark.parametrize("updates", [{"credential_type": "other"}, {"app_id": "not-uuid"},
    {"verification_profile_id": "not-uuid"}, {"secret_key": "fixture-secret\nprivate"}, {"secret_key": ""}])
def test_bad_raw_credential_is_refused_without_secret_context(updates):
    with pytest.raises(ValueError) as failure:
        ad._credential(credential(**updates))
    assert "fixture-secret" not in str(failure.value) and "private" not in str(failure.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,identifier", [("profile_id", PID), ("customer_user_id", "customer-fixture")])
async def test_profile_headers_fixed_root_and_projection(http, kind, identifier):
    http.responses = [(200, profile())]
    out = await make_node("get_profile", identifier_kind=kind, profile_identifier=identifier).execute({})
    request = http.calls[0]
    assert str(request.url) == ad.ROOT + "profile/" and request.method == "GET"
    assert request.headers["Authorization"] == "Api-Key fixture-secret"
    assert request.headers["adapty-" + kind.replace("_", "-")] == identifier
    assert ("adapty-customer-user-id" in request.headers) != ("adapty-profile-id" in request.headers)
    assert out["data"]["app_id"] == APP and out["data"]["timestamp"] == 1791244800000
    assert "private" not in json.dumps(out) and "subscriptions" not in out["data"] and "total_revenue_usd" not in out["data"]
    assert out["data"]["access_levels"][0]["expires_at"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["create_profile", "update_profile", "delete_profile", "grant_access_level", "revoke_access_level"])
async def test_wrong_app_binding_halts_before_any_mutation(http, operation):
    http.responses = [(200, profile(app_id=OTHER))]
    fields = {"installation_meta": {"device_id": DEVICE}} if operation in {"create_profile", "update_profile"} else {"access_level_id": "premium"} if "access_level" in operation else {}
    with pytest.raises(RuntimeError, match="another app/profile"):
        await make_node(operation, **fields).execute({})
    assert len(http.calls) == 1 and http.calls[0].method == "GET"


@pytest.mark.asyncio
async def test_create_and_patch_documented_body_and_explicit_null(http):
    http.responses = [(200, profile()), (200, profile(profile_id=OTHER, customer_user_id="new-customer"))]
    created = await make_node("create_profile", profile_identifier=OTHER, platform_header="iOS",
        installation_meta={"device_id": DEVICE}, first_name="Fixture", analytics_disabled=True).execute({})
    assert created["operation"] == "create_profile" and [request.method for request in http.calls] == ["GET", "POST"]
    assert http.calls[0].headers["adapty-profile-id"] == PID and http.calls[1].headers["adapty-profile-id"] == OTHER
    assert http.calls[1].headers["adapty-platform"] == "iOS"
    assert json.loads(http.calls[1].content) == {"installation_meta": {"device_id": DEVICE}, "first_name": "Fixture", "analytics_disabled": True}
    http.responses = [(200, profile()), (200, profile())]
    updated = await make_node("update_profile", installation_meta={"device_id": DEVICE}, first_name=None,
        custom_attributes=[{"key": "colour", "value": "blue"}]).execute({})
    assert updated["operation"] == "update_profile" and http.calls[-1].method == "PATCH"
    assert json.loads(http.calls[-1].content) == {"installation_meta": {"device_id": DEVICE}, "first_name": None,
        "custom_attributes": [{"key": "colour", "value": "blue"}]}


@pytest.mark.parametrize("attributes", [[{"key": "x", "value": True}], [{"key": "x", "value": "x" * 51}],
    [{"key": "bad space", "value": "x"}], [{"key": "x", "value": float("nan")}],
    [{"key": "x", "value": "a"}, {"key": "x", "value": "b"}], [{"key": str(i), "value": "x"} for i in range(31)]])
def test_actual_profile_model_rejects_bad_custom_attribute_values(attributes):
    with pytest.raises(ValidationError):
        ad.AdaptyNodeConfig(config={"operation": "create_profile", "profile_identifier": PID,
            "installation_meta": {"device_id": DEVICE}, "custom_attributes": attributes}, credentials=credential())


@pytest.mark.asyncio
async def test_delete_empty_204_and_other_success_shapes_are_not_deletion(http):
    http.responses = [(200, profile()), (204, None)]
    out = await make_node("delete_profile").execute({})
    assert out["http_status"] == 204 and out["deletion_acknowledged"] is True
    assert http.calls[-1].method == "DELETE"
    for status, payload in ((200, profile()), (204, "private")):
        http.responses = [(200, profile()), (status, payload)]
        with pytest.raises(RuntimeError, match="204"):
            await make_node("delete_profile").execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,path,dates", [("grant_access_level", "grant", {"starts_at": None, "expires_at": "2099-01-01T00:00:00Z"}),
    ("revoke_access_level", "revoke", {"revoke_at": None})])
async def test_access_writes_have_explicit_effect_and_documented_payload(http, operation, path, dates):
    http.responses = [(200, profile()), (200, profile())]
    out = await make_node(operation, access_level_id="premium", **dates).execute({})
    assert str(http.calls[-1].url) == ad.ROOT + "purchase/profile/" + path + "/access-level/"
    assert json.loads(http.calls[-1].content) == {"access_level_id": "premium", **dates}
    assert out["operation"] == operation and "quiet" in out["confirmation"]


@pytest.mark.asyncio
@pytest.mark.parametrize("level,expected", [({"starts_at": None, "expires_at": None, "is_in_grace_period": False}, True),
    ({"starts_at": None, "expires_at": "2000-01-01T00:00:00Z", "is_in_grace_period": False}, False),
    ({"starts_at": None, "expires_at": "2000-01-01T00:00:00Z", "is_in_grace_period": True}, True),
    ({"starts_at": "2099-01-01T00:00:00Z", "expires_at": None, "is_in_grace_period": True}, False)])
async def test_access_status_is_derived_from_current_dates_and_grace_not_sdk_flag(http, level, expected):
    http.responses = [(200, profile(access_levels=[{"access_level_id": "premium", **level}]))]
    out = await make_node("check_access_level", access_level_id="premium").execute({})
    assert out["has_access"] is expected and out["found"] is True and "is_active" not in out["data"]


@pytest.mark.asyncio
async def test_profile_and_access_pickers_use_only_the_chosen_profile(http):
    http.responses = [(200, profile()), (200, profile(profile_id=OTHER))]
    first = await ad.AdaptyNode.load_field_options("profile_identifier", credential(), context={"identifier_kind": "customer_user_id"})
    assert first == {"options": [{"value": "customer-fixture", "label": "customer-fixture"}], "next_page_token": None}
    selected = await ad.AdaptyNode.load_field_options("access_level_id", credential(),
        context={"identifier_kind": "profile_id", "profile_identifier": OTHER, "app_id": "forged", "secret_key": "forged"}, search="missing")
    assert selected == {"options": [], "next_page_token": None}
    assert http.calls[-1].headers["adapty-profile-id"] == OTHER and http.calls[-1].headers["Authorization"] == "Api-Key fixture-secret"
    before = len(http.calls)
    for context, token in (({}, None), ({"identifier_kind": "other", "profile_identifier": OTHER}, None),
            ({"identifier_kind": "profile_id", "profile_identifier": OTHER}, "invented-page")):
        with pytest.raises(ValueError):
            await ad.AdaptyNode.load_field_options("access_level_id", credential(), context=context, page_token=token)
    assert len(http.calls) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("status,payload", [(401, {"errors": "fixture-secret"}), (403, {"errors": "private"}),
    (404, {"errors": "private"}), (429, {"errors": "private"}), (500, {}), (200, {"errors": "fixture-secret"}),
    (200, {}), (200, profile(profile_id=OTHER)), (200, profile(access_levels=[{}]))])
async def test_provider_error_or_malformed_profile_is_static_and_unverified(http, status, payload):
    http.responses = [(status, payload)]
    with pytest.raises(RuntimeError) as failure:
        await make_node("get_profile").execute({})
    assert "fixture-secret" not in str(failure.value) and "private" not in str(failure.value) and len(http.calls) == 1


@pytest.mark.asyncio
async def test_saved_current_row_replaces_all_app_bindings_without_mint_or_persistence(saved):
    saved.storage.grant = credential(secret_key="current-secret", app_id=OTHER, verification_profile_id=OTHER)
    current = await ad.AdaptyNode.freshen_credential(credential(), pool=saved.storage, user_id=USER,
        credential_id=CID, workflow_id=WF, organization_id=ORG)
    assert current["secret_key"] == "current-secret" and current["app_id"] == OTHER and current["verification_profile_id"] == OTHER
    assert saved.http.calls == [] and saved.storage.writes == [] and saved.storage.revoke_tags == []
    saved.storage.access = {(OWNER, ORG)}
    assert (await ad.AdaptyNode.freshen_credential(credential(), pool=saved.storage, user_id=USER,
        credential_id=CID, workflow_id=WF, organization_id=ORG))["secret_key"] == "current-secret"


@pytest.mark.asyncio
@pytest.mark.parametrize("unavailable", ["wrong-family", "revoked", "denied"])
async def test_actual_current_authority_refuses_before_decryption_and_provider_work(saved, unavailable):
    if unavailable == "wrong-family":
        saved.storage.row["credential_type"] = "other"
    elif unavailable == "revoked":
        saved.storage.row["revoked_at"] = datetime.now(timezone.utc)
    else:
        saved.storage.access.clear()
    with pytest.raises(ValueError):
        await ad.AdaptyNode.freshen_credential(credential(), pool=saved.storage, user_id=USER, credential_id=CID)
    saved.crypto.decrypt_credential.assert_not_called()
    assert saved.http.calls == []


@pytest.mark.asyncio
async def test_real_manual_connect_is_app_profile_reachability_not_account_identity(http, monkeypatch):
    from nodes.core import credential_connect
    from nodes.core.connection_evidence import collect_evidence
    monkeypatch.setattr(credential_connect, "_collect_evidence", collect_evidence)
    bad = await credential_connect.validate_for_connect(credential_type="adapty_api_key", credential_data=credential(app_id="bad"), user_id=USER)
    assert not bad.ok and bad.field_errors and http.calls == []
    http.responses = [(200, profile())]
    valid = await credential_connect.validate_for_connect(credential_type="adapty_api_key", credential_data=credential(), user_id=USER)
    assert valid.ok and valid.node_type == NODE and valid.evidence.reachable is True
    assert valid.evidence.proves == "reachability" and valid.evidence.account_label is None and valid.evidence.samples[0].label == PID


@pytest.mark.asyncio
async def test_registered_socket_current_secret_and_trusted_org_ignore_request_authority(sockets):
    sockets.saved.storage.grant = credential(secret_key="current-secret")
    sockets.saved.http.responses = [(200, profile())]
    assert await socket_call(sockets, "credential:validate_access", organization_id=OWNER, user_id=OWNER) == {"valid": True}
    sockets.saved.http.responses = [(200, profile())]
    picked = await socket_call(sockets, "workflow:node:load_options", field_name="profile_identifier",
        context={"identifier_kind": "profile_id", "app_id": OTHER, "secret_key": "forged", "organization_id": OWNER, "workflow_id": WF})
    assert picked["success"] is True and picked["options"][0]["value"] == PID
    assert all(request.headers["Authorization"] == "Api-Key current-secret" for request in sockets.saved.http.calls)
    assert all(args[2] == ORG for sql, args in sockets.saved.storage.calls if "SELECT c.credential" in sql)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["pending", "rejected"])
async def test_registered_admission_and_saved_evidence_do_not_fallback_or_call_provider(sockets, status):
    from nodes.core.connection_evidence import collect_evidence
    storage = sockets.saved.storage
    storage.row["approval_operations"] = ["*"]
    first = await socket_call(sockets, "workflow:node:load_options", field_name="profile_identifier", context={"approved": True})
    assert first["success"] is False and "Review:" in first["message"]
    evidence = await collect_evidence(node_type=NODE, credential_id=CID, user_id=USER, pool=storage, organization_id=ORG, workflow_id=WF)
    assert evidence.reachable is None and evidence.account_label is None and evidence.samples == []
    if status == "rejected":
        for grant in storage.grants.values():
            grant["status"] = "rejected"
        rejected = await socket_call(sockets, "workflow:node:load_options", field_name="profile_identifier", context={"approved": True})
        assert rejected["success"] is False and "rejected" in rejected["message"]
    assert sockets.saved.http.calls == [] and storage.writes == []
