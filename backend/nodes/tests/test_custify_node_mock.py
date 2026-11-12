"""Exercise Custify's actual HTTP construction, manual auth and poll lifecycle.

Task and ticket values come from examples in the pinned provider schemas.
"""
import copy
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import custify_node as native
from nodes.core.base import ConfigValidationError
from nodes.core.registry import NodeFactory
from nodes.core.poll_trigger import poll_scope

TOKEN = 'custify-unit-key-42'
FIXTURES = Path(__file__).parent / 'fixtures' / 'custify'


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='custify-unit', node_type='automation-custify',
        node_data={'config': config, 'credentials': {'credential_type': 'custify_api_key', 'api_key': TOKEN}})


def transport(monkeypatch, reply):
    requests = []
    def respond(request):
        requests.append(request)
        return reply(request) if callable(reply) else httpx.Response(200, json=reply)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


def example(name):
    return json.loads((FIXTURES / (name + '.json')).read_text())['body']


def test_custify_manual_credential_defaults_and_origin_guard():
    c = native.CustifyAPIKeyCredential(api_key='  '+TOKEN+'\n')
    assert c.credential_type == 'custify_api_key' and c.api_key == TOKEN
    assert c.api_url == 'https://api.custify.com'
    for host in ['https://evil.test', 'https://api.custify.com.evil.test', 'http://api.custify.com',
                 'https://user@api.custify.com', 'https://api.custify.com/people']:
        with pytest.raises(ValueError):
            native.CustifyAPIKeyCredential(api_key=TOKEN, api_url=host)
    for key in ['Bearer '+TOKEN, 'https://example.com/key', '<token>']:
        with pytest.raises(ValidationError):
            native.CustifyAPIKeyCredential(api_key=key)


def test_custify_task_tags_and_event_dates_match_contract_types():
    with pytest.raises(ConfigValidationError, match='tags'):
        native.CustifyNode.parse_config({'config': {'operation':'create_task','name':'First task',
            'company_id':'20','tags':[{'id':'5d11d5687113bc33f07573f0'}]}})
    with pytest.raises(ConfigValidationError, match='created_at'):
        native.CustifyNode.parse_config({'config': {'operation':'insert_event','name':'login',
            'user_id':'1','created_at':'not-a-date'}})


@pytest.mark.asyncio
async def test_custify_list_tasks_is_connection_evidence(monkeypatch):
    row = example('TaskListing')
    requests = transport(monkeypatch, {'total': 1, 'tasks': [row]})
    result = await node({'operation': 'list_tasks'}).execute({})
    assert result['data'] == [row] and result['total'] == 1
    assert requests[0].method == 'GET' and requests[0].url.path == '/task'
    assert requests[0].headers['Authorization'] == 'Bearer '+TOKEN
    assert dict(requests[0].url.params) == {'page':'1', 'itemsPerPage':'20'}
    assert native.CustifyNode.connection_evidence.operation == 'list_tasks'


@pytest.mark.asyncio
async def test_custify_filters_are_single_encoded_json_parameters(monkeypatch):
    requests = transport(monkeypatch, {})
    sorting = {'field': 'updated_at', 'direction': 'desc'}
    filters = [{'fieldName': 'name', 'fieldType': 'String', 'filterType': 'contains', 'filterValue': 'A & B'}]
    await node({'operation':'list_companies', 'page':3, 'sorting':sorting, 'filters':filters,
                'properties':['name','updated_at'], 'includeSegments':True}).execute({})
    params = requests[0].url.params
    assert json.loads(params['sorting']) == sorting and json.loads(params['filters']) == filters
    assert json.loads(params['properties']) == ['name','updated_at'] and params['includeSegments'] == 'true'
    assert params['page'] == '3'


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,config,path,expected', [
    ('upsert_person', {'user_id':'25', 'name':'John Doe', 'unsubscribed_from_calls':False}, '/people',
     {'user_id':'25','name':'John Doe','unsubscribed_from_calls':False}),
    ('upsert_company', {'company_id':'6','monthly_revenue':0,'churned':False}, '/company',
     {'company_id':'6','monthly_revenue':0,'churned':False}),
    ('create_task', {'company_id':'20','name':'First task','tags':['5d11d5687113bc33f07573f0']}, '/task',
     {'company_id':'20','name':'First task','priority':'medium','status':'open','tags':['5d11d5687113bc33f07573f0']}),
    ('update_task', {'id':'5ea93252e0263c08145d6945','status':'done'}, '/task/5ea93252e0263c08145d6945',
     {'_id':'5ea93252e0263c08145d6945','status':'done'}),
    ('tag_people', {'ids':['5d402cf8c3a4c5578c9be5f4'],'tag':'5d948817c5f9442ea5482321'}, '/people/tag',
     {'ids':['5d402cf8c3a4c5578c9be5f4'],'tag':'5d948817c5f9442ea5482321','type':'add'}),
    ('insert_event', {'name':'login','created_at':'2019-07-01T12:00:00.000Z','user_id':'1'}, '/event',
     {'name':'login','created_at':'2019-07-01T12:00:00Z','user_id':'1'}),
    ('create_ticket', {'externalId':'ab','title':'First ticket','company':'6'}, '/ticket',
     {'externalId':'ab','title':'First ticket','company':'6','ticketStatus':'open'}),
])
async def test_custify_writes_send_documented_fields(monkeypatch, operation, config, path, expected):
    requests = transport(monkeypatch, {})
    await node({'operation':operation, **config}).execute({})
    assert len(requests) == 1 and requests[0].url.path == path
    assert requests[0].method == ('PUT' if operation == 'update_task' else 'POST')
    assert json.loads(requests[0].content) == expected


