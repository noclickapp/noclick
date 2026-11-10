"""HTTP-boundary tests against examples in Appwrite's published 2.3.0 contract."""
import base64
import copy
import hashlib
import hmac
import json
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest

from nodes.appwrite_node import AppwriteAPIKeyCredential, AppwriteNode, AppwriteNodeConfig
from nodes.appwrite_operations import OPERATIONS, TRIGGERS

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/appwrite/responses.json').read_text())
CREDENTIAL = {'credential_type': 'appwrite_api_key', 'api_key': 'test-appwrite-key',
              'project_id': '5e5ea5c15117e', 'endpoint': 'https://fra.cloud.appwrite.io/v1'}


def make_node(config):
    return AppwriteNode(node_id='appwrite-test', node_type='automation-appwrite',
        node_data={'config': config}, config=AppwriteNodeConfig.model_validate(
            {'config': config, 'credentials': CREDENTIAL}), sio=Mock())


@pytest.fixture
def capture(monkeypatch):
    import nodes.appwrite_node as module
    state = {'requests': [], 'status': 200, 'body': {}}
    def handle(request):
        state['requests'].append(request)
        return httpx.Response(state['status'], json=state['body']) if state['status'] != 204 else httpx.Response(204)
    monkeypatch.setattr(module, 'guarded_async_client', lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(handle)))
    return state


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', list(OPERATIONS))
async def test_operations_reach_published_route(operation, capture):
    spec = OPERATIONS[operation]
    config = {'operation': operation}
    for field, (wire, location, kind, required, _) in spec['fields'].items():
        if required:
            config[field] = '{}' if kind == 'object' else '[]' if kind == 'array' else '5e5ea5c15117e'
    capture.update(status=spec['success'][0], body=FIXTURE['responses'].get(operation, {}))
    result = await make_node(config).execute({})
    request = capture['requests'][0]
    assert request.method == spec['method']
    expected_path = spec['path']
    for field, (wire, location, *_) in spec['fields'].items():
        if location == 'path':
            expected_path = expected_path.replace('{'+wire+'}', config[field])
    assert request.url.path == '/v1' + expected_path
    assert request.headers['X-Appwrite-Project'] == CREDENTIAL['project_id']
    assert request.headers['X-Appwrite-Key'] == CREDENTIAL['api_key']
    assert result['status'] == 'success'
    if operation in {'list_users', 'get_user', 'create_user'}:
        assert '"password"' not in json.dumps(result)


@pytest.mark.asyncio
async def test_row_json_and_query_encoding(capture):
    capture.update(status=201, body=FIXTURE['responses']['create_row'])
    await make_node({'operation':'create_row', 'database_id':'db', 'table_id':'table',
                     'row_id':'unique()', 'data':'{"name":"Ada"}', 'permissions':'["read(\\"any\\")"]'}).execute({})
    assert json.loads(capture['requests'][-1].content) == {'rowId':'unique()', 'data':{'name':'Ada'}, 'permissions':['read("any")']}
    capture.update(status=200, body=FIXTURE['responses']['list_rows'])
    query = '{"method":"orderDesc","attribute":"$createdAt"}'
    await make_node({'operation':'list_rows', 'database_id':'db', 'table_id':'table', 'queries':json.dumps([query])}).execute({})
    assert capture['requests'][-1].url.params.get_list('queries[]') == [query]


@pytest.mark.asyncio
async def test_execution_wire_names(capture):
    capture.update(status=201, body=FIXTURE['responses']['create_execution'])
    await make_node({'operation':'create_execution', 'function_id':'function', 'async_execution':True,
                     'body':'hello', 'headers':'{"X-Test":"yes"}', 'method':'POST', 'path':'/'}).execute({})
    assert json.loads(capture['requests'][-1].content) == {'async':True,'body':'hello','headers':{'X-Test':'yes'},'method':'POST','path':'/'}


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', list(TRIGGERS))
async def test_webhook_lifecycle(operation, capture):
    capture.update(status=201, body=FIXTURE['webhook'])
    state = await AppwriteNode._register_external_webhook(webhook_url='https://hooks.example.com/event',
        credential=CREDENTIAL, config={'operation':operation}, node_id='node')
    body = json.loads(capture['requests'][0].content)
    assert body == {'webhookId':'unique()', 'url':'https://hooks.example.com/event', 'name':'NoClick node',
                    'events':[TRIGGERS[operation]], 'enabled':True, 'tls':True}
    assert state['signing_secret'] == FIXTURE['webhook']['secret']
    capture.update(status=204)
    await AppwriteNode._unregister_external_webhook(credential=CREDENTIAL, config=state, node_id='node')
    assert capture['requests'][-1].method == 'DELETE'
    assert capture['requests'][-1].url.path == '/v1/webhooks/' + FIXTURE['webhook']['$id']


