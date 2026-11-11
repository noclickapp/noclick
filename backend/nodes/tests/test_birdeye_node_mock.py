"""Exercise every Birdeye operation through the native operation runner.

Independent wire expectations pin methods, route casing, API-key placement and
bodies; provider examples protect parsing and error propagation.
"""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import birdeye_node as mod
from nodes.core.run_op import run_node_operation

CASES = json.loads((Path(__file__).parent / 'fixtures/birdeye/operations.json').read_text())
AUTH = {'credential_type': 'birdeye_api_key', 'api_key': 'fixture-birdeye-key', 'business_id': '12345678'}


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    async def send(request):
        requests.append(request)
        status, payload = replies.pop(0)
        return httpx.Response(status, json=payload)
    client = httpx.AsyncClient
    monkeypatch.setattr(mod.httpx, 'AsyncClient', lambda **kw: client(**kw, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(operation, config=None, credential=AUTH):
    return await run_node_operation(node_type='automation-birdeye', operation=operation,
        arguments=config or {}, credential_data=credential, user_id='00000000-0000-4000-8000-000000000001')


@pytest.mark.asyncio
@pytest.mark.parametrize('case', CASES, ids=lambda c: c['operation'])
async def test_birdeye_published_requests(transport, case):
    requests, replies = transport
    replies.append((200, case['response']))
    result = await run(case['operation'], case['config'])
    assert result['data'] == case['response']
    assert len(requests) == 1
    request = requests[0]
    assert request.url.host == 'api.birdeye.com'
    assert request.url.path == '/resources' + case['path']
    assert request.method == case['method']
    assert dict(request.url.params) == case['params']
    assert request.headers['x-api-key'] == AUTH['api_key']
    assert AUTH['api_key'] not in str(request.url)
    assert (json.loads(request.content) if request.content else None) == case['body']


@pytest.mark.asyncio
async def test_birdeye_business_override(transport):
    requests, replies = transport
    replies.append((200, {'name': 'Other Business'}))
    await run('get_business', {'business_id': '987654321'})
    assert requests[0].url.path.endswith('/business/987654321')


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [400, 401, 403, 404, 429, 500, 302])
async def test_birdeye_rejection_never_becomes_success(transport, status):
    requests, replies = transport
    replies.append((status, {'code': 1161, 'message': 'Invalid API key'}))
    with pytest.raises(Exception, match='Invalid API key'):
        await run('get_business')
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_birdeye_error_envelope_and_secret_redaction(transport):
    _, replies = transport
    replies.append((200, {'code': 1161, 'message': 'Invalid ' + AUTH['api_key']}))
    with pytest.raises(Exception) as exc:
        await run('get_business')
    assert AUTH['api_key'] not in str(exc.value)
    assert '[redacted]' in str(exc.value)


def test_birdeye_manual_credential_and_path_validation():
    assert mod.BirdeyeAPIKeyCredential(api_key='fixture-birdeye-key', business_id='12345678').credential_type == 'birdeye_api_key'
    for value in ['../admin', '123/456', 'https://example.com', '?key=oops']:
        with pytest.raises(ValidationError):
            mod.GetBusinessConfig(business_id=value)
    with pytest.raises(ValidationError):
        mod.ListReviewsConfig(sindex=99999, count=2)
    with pytest.raises(ValidationError):
        mod.DeleteContactConfig(id="115339282")


@pytest.mark.asyncio
async def test_birdeye_connection_evidence_names_the_business(transport):
    from nodes.core.connection_evidence import collect_evidence
    requests, replies = transport
    replies.append((200, {'businessId': 12345678, 'name': 'Fixture Business'}))
    evidence = await collect_evidence(node_type='automation-birdeye', credential_data=AUTH,
        user_id='00000000-0000-4000-8000-000000000001')
    assert evidence.reachable is True
    assert evidence.account_label == 'Fixture Business'
    assert len(requests) == 1 and requests[0].method == 'GET'


def test_birdeye_contact_writes_require_explicit_locations():
    with pytest.raises(ValidationError):
        mod.UpsertContactConfig(email="michael@test.com")
    with pytest.raises(ValidationError):
        mod.DeleteContactConfig(id="115339282", businessIds=[])


def poll_node(operation, **values):
    node = mod.BirdeyeNode(node_id='birdeye-poll', node_type='automation-birdeye',
        node_data={}, config=mod.BirdeyeNodeConfig(config={'operation': operation, **values}, credentials=AUTH),
        sio=None, sid=None, workflow_id='workflow', user_id='user')
    node.emit = AsyncMock()
    return node


def memory_state(node):
    state = {}
    async def update(mutator, **kwargs):
        new_state, result = mutator(dict(state))
        if new_state is not None:
            state.clear()
            state.update(new_state)
        return result
    node._update_node_state = update
    return state


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,list_operation,id_field,change_field', [
    ('on_new_or_updated_review', 'list_reviews', 'reviewId', 'comments'),
    ('on_new_or_updated_contact', 'list_contacts', 'customerId', 'name'),
])
async def test_birdeye_poll_baselines_deduplicates_and_delivers_changes(
        transport, operation, list_operation, id_field, change_field):
    from copy import deepcopy
    requests, replies = transport
    node = poll_node(operation)
    state = memory_state(node)
    published = deepcopy(next(case['response'] for case in CASES if case['operation'] == list_operation))
    if list_operation == 'list_contacts':
        # Retain the two documented contact examples, presented as one page.
        published.update(totalPages=1, totalCount=2, size=100)
    replies.append((200, deepcopy(published)))
    first = await node.execute({})
    assert first['data'] == []
    assert not node.should_propagate_output(first, {'operation': operation})
    assert node.resolve_agent_event(first) is None
    replies.append((200, deepcopy(published)))
    assert (await node.execute({}))['event_count'] == 0
    items = published if isinstance(published, list) else published['customers']
    items[0][change_field] = 'Changed provider content'
    new_item = deepcopy(items[1])
    new_item[id_field] = '999999'
    items.append(new_item)
    replies.append((200, deepcopy(published)))
    changed = await node.execute({})
    assert changed['data'] == [items[0], new_item]
    assert node.trigger_emitted_event(changed)
    event = node.resolve_agent_event(changed)['text']
    assert '12345678' in event and '999999' in event and 'Changed provider content' in event
    assert node.should_propagate_output(changed, {'operation': operation})
    assert all(req.headers['x-api-key'] == AUTH['api_key'] for req in requests)
    # A re-armed baseline cannot consume updates; reverting to a previously
    # seen value is another update, rather than an eternally seen revision.
    items[0][change_field] = 'A later update'
    node._poll_baseline_only = True
    replies.append((200, deepcopy(published)))
    assert (await node.execute({}))['event_count'] == 0
    node._poll_baseline_only = False
    replies.append((200, deepcopy(published)))
    assert (await node.execute({}))['event_count'] == 1
    items[0][change_field] = 'Changed provider content'
    replies.append((200, deepcopy(published)))
    assert (await node.execute({}))['data'] == [items[0]]
    old_scope = state['scope']
    node._config = mod.BirdeyeNodeConfig(config={'operation': operation, 'business_id': '987654321'}, credentials=AUTH)
    replies.append((200, deepcopy(published)))
    assert (await node.execute({}))['event_count'] == 0
    assert state['scope'] != old_scope