@pytest.mark.asyncio
async def test_custify_ids_cannot_change_route_and_errors_redact_key(monkeypatch):
    requests = transport(monkeypatch, {})
    await node({'operation':'get_person','id':'a/b?x=y'}).execute({})
    assert requests[0].url.raw_path == b'/people/a%2Fb%3Fx%3Dy'
    transport(monkeypatch, lambda r: httpx.Response(401, text='Rejected '+TOKEN))
    with pytest.raises(ValueError, match='Rejected') as exc:
        await node({'operation':'list_tasks'}).execute({})
    assert TOKEN not in str(exc.value)


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,fixture,key', [
    ('on_task_updated','TaskListing','tasks'), ('on_new_ticket','TicketListing','tickets'),
])
async def test_custify_poll_pages_dedup_versions_and_agent_event(monkeypatch, operation, fixture, key):
    row = example(fixture)
    second = copy.deepcopy(row); second['id'] = 'another-id'
    requests = transport(monkeypatch, lambda r: httpx.Response(200,
        json={'total':2,key:[row if r.url.params['page'] == '1' else second]}))
    n = node({'operation':operation})
    state = {'seen_ids': []}
    async def update(mutator, **kwargs):
        replacement, result = mutator(state)
        if replacement is not None:
            state.clear(); state.update(replacement)
        return result
    n._update_node_state = update
    result = await n.execute({})
    assert result['new_item_count'] == 2 and len(requests) == 2
    assert requests[1].url.params['page'] == '2'
    if operation == 'on_task_updated':
        assert 'sorting' not in requests[0].url.params and 'sort' not in requests[0].url.params
    else:
        assert requests[0].url.params['sort'] == 'openedAt'
    event = native.CustifyNode.resolve_agent_event(result)
    assert row['id'] in event['text'] and str(row['company']) in event['text']
    assert (await n.execute({}))['new_item_count'] == 0
    if operation == 'on_task_updated':
        row['updated_at'] = '2023-10-02T12:00:00.000Z'
        assert (await n.execute({}))['new_item_count'] == 1
    assert poll_scope(native.CustifyNode, {'operation':operation}) == poll_scope(native.CustifyNode, {'operation':operation,'goal':'Cosmetic'})
    assert poll_scope(native.CustifyNode, {'operation':operation}) is not None


@pytest.mark.asyncio
async def test_custify_first_poll_baselines_then_delivers_new_tasks(monkeypatch):
    row = example('TaskListing')
    transport(monkeypatch, lambda r: httpx.Response(200, json={'total':1,'tasks':[copy.deepcopy(row)]}))
    n = node({'operation':'on_task_updated'})
    state = {}
    async def update(mutator, **kwargs):
        replacement, result = mutator(state)
        if replacement is not None:
            state.clear(); state.update(replacement)
        return result
    n._update_node_state = update
    result = await n.execute({})
    assert result['new_item_count'] == 0 and state['seen_ids']
    assert native.CustifyNode.resolve_agent_event(result) is None
    row['updated_at'] = '2023-10-02T12:00:00.000Z'
    result = await n.execute({})
    assert result['new_item_count'] == 1
    assert native.CustifyNode.should_propagate_output(result, {'operation':'on_task_updated'})


@pytest.mark.asyncio
async def test_custify_incomplete_poll_never_advances_state(monkeypatch):
    calls = 0
    def reply(request):
        nonlocal calls
        calls += 1
        return httpx.Response(200,json={'total':2,'tasks':[example('TaskListing')] if calls == 1 else []})
    transport(monkeypatch, reply)
    n = node({'operation':'on_task_updated'})
    n._filter_unseen = AsyncMock()
    with pytest.raises(ValueError, match='incomplete'):
        await n.execute({})
    n._filter_unseen.assert_not_called()
