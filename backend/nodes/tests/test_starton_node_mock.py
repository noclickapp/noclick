"""Exercise Starton through the workflow factory with synthetic project data.

Fixed route fixtures and write-body assertions guard against sending blockchain
requests to the wrong resource or silently dropping transaction arguments.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import starton_node as native
from nodes.core.registry import NodeFactory

TOKEN = 'synthetic-starton-api-key-42'
CREDENTIAL = {'credential_type': 'starton_api_key', 'api_key': TOKEN}
CASES = json.loads((Path(__file__).parent / 'fixtures/starton/operations.json').read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='starton-fixture', node_type='automation-starton',
        node_data={'config': config, 'credentials': CREDENTIAL})


def transport(monkeypatch, body, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body, headers={'Location': 'https://other.example.test/'})
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', CASES)
async def test_factory_routes_auth_and_documented_response_shapes(monkeypatch, operation):
    case = CASES[operation]
    body = {'id': 'owned-resource', 'name': 'Owned contract'}
    if operation.startswith('list_'):
        body = {'items': [body], 'meta': {'itemCount': 1, 'currentPage': 0, 'totalPages': 1}}
    if operation == 'delete_pin':
        body = True
    requests = transport(monkeypatch, body, status=201 if case['method'] == 'POST' else 200)
    result = await node(case['config']).run({})
    assert result['status'] == 'success', result
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case['method']
    expected = case['path']
    for key, value in case['config'].items():
        wire = 'id' if key == 'resource_id' else 'name' if operation == 'get_network' and key == 'network' else key
        expected = expected.replace('{' + wire + '}', str(value))
    assert request.url.path == expected
    assert request.url.host == 'api.starton.com' and request.url.scheme == 'https'
    assert request.headers['x-api-key'] == TOKEN
    assert TOKEN not in str(result)
    if operation.startswith('list_'):
        assert dict(request.url.params)['page'] == '0'
        assert result['items'][0]['name'] == 'Owned contract'
        assert result['meta'] == body['meta']
    if operation == 'delete_pin':
        assert result['data'] is True


@pytest.mark.asyncio
async def test_transaction_wire_fields_and_simulation_are_preserved(monkeypatch):
    requests = transport(monkeypatch, {'id': 'tx_owned', 'state': 'PENDING'}, 201)
    wallet = '0x298e760768c8481780397eE28A127eAd584df4ee'
    result = await node({'operation': 'create_transaction', 'network': 'polygon-amoy',
        'signerWallet': wallet, 'to': wallet, 'value': '1000000000000000000',
        'data': '0x1234', 'simulate': True, 'metadata': {'invoice': '42'}, 'nonce': 0}).run({})
    assert result['status'] == 'success'
    assert dict(requests[0].url.params) == {'simulate': 'true'}
    assert json.loads(requests[0].content) == {'network': 'polygon-amoy', 'signerWallet': wallet,
        'to': wallet, 'value': '1000000000000000000', 'data': '0x1234', 'metadata': {'invoice': '42'}, 'nonce': 0}
    assert result['data']['state'] == 'PENDING'


@pytest.mark.asyncio
async def test_contract_read_params_and_ipfs_json_remain_structured(monkeypatch):
    requests = transport(monkeypatch, {'response': {'result': '42'}}, 201)
    cfg = {**CASES['read_smart_contract']['config'], 'functionName': 'balanceOf', 'params': ['0xabc', 0, False, {'nested': 'value'}]}
    assert (await node(cfg).run({}))['status'] == 'success'
    assert json.loads(requests[0].content) == {'functionName': 'balanceOf', 'params': cfg['params']}
    requests = transport(monkeypatch, {'id': 'req_owned'}, 201)
    content = {'name': 'NFT', 'attributes': [{'trait_type': 'Level', 'value': 1}]}
    assert (await node({'operation': 'upload_json', 'name': 'metadata.json', 'content': content}).run({}))['status'] == 'success'
    assert json.loads(requests[0].content) == {'name': 'metadata.json', 'content': content}


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 302, 400, 401, 403, 404, 429, 500])
async def test_provider_errors_are_not_retried_or_followed_and_secrets_are_redacted(monkeypatch, status):
    requests = transport(monkeypatch, {'message': 'Rejected ' + TOKEN}, status)
    result = await node({'operation': 'list_smart_contracts'}).run({})
    assert result['status'] == 'error' and result['http_status'] == status
    assert result['message'] == 'Rejected [redacted]' and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{}, {'items': {}, 'meta': {}}, {'items': []}, {'statusCode': 401, 'errorCode': 'NOT_AUTHENTICATED', 'message': 'Not authenticated'}])
async def test_invalid_lists_and_error_envelopes_never_prove_connection(monkeypatch, body):
    transport(monkeypatch, body)
    if body.get('errorCode'):
        result = await node({'operation': 'list_smart_contracts'}).run({})
        assert result['status'] == 'error' and result['message'] == 'Not authenticated'
    else:
        with pytest.raises(ValueError, match='Unexpected Starton paginated response'):
            await node({'operation': 'list_smart_contracts'}).run({})


@pytest.mark.asyncio
async def test_output_redacts_secret_fields_and_echoes(monkeypatch):
    transport(monkeypatch, {'name': TOKEN, 'privateKey': 'private', 'nested': {'api_key': TOKEN}})
    result = await node(CASES['get_wallet']['config']).run({})
    assert result['data'] == {'name': '[redacted]', 'nested': {}}


@pytest.mark.parametrize('config', [
    {'operation': 'get_pin', 'resource_id': '../other'},
    {'operation': 'get_wallet', 'address': 'wrong'},
    {'operation': 'list_smart_contracts', 'limit': 2501},
    {'operation': 'create_wallet'},
    {'operation': 'call_smart_contract', 'network': 'polygon-amoy', 'address': '0x298e760768c8481780397eE28A127eAd584df4ee'},
    {'operation': 'arbitrary_request', 'url': 'https://other.example.test'},
])
def test_missing_invalid_and_foreign_fields_fail_before_request(config):
    with pytest.raises((ValueError, ValidationError)):
        native.StartonNode.parse_config({'config': config, 'credentials': CREDENTIAL})


def test_manual_credential_defaults_and_evidence_contract():
    cred = native.StartonAPIKeyCredential(api_key=TOKEN)
    assert cred.credential_type == 'starton_api_key'
    assert native.StartonNode.connection_evidence.operation == 'list_smart_contracts'
    assert len(CASES) == 25 and len({x['provider_operation'] for x in CASES.values()}) == 25
    assert TOKEN not in repr(cred) and 'api_key=' not in repr(cred)


@pytest.mark.asyncio
async def test_json_editor_strings_become_json_objects_on_the_wire(monkeypatch):
    requests = transport(monkeypatch, {'id': 'req_owned'}, 201)
    result = await node({'operation': 'upload_json', 'name': 'metadata.json',
        'content': '{"name": "NFT", "attributes": []}', 'metadata': '{"batch": 42}'}).run({})
    assert result['status'] == 'success'
    assert json.loads(requests[0].content) == {'name': 'metadata.json',
        'content': {'name': 'NFT', 'attributes': []}, 'metadata': {'batch': 42}}


@pytest.mark.parametrize('value', ['[]', 'not json', '{"n": NaN}'])
def test_json_editor_refuses_non_objects_and_non_finite_values(value):
    with pytest.raises((ValueError, ValidationError)):
        native.StartonNode.parse_config({'config': {'operation': 'upload_json',
            'name': 'metadata.json', 'content': value}, 'credentials': CREDENTIAL})


@pytest.mark.asyncio
async def test_kms_credentials_are_removed_from_both_list_projections(monkeypatch):
    transport(monkeypatch, {'items': [{'id': 'kms_owned', 'name': 'Team KMS',
        'credentials': {'accessKeyId': 'sensitive', 'secretAccessKey': 'sensitive'}}], 'meta': {}})
    result = await node({'operation': 'list_kms'}).run({})
    assert result['items'] == [{'id': 'kms_owned', 'name': 'Team KMS'}]
    assert result['data']['items'] == result['items']
    assert 'sensitive' not in str(result)
