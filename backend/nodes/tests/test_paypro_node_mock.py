"""PayPro contract examples through the real factory; no live account needed."""
import copy
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import paypro_node as native
from nodes.core.registry import NodeFactory

EXAMPLES = json.loads((Path(__file__).parent / 'fixtures/paypro/contract_examples.json').read_text())
TOKEN = 'paypro-synthetic-test-key-753'


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='paypro-test', node_type='automation-paypro',
        node_data={'config': config, 'credentials': {'credential_type': 'paypro_api_key', 'api_key': TOKEN}})


def transport(monkeypatch, reply):
    requests = []
    def respond(req):
        requests.append(req)
        return reply(req)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', EXAMPLES)
async def test_published_contract_examples_exact_request_and_parse(monkeypatch, operation):
    case = EXAMPLES[operation]
    expected_status = 201 if operation in {'create_customer', 'create_payment', 'create_refund', 'create_subscription'} else 200
    requests = transport(monkeypatch, lambda req: httpx.Response(expected_status, json=case['response']))
    result = await node(case['config']).execute({})
    assert result['status'] == 'success'
    assert TOKEN not in json.dumps(result)
    assert len(requests) == 1
    req = requests[0]
    assert req.method == case['method']
    assert req.url.host == 'api.paypro.nl'
    assert req.url.path == case['path'].replace('{id}', 'resource123').replace('{balance_id}', 'resource123')
    assert req.headers['Authorization'] == 'Bearer ' + TOKEN
    if 'body' in case['config']:
        assert json.loads(req.content) == case['config']['body']
    else:
        assert req.content == b''
    assert dict(req.url.params) == ({'limit': '10'} if operation.startswith('list_') else {})
    assert result['data'] == (case['response']['data'] if operation.startswith('list_') else case['response'])


@pytest.mark.asyncio
async def test_cursor_is_returned_and_reused_without_following_links(monkeypatch):
    body = copy.deepcopy(EXAMPLES['list_customers']['response'])
    body['_links']['next'] = 'https://api.paypro.nl/customers?cursor=next%2Bpage&limit=2'
    requests = transport(monkeypatch, lambda req: httpx.Response(200, json=body))
    result = await node({'operation': 'list_customers', 'limit': 2}).execute({})
    assert result['has_more'] is True and result['next_cursor'] == 'next+page'
    assert len(requests) == 1
    body['_links'].pop('next')
    result = await node({'operation': 'list_customers', 'limit': 2, 'cursor': result['next_cursor']}).execute({})
    assert dict(requests[-1].url.params) == {'limit': '2', 'cursor': 'next+page'}
    assert result['has_more'] is False


@pytest.mark.asyncio
@pytest.mark.parametrize('url', ['https://evil.example/customers?cursor=x', 'https://api.paypro.nl/payments?cursor=x', 'https://api.paypro.nl/customers?cursor=old', 'https://api.paypro.nl/customers?limit=2'])
async def test_invalid_continuation_never_leaks_auth_or_claims_completion(monkeypatch, url):
    body = copy.deepcopy(EXAMPLES['list_customers']['response'])
    body['_links']['next'] = url
    requests = transport(monkeypatch, lambda req: httpx.Response(200, json=body))
    result = await node({'operation': 'list_customers', 'cursor': 'old'}).execute({})
    assert result['status'] == 'error' and len(requests) == 1 and 'data' not in result


@pytest.mark.asyncio
@pytest.mark.parametrize('code', [301, 401, 403, 404, 429, 500])
async def test_rejections_are_not_success_and_key_is_redacted(monkeypatch, code):
    requests = transport(monkeypatch, lambda req: httpx.Response(code, json={'message': TOKEN}))
    result = await node({'operation': 'list_customers'}).execute({})
    assert result['status'] == 'error' and result['http_status'] == code
    assert TOKEN not in str(result) and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('payload', [{}, [], {'type': 'list', 'data': [], 'count': '1'}, {'type': 'list', 'data': [{'id': 'x', 'type': 'payment'}], 'count': 1}])
async def test_malformed_customer_pages_fail_closed(monkeypatch, payload):
    transport(monkeypatch, lambda req: httpx.Response(200, json=payload))
    result = await node({'operation': 'list_customers'}).execute({})
    assert result['status'] == 'error' and 'data' not in result


@pytest.mark.asyncio
async def test_write_timeout_is_unknown_and_never_retried(monkeypatch):
    def timeout(req):
        raise httpx.ReadTimeout('lost reply', request=req)
    requests = transport(monkeypatch, timeout)
    result = await node(EXAMPLES['create_refund']['config']).execute({})
    assert result['status'] == 'unknown' and len(requests) == 1


@pytest.mark.asyncio
async def test_payment_conflicting_mandate_is_refused_before_request(monkeypatch):
    requests = transport(monkeypatch, lambda req: pytest.fail('must not request'))
    cfg = copy.deepcopy(EXAMPLES['create_payment']['config'])
    cfg['body']['mandate'] = 'MD123'
    with pytest.raises(ValueError, match='mandate'):
        await node(cfg).execute({})
    assert not requests


@pytest.mark.parametrize('config', [
    {'operation': 'get_customer', 'customer_id': '../payments'},
    {'operation': 'list_customers', 'limit': 101},
    {'operation': 'create_payment', 'body': {'amount': True, 'currency': 'EUR', 'description': 'test'}},
    {'operation': 'create_payment', 'body': {'amount': 1000, 'currency': 'USD', 'description': 'test'}},
    {'operation': 'update_customer', 'customer_id': 'CU123', 'body': {'unknown': 'field'}},
])
def test_invalid_configuration_is_rejected(config):
    with pytest.raises((ValidationError, ValueError)):
        native.PayProNode.parse_config({'config': config})


def test_manual_credential_default_and_evidence():
    credential = native.PayProAPIKeyCredential(api_key='  '+TOKEN+'  ')
    assert credential.credential_type == 'paypro_api_key' and credential.api_key == TOKEN
    assert native.PayProNode.connection_evidence.operation == 'list_customers'
    for value in ['Bearer '+TOKEN, 'https://example.com/key', '<token>', '']:
        with pytest.raises((ValueError, ValidationError)):
            native.PayProAPIKeyCredential(api_key=value)


@pytest.mark.asyncio
async def test_update_sends_explicit_null_without_sending_unset_fields(monkeypatch):
    requests = transport(monkeypatch, lambda req: httpx.Response(200, json=EXAMPLES['update_customer']['response']))
    result = await node({'operation': 'update_customer', 'customer_id': 'CU123', 'body': {'email': None}}).execute({})
    assert result['status'] == 'success'
    assert json.loads(requests[0].content) == {'email': None}


@pytest.mark.asyncio
async def test_write_server_error_and_malformed_success_are_unknown(monkeypatch):
    for response in [httpx.Response(503, json={'error': 'unavailable'}), httpx.Response(201, json={})]:
        requests = transport(monkeypatch, lambda req: response)
        result = await node(EXAMPLES['create_payment']['config']).execute({})
        assert result['status'] == 'unknown' and len(requests) == 1
