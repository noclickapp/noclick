"""
Mock tests for the Sentry node (no live API calls).

Covers auth (Bearer token vs OAuth), region→host routing, REST path/param
construction across resources, the Link-header cursor parser, dynamic-option
dropdowns (org-scoped + project-scoped), and the service-hook trigger lifecycle
(register body, unregister, HMAC-SHA256 signature verification). The HTTP seam
(_rest_request) is patched so the node's request-shaping is what's tested.
"""

import hashlib
import hmac
import pytest
import json
from pathlib import Path
import httpx
from unittest.mock import Mock, patch

from nodes.sentry_node import (
    SentryNode, SentryNodeConfig, SentryAuthTokenCredential, SentryOAuthCredential, _host, _next_cursor,
    SentryListIssuesConfig, SentryGetIssueConfig, SentryUpdateIssueConfig,
    SentryListProjectsConfig, SentryGetProjectConfig, SentryCreateReleaseConfig,
    SentryListServiceHooksConfig, SentryRawRequestConfig, SentryOnErrorConfig, SentryOnAlertConfig,
)


def cred(**kw):
    base = dict(region="us", auth_token="sntrys_test", organization_slug="acme")
    base.update(kw)
    return SentryAuthTokenCredential(**base)


def node(cfg, credential=None):
    return SentryNode(node_id="s", node_type="automation-sentry", node_data={},
                      config=SentryNodeConfig(config=cfg, credentials=credential or cred()),
                      sio=Mock(), sid="s", workflow_id="w", user_id="u")


async def run_rest(cfg, credential=None, response=None):
    captured = {}

    async def fake(cred_, method, path, params=None, json_body=None, action_name="request"):
        captured.update(cred=cred_, method=method, path=path, params=params, json_body=json_body, action_name=action_name)
        return response or {"status": "success", "action": action_name, "data": {}}

    with patch("nodes.sentry_node._rest_request", side_effect=fake):
        result = await node(cfg, credential).execute({})
    return result, captured


async def _noop_ensure(self, credentials):
    return None


# ------------------------------------------------------------------ host / region


def test_host_regions():
    assert _host("us", None) == "https://sentry.io"
    assert _host("us2", None) == "https://us2.sentry.io"
    assert _host("de", None) == "https://de.sentry.io"
    assert _host("custom", "sentry.acme.com") == "https://sentry.acme.com"
    assert _host(None, None) == "https://sentry.io"


# ------------------------------------------------------------------ Link header cursor


def test_next_cursor_has_more():
    link = '<https://sentry.io/api/0/x/?cursor=0:0:1>; rel="previous"; results="false"; cursor="0:0:1", ' \
           '<https://sentry.io/api/0/x/?cursor=0:100:0>; rel="next"; results="true"; cursor="0:100:0"'
    assert _next_cursor(link) == "0:100:0"


def test_next_cursor_last_page():
    link = '<https://sentry.io/api/0/x/?cursor=0:100:0>; rel="next"; results="false"; cursor="0:100:0"'
    assert _next_cursor(link) is None
    assert _next_cursor(None) is None


# ------------------------------------------------------------------ path construction


@pytest.mark.asyncio
async def test_list_issues_org_scoped():
    _, cap = await run_rest(SentryListIssuesConfig(query="is:unresolved", project_slug="web", stats_period="24h"))
    assert cap["method"] == "GET"
    assert cap["path"] == "/api/0/organizations/acme/issues/"
    assert "project:web" in cap["params"]["query"]
    assert cap["params"]["statsPeriod"] == "24h"


@pytest.mark.asyncio
async def test_get_issue_path():
    _, cap = await run_rest(SentryGetIssueConfig(issue_id="12345"))
    assert cap["path"] == "/api/0/organizations/acme/issues/12345/"


@pytest.mark.asyncio
async def test_update_issue_body():
    _, cap = await run_rest(SentryUpdateIssueConfig(issue_id="1", status="resolved", assigned_to="me@x.com",
                                                    body_json='{"priority":"high"}'))
    assert cap["method"] == "PUT"
    assert cap["json_body"] == {"status": "resolved", "assignedTo": "me@x.com", "priority": "high"}