def test_signature_binds_raw_body_url_and_secret():
    body = b'{"name":"Ada"}'
    config = {'webhook_url':'https://hooks.example.com/event','signing_secret':'test-secret'}
    signature = base64.b64encode(hmac.new(b'test-secret',config['webhook_url'].encode()+body,hashlib.sha1).digest()).decode()
    headers = {'X-Appwrite-Webhook-Signature':signature}
    assert AppwriteNode.verify_webhook_signature(body, headers, config)
    assert not AppwriteNode.verify_webhook_signature(body+b' ', headers, config)
    assert not AppwriteNode.verify_webhook_signature(body, headers, {**config,'webhook_url':'https://other.example.com'})
    assert not AppwriteNode.verify_webhook_signature(body, headers, {**config,'signing_secret':'other'})
    assert not AppwriteNode.verify_webhook_signature(body, {}, config)


@pytest.mark.parametrize('operation', list(TRIGGERS))
def test_documented_events_reach_agent(operation):
    resource = 'create_row' if 'row' in operation else 'get_user' if 'user' in operation else 'get_file'
    payload = copy.deepcopy(FIXTURE['responses'][resource])
    if operation == 'on_file_uploaded':
        payload['chunksUploaded'] = payload['chunksTotal']
    payload['_webhook'] = {'headers': {'X-Appwrite-Webhook-Events':TRIGGERS[operation],
        'X-Appwrite-Webhook-User-Id':'actor', 'X-Appwrite-Webhook-Project-Id':'project'}}
    output = AppwriteNode.resolve_trigger_payload(payload, {'operation':operation})
    event = AppwriteNode.resolve_agent_event(output)
    assert payload['$id'] in event['text']
    assert 'actor' in event['text'] and 'project' in event['text']
    assert '"password"' not in event['text'] and '_webhook' not in event['text']
    assert not AppwriteNode.filter_trigger_payload(payload, {'operation':next(k for k in TRIGGERS if k != operation)})


def test_partial_upload_does_not_fire():
    payload = {'chunksTotal':2,'chunksUploaded':1,'_webhook':{'headers':{'x-appwrite-webhook-events':'buckets.b.files.f.create'}}}
    assert not AppwriteNode.filter_trigger_payload(payload, {'operation':'on_file_uploaded'})


@pytest.mark.asyncio
async def test_invalid_json_fails_before_http(capture):
    with pytest.raises(ValueError, match='JSON'):
        await make_node({'operation':'create_row','database_id':'db','table_id':'table','row_id':'row','data':'[]'}).execute({})
    assert not capture['requests']


@pytest.mark.asyncio
async def test_provider_rejection_preserved_without_secret(capture):
    capture.update(status=401, body={'message':'Invalid key '+CREDENTIAL['api_key']})
    with pytest.raises(ValueError, match='Invalid key') as exc:
        await make_node({'operation':'list_databases'}).execute({})
    assert CREDENTIAL['api_key'] not in str(exc.value)


@pytest.mark.parametrize('endpoint', ['http://cloud.appwrite.io/v1','https://user:pass@cloud.appwrite.io/v1','https://cloud.appwrite.io/v1?key=x','https://cloud.appwrite.io/console'])
def test_endpoint_validation(endpoint):
    with pytest.raises(ValueError):
        AppwriteAPIKeyCredential.model_validate({**CREDENTIAL,'endpoint':endpoint})


def test_manual_credential_discriminator_defaults():
    credential = AppwriteAPIKeyCredential.model_validate({'project_id':'project','api_key':'valid-key'})
    assert credential.credential_type == 'appwrite_api_key'
