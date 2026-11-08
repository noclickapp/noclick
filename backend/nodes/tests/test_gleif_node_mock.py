"""Exercise every operation with the publisher's verbatim saved responses."""
import json
from pathlib import Path

import httpx
import pytest

from nodes import gleif_node as native
from nodes.core.registry import NodeFactory

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/gleif/postman_examples.json').read_text())
CASES = [(case, reply) for case in FIXTURE['cases'] for reply in case['responses']]


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='gleif-test', node_type='automation-gleif', node_data={'config': config})


@pytest.mark.asyncio
@pytest.mark.parametrize('case,reply', CASES, ids=[f"{c['operation']}-{i}" for i, (c, _) in enumerate(CASES)])
async def test_published_examples(monkeypatch, case, reply):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(reply.get('code') or 200, content=reply['body'], headers={'Content-Type': 'application/vnd.api+json'})

    def client(**kwargs):
        assert kwargs == {'timeout': 30, 'trust_env': False, 'follow_redirects': False}
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native, 'guarded_async_client', client)
    result = await node(case['config']).execute({})
    assert len(requests) == 1
    request = requests[0]
    assert request.method == 'GET'
    assert str(request.url).split('?')[0] == native.BASE + case['path']
    assert request.headers['Accept'] == 'application/vnd.api+json'
    assert 'authorization' not in request.headers
    assert not request.content
    expected = {}
    if case['operation'] == 'list_lei_records':
        expected = {'page[size]': '2', 'page[number]': '100'}
    elif case['operation'].startswith('search_'):
        expected = {'field': case['config']['field'], 'q': case['config']['query']}
    assert dict(request.url.params) == expected
    assert result['status'] == 'success'
    assert result['operation'] == case['operation']
    for key, value in json.loads(reply['body']).items():
        assert result[key] == value


@pytest.mark.parametrize('config', [
    {'operation': 'get_lei_record', 'lei': '../etc/passwd'},
    {'operation': 'get_issuer', 'resource_id': '..'},
    {'operation': 'get_legal_form', 'resource_id': 'x?other=y'},
    {'operation': 'list_lei_records', 'page_size': 201},
    {'operation': 'list_lei_records', 'page_number': 0},
    {'operation': 'search_fuzzy', 'query': 'test', 'field': 'unsupported'},
    {'operation': 'get_lei_record'},
    {'operation': 'delete_lei_record', 'lei': '529900W18LQJJN6SJ336'},
])
def test_invalid_config(config):
    assert native.GleifNode.validate_config({'config': config})['valid'] is False


@pytest.mark.asyncio
@pytest.mark.parametrize('status,body', [(401, {'errors': [{'detail': 'Denied'}]}), (429, {'errors': [{'detail': 'Rate limited'}]}), (200, {'errors': []}), (200, {'data': 'bad'}), (200, {}), (302, {'data': []})])
async def test_provider_failures_are_not_success(monkeypatch, status, body):
    def client(**kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(status, json=body)), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    with pytest.raises((httpx.HTTPStatusError, ValueError)):
        await node({'operation': 'list_lei_records'}).execute({})


def test_public_api_has_no_credentials_and_reachability_evidence():
    assert native.GleifFullConfig.model_fields['credentials'].annotation is type(None)
    assert native.GleifNode.connection_evidence.proves == 'reachability'
    assert len(native.ROUTES) == 25
