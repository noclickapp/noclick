"""Exercise Parseur requests through the native node factory, without an account."""
import json
from pathlib import Path
import httpx
import pytest
from nodes import parseur_node as native
from nodes.core.registry import NodeFactory

TOKEN = 'synthetic-parseur-key-42'

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield

def node(config, credential_type='parseur_api_key'):
    return NodeFactory.create_node(node_id='parseur-test', node_type='automation-parseur',
        node_data={'config': config, 'credentials': {'credential_type': credential_type, 'api_key': TOKEN}})

def transport(monkeypatch, status=200, payload=None, raw=None):
    requests = []
    client = httpx.AsyncClient
    def reply(request):
        requests.append(request)
        return httpx.Response(status, json=payload) if raw is None else httpx.Response(status, content=raw)
    monkeypatch.setattr(native.httpx, 'AsyncClient', lambda **kw: client(transport=httpx.MockTransport(reply), **kw))
    return requests

@pytest.mark.asyncio
@pytest.mark.parametrize('operation,config,method,path,body', [
    ('list_mailboxes', {'page': 2, 'search': 'Invoices'}, 'GET', '/parser', None),
    ('get_document', {'document_id': '123456789'}, 'GET', '/document/123456789', None),
    ('copy_document', {'document_id': '123', 'target_mailbox_id': '456'}, 'POST', '/document/123/copy/456', None),
    ('skip_document', {'document_id': '123'}, 'POST', '/document/123/skip', None),
    ('reprocess_document', {'document_id': '123'}, 'POST', '/document/123/process', None),
    ('delete_mailbox', {'mailbox_id': '98765'}, 'DELETE', '/parser/98765', None),
    ('update_mailbox', {'mailbox_id': '98765', 'name': 'Invoices'}, 'PUT', '/parser/98765', {'name': 'Invoices'}),
    ('upload_email', {'subject': 'Invoice', 'sender': 'sender@example.com', 'recipient': 'invoices@in.parseur.com', 'body_plain': 'Invoice 42'}, 'POST', '/email', {'subject': 'Invoice', 'from': 'sender@example.com', 'recipient': 'invoices@in.parseur.com', 'body_plain': 'Invoice 42'}),
    ('update_custom_download', {'mailbox_id': '98765', 'download_id': '12', 'name': 'My Download', 'items': ['CustomerName']}, 'PATCH', '/parser/98765/export_config/12', {'name': 'My Download', 'type': 'PARSER', 'items': ['CustomerName']}),
])
async def test_requests(monkeypatch, operation, config, method, path, body):
    requests = transport(monkeypatch, payload={'id': 42})
    result = await node({'operation': operation, **config}).execute({})
    assert result == {'data': {'id': 42}, 'http_status': 200}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == path
    assert request.url.host == 'api.parseur.com'
    assert request.headers['Authorization'] == 'Token ' + TOKEN
    assert (json.loads(request.content) if request.content else None) == body
    if operation == 'list_mailboxes':
        assert dict(request.url.params) == {'page': '2', 'page_size': '25', 'search': 'Invoices'}

@pytest.mark.asyncio
async def test_documented_mailbox_page_and_redaction(monkeypatch):
    payload = json.loads((Path(__file__).parent / 'fixtures/parseur/mailboxes.json').read_text())
    payload['secret'] = TOKEN
    requests = transport(monkeypatch, payload=payload)
    result = await node({'operation': 'list_mailboxes'}).execute({})
    assert result['data']['results'][0]['id'] == payload['results'][0]['id']
    assert 'secret' not in result['data'] and TOKEN not in str(result)
    assert len(requests) == 1

@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 401, 403, 404, 429, 500])
async def test_http_failure_does_not_claim_success_or_leak_token(monkeypatch, status):
    requests = transport(monkeypatch, status=status, payload={'detail': TOKEN})
    with pytest.raises(ValueError, match=f'HTTP {status}') as error:
        await node({'operation': 'get_document', 'document_id': '123'}).execute({})
    assert TOKEN not in str(error.value) and len(requests) == 1

@pytest.mark.asyncio
async def test_empty_delete_response(monkeypatch):
    transport(monkeypatch, status=204, raw=b'')
    assert await node({'operation': 'delete_document', 'document_id': '123'}).execute({}) == {'data': None, 'http_status': 204}

@pytest.mark.asyncio
async def test_invalid_json(monkeypatch):
    transport(monkeypatch, raw=b'<html>Error</html>')
    with pytest.raises(ValueError, match='invalid JSON'):
        await node({'operation': 'list_mailboxes'}).execute({})

@pytest.mark.parametrize('identifier', ['../123', '123?x=1', 'https://evil.test', '123/456'])
def test_refuse_path_injection(identifier):
    with pytest.raises(ValueError):
        node({'operation': 'get_document', 'document_id': identifier})

def test_refuse_wrong_credential_family():
    with pytest.raises(ValueError):
        node({'operation': 'list_mailboxes'}, 'other_api_key')
