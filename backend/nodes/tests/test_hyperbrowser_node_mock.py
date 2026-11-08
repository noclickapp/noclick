"""Native factory and Hyperbrowser wire-contract regressions."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import hyperbrowser_node as native
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / 'fixtures/hyperbrowser/requests.json').read_text())
KEY = 'synthetic-hyperbrowser-key'


def node(config):
    return NodeFactory.create_node(node_id='hyperbrowser-test', node_type='automation-hyperbrowser',
        node_data={'config': config, 'credentials': {'credential_type': 'hyperbrowser_api_key', 'api_key': KEY}})


def transport(monkeypatch, response):
    requests = []
    def handle(request):
        requests.append(request)
        return response
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handle), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('case', CASES, ids=lambda c: c['config']['operation'])
async def test_operation_wire_contract(monkeypatch, case):
    body = {'id': 'owned', 'status': 'pending', 'sessions': [{'id': 'session'}], 'profiles': [{'id': 'profile'}]}
    if case['config']['operation'] in {'stop_session', 'delete_profile', 'stop_hyper_agent'}:
        body = {'success': True}
    requests = transport(monkeypatch, httpx.Response(200, json=body))
    result = await node(case['config']).execute({})
    assert result['data'] == body and result['status'] == 'success'
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case['method'] and request.url.path == case['path']
    assert request.url.host == 'api.hyperbrowser.ai' and request.headers['x-api-key'] == KEY
    if request.method == 'POST':
        assert json.loads(request.content) == {k: v for k, v in case['config'].items() if k != 'operation'}
    if case['config']['operation'].startswith('list_'):
        assert request.url.params['page'] == '1' and len(result['items']) == 1


@pytest.mark.asyncio
async def test_schema_alias_nested_options_and_false(monkeypatch):
    requests = transport(monkeypatch, httpx.Response(200, json={'jobId': 'job'}))
    config = {'operation': 'start_extract', 'urls': ['https://example.com'], 'schema': {'type': 'object'},
        'sessionOptions': {'useProxy': False, 'profile': {'id': 'profile', 'persistChanges': True}}, 'waitFor': 0}
    await node(config).execute({})
    assert json.loads(requests[0].content) == {k: v for k, v in config.items() if k != 'operation'}


@pytest.mark.asyncio
async def test_pagination_filter_and_empty_account(monkeypatch):
    body = {'sessions': [], 'totalCount': 100, 'page': 2, 'pageSize': 10}
    requests = transport(monkeypatch, httpx.Response(200, json=body))
    result = await node({'operation': 'list_sessions', 'page': 2, 'status': 'closed'}).execute({})
    assert dict(requests[0].url.params) == {'page': '2', 'status': 'closed'}
    assert result['items'] == [] and result['data'] == body and 'complete' not in result


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 401, 403, 404, 429, 500])
async def test_http_errors_redact_key_and_do_not_retry(monkeypatch, status):
    requests = transport(monkeypatch, httpx.Response(status, text='rejected ' + KEY))
    with pytest.raises(ValueError) as exc:
        await node({'operation': 'list_sessions'}).execute({})
    assert str(status) in str(exc.value) and KEY not in str(exc.value) and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [[], {}, {'sessions': None}, {'sessions': [], 'success': False}])
async def test_connection_requires_valid_resource_list(monkeypatch, body):
    transport(monkeypatch, httpx.Response(200, json=body))
    with pytest.raises(ValueError):
        await node({'operation': 'list_sessions'}).execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,field', [('stop_session', 'session_id'), ('delete_profile', 'profile_id'), ('stop_hyper_agent', 'job_id')])
async def test_unconfirmed_mutation_is_never_reported_successful(monkeypatch, operation, field):
    transport(monkeypatch, httpx.Response(200, json={'success': False}))
    with pytest.raises(ValueError, match='did not confirm'):
        await node({'operation': operation, field: 'owned-id'}).execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize('identifier', ['..', '../foreign', 'x?secret=y', 'x#fragment', 'x\\path'])
async def test_path_injection_refused_before_http(monkeypatch, identifier):
    requests = transport(monkeypatch, httpx.Response(200, json={}))
    with pytest.raises(ValueError):
        await node({'operation': 'get_session', 'session_id': identifier}).execute({})
    assert requests == []


def test_manual_credential_default_and_required_arguments():
    credential = native.HyperbrowserApiKeyCredential(api_key=KEY)
    assert credential.credential_type == 'hyperbrowser_api_key'
    for config in [{'operation': 'get_session'}, {'operation': 'start_scrape'}, {'operation': 'start_extract', 'urls': []},
                   {'operation': 'get_scrape', 'job_id': 'not-a-uuid'}, {'operation': 'get_scrape_status', 'job_id': 'not-a-uuid'},
                   {'operation': 'list_sessions', 'page': 0}, {'operation': 'search_web'}, {'operation': 'unknown'}]:
        with pytest.raises((ValueError, ValidationError)):
            native.HyperbrowserNode.parse_config({'config': config, 'credentials': credential.model_dump()})
    assert len(native.OPERATIONS) == 25
