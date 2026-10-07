"""Prepared UNRUN: MediaSilo actual native seams and bounded metadata reads."""
import json
import logging
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from nodes import mediasilo_node as fn
from nodes.core.registry import NodeFactory
from nodes.core.run_op import run_node_operation, run_node_lookup
from repositories.credentials import CredentialValidationRow

CREDS = {"credential_type": "mediasilo_api_key", "api_key": "synthetic+/=key", "api_secret": "synthetic+/=secret"}
STAMP = datetime(2026, 10, 7, tzinfo=timezone.utc)
PROJECT = {"id": "project-1", "accountId": 7, "name": "Owned project", "dateCreated": "2026-10-07T00:00:00Z", "lastActivity": 1791331200, "folderCount": 1, "ownerId": "omit owner", "owner": {"email": "omit email", "secret": "omit secret"}, "description": "omit description", "poster": "omit URL", "isDRM": True, "aggregates": {"credentials": "omit key"}}
FOLDER = {"id": "folder-1", "projectId": "project-1", "name": "Owned folder", "parentId": "folder-parent", "folderCount": 0, "assetsCount": 3, "size": 123, "settings": {"secret": "omit secret"}, "shareUrl": "omit URL"}
OPS = ["test_connection", "list_projects", "get_project", "list_folders", "get_folder"]

@pytest.fixture(autouse=True)
def ensure_native_db_pool(): yield

class Response:
    def __init__(self, body=None, *, status=200, raw=None, mime="application/json;charset=utf-8", after=None):
        self.body, self.raw, self.status_code, self.after = body, raw, status, after
        self.headers = {"Content-Type": mime}
    async def __aenter__(self): return self
    async def __aexit__(self, *args):
        if self.after: self.after()
    async def aiter_bytes(self, chunk_size):
        assert chunk_size == 65536
        yield self.raw if self.raw is not None else json.dumps(self.body).encode("utf-8")

@pytest.fixture
def wire(monkeypatch):
    calls, responses = [], []
    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        def stream(self, method, url, **kwargs):
            calls.append({"method": method, "url": url, **kwargs})
            logging.getLogger("httpx").info("private %s %s", url, kwargs)
            response = responses.pop(0)
            return response if isinstance(response, Response) else Response(response)
    def client(**kwargs):
        assert kwargs == {"require_public": True, "timeout": 20.0, "follow_redirects": False, "trust_env": False}
        return Client()
    monkeypatch.setattr(fn, "guarded_async_client", client)
    return SimpleNamespace(calls=calls, responses=responses)

def folder_catalog(wire, body=None):
    wire.responses.extend([[PROJECT], PROJECT, [FOLDER] if body is None else body, PROJECT])

async def run(op, args=None, *, credential_data=None, **context):
    return await run_node_operation(node_type=fn.NODE_TYPE, operation=op, arguments=args or {}, credential_data=credential_data or CREDS, user_id="actor", **context)

def test_actual_factory_closed_schema_and_original_saved_family():
    node = NodeFactory.create_node(node_id="native", node_type=fn.NODE_TYPE, user_id="actor", node_data={"config": {"operation": "get_folder", "project_id": "project-1", "folder_id": "folder-1"}, "credentials": CREDS})
    assert node.config.config.folder_id == "folder-1" and node.config.credentials.api_secret == CREDS["api_secret"]
    defs = fn.MediaSiloNode.get_config_schema()["$defs"]
    assert sorted(d["properties"]["operation"]["const"] for d in defs.values() if "operation" in d.get("properties", {})) == sorted(OPS)
    assert defs["MediaSiloFolderConfig"]["properties"]["folder_id"]["x-dynamic-options"]["depends_on"] == "project_id"
    for family in (None, "http_bearer", "mediasilo_oauth"):
        data = {"credential_id": "saved", "config": {"operation": "test_connection"}, "credentials": {**CREDS, "credential_type": family}}
        assert fn.MediaSiloNode.validate_config(data)["valid"] is False
        with pytest.raises(ValueError, match="family"): fn.MediaSiloNode.parse_config(data)

@pytest.mark.parametrize("cfg", [{"operation": "get_folder", "folder_id": "folder-1"}, {"operation": "get_project", "project_id": "../other"}, {"operation": "get_folder", "project_id": "project-1", "folder_id": True}, {"operation": "list_projects", "page": 2}, {"operation": "list_projects", "cursor": "opaque"}, {"operation": "test_connection", "url": "https://evil.test"}, {"operation": "get_asset"}, {"operation": "create_project"}, {"operation": "download"}])
def test_closed_config_no_guessed_paging_or_media_control(cfg):
    with pytest.raises(ValueError): fn.MediaSiloNode.parse_config({"config": cfg, "credentials": CREDS})