@pytest.mark.asyncio
async def test_list_projects_path():
    _, cap = await run_rest(SentryListProjectsConfig())
    assert cap["path"] == "/api/0/organizations/acme/projects/"


@pytest.mark.asyncio
async def test_get_project_project_scoped_path():
    _, cap = await run_rest(SentryGetProjectConfig(project_slug="web"))
    assert cap["path"] == "/api/0/projects/acme/web/"


@pytest.mark.asyncio
async def test_create_release_splits_projects():
    _, cap = await run_rest(SentryCreateReleaseConfig(version="1.2.3", projects="web, api",
                                                      body_json='{"refs":[{"repository":"o/r","commit":"abc"}]}'))
    assert cap["method"] == "POST"
    assert cap["path"] == "/api/0/organizations/acme/releases/"
    assert cap["json_body"]["version"] == "1.2.3"
    assert cap["json_body"]["projects"] == ["web", "api"]
    assert cap["json_body"]["refs"][0]["commit"] == "abc"


@pytest.mark.asyncio
async def test_service_hooks_project_scoped():
    _, cap = await run_rest(SentryListServiceHooksConfig(project_slug="web"))
    assert cap["path"] == "/api/0/projects/acme/web/hooks/"


@pytest.mark.asyncio
async def test_raw_request_rejects_absolute_url():
    with pytest.raises(ValueError, match="relative"):
        await node(SentryRawRequestConfig(method="GET", path="https://evil.com")).execute({})


# ------------------------------------------------------------------ OAuth routing


@pytest.mark.asyncio
async def test_oauth_uses_access_token_and_region_host():
    oauth = SentryOAuthCredential(access_token="pha_x", refresh_token="r", expires_at="2999-01-01T00:00:00+00:00",
                                  region="de", organization_slug="acme")
    captured = {}

    async def fake_http(method, url, headers=None, params=None, json=None):
        captured.update(url=url, auth=headers.get("Authorization"))
        resp = Mock(); resp.status_code = 200; resp.content = b"{}"; resp.headers = {}
        resp.json = lambda: {}
        return resp

    class _Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return None
        async def request(self, method, url, headers=None, params=None, json=None):
            return await fake_http(method, url, headers, params, json)

    with patch("nodes.sentry_node.httpx.AsyncClient", return_value=_Client()), \
         patch.object(SentryNode, "_ensure_fresh_token", _noop_ensure):
        await node(SentryListProjectsConfig(), credential=oauth).execute({})
    assert captured["auth"] == "Bearer pha_x"
    assert captured["url"].startswith("https://de.sentry.io/api/0/organizations/acme/projects/")


# ------------------------------------------------------------------ dropdowns


@pytest.mark.asyncio
async def test_dropdown_projects():
    async def fake(cred_, method, path, params=None, json_body=None, action_name="request"):
        assert path == "/api/0/organizations/acme/projects/"
        return {"status": "success", "data": [{"slug": "web", "name": "Web App"}, {"slug": "api", "name": "API"}],
                "next_cursor": None}

    with patch("nodes.sentry_node._rest_request", side_effect=fake):
        res = await SentryNode.load_field_options("project_slug", cred().model_dump())
    assert res["options"] == [{"label": "Web App", "value": "web"}, {"label": "API", "value": "api"}]


@pytest.mark.asyncio
async def test_dropdown_organizations_not_org_scoped():
    async def fake(cred_, method, path, params=None, json_body=None, action_name="request"):
        assert path == "/api/0/organizations/"
        return {"status": "success", "data": [{"slug": "acme", "name": "Acme"}], "next_cursor": None}

    with patch("nodes.sentry_node._rest_request", side_effect=fake):
        res = await SentryNode.load_field_options("organization_slug", cred().model_dump())
    assert res["options"] == [{"label": "Acme", "value": "acme"}]


