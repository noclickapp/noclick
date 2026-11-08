"""Check Typefully request serialization for every exposed v2 operation.

The independent fixtures cover pagination, asynchronous publishing, and partial
updates; negative cases ensure errors and invalid credentials cannot look successful.
"""
import json
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes.core.registry import NodeFactory
from nodes.typefully_node import TypefullyAPIKeyCredential, TypefullyNode

CASES = json.loads((Path(__file__).parent / 'fixtures/typefully/operations.json').read_text())
TOKEN = 'typefully-test-api-key'


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    # These HTTP-only unit tests do not access the database.
    yield


def node(config):
    return NodeFactory.create_node(node_type='automation-typefully', node_id='typefully-test',
        node_data={'config': config, 'credentials': {'credential_type': 'typefully_api_key', 'api_key': TOKEN}})


def transport(monkeypatch, handler):
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs == {'timeout': 30, 'follow_redirects': False, 'trust_env': False}
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as session:
            yield session
    monkeypatch.setattr('nodes.typefully_node.guarded_async_client', client)


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', CASES)
async def test_typefully_contract_requests(monkeypatch, operation):
    case = CASES[operation]
    calls = []
    def handle(request):
        calls.append(request)
        assert request.url.host == 'api.typefully.com'
        assert request.method == case['method']
        assert request.url.path == case['path']
        assert request.headers['Authorization'] == 'Bearer ' + TOKEN
        assert {k: request.url.params.get_list(k) for k in request.url.params} == case['query']
        assert (json.loads(request.content) if request.content else None) == case['body']
        return httpx.Response(204) if case['status'] == 204 else httpx.Response(case['status'], json=case['response'])
    transport(monkeypatch, handle)
    result = await node(case['config']).execute({})
    assert len(calls) == 1
    assert result['status'] == 'success'
    assert result['http_status'] == case['status']
    if case['status'] == 204:
        assert result['deleted'] is True
        assert result['draft_id'] == 456
    else:
        assert result['data'] == case['response']
    if operation.startswith('list_'):
        assert result['next_offset'] == 2
    if operation == 'create_draft':
        assert result['data']['publish_state'] == 'in_progress'
        assert result['data']['status'] == 'draft'


@pytest.mark.parametrize('key', ['Bearer abc', 'abc\nheader', 'https://example.com/key', '<token>'])
def test_typefully_rejects_invalid_keys(key):
    with pytest.raises(ValueError):
        TypefullyAPIKeyCredential(api_key=key)


@pytest.mark.parametrize('config', [
    {'operation': 'get_social_set', 'social_set_id': '../other'},
    {'operation': 'get_media_status', 'social_set_id': 123, 'media_id': '../other'},
    {'operation': 'list_social_sets', 'limit': 51},
    {'operation': 'create_media_upload', 'social_set_id': 123, 'file_name': 'file.exe'},
    {'operation': 'create_draft', 'social_set_id': 123, 'platforms': {'x': {'enabled': True}}},
    {'operation': 'create_draft', 'social_set_id': 123, 'platforms': {}, 'publish_at': 'now', 'plan_at': 'next-free-slot'},
    {'operation': 'get_queue', 'social_set_id': 123, 'start_date': '2026-02-28', 'end_date': '2026-02-01'},
])
def test_typefully_invalid_configs(config):
    with pytest.raises((ValueError, ValidationError)):
        TypefullyNode.parse_config({'config': config, 'credentials': {'api_key': TOKEN}})


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [401, 403, 422, 429, 500])
async def test_typefully_errors_do_not_succeed(monkeypatch, status):
    transport(monkeypatch, lambda r: httpx.Response(status, json={'error': {'message': 'Rejected ' + TOKEN}}))
    with pytest.raises(ValueError, match=rf'Typefully HTTP {status}: Rejected \[redacted\]'):
        await node({'operation': 'get_current_user'}).execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [[], {'error': {'message': 'bad'}}, {'results': [], 'count': 2}])
async def test_typefully_invalid_responses(monkeypatch, body):
    transport(monkeypatch, lambda r: httpx.Response(200, json=body))
    with pytest.raises(ValueError):
        await node({'operation': 'list_social_sets'}).execute({})


@pytest.mark.asyncio
async def test_typefully_does_not_follow_next_url(monkeypatch):
    body = {'results': [], 'count': 0, 'limit': 10, 'offset': 0, 'next': 'https://other.example/private'}
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, json=body)
    transport(monkeypatch, handle)
    result = await node({'operation': 'list_social_sets'}).execute({})
    assert len(calls) == 1
    assert result['next_offset'] is None
