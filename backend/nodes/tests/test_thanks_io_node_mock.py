"""Exercise the real factory with provider-authored response examples, offline."""
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock
import httpx
import pytest
from nodes import thanks_io_node as native
from nodes.core.registry import NodeFactory
from nodes.core.connection_evidence import collect_evidence
from utils import ssrf

TOKEN = "fixture-thanks-key-42"
AUTH = {"credential_type": "thanks_io_api_key", "api_key": TOKEN}
CASES = json.loads((Path(__file__).parent / "fixtures/thanks_io/published_cases.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))
    async def respond(request):
        requests.append(request)
        assert request.url.host == "api.thanks.io"
        assert request.headers["Authorization"] == "Bearer " + TOKEN
        assert TOKEN not in str(request.url)
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply
    guarded = ssrf.guarded_async_client
    monkeypatch.setattr(native, "guarded_async_client", lambda **kwargs: guarded(**kwargs, transport=httpx.MockTransport(respond)))
    return requests, replies


def node(config, auth=None):
    return NodeFactory.create_node(node_id="thanks-fixture", node_type="automation-thanks-io",
        node_data={"config": config, "credentials": deepcopy(AUTH if auth is None else auth)})


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=[c['operation'] for c in CASES])
async def test_published_responses_and_exact_request_contract(transport, case):
    requests, replies = transport
    replies.append(httpx.Response(case['status'], json=case['body']))
    config = {"operation": case['operation'], **case['config']}
    instance = node(config)
    result = await instance.execute({})
    assert result['success'] is True
    assert result['http_status'] == case['status']
    assert result['data'] == native._redact(case['body'], TOKEN)
    assert len(requests) == 1 and not replies
    request = requests[0]
    assert request.method == case['method'] and request.url.path == case['path']
    assert request.headers['Accept'] == 'application/json'
    values = instance.config.config.model_dump(exclude={'operation'}, exclude_none=True)
    if case['operation'] in ('get_recipient','update_recipient','delete_recipient'):
        values.pop('recipient_id')
    if case['operation'] in ('get_message_template','update_message_template','delete_message_template'):
        values.pop('message_template_id')
    if case['operation'] in ('track_order','list_order_items','cancel_order'):
        values.pop('order_id')
    if case['operation'] in ('get_mailing_list','delete_mailing_list','list_recipients'):
        values.pop('mailing_list_id')
    if request.method == 'GET':
        assert dict(request.url.params) == {k: str(v) for k, v in values.items()}
        assert request.content == b''
    elif values:
        assert json.loads(request.content) == values
    else:
        assert request.content == b''


@pytest.mark.asyncio
async def test_connection_shows_account_specific_lists(transport):
    requests, replies = transport
    replies.append(httpx.Response(200, json={'data':[{'id':3019,'description':'Test Mailing List','api_key':'must-not-leak'}]}))
    evidence = await collect_evidence(node_type='automation-thanks-io', credential_data=AUTH,
        user_id='00000000-0000-4000-8000-000000000001')
    assert evidence.reachable is True
    assert 'Test Mailing List' in str(evidence)
    assert 'must-not-leak' not in str(evidence)
    assert len(requests) == 1 and requests[0].method == 'GET'


@pytest.mark.asyncio
@pytest.mark.parametrize('code', [401,403,422,429,500])
async def test_provider_rejection_preserves_message_and_redacts_secrets(transport, code):
    requests, replies = transport
    replies.append(httpx.Response(code, json={'status':'failed','errors':['Unauthorized',TOKEN],'api_key':'private'}))
    result = await node({'operation':'list_mailing_lists'}).execute({})
    assert result['success'] is False and result['http_status'] == code
    assert 'Unauthorized' in str(result) and TOKEN not in str(result) and 'private' not in str(result)
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_http_200_error_envelope_is_not_success(transport):
    transport[1].append(httpx.Response(200,json={'status':'failed','errors':['Invalid address']}))
    result = await node({'operation':'list_mailing_lists'}).execute({})
    assert result['status'] == 'error' and result['success'] is False


@pytest.mark.asyncio
@pytest.mark.parametrize('reply',[httpx.Response(200,text='<html>bad</html>'),httpx.Response(200,json=[]),httpx.Response(200,json={}),httpx.Response(302,headers={'Location':'https://foreign.test'})])
async def test_unexpected_response_and_redirect_not_followed(transport, reply):
    transport[1].append(reply)
    with pytest.raises(ValueError):
        await node({'operation':'list_mailing_lists'}).execute({})
    assert len(transport[0]) == 1


@pytest.mark.asyncio
async def test_send_timeout_never_retries(transport):
    transport[1].append(httpx.ReadTimeout('private '+TOKEN))
    config=next(c['config'] for c in CASES if c['operation']=='send_postcard')
    with pytest.raises(ValueError, match='inspect orders') as error:
        await node({'operation':'send_postcard',**config}).execute({})
    assert TOKEN not in str(error.value) and len(transport[0]) == 1


@pytest.mark.parametrize('config',[
    {'operation':'get_recipient','recipient_id':'../x'},
    {'operation':'get_mailing_list','mailing_list_id':0},
    {'operation':'list_order_items','order_id':1,'per_page':101},
    {'operation':'create_recipient','mailing_list_id':1},
    {'operation':'update_recipient','recipient_id':1},
    {'operation':'update_message_template','message_template_id':1},
    {'operation':'send_postcard','mailing_list_ids':[1]},
    {'operation':'custom_request'},
])
def test_invalid_inputs_fail_before_transport(transport,config):
    with pytest.raises(ValueError):
        node(config)
    assert transport[0] == []


@pytest.mark.parametrize('auth',[
    {**AUTH,'credential_type':'other_api_key'},
    {**AUTH,'api_key':'Bearer token-value'},
    {**AUTH,'api_key':'https://example.com/key'},
    {**AUTH,'api_key':'<token>'},
])
def test_invalid_credentials_fail_before_transport(transport,auth):
    with pytest.raises(ValueError):
        node({'operation':'list_mailing_lists'},auth)
    assert transport[0] == []