@pytest.mark.asyncio
async def test_dropdown_rule_id_depends_on_project():
    calls = []

    async def fake(cred_, method, path, params=None, json_body=None, action_name="request"):
        calls.append(path)
        return {"status": "success", "data": [{"id": "77", "name": "High error rate"}], "next_cursor": None}

    with patch("nodes.sentry_node._rest_request", side_effect=fake):
        # No project in context → no options, no call.
        empty = await SentryNode.load_field_options("rule_id", cred().model_dump(), context={})
        assert empty == {"options": []}
        res = await SentryNode.load_field_options("rule_id", cred().model_dump(), context={"project_slug": "web"})
    assert "/api/0/projects/acme/web/rules/" in calls
    assert res["options"] == [{"label": "High error rate", "value": "77"}]


@pytest.mark.asyncio
async def test_dropdown_environment_org_scoped():
    async def fake(cred_, method, path, params=None, json_body=None, action_name="request"):
        assert path == "/api/0/organizations/acme/environments/"
        return {"status": "success", "data": [{"name": "production"}, {"name": "staging"}], "next_cursor": None}

    with patch("nodes.sentry_node._rest_request", side_effect=fake):
        res = await SentryNode.load_field_options("environment", cred().model_dump())
    assert res["options"] == [{"label": "production", "value": "production"}, {"label": "staging", "value": "staging"}]


@pytest.mark.asyncio
async def test_dropdown_hook_id_depends_on_project():
    calls = []

    async def fake(cred_, method, path, params=None, json_body=None, action_name="request"):
        calls.append(path)
        return {"status": "success", "data": [{"id": "hk1", "url": "https://x.hooks.example.test"}], "next_cursor": None}

    with patch("nodes.sentry_node._rest_request", side_effect=fake):
        empty = await SentryNode.load_field_options("hook_id", cred().model_dump(), context={})
        assert empty == {"options": []}
        res = await SentryNode.load_field_options("hook_id", cred().model_dump(), context={"project_slug": "web"})
    assert "/api/0/projects/acme/web/hooks/" in calls
    assert res["options"] == [{"label": "https://x.hooks.example.test", "value": "hk1"}]


@pytest.mark.asyncio
async def test_dropdown_no_credential():
    res = await SentryNode.load_field_options("project_slug", {})
    assert res == {"options": []}


# ------------------------------------------------------------------ trigger lifecycle


@pytest.mark.asyncio
@pytest.mark.parametrize("op_cls,operation,event", [
    (SentryOnErrorConfig, "on_error", "event.created"),
    (SentryOnAlertConfig, "on_alert", "event.alert"),
])
async def test_register_service_hook(op_cls, operation, event):
    captured = {}

    async def fake(cred_, method, path, params=None, json_body=None, action_name="request"):
        captured.update(method=method, path=path, json_body=json_body)
        return {"status": "success", "data": {"id": "hook_9", "secret": "shh"}}

    with patch("nodes.sentry_node._rest_request", side_effect=fake):
        extra = await SentryNode._register_external_webhook(
            webhook_url="https://abc.hooks.example.test", credential=cred().model_dump(),
            config={"operation": operation, "project_slug": "web"}, node_id="s")

    assert captured["method"] == "POST"
    assert captured["path"] == "/api/0/projects/acme/web/hooks/"
    assert captured["json_body"] == {"url": "https://abc.hooks.example.test", "events": [event]}
    assert extra == {"external_webhook_id": "hook_9", "signing_secret": "shh"}


@pytest.mark.asyncio
async def test_unregister_service_hook():
    captured = {}

    async def fake(cred_, method, path, params=None, json_body=None, action_name="request"):
        captured.update(method=method, path=path)
        return {"status": "success", "data": {}}

    with patch("nodes.sentry_node._rest_request", side_effect=fake):
        await SentryNode._unregister_external_webhook(
            credential=cred().model_dump(), config={"external_webhook_id": "hook_9", "project_slug": "web"}, node_id="s")
    assert captured["method"] == "DELETE"
    assert captured["path"] == "/api/0/projects/acme/web/hooks/hook_9/"


