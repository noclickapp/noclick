"""Verify Mezmo wire behavior through the real node factory using synthetic keys.

Covers all ten contract operations, destructive bulk shapes, connection evidence,
required usage arguments, response envelopes and token redaction without a network.
"""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import mezmo_node as native
from nodes.core.credential_connect import shape_credential
from nodes.core.registry import NodeFactory

KEY = "synthetic-mezmo-enterprise-key"
FIXTURES = json.loads((Path(__file__).parent / "fixtures/mezmo/responses.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="mezmo-test", node_type="automation-mezmo", node_data={
        "config": config, "credentials": {"credential_type": "mezmo_access_key", "access_key": KEY},
    })


def transport(monkeypatch, body, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,fixture,body,params", [
    ({"operation": "get_enterprise"}, "GET", "/v3/enterprise", "enterprise", None, {}),
    ({"operation": "create_account", "account": {"company": "Snippet Factory", "owneremail": "admin@snippetfactory.com", "plan": {"type": "enterprise"}, "retention": 7}}, "POST", "/v3/enterprise/account", "account", {"company": "Snippet Factory", "owneremail": "admin@snippetfactory.com", "plan": {"type": "enterprise"}, "retention": 7}, {}),
    ({"operation": "bulk_account_operations", "operations": [{"action": "UPDATE", "entity_id": "471ef1c4154b987a94509213", "entity": {"external_id": None, "retention": 7}}]}, "PATCH", "/v3/enterprise/account", "bulk", {"operations": [{"action": "UPDATE", "entity_id": "471ef1c4154b987a94509213", "entity": {"external_id": None, "retention": 7}}]}, {}),
    ({"operation": "get_account", "account_id": "5fbca354be"}, "GET", "/v3/enterprise/account/5fbca354be", "account", None, {}),
    ({"operation": "attach_account", "account_id": "5fbca354be", "owner": "admin@snippetfactory.com", "plan": "enterprise"}, "PATCH", "/v3/enterprise/account/5fbca354be/attach", "account", {"owner": "admin@snippetfactory.com", "plan": "enterprise"}, {}),
    ({"operation": "detach_account", "account_id": "74de7c06e4"}, "PATCH", "/v3/enterprise/account/74de7c06e4/detach", "account", None, {"deactivate": "false"}),
    ({"operation": "list_pipelines"}, "GET", "/v3/enterprise/pipeline", "list", None, {}),
    ({"operation": "get_pipeline_health", "include_logs": False}, "GET", "/v3/enterprise/pipeline/metric/health", "list", None, {"include_logs": "false"}),
    ({"operation": "get_pipeline_usage", "from_time": "2026-01-01T00:00:00Z", "to_time": "2026-01-02T00:00:00Z", "bucket": 3600, "include_deleted": False, "pipeline_id": "018e438c-b917-7a8a-821c-f5aaeedbd6a7", "traffic": "egress"}, "GET", "/v3/enterprise/pipeline/metric/usage", "list", None, {"from": "2026-01-01T00:00:00Z", "to": "2026-01-02T00:00:00Z", "bucket": "3600", "include_deleted": "false", "pipeline_id": "018e438c-b917-7a8a-821c-f5aaeedbd6a7", "traffic": "egress"}),
    ({"operation": "get_pipeline_node_schemas"}, "GET", "/v3/enterprise/pipeline/node", "schemas", None, {}),
])
async def test_mezmo_contract_wires(monkeypatch, config, method, path, fixture, body, params):
    requests = transport(monkeypatch, FIXTURES[fixture], 201 if config["operation"] in {"create_account", "attach_account"} else 200)
    n = node(config)
    n.emit = AsyncMock()
    result = await n.execute({})
    request, = requests
    assert request.method == method and request.url.host == "api.mezmo.com" and request.url.path == path
    assert request.headers["authorization"] == "Token " + KEY
    assert dict(request.url.params) == params
    assert (json.loads(request.content) if request.content else None) == body
    if body is not None:
        assert request.headers["content-type"] == ("application/x-bulk+json" if config["operation"] == "bulk_account_operations" else "application/json")
    assert result == {**FIXTURES[fixture], "status": "success"}
    n.emit.assert_awaited_once_with(result)


@pytest.mark.parametrize("item", [
    {"action": "UPDATE", "entity": {"retention": 7}},
    {"action": "DELETE"}, {"action": "CREATE"},
    {"action": "CREATE", "entity_id": "existing", "entity": {}},
    {"action": "UPDATE", "entity_id": "existing"},
    {"action": "DESTROY", "entity_id": "existing"},
    {"action": "CREATE", "entity": {"retention": 91}},
    {"action": "UPDATE", "entity_id": "existing", "entity": {"company": None}},
])
def test_mezmo_invalid_bulk_never_reaches_api(item):
    with pytest.raises(ValidationError):
        native.MezmoBulkAccountsConfig(operations=[item])


@pytest.mark.parametrize("args", [
    {}, {"from_time": "today", "to_time": "tomorrow", "bucket": 60},
    {"from_time": "2026-01-02T00:00:00Z", "to_time": "2026-01-01T00:00:00Z", "bucket": 60},
    {"from_time": "2026-01-01T00:00:00", "to_time": "2026-01-02T00:00:00", "bucket": 60},
])
def test_mezmo_usage_requires_complete_valid_window(args):
    with pytest.raises(ValidationError):
        native.MezmoPipelineUsageConfig(**args)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
async def test_mezmo_errors_preserve_provider_text_redact_key_and_never_retry(monkeypatch, status):
    requests = transport(monkeypatch, {"message": "Rejected " + KEY}, status)
    result = await node({"operation": "get_enterprise"}).execute({})
    assert result == {"status": "error", "http_status": status, "error": "Rejected [redacted]"}
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, [], {"meta": {}, "data": None}, {"meta": {}, "data": [], "error": "denied"}])
async def test_mezmo_malformed_response_refuses_success(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError):
        await node({"operation": "get_enterprise"}).execute({})


@pytest.mark.asyncio
async def test_mezmo_enterprise_evidence_and_redaction(monkeypatch):
    transport(monkeypatch, {"meta": {}, "data": {"name": "Acme Inc.", "nested": [KEY], "access_key": KEY}})
    result = await node({"operation": "get_enterprise"}).execute({})
    assert result["data"] == {"name": "Acme Inc.", "nested": ["[redacted]"]}
    assert native.MezmoNode.connection_evidence.identity_operation == "get_enterprise"


def test_mezmo_can_be_shaped_by_hand_without_type_tag():
    shaped, errors, resolved = shape_credential("mezmo_access_key", {"access_key": KEY})
    assert not errors and shaped["access_key"] == KEY
    assert resolved == ("automation-mezmo", native.MezmoAccessKeyCredential)
    assert native.MezmoAccessKeyCredential(access_key=KEY).credential_type == "mezmo_access_key"
    with pytest.raises(ValidationError):
        native.MezmoAccessKeyCredential(access_key="Token " + KEY)
