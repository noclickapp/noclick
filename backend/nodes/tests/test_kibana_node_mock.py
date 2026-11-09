"""Kibana request, credential and provider-response regressions (offline)."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import kibana_node as native
from nodes.core.registry import NodeFactory, NODE_REGISTRY

TOKEN = "synthetic-kibana-key"
CREDENTIAL = {"credential_type": "kibana_api_key", "api_base_url": "https://kibana.example.com", "api_key": TOKEN}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="kibana-test", node_type="automation-kibana",
        node_data={"config": config, "credentials": CREDENTIAL})


def transport(monkeypatch, response):
    calls = []
    def respond(request):
        calls.append(request)
        return response(request) if callable(response) else response
    def client(**kwargs):
        assert kwargs["trust_env"] is False
        assert kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return calls


# Independent route expectations: these are the published REST endpoints.
CASES = [
    ({"operation": "list_spaces"}, "GET", "/api/spaces/space", None),
    ({"operation": "get_space", "id": "marketing"}, "GET", "/api/spaces/space/marketing", None),
    ({"operation": "create_space", "id": "marketing", "name": "Marketing", "disabled_features": ["discover"]}, "POST", "/api/spaces/space", {"id": "marketing", "name": "Marketing", "disabledFeatures": ["discover"]}),
    ({"operation": "update_space", "id": "marketing", "name": "Marketing"}, "PUT", "/api/spaces/space/marketing", {"id": "marketing", "name": "Marketing"}),
    ({"operation": "delete_space", "id": "marketing"}, "DELETE", "/api/spaces/space/marketing", None),
    ({"operation": "list_data_views"}, "GET", "/api/data_views", None),
    ({"operation": "get_data_view", "id": "logs-view"}, "GET", "/api/data_views/data_view/logs-view", None),
    ({"operation": "create_data_view", "title": "logs-*", "time_field_name": "@timestamp", "allow_no_index": True}, "POST", "/api/data_views/data_view", {"data_view": {"title": "logs-*", "timeFieldName": "@timestamp", "allowNoIndex": True}, "override": False}),
    ({"operation": "update_data_view", "id": "logs-view", "title": "new-logs-*", "name": "Logs"}, "POST", "/api/data_views/data_view/logs-view", {"data_view": {"title": "new-logs-*", "name": "Logs"}, "refresh_fields": False}),
    ({"operation": "delete_data_view", "id": "logs-view"}, "DELETE", "/api/data_views/data_view/logs-view", None),
    ({"operation": "get_default_data_view"}, "GET", "/api/data_views/default", None),
    ({"operation": "set_default_data_view", "data_view_id": "logs-view", "force": True}, "POST", "/api/data_views/default", {"data_view_id": "logs-view", "force": True}),
    ({"operation": "list_rules", "page": 3, "per_page": 5, "search": "latency"}, "GET", "/api/alerting/rules/_find", None),
    ({"operation": "get_rule", "id": "latency-rule"}, "GET", "/api/alerting/rule/latency-rule", None),
    ({"operation": "delete_rule", "id": "latency-rule"}, "DELETE", "/api/alerting/rule/latency-rule", None),
    ({"operation": "enable_rule", "id": "latency-rule"}, "POST", "/api/alerting/rule/latency-rule/_enable", None),
    ({"operation": "disable_rule", "id": "latency-rule"}, "POST", "/api/alerting/rule/latency-rule/_disable", None),
    ({"operation": "mute_rule", "id": "latency-rule"}, "POST", "/api/alerting/rule/latency-rule/_mute_all", None),
    ({"operation": "unmute_rule", "id": "latency-rule"}, "POST", "/api/alerting/rule/latency-rule/_unmute_all", None),
    ({"operation": "list_connectors"}, "GET", "/api/actions/connectors", None),
    ({"operation": "get_connector", "id": "slack-alerts"}, "GET", "/api/actions/connector/slack-alerts", None),
    ({"operation": "delete_connector", "id": "slack-alerts"}, "DELETE", "/api/actions/connector/slack-alerts", None),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,body", CASES)
async def test_requests_and_no_content_acknowledgements(monkeypatch, config, method, path, body):
    if method == "GET":
        data = [] if config["operation"] in {"list_spaces", "list_connectors"} else {"data": [], "data_view": []}
        response = httpx.Response(200, json=data)
    else:
        response = httpx.Response(204)
    calls = transport(monkeypatch, response)
    result = await node(config).execute({})
    assert result["success"] is True
    if method != "GET":
        assert result["acknowledged"] is True
    assert len(calls) == 1
    request = calls[0]
    assert request.method == method and request.url.path == path
    assert request.headers["Authorization"] == "ApiKey " + TOKEN
    assert request.headers["kbn-xsrf"] == "true"
    assert (json.loads(request.content) if request.content else None) == body
    if config["operation"] == "list_rules":
        assert dict(request.url.params) == {"page": "3", "per_page": "5", "search": "latency"}
    else:
        assert not request.url.query


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 400, 401, 403, 404, 429, 500])
async def test_rejection_preserves_provider_message_and_redacts_key(monkeypatch, status):
    calls = transport(monkeypatch, httpx.Response(status, json={"message": "Kibana rejected key " + TOKEN}))
    result = await node({"operation": "list_spaces"}).execute({})
    assert result["success"] is False and result["http_status"] == status
    assert "Kibana rejected key" in result["message"] and TOKEN not in str(result)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_error_envelope_and_html_are_not_connection_success(monkeypatch):
    transport(monkeypatch, httpx.Response(200, json={"error": "Forbidden", "message": "No space access"}))
    result = await node({"operation": "list_spaces"}).execute({})
    assert result["success"] is False and result["message"] == "No space access"
    transport(monkeypatch, httpx.Response(200, text="<html>Login</html>"))
    with pytest.raises(ValueError, match="non-JSON"):
        await node({"operation": "list_spaces"}).execute({})


@pytest.mark.asyncio
async def test_documented_list_responses(monkeypatch):
    examples = json.loads((Path(__file__).parent / "fixtures/kibana/documented_lists.json").read_text())
    for path, example in examples.items():
        operation = {"/api/spaces/space": "list_spaces", "/api/data_views": "list_data_views", "/api/alerting/rules/_find": "list_rules", "/api/actions/connectors": "list_connectors"}[path]
        transport(monkeypatch, httpx.Response(200, json=example["body"]))
        result = await node({"operation": operation}).execute({})
        assert result["success"] is True
        assert result["data"] == example["body"]


@pytest.mark.asyncio
async def test_list_rules_returns_one_explicit_page(monkeypatch):
    transport(monkeypatch, httpx.Response(200, json={"page": 2, "per_page": 1, "total": 3, "data": [{"id": "rule-2"}]}))
    result = await node({"operation": "list_rules", "page": 2, "per_page": 1}).execute({})
    assert result["items"] == [{"id": "rule-2"}]
    assert result["page"] == 2 and result["per_page"] == 1 and result["total"] == 3


@pytest.mark.parametrize("url", ["http://kibana.example.com", "https://user:pass@kibana.example.com", "https://kibana.example.com/app/home", "https://kibana.example.com?token=x", "https://127.0.0.1", "https://localhost", "https://kibana.example.com/#home"])
def test_refuse_unsafe_or_ambiguous_origins(url):
    with pytest.raises(ValidationError):
        native.KibanaAPIKeyCredential(**{**CREDENTIAL, "api_base_url": url})


@pytest.mark.parametrize("identifier", ["../other", "..", "x?override=true", "x#fragment", "%2F", "x\\y", "x\nheader"])
def test_refuse_resource_path_injection(identifier):
    with pytest.raises(ValidationError):
        native.KibanaGetRuleConfig(id=identifier)


def test_manual_credentials_and_discovery():
    assert NODE_REGISTRY["automation-kibana"] is native.KibanaNode
    credential = native.KibanaAPIKeyCredential(api_base_url=" https://Kibana.example.com:443/ ", api_key=TOKEN)
    assert credential.credential_type == "kibana_api_key"
    assert credential.api_base_url == "https://kibana.example.com"
    assert native.KibanaNode.connection_evidence.operation == "list_spaces"
    assert len(native.ROUTES) == 22


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [httpx.Response(204), httpx.Response(200, json={"unrelated": "object"})])
async def test_connection_requires_spaces_list(monkeypatch, response):
    transport(monkeypatch, response)
    with pytest.raises(ValueError):
        await node({"operation": "list_spaces"}).execute({})