@pytest.mark.asyncio
async def test_birdeye_review_poll_paginates_and_uses_update_filter(transport):
    from copy import deepcopy
    requests, replies = transport
    review = next(case['response'] for case in CASES if case['operation'] == 'list_reviews')[0]
    page = [dict(deepcopy(review), reviewId=str(1000+i)) for i in range(100)]
    replies.extend([(200, page), (200, [dict(deepcopy(review), reviewId='2000')])])
    node = poll_node('on_new_or_updated_review', update_from_date='04/01/2013', business_id='987654321')
    state = memory_state(node)
    state['seen_ids'] = []
    result = await node.execute({})
    assert result['event_count'] == 101
    assert [dict(req.url.params) for req in requests] == [
        {'sindex': '0', 'count': '100'}, {'sindex': '100', 'count': '100'}]
    assert all(req.url.path.endswith('/businessId/987654321') for req in requests)
    assert all(json.loads(req.content) == {'statuses': ['all'], 'updateFromDate': '04/01/2013'} for req in requests)


@pytest.mark.asyncio
async def test_birdeye_contact_poll_paginates_and_uses_declared_scope(transport):
    requests, replies = transport
    published = next(case['response'] for case in CASES if case['operation'] == 'list_contacts')
    replies.extend([(200, dict(published, totalPages=2)), (200, dict(published, totalPages=2, customers=[]))])
    node = poll_node('on_new_or_updated_contact', start_date='07/01/2019')
    memory_state(node)
    await node.execute({})
    assert [dict(req.url.params) for req in requests] == [
        {'businessId': '12345678', 'page': '0', 'size': '100', 'sortby': 'lastActivityOn'},
        {'businessId': '12345678', 'page': '1', 'size': '100', 'sortby': 'lastActivityOn'}]
    assert all(json.loads(req.content) == {'startDate': '07/01/2019'} for req in requests)


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,payload', [
    ('on_new_or_updated_review', {'unexpected': []}),
    ('on_new_or_updated_review', [{'comments': 'missing ID'}]),
    ('on_new_or_updated_contact', {'customers': [{}], 'totalPages': 1}),
])
async def test_birdeye_bad_poll_does_not_advance_state(transport, operation, payload):
    _, replies = transport
    replies.append((200, payload))
    node = poll_node(operation)
    state = memory_state(node)
    with pytest.raises(ValueError, match='Birdeye'):
        await node.execute({})
    assert state == {}


@pytest.mark.asyncio
async def test_birdeye_poll_limit_does_not_save_partial_baseline():
    node = poll_node('on_new_or_updated_contact')
    state = memory_state(node)
    node._request = AsyncMock(return_value={'customers': [{'customerId': 12345}], 'totalPages': 101})
    with pytest.raises(ValueError, match='10,000'):
        await node.execute({})
    assert state == {}
    assert node._request.await_count == 100
