"""Network-free checks using synthetic values and schema examples from Spydra's pinned API contract."""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from openapi_schema_validator import OAS30Validator
from nodes import spydra_node as native
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / 'fixtures/spydra/contract.json').read_text())['cases']
TOKEN = 'synthetic-spydra-token-42'
BASE = 'https://network.spydra.app/tokenize/chaincode'

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield

def credential(**changes):
    return {'credential_type': 'spydra_api_key', 'api_key': TOKEN, 'api_url': BASE, **changes}

def node(config):
    return NodeFactory.create_node(node_id='spydra-fixture', node_type='automation-spydra',
        node_data={'config': config, 'credentials': credential()})

def transport(monkeypatch, status, body):
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return calls

@pytest.mark.asyncio
@pytest.mark.parametrize('operation', CASES)
async def test_each_operation_matches_published_contract(monkeypatch, operation):
    case = CASES[operation]
    calls = transport(monkeypatch, case['response_status'], case['response'])
    result = await node(case['config']).execute({})
    assert result['status'] == 'success' and result['data'] == case['response']
    assert len(calls) == 1
    request = calls[0]
    assert request.method == case['method']
    assert request.url.path == '/tokenize/chaincode' + case['path']
    assert request.url.host == 'network.spydra.app'
    assert dict(request.url.params) == case['query']
    assert request.headers['X-API-KEY'] == TOKEN
    assert (json.loads(request.content) if request.content else None) == case['body']
    if case['body'] is not None:
        OAS30Validator(case['body_schema']).validate(json.loads(request.content))
    for key, value in request.url.params.items():
        schema = case['parameter_schemas'][key]
        value = int(value) if schema['type'] == 'integer' else (value == 'true' if schema['type'] == 'boolean' else value)
        OAS30Validator(schema).validate(value)
    assert TOKEN not in str(result)

@pytest.mark.asyncio
async def test_explicit_bookmark_and_entity_query_not_auto_paginated(monkeypatch):
    body = {'count': 0, 'records': [], 'bookmark': 'next+cursor/='}
    calls = transport(monkeypatch, 200, body)
    result = await node({'operation': 'list_assets', 'assetType': 'Property',
        'pageSize': 10, 'bookmark': 'previous+cursor/=', 'actAs': 'userId:123'}).execute({})
    assert result['data'] == body and len(calls) == 1
    assert dict(calls[0].url.params) == {'assetType': 'Property', 'pageSize': '10',
        'bookmark': 'previous+cursor/=', 'actAs': 'userId:123'}

@pytest.mark.asyncio
async def test_async_receipt_is_not_claimed_committed(monkeypatch):
    calls = transport(monkeypatch, 202, {'receiptId': 'receipt-1'})
    result = await node({**CASES['create_assets']['config'], 'async_mode': True}).execute({})
    assert result['data'] == {'receiptId': 'receipt-1'}
    assert calls[0].url.params['async'] == 'true' and len(calls) == 1
    assert 'committed' not in result

@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 302, 400, 401, 403, 404, 409, 429, 500])
async def test_refusals_do_not_leak_key_or_retry_writes(monkeypatch, status):
    calls = transport(monkeypatch, status, {'errorCode': 'Denied', 'message': TOKEN})
    result = await node(CASES['create_assets']['config']).execute({})
    assert result['status'] == 'error' and result['http_status'] == status
    assert TOKEN not in str(result) and len(calls) == 1

@pytest.mark.asyncio
@pytest.mark.parametrize('body', [[], None, {}, {'records': 'invalid'}, {'errorCode': 'Invalid'}, {'error': TOKEN}])
async def test_invalid_success_envelopes_are_errors(monkeypatch, body):
    transport(monkeypatch, 200, body)
    result = await node({'operation': 'list_my_transfer_requests'}).execute({})
    assert result['status'] == 'error' and TOKEN not in str(result)

@pytest.mark.asyncio
async def test_write_requires_receipt_and_supports_custom_entity_key(monkeypatch):
    calls = transport(monkeypatch, 200, {'receiptId': 'receipt-1'})
    config = {'operation': 'update_asset_owners', 'assetType': 'Property',
        'data': [{'id': 'Prop1', 'owners': [{'orgId': 'org-1', 'vendorId': 'vendor-2'}]}]}
    assert (await node(config).execute({}))['status'] == 'success'
    assert json.loads(calls[0].content)['data'][0]['owners'] == [{'orgId': 'org-1', 'vendorId': 'vendor-2'}]
    transport(monkeypatch, 200, {})
    assert (await node(config).execute({}))['status'] == 'error'

@pytest.mark.parametrize('url', ['http://network.spydra.app/tokenize/app',
    'https://user:pass@network.spydra.app/tokenize/app', 'https://network.spydra.app:443/tokenize/app',
    'https://127.0.0.1/tokenize/app', 'https://network.spydra.app/tokenize/../app',
    BASE + '?key=secret', BASE + '#fragment', 'https://network.spydra.app'])
def test_rejects_unsafe_or_incomplete_deployment_url(url):
    with pytest.raises(ValidationError):
        native.SpydraAPIKeyCredential.model_validate(credential(api_url=url))

def test_manual_credential_default_and_required_fields():
    value = native.SpydraAPIKeyCredential.model_validate({'api_key': TOKEN, 'api_url': BASE + '/'})
    assert value.credential_type == 'spydra_api_key' and value.api_url == BASE
    for cfg in [{'operation': 'get_asset', 'assetType': 'Property'},
        {'operation': 'create_assets', 'assetType': 'Property', 'data': []},
        {'operation': 'get_approval', 'id': 'id-1'}, {'operation': 'unknown'}]:
        with pytest.raises(ValueError):
            native.SpydraNode.parse_config({'config': cfg, 'credentials': credential()})
    assert native.SpydraNode.connection_evidence.operation == 'list_my_transfer_requests'
    assert len(CASES) == 23


@pytest.mark.asyncio
async def test_connection_refusal_retains_provider_words_and_status(monkeypatch):
    transport(monkeypatch, 403, {"errorCode": "Forbidden", "message": "Access denied for organization"})
    result = await node({"operation": "list_my_transfer_requests"}).execute({})
    assert result['error'] == 'Access denied for organization' and result['status_code'] == 403
