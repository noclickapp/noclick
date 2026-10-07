"""Prepared Sematext native wire, parent binding and privacy regressions.

Actual factory/dispatcher/connect/schema seams use synthetic HTTP boundaries.
These fixtures are UNRUN and prove no account, entitlement or UI result.
"""
from copy import deepcopy
import json
from types import SimpleNamespace
import httpx
import pytest
from nodes import sematext_node as p
from nodes.core.registry import NodeFactory, NODE_REGISTRY
from nodes.core.run_op import run_node_operation

USER = "00000000-0000-4000-8000-000000000001"
APP, SECOND, FOREIGN = "123", "124", "999"
PRIVATE = "SYNTHETIC_PRIVATE_MARKER"


def blob(**changes):
    return {"credential_type": p.FAMILY, "api_key": "synthetic-account-key", "region": "US", "include_labels": False,
            "approved_app_ids_json": json.dumps([APP, SECOND]), **changes}


def app(uid=APP):
    return {"id": int(uid), "appTypeId": 1, "appType": "logs", "status": "ACTIVE", "displayStatus": "Ready",
        "registrationDate": 1791339600000, "name": PRIVATE, "token": PRIVATE, "tokens": [PRIVATE], "readToken": PRIVATE,
        "readWriteToken": PRIVATE, "writeToken": PRIVATE, "creatorEmail": PRIVATE, "ownerEmail": PRIVATE,
        "creditCardNumber": PRIVATE, "creditCardExpiry": PRIVATE, "integration": {"config": PRIVATE},
        "plan": {"secret": PRIVATE}, "userRoles": [{"email": PRIVATE}], "description": PRIVATE}


def rule(parent=APP):
    return {"ruleKey": 456, "appId": int(parent), "enabled": True, "ruleType": "THRESHOLD", "priority": "WARN",
        "lastTriggered": 1791339600000, "name": PRIVATE, "appToken": PRIVATE, "accountEmail": PRIVATE,
        "creatorEmail": PRIVATE, "runbook": PRIVATE, "query": PRIVATE, "filterValues": PRIVATE,
        "metadata": {"private": PRIVATE}, "notificationEmails": [PRIVATE], "notificationIntegrations": [{"key": PRIVATE}],
        "integrations": PRIVATE, "schedule": [PRIVATE], "sendToEmail": PRIVATE, "userPermissions": {"secret": PRIVATE}}


def envelope(key, value, success=True):
    return {"success": success, "data": {key: value}, "message": PRIVATE, "errors": [{"message": PRIVATE}]}


def option(value):
    return {"value": value, "label": value, "metadata": {"completion": "unknown", "identity_verified": False}}


@pytest.fixture
def wire(monkeypatch):
    state = SimpleNamespace(queue=[], calls=[], after_headers=None, after_body=None)
    class Response:
        def __init__(self, payload, status, ctype):
            self.status_code, self.headers = status, {"content-type": ctype, "location": PRIVATE}
            self.payload = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        async def __aenter__(self):
            if state.after_headers: state.after_headers()
            return self
        async def __aexit__(self, *_): return False
        async def aiter_bytes(self):
            yield self.payload
            if state.after_body: state.after_body()
    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *_): return False
        def stream(self, method, url, **kwargs):
            state.calls.append((method, url, deepcopy(kwargs)))
            assert state.queue, "Unexpected request beyond synthetic boundary"
            value = state.queue.pop(0)
            if isinstance(value, BaseException): raise value
            return Response(*value) if isinstance(value, tuple) else Response(value, 200, "application/json")
    def client(**kwargs):
        assert kwargs == {"require_public": True, "timeout": 30, "follow_redirects": False, "trust_env": False}
        return Client()
    monkeypatch.setattr(p, "guarded_async_client", client)
    return state


async def execute(config, data=None, inputs=None):
    node = NodeFactory.create_node("fixture", p.NODE_TYPE, {"config": config, "credentials": data or blob()}, user_id=USER)
    return await node.execute(inputs or {})


