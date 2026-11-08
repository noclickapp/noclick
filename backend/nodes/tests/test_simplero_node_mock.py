"""Offline request contract tests; no live Simplero account is used."""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import simplero_node as native
from nodes.core.registry import NodeFactory

TOKEN = 'simplero-offline-fixture-key'
ROUTES = json.loads((Path(__file__).parent / 'fixtures/simplero/routes.json').read_text())


def node(config):
    return NodeFactory.create_node(node_id='simplero-test', node_type='automation-simplero', node_data={
        'config': config, 'credentials': {'credential_type': 'simplero_api_key', 'api_key': TOKEN}})


def transport(monkeypatch, body=None, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body if body is not None else {'data': {'id': 42}})
    original = httpx.AsyncClient
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return original(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native.httpx, 'AsyncClient', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', ROUTES)
async def test_each_operation_has_exactly_one_documented_request(monkeypatch, operation):
    contract = ROUTES[operation]
    cfg = {'operation': operation}
    for field in ['customer_id', 'tag_id', 'list_id', 'product_id', 'purchase_id', 'automation_id', 'subscription_id']:
        if '{'+field+'}' in contract['path']:
            cfg[field] = 42
    if operation in ['create_customer', 'update_customer']:
        cfg.update(email='person@example.com', first_names='Ada', lead_score=0)
    if operation == 'update_tag':
        cfg.update(name='Engaged', description='Contact segment')
    if operation == 'subscribe_contact':
        cfg.update(list_id=7, require_double_opt_in=True, skip_welcome=False, skip_auto_responses=False)
    if operation == 'create_list':
        cfg.update(name='Newsletter', internal_name='Newsletter')
    if operation in ['add_tag', 'remove_tag']:
        cfg['tag_id'] = 7
    if operation in ['start_automation', 'stop_automation']:
        cfg['automation_id'] = 7
    body = {'data': [], 'pagination': {'page': 1, 'per_page': 20, 'total': 0, 'total_pages': 0, 'next_after': None}} if operation.startswith('list_') else {'data': {'success': True}} if '/actions/' in contract['path'] else {'data': {'id': 42}}
    requests = transport(monkeypatch, body)
    result = await node(cfg).execute({})
    assert result['status'] == 'success' and result['data'] == body['data']
    assert len(requests) == 1
    req = requests[0]
    assert req.method == contract['method']
    assert req.url.host == 'simplero.com'
    assert req.url.path == '/api/v2'+contract['path'].format(**cfg)
    assert req.headers['X-API-Key'] == TOKEN
    assert req.headers['User-Agent'] == 'NoClick (support@noclick.com)'
    if req.method != 'GET':
        expected = {k: v for k,v in cfg.items() if k != 'operation' and '{'+k+'}' not in contract['path']}
        assert (json.loads(req.content) if req.content else {}) == expected


@pytest.mark.asyncio
async def test_cursor_and_search_preserve_provider_pagination(monkeypatch):
    body = {'data': [{'id': 42, 'name': 'My list'}], 'pagination': {'page': None, 'next_after': 42, 'total': None}}
    requests = transport(monkeypatch, body)
    result = await node({'operation': 'list_lists', 'after': 20, 'per_page': 5, 'q': 'Paid + members'}).execute({})
    assert dict(requests[0].url.params) == {'after': '20', 'per_page': '5', 'q': 'Paid + members'}
    assert result['pagination'] == body['pagination']


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 401, 403, 422, 429, 500])
async def test_provider_failure_no_retry_and_secret_redaction(monkeypatch, status):
    requests = transport(monkeypatch, {'errors': [TOKEN+' rejected']}, status)
    with pytest.raises(ValueError) as exc:
        await node({'operation':'list_lists'}).execute({})
    assert f'HTTP {status}' in str(exc.value) and TOKEN not in str(exc.value)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{}, {'data': {}}, {'errors': ['Denied']}, {'data': None}, {'data': ['not a record']}])
async def test_bad_list_envelopes_fail(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError):
        await node({'operation':'list_lists'}).execute({})


@pytest.mark.asyncio
async def test_action_failure_is_not_success(monkeypatch):
    transport(monkeypatch, {'data': {'success': False, 'message': 'Contact is not subscribed'}})
    with pytest.raises(ValueError, match='Contact is not subscribed'):
        await node({'operation':'unsubscribe', 'subscription_id':42}).execute({})


@pytest.mark.parametrize('config', [
    {'operation':'list_lists','per_page':101}, {'operation':'list_lists','page':0},
    {'operation':'get_customer','customer_id':'../tags'}, {'operation':'update_customer','customer_id':42},
    {'operation':'create_customer','email':'invalid','lead_score':0},
    {'operation':'create_customer','email':'person@example.com'},
    {'operation':'add_tag','customer_id':42}, {'operation':'unknown'},
])
def test_invalid_inputs_rejected(config):
    with pytest.raises((ValidationError, ValueError)):
        node(config)


def test_schema_discovery_evidence_and_credential():
    assert len(ROUTES) == 24
    assert native.SimpleroNode.connection_evidence.operation == 'list_lists'
    schema = native.SimpleroNode.get_config_schema()
    assert schema['$defs']['SimpleroAPIKeyCredential']['title'] == 'Simplero API Key'
    assert schema['$defs']['SimpleroAPIKeyCredential']['properties']['api_key']['ui:widget'] == 'password'
    with pytest.raises(ValidationError):
        native.SimpleroAPIKeyCredential(api_key=TOKEN, credential_type='another_provider')
