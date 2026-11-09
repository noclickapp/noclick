"""Factory-level request tests and stateful polls; HTTP is always mocked."""
import base64
import hashlib
import hmac
import json
from copy import deepcopy
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import smsglobal_node as sms
from nodes.core.registry import NodeFactory
from nodes.core.run_op import run_node_operation
from utils import ssrf

AUTH = {"credential_type": "smsglobal_api_key", "api_key": "fixture-key", "api_secret": "fixture-secret"}
USER = "00000000-0000-4000-8000-000000000001"


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))

    async def send(request):
        requests.append(request)
        assert request.url.host == "api.smsglobal.com"
        assert request.headers['Authorization'].startswith('MAC id="fixture-key", ts="')
        assert AUTH['api_secret'] not in str(request.headers)
        assert AUTH['api_key'] not in str(request.url)
        code, data = replies.pop(0)
        return httpx.Response(code, content=data) if isinstance(data, bytes) else httpx.Response(code, json=data)

    native = ssrf.guarded_async_client
    monkeypatch.setattr(sms, "guarded_async_client", lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(operation, arguments=None):
    return await run_node_operation(node_type="automation-smsglobal", operation=operation,
        arguments=arguments or {}, credential_data=deepcopy(AUTH), user_id=USER)


# Routes and payloads are independent expectations from the pinned v2 contract.
CASES = [
    ("send_sms", {"destination": "61433111222", "message": "Hello", "origin": "NoClick"}, "POST", "/v2/sms", {"messages": [{"destination": "61433111222", "message": "Hello", "origin": "NoClick"}]}),
    ("list_outgoing_messages", {"start_date": "2020-09-16 16:51:59", "status": "delivered"}, "GET", "/v2/sms", None),
    ("get_outgoing_message", {"message_id": 12}, "GET", "/v2/sms/12", None),
    ("delete_scheduled_message", {"message_id": 12}, "DELETE", "/v2/sms/scheduled/12", None),
    ("list_incoming_messages", {}, "GET", "/v2/sms-incoming", None),
    ("get_incoming_message", {"message_id": 12}, "GET", "/v2/sms-incoming/12", None),
    ("list_groups", {}, "GET", "/v2/group", None),
    ("get_group", {"group_id": 12}, "GET", "/v2/group/12", None),
    ("create_group", {"name": "Customers", "is_global": False}, "POST", "/v2/group", {"name": "Customers", "isGlobal": False}),
    ("update_group", {"group_id": 12, "name": "Customers"}, "PATCH", "/v2/group/12", {"name": "Customers"}),
    ("delete_group", {"group_id": 12}, "DELETE", "/v2/group/12", None),
    ("list_contacts", {"group_id": 12, "sort": "-id"}, "GET", "/v2/group/12/contacts", None),
    ("get_contact", {"contact_id": 12}, "GET", "/v2/contact/12", None),
    ("create_contact", {"group_id": 12, "msisdn": "61433111222", "given_name": "Sam"}, "POST", "/v2/group/12/contact", {"msisdn": "61433111222", "givenName": "Sam"}),
    ("update_contact", {"contact_id": 12, "msisdn": "61433111222", "display_name": "Sam"}, "PUT", "/v2/contact/12", {"msisdn": "61433111222", "displayName": "Sam"}),
    ("delete_contact", {"contact_id": 12}, "DELETE", "/v2/contact/12", None),
    ("list_opt_outs", {"phone_number": 61433111222}, "GET", "/v2/opt-outs", None),
    ("opt_out_numbers", {"optouts": ["61433111222"]}, "POST", "/v2/opt-outs", {"optouts": ["61433111222"]}),
    ("validate_opt_outs", {"optouts": ["61433111222"]}, "POST", "/v2/opt-outs/validate", {"optouts": ["61433111222"]}),
    ("opt_in_number", {"number": 61433111222}, "DELETE", "/v2/opt-outs/61433111222", None),
    ("get_contact_details", {}, "GET", "/v2/user/contact-details", None),
    ("get_credit_balance", {}, "GET", "/v2/user/credit-balance", None),
    ("list_dedicated_numbers", {}, "GET", "/v2/dedicated-number", None),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,arguments,method,path,body", CASES)
async def test_all_actions(transport, operation, arguments, method, path, body):
    requests, replies = transport
    replies.append((204, b"") if method in {"DELETE", "PUT", "PATCH"} or operation == "opt_out_numbers" else (200, {"id": 12}))
    output = await run(operation, arguments)
    assert output['status'] == 'success'
    assert len(requests) == 1 and not replies
    request = requests[0]
    assert request.method == method and request.url.path == path
    assert (json.loads(request.content) if request.content else None) == body
    if operation == "list_outgoing_messages":
        assert request.url.params['startDate'] == "2020-09-16 16:51:59"
        assert request.url.params['status'] == "delivered"
        assert request.url.params['offset'] == '1'
    if operation == "list_opt_outs":
        assert request.url.params['phoneNumber'] == '61433111222'


def test_mac_covers_exact_encoded_uri_and_final_empty_line():
    url = httpx.URL("https://api.smsglobal.com/v2/sms", params={"search": "a & b", "offset": 1})
    expected = '1325376000\nrandom-string\nGET\n/v2/sms?search=a+%26+b&offset=1\napi.smsglobal.com\n443\n\n'
    digest = base64.b64encode(hmac.new(b'fixture-secret', expected.encode(), hashlib.sha256).digest()).decode()
    assert sms.mac_header(sms.SMSGlobalCredential(**AUTH), 'GET', url, timestamp=1325376000, nonce='random-string') == f'MAC id="fixture-key", ts="1325376000", nonce="random-string", mac="{digest}"'


def node(operation, **config):
    return NodeFactory.create_node(node_id='smsglobal-test', node_type='automation-smsglobal',
        node_data={'config': {'operation': operation, 'start_date': '2020-09-16 16:51:59', **config}, 'credentials': AUTH})


@pytest.fixture
def message_fixture():
    return json.loads((__import__('pathlib').Path(__file__).parent / 'fixtures/smsglobal/messages.json').read_text())


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', ['on_new_incoming_message', 'on_new_or_updated_outgoing_message'])
async def test_polls_baseline_new_item_status_change_and_agent_context(transport, monkeypatch, message_fixture, operation):
    requests, replies = transport
    instance = node(operation)
    state = {}

    async def update(mutator, **kwargs):
        updated, result = mutator(deepcopy(state))
        if updated is not None:
            state.clear()
            state.update(updated)
        return result

    monkeypatch.setattr(instance, '_update_node_state', update)
    row = deepcopy(message_fixture['incoming' if operation == 'on_new_incoming_message' else 'outgoing'])
    def queue(rows): replies.append((200, {'messages': deepcopy(rows), 'total': len(rows), 'offset': 1, 'limit': 500}))
    queue([row])
    assert (await instance.execute({}))['messages'] == []
    assert instance.trigger_produced_no_event({})
    queue([row, {**row, 'id': row['id'] + 1}])
    out = await instance.execute({})
    assert len(out['messages']) == 1
    text = instance.resolve_agent_event(out)['text']
    for field in ['origin', 'destination', 'message', 'dateTime']:
        assert str(row[field]) in text
    assert instance.trigger_emitted_event(out)
    queue([row, {**row, 'id': row['id'] + 1}])
    assert (await instance.execute({}))['messages'] == []
    if operation != 'on_new_incoming_message':
        queue([{**row, 'status': 'Delivered'}])
        out = await instance.execute({})
        assert len(out['messages']) == 1 and 'Delivered' in instance.resolve_agent_event(out)['text']
    assert all(r.url.params['startDate'] == '2020-09-16 16:51:59' for r in requests)


@pytest.mark.asyncio
async def test_poll_reads_every_page_before_updating_state(transport, monkeypatch, message_fixture):
    requests, replies = transport
    instance = node('on_new_incoming_message', destination=61499057767)
    row = message_fixture['incoming']
    replies.extend([(200, {'messages': [row], 'total': 2}), (200, {'messages': [{**row, 'id': row['id']+1}], 'total': 2})])
    unseen = AsyncMock(side_effect=lambda rows, key: rows)
    monkeypatch.setattr(instance, '_filter_unseen', unseen)
    assert len((await instance.execute({}))['messages']) == 2
    assert [r.url.params['offset'] for r in requests] == ['1', '2']
    assert all(r.url.params['destination'] == '61499057767' for r in requests)
    assert unseen.await_count == 1


@pytest.mark.asyncio
async def test_poll_rejects_incomplete_or_oversized_snapshot(transport, monkeypatch):
    _, replies = transport
    instance = node('on_new_incoming_message')
    unseen = AsyncMock()
    monkeypatch.setattr(instance, '_filter_unseen', unseen)
    for payload in [{'messages': [], 'total': 10000}, {'messages': [], 'total': 1}, {'messages': [{}], 'total': 1}]:
        replies.append((200, payload))
        with pytest.raises(ValueError): await instance.execute({})
    unseen.assert_not_awaited()


@pytest.mark.asyncio
async def test_provider_rejection_and_secret_redaction(transport):
    _, replies = transport
    replies.append((401, {'message': 'Invalid key fixture-key and fixture-secret'}))
    with pytest.raises(ValueError) as exc: await run('get_contact_details')
    assert '401' in str(exc.value) and 'Invalid key' in str(exc.value)
    assert 'fixture-key' not in str(exc.value) and 'fixture-secret' not in str(exc.value)


@pytest.mark.parametrize('config', [
    {'operation':'get_contact','contact_id':'../other'},
    {'operation':'list_outgoing_messages','offset':9990,'limit':20},
    {'operation':'list_incoming_messages','start_date':'yesterday'},
    {'operation':'send_sms','destination':'1234','message':'hello','origin':'NoClick','shared_pool':'test'},
])
def test_invalid_config_is_rejected(config):
    assert not sms.SMSGlobalNode.validate_config({'config':config,'credentials':AUTH})['valid']


def test_manual_credential_defaults():
    assert sms.SMSGlobalCredential(api_key='fixture-key',api_secret='fixture-secret').credential_type == 'smsglobal_api_key'


@pytest.mark.asyncio
async def test_sdk_decimal_string_ids_and_list_without_total(transport, monkeypatch, message_fixture):
    _, replies = transport
    instance = node('on_new_or_updated_outgoing_message')
    row = {**message_fixture['outgoing'], 'id': '123'}
    replies.append((200, {'messages': [row]}))
    monkeypatch.setattr(instance, '_filter_unseen', AsyncMock(side_effect=lambda rows, key: rows))
    result = await instance.execute({})
    assert result['messages'] == [row]