@pytest.mark.asyncio
async def test_actual_factory_dispatcher_regional_account_header_and_no_input_overlay(wire):
    assert NODE_REGISTRY[p.NODE_TYPE] is p.SematextNode
    wire.queue = [envelope("apps", [app()]), envelope("apps", [])]
    result = await execute({"operation": "check_connection"}, blob(region="EU"), {"region": "US", "operation": "send_report"})
    assert result["witness_verified"] and not result["identity_verified"] and not result["account_ownership_verified"]
    result = await run_node_operation(node_type=p.NODE_TYPE, operation="check_connection", arguments={}, user_id=USER, credential_data=blob())
    assert result["witness_verified"] and result["received_count"] == 0 and result["completion"] == "unknown"
    assert wire.calls[0][1] == p.ROOTS["EU"] + p.BASE + "/apps"
    assert wire.calls[1][1] == p.ROOTS["US"] + p.BASE + "/apps"
    for method, url, kwargs in wire.calls:
        assert method == "GET" and kwargs["params"] is None
        assert kwargs["headers"] == {"Authorization": "apiKey synthetic-account-key", "Accept": "application/json", "Content-Type": "application/json"}


@pytest.mark.asyncio
async def test_actual_connect_empty_catalog_is_only_reachability(wire, monkeypatch):
    from nodes.core import credential_connect as cc
    from nodes.core.connection_evidence import collect_evidence
    monkeypatch.setattr(cc, "_collect_evidence", collect_evidence)
    wire.queue = [envelope("apps", []), envelope("apps", [], success="true")]
    result = await cc.validate_for_connect(credential_type=p.FAMILY, credential_data=blob(), user_id=USER)
    assert result.evidence.reachable is True and result.evidence.proves == "reachability" and result.evidence.account_label is None
    assert "verified_as" not in result.verified_metadata()
    unknown = await cc.validate_for_connect(credential_type=p.FAMILY, credential_data=blob(), user_id=USER)
    assert unknown.evidence.reachable is None and not unknown.verified_metadata()


@pytest.mark.asyncio
async def test_all_closed_reads_scalar_whitelist_excludes_messages_tokens_and_notification_settings(wire):
    cases = [({"operation": "list_apps"}, [envelope("apps", [app(), app(FOREIGN)])]),
        ({"operation": "get_app", "app_id": APP}, [envelope("apps", [app()]), envelope("app", app())]),
        ({"operation": "list_app_types"}, [envelope("appTypes", ["logs", "infra"])]),
        ({"operation": "list_alert_rules", "app_id": APP}, [envelope("apps", [app()]), envelope("app", app()), envelope("alertRules", [rule()])])]
    for cfg, responses in cases:
        wire.queue = responses
        result = await execute(cfg)
        assert result["status"] == "success" and result["resource_access_verified"] and not result["identity_verified"]
        assert PRIVATE not in json.dumps(result) and not wire.queue
        if cfg["operation"] == "list_apps": assert result["filtered_count"] == 1
        if cfg["operation"] == "list_alert_rules": assert result["parent_link_verified"]
    assert {url.removeprefix(p.ROOTS["US"] + p.BASE) for _, url, _ in wire.calls} == {"/apps", "/apps/" + APP, "/apps/types", "/apps/" + APP + "/alerts"}


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["unapproved", "missing-catalog", "foreign-detail", "foreign-rule"])
async def test_exact_current_catalog_detail_and_rule_app_ancestry(wire, kind):
    selected = FOREIGN if kind == "unapproved" else APP
    wire.queue = [envelope("apps", [] if kind == "missing-catalog" else [app()]),
                  envelope("app", app(FOREIGN if kind == "foreign-detail" else APP)),
                  envelope("alertRules", [rule(FOREIGN if kind == "foreign-rule" else APP)])]
    with pytest.raises((ValueError, RuntimeError)): await execute({"operation": "list_alert_rules", "app_id": selected})
    assert len(wire.calls) == {"unapproved": 0, "missing-catalog": 1, "foreign-detail": 2, "foreign-rule": 3}[kind]


@pytest.mark.asyncio
async def test_unpaged_local_bounds_and_picker_unknown_completion(wire):
    wire.queue = [envelope("apps", [app(), app(SECOND), app(FOREIGN)]), envelope("apps", [app()])]
    result = await execute({"operation": "list_apps", "limit": 1})
    assert result["received_count"] == 3 and result["returned_count"] == 1 and result["filtered_count"] == 1
    assert result["locally_truncated"] and result["completion"] == "unknown" and not ({"total", "has_more", "page", "next_page"} & result.keys())
    result = await p.SematextNode.load_field_options("app_id", blob())
    assert result == {"options": [option(APP)], "next_page_token": None, "completion": "unknown"}
    with pytest.raises(ValueError): await p.SematextNode.load_field_options("app_id", blob(), page_token="2")
    assert len(wire.calls) == 2 and all(call[2]["params"] is None for call in wire.calls)