@pytest.mark.asyncio
async def test_actual_dispatch_fixed_two_headers_reachability_and_transport_privacy(wire, caplog):
    wire.responses.append([PROJECT])
    with caplog.at_level(logging.DEBUG): result = await run("test_connection")
    assert wire.calls == [{"method": "GET", "url": fn.BASE + "/projects", "headers": {"x-key": CREDS["api_key"], "x-secret": CREDS["api_secret"], "Accept": "application/json"}}]
    proof = result["data"]
    assert proof["proves"] == "reachability" and proof["account_identity_verified"] is False and proof["account_ownership_verified"] is False
    assert proof["results"] == [{"id": "project-1", "accountId": 7, "dateCreated": PROJECT["dateCreated"], "lastActivity": 1791331200, "folderCount": 1}]
    assert proof["pagination"]["completion_verified"] is False and proof["pagination"]["continuation_supported"] is False
    assert all(value not in caplog.text for value in CREDS.values()) and fn._PRIVATE_REQUEST.get() is False
    logging.getLogger("httpx").warning("unrelated context"); assert "unrelated context" in caplog.text

@pytest.mark.asyncio
async def test_actual_folder_dispatch_catalog_detail_ancestry_and_closed_projection(wire):
    folder_catalog(wire); wire.responses.extend([FOLDER, [PROJECT], PROJECT])
    result = await run("get_folder", {"project_id": "project-1", "folder_id": "folder-1", "include_names": True})
    assert [c["url"] for c in wire.calls] == [fn.BASE + p for p in ["/projects", "/projects/project-1", "/projects/project-1/folders", "/projects/project-1", "/folders/folder-1", "/projects", "/projects/project-1"]]
    assert result["data"]["folder"] == {"id": "folder-1", "projectId": "project-1", "parentId": "folder-parent", "folderCount": 0, "assetsCount": 3, "size": 123, "name": "Owned folder"}
    assert result["data"]["returned_folder_project_id_verified"] is True
    assert "omit" not in json.dumps(result) and "owner" not in result["data"]["folder"]
    wire.responses.extend([[PROJECT], PROJECT]); project = await run("get_project", {"project_id": "project-1", "include_names": True})
    assert project["data"]["project"]["name"] == "Owned project" and "isDRM" not in json.dumps(project)
    folder_catalog(wire); catalog = await run("list_folders", {"project_id": "project-1"})
    assert "name" not in catalog["data"]["folders"][0]

@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["not_listed", "detail_id", "account", "folder_project", "after_account", "folder_detail_id", "folder_detail_project"])
async def test_actual_returned_ancestry_not_requested_identity(wire, case):
    if case == "not_listed": wire.responses.append([])
    else:
        wire.responses.extend([[PROJECT], {**PROJECT, **({"id": "other-project"} if case == "detail_id" else {"accountId": 8} if case == "account" else {})}])
        if case not in ("detail_id", "account"):
            wire.responses.extend([[{**FOLDER, **({"projectId": "other-project"} if case == "folder_project" else {})}], {**PROJECT, **({"accountId": 8} if case == "after_account" else {})}])
            if case.startswith("folder_detail"):
                wire.responses.append({**FOLDER, **({"id": "other-folder"} if case == "folder_detail_id" else {"projectId": "other-project"})})
    with pytest.raises(fn.MediaSiloAPIError): await run("get_folder", {"project_id": "project-1", "folder_id": "folder-1"})
    assert len(wire.calls) <= 5

@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{"projects": [PROJECT]}, {"error": "private"}, {"status": "rejected", **PROJECT}, [PROJECT, PROJECT], [{**PROJECT, "id": True}], [{**PROJECT, "accountId": "7"}], [{**PROJECT, "folderCount": -1}], [{**PROJECT, "dateCreated": "unknown"}]])
async def test_http200_wrong_envelope_error_duplicate_or_metadata_never_success(wire, body):
    wire.responses.append(body)
    with pytest.raises(fn.MediaSiloAPIError): await run("list_projects")
    assert len(wire.calls) == 1

