"""Prepared Ilert regressions use real factory, authority, admission and socket seams.
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
from nodes import ilert_node as ad
from nodes.core.registry import NODE_REGISTRY, NodeFactory
from tests.test_oauth_refresh_authority import _Storage as AuthorityStorage, CID, USER, OWNER, ORG, WF
from tests.test_post_connect_validation_context import _Storage as AdmissionStorage
from wss.receiver.client_events import WorkflowNodeLoadOptionsRequest, CredentialValidateAccessRequest

NODE = "automation-ilert"
ACTOR, TEAM, SERVICE, OTHER = "88", "1", "7", "99"


@pytest.fixture
def ensure_native_db_pool():
    yield


def credential(**updates):
    return {"credential_type": "ilert_api_key", "access_token": "fixture-token", "actor_id": ACTOR, **updates}


def make_node(operation, data=None, **config):
    target = {"team_id": TEAM} if operation in {"get_team", "list_services", "get_service", "list_incidents", "get_incident"} else {}
    if operation in {"get_service", "list_incidents", "get_incident"}:
        target["service_id"] = SERVICE
    if operation == "get_incident":
        target["incident_id"] = "9"
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
        self.row.update(id=CID, credential_type="ilert_api_key",
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


def actor(**updates):
    return {"id": 88, "createdAt": "2026-10-07T00:00:00+05:30", "firstName": "Private Person",
        "email": "private@example.invalid", "role": "ADMIN", "avatarUrl": "https://private.invalid", **updates}


def team(**updates):
    return {"id": 1, "name": "Fixture Team", "members": [{"email": "private@example.invalid"}], **updates}


def service(**updates):
    return {"id": 7, "name": "Fixture Service", "status": "OPERATIONAL", "teams": [{"id": 1}],
        "description": "sensitive-provider-sentinel", "links": [{"url": "https://private.invalid"}],
        "iconUrl": "https://private.invalid", "labels": {"secret": "sensitive-provider-sentinel"}, **updates}


def incident(**updates):
    return {"id": 9, "title": "Fixture Incident", "status": "INVESTIGATING", "severity": 3,
        "declaredAt": "2026-10-07T00:00:00Z", "resolvedAt": None,
        "affectedServices": [{"service": service(), "impact": "DEGRADED"}],
        "responders": [{"user": actor()}], "summary": "sensitive-provider-sentinel",
        "conferenceBridge": {"url": "https://private.invalid"}, "channel": {"secret": "sensitive-provider-sentinel"}, **updates}


def page(*rows):
    return (200, list(rows))


def test_actual_factory_has_eight_closed_configs_and_rest_key_not_events():
    assert NODE_REGISTRY[NODE] is ad.IlertNode
    schema = ad.IlertNode.get_config_schema()
    defs = schema["$defs"]
    assert len(schema["properties"]["config"]["oneOf"]) == 8
    cred = defs["IlertAPIKeyCredential"]
    assert cred["required"] == ["access_token", "actor_id"]
    assert cred["properties"]["access_token"]["ui:widget"] == "password"
    assert "x-oauth-provider" not in cred
    assert defs["IlertStatusPagesConfig"]["properties"]["limit"]["maximum"] == 50
    assert defs["IlertTeamsConfig"]["properties"]["limit"]["maximum"] == 100
    assert defs["IlertGetIncidentConfig"]["required"] == ["team_id", "service_id", "incident_id"]
    assert defs["IlertGetIncidentConfig"]["properties"]["service_id"]["x-dynamic-options"]["depends_on"] == "team_id"
    assert defs["IlertGetIncidentConfig"]["properties"]["incident_id"]["x-dynamic-options"]["depends_on"] == "service_id"
    for config in ({"operation": "create_incident"}, {"operation": "list_alert_sources"},
        {"operation": "list_teams", "limit": 101}, {"operation": "list_teams", "limit": True},
        {"operation": "list_status_pages", "limit": 51}, {"operation": "list_teams", "offset": -1},
        {"operation": "list_teams", "include": "responders"}):
        with pytest.raises(ValidationError):
            ad.IlertNodeConfig.model_validate({"config": config, "credentials": credential()})


@pytest.mark.parametrize("updates", [{"access_token": ""}, {"access_token": "Bearer x"},
    {"access_token": "https://private.invalid"}, {"access_token": 123}, {"access_token": "x"*8193},
    {"credential_type": "ilert_events"}, {"actor_id": True}, {"actor_id": "01"},
    {"team_context": True}, {"team_context": -2}, {"team_context": "0"}])
def test_raw_family_header_actor_and_context_bounds(updates):
    with pytest.raises(ValueError):
        ad._credential(credential(**updates))


def test_actual_factory_error_keeps_secret_private():
    with pytest.raises(ValueError) as failure:
        make_node("check_connection", data=credential(access_token="sensitive-provider-sentinel invalid"))
    assert "sensitive-provider-sentinel" not in str(failure.value)


@pytest.mark.asyncio
async def test_actual_foreign_raw_family_stops_before_http(http):
    with pytest.raises(ValueError):
        await make_node("check_connection", data=credential(credential_type="other")).execute({})
    assert http.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("context", [None, -1, 0, 1])
async def test_fixed_rest_bearer_actor_projection_and_optional_team_header(http, context):
    http.responses = [(200, actor())]
    out = await make_node("check_connection", data=credential(team_context=context)).execute({})
    assert out["protected_actor"] is True and out["current_user_id"] == ACTOR
    assert out["items"] == [{"id": ACTOR, "createdAt": "2026-10-07T00:00:00+05:30"}]
    req = http.calls[0]
    assert req.method == "GET" and req.url.host == "api.ilert.com" and req.url.path == "/api/users/current"
    assert dict(req.url.params) == {} and req.headers["Authorization"] == "Bearer fixture-token"
    assert req.headers.get("team-context") == (str(context) if context is not None else None)
    assert req.headers["Accept"] == "application/json" and req.headers["User-Agent"].startswith("NoClick")
    assert "private@example.invalid" not in json.dumps(out) and "Private Person" not in json.dumps(out)


@pytest.mark.asyncio
async def test_actor_mismatch_stops_before_catalogs(http):
    http.responses = [(200, actor(id=99))]
    with pytest.raises(RuntimeError):
        await make_node("list_teams").execute({})
    assert [req.url.path for req in http.calls] == ["/api/users/current"]


@pytest.mark.asyncio
async def test_current_team_and_service_refs_are_verified_before_detail(http):
    http.responses = [(200, actor()), page(team()), page(service()), (200, service())]
    out = await make_node("get_service", include_names=True).execute({})
    assert out["service"] == {"id": SERVICE, "status": "OPERATIONAL", "team_ids": [TEAM], "name": "Fixture Service"}
    assert [req.url.path for req in http.calls] == ["/api/users/current", "/api/teams", "/api/services", "/api/services/7"]
    assert dict(http.calls[1].url.params) == {"max-results": "100", "start-index": "0"}
    assert "include" not in http.calls[2].url.params and not http.calls[3].url.params
    assert "sensitive-provider-sentinel" not in json.dumps(out) and "private.invalid" not in json.dumps(out)


@pytest.mark.asyncio
async def test_current_incident_services_filter_and_closed_affected_projection(http):
    http.responses = [(200, actor()), page(team()), page(service()), page(incident()), (200, incident())]
    out = await make_node("get_incident").execute({})
    row = out["incident"]
    assert row["affected_services"] == [{"id": SERVICE, "impact": "DEGRADED", "status": "OPERATIONAL"}]
    assert row["resolvedAt"] is None and row["severity"] == 3 and "title" not in row
    assert dict(http.calls[3].url.params) == {"max-results": "100", "start-index": "0", "services": SERVICE}
    assert http.calls[-1].url.path == "/api/incidents/9"
    assert not {"responders", "summary", "conferenceBridge", "channel", "declaredBy", "links"} & row.keys()
    assert "private.invalid" not in json.dumps(out) and "private@example.invalid" not in json.dumps(out)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["team", "service-team", "incident-catalog", "incident-affected", "detail-id"])
async def test_unwitnessed_or_replaced_ancestry_fails_without_outsider_detail(http, failure):
    http.responses = [(200, actor()), page(team(id=99) if failure == "team" else team())]
    if failure != "team":
        http.responses += [page(service(teams=[{"id": 99}]) if failure == "service-team" else service())]
    if failure not in {"team", "service-team"}:
        http.responses += [page(incident(id=99) if failure == "incident-catalog" else incident())]
    if failure in {"incident-affected", "detail-id"}:
        http.responses += [(200, incident(affectedServices=[])) if failure == "incident-affected" else (200, incident(id=99))]
    with pytest.raises((ValueError, RuntimeError)):
        await make_node("get_incident").execute({})
    assert len(http.calls) == {"team": 2, "service-team": 3, "incident-catalog": 4, "incident-affected": 5, "detail-id": 5}[failure]


@pytest.mark.asyncio
async def test_numeric_pages_keep_unknown_totals_and_bind_current_context(http):
    http.responses = [(200, actor()), page(team(), team(id=2))]
    first = await make_node("list_teams", limit=2).execute({})
    assert first["total"] is None and first["has_more"] is None and first["completion"] == "unknown"
    assert first["next_page_token"] and "fixture-token" not in first["next_page_token"]
    count = len(http.calls)
    for args in ({"include_names": True}, {"limit": 1}, {"offset": 2},
        {"data": credential(access_token="new-token")}, {"data": credential(actor_id=OTHER)},
        {"data": credential(team_context=0)}):
        with pytest.raises(ValueError):
            await make_node("list_teams", limit=args.get("limit", 2), page_token=first["next_page_token"],
                **{k: v for k, v in args.items() if k != "limit"}).execute({})
    assert len(http.calls) == count
    http.responses = [(200, actor()), page(team(id=3))]
    last = await make_node("list_teams", limit=2, page_token=first["next_page_token"]).execute({})
    assert last["offset"] == 2 and last["next_page_token"] is None and last["total"] is None
    assert dict(http.calls[-1].url.params) == {"max-results": "2", "start-index": "2"}


@pytest.mark.asyncio
async def test_local_service_filter_advances_by_provider_page_count(http):
    http.responses = [(200, actor()), page(team()), page(service(id=8, teams=[{"id": 2}]), service(id=9, teams=[{"id": 2}]))]
    first = await make_node("list_services", limit=2).execute({})
    assert first["items"] == [] and first["provider_returned"] == 2 and first["next_page_token"]
    http.responses = [(200, actor()), page(team()), page(service())]
    last = await make_node("list_services", limit=2, page_token=first["next_page_token"]).execute({})
    assert last["items"][0]["id"] == SERVICE and last["offset"] == 2


@pytest.mark.asyncio
async def test_selector_zero_match_cursor_and_forged_context_are_resource_only(http):
    with pytest.raises(ValueError):
        await ad.IlertNode.load_field_options("service_id", credential(), context={"approved": True})
    assert http.calls == []
    http.responses = [(200, actor()), page(team()), page(*[service(id=n) for n in range(1, 51)])]
    first = await ad.IlertNode.load_field_options("service_id", credential(), context={"team_id": TEAM,
        "access_token": "forged", "actor_id": OTHER, "team_context": 99, "organization_id": OWNER}, search="999")
    assert first["options"] == [] and first["next_page_token"]
    count = len(http.calls)
    with pytest.raises(ValueError):
        await ad.IlertNode.load_field_options("service_id", credential(), context={"team_id": OTHER},
            search="999", page_token=first["next_page_token"])
    assert len(http.calls) == count
    http.responses = [(200, actor()), page(team()), page(service(id=999))]
    last = await ad.IlertNode.load_field_options("service_id", credential(), context={"team_id": TEAM}, search="999", page_token=first["next_page_token"])
    assert last["options"] == [{"value": "999", "label": "999"}] and last["next_page_token"] is None
    assert all(req.headers["Authorization"] == "Bearer fixture-token" and "team-context" not in req.headers for req in http.calls)


@pytest.mark.asyncio
async def test_status_page_catalog_never_exports_settings_capabilities_or_subscribers(http):
    http.responses = [(200, actor()), page({"id": 3, "status": "OPERATIONAL", "name": "Fixture Page",
        "structure": {"secret": "sensitive-provider-sentinel"}, "domain": "private.invalid", "metrics": [actor()],
        "ipWhitelist": ["10.0.0.1"], "analyticsKey": "sensitive-provider-sentinel", "notifyFromEmail": "private@example.invalid"})]
    out = await make_node("list_status_pages").execute({})
    assert out["items"] == [{"id": "3", "status": "OPERATIONAL"}]
    assert http.calls[-1].url.path == "/api/status-pages"
    assert dict(http.calls[-1].url.params) == {"max-results": "25", "start-index": "0"}


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"message": "sensitive-provider-sentinel"}, [team(id=True)], [team(id="1")], [team(), team()]])
async def test_bare_arrays_direct_ids_and_duplicates_fail_closed(http, payload):
    http.responses = [(200, actor()), (200, payload)]
    with pytest.raises(RuntimeError) as failure:
        await make_node("list_teams").execute({})
    assert "sensitive-provider-sentinel" not in str(failure.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("status,payload", [(401, "fixture-token sensitive-provider-sentinel"), (403, {"message": "sensitive-provider-sentinel"}),
    (429, {}), (500, {}), (302, None), (204, None), (200, {"wrong": True})])
async def test_errors_remain_static_unverified_without_retries(http, status, payload):
    http.responses = [(status, payload)]
    with pytest.raises(RuntimeError) as failure:
        await make_node("check_connection").execute({})
    assert "fixture-token" not in str(failure.value) and "sensitive-provider-sentinel" not in str(failure.value)
    assert len(http.calls) == 1


@pytest.mark.asyncio
async def test_current_saved_row_adopts_key_actor_context_and_manager_metadata(saved):
    saved.storage.grant = credential(access_token="current-token", actor_id=OTHER, team_context=-1, manager_flag="retain")
    current = await ad.IlertNode.freshen_credential(credential(), pool=saved.storage, user_id=USER,
        credential_id=CID, workflow_id=WF, organization_id=ORG)
    assert current["access_token"] == "current-token" and current["actor_id"] == OTHER and current["team_context"] == -1
    assert current["manager_flag"] == "retain" and saved.http.calls == [] and saved.storage.writes == []


@pytest.mark.asyncio
@pytest.mark.parametrize("unavailable", ["wrong-family", "revoked", "denied"])
async def test_current_typed_live_access_precedes_decryption_and_provider(saved, unavailable):
    if unavailable == "wrong-family":
        saved.storage.row["credential_type"] = "other"
    elif unavailable == "revoked":
        saved.storage.row["revoked_at"] = datetime.now(timezone.utc)
    else:
        saved.storage.access.clear()
    with pytest.raises(ValueError):
        await ad.IlertNode.freshen_credential(credential(), pool=saved.storage, user_id=USER, credential_id=CID)
    saved.crypto.decrypt_credential.assert_not_called()
    assert saved.http.calls == []


@pytest.mark.asyncio
async def test_manual_connect_real_collector_uses_actor_not_supplied_identity(http, monkeypatch):
    from nodes.core import credential_connect
    from nodes.core.connection_evidence import collect_evidence
    monkeypatch.setattr(credential_connect, "_collect_evidence", collect_evidence)
    http.responses = [(200, actor())]
    result = await credential_connect.validate_for_connect(credential_type="ilert_api_key", credential_data=credential(), user_id=USER)
    assert result.ok and result.node_type == NODE and result.evidence.reachable is True
    assert result.evidence.samples == [ACTOR] and result.evidence.proves == "account" and result.evidence.account_label is None
    assert "private@example.invalid" not in json.dumps(asdict(result.evidence))


@pytest.mark.asyncio
async def test_registered_socket_uses_current_actor_context_and_trusted_org(sockets):
    sockets.saved.storage.grant = credential(access_token="current-token", actor_id=OTHER, team_context=-1)
    sockets.saved.http.responses = [(200, actor(id=99))]
    assert await socket_call(sockets, "credential:validate_access", user_id=OWNER, organization_id=OWNER) == {"valid": True}
    sockets.saved.http.responses = [(200, actor(id=99)), page(team())]
    out = await socket_call(sockets, "workflow:node:load_options", field_name="team_id",
        context={"access_token": "forged", "actor_id": ACTOR, "team_context": 99, "organization_id": OWNER, "workflow_id": WF})
    assert out["success"] is True and out["options"] == [{"value": TEAM, "label": TEAM}]
    assert all(req.headers["Authorization"] == "Bearer current-token" and req.headers["team-context"] == "-1" for req in sockets.saved.http.calls)
    assert all(args[2] == ORG for sql, args in sockets.saved.storage.calls if "SELECT c.credential" in sql)


@pytest.mark.asyncio
@pytest.mark.parametrize("status,payload", [(403, {"secret": "sensitive-provider-sentinel"}), (200, actor(id=99))])
async def test_native_validation_keeps_denial_or_actor_mismatch_unknown(sockets, status, payload):
    sockets.saved.http.responses = [(status, payload)]
    out = await socket_call(sockets, "credential:validate_access")
    assert out["valid"] is None and "sensitive-provider-sentinel" not in json.dumps(out)


@pytest.mark.asyncio
@pytest.mark.parametrize("policy", ["pending", "rejected"])
async def test_real_admission_and_evidence_deny_before_http_and_raw_fallback(sockets, policy):
    from nodes.core.connection_evidence import collect_evidence
    storage = sockets.saved.storage
    storage.row["approval_operations"] = ["*"]
    out = await socket_call(sockets, "workflow:node:load_options", field_name="team_id", context={"approved": True})
    assert out["success"] is False
    if policy == "rejected":
        for grant in storage.grants.values():
            grant["status"] = "rejected"
    evidence = await collect_evidence(node_type=NODE, credential_id=CID, user_id=USER, pool=storage, organization_id=ORG, workflow_id=WF)
    assert evidence.reachable is None and evidence.account_label is None and evidence.samples == []
    assert sockets.saved.http.calls == [] and storage.writes == []


@pytest.mark.asyncio
async def test_actual_public_dns_guard_refuses_private_override(monkeypatch):
    import asyncio
    import socket
    from utils import ssrf
    transport_calls = []
    lookup = AsyncMock(return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.8", 443))])
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", lookup)
    monkeypatch.setattr(ssrf, "allow_private_hosts", lambda: True)
    def guarded(**kwargs):
        return ssrf.guarded_async_client(transport=httpx.MockTransport(
            lambda request: transport_calls.append(request) or httpx.Response(200, json=actor())), **kwargs)
    monkeypatch.setattr(ad, "guarded_async_client", guarded)
    with pytest.raises(RuntimeError, match="could not be reached"):
        await make_node("check_connection").execute({})
    lookup.assert_awaited_once_with("api.ilert.com", 443, type=socket.SOCK_STREAM)
    assert transport_calls == []

