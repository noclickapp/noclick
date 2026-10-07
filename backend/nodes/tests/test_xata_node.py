"""Prepared Xata regressions use real factory, authority, admission and socket seams.
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
from pydantic import ValidationError
from nodes import xata_node as ad
from nodes.core.registry import NODE_REGISTRY, NodeFactory
from tests.test_oauth_refresh_authority import _Storage as AuthorityStorage, CID, USER, OWNER, ORG, WF
from tests.test_post_connect_validation_context import _Storage as AdmissionStorage
from wss.receiver.client_events import WorkflowNodeLoadOptionsRequest, CredentialValidateAccessRequest

NODE = "automation-xata"
OID, PROJECT, BRANCH, BACKUP, OTHER = "org-a", "project-a", "branch-a", "backup-a", "foreign"


@pytest.fixture
def ensure_native_db_pool():
    yield


def credential(**updates):
    return {"credential_type": "xata_issued_oauth", "access_token": "fixture-token", "granted_scopes": ["org:read", "project:read", "branch:read"], **updates}


def make_node(operation, data=None, **config):
    target = {"organization_id": OID} if operation not in {"check_connection", "list_organizations"} else {}
    if operation in {"get_project", "list_branches", "list_backups", "get_backup"}:
        target["project_id"] = PROJECT
    if operation == "get_backup":
        target["backup_id"] = BACKUP
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
        self.row.update(id=CID, credential_type="xata_issued_oauth",
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

def organization(**updates):
    return {"id": OID, "name": "Private organization", "status": {"status": "enabled", "last_updated": "2026-10-07T00:00:00Z",
        "disabled_by_admin": False, "billing_status": "ok", "usage_tier": "t1", "billing_reason": "private-sentinel",
        "admin_reason": "private-sentinel"}, "marketplace": "private-sentinel", **updates}

def project(**updates):
    return {"id": PROJECT, "name": "Private project", "createdAt": "2026-10-07T00:00:00Z", "updatedAt": "2026-10-07T00:00:00Z",
        "configuration": {"connectionString": "postgres://private-sentinel"}, **updates}

def branch(**updates):
    return {"id": BRANCH, "name": "Private branch", "createdAt": "2026-10-07T00:00:00Z", "updatedAt": "2026-10-07T00:00:00Z",
        "region": "us", "publicAccess": True, "backupsEnabled": True, "description": "private-sentinel",
        "connectionString": "postgres://private-sentinel", **updates}

def backup(**updates):
    return {"id": BACKUP, "branchID": BRANCH, "description": "private-sentinel",
        "earliestRestore": "2026-10-07T00:00:00Z", **updates}

def catalog(kind, *rows):
    return (200, {kind: list(rows)})

def parents():
    return [catalog("organizations", organization()), catalog("projects", project())]


def test_actual_factory_and_schema_have_eight_closed_read_operations():
    assert ad._id("-org~a:region") == "-org~a:region"
    assert NODE_REGISTRY[NODE] is ad.XataNode
    schema = ad.XataNode.get_config_schema()
    defs = schema["$defs"]
    assert defs["XataIssuedOAuthCredential"]["required"] == ["access_token", "granted_scopes"]
    assert defs["XataGetBackupConfig"]["properties"]["backup_id"]["x-dynamic-options"]["depends_on"] == "project_id"
    assert defs["XataGetBackupConfig"]["properties"]["project_id"]["x-dynamic-options"]["depends_on"] == "organization_id"
    operations = {v["properties"]["operation"]["const"] for v in defs.values() if "operation" in v.get("properties", {})}
    assert operations == {"check_connection", "list_organizations", "get_organization", "list_projects", "get_project", "list_branches", "list_backups", "get_backup"}
    with pytest.raises(ValidationError):
        make_node("get_branch")
    assert "branch" not in ad.ROUTES


@pytest.mark.asyncio
async def test_catalog_proof_nested_status_private_projection_and_fixed_header(http):
    http.responses = [catalog("organizations", organization(), organization(id=OTHER))]
    out = await make_node("check_connection", max_items=1).execute({})
    assert out["protected_catalog"] is True and out["returned"] == 1 and out["provider_returned"] == 2 and out["local_truncated"] is True
    assert out["items"] == [{"id": OID, "status": {"status": "enabled", "last_updated": "2026-10-07T00:00:00Z"}}]
    assert "unknown" in out["completion"] and "total" not in out and "next_page_token" not in out
    req = http.calls[0]
    assert str(req.url) == "https://api.xata.tech/organizations" and req.headers["Authorization"] == "Bearer fixture-token"
    assert "private-sentinel" not in json.dumps(out) and "Private organization" not in json.dumps(out)


@pytest.mark.asyncio
async def test_project_detail_bound_by_catalog_without_invented_parent_scalar(http):
    http.responses = parents()+[(200, project())]
    out = await make_node("get_project", include_names=True).execute({})
    assert out["project"] == {"id": PROJECT, "name": "Private project", "createdAt": "2026-10-07T00:00:00Z", "updatedAt": "2026-10-07T00:00:00Z"}
    assert "organization_id" not in out["project"] and "configuration" not in out["project"]
    assert http.calls[-1].url.path == "/organizations/org-a/projects/project-a"
    http.responses = parents()+[(200, project(id=OTHER))]
    with pytest.raises(RuntimeError):
        await make_node("get_project").execute({})


@pytest.mark.asyncio
async def test_backup_catalog_and_detail_verify_current_branch_and_backup_ancestry(http):
    http.responses = parents()+[catalog("branches", branch()), catalog("backups", backup()), (200, backup()), catalog("branches", branch())]
    out = await make_node("get_backup").execute({})
    assert out["backup"] == {"id": BACKUP, "branchID": BRANCH, "earliestRestore": "2026-10-07T00:00:00Z"}
    assert len(http.calls) == 6 and all(not req.url.params for req in http.calls)
    assert "private-sentinel" not in json.dumps(out)


@pytest.mark.asyncio
@pytest.mark.parametrize("foreign", ["organization", "project", "backup-branch", "detail-id", "detail-branch"])
async def test_resource_mismatch_stops_before_any_unwitnessed_child_read(http, foreign):
    http.responses = parents()+[catalog("branches", branch()), catalog("backups", backup()), (200, backup()), catalog("branches", branch())]
    if foreign == "organization":
        http.responses[0] = catalog("organizations", organization(id=OTHER))
    elif foreign == "project":
        http.responses[1] = catalog("projects", project(id=OTHER))
    elif foreign == "backup-branch":
        http.responses[3] = catalog("backups", backup(branchID=OTHER))
    elif foreign == "detail-id":
        http.responses[4] = (200, backup(id=OTHER))
    else:
        http.responses[4] = (200, backup(branchID=OTHER))
    with pytest.raises((ValueError, RuntimeError)):
        await make_node("get_backup").execute({})
    assert len(http.calls) == {"organization": 1, "project": 2, "backup-branch": 4, "detail-id": 5, "detail-branch": 6}[foreign]


@pytest.mark.asyncio
async def test_scope_expiry_family_and_unsupported_cursor_refuse_before_provider_io(http):
    for data in (credential(granted_scopes=["project:read"]), credential(expires_at="2000-01-01T00:00:00Z"),
                 credential(credential_type="xata_api_key"), credential(access_token="Bearer private-sentinel")):
        with pytest.raises(ValueError):
            await ad.XataNode.load_field_options("organization_id", data)
    with pytest.raises(ValueError):
        await ad.XataNode.load_field_options("organization_id", credential(), page_token="fabricated")
    assert http.calls == []


@pytest.mark.asyncio
async def test_parent_selector_uses_full_context_local_id_search_not_forged_token(http):
    with pytest.raises(ValueError):
        await ad.XataNode.load_field_options("backup_id", credential(), context={"project_id": PROJECT})
    assert http.calls == []
    http.responses = parents()+[catalog("branches", branch()), catalog("backups", backup())]
    out = await ad.XataNode.load_field_options("backup_id", credential(), context={"organization_id": OID,
        "project_id": PROJECT, "access_token": "forged", "workflow_id": WF}, search="backup")
    assert out == {"options": [{"value": BACKUP, "label": BACKUP}], "next_page_token": None}
    assert all(req.headers["Authorization"] == "Bearer fixture-token" for req in http.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, [], {"organizations": {}}, {"organizations": [organization(status="enabled")]},
    {"organizations": [organization(id="../foreign")]}, {"organizations": [organization(), organization()]},
    {"organizations": [organization(status={"status": "unknown"})]}, {"organizations": [], "error": "private-sentinel"}])
async def test_exact_wrapper_ids_and_nested_status_fail_closed(http, payload):
    http.responses = [(200, payload)]
    with pytest.raises(RuntimeError) as failure:
        await make_node("check_connection").execute({})
    assert "private-sentinel" not in str(failure.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429, 500, 302, 204])
async def test_provider_refusals_remain_static_unknown_without_retry(http, status):
    http.responses = [(status, {"error": "private-sentinel fixture-token"})]
    with pytest.raises(RuntimeError) as failure:
        await make_node("check_connection").execute({})
    assert "private-sentinel" not in str(failure.value) and "fixture-token" not in str(failure.value) and len(http.calls) == 1


@pytest.mark.asyncio
async def test_saved_current_row_adopts_token_scopes_expiry_and_preserves_manager_metadata(saved):
    saved.storage.grant = credential(access_token="current-token", manager_flag="keep")
    current = await ad.XataNode.freshen_credential(credential(), pool=saved.storage, user_id=USER,
        credential_id=CID, workflow_id=WF, organization_id=ORG)
    assert current["access_token"] == "current-token" and current["manager_flag"] == "keep"
    assert current["granted_scopes"] == ["org:read", "project:read", "branch:read"]
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
        await ad.XataNode.freshen_credential(credential(), pool=saved.storage, user_id=USER, credential_id=CID)
    saved.crypto.decrypt_credential.assert_not_called()
    assert saved.http.calls == []


@pytest.mark.asyncio
async def test_actual_manual_connect_reports_catalog_reachability_without_identity(http, monkeypatch):
    from nodes.core import credential_connect
    from nodes.core.connection_evidence import collect_evidence
    monkeypatch.setattr(credential_connect, "_collect_evidence", collect_evidence)
    http.responses = [catalog("organizations", organization())]
    result = await credential_connect.validate_for_connect(credential_type="xata_issued_oauth", credential_data=credential(), user_id=USER)
    assert result.ok and result.node_type == NODE and result.evidence.reachable is True
    assert result.evidence.proves == "reachability" and result.evidence.samples == [OID] and result.evidence.account_label is None
    assert "private-sentinel" not in json.dumps(asdict(result.evidence))


@pytest.mark.asyncio
async def test_registered_socket_uses_current_token_trusted_org_and_native_probe(sockets):
    sockets.saved.storage.grant = credential(access_token="current-token")
    sockets.saved.http.responses = [catalog("organizations", organization())]
    assert await socket_call(sockets, "credential:validate_access", user_id=OWNER, organization_id=OWNER) == {"valid": True}
    sockets.saved.http.responses = [catalog("organizations", organization())]
    out = await socket_call(sockets, "workflow:node:load_options", field_name="organization_id",
        context={"access_token": "forged", "_user_id": OWNER, "workflow_id": WF})
    assert out["success"] is True and out["options"] == [{"value": OID, "label": OID}]
    assert all(req.headers["Authorization"] == "Bearer current-token" for req in sockets.saved.http.calls)
    assert all(args[2] == ORG for sql, args in sockets.saved.storage.calls if "SELECT c.credential" in sql)


@pytest.mark.asyncio
@pytest.mark.parametrize("status,payload", [(403, {"error": "private-sentinel"}), (200, {"organizations": {}})])
async def test_native_registered_validation_preserves_unknown_on_provider_or_shape_failure(sockets, status, payload):
    sockets.saved.http.responses = [(status, payload)]
    out = await socket_call(sockets, "credential:validate_access")
    assert out["valid"] is None and "private-sentinel" not in json.dumps(out)


@pytest.mark.asyncio
@pytest.mark.parametrize("policy", ["pending", "rejected"])
async def test_actual_admission_and_evidence_policy_stop_without_http_or_raw_fallback(sockets, policy):
    from nodes.core.connection_evidence import collect_evidence
    storage = sockets.saved.storage
    storage.row["approval_operations"] = ["*"]
    out = await socket_call(sockets, "workflow:node:load_options", field_name="organization_id", context={"approved": True})
    assert out["success"] is False
    if policy == "rejected":
        for grant in storage.grants.values():
            grant["status"] = "rejected"
    evidence = await collect_evidence(node_type=NODE, credential_id=CID, user_id=USER, pool=storage, organization_id=ORG, workflow_id=WF)
    assert evidence.reachable is None and evidence.account_label is None and evidence.samples == []
    assert sockets.saved.http.calls == [] and storage.writes == []


@pytest.mark.asyncio
async def test_public_transport_refuses_private_dns_even_with_legacy_override(monkeypatch):
    import asyncio
    import socket
    from utils import ssrf
    transport_calls = []
    lookup = AsyncMock(return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.8", 443))])
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", lookup)
    monkeypatch.setattr(ssrf, "allow_private_hosts", lambda: True)
    def guarded(**kwargs):
        return ssrf.guarded_async_client(transport=httpx.MockTransport(
            lambda request: transport_calls.append(request) or httpx.Response(200, json={"organizations": []})), **kwargs)
    monkeypatch.setattr(ad, "guarded_async_client", guarded)
    with pytest.raises(RuntimeError, match="could not be reached"):
        await make_node("check_connection").execute({})
    lookup.assert_awaited_once_with("api.xata.tech", 443, type=socket.SOCK_STREAM)
    assert transport_calls == []