@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["401", "403", "429", "503", "204", "html", "empty", "duplicate", "nan", "deep", "oversize", "too_many"])
async def test_bounds_errors_no_replay_and_no_secret_echo(wire, monkeypatch, case):
    response = Response([PROJECT])
    if case.isdigit(): response = Response(status=int(case), raw=b"private", mime="text/html")
    if case == "html": response.headers["Content-Type"] = "text/html"
    if case == "empty": response.raw = b""
    if case == "duplicate": response.raw = b'[{"id":"project-1","id":"other","name":"Owned"}]'
    if case == "nan": response.raw = b'[{"id":"project-1","name":"Owned","opaque":1e309}]'
    if case == "deep": response.raw = b'[' * 40 + b'0' + b']' * 40
    if case == "oversize": monkeypatch.setattr(fn, "MAX_BYTES", 32)
    if case == "too_many": response.body = [PROJECT] * 1001
    wire.responses.append(response)
    with pytest.raises(fn.MediaSiloAPIError) as error: await run("test_connection")
    assert error.value.authority_rejected is False and all(v not in str(error.value) for v in CREDS.values()) and len(wire.calls) == 1 and fn._PRIVATE_REQUEST.get() is False

@pytest.mark.asyncio
async def test_picker_bound_parent_id_only_labels_no_continuation_or_name_leak(wire):
    folder_catalog(wire)
    result = await fn.MediaSiloNode.load_field_options("folder_id", CREDS, {"_user_id": "actor", "project_id": "project-1"}, search="folder-1")
    assert result == {"options": [{"value": "folder-1", "label": "folder-1"}], "next_page_token": None}
    with pytest.raises(ValueError): await fn.MediaSiloNode.load_field_options("folder_id", CREDS, {"_user_id": "actor"})
    with pytest.raises(ValueError, match="continuation"): await fn.MediaSiloNode.load_field_options("project_id", CREDS, {"_user_id": "actor"}, page_token="remote")
    assert len(wire.calls) == 4
    with pytest.raises(fn.MediaSiloAPIError): fn._folder_metadata({**FOLDER, "parentId": "folder-1"}, "project-1")

@pytest.mark.asyncio
async def test_both_keys_redacted_and_optional_witnesses_remain_unknown(wire):
    wire.responses.extend([[{**PROJECT, "accountId": None}], {**PROJECT, "accountId": None, "name": "synthetic%2b%2F%3dkey synthetic%2B%2f%3Dsecret", "status": {"opaque": True}}])
    result = await run("get_project", {"project_id": "project-1", "include_names": True})
    assert result["data"]["project"]["name"] == "[redacted] [redacted]" and "accountId" not in result["data"]["project"]
    assert fn._folder_metadata({**FOLDER, "parentId": None}, "project-1").get("parentId") is None

@pytest.mark.asyncio
async def test_current_raw_canonical_row_stored_picker_actor_binding_and_no_forged_blob_type(monkeypatch, wire):
    from nodes.core import run_op
    from repositories.credentials import CredentialsRepo
    from repositories.credential_approvals import CredentialApprovalRepo
    from utils import encryption
    pool = object(); row = CredentialValidationRow(fn.FAMILIES[0], "owner", 2, STAMP, 1, None, "sealed")
    authority = AsyncMock(return_value=row); monkeypatch.setattr(CredentialsRepo, "fetch_validation_authority", authority)
    monkeypatch.setattr(encryption, "get_encryption", lambda: SimpleNamespace(decrypt_credential=lambda _: {**CREDS, "credential_type": "http_bearer", "owner_id": "forged"}))
    fresh = await fn.MediaSiloNode.freshen_credential(CREDS, pool=pool, user_id="actor", credential_id="saved", organization_id="org", workflow_id="wf")
    assert fresh["credential_type"] == fn.FAMILIES[0] and fresh["owner_id"] == "owner" and fresh["token_version"] == 2 and fresh["approval_revision"] == 1
    context = fn._context(fresh, {"_user_id": "actor", "_approval_pool": "forged", "_credential_id": "forged"})
    assert context["_approval_pool"] is pool and context["_credential_id"] == "saved"
    with pytest.raises(ValueError, match="actor"): fn._context(fresh, {"_user_id": "other"})
    monkeypatch.setattr(run_op, "resolve_operation_credential", AsyncMock(return_value=CREDS)); monkeypatch.setattr(CredentialApprovalRepo, "admit", AsyncMock(return_value=None))
    wire.responses.append([PROJECT]); result = await run_node_lookup(node_type=fn.NODE_TYPE, field_name="project_id", credential_id="saved", user_id="actor", pool=pool, organization_id="org", workflow_id="wf", context={})
    assert result["options"] == [{"value": "project-1", "label": "project-1"}] and len(wire.calls) == 1 and all(call.args == ("saved", "actor", "org") for call in authority.call_args_list)

