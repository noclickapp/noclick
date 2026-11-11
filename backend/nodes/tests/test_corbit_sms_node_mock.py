"""Replay Corbit's own saved responses at the HTTP boundary, including errors."""
import copy
import json
from pathlib import Path

import httpx
import pytest
import respx
from pydantic import ValidationError

from nodes.corbit_sms_node import CorbitSMSCredential, CorbitSMSNode, ROUTES
from nodes.core.poll_trigger import poll_scope

FIXTURES = Path(__file__).parent / 'fixtures' / 'corbit-sms'
ITEMS = json.loads((FIXTURES / 'postman_examples.json').read_text())['items']
INPUTS = json.loads((FIXTURES / 'inputs.json').read_text())
NAMES = ['send_sms', 'send_bulk_sms', 'get_balance', 'list_sender_names',
         'get_message_status', 'get_message_report', 'list_templates',
         'save_template', 'get_template', 'delete_template', 'send_template',
         'get_usage', 'list_messages']
BY_OP = dict(zip(NAMES, ITEMS, strict=True))


def node(operation, **changes):
    config = {**INPUTS[operation]['config'], **changes}
    data = {'config': config, 'credentials': {'credential_type': 'corbit_sms_api_token', 'api_token': 'corbit-test-secret'}}
    return CorbitSMSNode(node_id='corbit-test', node_type='automation-corbit-sms',
                         node_data=data, config=CorbitSMSNode.parse_config(data))


def url(operation):
    config = INPUTS[operation]['config']
    path = ROUTES[operation][1]
    for key in ('name', 'message_id'):
        if key in config:
            path = path.replace('{' + key + '}', config[key])
    return 'https://api.corbit.sa' + path


CASES = [(name, example) for name, item in BY_OP.items() for example in item['response']]


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,example', CASES, ids=[f'{op}-{ex["code"]}-{i}' for i, (op, ex) in enumerate(CASES)])
async def test_saved_provider_responses(operation, example):
    # Response bytes are copied unchanged from the pinned collection, not
    # synthesized to suit the parser.
    with respx.mock(assert_all_called=True) as router:
        route = router.route(method=ROUTES[operation][0], url=url(operation)).mock(
            return_value=httpx.Response(example['code'], content=example['body'], headers={'Content-Type': 'application/json'}))
        if example['code'] >= 400:
            with pytest.raises(httpx.HTTPStatusError):
                await node(operation).execute({})
        else:
            assert await node(operation).execute({}) == json.loads(example['body'])
        assert route.call_count == 1  # A failed write is never silently retried.
        request = route.calls[0].request
        assert request.headers['Authorization'] == 'Bearer corbit-test-secret'
        if operation in {'send_sms', 'send_bulk_sms'}:
            sent = json.loads(request.content)
            assert sent['senderName'] == 'Mobile.SA'
            assert sent['sendAtOption'] == ('NOW' if operation == 'send_sms' else 'Now')
            assert 'X-Allow-Duplicate' not in request.headers
        elif operation == 'save_template':
            assert json.loads(request.content) == {'text': 'Hello {{name}}, your code is {{code|0000}}'}
        elif operation == 'send_template':
            assert json.loads(request.content) == {'senderName': 'Corbit', 'template': 'otp', 'vars': {'code': '0000'},
                'recipients': [{'number': '201008834539', 'vars': {'name': 'Ali', 'code': '4821'}}]}
        elif operation == 'list_messages':
            assert dict(request.url.params) == {'limit': '50', 'from': '2026-09-01'}
        else:
            assert not request.content


@pytest.mark.asyncio
async def test_explicit_retry_and_duplicate_headers():
    with respx.mock as router:
        route = router.post(url('send_sms')).mock(return_value=httpx.Response(200, content=BY_OP['send_sms']['response'][0]['body']))
        await node('send_sms', allow_duplicate=True, idempotency_key='otp-4821').execute({})
        assert route.calls[0].request.headers['Idempotency-Key'] == 'otp-4821'
        assert route.calls[0].request.headers['X-Allow-Duplicate'] == 'true'


