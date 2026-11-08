"""Exercise each published route, parameter boundary, auth and response shape."""
import httpx
import pytest
from nodes.beach_day_api_node import BeachDayApiKeyCredential, BeachDayApiNode
from nodes.core.registry import NodeFactory

CASES = [
    ({'operation': 'get_health'}, '/health/', {}, {'status': 'ok', 'service': 'Beach Day API'}),
    ({'operation': 'list_beaches', 'state': 'CA', 'country': 'United States', 'search': 'Malibu', 'offset': 2, 'limit': 5}, '/beaches/', {'state':'CA', 'country':'United States', 'search':'Malibu', 'offset':2,'limit':5}, {'count':0,'results':[]}),
    ({'operation': 'get_beach_detail', 'id': 1}, '/beaches/1/', {}, {'id':1,'name':'Venice Beach','weather':None}),
    ({'operation': 'list_beach_conditions', 'id': 1, 'offset': 3, 'limit': 2}, '/beaches/1/conditions/', {'offset':3,'limit':2}, {'beach_id':1,'count':0,'results':[]}),
    ({'operation': 'get_scored_beaches', 'offset': 4, 'limit': 3}, '/beaches/scored/', {'offset':4,'limit':3}, {'count':0,'results':[]}),
    ({'operation': 'get_beach_rules', 'id': 1}, '/beaches/1/rules/', {}, {'beach_id':1,'rules':[]}),
    ({'operation': 'get_beach_amenities', 'id': 1}, '/beaches/1/amenities/', {}, {'beach_id':1,'amenities':[]}),
    ({'operation': 'get_tide_predictions', 'beach_id': 1}, '/tides/1/', {}, {'beach_id':1,'tide_predictions':[]}),
    ({'operation': 'list_countries'}, '/countries/', {}, {'count':1,'results':[{'country':'United States','beach_count':123}]}),
]

def node(config):
    data = {'config':config,'credentials':{'credential_type':'beach_day_api_key','api_key':'beach-test-secret'}}
    return NodeFactory.create_node(node_id='beach', node_type='automation-beach-day-api', node_data=data)

@pytest.mark.asyncio
@pytest.mark.parametrize('config,path,params,body', CASES)
async def test_routes(monkeypatch, config, path, params, body):
    async def request(self, method, url, **kwargs):
        assert method == 'GET'
        assert url == 'https://beachdayapi.com/v1' + path
        assert kwargs['params'] == params
        if config['operation'] == 'get_health':
            assert 'Authorization' not in kwargs['headers']
        else:
            assert kwargs['headers']['Authorization'] == 'Bearer beach-test-secret'
        return httpx.Response(200, json=body)
    monkeypatch.setattr(httpx.AsyncClient, 'request', request)
    assert await node(config).execute({}) == {'status':'success','data':body}

@pytest.mark.asyncio
@pytest.mark.parametrize('status', [401,402,404,429,500,302])
async def test_provider_failure(monkeypatch, status):
    async def request(*args, **kwargs):
        return httpx.Response(status, json={'detail':'Rejected beach-test-secret'})
    monkeypatch.setattr(httpx.AsyncClient, 'request', request)
    result = await node({'operation':'list_countries'}).execute({})
    assert result == {'status':'error','http_status':status,'error':'Rejected [redacted]'}

@pytest.mark.asyncio
@pytest.mark.parametrize('body', [[],None,{'error':'failed'},{'detail':'failed'}])
async def test_error_envelopes_are_not_success(monkeypatch, body):
    async def request(*args, **kwargs): return httpx.Response(200,json=body)
    monkeypatch.setattr(httpx.AsyncClient,'request',request)
    with pytest.raises(ValueError): await node({'operation':'list_countries'}).execute({})

@pytest.mark.parametrize('config', [
    {'operation':'get_beach_detail','id':'../countries'},
    {'operation':'get_tide_predictions','beach_id':0},
    {'operation':'list_beaches','limit':501},
    {'operation':'get_scored_beaches','limit':201},
    {'operation':'list_beach_conditions','id':1,'limit':201},
    {'operation':'list_beaches','offset':-1},
])
def test_invalid_config(config):
    assert not BeachDayApiNode.validate_config({'config':config})['valid']


def test_hand_connect_and_evidence():
    assert BeachDayApiKeyCredential(api_key='beach-test-secret').credential_type == 'beach_day_api_key'
    assert BeachDayApiNode.connection_evidence.proves == 'reachability'
    assert BeachDayApiNode.connection_evidence.operation == 'list_countries'
