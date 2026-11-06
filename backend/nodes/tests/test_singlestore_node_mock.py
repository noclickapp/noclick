"""SingleStore contracts through the real factory, current-row checks and socket seams.

Only DNS/HTTP and SQL/encryption storage boundaries are synthetic. The real
native dispatcher, credential repositories, admission and socket receiver run.
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
from nodes import singlestore_node as native
from nodes.core.connection_evidence import collect_evidence
from nodes.core.credential_connect import validate_for_connect
from nodes.core.registry import NODE_REGISTRY, NodeFactory
from nodes.core.run_op import run_node_operation, run_node_lookup

NODE, FAMILY = native.NODE_TYPE, "singlestore_management_api_key"
CID, USER, ORG, OWNER, WORKFLOW = (str(UUID(int=i)) for i in (42, 1, 3, 2, 4))
UPDATED = datetime(2026, 10, 6, tzinfo=timezone.utc)
PROJECT, CLUSTER = (str(UUID(int=i)) for i in (101, 102))
CREDS = {"credential_type": FAMILY, "api_key": "42abcdef42abcdef42abcdef42abcdef42abcdef42abcdef42abcdef42abcdef42", "organization_id": ORG}
OPS = {"get_organization", "list_projects", "get_project", "rename_project", "list_regions", "list_shared_tier_regions",
    "list_clusters", "get_cluster", "list_stage_folder", "get_stage_file_metadata", "create_stage_folder", "move_empty_stage_folder", "delete_empty_stage_folder"}

@pytest.fixture
def ensure_native_db_pool():
    yield

@pytest.fixture
def provider(monkeypatch):
    from utils import ssrf
    state = SimpleNamespace(requests=[], status=None, raw=None, media=None, target=None,
        timeout=False, after_response=None, empty=False, private_dns=False, name="Fixture project",
        foreign_org=False, foreign_project=False, stale_name=False,
        folders={"empty/": [], "full/": [{"path": "full/file.json", "name": "file.json", "type": "json", "size": 0, "writable": False, "content": "private"}]})
    original_dns, original_client = ssrf._resolve_host_addresses, ssrf.guarded_async_client
    async def public_dns(host, port, **kwargs):
        assert kwargs.get("permit_non_public", False) is False
        try:
            ipaddress.ip_address(host)
        except ValueError:
            assert host == "api.singlestore.com"
            address = "127.0.0.1" if state.private_dns else "93.184.216.34"
            ssrf._assert_ip_allowed(address)
            return [address]
        return await original_dns(host, port, **kwargs)
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", public_dns)
    async def respond(request):
        assert request.url.host == "api.singlestore.com" and request.url.scheme == "https"
        assert request.headers["authorization"] == "Bearer " + CREDS["api_key"]
        assert CREDS["api_key"] not in str(request.url) + request.content.decode()
        state.requests.append(request)
        if state.timeout:
            raise httpx.ReadTimeout("private " + CREDS["api_key"], request=request)
        path = request.url.path.removeprefix("/v2")
        method, status = request.method, 200
        project = {"projectID": PROJECT, "name": state.name, "edition": "STANDARD", "createdAt": UPDATED.isoformat(), "secret": "private"}
        cluster = {"clusterID": CLUSTER, "projectID": str(UUID(int=999)) if state.foreign_project else PROJECT,
            "name": "Fixture cluster", "provider": "AWS", "region": "us-west-2", "state": "ACTIVE", "kai": False, "multiAZ": False,
            "scalingProgress": 0, "endpoint": "private.sql.invalid", "adminPassword": "private", "firewallRanges": ["private"]}
        if path == "/organizations/current" and method == "GET":
            raw = {"orgID": str(UUID(int=999)) if state.foreign_org else ORG, "name": "Fixture organization", "firewallRanges": ["private"]}
        elif path == "/projects" and method == "GET":
            raw = [] if state.empty else [project]
        elif path == "/projects/" + PROJECT and method == "GET":
            raw = project
        elif path == "/projects/" + PROJECT and method == "PATCH":
            assert json.loads(request.content) == {"name": "Updated project"}
            if not state.stale_name: state.name = "Updated project"
            raw = {"projectID": PROJECT}
        elif path in {"/regions", "/regions/sharedtier"} and method == "GET":
            assert request.url.params["fields"] == "provider,region,regionName"
            raw = [] if state.empty else [{"provider": "AWS", "region": "US West", "regionName": "us-west-2", "private": "private"}]
        elif path == "/clusters" and method == "GET":
            assert request.url.params["projectID"] == PROJECT and request.url.params["includeTerminated"] == "false"
            assert request.url.params["fields"] == native.CLUSTER_FIELDS
            raw = [] if state.empty else [cluster]
        elif path == "/clusters/" + CLUSTER and method == "GET":
            assert request.url.params["fields"] == native.CLUSTER_FIELDS
            raw = cluster
        elif path.startswith("/clusters/" + CLUSTER + "/stage/fs"):
            folder = path.removeprefix("/clusters/" + CLUSTER + "/stage/fs").removeprefix("/")
            if folder == "file.json":
                assert method == "GET" and request.url.params["metadata"] == "true"
                raw = {"path": "file.json", "name": "file.json", "type": "json", "size": 0, "writable": False,
                    "content": "private", "downloadUrl": "https://private.invalid"}
            elif method == "GET":
                if folder == "":
                    rows = [{"path": key, "name": key.rstrip("/"), "type": "directory"} for key in state.folders]
                elif folder not in state.folders:
                    status, rows = 404, []
                else:
                    rows = state.folders[folder]
                raw = {"path": folder or "/", "type": "directory", "content": rows}
            elif method == "PUT":
                assert request.content == b"" and folder.endswith("/") and folder not in state.folders
                state.folders[folder] = []
                raw = {"path": "/" + folder.rstrip("/"), "name": folder.rstrip("/")}
            elif method == "PATCH":
                body = json.loads(request.content)
                assert body == {"newPath": "moved/"} and folder == "empty/"
                state.folders[body["newPath"]] = state.folders.pop(folder)
                raw = {"path": body["newPath"], "name": "moved"}
            elif method == "DELETE":
                assert folder == "empty/" and state.folders[folder] == []
                state.folders.pop(folder)
                raw = {"path": folder, "name": "empty"}
            else:
                raise AssertionError("Unexpected Stage method")
        else:
            raise AssertionError("Unexpected native route " + method + " " + path)
        if state.target is None or state.target == path:
            status = state.status or status
            content = state.raw if state.raw is not None else json.dumps(raw).encode()
            media = state.media or "application/json"
        else:
            content, media = json.dumps(raw).encode(), "application/json"
        if state.after_response:
            after, state.after_response = state.after_response, None
            after()
        return httpx.Response(status, content=content, headers={"content-type": media, "location": "https://private.invalid/download"}, request=request)
    def guarded(**kwargs):
        assert kwargs == {"follow_redirects": False, "trust_env": False, "timeout": 20.0}
        return original_client(**kwargs, transport=httpx.MockTransport(respond))
    monkeypatch.setattr(native, "guarded_async_client", guarded)
    return state

async def run(op, args=None, **kwargs):
    return await run_node_operation(node_type=NODE, operation=op, arguments=args or {}, user_id=USER,
        credential_data=kwargs.pop("credential_data", CREDS), **kwargs)

CASES = [
    ("get_organization", {}, "GET", "/organizations/current"),
    ("list_projects", {}, "GET", "/projects"),
    ("get_project", {"project_id": PROJECT}, "GET", "/projects/" + PROJECT),
    ("rename_project", {"project_id": PROJECT, "name": "Updated project"}, "PATCH", "/projects/" + PROJECT),
    ("list_regions", {}, "GET", "/regions"),
    ("list_shared_tier_regions", {}, "GET", "/regions/sharedtier"),
    ("list_clusters", {"project_id": PROJECT}, "GET", "/clusters"),
    ("get_cluster", {"project_id": PROJECT, "cluster_id": CLUSTER}, "GET", "/clusters/" + CLUSTER),
    ("list_stage_folder", {"project_id": PROJECT, "cluster_id": CLUSTER}, "GET", "/clusters/" + CLUSTER + "/stage/fs"),
    ("get_stage_file_metadata", {"project_id": PROJECT, "cluster_id": CLUSTER, "file_path": "file.json"}, "GET", "/clusters/" + CLUSTER + "/stage/fs/file.json"),
    ("create_stage_folder", {"project_id": PROJECT, "cluster_id": CLUSTER, "folder_path": "new"}, "PUT", "/clusters/" + CLUSTER + "/stage/fs/new/"),
    ("move_empty_stage_folder", {"project_id": PROJECT, "cluster_id": CLUSTER, "folder_path": "empty", "new_folder_path": "moved"}, "PATCH", "/clusters/" + CLUSTER + "/stage/fs/empty/"),
    ("delete_empty_stage_folder", {"project_id": PROJECT, "cluster_id": CLUSTER, "folder_path": "empty"}, "DELETE", "/clusters/" + CLUSTER + "/stage/fs/empty/"),
]

@pytest.mark.asyncio
@pytest.mark.parametrize("operation,arguments,method,path", CASES)
async def test_actual_factory_native_contracts_and_private_projection(provider, operation, arguments, method, path):
    assert NODE_REGISTRY[NODE] is native.SingleStoreNode
    result = await run(operation, arguments)
    assert result["status"] == "success" and result["data"] is not None
    assert (method, "/v2" + path) in [(r.method, r.url.path) for r in provider.requests]
    assert "private" not in json.dumps(result) and CREDS["api_key"] not in json.dumps(result)
    if method != "GET": assert result["data"]["readback_verified"] is True
    if operation == "get_cluster":
        assert result["data"]["kai"] is False and result["data"]["scalingProgress"] == 0
    if operation == "get_stage_file_metadata":
        assert result["data"]["file"]["size"] == 0 and result["data"]["file"]["writable"] is False

def test_real_catalog_factory_and_generated_schema_scope():
    from coder.workflow.operation_catalog import get_operations_for_node_type
    operations = get_operations_for_node_type(NODE)
    assert {operation.name for operation in operations} == OPS
    assert not any(operation.is_trigger for operation in operations)
    instance = NodeFactory.create_node(node_id="fixture", node_type=NODE,
        node_data={"config": {"operation": "get_organization"}, "credentials": CREDS},
        sio=None, sid=None, workflow_id=None, user_id=USER, conversation_id=None, organization_id=ORG)
    assert isinstance(instance.config, native.SingleStoreNodeConfig)
    assert native.SingleStoreNode.get_config_schema()["$defs"]["SingleStoreManagementCredential"]["properties"]["credential_type"]["const"] == FAMILY

@pytest.mark.parametrize("name", ["", "   "])
def test_rename_project_rejects_blank_names(name):
    with pytest.raises(ValueError):
        native.RenameProject(project_id=PROJECT, name=name)

@pytest.mark.asyncio
async def test_manual_connect_and_current_organization_evidence(provider):
    verdict = await validate_for_connect(credential_type=FAMILY, credential_data=CREDS, user_id=USER)
    assert verdict.ok and verdict.evidence.account_label == "Fixture organization"
    evidence = await collect_evidence(node_type=NODE, credential_data=CREDS, user_id=USER)
    assert evidence.reachable is True and native.SingleStoreNode.connection_evidence.proves == "account"
    assert evidence.account_label == "Fixture organization"
    provider.foreign_org = True
    with pytest.raises(ValueError): await run("get_organization")

@pytest.mark.parametrize("change", [{"api_key": "Bearer abc"}, {"api_key": "https://foreign.invalid"}, {"api_key": "a\r\nheader"},
    {"api_key": "placeholder"}, {"organization_id": "../foreign"}, {"organization_id": 42}, {"credential_type": "foreign"}])
def test_strict_native_credential_shape(change):
    with pytest.raises(ValueError): native._credential({**CREDS, **change})

@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 302, 307, 202, 204, 401, 403, 404, 429, 500])
async def test_http_errors_no_redirect_retry_or_secret_echo(provider, status, caplog):
    provider.status = status
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(ValueError) as failure: await run("get_organization")
    assert CREDS["api_key"] not in str(failure.value) + caplog.text
    assert len(provider.requests) == 1

@pytest.mark.asyncio
async def test_http200_error_envelope_media_bounds_and_public_transport(provider):
    for raw, media in [(b'{"error":"private"}', "application/json"), (b'{"orgID":null}', "application/json"),
        (b'{"orgID":"a","orgID":"b"}', "application/json"), (b"NaN", "application/json"), (b"{}", "text/html"),
        (b"x" * (native.MAX_BYTES + 1), "application/json"), (json.dumps({"key": CREDS["api_key"]}).encode(), "application/json")]:
        provider.raw, provider.media = raw, media
        with pytest.raises(ValueError): await run("get_organization")
    provider.raw, provider.media, provider.private_dns = None, None, True
    provider.requests.clear()
    with pytest.raises(ValueError): await run("get_organization")
    assert provider.requests == []

@pytest.mark.asyncio
async def test_empty_bounds_parent_membership_and_no_guessed_paging(provider):
    provider.empty = True
    assert (await run("list_projects"))["data"]["items"] == []
    assert (await run("list_clusters", {"project_id": PROJECT}))["data"]["items"] == []
    provider.requests.clear()
    with pytest.raises(ValueError): await native.SingleStoreNode.load_field_options("cluster_id", CREDS, {})
    with pytest.raises(ValueError): await native.SingleStoreNode.load_field_options("project_id", CREDS, page_token="foreign")
    assert provider.requests == []
    provider.foreign_project = True
    with pytest.raises(ValueError): await run("get_cluster", {"project_id": PROJECT, "cluster_id": CLUSTER})
    provider.foreign_project, provider.target = False, "/projects"
    provider.raw = json.dumps([{"projectID": PROJECT}] * 501).encode()
    with pytest.raises(ValueError): await run("list_projects")

@pytest.mark.parametrize("path", ["/", "../x", "x/../y", "x//y", "x%2Fy", "x?private", "x#private", "x\\y", "x\x00y"])
def test_stage_paths_before_requests(path):
    with pytest.raises(ValueError): native._path(path, folder=True)

@pytest.mark.asyncio
async def test_empty_folder_mutation_guards_readbacks_and_download_refusal(provider):
    args = {"project_id": PROJECT, "cluster_id": CLUSTER}
    for operation, more in [("delete_empty_stage_folder", {"folder_path": "full"}),
        ("move_empty_stage_folder", {"folder_path": "full", "new_folder_path": "moved"}),
        ("create_stage_folder", {"folder_path": "empty"})]:
        with pytest.raises(ValueError): await run(operation, {**args, **more})
    assert all(r.method == "GET" for r in provider.requests)
    provider.target, provider.status = "/clusters/" + CLUSTER + "/stage/fs/file.json", 307
    with pytest.raises(ValueError): await run("get_stage_file_metadata", {**args, "file_path": "file.json"})
    provider.target, provider.status, provider.stale_name = None, None, True
    with pytest.raises(ValueError, match="readback"): await run("rename_project", {"project_id": PROJECT, "name": "Updated project"})

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
        if "owner_id" in sql and "FROM workflows" in sql and "FROM credentials" not in sql: return {"owner_id": OWNER}
        if sql.startswith("SELECT 1 FROM workflow_authorized_credentials"): return {"one": 1} if self.authorized else None
        if sql.startswith("SELECT name,owner_id,approval_operations"):
            return {"name": "Fixture", "owner_id": self.row["owner_id"], "approval_operations": ["*"] if self.decision else [], "approval_revision": self.row["approval_revision"], "revoked_at": self.row["revoked_at"]}
        if sql.startswith("SELECT id,status,consumed_at,expires_at"):
            return {"id": UUID(int=100), "status": self.decision, "consumed_at": None, "expires_at": UPDATED.replace(year=2099)}
        if "AS revoked" in sql:
            return {"revoked": self.row["revoked_at"] is not None, "name": "Fixture", "owner_id": self.row["owner_id"], "workflow_owner_id": OWNER}
        if "FROM credentials c" in sql:
            return None if not self.access or self.owner_fallback and args[1] == USER else deepcopy(self.row)
        raise AssertionError("Unexpected synthetic storage query")
    async def fetchval(self, sql, *args):
        return None  # No separate workflow lender in this fixture.
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
        assert (await run("get_organization", credential_id=CID, pool=stored.storage, organization_id=ORG))["data"]["orgID"] == ORG
    else:
        with pytest.raises(ValueError): await run("get_organization", credential_id=CID, pool=stored.storage, organization_id=ORG)
        assert provider.requests == []  # The shared resolver may decrypt before the native family gate.
@pytest.mark.asyncio
@pytest.mark.parametrize("change,value", [("token_version", 99), ("approval_revision", 99), ("owner_id", OWNER), ("updated_at", UPDATED.replace(year=2027)), ("revoked_at", UPDATED), ("credential_type", None)])
async def test_acceptance_rechecks_current_row(stored, provider, change, value):
    provider.after_response = lambda: stored.storage.row.update({change: value})
    with pytest.raises(ValueError): await run("get_organization", credential_id=CID, pool=stored.storage, organization_id=ORG)
    assert len(provider.requests) == 1
@pytest.mark.asyncio
async def test_native_lookup_and_post_connect_access(stored, provider):
    result = await run_node_lookup(node_type=NODE, field_name="project_id", credential_id=CID, user_id=USER, pool=stored.storage, organization_id=ORG)
    assert result["options"][0]["value"] == PROJECT
    assert await native.SingleStoreNode.validate_credential_access(CREDS) == {"valid": True}


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
    data = await _route(monkeypatch, stored, "workflow:node:load_options", WorkflowNodeLoadOptionsRequest, workflow_handler.WorkflowHandler, workflow_handler, {"field_name": "project_id"})
    allowed = family == FAMILY and decision is None
    assert data["success"] is allowed and bool(provider.requests) is allowed
    assert data["options"] == ([{"value": PROJECT, "label": "Fixture project", "metadata": None}] if allowed else [])
    assert CREDS["api_key"] not in json.dumps(data)

@pytest.mark.asyncio
@pytest.mark.parametrize("authorized", [False, True])
async def test_workflow_owner_acl_and_native_lookup(stored, provider, authorized):
    stored.storage.owner_fallback, stored.storage.authorized, stored.storage.row["owner_id"] = True, authorized, OWNER
    if authorized:
        result = await run_node_lookup(node_type=NODE, field_name="project_id", credential_id=CID, user_id=USER, pool=stored.storage, organization_id=ORG, workflow_id=WORKFLOW)
        assert result["options"][0]["value"] == PROJECT
    else:
        with pytest.raises(ValueError):
            await run_node_lookup(node_type=NODE, field_name="project_id", credential_id=CID, user_id=USER, pool=stored.storage, organization_id=ORG, workflow_id=WORKFLOW)
        assert provider.requests == []

@pytest.mark.asyncio
async def test_account_key_and_actor_org_changes_refuse_acceptance(stored, provider, monkeypatch):
    from wss.handlers import workflow_handler
    provider.after_response = lambda: monkeypatch.setattr(workflow_handler, "get_user_org_context", AsyncMock(return_value=str(UUID(int=9))))
    with pytest.raises(ValueError, match="context changed"):
        await run("get_organization", credential_id=CID, pool=stored.storage, organization_id=ORG)
    monkeypatch.setattr(workflow_handler, "get_user_org_context", AsyncMock(return_value=ORG))
    provider.after_response = lambda: setattr(stored.crypto.decrypt_credential, "side_effect", lambda _: {**CREDS, "api_key": "abcdef42abcdef42abcdef42abcdef42abcdef42abcdef42abcdef42abcdef42ab"})
    provider.requests.clear()
    with pytest.raises(ValueError, match="binding changed"):
        await run("list_projects", credential_id=CID, pool=stored.storage, organization_id=ORG)
    assert len(provider.requests) == 1

@pytest.mark.asyncio
async def test_inaccessible_revoked_and_invalid_plaintext_before_http(stored, provider):
    for kind in ("inaccessible", "revoked", "invalid"):
        stored.storage.access = kind != "inaccessible"
        stored.storage.row["revoked_at"] = UPDATED if kind == "revoked" else None
        stored.crypto.decrypt_credential.side_effect = lambda _: {**CREDS, "api_key": "bad header"} if kind == "invalid" else dict(CREDS)
        with pytest.raises(PermissionError if kind == "revoked" else ValueError):
            await run("get_organization", credential_id=CID, pool=stored.storage, organization_id=ORG)
        assert provider.requests == []
@pytest.mark.asyncio
@pytest.mark.parametrize("family", [None, "foreign-family"])
async def test_native_picker_rechecks_authoritative_family_before_decrypt(stored, provider, family):
    stored.storage.row["credential_type"] = family
    stored.crypto.decrypt_credential.side_effect = lambda _: dict(CREDS)
    with pytest.raises(ValueError):
        credential = await native.SingleStoreNode.freshen_credential(CREDS, credential_id=CID, user_id=USER, pool=stored.storage)
        await native.SingleStoreNode.load_field_options("project_id", credential)
    assert not stored.crypto.decrypt_credential.called and provider.requests == []

@pytest.mark.asyncio
async def test_actual_dependent_socket_picker_and_selected_operation(stored, provider, monkeypatch):
    from wss.handlers import workflow_handler
    from wss.receiver.client_events import WorkflowNodeLoadOptionsRequest
    data = await _route(monkeypatch, stored, "workflow:node:load_options", WorkflowNodeLoadOptionsRequest,
        workflow_handler.WorkflowHandler, workflow_handler, {"field_name": "cluster_id", "context": {"project_id": PROJECT}})
    assert data["success"] is True and data["options"] == [{"value": CLUSTER, "label": "Fixture cluster", "metadata": None}]
    selected = data["options"][0]["value"]
    assert (await run("get_cluster", {"project_id": PROJECT, "cluster_id": selected}))["data"]["clusterID"] == CLUSTER
    provider.requests.clear()
    invalid = await _route(monkeypatch, stored, "workflow:node:load_options", WorkflowNodeLoadOptionsRequest,
        workflow_handler.WorkflowHandler, workflow_handler, {"field_name": "cluster_id", "context": {}})
    assert invalid["success"] is False and invalid["options"] == [] and provider.requests == []

@pytest.mark.asyncio
@pytest.mark.parametrize("status,timeout,expected", [(None, False, True), (401, False, False), (403, False, False), (None, True, None)])
async def test_node_post_connect_access(provider, status, timeout, expected):
    provider.status, provider.timeout = status, timeout
    assert (await native.SingleStoreNode.validate_credential_access(CREDS))["valid"] is expected

@pytest.mark.asyncio
async def test_freshen_credential_matches_base_hook_and_binds_picker_authority(stored):
    import inspect
    from nodes.core.base import WorkflowNode

    actual = inspect.signature(native.SingleStoreNode.freshen_credential).parameters
    expected = inspect.signature(WorkflowNode.freshen_credential).parameters
    assert list(actual) == list(expected)
    assert [(p.kind, p.default) for p in actual.values()] == [(p.kind, p.default) for p in expected.values()]
    assert await native.SingleStoreNode.freshen_credential(CREDS) == CREDS
    bound = await native.SingleStoreNode.freshen_credential(
        CREDS, pool=stored.storage, user_id=USER, credential_id=CID,
    )
    assert (bound.pool, bound.user_id, bound.credential_id, bound.workflow_id) == (stored.storage, USER, CID, None)
