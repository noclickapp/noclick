"""Exercise ilert configuration, provider requests and closed resource projections.
Provider HTTP is synthetic; factory and connection evidence use staging implementations.
"""
from dataclasses import asdict
import json
from types import SimpleNamespace

import httpx
import pytest
from pydantic import ValidationError
from nodes import ilert_node as ad
from nodes.core.registry import NODE_REGISTRY, NodeFactory

USER = "11111111-1111-1111-1111-111111111111"
OWNER = "22222222-2222-2222-2222-222222222222"
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
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(ad, "guarded_async_client", client)
    return state


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
async def test_manual_connect_real_collector_uses_actor_not_supplied_identity(http, monkeypatch):
    from nodes.core import credential_connect
    from nodes.core.connection_evidence import collect_evidence
    monkeypatch.setattr(credential_connect, "_collect_evidence", collect_evidence)
    http.responses = [(200, actor())]
    result = await credential_connect.validate_for_connect(credential_type="ilert_api_key", credential_data=credential(), user_id=USER)
    assert result.ok and result.node_type == NODE and result.evidence.reachable is True
    assert [asdict(sample) for sample in result.evidence.samples] == [{"label": ACTOR, "value": None}]
    assert ad.IlertNode.connection_evidence.proves == "account"
    assert result.evidence.account_label is None
    assert "private@example.invalid" not in json.dumps(asdict(result.evidence))




@pytest.mark.asyncio
@pytest.mark.parametrize("status,payload", [(403, {"secret": "sensitive-provider-sentinel"}), (200, actor(id=99))])
async def test_native_validation_keeps_denial_or_actor_mismatch_unknown(http, status, payload):
    http.responses = [(status, payload)]
    out = await ad.IlertNode.validate_credential_access(credential())
    assert out["valid"] is None and "sensitive-provider-sentinel" not in json.dumps(out)
