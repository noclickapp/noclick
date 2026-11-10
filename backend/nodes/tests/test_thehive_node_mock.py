"""Wire-level coverage of TheHive's published v1 contract, with no live account.

Request fixtures copy the provider's x-codeSamples. Response objects below use
individual Output* schema examples, not claimed as recorded API traffic.
"""
import json
from pathlib import Path
from contextlib import asynccontextmanager

import httpx
import pytest

from nodes import thehive_node as module
from nodes.thehive_node import TheHiveNode, TheHiveApiKeyCredential, CONFIG_MODELS, OPERATIONS
from nodes.core.poll_trigger import poll_scope

FIXTURES = Path(__file__).parent / 'fixtures' / 'thehive'
CREDENTIAL = {'credential_type': 'thehive_api_key', 'base_url': 'https://thehive.example.com', 'api_key': 'a-realistic-test-key', 'organisation': 'SOC'}


def node(config):
    parsed = TheHiveNode.parse_config({'config': config, 'credentials': CREDENTIAL})
    return TheHiveNode('node', 'automation-thehive', {'config': config}, config=parsed)


@pytest.fixture
def wire(monkeypatch):
    calls, responses = [], []

    def handle(request):
        calls.append(request)
        status, body = responses.pop(0)
        return httpx.Response(status, json=body) if status != 204 else httpx.Response(204)

    @asynccontextmanager
    async def client(**kwargs):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle), **kwargs) as instance:
            yield instance

    monkeypatch.setattr(module, 'guarded_async_client', client)
    return calls, responses


def test_manual_credential_and_url():
    c = TheHiveApiKeyCredential(base_url='thehive.example.com/#/cases', api_key=' example-key ')
    assert c.credential_type == 'thehive_api_key'
    assert c.base_url == 'https://thehive.example.com'
    assert c.api_key == 'example-key'
    assert 'example-key' not in repr(c)
    for patch in [{'base_url': 'http://thehive.example.com'}, {'base_url': 'https://u:p@thehive.example.com'},
                  {'api_key': ''}, {'api_key': 'Bearer key'}, {'api_key': 'https://example.com'}, {'organisation': 'SOC\r\nx-header: value'}]:
        with pytest.raises(ValueError):
            TheHiveApiKeyCredential.model_validate({**CREDENTIAL, **patch})


@pytest.mark.asyncio
@pytest.mark.parametrize('case', json.loads((FIXTURES / 'requests.json').read_text())['operations'])
async def test_documented_requests(case, wire):
    calls, responses = wire
    responses.append((case['status'], case['response']))
    result = await node(case['config']).execute({})
    assert result['data'] == case['response'] if case['status'] != 204 else result['data']['acknowledged']
    request = calls[0]
    assert len(calls) == 1
    assert request.method == case['method']
    assert request.url.path == case['path']
    assert request.headers['Authorization'] == 'Bearer a-realistic-test-key'
    assert request.headers['X-Organisation'] == 'SOC'
    assert json.loads(request.content) == case['body'] if case['body'] is not None else not request.content


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,entity', [('list_cases', 'listCase'), ('list_alerts', 'listAlert'), ('list_tasks', 'listTask'), ('list_observables', 'listObservable')])
async def test_query_pagination_filter_and_sort(operation, entity, wire):
    calls, responses = wire
    responses.append((200, [{'_id': '~123', 'title': 'Case'}]))
    result = await node({'operation': operation, 'offset': 100, 'limit': 1, 'created_since': 1734425224596}).execute({})
    assert result['next_offset'] == 101
    assert json.loads(calls[0].content) == {'query': [
        {'_name': entity}, {'_name': 'filter', '_gte': {'_field': '_createdAt', '_value': 1734425224596}},
        {'_name': 'sort', '_fields': [{'_createdAt': 'desc'}]}, {'_name': 'page', 'from': 100, 'to': 101}]}


@pytest.mark.asyncio
async def test_poll_baseline_new_detection_and_agent_event(wire):
    calls, responses = wire
    item = {'base': {'_id': '~327684328', '_type': 'Audit', '_createdBy': 'alice@example.com',
                    '_createdAt': 1694441999960, 'action': 'update', 'requestId': 'request',
                    'rootId': '~327925760', 'objectId': '~327925760', 'objectType': 'Case',
                    'details': {'status': 'InProgress', 'stage': 'InProgress'}, 'mainAction': True},
            'summary': {'Task': {'create': 2}}}
    n = node({'operation': 'on_new_activity', 'root_id': '~327925760', 'count': 1000})
    state = {}

    async def update(mutator, **kwargs):
        nonlocal state
        changed, result = mutator(state)
        if changed is not None:
            state = changed
        return result

    n._update_node_state = update
    responses.extend([(200, []), (200, [item]), (200, [item])])
    assert (await n.execute({}))['new_count'] == 0
    result = await n.execute({})
    assert result['items'] == [item]
    event = n.resolve_agent_event(result)
    assert all(value in event['text'] for value in ['alice@example.com', 'update', 'InProgress', '~327925760', '~327684328'])
    assert dict(calls[0].url.params) == {'rootId': '~327925760', 'count': '1000'}
    assert n.should_propagate_output(result, {'operation': 'on_new_activity'})
    assert (await n.execute({}))['new_count'] == 0
    assert not n.should_propagate_output({'new_count': 0}, {'operation': 'on_new_activity'})
    assert poll_scope(TheHiveNode, {'operation': 'on_new_activity'}) != poll_scope(TheHiveNode, {'operation': 'on_new_activity', 'root_id': '~327925760'})


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{}, [{'base': {'_id': '~1'}}, {'base': {'_id': '~1'}}], [{'base': {'action': 'update'}}]])
async def test_poll_rejects_invalid_shape_and_ids(body, wire):
    calls, responses = wire
    responses.append((200, body))
    with pytest.raises(ValueError):
        await node({'operation': 'on_new_activity'}).execute({})


@pytest.mark.asyncio
async def test_errors_redirects_and_secrets(wire):
    calls, responses = wire
    for status in [401, 403, 429, 500, 302]:
        responses.append((status, {'message': 'rejected a-realistic-test-key'}))
        with pytest.raises(ValueError, match=f'TheHive API error {status}') as error:
            await node({'operation': 'get_current_user'}).execute({})
        assert CREDENTIAL['api_key'] not in str(error.value)
    assert len(calls) == 5  # writes and reads are never retried implicitly


@pytest.mark.asyncio
async def test_empty_patch_is_refused_before_request(wire):
    calls, _ = wire
    with pytest.raises(ValueError, match='at least one'):
        await node({'operation': 'update_case', 'case_id': '~354'}).execute({})
    assert not calls


@pytest.mark.asyncio
async def test_id_is_one_encoded_path_segment(wire):
    calls, responses = wire
    responses.append((200, {'_id': '~354'}))
    await node({'operation': 'get_case', 'case_id': '~354?x=1/escape'}).execute({})
    assert str(calls[0].url).endswith('/api/v1/case/~354%3Fx%3D1%2Fescape')
    assert not calls[0].url.query


@pytest.mark.asyncio
async def test_recent_activity_uses_documented_query_parameters(wire):
    calls, responses = wire
    responses.append((200, []))
    result = await node({'operation': 'get_activity', 'root_id': '~327925760', 'count': 25}).execute({})
    assert result == {'data': []}
    assert calls[0].method == 'GET'
    assert calls[0].url.path == '/api/v1/flow'
    assert dict(calls[0].url.params) == {'rootId': '~327925760', 'count': '25'}
