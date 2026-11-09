"""Exercise native Manychat operations through the registry, without credentials or network."""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from nodes import manychat_node as api
from nodes.core.run_op import run_node_operation
from utils import ssrf

CASES = json.loads((Path(__file__).parent / 'fixtures/manychat/operations.json').read_text())
AUTH = {'credential_type': 'manychat_api_token', 'api_token': 'synthetic-manychat-token'}


@pytest.fixture
def transport(monkeypatch):
    seen, replies = [], []
    monkeypatch.setattr(ssrf, '_resolve_host_addresses', AsyncMock(return_value=['93.184.216.34']))
    async def send(request):
        seen.append(request)
        assert request.url.host == 'api.manychat.com'
        assert request.headers['Authorization'] == 'Bearer ' + AUTH['api_token']
        assert AUTH['api_token'] not in str(request.url)
        code, body, headers = replies.pop(0)
        return httpx.Response(code, json=body, headers=headers)
    native = ssrf.guarded_async_client
    monkeypatch.setattr(api, 'guarded_async_client', lambda **kw: native(**kw, transport=httpx.MockTransport(send)))
    return seen, replies


async def run(op, config=None, credential=None):
    return await run_node_operation(node_type='automation-manychat', operation=op, arguments=config or {},
        credential_data=AUTH if credential is None else credential, user_id='00000000-0000-0000-0000-000000000001')


@pytest.mark.asyncio
@pytest.mark.parametrize('case', CASES, ids=lambda c: c['operation'])
async def test_exact_native_wire_contract(transport, case):
    seen, replies = transport
    replies.append((200, case['response'], {}))
    result = await run(case['operation'], case['config'])
    assert result['status'] == 'success'
    assert len(seen) == 1
    request = seen[0]
    assert request.method == case['method'] and request.url.path == case['path']
    if request.method == 'GET':
        assert dict(request.url.params) == {('field_value' if k == 'search_value' else k): str(v) for k, v in case['config'].items()}
        assert not request.content
    else:
        assert json.loads(request.content) == case['config']
    if case['operation'] == 'send_flow':
        assert result['accepted'] is True and result['delivery_verified'] is False
    assert AUTH['api_token'] not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize('code,body,headers', [
    (401, {'status':'error','message':'Invalid API key'}, {}),
    (429, {'status':'error','message':'Too many requests'}, {}),
    (200, {'status':'error','message':'Permission denied'}, {}),
    (200, {'status':'success'}, {}),
    (200, [], {}),
    (200, {'status':'success','data':{}}, {}),
    (200, {'status':'success','data':{'id':123,'name':'Fixture'}}, {'Content-Type':'text/html'}),
    (302, {}, {'Location':'https://foreign.test'}),
])
async def test_failure_envelopes_never_prove_connection(transport, code, body, headers):
    transport[1].append((code, body, headers))
    with pytest.raises(ValueError):
        await run('get_page_info')
    assert len(transport[0]) == 1


@pytest.mark.asyncio
async def test_provider_rejection_preserved_and_secret_redacted(transport):
    transport[1].append((403, {'status':'error','message':'Denied ' + AUTH['api_token']}, {}))
    with pytest.raises(ValueError, match='Denied') as exc:
        await run('get_page_info')
    assert AUTH['api_token'] not in str(exc.value)


@pytest.mark.asyncio
@pytest.mark.parametrize('tag', ['other_api_token', None, '', 42])
async def test_foreign_family_fails_before_transport(transport, tag):
    with pytest.raises(ValueError):
        await run('get_page_info', credential={**AUTH,'credential_type':tag})
    assert not transport[0]


@pytest.mark.parametrize('op,config', [
    ('create_subscriber', {}),
    ('create_subscriber', {'email':'fixture@example.test'}),
    ('update_subscriber', {'subscriber_id':123}),
    ('update_subscriber', {'subscriber_id':123,'phone':'+15400000000','has_opt_in_sms':True}),
    ('find_subscriber_by_system_field', {}),
    ('add_subscriber_tag', {'subscriber_id':123,'tag_id':-1}),
    ('set_bot_field', {'field_id':123,'field_value':{'unexpected':'object'}}),
    ('get_page_info', {'url':'https://foreign.test'}),
])
def test_invalid_inputs_refused(op, config):
    with pytest.raises(ValueError):
        api.ManychatNode.parse_config({'config': {'operation':op, **config}, 'credentials':AUTH})


@pytest.mark.asyncio
@pytest.mark.parametrize('value', [False, 0, 1.25, '2018-07-18'])
async def test_custom_values_keep_scalar_type(transport, value):
    transport[1].append((200, {'status':'success'}, {}))
    await run('set_subscriber_custom_field', {'subscriber_id':123,'field_id':456,'field_value':value})
    sent = json.loads(transport[0][0].content)['field_value']
    assert type(sent) is type(value) and sent == value


def test_credential_manual_default():
    credential = api.ManychatAPITokenCredential(api_token='synthetic-manychat-token')
    assert credential.credential_type == 'manychat_api_token'
    assert api.ManychatAPITokenCredential.model_fields['credential_type'].default == 'manychat_api_token'


@pytest.mark.asyncio
async def test_connection_evidence_names_actual_page(transport):
    from nodes.core.connection_evidence import collect_evidence
    transport[1].append((200, {'status':'success','data':{'id':123,'name':'Fixture account'}}, {}))
    evidence = await collect_evidence(node_type='automation-manychat', credential_data=AUTH,
        user_id='00000000-0000-0000-0000-000000000001')
    assert evidence.reachable is True
    assert 'Fixture account' in str(evidence)
    assert transport[0][0].method == 'GET'
    assert transport[0][0].url.path == '/fb/page/getInfo'