def test_verify_signature_valid():
    # Service hooks sign with X-ServiceHook-Signature = HMAC-SHA256(body, secret).
    body = b'{"action":"created"}'
    secret = "topsecret"
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert SentryNode.verify_webhook_signature(body, {"X-ServiceHook-Signature": sig}, {"signing_secret": secret}) is True
    # header lookup is case-insensitive
    assert SentryNode.verify_webhook_signature(body, {"x-servicehook-signature": sig}, {"signing_secret": secret}) is True


def test_verify_signature_invalid():
    assert SentryNode.verify_webhook_signature(b"{}", {"X-ServiceHook-Signature": "deadbeef"}, {"signing_secret": "s"}) is False


def test_verify_signature_rejects_wrong_header():
    # The integration-platform Sentry-Hook-Signature must NOT satisfy a service hook.
    body = b'{"x":1}'
    sig = hmac.new(b"s", body, hashlib.sha256).hexdigest()
    assert SentryNode.verify_webhook_signature(body, {"sentry-hook-signature": sig}, {"signing_secret": "s"}) is False


def test_verify_signature_no_secret_accepts():
    assert SentryNode.verify_webhook_signature(b"{}", {}, {}) is True


@pytest.mark.asyncio
async def test_trigger_passthrough_in_execute():
    payload = {"action": "created", "data": {"issue": {"id": "1"}}}
    result = await node(SentryOnErrorConfig(project_slug="web")).execute(payload)
    assert result["status"] == "success"
    assert result["action"] == "on_error"
    assert result["data"] == payload


_ALERT_OPERATIONS = [f"{action}_{family}_alert" + ("s" if action == "list" else "")
                     for family in ("issue", "metric") for action in ("list", "create", "get", "update", "delete")]
_CURRENT_EXAMPLES = json.loads((Path(__file__).parent / "fixtures/sentry_current_alerts.json").read_text())


def _saved_alert(operation):
    cfg = {"operation": operation}
    if "issue" in operation:
        cfg["project_slug"] = "web"
        if not operation.startswith(("list", "create")):
            cfg["rule_id"] = "77"
    elif not operation.startswith(("list", "create")):
        cfg["alert_rule_id"] = "88"
    if operation.startswith(("create", "update")):
        cfg["body_json"] = '{"name": "Saved rule"}'
    return cfg


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", _ALERT_OPERATIONS)
async def test_saved_alert_actions_keep_their_config_routes_and_outputs(operation):
    parsed = SentryNode.parse_config({"config": _saved_alert(operation)})
    assert parsed.config.alert_api == "legacy"
    response = {"status": "success", "action": operation, "data": {"id": "77", "conditions": [], "frequency": 30}}
    result, cap = await run_rest(parsed.config, response=response)
    assert result["data"] == response["data"]
    assert result["action"] == operation
    assert ("/rules/" if "issue" in operation else "/alert-rules/") in cap["path"]


@pytest.mark.asyncio
@pytest.mark.parametrize("dataset", ["omitted", None, "", "transactions", "errors"])
async def test_saved_discover_dataset_preserves_wire_semantics(dataset):
    cfg = {"operation": "query_discover", "field": "count()"}
    if dataset != "omitted":
        cfg["dataset"] = dataset
    parsed = SentryNode.parse_config({"config": cfg})
    captured = []
    def respond(request):
        captured.append(request)
        return httpx.Response(200, json={"data": [], "meta": {}})
    with patch("nodes.sentry_node.guarded_async_client", side_effect=lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(respond))):
        result = await node(parsed.config).execute({})
    assert result["status"] == "success"
    if dataset in ("omitted", None, ""):
        assert "dataset" not in captured[0].url.params
    else:
        assert captured[0].url.params["dataset"] == dataset


