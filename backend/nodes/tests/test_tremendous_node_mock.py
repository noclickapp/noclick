"""Exercise every verbatim published response, plus wire and failure boundaries."""
import json
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest

from nodes import tremendous_node as t
from nodes.core.registry import NodeFactory

FIXTURES = json.loads((Path(__file__).parent / 'fixtures/tremendous/postman_examples.json').read_text())
AUTH = {'credential_type': 'tremendous_api_key', 'api_key': 'test-tremendous-secret-123'}
ORDER = {'external_id': 'sample-order-001', 'payment': {'funding_source_id': 'BALANCE'},
         'reward': {'value': {'denomination': 10, 'currency_code': 'USD'},
                    'recipient': {'name': 'Alice', 'email': 'alice@example.com'},
                    'delivery': {'method': 'EMAIL'}, 'products': ['Q24BD9EZ332JT']}}


def config(op):
    data = {'operation': op}
    route = t.ROUTES[op][1]
    for key in ['reward_id', 'order_id', 'product_id', 'campaign_id', 'funding_source_id', 'invoice_id', 'organization_id']:
        if '{' + key + '}' in route:
            data[key] = 'NNS4ZRIYF71F'
    if op == 'create_order': data.update(ORDER)
    if op == 'create_invoice': data['amount'] = 100
    return data


def install(monkeypatch, example):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(example['code'], content=example.get('body', '').encode(),
                              headers=[(h['key'], h['value']) for h in example.get('header', [])])
    @asynccontextmanager
    async def client(**kwargs):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            yield c
    monkeypatch.setattr(t, 'guarded_async_client', client)
    return calls


async def run(data, auth=None):
    node = NodeFactory.create_node(node_id='t', node_type='automation-tremendous',
        node_data={'config': data, 'credentials': auth or AUTH})
    return await node.execute({})


CASES = [(op, i) for op, item in FIXTURES['operations'].items() for i in range(len(item['response']))]


@pytest.mark.asyncio
@pytest.mark.parametrize('op,index', CASES)
async def test_all_saved_postman_responses(monkeypatch, op, index):
    example = FIXTURES['operations'][op]['response'][index]
    calls = install(monkeypatch, example)
    result = await run(config(op))
    assert len(calls) == 1
    assert calls[0].method == t.ROUTES[op][0]
    assert calls[0].headers['authorization'] == 'Bearer ' + AUTH['api_key']
    assert calls[0].url.host == 'testflight.tremendous.com'
    assert result['http_status'] == example['code']
    assert result['status'] == ('success' if 200 <= example['code'] < 300 else 'error')
    if result['status'] == 'success':
        for key, value in json.loads(example['body']).items(): assert result[key] == value


@pytest.mark.asyncio
async def test_order_exact_body_and_production_opt_in(monkeypatch):
    calls = install(monkeypatch, FIXTURES['operations']['create_order']['response'][0])
    await run(config('create_order'), {**AUTH, 'environment': 'production'})
    assert calls[0].url == 'https://api.tremendous.com/api/v2/orders'
    assert json.loads(calls[0].content) == ORDER


@pytest.mark.asyncio
async def test_paging_and_filters(monkeypatch):
    calls = install(monkeypatch, FIXTURES['operations']['list_invoices']['response'][0])
    await run({'operation': 'list_invoices', 'offset': 20, 'limit': 10})
    assert dict(calls[0].url.params) == {'offset': '20', 'limit': '10'}


@pytest.mark.asyncio
async def test_resend_sends_no_undocumented_body(monkeypatch):
    calls = install(monkeypatch, FIXTURES['operations']['resend_reward']['response'][0])
    await run(config('resend_reward'))
    assert calls[0].content == b''


@pytest.mark.asyncio
@pytest.mark.parametrize('body', ['<html>login</html>', '[]', '{}', '{"error":"refused"}'])
async def test_malformed_success_is_not_success(monkeypatch, body):
    install(monkeypatch, {'code': 200, 'body': body})
    with pytest.raises(ValueError): await run(config('list_organizations'))


@pytest.mark.parametrize('identifier', ['../other', 'a/b', 'a?x=1', 'https://evil.test'])
def test_resource_ids_cannot_change_routes(identifier):
    with pytest.raises(ValueError): t.GetRewardConfig(reward_id=identifier)


@pytest.mark.parametrize('changes', [{'external_id': ''}, {'reward': {**ORDER['reward'], 'products': None}}, {'reward': {**ORDER['reward'], 'value': {'denomination': -1}}}])
def test_invalid_orders_refused(changes):
    with pytest.raises(ValueError): t.CreateOrderConfig(**{**ORDER, **changes})


def test_manual_credential_defaults():
    assert t.TremendousAPIKeyCredential(api_key=AUTH['api_key']).credential_type == 'tremendous_api_key'


@pytest.mark.asyncio
async def test_provider_error_redacts_key(monkeypatch):
    install(monkeypatch, {'code': 401, 'body': AUTH['api_key']})
    assert AUTH['api_key'] not in json.dumps(await run(config('list_organizations')))


@pytest.mark.asyncio
async def test_transport_failure_never_retries(monkeypatch):
    calls = []
    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("uncertain", request=request)
    @asynccontextmanager
    async def client(**kwargs):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            yield c
    monkeypatch.setattr(t, 'guarded_async_client', client)
    with pytest.raises(ValueError, match="may have been applied"):
        await run(config('create_order'))
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_redirect_not_followed(monkeypatch):
    calls = install(monkeypatch, {'code': 302, 'body': '', 'header': [{'key': 'Location', 'value': 'https://foreign.test'}]})
    result = await run(config('list_organizations'))
    assert result['status'] == 'error' and len(calls) == 1


def test_other_credential_family_refused():
    with pytest.raises(ValueError):
        t.TremendousAPIKeyCredential(credential_type='other_api_key', api_key=AUTH['api_key'])
