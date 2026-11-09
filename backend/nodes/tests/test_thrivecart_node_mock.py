"""Replay verbatim provider Postman examples through the native node factory."""
import json
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import ValidationError

from nodes import thrivecart_node as native
from nodes.core.registry import NodeFactory

FIXTURES = json.loads((Path(__file__).parent / 'fixtures/thrivecart/postman_examples.json').read_text())
KEY = 'test-thrivecart-private-key-12345'


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credentials=None):
    return NodeFactory.create_node(node_id='thrivecart-test', node_type='automation-thrivecart',
        node_data={'config': config, 'credentials': credentials or {'credential_type': 'thrivecart_api_key', 'api_key': KEY}})


def transport(monkeypatch, body, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False
        assert kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


CASES = [(op, i) for op, example in FIXTURES.items() for i in range(len(example['responses']))]


@pytest.mark.asyncio
@pytest.mark.parametrize('op,index', CASES)
async def test_all_saved_success_examples_and_exact_route(monkeypatch, op, index):
    example = FIXTURES[op]
    saved = example['responses'][index]
    body = json.loads(saved['body'])
    requests = transport(monkeypatch, body, saved['code'])
    result = await node(example['config']).execute({})
    assert result['status'] == 'success'
    assert result['data'] == body
    assert len(requests) == 1
    request = requests[0]
    method = example['request']['method']
    published_url = example['request']['url'].split('?')[0]
    for field, value in example['config'].items():
        published_url = published_url.replace(':' + field, str(value))
    assert request.method == method
    assert str(request.url).split('?')[0] == published_url
    assert request.headers['Authorization'] == 'Bearer ' + KEY
    assert KEY not in str(result)
    if method == 'POST' and op != 'create_student':
        assert request.headers['content-type'].startswith('application/x-www-form-urlencoded')
        expected = {k: [str(v)] for k, v in example['config'].items() if k not in {'operation', 'mode'}}
        assert parse_qs(request.content.decode()) == expected
    if op == 'create_student':
        assert request.headers['content-type'].startswith('multipart/form-data; boundary=')
        for field in ('email', 'course_id', 'tags[]', 'order_info[order_id]', 'order_info[purchase_type]', 'order_info[purchase_id]', 'trigger_emails'):
            assert ('name="' + field + '"').encode() in request.content


@pytest.mark.asyncio
async def test_search_filters_and_pagination_are_preserved(monkeypatch):
    body = json.loads(FIXTURES['search_transactions']['responses'][0]['body'])
    requests = transport(monkeypatch, body)
    result = await node({'operation': 'search_transactions', 'page': 2, 'per_page': 100,
        'query': 'demo+sales@thrivecart.com', 'transaction_type': 'refund', 'currency': 'usd', 'mode': 'test'}).execute({})
    assert dict(requests[0].url.params) == {'page': '2', 'perPage': '100', 'query': 'demo+sales@thrivecart.com', 'transactionType': 'refund', 'currency': 'usd'}
    assert requests[0].headers['X-TC-Mode'] == 'test'
    assert result['data']['meta'] == body['meta']
    assert result['page'] == 2 and result['per_page'] == 100
    assert 'complete' not in result


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [200, 400, 401, 403, 429, 500])
async def test_error_envelopes_redact_key_and_never_retry(monkeypatch, status):
    requests = transport(monkeypatch, {'error': 'Rejected ' + KEY}, status)
    result = await node({'operation': 'get_account'}).execute({})
    assert result['status'] == 'error' and not result['success']
    assert result['http_status'] == status
    assert result['message'] == 'Rejected [redacted]'
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_false_write_success_is_error(monkeypatch):
    requests = transport(monkeypatch, {'success': False, 'message': 'Cannot refund'})
    result = await node(FIXTURES['refund_transaction']['config']).execute({})
    assert result['status'] == 'error'
    assert len(requests) == 1


@pytest.mark.parametrize('config', [
    {'operation': 'get_product', 'product_id': '../ping'},
    {'operation': 'get_product', 'product_id': '1?secret=x'},
    {'operation': 'search_transactions', 'per_page': 101},
    {'operation': 'search_affiliates', 'per_page': 26},
    {'operation': 'get_customer', 'email': 'not-an-email'},
    {'operation': 'pause_subscription', 'order_id': '1', 'subscription_id': '2', 'auto_resume': 1},
    {'operation': 'create_student', 'email': 'student@thrivecart.com', 'course_id': '1', 'order_id': '1'},
])
def test_invalid_configs_fail_before_request(config):
    with pytest.raises((ValueError, ValidationError)):
        native.ThriveCartNode.parse_config({'config': config})


def test_manual_credential_has_default_type_and_cleans_key():
    credential = native.ThriveCartAPIKeyCredential(api_key='  ' + KEY + '  ')
    assert credential.credential_type == 'thrivecart_api_key'
    assert credential.api_key == KEY
    for bad in ('Bearer ' + KEY, 'https://thrivecart.com/token', '<token>', 'line\nfeed'):
        with pytest.raises((ValueError, ValidationError)):
            native.ThriveCartAPIKeyCredential(api_key=bad)


@pytest.mark.asyncio
async def test_identity_is_account_specific_and_non_json_is_unverified(monkeypatch):
    transport(monkeypatch, {'account_id': '1', 'account_name': 'myaccount'})
    result = await node({'operation': 'get_account'}).execute({})
    assert result['data']['account_name'] == 'myaccount'
    transport(monkeypatch, {})
    with pytest.raises(ValueError, match='account information'):
        await node({'operation': 'get_account'}).execute({})


@pytest.mark.asyncio
async def test_student_multiple_tags_order_encoding_and_false_email(monkeypatch):
    from email.parser import BytesParser
    from email.policy import default
    requests = transport(monkeypatch, json.loads(FIXTURES['create_student']['responses'][0]['body']))
    await node({'operation': 'create_student', 'email': 'student@thrivecart.com', 'course_id': '2255',
        'tags': ['one', 'two'], 'trigger_emails': False}).execute({})
    request = requests[0]
    message = BytesParser(policy=default).parsebytes(('Content-Type: ' + request.headers['content-type'] + '\r\n\r\n').encode() + request.content)
    fields = [(p.get_param('name', header='content-disposition'), p.get_payload(decode=True).decode()) for p in message.iter_parts()]
    assert [v for k, v in fields if k == 'tags[]'] == ['one', 'two']
    assert ('trigger_emails', 'false') in fields
    assert not any(k.startswith('order_info') for k, _ in fields)