def test_dataset_schema_keeps_legacy_values():
    schema = SentryNode.get_config_schema()["$defs"]["SentryDiscoverConfig"]["properties"]["dataset"]
    assert "transactions" in schema["enum"]
    assert "" in schema["enum"]
    assert schema["default"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("family,resource,old_id,new_id", [("issue", "workflows", "77", "6789123"), ("metric", "detectors", "88", "123456")])
async def test_explicit_migration_keeps_old_field_names_and_output_keys(family, resource, old_id, new_id):
    operation = f"get_{family}_alert"
    saved = _saved_alert(operation)
    migrated = SentryNode.migrate_alert_config(saved, resource_id=new_id)
    assert saved["rule_id" if family == "issue" else "alert_rule_id"] == old_id
    assert migrated["rule_id" if family == "issue" else "alert_rule_id"] == new_id
    cfg = SentryNode.parse_config({"config": migrated}).config
    example = _CURRENT_EXAMPLES["workflow" if family == "issue" else "detector"]["body"]
    result, cap = await run_rest(cfg, response={"status": "success", "action": operation, "data": example})
    assert cap["path"] == f"/api/0/organizations/acme/{resource}/{new_id}/"
    assert result["data"]["id"] == example["id"]
    assert result["data"]["name"] == example["name"]
    if family == "issue":
        assert result["data"]["frequency"] == example["config"]["frequency"]
        assert result["data"]["triggers"] == example["triggers"]
    else:
        assert result["data"]["timeWindow"] == 15
        assert isinstance(result["data"]["timeWindow"], int)
        assert result["data"]["aggregate"] == "count()"
        assert result["data"]["dataSources"] == example["dataSources"]


def test_migration_does_not_guess_resource_ids_or_translate_legacy_payloads():
    with pytest.raises(ValueError, match="cannot be inferred"):
        SentryNode.migrate_alert_config(_saved_alert("get_issue_alert"))
    with pytest.raises(ValueError, match="translated"):
        SentryNode.migrate_alert_config(_saved_alert("update_metric_alert"), resource_id="123456")


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", _ALERT_OPERATIONS)
async def test_migrated_alert_routes_use_current_api(operation):
    metric = "metric" in operation
    action = operation.split("_")[0]
    # Provider-authored response fixture also supplies representative native fields.
    example = _CURRENT_EXAMPLES["detector" if metric else "workflow"]["body"]
    body = {"name": example["name"]}
    migrated = SentryNode.migrate_alert_config(
        _saved_alert(operation), resource_id=example["id"], current_body=body, project_slug="web")
    cfg = SentryNode.parse_config({"config": migrated}).config
    result, cap = await run_rest(cfg, response={"status": "success", "data": [example] if action == "list" else example})
    resource = "detectors" if metric else "workflows"
    expected = f"/api/0/organizations/acme/{resource}/"
    if action in {"get", "update", "delete"}:
        expected += f"{example['id']}/"
    elif action == "create" and metric:
        expected = "/api/0/organizations/acme/projects/web/detectors/"
    assert cap["path"] == expected
    assert cap["method"] == {"list": "GET", "get": "GET", "create": "POST", "update": "PUT", "delete": "DELETE"}[action]
    if action in {"create", "update"}:
        assert cap["json_body"] == body
    if action == "list":
        assert cap["params"]["type" if metric else "project"] == ("metric_issue" if metric else "web")
        assert result["data"][0]["id"] == example["id"]


@pytest.mark.asyncio
@pytest.mark.parametrize("field,resource", [("rule_id", "workflows"), ("alert_rule_id", "detectors")])
async def test_migrated_alert_dropdown_uses_current_ids(field, resource):
    calls = []
    async def fake(cred_, method, path, **kwargs):
        calls.append(path)
        return {"status": "success", "data": [{"id": "current-id", "name": "Current alert"}]}
    with patch("nodes.sentry_node._rest_request", side_effect=fake):
        result = await SentryNode.load_field_options(field, cred().model_dump(), context={"alert_api": "current", "project_slug": "web"})
    assert calls == [f"/api/0/organizations/acme/{resource}/"]
    assert result["options"] == [{"value": "current-id", "label": "Current alert"}]


@pytest.mark.asyncio
async def test_current_alert_rejects_untranslated_payload_before_request():
    cfg = SentryNode.parse_config({"config": {**_saved_alert("create_issue_alert"), "alert_api": "current", "body_json": '{"frequency": 30}'}}).config
    with patch("nodes.sentry_node._rest_request") as request:
        with pytest.raises(ValueError, match="Translate the legacy"):
            await node(cfg).execute({})
    request.assert_not_called()
