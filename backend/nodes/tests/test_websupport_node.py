"""Prepared Websupport regressions use real factory, authority, admission and socket seams.
Only SQL/encryption, provider HTTP and socket-delivery boundaries are synthetic.
These source fixtures are unrun and do not prove live account access.
"""
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from nodes import websupport_node as ad
from nodes.core.base import ConfigValidationError
from nodes.core.registry import NODE_REGISTRY, NodeFactory
from tests.test_oauth_refresh_authority import _Storage as AuthorityStorage, CID, USER, OWNER, ORG, WF
from tests.test_post_connect_validation_context import _Storage as AdmissionStorage
from wss.receiver.client_events import WorkflowNodeLoadOptionsRequest, CredentialValidateAccessRequest

NODE = "automation-websupport"
SERVICE, OTHER = "service-17", "other-service"


@pytest.fixture
def ensure_native_db_pool():
    yield


def credential(**updates):
    return {"credential_type": "websupport_api_key", "api_key": "fixture-key", "api_secret": "fixture-secret", "service_id": SERVICE, **updates}


def make_node(operation, data=None, **config):
    target = {}
    return NodeFactory.create_node("fixture", NODE, {"config": {"operation": operation, **target, **config},
        "credentials": credential() if data is None else data}, user_id=USER)

