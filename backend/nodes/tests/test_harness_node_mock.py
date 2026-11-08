"""Exercise real Harness execute paths with a fake HTTP boundary."""
import json
import httpx
import pytest
from nodes import harness_node as native
from nodes.core.registry import NodeFactory

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield

CREDENTIAL = {"credential_type": "harness_api_key", "api_key": "synthetic-harness-key", "account_identifier": "account"}

def config_for(operation):
    method, path, resource, action = native.ROUTES[operation]
    c = {"operation": operation}
    if resource != "organization": c["org_identifier"] = "org"
    if resource not in {"organization", "project"}: c["project_identifier"] = "project"
    if action != "list":
        c["plan_execution_id" if resource == "execution" else "org_identifier" if resource == "organization" else resource + "_identifier"] = "owned"
    if action in {"create", "update"}: c.update(name="Owned", tags={"team": "delivery"})
    if resource == "environment" and action in {"create", "update"}: c["environment_type"] = "PreProduction"
    if action == "execute": c.update(module_type="CD", input_set_yaml="pipeline:\n  identifier: owned\n")
    return c

@pytest.mark.asyncio
@pytest.mark.parametrize("operation", native.ROUTES)
async def test_request_contract(monkeypatch, operation):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"status": "SUCCESS", "data": {"content": []}})
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    n = NodeFactory.create_node(node_id="fixture", node_type="automation-harness", node_data={"config": config_for(operation), "credentials": CREDENTIAL})
    result = await n.execute({})
    assert result["status"] == "success"
    assert len(requests) == 1
    r = requests[0]
    method, path, resource, action = native.ROUTES[operation]
    assert r.method == method
    assert r.url.host == "app.harness.io"
    assert r.url.params["accountIdentifier"] == "account"
    assert r.headers["x-api-key"] == CREDENTIAL["api_key"]
    if resource != "organization": assert r.url.params["orgIdentifier"] == "org"
    if action in {"create", "update"}:
        body = json.loads(r.content)
        if resource in {"organization", "project"}: body = body[resource]
        assert body["identifier"] == "owned"
        assert body["tags"] == {"team": "delivery"}
    if action == "execute":
        assert r.url.params["moduleType"] == "CD"
        assert json.loads(r.content) == config_for(operation)["input_set_yaml"]
    if action == "list":
        assert r.url.params["pageIndex" if resource in {"organization", "project"} else "page"] == "0"

@pytest.mark.asyncio
@pytest.mark.parametrize("status,body", [(401, {"message": "Invalid key"}), (200, {"status": "FAILURE", "message": "Denied"})])
async def test_provider_failure_is_not_success(monkeypatch, status, body):
    monkeypatch.setattr(native, "guarded_async_client", lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(status,json=body)), **kw))
    n = NodeFactory.create_node(node_id="fixture", node_type="automation-harness", node_data={"config": {"operation": "list_organizations"}, "credentials": CREDENTIAL})
    assert (await n.execute({}))["status"] == "error"

@pytest.mark.asyncio
async def test_account_evidence_exposes_organization_names(monkeypatch):
    body = {"status": "SUCCESS", "data": {"content": [{"organization": {"identifier": "org", "name": "Delivery Team"}}]}}
    monkeypatch.setattr(native, "guarded_async_client", lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200,json=body)), **kw))
    n = NodeFactory.create_node(node_id="fixture", node_type="automation-harness", node_data={"config": {"operation": "list_organizations"}, "credentials": CREDENTIAL})
    assert (await n.execute({}))["items"][0]["name"] == "Delivery Team"

@pytest.mark.parametrize("value", ["../other", "a/b", "a?x=1", "a\\r\\n"])
def test_path_identifiers_refuse_delimiters(value):
    with pytest.raises(ValueError):
        native.GetPipeline(org_identifier="org", project_identifier="project", pipeline_identifier=value)