def state_store(instance, state):
    async def update(mutator, **kwargs):
        replacement, result = mutator(copy.deepcopy(state))
        if replacement is not None:
            state.clear()
            state.update(replacement)
        return result
    instance._update_node_state = update


@pytest.mark.asyncio
async def test_poll_baseline_new_item_dedup_and_agent_event():
    payload = json.loads(BY_OP['list_messages']['response'][0]['body'])
    instance = node('on_new_sent_message')
    state = {}
    state_store(instance, state)
    with respx.mock as router:
        route = router.get(url('list_messages')).mock(return_value=httpx.Response(200, json=payload))
        assert (await instance.execute({}))['new_message_count'] == 0
        assert instance.trigger_produced_no_event({})
        # An existing empty baseline now observes the exact documented record.
        state['seen_ids'] = []
        output = await instance.execute({})
        assert output['messages'] == payload['data']['messages']
        assert output['new_message_count'] == 1
        event = CorbitSMSNode.resolve_agent_event(output)
        for text in ('School1', '201008834539', '30be7f80-e587-46ac-a5b3-0f89d21c03dd', '2026-09-24', 'does not include message text'):
            assert text in event['text']
        assert (await instance.execute({}))['messages'] == []
        assert CorbitSMSNode.resolve_agent_event({'messages': []}) is None
        assert dict(route.calls[0].request.url.params) == {'from': '2026-09-01', 'limit': '200'}


@pytest.mark.asyncio
async def test_poll_follows_short_pages_and_refuses_cursor_cycles():
    instance = node('on_new_sent_message', sender='School1', number='2010', include_status=True)
    payload = json.loads(BY_OP['list_messages']['response'][0]['body'])
    # Pagination transport scenarios; the record itself is the published example.
    first = copy.deepcopy(payload)
    first['data']['nextCursor'] = 'next-page'
    state = {'seen_ids': []}
    state_store(instance, state)
    with respx.mock as router:
        route = router.get(url('list_messages')).mock(side_effect=[httpx.Response(200, json=first), httpx.Response(200, json=payload)])
        assert (await instance.execute({}))['new_message_count'] == 1
        query = dict(route.calls[1].request.url.params)
        assert query == {'from': '2026-09-01', 'sender': 'School1', 'number': '2010', 'status': '1', 'limit': '200', 'cursor': 'next-page'}
    untouched = {'seen_ids': []}
    state_store(instance, untouched)
    with respx.mock as router:
        router.get(url('list_messages')).mock(return_value=httpx.Response(200, json=first))
        with pytest.raises(ValueError, match='cursor did not advance'):
            await instance.execute({})
    assert untouched == {'seen_ids': []}


def test_manual_credential_and_poll_scope():
    assert CorbitSMSCredential(api_token=' corbit-secret ').api_token == 'corbit-secret'
    assert CorbitSMSCredential.model_fields['credential_type'].default == 'corbit_sms_api_token'
    for token in ('Bearer abc', 'https://api.corbit.sa/token', 'abc\r\nx: secret'):
        with pytest.raises(ValidationError):
            CorbitSMSCredential(api_token=token)
    a = INPUTS['on_new_sent_message']['config']
    assert poll_scope(CorbitSMSNode, a) == poll_scope(CorbitSMSNode, {**a, 'label': 'Cosmetic'})
    for key, value in [('sender', 'School1'), ('number', '2010'), ('from_time', '2026-09-24'), ('to_time', '2026-09-25'), ('include_status', True)]:
        assert poll_scope(CorbitSMSNode, a) != poll_scope(CorbitSMSNode, {**a, key: value})


@pytest.mark.asyncio
async def test_error_envelope_cannot_be_connection_evidence():
    with respx.mock as router:
        router.get(url('list_sender_names')).mock(return_value=httpx.Response(200, json={'status': 'Error', 'message': 'Token rejected'}))
        with pytest.raises(ValueError, match='Token rejected'):
            await node('list_sender_names').execute({})
