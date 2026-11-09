"""Offline requests checked against extracted, pinned TikTok provider schemas."""
import json
from pathlib import Path

import httpx
import pytest
from openapi_schema_validator import OAS30Validator
from pydantic import ValidationError

from nodes import tiktok_ads_node as native
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / 'fixtures/tiktok_ads/contract.json').read_text())['cases']
TOKEN = 'synthetic-tiktok-ads-token'
CREDENTIAL = {'credential_type': 'tiktok_ads_access_token', 'access_token': TOKEN, 'advertiser_id': '1234567890123456789'}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credential=None):
    return NodeFactory.create_node(node_id='tiktok-ads-fixture', node_type='automation-tiktok-ads',
        node_data={'config': config, 'credentials': credential or CREDENTIAL})


def transport(monkeypatch, body, status=200):
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
async def test_tiktok_ads_request_matches_provider_fields(monkeypatch, operation):
    case = CASES[operation]
    calls = transport(monkeypatch, case['response'])
    result = await node(case['config']).execute({})
    assert result['status'] == 'success' and result['data'] == case['response']['data']
    assert len(calls) == 1
    request = calls[0]
    assert request.method == case['method']
    assert request.url.host == 'business-api.tiktok.com' and request.url.scheme == 'https'
    assert request.url.path == '/open_api/v1.3' + case['path']
    assert request.headers['Access-Token'] == TOKEN
    assert dict(request.url.params) == case['query']
    body = json.loads(request.content) if request.content else None
    assert body == case['body']
    if body is not None:
        OAS30Validator(case['body_schema']).validate(body)
    for key, value in request.url.params.items():
        schema = case['parameter_schemas'][key]
        if schema.get('type') in {'array', 'object', 'boolean', 'integer'}:
            value = json.loads(value)
        OAS30Validator(schema).validate(value)
    OAS30Validator(case['response_schema']).validate(case['response'])
    assert TOKEN not in str(result)


@pytest.mark.asyncio
async def test_tiktok_ads_account_evidence_uses_credential_and_recognizable_name(monkeypatch):
    case = CASES['get_advertiser_info']
    calls = transport(monkeypatch, case['response'])
    result = await node({'operation': 'get_advertiser_info'}).execute({})
    assert json.loads(calls[0].url.params['advertiser_ids']) == [CREDENTIAL['advertiser_id']]
    assert result['data']['list'][0]['advertiser_name'] == 'Example advertiser'
    assert native.TikTokAdsNode.connection_evidence.operation == 'get_advertiser_info'


@pytest.mark.asyncio
async def test_tiktok_ads_explicit_account_override_and_pagination(monkeypatch):
    case = CASES['list_campaigns']
    calls = transport(monkeypatch, case['response'])
    result = await node({**case['config'], 'advertiser_id': '999'}).execute({})
    assert calls[0].url.params['advertiser_id'] == '999'
    assert result['data']['page_info']['total_page'] == 3 and len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 302, 400, 401, 403, 404, 429, 500])
async def test_tiktok_ads_http_errors_preserve_rejection_and_do_not_retry(monkeypatch, status):
    calls = transport(monkeypatch, {'code': 40001, 'message': 'Rejected ' + TOKEN}, status)
    result = await node(CASES['create_campaign']['config']).execute({})
    assert result['status'] == 'error' and result['http_status'] == status
    assert result['status_code'] == status
    assert result['error'] == 'Rejected [redacted]' and len(calls) == 1
    assert TOKEN not in str(result)


@pytest.mark.asyncio
async def test_tiktok_ads_http_200_api_error_is_not_success(monkeypatch):
    transport(monkeypatch, {'code': 40001, 'message': 'Access token is invalid', 'data': {}})
    result = await node({'operation': 'get_advertiser_info'}).execute({})
    assert result['status'] == 'error' and result['provider_code'] == 40001
    assert result['error'] == 'Access token is invalid'


@pytest.mark.asyncio
async def test_tiktok_ads_partial_batch_failure_preserves_per_item_details(monkeypatch):
    body = {'code': 0, 'data': {'campaign_list': [{'campaign_id': '111'}], 'error_list': [{'campaign_id': '222', 'error_message': 'Not allowed'}]}}
    calls = transport(monkeypatch, body)
    result = await node({'operation': 'update_campaign_status', 'campaign_ids': ['111', '222'], 'operation_status': 'DISABLE'}).execute({})
    assert result['status'] == 'error' and result['data'] == body['data'] and len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [None, [], {}, {'code': '0', 'data': {}}, {'code': False, 'data': {}}, {'code': 0}, {'code': 0, 'data': []}])
async def test_tiktok_ads_invalid_success_envelope(monkeypatch, body):
    transport(monkeypatch, body)
    result = await node({'operation': 'get_advertiser_info'}).execute({})
    assert result['status'] == 'error'


@pytest.mark.asyncio
async def test_tiktok_ads_token_is_redacted_from_success_payload(monkeypatch):
    transport(monkeypatch, {'code': 0, 'request_id': TOKEN, 'data': {TOKEN: [TOKEN]}})
    result = await node({'operation': 'get_advertiser_info'}).execute({})
    assert result['status'] == 'success' and TOKEN not in str(result)


@pytest.mark.parametrize('changes', [{'access_token': 'https://example.com/token'}, {'access_token': 'Bearer token'}, {'access_token': 'abc\nxyz'}, {'advertiser_id': '../other'}, {'advertiser_id': 'account'}])
def test_tiktok_ads_manual_credential_validation(changes):
    with pytest.raises(ValidationError):
        native.TikTokAdsAccessTokenCredential.model_validate({**CREDENTIAL, **changes})


def test_tiktok_ads_credential_type_defaults_for_manual_connect():
    value = native.TikTokAdsAccessTokenCredential(access_token=TOKEN, advertiser_id='123')
    assert value.credential_type == 'tiktok_ads_access_token'


@pytest.mark.parametrize('config', [
    {'operation': 'update_campaign', 'campaign_id': '111'},
    {'operation': 'update_adgroup', 'adgroup_id': '222'},
    {'operation': 'get_report', 'start_date': '2026-11-08', 'end_date': '2026-11-01'},
    {'operation': 'update_campaign_status', 'campaign_ids': [], 'operation_status': 'ENABLE'},
    {'operation': 'get_audiences', 'custom_audience_ids': ['444'], 'history_size': 0},
    {'operation': 'list_pixels', 'page_size': 21},
    {'operation': 'list_ads', 'filtering': {'ad_name': 'Unsupported filter'}},
])
def test_tiktok_ads_invalid_changes_are_refused(config):
    with pytest.raises(ValueError):
        node(config)


@pytest.mark.asyncio
async def test_tiktok_ads_transport_error_has_no_retry(monkeypatch):
    calls = []
    def respond(request):
        calls.append(request)
        raise httpx.ReadTimeout('secret ' + TOKEN, request=request)
    monkeypatch.setattr(native, 'guarded_async_client', lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs))
    result = await node(CASES['create_campaign']['config']).execute({})
    assert result['status'] == 'error' and TOKEN not in str(result) and len(calls) == 1
