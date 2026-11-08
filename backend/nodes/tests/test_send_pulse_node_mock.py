"""Verify SendPulse serialization, credentials, error handling and pagination."""
import json
from contextlib import asynccontextmanager
import httpx
import pytest
from nodes.send_pulse_node import SendPulseNode, SendPulseAPIKeyCredential
from nodes.core.registry import NodeFactory

KEY = 'sendpulse-realistic-test-key-12345678'

def node(config):
    return NodeFactory.create_node(node_id='send-pulse-test', node_type='automation-send-pulse', node_data={
        'config': config, 'credentials': {'credential_type': 'send_pulse_api_key', 'api_key': KEY}})

def transport(monkeypatch, body, status=200):
    seen=[]
    def respond(request):
        seen.append(request)
        return httpx.Response(status, json=body)
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs['follow_redirects'] is False
        assert kwargs['trust_env'] is False
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as session:
            yield session
    monkeypatch.setattr('nodes.send_pulse_node.guarded_async_client', client)
    return seen

@pytest.mark.asyncio
async def test_send_pulse_add_contacts(monkeypatch):
    seen=transport(monkeypatch, {'result': True})
    result=await node({'operation':'add_contacts','id':42,'emails':[{'email':'user@example.com','variables':{'Name':'Alice'}}]}).execute({})
    assert result['data']=={'result':True}
    request=seen[0]
    assert request.method=='POST' and str(request.url)=='https://api.sendpulse.com/addressbooks/42/emails'
    assert request.headers['Authorization']=='Bearer '+KEY
    assert json.loads(request.content)=={'emails':[{'email':'user@example.com','variables':{'Name':'Alice'}}]}

@pytest.mark.asyncio
async def test_send_pulse_page(monkeypatch):
    seen=transport(monkeypatch, [{'id':42,'name':'Customers'}])
    result=await node({'operation':'list_mailing_lists','limit':1,'offset':4}).execute({})
    assert result['next_offset']==5
    assert dict(seen[0].url.params)=={'limit':'1','offset':'4'}

@pytest.mark.asyncio
async def test_send_pulse_queue(monkeypatch):
    transport(monkeypatch, {'result':True,'queue_id':123})
    result=await node({'operation':'create_tag','name':'VIP','color':'#FF0000'}).execute({})
    assert result['data']['queue_id']==123
    assert 'readback_verified' not in result

@pytest.mark.asyncio
@pytest.mark.parametrize('status,body', [(401,{'message':'Unauthorized'}),(200,{'result':False,'message':'Rejected'}),(200,{'error_code':422,'message':'Invalid'})])
async def test_send_pulse_rejections(monkeypatch,status,body):
    transport(monkeypatch, body,status)
    with pytest.raises(ValueError):
        await node({'operation':'list_mailing_lists'}).execute({})

def test_send_pulse_key_and_evidence():
    assert SendPulseNode.connection_evidence.operation=='list_mailing_lists'
    with pytest.raises(ValueError):
        SendPulseAPIKeyCredential(api_key='Bearer token')

@pytest.mark.asyncio
async def test_send_pulse_documented_inputs(monkeypatch):
    from pathlib import Path
    examples = json.loads((Path(__file__).parent / 'fixtures/send-pulse/documented_examples.json').read_text())
    for operation, example in examples['inputs'].items():
        seen = transport(monkeypatch, {'result': True})
        result = await node(example['config']).execute({})
        assert result['data'] == {'result': True}
        assert json.loads(seen[0].content) == {'emails': example['config']['emails']}

@pytest.mark.asyncio
async def test_send_pulse_redacts_nested_output(monkeypatch):
    transport(monkeypatch, {'nested': [KEY, {'message': 'prefix ' + KEY}]})
    result = await node({'operation': 'get_balance'}).execute({})
    assert result['data'] == {'nested': ['[redacted]', {'message': 'prefix [redacted]'}]}
