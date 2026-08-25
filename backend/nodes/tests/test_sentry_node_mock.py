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
