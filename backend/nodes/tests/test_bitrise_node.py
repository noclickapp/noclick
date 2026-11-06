"""Prepared Bitrise regressions use real factory, authority, admission and socket seams.
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
from nodes import bitrise_node as ad
from nodes.core.registry import NODE_REGISTRY, NodeFactory
from nodes.core.connection_evidence import EvidenceSample
from tests.test_oauth_refresh_authority import _Storage as AuthorityStorage, CID, USER, OWNER, ORG, WF
from tests.test_post_connect_validation_context import _Storage as AdmissionStorage
from wss.receiver.client_events import WorkflowNodeLoadOptionsRequest, CredentialValidateAccessRequest

NODE = "automation-bitrise"
APP, BUILD, OTHER = "app-a", "build-a", "app-b"


@pytest.fixture
def ensure_native_db_pool():
    yield


def credential(**updates):
    return {"credential_type": "bitrise_api_token", "access_token": "fixture-token", **updates}


def make_node(operation, data=None, **config):
    target = {"app_slug": APP} if operation in {"get_app", "list_branches", "list_builds", "get_build"} else {}
    if operation == "get_build":
        target["build_slug"] = BUILD
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
        self.row.update(id=CID, credential_type="bitrise_api_token",
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


def app(**updates):
    return {"slug": APP, "project_type": "ios", "status": 1, "title": "Fixture App",
        "owner": {"email": "private@example.invalid"}, "repo_url": "https://private.invalid",
        "repo_owner": "sensitive-provider-sentinel", "avatar_url": "https://private.invalid", **updates}


def build(**updates):
    return {"slug": BUILD, "build_number": 9007199254740993, "status": 1, "branch": "main",
        "triggered_at": "2026-10-07T00:00:00Z", "finished_at": None,
        "commit_hash": "sensitive-provider-sentinel", "commit_message": "sensitive-provider-sentinel",
        "commit_view_url": "https://private.invalid", "original_build_params": {"secret": "sensitive-provider-sentinel"},
        "triggered_by": "private@example.invalid", "credit_cost": 100, "rebuildable": True, **updates}


def page(*rows, following=None, total=None, limit=None):
    paging = {}
    if following is not None:
        paging["next"] = following
    if total is not None:
        paging["total_item_count"] = total
    if limit is not None:
        paging["page_item_limit"] = limit
    return (200, {"data": list(rows), "paging": paging})


def test_actual_factory_has_six_closed_configs_raw_token_and_current_parent():
    assert NODE_REGISTRY[NODE] is ad.BitriseNode
    schema = ad.BitriseNode.get_config_schema()
    defs = schema["$defs"]
    assert len(schema["properties"]["config"]["oneOf"]) == 6
    cred = defs["BitriseAPITokenCredential"]
    assert cred["required"] == ["access_token"] and "actor_id" not in cred["properties"]
    assert cred["properties"]["access_token"]["ui:widget"] == "password"
    assert "x-oauth-provider" not in cred
    assert defs["BitriseAppsConfig"]["properties"]["limit"]["maximum"] == 50
    assert defs["BitriseGetBuildConfig"]["required"] == ["app_slug", "build_slug"]
    assert defs["BitriseGetBuildConfig"]["properties"]["build_slug"]["x-dynamic-options"]["depends_on"] == "app_slug"
    for config in ({"operation": "trigger_build"}, {"operation": "get_secrets"},
        {"operation": "list_apps", "limit": 51}, {"operation": "list_apps", "limit": True},
        {"operation": "list_apps", "next": "https://private.invalid"},
        {"operation": "get_build", "app_slug": APP, "build_slug": "../foreign"}):
        with pytest.raises(ValidationError):
            ad.BitriseNodeConfig.model_validate({"config": config, "credentials": credential()})


@pytest.mark.parametrize("updates", [{"access_token": ""}, {"access_token": "Bearer x"},
    {"access_token": "https://private.invalid"}, {"access_token": 123}, {"access_token": "x"*8193},
    {"credential_type": "bitrise_addon"}])
def test_raw_family_and_header_bounds(updates):
    with pytest.raises(ValueError):
        ad._credential(credential(**updates))


def test_actual_factory_error_does_not_expose_token():
    with pytest.raises(ValueError) as failure:
        make_node("check_connection", data=credential(access_token="sensitive-provider-sentinel invalid"))
    assert "sensitive-provider-sentinel" not in str(failure.value)


@pytest.mark.asyncio
async def test_foreign_unsaved_family_stops_before_http(http):
    with pytest.raises(ValueError):
        await make_node("check_connection", data=credential(credential_type="other")).execute({})
    assert http.calls == []


@pytest.mark.asyncio
async def test_connection_reads_protected_apps_raw_authorization_without_actor_invention(http):
    http.responses = [page(app(), total=1, limit=50)]
    out = await make_node("check_connection").execute({})
    assert out["protected_catalog"] is True
    assert out["items"] == [{"slug": APP, "status": 1, "project_type": "ios"}]
    assert "current_user_id" not in out and "workspace_id" not in out
    req = http.calls[0]
    assert req.method == "GET" and req.url.host == "api.bitrise.io" and req.url.path == "/v0.1/apps"
    assert dict(req.url.params) == {"limit": "50"}
    assert req.headers["Authorization"] == "fixture-token" and "Bitrise-Addon-Auth-Token" not in req.headers
    assert req.headers["Accept"] == "application/json" and req.headers["User-Agent"].startswith("NoClick")
    assert "private.invalid" not in json.dumps(out) and "private@example.invalid" not in json.dumps(out)


@pytest.mark.asyncio
async def test_empty_catalog_is_reachable_without_identity(http):
    http.responses = [page(total=0, limit=50)]
    out = await make_node("check_connection").execute({})
    assert out["protected_catalog"] is True and out["items"] == [] and out["total_item_count"] == "0"
    assert out["has_more"] is False and out["next_page_token"] is None


@pytest.mark.asyncio
async def test_app_detail_is_current_catalog_witnessed_and_slug_checked(http):
    http.responses = [page(app()), (200, {"data": app()})]
    out = await make_node("get_app", include_names=True).execute({})
    assert out["app"] == {"slug": APP, "status": 1, "project_type": "ios", "title": "Fixture App"}
    assert [req.url.path for req in http.calls] == ["/v0.1/apps", "/v0.1/apps/app-a"]
    assert not http.calls[-1].url.params and "owner" not in out["app"]


@pytest.mark.asyncio
async def test_build_catalog_and_detail_use_exact_selected_app_url_ancestry(http):
    http.responses = [page(app()), page(build()), (200, {"data": build()})]
    out = await make_node("get_build").execute({})
    assert out["selected_app_slug"] == APP and out["build"]["slug"] == BUILD
    assert out["build"]["build_number"] == "9007199254740993" and out["build"]["finished_at"] is None
    assert [req.url.path for req in http.calls] == ["/v0.1/apps", "/v0.1/apps/app-a/builds", "/v0.1/apps/app-a/builds/build-a"]
    assert "app_slug" not in out["build"] and "owner" not in out["build"] and "parent" in out["ancestry"]
    assert not {"branch", "commit_hash", "credit_cost", "original_build_params", "triggered_by", "rebuildable"} & out["build"].keys()
    assert "sensitive-provider-sentinel" not in json.dumps(out) and "private.invalid" not in json.dumps(out)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["app", "build-catalog", "detail-slug"])
async def test_missing_or_replaced_parent_stops_outsider_detail(http, failure):
    http.responses = [page(app(slug=OTHER) if failure == "app" else app())]
    if failure != "app":
        http.responses += [page(build(slug="other-build") if failure == "build-catalog" else build())]
    if failure == "detail-slug":
        http.responses += [(200, {"data": build(slug="other-build")})]
    with pytest.raises((ValueError, RuntimeError)):
        await make_node("get_build").execute({})
    assert len(http.calls) == {"app": 1, "build-catalog": 2, "detail-slug": 3}[failure]


@pytest.mark.asyncio
async def test_provider_anchor_overrides_short_page_inference_and_preserves_actual_counts(http):
    http.responses = [page(app(), following="next-app", total=8, limit=2)]
    first = await make_node("list_apps", limit=2).execute({})
    assert first["provider_returned"] == 1 and first["has_more"] is True and first["total_item_count"] == "8"
    assert first["page_item_limit"] == 2 and first["next_page_token"]
    calls = len(http.calls)
    for args in ({"include_names": True}, {"limit": 1}, {"data": credential(access_token="current-token")}):
        with pytest.raises(ValueError):
            await make_node("list_apps", limit=args.get("limit", 2), page_token=first["next_page_token"],
                **{k: v for k, v in args.items() if k != "limit"}).execute({})
    assert len(http.calls) == calls
    http.responses = [page(app(slug="next-app"), total=8, limit=2)]
    last = await make_node("list_apps", limit=2, page_token=first["next_page_token"]).execute({})
    assert last["has_more"] is False and last["next_page_token"] is None
    assert dict(http.calls[-1].url.params) == {"limit": "2", "next": "next-app"}


@pytest.mark.asyncio
async def test_full_page_without_next_does_not_fabricate_continuation_or_total(http):
    http.responses = [page(app(), app(slug=OTHER))]
    out = await make_node("list_apps", limit=2).execute({})
    assert out["has_more"] is False and out["next_page_token"] is None
    assert out["total_item_count"] is None and out["page_item_limit"] is None


@pytest.mark.asyncio
async def test_branches_names_are_opt_in_and_local_truncation_is_not_provider_paging(http):
    http.responses = [page(app()), (200, {"data": ["main", "release/x", "feature/y"]})]
    safe = await make_node("list_branches").execute({})
    assert safe["branches"] == [] and safe["branch_count"] == 3 and safe["names_included"] is False
    http.responses = [page(app()), (200, {"data": ["main", "release/x", "feature/y"]})]
    named = await make_node("list_branches", include_names=True, max_names=2).execute({})
    assert named["branches"] == ["main", "release/x"] and named["local_truncated"] is True
    assert http.calls[-1].url.path == "/v0.1/apps/app-a/branches" and not http.calls[-1].url.params


@pytest.mark.asyncio
async def test_selector_empty_search_page_retains_anchor_and_ignores_forged_authority(http):
    with pytest.raises(ValueError):
        await ad.BitriseNode.load_field_options("build_slug", credential(), context={"approved": True})
    assert http.calls == []
    http.responses = [page(app()), page(build(), following="next-build", total=2, limit=50)]
    first = await ad.BitriseNode.load_field_options("build_slug", credential(), context={"app_slug": APP,
        "access_token": "forged", "organization_id": OWNER, "workflow_id": WF}, search="target")
    assert first["options"] == [] and first["next_page_token"]
    count = len(http.calls)
    with pytest.raises(ValueError):
        await ad.BitriseNode.load_field_options("build_slug", credential(), context={"app_slug": OTHER},
            page_token=first["next_page_token"], search="target")
    assert len(http.calls) == count
    http.responses = [page(app()), page(build(slug="target-build"), total=2, limit=50)]
    last = await ad.BitriseNode.load_field_options("build_slug", credential(), context={"app_slug": APP},
        page_token=first["next_page_token"], search="target")
    assert last["options"] == [{"value": "target-build", "label": "target-build"}] and last["next_page_token"] is None
    assert all(req.headers["Authorization"] == "fixture-token" for req in http.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, [], {"data": {}}, {"data": [app(slug="../foreign")]},
    {"data": [app(), app()]}, {"data": [], "paging": {"next": "https://private.invalid"}},
    {"data": [], "paging": {"total_item_count": True}}, {"data": [], "paging": {"page_item_limit": 51}},
    {"data": [], "error": "sensitive-provider-sentinel"}])
async def test_envelope_slugs_and_paging_fail_closed_without_capability_urls(http, payload):
    http.responses = [(200, payload)]
    with pytest.raises(RuntimeError) as failure:
        await make_node("list_apps").execute({})
    assert "sensitive-provider-sentinel" not in str(failure.value) and "private.invalid" not in str(failure.value)


@pytest.mark.asyncio
async def test_parent_witness_detects_repeated_provider_anchor(http):
    http.responses = [page(app(slug=OTHER), following="loop"), page(app(slug=OTHER), following="loop")]
    with pytest.raises(RuntimeError):
        await make_node("get_app").execute({})
    assert len(http.calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("status,payload", [(401, "fixture-token sensitive-provider-sentinel"), (403, {"error": "sensitive-provider-sentinel"}),
    (429, {}), (500, {}), (302, None), (204, None), (200, {"wrong": True})])
async def test_provider_errors_are_static_unverified_without_retries(http, status, payload):
    http.responses = [(status, payload)]
    with pytest.raises(RuntimeError) as failure:
        await make_node("check_connection").execute({})
    assert "fixture-token" not in str(failure.value) and "sensitive-provider-sentinel" not in str(failure.value)
    assert len(http.calls) == 1


@pytest.mark.asyncio
async def test_current_saved_row_adopts_token_and_retains_manager_metadata(saved):
    saved.storage.grant = credential(access_token="current-token", manager_flag="retain")
    current = await ad.BitriseNode.freshen_credential(credential(), pool=saved.storage, user_id=USER,
        credential_id=CID, workflow_id=WF, organization_id=ORG)
    assert current["access_token"] == "current-token" and current["manager_flag"] == "retain"
    assert saved.http.calls == [] and saved.storage.writes == [] and saved.storage.revoke_tags == []


@pytest.mark.asyncio
@pytest.mark.parametrize("unavailable", ["wrong-family", "revoked", "denied"])
async def test_actual_current_typed_live_access_precedes_decryption_and_http(saved, unavailable):
    if unavailable == "wrong-family":
        saved.storage.row["credential_type"] = "other"
    elif unavailable == "revoked":
        saved.storage.row["revoked_at"] = datetime.now(timezone.utc)
    else:
        saved.storage.access.clear()
    with pytest.raises(ValueError):
        await ad.BitriseNode.freshen_credential(credential(), pool=saved.storage, user_id=USER, credential_id=CID)
    saved.crypto.decrypt_credential.assert_not_called()
    assert saved.http.calls == []


@pytest.mark.asyncio
async def test_manual_connect_uses_actual_catalog_reachability_not_account_identity(http, monkeypatch):
    from nodes.core import credential_connect
    from nodes.core.connection_evidence import collect_evidence
    monkeypatch.setattr(credential_connect, "_collect_evidence", collect_evidence)
    http.responses = [page(app())]
    result = await credential_connect.validate_for_connect(credential_type="bitrise_api_token", credential_data=credential(), user_id=USER)
    assert result.ok and result.node_type == NODE and result.evidence.reachable is True
    assert result.evidence.samples == [EvidenceSample(label=APP, value=None)] and result.evidence.proves == "reachability" and result.evidence.account_label is None
    assert "private@example.invalid" not in json.dumps(asdict(result.evidence))


@pytest.mark.asyncio
async def test_registered_socket_uses_current_token_and_trusted_org_not_context(sockets):
    sockets.saved.storage.grant = credential(access_token="current-token")
    sockets.saved.http.responses = [page(app())]
    assert await socket_call(sockets, "credential:validate_access", user_id=OWNER, organization_id=OWNER) == {"valid": True}
    sockets.saved.http.responses = [page(app())]
    out = await socket_call(sockets, "workflow:node:load_options", field_name="app_slug",
        context={"access_token": "forged", "organization_id": OWNER, "workflow_id": WF})
    assert out["success"] is True and out["options"] == [{"value": APP, "label": APP, "metadata": None}]
    assert all(req.headers["Authorization"] == "current-token" for req in sockets.saved.http.calls)
    assert all(args[2] == ORG for sql, args in sockets.saved.storage.calls if "SELECT c.credential" in sql)


@pytest.mark.asyncio
@pytest.mark.parametrize("status,payload", [(403, {"secret": "sensitive-provider-sentinel"}), (200, {"data": {}})])
async def test_native_validation_keeps_provider_or_malformed_catalog_failure_unknown(sockets, status, payload):
    sockets.saved.http.responses = [(status, payload)]
    out = await socket_call(sockets, "credential:validate_access")
    assert out["valid"] is None and "sensitive-provider-sentinel" not in json.dumps(out)


@pytest.mark.asyncio
@pytest.mark.parametrize("policy", ["pending", "rejected"])
async def test_actual_admission_and_evidence_deny_before_http_and_raw_fallback(sockets, policy):
    from nodes.core.connection_evidence import collect_evidence
    storage = sockets.saved.storage
    storage.row["approval_operations"] = ["*"]
    out = await socket_call(sockets, "workflow:node:load_options", field_name="app_slug", context={"approved": True})
    assert out["success"] is False
    if policy == "rejected":
        for grant in storage.grants.values():
            grant["status"] = "rejected"
    evidence = await collect_evidence(node_type=NODE, credential_id=CID, user_id=USER, pool=storage, organization_id=ORG, workflow_id=WF)
    assert evidence.reachable is None and evidence.account_label is None and evidence.samples == []
    assert sockets.saved.http.calls == [] and storage.writes == []


@pytest.mark.asyncio
async def test_fixed_public_transport_refuses_private_override(monkeypatch):
    import asyncio
    import socket
    from utils import ssrf
    transport_calls = []
    lookup = AsyncMock(return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.8", 443))])
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", lookup)
    monkeypatch.setattr(ssrf, "allow_private_hosts", lambda: True)
    def guarded(**kwargs):
        return ssrf.guarded_async_client(transport=httpx.MockTransport(
            lambda request: transport_calls.append(request) or httpx.Response(200, json={"data": []})), **kwargs)
    monkeypatch.setattr(ad, "guarded_async_client", guarded)
    with pytest.raises(RuntimeError, match="could not be reached"):
        await make_node("check_connection").execute({})
    lookup.assert_awaited_once_with("api.bitrise.io", 443, type=socket.SOCK_STREAM)
    assert transport_calls == []