@pytest.mark.asyncio
async def test_names_are_saved_opt_in_without_sensitive_subtrees(wire):
    wire.queue = [envelope("apps", [app()]), envelope("app", app()), envelope("apps", [app()]), envelope("app", app())]
    hidden = await execute({"operation": "get_app", "app_id": APP}, inputs={"include_labels": True})
    shown = await execute({"operation": "get_app", "app_id": APP}, blob(include_labels=True))
    assert "name" not in hidden["data"] and shown["data"]["name"] == PRIVATE
    assert not ({"token", "tokens", "readToken", "creditCardNumber", "integration", "plan", "userRoles", "message", "errors"} & shown["data"].keys())


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [[], {"success": True, "data": []}, envelope("app", []),
    envelope("apps", [app(), app()]), envelope("apps", [{**app(), "id": True}]), envelope("apps", [{**app(), "id": APP}]),
    envelope("apps", [], success="true"), envelope("apps", [app()] * 1001)])
async def test_unknown_envelopes_types_duplicates_bounds_never_become_success(wire, payload):
    wire.queue = [payload]
    with pytest.raises(RuntimeError): await execute({"operation": "check_connection"})


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [envelope("appTypes", [True]), envelope("appTypes", ["logs", "logs"]), envelope("appTypes", {})])
async def test_app_types_are_exact_distinct_strings(wire, payload):
    wire.queue = [payload]
    with pytest.raises(RuntimeError): await execute({"operation": "list_app_types"})


@pytest.mark.asyncio
@pytest.mark.parametrize("status,payload,ctype", [(200, envelope("apps", [], False), "application/json"),
    (401, {"message": PRIVATE}, "application/json"), (403, {"errors": [PRIVATE]}, "application/json"),
    (202, {}, "application/json"), (302, {}, "application/json"), (500, {}, "text/html"),
    (200, {}, "text/html"), (200, b'{"success":true,"success":false}', "application/json"),
    (200, b'[NaN]', "application/json"), (200, b' ' * 2_000_001, "application/json")])
async def test_failure_messages_errors_redirects_and_invalid_json_never_escape(wire, status, payload, ctype):
    wire.queue = [(payload, status, ctype)]
    with pytest.raises((ValueError, RuntimeError)) as caught: await execute({"operation": "check_connection"})
    assert PRIVATE not in str(caught.value) and len(wire.calls) == 1


def test_actual_native_schema_family_region_and_positive_int64_app_ids():
    schema = p.SematextNode.get_config_schema()
    model = schema["$defs"]["SematextAccountAPIKeyCredential"]
    assert model["title"] == "Sematext Account API Key" and "x-credential-type" not in model
    assert model["properties"]["api_key"]["ui:widget"] == "password" and model["properties"]["region"]["enum"] == ["US", "EU"]
    assert set(schema["properties"]["config"]["discriminator"]["mapping"]) == set(p.OPS) and len(p.OPS) == 5
    assert p.SematextNode.validate_config({"config": {"operation": "check_connection"}})["valid"] is True
    for changes in ({"credential_type": None}, {"credential_type": "sematext_app_token"}, {"api_key": "apiKey " + PRIVATE},
        {"region": "other"}, {"app_token": PRIVATE}, {"approved_app_ids_json": "[123]"}, {"include_labels": "true"}):
        raw = {"config": {"operation": "check_connection"}, "credentials": blob(**changes)}
        assert p.SematextNode.validate_config(raw)["valid"] is False
        with pytest.raises(ValueError) as caught: p.SematextNode.parse_config(raw)
        assert PRIVATE not in str(caught.value)
    for value in (True, "0", "01", "9223372036854775808", "https://invalid/", 123):
        with pytest.raises(ValueError): p.app_id(value)
    for limit in (True, 0, 101):
        with pytest.raises(ValueError): p.ListApps(limit=limit)
