"""Exercise the native factory and actual outgoing HTTP requests against Zyte's contract."""
import base64
import json
from pathlib import Path
import httpx
import pytest
from nodes import zyte_api_node as native
from nodes.core.registry import NodeFactory

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield

def node(config):
    return NodeFactory.create_node(node_id="zyte-fixture", node_type="automation-zyte-api", node_data={
        "config": config, "credentials": {"credential_type": "zyte_api_key", "api_key": "synthetic-zyte-key"}})

def transport(monkeypatch, status=200, payload=None):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=payload if payload is not None else {"url": "https://example.com", "httpResponseBody": "PGh0bWw+PC9odG1sPg=="})
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests

@pytest.mark.asyncio
@pytest.mark.parametrize('operation,field', list(native.MODES.items()))
async def test_presets_exact_contract_request(monkeypatch, operation, field):
    requests = transport(monkeypatch)
    result = await node({'operation': operation, 'url': 'https://example.com'}).execute({})
    req = requests[0]
    assert req.method == 'POST' and str(req.url) == 'https://api.zyte.com/v1/extract'
    assert req.headers['authorization'] == 'Basic ' + base64.b64encode(b'synthetic-zyte-key:').decode()
    assert json.loads(req.content) == {'url': 'https://example.com', field: True}
    assert result['status'] == 'success' and result['data']['url'] == 'https://example.com'

@pytest.mark.asyncio
async def test_documented_post_text(monkeypatch):
    requests = transport(monkeypatch)
    fixture = json.loads((Path(__file__).parent/'fixtures/zyte-api/post-text.json').read_text())
    await node({'operation': 'submit_http_post', 'url': fixture['url'], 'http_request_text': fixture['httpRequestText']}).execute({})
    assert json.loads(requests[0].content) == fixture

@pytest.mark.asyncio
async def test_connection_reachability(monkeypatch):
    requests = transport(monkeypatch)
    assert (await node({'operation':'check_connection'}).execute({}))['status'] == 'success'
    assert json.loads(requests[0].content) == {'url':'https://example.com','httpResponseBody':True}
    assert native.ZyteApiNode.connection_evidence.proves == 'reachability'

@pytest.mark.asyncio
@pytest.mark.parametrize('status', [400,401,403,422,429,500])
async def test_provider_rejection_preserves_detail_redacts_key(monkeypatch,status):
    transport(monkeypatch,status,{'detail':'Rejected synthetic-zyte-key'})
    with pytest.raises(ValueError,match=f'HTTP {status}: Rejected \\[redacted\\]'):
        await node({'operation':'check_connection'}).execute({})

@pytest.mark.asyncio
async def test_invalid_success_response(monkeypatch):
    transport(monkeypatch,payload={'unexpected':True})
    with pytest.raises(ValueError,match='invalid extraction response'):
        await node({'operation':'check_connection'}).execute({})

@pytest.mark.parametrize('url',['http://127.0.0.1/a','file:///etc/passwd','https://user:pass@example.com'])
def test_url_contract(url):
    with pytest.raises(ValueError):
        node({'operation':'get_http_body','url':url})
