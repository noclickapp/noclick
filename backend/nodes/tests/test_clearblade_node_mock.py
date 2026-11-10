"""Published-contract request mapping and scheduled collection change detection."""
import json
from contextlib import asynccontextmanager
import httpx
import pytest
from nodes import clearblade_node as native
from nodes.core.registry import NodeFactory

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='clearblade-test', node_type='automation-clearblade', node_data={'config': config, 'credentials': {'credential_type': 'clearblade_user_token', 'user_token': 'test-user-token', 'system_key': 'system'}})


def transport(monkeypatch, body):
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(200, json=body)
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs['follow_redirects'] is False
        assert kwargs['trust_env'] is False
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as c:
            yield c
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize('config,method,path,body', [
    ({'operation':'list_collections'}, 'GET', '/api/v/3/allcollections/system', None),
    ({'operation':'create_rows','collection_name':'sensors','rows':[{'item_id':'6e0227d8-8a98-454a-951d-a109f813a397'}]}, 'POST', '/api/v/1/collection/system/sensors', [{'item_id':'6e0227d8-8a98-454a-951d-a109f813a397'}]),
    ({'operation':'update_rows','collection_name':'sensors','query':{'FILTERS':[[{'EQ':{'item_id':'row'}}]]},'values':{'state':'On'}}, 'PUT', '/api/v/1/collection/system/sensors', {'query':{'FILTERS':[[{'EQ':{'item_id':'row'}}]]},'$set':{'state':'On'}}),
    ({'operation':'publish_message','topic':'/sensor/111111','payload':'{"temperature":43}'}, 'POST', '/api/v/1/message/system/publish', {'topic':'/sensor/111111','body':'{"temperature":43}'}),
    ({'operation':'execute_service','service_name':'sensor','parameters':{'value':1}}, 'POST', '/api/v/1/code/system/sensor', {'value':1}),
    ({'operation':'update_device','name':'sensor','state':'On'}, 'PUT', '/api/v/2/devices/system/sensor', {'state':'On'}),
])
async def test_requests(monkeypatch, config, method, path, body):
    calls = transport(monkeypatch, {})
    await node(config).execute({})
    req = calls[0]
    assert (req.method, req.url.path) == (method, path)
    assert req.headers['ClearBlade-UserToken'] == 'test-user-token'
    assert (json.loads(req.content) if req.content else None) == body


@pytest.mark.asyncio
async def test_poll_documented_rows_and_repeat(monkeypatch):
    # dataArray example from the pinned contract; no invented row identity fields.
    calls = transport(monkeypatch, {'DATA':[{'row1':'row1_data','row2':'row2_data'}]})
    n = node({'operation':'on_new_or_updated_rows','collection_name':'sales_records','time_column':'order_date'})
    state = {'seen_ids':[]}
    async def update(mutator, **kwargs):
        updated, result = mutator(dict(state))
        if updated is not None:
            state.update(updated)
        return result
    n._update_node_state = update
    first = await n.execute({})
    assert len(first['rows']) == 1
    assert 'sales_records' in n.resolve_agent_event(first)['text']
    assert not (await n.execute({}))['rows']
    query = json.loads(calls[0].url.params['query'])
    assert query['SORT'] == [{'DESC':'order_date'}]


def test_manual_credential_default():
    c = native.ClearBladeCredential(user_token='token', system_key='system')
    assert c.credential_type == 'clearblade_user_token'
