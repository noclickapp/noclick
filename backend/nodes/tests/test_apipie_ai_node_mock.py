"""Exercise factory routing against request examples in APIpie's published contract."""
import json
from pathlib import Path
import httpx
import pytest
from nodes import apipie_ai_node as native
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / "fixtures/apipie-ai/requests.json").read_text())

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield

def node(config):
    return NodeFactory.create_node(node_id="apipie-test", node_type="automation-apipie-ai", node_data={
        "config": config, "credentials": {"credential_type": "apipie_ai_api_key", "api_key": "test-apipie-secret-123"}})

@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["config"]["operation"])
async def test_documented_requests(monkeypatch, case):
    seen = []
    def respond(request):
        seen.append(request)
        return httpx.Response(200, json={"scope": "app", "key": "test-app", "settings": {}})
    monkeypatch.setattr(native, "guarded_async_client", lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(respond), **kw))
    result = await node(case["config"]).execute({})
    assert result["data"]["key"] == "test-app"
    assert len(seen) == 1
    req = seen[0]
    assert req.method == case["method"]
    assert req.url.host == "apipie.ai" and req.url.path == case["path"]
    assert req.headers["Authorization"] == "Bearer test-apipie-secret-123"
    expected = {k: v for k,v in case["config"].items() if k != "operation"}
    query = {k: expected.pop(k) for k in case["query_fields"] if k in expected}
    assert dict(req.url.params) == {k: str(v) for k,v in query.items()}
    if req.method in {"POST", "PUT"}:
        if case["config"]["operation"] == "create_chat_completion": expected["stream"] = False
        if case["config"]["operation"] == "generate_image": expected["response_format"] = "url"
        assert json.loads(req.content) == expected
    else:
        assert not req.content

@pytest.mark.asyncio
@pytest.mark.parametrize("status,body", [(401,{"error":"invalid test-apipie-secret-123"}), (200,{"error":"bad request"}), (200,"unexpected"), (302,{})])
async def test_provider_errors_fail_and_redact(monkeypatch,status,body):
    monkeypatch.setattr(native, "guarded_async_client", lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(status,json=body)), **kw))
    with pytest.raises(Exception) as exc:
        await node({"operation":"get_state"}).execute({})
    assert "test-apipie-secret-123" not in str(exc.value)

def test_conditional_user_and_required_embedding():
    with pytest.raises(ValueError):
        native.UpdateStateConfig(enable_user_states=True)
    with pytest.raises(ValueError):
        native.CreateEmbeddingConfig(model="text-embedding-3-small")
    assert native.ApipieAICredential(api_key="test-secret").credential_type == "apipie_ai_api_key"