@pytest.fixture
def http(monkeypatch):
    state = SimpleNamespace(calls=[], client_options=[], responses=[])
    async def respond(request):
        state.calls.append(request)
        assert state.responses, "Unexpected HTTP request"
        item = state.responses.pop(0)
        status, payload = item[:2]
        headers = item[2] if len(item) == 3 else {}
        return httpx.Response(status, content=payload, headers=headers) if isinstance(payload, (str, bytes)) else httpx.Response(status, json=payload, headers=headers) if payload is not None else httpx.Response(status, headers=headers)
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
        self.row.update(id=CID, credential_type="websupport_api_key",
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


STAMP = "2026-01-01T13:00:00.000Z"

def zone(**updates):
    return {"name": "example.com", "lastCheck": STAMP, "dnssecSigning": "active",
        "credentials": "private-sentinel", "content": "private-sentinel", **updates}

def record(**updates):
    return {"id": 17, "name": "www", "type": "A", "ttl": 3600, "content": "private-sentinel",
        "priority": None, "port": None, "weight": None, "note": "private-sentinel", **updates}

def page(*rows, **updates):
    return {"currentPage": 0, "rowsPerPage": 50, "totalPages": 3, "totalRecords": 111,
        "data": list(rows), **updates}

def test_actual_factory_schema_has_three_current_operations_and_bound_key_secret():
    assert NODE_REGISTRY[NODE] is ad.WebsupportNode
    defs = ad.WebsupportNode.get_config_schema()["$defs"]
    assert defs["WebsupportApiKeyCredential"]["required"] == ["api_key", "api_secret", "service_id"]
    ops = {d["properties"]["operation"]["const"] for d in defs.values() if "operation" in d.get("properties", {})}
    assert ops == {"check_connection", "get_zone", "list_records"}
    assert defs["WebsupportRecordsConfig"]["properties"]["record_type"]["x-dynamic-options"]["field"] == "record_type"
    for operation in ("list_services", "get_record", "update_record", "nic_update", "get_account"):
        with pytest.raises(ConfigValidationError):
            make_node(operation)
    for extra in ({"page": 2}, {"service_id": OTHER}, {"rowsPerPage": 500}, {"filters": {"content": "private-sentinel"}}):
        with pytest.raises(ConfigValidationError):
            make_node("list_records", **extra)


@pytest.mark.asyncio
async def test_actual_request_signing_uses_exact_no_query_path_fresh_signature_and_matching_utc_date(http, monkeypatch):
    import base64
    import hashlib
    import hmac
    ticks = iter((1704067200, 1704067201))
    monkeypatch.setattr(ad, "time", SimpleNamespace(time=lambda: next(ticks)))
    http.responses = [(200, {"verified": True}), (200, zone())]
    out = await make_node("check_connection").execute({})
    assert out["verified"] is True and out["protected_zone"] is True and out["items"] == [{"lastCheck": STAMP, "dnssecSigning": "active"}]
    assert len(http.calls) == 2
    for request, stamp in zip(http.calls, (1704067200, 1704067201)):
        assert request.method == "GET" and request.url.host == "rest.websupport.sk" and not request.url.params
        canonical = f"GET {request.url.path} {stamp}".encode()
        expected = hmac.new(b"fixture-secret", canonical, hashlib.sha1).hexdigest()
        username, signature = base64.b64decode(request.headers["authorization"].removeprefix("Basic ")).decode().split(":", 1)
        assert username == "fixture-key" and signature == expected and len(signature) == 40
        assert request.headers["x-date"] == datetime.fromtimestamp(stamp, timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        assert request.headers["accept"] == "application/json" and request.headers["content-type"] == "application/json"
        assert "fixture-secret" not in json.dumps(dict(request.headers)) and "fixture-secret" not in str(request.url)
    assert http.calls[0].url.path == "/v2/check"
    assert http.calls[1].url.path == "/v2/service/service-17/dns/zone"
    assert "private-sentinel" not in json.dumps(out) and "account_label" not in out and "service_id" not in out


@pytest.mark.asyncio
async def test_default_record_envelope_preserves_nullable_ids_counts_and_unknown_completion_without_query(http):
    http.responses = [(200, zone()), (200, page(record(id=None), record(id=18, type="TXT")))]
    out = await make_node("list_records", max_items=1).execute({})
    assert out["items"] == [{"id": None, "type": "A", "ttl": 3600}]
    assert out["provider_page"] == {"currentPage": 0, "rowsPerPage": 50, "totalPages": 3, "totalRecords": 111}
    assert out["returned"] == 1 and out["provider_returned"] == 2 and out["local_truncated"] is True
    assert "unknown" in out["completion"] and "total" not in out and "next_page_token" not in out
    assert "private-sentinel" not in json.dumps(out) and "example.com" not in json.dumps(out) and "www" not in json.dumps(out)
    assert [request.url.path for request in http.calls] == ["/v2/service/service-17/dns/zone", "/v2/service/service-17/dns/record"]
    assert all(not request.url.params for request in http.calls)


@pytest.mark.asyncio
async def test_zone_optional_fields_and_names_do_not_fabricate_service_or_domain_identity(http):
    http.responses = [(200, {})]
    out = await make_node("get_zone").execute({})
    assert out["zone"] == {} and "service_id" not in out and "id" not in out["zone"]
    http.responses = [(200, zone())]
    named = await make_node("get_zone", include_names=True).execute({})
    assert named["zone"] == {"name": "example.com", "lastCheck": STAMP, "dnssecSigning": "active"}
    assert "credentials" not in named["zone"] and "service-17" not in json.dumps(named)


@pytest.mark.asyncio
async def test_local_type_filter_and_current_service_selector_ignore_forged_context(http):
    http.responses = [(200, zone()), (200, page(record(), record(id=18, type="TXT")))]
    out = await make_node("list_records", record_type="TXT", include_names=True).execute({})
    assert out["items"] == [{"id": 18, "type": "TXT", "ttl": 3600, "name": "www"}]
    http.responses = [(200, zone()), (200, page(record(), record(id=18, type="TXT"), record(id=19)))]
    options = await ad.WebsupportNode.load_field_options("record_type", credential(), context={"service_id": OTHER,
        "api_secret": "forged", "workflow_id": WF}, search="T")
    assert options["options"] == [{"value": "TXT", "label": "TXT"}] and options["next_page_token"] is None
    assert all("/service/service-17/" in request.url.path and not request.url.params for request in http.calls)
    before = len(http.calls)
    for field, kwargs in (("service_id", {}), ("record_id", {}), ("record_type", {"page_token": "forged"})):
        with pytest.raises(ValueError):
            await ad.WebsupportNode.load_field_options(field, credential(), **kwargs)
    assert len(http.calls) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{"data": []}, page(record(ttl=True)), page(record(id=True)), page(record(type="CUSTOM")),
    page(record(), record()), page(record(name="https://private.invalid")), page(record(), currentPage=True)])
