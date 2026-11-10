import base64
import hashlib
import hmac
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from nodes.codat_node import CodatNode, CodatAPIKeyCredential, OPERATIONS
from nodes.core.registry import NodeFactory

FIXTURES = Path(__file__).parent / 'fixtures' / 'codat'
SPEC = json.loads((FIXTURES / 'contract.json').read_text())
CREDENTIAL = {'credential_type': 'codat_api_key', 'api_key': 'codat-test-secret', 'company_id': '8a210b68-6988-11ed-a1eb-0242ac120002'}

def deref(value):
    while '$ref' in value:
        target = SPEC
        for part in value['$ref'][2:].split('/'):
            target = target[part]
        value = target
    return value

@pytest.mark.asyncio
@pytest.mark.parametrize('operation', OPERATIONS)
async def test_codat_every_operation_maps_to_pinned_contract(operation, monkeypatch):
    route = OPERATIONS[operation]
    endpoint = SPEC['paths'][route['path']][route['method'].lower()]
    assert endpoint['operationId'].replace('-', '_') == operation
    config = {'operation': operation}
    for parameter in SPEC['paths'][route['path']].get('parameters', []) + endpoint.get('parameters', []):
        parameter = deref(parameter)
        schema = deref(parameter['schema'])
        if not parameter.get('required'):
            continue
        config[parameter['name']] = schema.get('example', schema.get('enum', [None])[0]) or (1 if schema.get('type') == 'integer' else 'sample')
    request = AsyncMock(return_value={'documented': True})
    monkeypatch.setattr(CodatNode, '_request', request)
    node = NodeFactory.create_node(node_id='test', node_type='automation-codat', node_data={'config': config, 'credentials': CREDENTIAL})
    assert (await node.execute({}))['data'] == {'documented': True}
    args, kwargs = request.call_args
    assert args[1] == route['method']
    expected = route['path']
    for key, value in config.items():
        expected = expected.replace('{'+key+'}', str(value))
    assert args[2] == expected
    assert set(kwargs['params']) <= set(route['query'])
    assert all(kwargs['params'][key] == value for key, value in config.items() if key in route['query'])

@pytest.mark.asyncio
async def test_codat_raw_key_encoding_no_basic_password(monkeypatch):
    seen = []
    async def handle(request):
        seen.append(request)
        return httpx.Response(200, json={'status': 'Done'})
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(handle), **kw))
    await CodatNode._request(CREDENTIAL['api_key'], 'GET', '/data/companies/test/assess/excel')
    assert seen[0].headers['authorization'] == 'Basic ' + base64.b64encode(CREDENTIAL['api_key'].encode()).decode()

@pytest.mark.asyncio
async def test_codat_registration_and_cleanup(monkeypatch):
    identifier = '12571faf-0898-47e7-afdd-0fe9eb0a9bf5'
    request = AsyncMock(return_value={'id': identifier})
    monkeypatch.setattr(CodatNode, '_request', request)
    result = await CodatNode._register_external_webhook(webhook_url='https://example.com/hook', credential=CREDENTIAL, config={'operation': 'on_read_completed'}, node_id='test')
    assert result == {'external_webhook_id': identifier}
    assert request.call_args.kwargs['body'] == {'url': 'https://example.com/hook', 'eventTypes': ['read.completed'], 'disabled': False}
    await CodatNode._unregister_external_webhook(credential=CREDENTIAL, config=result, node_id='test')
    assert request.call_args.args[1:] == ('DELETE', '/webhooks/' + identifier)

@pytest.mark.parametrize('event', json.loads((FIXTURES / 'events.json').read_text()).values())
def test_codat_documented_event_and_signature(event):
    body = json.dumps(event['body']).encode()
    timestamp = str(int(time.time()))
    key = b'local-unit-test-signing-key'
    headers = {'webhook-id': 'msg-test', 'webhook-timestamp': timestamp}
    signature = base64.b64encode(hmac.new(key, b'msg-test.' + timestamp.encode() + b'.' + body, hashlib.sha256).digest()).decode()
    headers['webhook-signature'] = 'v1,' + signature
    config = {'signing_secret': 'whsec_' + base64.b64encode(key).decode()}
    assert CodatNode.verify_webhook_signature(body, headers, config)
    assert not CodatNode.verify_webhook_signature(body + b'x', headers, config)
    assert not CodatNode.verify_webhook_signature(body, headers, {})
    headers['webhook-timestamp'] = '1'
    assert not CodatNode.verify_webhook_signature(body, headers, config)
    message = CodatNode.resolve_agent_event(event['body'])
    assert 'Toft stores' in message['text']
    assert event['body']['payload']['referenceCompany']['id'] in message['text']

def test_codat_manual_credential_has_default_type():
    credential = CodatAPIKeyCredential.model_validate({k: v for k, v in CREDENTIAL.items() if k != 'credential_type'})
    assert credential.credential_type == 'codat_api_key'
