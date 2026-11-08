"""Offline ImageKit requests and provider-authored payload regressions.

routes.json pins the provider OpenAPI examples and operation IDs at version
1.0.0: https://raw.githubusercontent.com/imagekit-developer/openapi/main/openapi.yml
"""
import base64
import json
from email.parser import BytesParser
from email.policy import default
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import imagekit_io_node as native
from nodes.core.registry import NodeFactory
from nodes.core.credential_connect import shape_credential

FIXTURES = json.loads((Path(__file__).parent / 'fixtures/imagekit-io/routes.json').read_text())
TOKEN = 'imagekit-synthetic-private-key-42'


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credential=True):
    return NodeFactory.create_node(node_id='imagekit-test', node_type='automation-imagekit-io',
        node_data={'config': config, **({'credentials': {'credential_type': 'imagekit_io_api_key', 'private_api_key': TOKEN}} if credential else {})})


def transport(monkeypatch, reply):
    requests = []
    def capture(request):
        requests.append(request)
        return reply(request)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(capture), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', FIXTURES)
async def test_imagekit_io_contract_requests(monkeypatch, operation):
    fixture = FIXTURES[operation]
    requests = transport(monkeypatch, lambda _: httpx.Response(fixture['status'],
        **({'json': fixture['response']} if fixture['status'] != 204 else {})))
    result = await node(fixture['config']).execute({})
    assert result['status'] == 'success' and result['http_status'] == fixture['status']
    assert result['data'] == fixture['response']
    assert len(requests) == 1
    req = requests[0]
    assert req.method == fixture['method'] and req.url.path == fixture['path']
    assert req.url.host == ('upload.imagekit.io' if operation == 'upload_file' else 'api.imagekit.io')
    assert req.headers['Authorization'] == 'Basic ' + base64.b64encode((TOKEN + ':').encode()).decode()
    assert req.headers['Accept'] == 'application/json'
    if fixture['query'] is not None:
        assert dict(req.url.params) == {k: str(v) for k, v in fixture['query'].items()}
    elif operation == 'upload_file':
        msg = BytesParser(policy=default).parsebytes(b'Content-Type: ' + req.headers['content-type'].encode() + b'\r\n\r\n' + req.content)
        assert {part.get_param('name', header='content-disposition'): part.get_payload(decode=True).decode() for part in msg.iter_parts()} == {
            k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in fixture['body'].items()}
    elif fixture['body']:
        assert json.loads(req.content) == fixture['body']
    else:
        assert not req.content


@pytest.mark.asyncio
async def test_imagekit_io_pagination(monkeypatch):
    rows = FIXTURES['list_files']['response']
    transport(monkeypatch, lambda _: httpx.Response(200, json=rows))
    result = await node({'operation': 'list_files', 'limit': len(rows), 'skip': 10}).execute({})
    assert result['pagination'] == {'limit': len(rows), 'skip': 10, 'next_skip': 10 + len(rows)}
    result = await node({'operation': 'list_files'}).execute({})
    assert result['pagination']['next_skip'] is None


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', ['delete_files', 'add_tags', 'remove_tags', 'remove_ai_tags', 'rename_file'])
async def test_imagekit_io_partial_success_is_explicit(monkeypatch, operation):
    body = {'message': 'Some files failed', 'errors': [{'fileId': 'missing'}]}
    transport(monkeypatch, lambda _: httpx.Response(207, json=body))
    result = await node(FIXTURES[operation]['config']).execute({})
    assert result == {'status': 'partial', 'http_status': 207, 'data': body}


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 400, 401, 403, 404, 429, 500])
async def test_imagekit_io_rejection_redaction_and_no_retries(monkeypatch, status):
    requests = transport(monkeypatch, lambda _: httpx.Response(status, text='Rejected ' + TOKEN))
    result = await node({'operation': 'list_files'}).execute({})
    assert result == {'status': 'error', 'http_status': status, 'error': 'Rejected [redacted]'}
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('response', [httpx.Response(200, text='<html>error</html>'), httpx.Response(200, json={})])
async def test_imagekit_io_invalid_list_response(monkeypatch, response):
    transport(monkeypatch, lambda _: response)
    assert (await node({'operation': 'list_files'}).execute({}))['status'] == 'error'


@pytest.mark.asyncio
async def test_imagekit_io_transport_failure_and_missing_credential(monkeypatch):
    def fail(req):
        raise httpx.ReadTimeout('secret ' + TOKEN, request=req)
    requests = transport(monkeypatch, fail)
    result = await node(FIXTURES['create_folder']['config']).execute({})
    assert result['status'] == 'error' and TOKEN not in str(result) and len(requests) == 1
    with pytest.raises(ValueError, match='private API key'):
        await node({'operation': 'list_files'}, credential=False).execute({})


def test_imagekit_io_manual_credential_and_validation():
    shaped, errors, resolved = shape_credential('imagekit_io_api_key', {'private_api_key': '  ' + TOKEN + '  '})
    assert not errors and shaped == {'private_api_key': TOKEN}
    assert resolved[1] is native.ImageKitAPIKeyCredential
    assert native.ImageKitAPIKeyCredential.model_validate(shaped).credential_type == 'imagekit_io_api_key'
    for value in ['https://example.com', '<token>', 'key:password', 'key\nheader']:
        with pytest.raises(ValidationError):
            native.ImageKitAPIKeyCredential(private_api_key=value)
    for config in [
        {'operation': 'get_file', 'file_id': '../secret'},
        {'operation': 'list_files', 'limit': 1001},
        {'operation': 'list_files', 'skip': -1},
        {'operation': 'upload_file', 'file': 'file:///tmp/x', 'file_name': 'x'},
        {'operation': 'purge_cache', 'url': 'https://user:pass@example.com/x'},
        {'operation': 'update_file', 'file_id': 'abc'},
        {'operation': 'add_tags', 'file_ids': [], 'tags': ['x']},
    ]:
        with pytest.raises(ValueError):
            node(config)
