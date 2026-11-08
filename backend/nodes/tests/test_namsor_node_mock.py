"""No live account: native factory requests against pinned contract routes."""
import json
import re
from pathlib import Path
from urllib.parse import unquote
import httpx
import pytest
from pydantic import ValidationError
from nodes import namsor_node as native
from nodes.core.registry import NodeFactory

TOKEN = 'synthetic-namsor-test-key-42'
CONTRACT = json.loads((Path(__file__).parent / 'fixtures/namsor/contract.json').read_text())

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield

def node(config):
    return NodeFactory.create_node(node_id='namsor-fixture', node_type='automation-namsor', node_data={
        'config': config, 'credentials': {'credential_type': 'namsor_api_key', 'api_key': TOKEN}})

def transport(monkeypatch, body=None, status=200, text=None):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, text=text) if text is not None else httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs['trust_env'] is False and kwargs['follow_redirects'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests

def sample(operation):
    route = CONTRACT['operations'][operation]
    config = {'operation': operation}
    for field in re.findall(r'\{(\w+)\}', route['path']):
        if field == 'source': continue
        config[field] = False if field in {'learnable', 'anonymized'} else 'US' if field == 'countryIso2' else '王 / + Café'
    if route['method'] == 'POST':
        item = {'id': 'row-1', 'name': 'John Smith'}
        if operation == 'classify_gender_batch': item = {'id': 'row-1', 'firstName': 'John', 'lastName': 'Smith'}
        if operation == 'parse_names_geo_batch': item['countryIso2'] = 'US'
        config['personalNames'] = [item]
    return config

@pytest.mark.asyncio
@pytest.mark.parametrize('operation', list(CONTRACT['operations']))
async def test_all_operations_one_exact_provider_request(monkeypatch, operation):
    config = sample(operation)
    requests = transport(monkeypatch, {'userId': 'account-42', 'apiKey': TOKEN, 'personalNames': [{'id': 'row-1'}]})
    result = await node(config).execute({})
    assert result['status'] == 'success' and TOKEN not in str(result)
    assert result['data']['userId'] == 'account-42' and result['data']['apiKey'] == '[redacted]'
    assert len(requests) == 1
    request = requests[0]; route = CONTRACT['operations'][operation]
    assert request.method == route['method'] and request.url.host == 'v2.namsor.com'
    assert request.headers['X-API-KEY'] == TOKEN
    expected = route['path']
    for field in re.findall(r'\{(\w+)\}', expected):
        value = TOKEN if field == 'source' else config[field]
        value = str(value).lower() if isinstance(value, bool) else value
        expected = expected.replace('{'+field+'}', value)
    assert unquote(request.url.raw_path.decode()) == '/NamSorAPIv2' + expected
    assert not request.url.query
    if request.method == 'POST': assert json.loads(request.content) == {'personalNames': config['personalNames']}
    else: assert request.content == b''

@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 302, 400, 401, 403, 429, 500])
async def test_provider_rejection_preserved_without_key(monkeypatch, status):
    requests = transport(monkeypatch, {'error': 'Rejected ' + TOKEN}, status)
    result = await node({'operation': 'get_api_key_info'}).execute({})
    assert result['status'] == 'error' and result['http_status'] == status
    assert TOKEN not in str(result) and len(requests) == 1

@pytest.mark.asyncio
async def test_evidence_requires_account_identity_and_redacts_other_keys(monkeypatch):
    transport(monkeypatch, {'apiKey': 'some-other-secret'})
    with pytest.raises(ValueError, match='identity'): await node({'operation': 'get_api_key_info'}).execute({})
    transport(monkeypatch, {'userId': 'user', 'apiKey': 'some-other-secret'})
    assert 'some-other-secret' not in str(await node({'operation': 'get_api_key_info'}).execute({}))

@pytest.mark.asyncio
@pytest.mark.parametrize('operation', ['set_learning', 'set_anonymization'])
async def test_privacy_empty_and_plain_text_only_acknowledge(monkeypatch, operation):
    for body in ['', 'OK']:
        transport(monkeypatch, text=body)
        result = await node(sample(operation)).execute({})
        assert result['status'] == 'success' and result['acknowledged'] is True
        assert 'readback_verified' not in result

@pytest.mark.asyncio
@pytest.mark.parametrize('body', [[], None, 'bad', {'error': 'bad'}])
async def test_bad_read_shapes_never_claim_success(monkeypatch, body):
    transport(monkeypatch, body)
    try: result = await node({'operation': 'parse_name', 'nameFull': 'John Smith'}).execute({})
    except ValueError: return
    assert result['status'] == 'error'

def test_hand_connect_default_and_batch_limits():
    assert native.NamsorAPIKeyCredential(api_key=TOKEN).credential_type == 'namsor_api_key'
    for value in ['', 'https://namsor.app/key', 'abc\r\nsecret']:
        with pytest.raises(ValidationError): native.NamsorAPIKeyCredential(api_key=value)
    for names in [[], [{'name': 'John Smith'}] * 101]:
        with pytest.raises(ValidationError): native.ParseNamesBatch(personalNames=names)
    with pytest.raises(ValidationError): native.ParseNamesGeoBatch(personalNames=[{'name': 'John Smith', 'countryIso2': 'USA'}])
    assert len(native.ROUTES) == 25
    assert native.NamsorNode.connection_evidence.identity_operation == 'get_api_key_info'

@pytest.mark.asyncio
async def test_connection_evidence_names_provider_account(monkeypatch):
    from nodes.core.connection_evidence import collect_evidence
    transport(monkeypatch, {'userId': 'account-42', 'apiKey': TOKEN})
    result = await collect_evidence(node_type='automation-namsor', user_id='fixture-user',
        credential_data={'credential_type': 'namsor_api_key', 'api_key': TOKEN})
    assert result.reachable is True
    assert result.account_label == 'account-42'