async def test_malformed_current_record_envelopes_and_safe_metadata_fail_closed(http, payload):
    http.responses = [(200, zone()), (200, payload)]
    with pytest.raises(RuntimeError) as error:
        await make_node("list_records").execute({})
    assert "private-sentinel" not in str(error.value) and "private.invalid" not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{"data": zone()}, {"dnssecSigning": "unknown"}, {"lastCheck": None}])
async def test_direct_zone_contract_refuses_wrappers_and_invalid_optional_properties(http, payload):
    http.responses = [(200, payload)]
    with pytest.raises(RuntimeError):
        await make_node("get_zone").execute({})
    assert len(http.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [False, None, "true", 1])
async def test_verification_requires_exact_true_before_any_zone_read(http, value):
    http.responses = [(200, {"verified": value})]
    with pytest.raises(RuntimeError):
        await make_node("check_connection").execute({})
    assert len(http.calls) == 1 and http.calls[0].url.path == "/v2/check"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 404, 422, 429, 500, 302, 204])
async def test_provider_refusals_are_static_without_private_body_or_retry(http, status):
    http.responses = [(status, {"message": "fixture-secret private-sentinel"})]
    with pytest.raises(RuntimeError) as error:
        await make_node("get_zone").execute({})
    assert "fixture-secret" not in str(error.value) and "private-sentinel" not in str(error.value) and len(http.calls) == 1


@pytest.mark.asyncio
async def test_current_saved_key_secret_service_version_and_manager_metadata_replace_stale_blob(saved):
    saved.storage.grant = credential(api_key="current-key", api_secret="current-secret", service_id=OTHER, manager_flag="keep")
    saved.storage.row["token_version"] = 8
    current = await ad.WebsupportNode.freshen_credential(credential(token_version=1), pool=saved.storage, user_id=USER,
        credential_id=CID, workflow_id=WF, organization_id=ORG)
    assert current["api_key"] == "current-key" and current["api_secret"] == "current-secret" and current["service_id"] == OTHER
    assert current["token_version"] == 8 and current["manager_flag"] == "keep"
    assert saved.http.calls == [] and saved.storage.writes == [] and saved.storage.revoke_tags == []


@pytest.mark.asyncio
@pytest.mark.parametrize("unavailable", ["wrong-family", "revoked", "denied"])
async def test_real_current_typed_live_access_precedes_decryption_and_http(saved, unavailable):
    if unavailable == "wrong-family":
        saved.storage.row["credential_type"] = "other"
    elif unavailable == "revoked":
        saved.storage.row["revoked_at"] = datetime.now(timezone.utc)
    else:
        saved.storage.access.clear()
    with pytest.raises(ValueError):
        await ad.WebsupportNode.freshen_credential(credential(), pool=saved.storage, user_id=USER, credential_id=CID)
    saved.crypto.decrypt_credential.assert_not_called()
    assert saved.http.calls == []


@pytest.mark.asyncio
async def test_actual_manual_connect_requires_auth_boolean_and_zone_without_actor_identity(http, monkeypatch):
    from nodes.core import credential_connect
    from nodes.core.connection_evidence import collect_evidence
    monkeypatch.setattr(credential_connect, "_collect_evidence", collect_evidence)
    http.responses = [(200, {"verified": True}), (200, zone())]
    out = await credential_connect.validate_for_connect(credential_type="websupport_api_key", credential_data=credential(), user_id=USER)
    assert out.ok and out.evidence.reachable is True and out.evidence.proves == "reachability" and out.evidence.account_label is None
    assert [sample.label for sample in out.evidence.samples] == [STAMP]
    assert "private-sentinel" not in json.dumps(asdict(out.evidence))
    http.responses = [(200, {"verified": False})]
    refused = await credential_connect.validate_for_connect(credential_type="websupport_api_key", credential_data=credential(), user_id=USER)
    assert not refused.ok and refused.evidence.reachable is False and refused.evidence.account_label is None
    assert len(http.calls) == 3


