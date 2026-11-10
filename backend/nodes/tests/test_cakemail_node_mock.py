"""HTTP-boundary and documented delivery tests for Cakemail."""
import hashlib
import hmac
import json
from pathlib import Path
from unittest.mock import AsyncMock
import httpx
import pytest
from nodes.cakemail_node import CakemailNode, CakemailTokenCredential, OPERATIONS

TOKEN = 'ck_pat_' + 'a' * 40
EVENTS = json.loads((Path(__file__).parent / 'fixtures/cakemail/events.json').read_text())['events']

@pytest.mark.parametrize('event', EVENTS)
def test_documented_deliveries(event):
    body = json.dumps(event).encode()
    signature = hmac.new(b'secret', body, hashlib.sha256).hexdigest()
    assert CakemailNode.verify_webhook_signature(body, {'X-Signature': signature}, {'signing_secret': 'secret'})
    assert not CakemailNode.verify_webhook_signature(body + b' ', {'x-signature': signature}, {'signing_secret': 'secret'})
    assert not CakemailNode.verify_webhook_signature(body, {}, {'signing_secret': 'secret'})
    turn = CakemailNode.resolve_agent_event(event)
    assert event['event'] in turn['text']
    assert '1234' in turn['text']

@pytest.mark.asyncio
async def test_registration_and_archive(monkeypatch):
    request = AsyncMock(side_effect=[{'id': 'abc'}, {'signature': {'key': 'secret', 'hash_function': 'sha256'}}, {}])
    monkeypatch.setattr(CakemailNode, '_request', request)
    saved = await CakemailNode._register_external_webhook(webhook_url='https://hooks.example.com/event', credential={'api_token': TOKEN}, config={'event_type': 'Email.Bounced'}, node_id='n')
    assert saved == {'external_webhook_id': 'abc', 'signing_secret': 'secret'}
    assert request.call_args_list[0].kwargs['body'] == {'event': 'Email.Bounced', 'url': 'https://hooks.example.com/event'}
    await CakemailNode._unregister_external_webhook(credential={'api_token': TOKEN}, config=saved, node_id='n')
    assert request.call_args.args[1:] == ('POST', '/webhooks/abc/archive')

@pytest.mark.asyncio
@pytest.mark.parametrize('name', OPERATIONS)
async def test_operation_dispatch(name, monkeypatch):
    method, route, query, fields = OPERATIONS[name]
    config = {'operation': name, **{k: 'test' for k in fields}}
    for key in ['list_id', 'contact_id', 'campaign_id', 'template_id']:
        if '{'+key+'}' in route: config[key] = 42
    node = CakemailNode.__new__(CakemailNode)
    node._config = CakemailNode.parse_config({'config': config, 'credentials': {'api_token': TOKEN}})
    node.emit = AsyncMock()
    request = AsyncMock(return_value={'data': [], 'pagination': {}})
    monkeypatch.setattr(CakemailNode, '_request', request)
    result = await node.execute({})
    assert result['status'] == 'success'
    assert request.call_args.args[1] == method
    assert '{' not in request.call_args.args[2]
    if name == 'create_contact': assert request.call_args.kwargs['params']['resubscribe'] is False

def test_manual_credential_default_and_validation():
    assert CakemailTokenCredential(api_token=TOKEN).credential_type == 'cakemail_token'
    with pytest.raises(ValueError): CakemailTokenCredential(api_token='https://wrong.example/token')

@pytest.mark.asyncio
async def test_rejection_keeps_provider_message_and_redacts_token(respx_mock):
    route = respx_mock.get('https://api.cakemail.dev/accounts/self').mock(return_value=httpx.Response(401, json={'detail': [{'msg': 'Token rejected: ' + TOKEN}]}))
    with pytest.raises(ValueError) as error:
        await CakemailNode._request(TOKEN, 'GET', '/accounts/self')
    assert 'Token rejected' in str(error.value)
    assert TOKEN not in str(error.value)
    assert route.calls[0].request.headers['Authorization'] == 'Bearer ' + TOKEN