@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["missing", "revoked", "foreign"])
async def test_current_denial_before_decrypt_client(monkeypatch, wire, state):
    from repositories.credentials import CredentialsRepo
    from utils import encryption
    row = CredentialValidationRow(fn.FAMILIES[0], "owner", 2, STAMP, 1, None, "sealed")
    row = None if state == "missing" else replace(row, revoked_at=STAMP) if state == "revoked" else replace(row, credential_type="http_bearer")
    monkeypatch.setattr(CredentialsRepo, "fetch_validation_authority", AsyncMock(return_value=row)); monkeypatch.setattr(encryption, "get_encryption", lambda: (_ for _ in ()).throw(AssertionError("No decrypt")))
    with pytest.raises(ValueError): await fn.MediaSiloNode.freshen_credential(CREDS, pool=object(), user_id="actor", credential_id="saved", organization_id="org")
    assert wire.calls == []

@pytest.mark.asyncio
async def test_raw_binding_changes_before_after_refusal_and_after_parser(monkeypatch, wire):
    from repositories.credential_approvals import CredentialApprovalRepo
    monkeypatch.setattr(CredentialApprovalRepo, "admit", AsyncMock(return_value=None))
    raw = {**CREDS, "owner_id": "owner", "token_version": 3, "approval_revision": 4, "updated_at": STAMP.isoformat()}; state = {"data": fn._shape(raw)}
    async def current(data, **context): return state["data"]
    monkeypatch.setattr(fn, "_current_data", current)
    wire.responses.append([PROJECT]); await run("test_connection", credential_data=raw, credential_id="saved", pool=object())
    state["data"] = {**fn._shape(raw), "api_key": "changed-synthetic-key"}
    with pytest.raises(fn.MediaSiloAPIError, match="binding changed"): await run("test_connection", credential_data=raw, credential_id="saved", pool=object())
    state["data"] = fn._shape(raw); wire.responses.append(Response(status=403, after=lambda: state.update(data={**fn._shape(raw), "approval_revision": 9})))
    with pytest.raises(fn.MediaSiloAPIError, match="changed"): await run("test_connection", credential_data=raw, credential_id="saved", pool=object())
    state["data"] = fn._shape(raw); original = fn._project_metadata
    def metadata(*args, **kwargs):
        result = original(*args, **kwargs); state["data"] = {**fn._shape(raw), "token_version": 10}; return result
    monkeypatch.setattr(fn, "_project_metadata", metadata); wire.responses.append([PROJECT])
    with pytest.raises(fn.MediaSiloAPIError, match="changed"): await run("test_connection", credential_data=raw, credential_id="saved", pool=object())
    assert len(wire.calls) == 3

@pytest.mark.asyncio
@pytest.mark.parametrize("change", [{"api_key": "changed-key"}, {"api_secret": "changed-secret"}, {"owner_id": "other-owner"}, {"token_version": 9}, {"approval_revision": 9}])
async def test_saved_execute_rejects_original_scope_and_policy_changes_before_client(monkeypatch, wire, change):
    raw = {**CREDS, "owner_id": "owner", "token_version": 3, "approval_revision": 4, "updated_at": STAMP.isoformat()}
    monkeypatch.setattr(fn, "_current_data", AsyncMock(return_value=fn._shape({**raw, **change})))
    node = NodeFactory.create_node(node_id="native", node_type=fn.NODE_TYPE, user_id="actor", node_data={"config": {"operation": "test_connection"}, "credentials": raw, "credential_id": "saved", "_approval_pool": object()})
    with pytest.raises(fn.MediaSiloAPIError, match="binding changed"): await node.execute({})
    assert wire.calls == []

@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["pending", "rejected"])
async def test_actual_operation_and_stored_picker_admission_before_header_wire(monkeypatch, wire, status):
    from nodes.core import run_op
    from repositories.credential_approvals import CredentialApprovalRepo
    monkeypatch.setattr(run_op, "resolve_operation_credential", AsyncMock(return_value=CREDS)); monkeypatch.setattr(CredentialApprovalRepo, "admit", AsyncMock(return_value={"status": status, "id": "approval", "new_request": False}))
    result = await run("test_connection", credential_id="saved", pool=object()); assert result["executed"] is False
    result = await run_node_lookup(node_type=fn.NODE_TYPE, field_name="project_id", credential_id="saved", user_id="actor", pool=object(), context={})
    assert result["status"] in ("pending_approval", "rejected") and wire.calls == []