@pytest.mark.asyncio
async def test_registered_socket_native_probe_picker_and_current_shared_org_binding(sockets):
    sockets.saved.storage.grant = credential(api_key="current-key", api_secret="current-secret", service_id=OTHER)
    sockets.saved.http.responses = [(200, {"verified": True}), (200, zone())]
    assert await socket_call(sockets, "credential:validate_access", user_id=OWNER, organization_id=OWNER) == {"valid": True}
    sockets.saved.http.responses = [(200, zone()), (200, page(record()))]
    out = await socket_call(sockets, "workflow:node:load_options", field_name="record_type",
        context={"service_id": SERVICE, "api_secret": "forged", "_user_id": OWNER, "workflow_id": WF})
    assert out["success"] is True and out["options"] == [{"value": "A", "label": "A", "metadata": None}]
    assert all("/service/other-service/" in request.url.path for request in sockets.saved.http.calls if request.url.path != "/v2/check")
    assert all(args[2] == ORG for sql, args in sockets.saved.storage.calls if "SELECT c.credential" in sql)


@pytest.mark.asyncio
@pytest.mark.parametrize("status,payload", [(403, {"message": "private-sentinel"}), (200, {"verified": "true"})])
async def test_registered_validation_preserves_unknown_on_provider_and_shape_failures(sockets, status, payload):
    sockets.saved.http.responses = [(status, payload)]
    out = await socket_call(sockets, "credential:validate_access")
    assert out["valid"] is None and "private-sentinel" not in json.dumps(out)


@pytest.mark.asyncio
@pytest.mark.parametrize("policy", ["pending", "rejected"])
async def test_actual_admission_and_evidence_stop_before_signing_or_raw_fallback(sockets, policy):
    from nodes.core.connection_evidence import collect_evidence
    storage = sockets.saved.storage
    storage.row["approval_operations"] = ["*"]
    out = await socket_call(sockets, "workflow:node:load_options", field_name="record_type", context={"approved": True})
    assert out["success"] is False
    if policy == "rejected":
        for grant in storage.grants.values():
            grant["status"] = "rejected"
    evidence = await collect_evidence(node_type=NODE, credential_id=CID, user_id=USER, pool=storage, organization_id=ORG, workflow_id=WF)
    assert evidence.reachable is None and evidence.account_label is None and evidence.samples == []
    assert sockets.saved.http.calls == [] and storage.writes == []


@pytest.mark.parametrize("service", ["https://foreign.invalid", "../foreign", "svc/a", "svc?query=1", "svc%2Fforeign", "", "x"*192])
def test_bound_service_is_opaque_safe_path_segment_without_domain_guessing(service):
    with pytest.raises(ValueError):
        ad._service(service)
    assert ad._service("service-17") == SERVICE and ad._service("opaque.reference") == "opaque.reference"


@pytest.mark.asyncio
async def test_wrong_raw_family_and_arbitrary_or_mutating_routes_stop_before_http(http):
    with pytest.raises(ValueError):
        await ad.WebsupportNode.load_field_options("record_type", credential(credential_type="websupport_password"))
    for kind in ("/nic/update", "ftp-account", "record-detail", "token"):
        with pytest.raises(ValueError):
            await ad._request(credential(), kind)
    assert http.calls == []


@pytest.mark.asyncio
async def test_actual_public_transport_refuses_private_dns_despite_legacy_override(monkeypatch):
    import asyncio
    import socket
    from utils import ssrf
    transport_calls = []
    lookup = AsyncMock(return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.8", 443))])
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", lookup)
    monkeypatch.setattr(ssrf, "allow_private_hosts", lambda: True)
    def guarded(**kwargs):
        return ssrf.guarded_async_client(transport=httpx.MockTransport(
            lambda request: transport_calls.append(request) or httpx.Response(200, json={})), **kwargs)
    monkeypatch.setattr(ad, "guarded_async_client", guarded)
    with pytest.raises(RuntimeError, match="could not be reached"):
        await make_node("check_connection").execute({})
    lookup.assert_awaited_once_with("rest.websupport.sk", 443, type=socket.SOCK_STREAM)
    assert transport_calls == []

