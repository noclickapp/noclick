"""Zeplin published success examples, one-request mapping and failure semantics."""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import zeplin_node as native
from nodes.core.registry import NodeFactory
from utils import ssrf

TOKEN = 'fixture-personal-token-not-live'
AUTH = {'credential_type': 'zeplin_personal_token', 'personal_access_token': TOKEN}
CONTRACT = json.loads((Path(__file__).parent / 'fixtures/zeplin/contract.json').read_text())
CASES = CONTRACT['cases']


def node(config, auth=AUTH):
    return NodeFactory.create_node(node_id='zeplin-test', node_type='automation-zeplin',
        node_data={'config': config, 'credentials': auth})


def transport(monkeypatch, status, body):
    requests = []
    monkeypatch.setattr(ssrf, '_resolve_host_addresses', AsyncMock(return_value=['93.184.216.34']))
    async def send(request):
        requests.append(request)
        if isinstance(body, Exception):
            raise body
        return httpx.Response(status, json=body) if body is not None else httpx.Response(status)
    guarded = ssrf.guarded_async_client
    monkeypatch.setattr(native, 'guarded_async_client', lambda **kwargs: guarded(**kwargs, transport=httpx.MockTransport(send)))
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('case', CASES, ids=lambda case: case['operation'])
async def test_zeplin_contract_request_and_published_response(monkeypatch, case):
    requests = transport(monkeypatch, case['status'], case['response'])
    result = await node({'operation': case['operation'], **case['config']}).execute({})
    assert result['status'] == 'success', result
    assert len(requests) == 1
    req = requests[0]
    assert req.method == case['method']
    assert str(req.url).split('?')[0] == native.BASE + case['path'].format(**case['config'])
    assert req.headers['authorization'] == 'Bearer ' + TOKEN
    assert TOKEN not in str(req.url) and TOKEN not in str(result)
    if case['body'] is not None:
        assert json.loads(req.content) == case['body']
    else:
        assert not req.content
    if case['operation'].startswith('list_'):
        assert dict(req.url.params) == {'limit': '30', 'offset': '0'}
        assert result['items'] == case['response']
    elif case['status'] != 204:
        assert result['data'] == case['response']


@pytest.mark.asyncio
async def test_zeplin_pagination_retains_offset_and_does_not_follow_urls(monkeypatch):
    rows = [{'id': '5d9caaecb4a3fa9bc9718686', 'url': 'https://untrusted.example/'}] * 2
    requests = transport(monkeypatch, 200, rows)
    result = await node({'operation': 'list_projects', 'limit': 2, 'offset': 8}).execute({})
    assert result['has_more'] and result['next_offset'] == 10 and len(requests) == 1
    assert dict(requests[0].url.params) == {'limit': '2', 'offset': '8'}
    transport(monkeypatch, 200, [])
    result = await node({'operation': 'list_projects', 'offset': 10}).execute({})
    assert result['has_more'] is False and result['next_offset'] is None


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 302, 400, 401, 403, 404, 429, 500])
async def test_zeplin_provider_rejections_preserve_status_and_redact_token(monkeypatch, status):
    requests = transport(monkeypatch, status, {'message': 'Rejected ' + TOKEN})
    result = await node({'operation': 'get_current_user'}).execute({})
    assert result['status'] == 'error' and result['http_status'] == status
    assert TOKEN not in str(result) and len(requests) == 1


@pytest.mark.asyncio
async def test_zeplin_ambiguous_write_is_never_retried(monkeypatch):
    requests = transport(monkeypatch, 200, httpx.ReadTimeout('uncertain'))
    result = await node({'operation': 'update_project', 'project_id': 'a' * 24, 'name': 'Design'}).execute({})
    assert result['status'] == 'error' and 'inspect Zeplin' in result['error'] and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{}, 'invalid', [None]])
async def test_zeplin_malformed_lists_are_errors(monkeypatch, body):
    transport(monkeypatch, 200, body)
    assert (await node({'operation': 'list_projects'}).execute({}))['status'] == 'error'


@pytest.mark.parametrize('config', [
    {'operation': 'get_project', 'project_id': '../other'},
    {'operation': 'list_projects', 'limit': 101},
    {'operation': 'list_projects', 'offset': -1},
    {'operation': 'create_note', 'project_id': 'a' * 24, 'screen_id': 'b' * 24, 'content': 'Review', 'x': 2, 'y': 0},
    {'operation': 'update_note', 'project_id': 'a' * 24, 'screen_id': 'b' * 24, 'note_id': 'c' * 24, 'status': 'closed'},
    {'operation': 'get_current_user', 'api_url': 'https://untrusted.example'},
])
def test_zeplin_invalid_configs_are_refused(config):
    with pytest.raises((ValueError, ValidationError)):
        node(config)


def test_zeplin_manual_credential_defaults_and_connection_evidence():
    credential = native.ZeplinPersonalTokenCredential(personal_access_token=TOKEN)
    assert credential.credential_type == AUTH['credential_type']
    assert native.ZeplinNode.connection_evidence.identity_operation == 'get_current_user'
    for token in ['', 'Bearer token', 'https://untrusted.example', '{{token}}', 'token\nvalue']:
        with pytest.raises((ValueError, ValidationError)):
            native.ZeplinPersonalTokenCredential(personal_access_token=token)