@pytest.mark.asyncio
async def test_actual_postconnect_handler_empty_reachability_evidence_and_tristate(monkeypatch, wire):
    from nodes.core import run_op
    from nodes.core.credential_validation import CredentialValidationContext, CredentialValidationUnavailable, CredentialValidationUnverified
    from nodes.core.connection_evidence import collect_evidence
    from repositories.credential_approvals import CredentialApprovalRepo
    from wss.handlers import credentials_handler as hm
    from wss.receiver.client_events import CredentialValidateAccessRequest
    row = CredentialValidationRow(fn.FAMILIES[0], "owner", 2, STAMP, 0, None, "sealed"); context = CredentialValidationContext("saved", fn.NODE_TYPE, "actor", "org", object(), row)
    monkeypatch.setattr(CredentialValidationContext, "create", AsyncMock(return_value=context)); monkeypatch.setattr(CredentialValidationContext, "revalidate", AsyncMock(return_value=row)); monkeypatch.setattr(run_op, "resolve_operation_credential", AsyncMock(return_value=CREDS)); monkeypatch.setattr(CredentialApprovalRepo, "admit", AsyncMock(return_value=None)); monkeypatch.setattr(fn, "_current_data", AsyncMock(return_value=fn._shape(CREDS)))
    sent = []
    async def capture(_sio, sid, response): sent.append(response.model_dump()["data"])
    monkeypatch.setattr(hm, "send_event", capture); sio = AsyncMock(); sio.get_session.return_value = {"user_id": "actor"}
    handler = hm.CredentialsHandler(sio); handler.get_pool = AsyncMock(return_value=context.pool); request = CredentialValidateAccessRequest(request_id="fixture", credential_id="saved", node_type=fn.NODE_TYPE)
    wire.responses.append([]); await handler.get_events()[request.event_name]("sid", request)
    assert sent[-1]["valid"] is True and sent[-1]["proves"] == "reachability" and sent[-1]["account_identity_verified"] is False
    wire.responses.append([]); evidence = await collect_evidence(node_type=fn.NODE_TYPE, credential_data=CREDS, user_id="actor")
    assert evidence.reachable is True and evidence.proves == "reachability" and evidence.samples == []
    wire.responses.append(Response(status=403, raw=b"private", mime="text/html")); assert (await collect_evidence(node_type=fn.NODE_TYPE, credential_data=CREDS, user_id="actor")).reachable is None
    assert (await fn.MediaSiloNode.validate_credential_access(CREDS))["valid"] is None
    for error, valid in [(CredentialValidationUnavailable("revoked"), False), (CredentialValidationUnverified("unknown"), None), (fn.MediaSiloAPIError("Authority unavailable", authority_rejected=True), False), (fn.MediaSiloAPIError("Request refused", http_status=403), None)]:
        monkeypatch.setattr(CredentialValidationContext, "run_operation", AsyncMock(side_effect=error)); assert (await fn.MediaSiloNode.validate_credential_access(CREDS, validation_context=context))["valid"] is valid

@pytest.mark.asyncio
@pytest.mark.parametrize("grant", [False, True])
async def test_actor_first_owner_fallback_requires_positive_workflow_grant(monkeypatch, wire, grant):
    from repositories.credentials import CredentialsRepo
    from utils import credentials, encryption
    row = CredentialValidationRow(fn.FAMILIES[0], "owner", 2, STAMP, 1, None, "sealed")
    authority = AsyncMock(side_effect=[None, row] if grant else [None]); monkeypatch.setattr(CredentialsRepo, "fetch_validation_authority", authority); monkeypatch.setattr(credentials, "get_workflow_owner_id", AsyncMock(return_value="owner")); allowed = AsyncMock(return_value=grant); monkeypatch.setattr(credentials, "is_credential_authorized_for_workflow", allowed)
    monkeypatch.setattr(encryption, "get_encryption", lambda: SimpleNamespace(decrypt_credential=lambda _: CREDS) if grant else (_ for _ in ()).throw(AssertionError("No decrypt")))
    if grant:
        fresh = await fn.MediaSiloNode.freshen_credential(CREDS, pool=object(), user_id="actor", credential_id="saved", organization_id="org", workflow_id="wf"); assert fresh["owner_id"] == "owner" and fresh["_mediasilo_authority"].user_id == "actor"
    else:
        with pytest.raises(ValueError, match="unavailable"): await fn.MediaSiloNode.freshen_credential(CREDS, pool=object(), user_id="actor", credential_id="saved", organization_id="org", workflow_id="wf")
    assert [call.args[1] for call in authority.call_args_list] == (["actor", "owner"] if grant else ["actor"]) and allowed.call_args.args[1:] == ("wf", "saved") and wire.calls == []
