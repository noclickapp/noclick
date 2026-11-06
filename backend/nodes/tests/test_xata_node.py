"""Xata contracts through the real node factory and connection-evidence collector.
Provider responses are deterministic fixtures; these checks do not prove live access.
"""
from dataclasses import asdict
import json
from types import SimpleNamespace

import httpx
import pytest
from nodes import xata_node as ad
from nodes.core.base import ConfigValidationError
from nodes.core.connection_evidence import EvidenceSample
from nodes.core.registry import NODE_REGISTRY, NodeFactory

USER = "00000000-0000-0000-0000-000000000001"
WF = "00000000-0000-0000-0000-000000000002"
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
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(ad, "guarded_async_client", client)
    return state


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
    assert defs["XataGetBackupConfig"]["properties"]["backup_id"]["x-dynamic-options"]["field_name"] == "backup_id"
    assert defs["XataIssuedOAuthCredential"]["required"] == ["access_token", "granted_scopes"]
    assert defs["XataGetBackupConfig"]["properties"]["backup_id"]["x-dynamic-options"]["depends_on"] == "project_id"
    assert defs["XataGetBackupConfig"]["properties"]["project_id"]["x-dynamic-options"]["depends_on"] == "organization_id"
    operations = {v["properties"]["operation"]["const"] for v in defs.values() if "operation" in v.get("properties", {})}
    assert operations == {"check_connection", "list_organizations", "get_organization", "list_projects", "get_project", "list_branches", "list_backups", "get_backup"}
    with pytest.raises(ConfigValidationError, match="get_branch.*not a valid option"):
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
async def test_actual_manual_connect_reports_catalog_reachability_without_identity(http, monkeypatch):
    from nodes.core import credential_connect
    from nodes.core.connection_evidence import collect_evidence
    monkeypatch.setattr(credential_connect, "_collect_evidence", collect_evidence)
    http.responses = [catalog("organizations", organization())]
    result = await credential_connect.validate_for_connect(credential_type="xata_issued_oauth", credential_data=credential(), user_id=USER)
    assert result.ok and result.node_type == NODE and result.evidence.reachable is True
    assert ad.XataNode.connection_evidence.proves == "reachability" and result.evidence.samples == [EvidenceSample(label=OID)] and result.evidence.account_label is None
    assert "private-sentinel" not in json.dumps(asdict(result.evidence))


@pytest.mark.asyncio
async def test_legacy_validation_hook_leaves_reachability_to_admitted_evidence(http):
    out = await ad.XataNode.validate_credential_access(credential())
    assert out["valid"] is None and "Check connection" in out["error"]
    out = await ad.XataNode.validate_credential_access(credential(expires_at="2000-01-01T00:00:00Z"))
    assert out["valid"] is False
    assert http.calls == []


@pytest.mark.asyncio
async def test_loader_hook_validates_current_blob_without_refreshing_or_losing_metadata(http):
    current = await ad.XataNode.freshen_credential(credential(access_token="current-token", manager_flag="keep"))
    assert current["access_token"] == "current-token" and current["manager_flag"] == "keep"
    with pytest.raises(ValueError):
        await ad.XataNode.freshen_credential(credential(credential_type="other"))
    assert http.calls == []


@pytest.mark.parametrize("field", ["page_token", "connectionString"])
def test_config_rejects_obsolete_paging_and_connection_fields(field):
    with pytest.raises(ConfigValidationError):
        make_node("get_project", **{field: "obsolete"})
