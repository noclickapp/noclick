"""Channel wire and polling behavior using Zoho's documented log examples."""
import copy
import json
from pathlib import Path
import httpx
import pytest
from nodes import zoho_cpaas_formerly_zeptomail_node as native

FIXTURES = Path(__file__).parent / 'fixtures' / 'zoho-cpaas-formerly-zeptomail'
TOKEN = 'unit-test-channel-key-97531'
ID = '7fff7400-b676-11f1-b0ad-b6d94062a427'


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, channel='sms'):
    parsed = native.ZohoCPaaSNode.parse_config({'config': config, 'credentials': {
        'credential_type': native.FAMILY, 'api_key': TOKEN, 'channel': channel}})
    return native.ZohoCPaaSNode('test-node', native.ZohoCPaaSNode.integration_type, {'config': config}, config=parsed)


def example(channel):
    return json.loads((FIXTURES / (channel + '-logs.json')).read_text())['body']


def mock_http(monkeypatch, response, status=200):
    calls = []
    original = httpx.AsyncClient
    def respond(request):
        calls.append(request)
        return httpx.Response(status, json=response(request) if callable(response) else response)
    monkeypatch.setattr(native.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize('channel,operation', [('sms', 'get_sms_logs'), ('voice', 'get_voice_logs'), ('whatsapp', 'get_whatsapp_logs')])
async def test_read_logs_exact_filters_and_key(monkeypatch, channel, operation):
    calls = mock_http(monkeypatch, example(channel))
    out = await node({'operation': operation, 'offset': 20, 'limit': 10, 'client_reference': 'ref + value', 'date_from': '2026-09-22T00:00:00+05:30'}).execute({})
    assert out['data'] == example(channel)['data']
    req = calls[0]
    assert req.url.path == '/v1.1/' + channel + '/logs'
    assert req.headers['authorization'] == 'Zoho-enczapikey ' + TOKEN
    assert req.url.params['client_reference'] == 'ref + value'
    assert req.url.params['date_from'] == '2026-09-22T00:00:00+05:30'
    assert req.url.params['offset'] == '20'


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,path', [('get_sms_message_details','sms'),('get_whatsapp_message_details','whatsapp'),('get_voice_call_details','voice')])
async def test_detail_ids_are_path_parameters(monkeypatch, operation, path):
    calls = mock_http(monkeypatch, {'data': {'message_id': ID}, 'status':'success'})
    await node({'operation':operation,'message_id':ID}).execute({})
    assert calls[0].url.path == '/v1.1/' + path + '/logs/' + ID
    assert not calls[0].url.query


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,path', [('send_email','/email'),('send_batch_emails','/email/batch'),('send_email_using_template','/email/template'),('send_batch_emails_using_template','/email/template/batch')])
async def test_email_bodies_and_template_selection(monkeypatch, operation, path):
    fixture = {'/email':'email-sending','/email/batch':'batch-email-sending','/email/template':'email-templates','/email/template/batch':'batch-email-templates'}[path]
    calls = mock_http(monkeypatch, json.loads((FIXTURES / (fixture + '.json')).read_text())['body'])
    config = {'operation':operation, 'from_address':'accounts@info.zylker.com', 'to_json':json.dumps([{'email_address':{'address':'rudra.d@zylker.com'}}]), 'track_opens':False}
    if 'template' in operation:
        config['template_key'] = '1234567890'
    else:
        config.update(subject='Account Confirmation', textbody='Hello')
    await node(config, channel='email').execute({})
    req = calls[0]; body = json.loads(req.content)
    assert req.method == 'POST' and req.url.path == '/v1.1' + path
    assert body['from'] == {'address':'accounts@info.zylker.com'}
    assert body['to'] == [{'email_address':{'address':'rudra.d@zylker.com'}}]
    assert body['track_opens'] is False
    assert 'operation' not in body and 'to_json' not in body


@pytest.mark.asyncio
async def test_sms_single_recipient_and_merge_json(monkeypatch):
    calls = mock_http(monkeypatch, {'data': {'message_id': ID}, 'status':'success'})
    await node({'operation':'send_sms','sender_key':'2d6f4a1b9c35','recipient':'+919876543210','template_alias':'otp','merge_info_json':'{"otp":"482913"}'}).execute({})
    assert json.loads(calls[0].content) == {'sender_key':'2d6f4a1b9c35','to':[{'mobile_no':'+919876543210'}],'template_alias':'otp','merge_info':{'otp':'482913'}}


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', ['send_voice_call','send_whatsapp_message'])
async def test_phone_body_aliases(monkeypatch, operation):
    calls = mock_http(monkeypatch, {'data':{'message_id':ID},'status':'success'})
    config = {'operation':operation,'from_number':'+14155550142','to_number':'+919876543210'}
    config.update({'message_content':'Your appointment is confirmed'} if operation == 'send_voice_call' else {'template_alias':'otp'})
    await node(config).execute({})
    body = json.loads(calls[0].content)
    assert body['from'] == config['from_number'] and body['to'] == config['to_number']
    assert 'from_number' not in body and 'to_number' not in body


@pytest.mark.asyncio
@pytest.mark.parametrize('channel', ['sms', 'whatsapp', 'voice'])
async def test_poll_baseline_new_changed_dedup_and_agent_event(monkeypatch, channel):
    payload = example(channel)
    mock_http(monkeypatch, lambda _: payload)
    n = node({'operation':'on_' + channel + '_activity'})
    state = {}
    async def update(mutator, **kwargs):
        changed, result = mutator(copy.deepcopy(state))
        if changed is not None:
            state.clear(); state.update(changed)
        return result
    n._update_node_state = update
    assert (await n.execute({}))['event_count'] == 0
    payload['data'][0]['status'] = 'CALL_FAILED' if channel == 'voice' else 'undelivered'
    result = await n.execute({})
    assert result['event_count'] == 1
    assert payload['data'][0]['message_id'] in n.resolve_agent_event(result)['text']
    assert payload['data'][0]['to'] in n.resolve_agent_event(result)['text']
    assert (await n.execute({}))['event_count'] == 0
    payload['data'][0]['message_id'] = ID if payload['data'][0]['message_id'] != ID else '6200ca60-921a-11f1-92c4-2a30dd3b833c'
    assert (await n.execute({}))['event_count'] == 1


@pytest.mark.asyncio
async def test_poll_complete_pages_before_checkpoint_and_refuses_truncation(monkeypatch):
    base = example('sms')['data'][0]
    def page(request):
        return {'data':[dict(base) for _ in range(100)] if request.url.params['offset'] == '0' else [], 'status':'success'}
    calls = mock_http(monkeypatch, page)
    n = node({'operation':'on_sms_activity','client_reference':'otp-482913'})
    async def unseen(rows, id_fn): return rows
    n._filter_unseen = unseen
    assert (await n.execute({}))['event_count'] == 100
    assert [r.url.params['offset'] for r in calls] == ['0','100']
    # No state is touched if the complete bounded scan cannot finish.
    monkeypatch.undo()
    mock_http(monkeypatch, {'data':[dict(base) for _ in range(100)], 'status':'success'})
    async def forbidden(*args): raise AssertionError('must not checkpoint truncated scan')
    n._filter_unseen = forbidden
    with pytest.raises(ValueError, match='2,000'):
        await n.execute({})


@pytest.mark.asyncio
async def test_connection_evidence_uses_key_channel_and_email_has_no_probe(monkeypatch):
    calls = mock_http(monkeypatch, example('sms'))
    cred = {'api_key':TOKEN, 'channel':'sms'}
    out = await native.ZohoCPaaSNode.load_field_options('activity_id', cred)
    assert out['options'][0]['value'] == example('sms')['data'][0]['message_id']
    assert calls[0].method == 'GET'
    with pytest.raises(ValueError, match='no read-only verification'):
        await native.ZohoCPaaSNode.load_field_options('activity_id', {**cred,'channel':'email'})
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_provider_rejection_and_secret_redaction(monkeypatch):
    mock_http(monkeypatch, {'error':{'message':'Rejected '+TOKEN}}, status=401)
    with pytest.raises(ValueError) as exc:
        await node({'operation':'get_sms_logs'}).execute({})
    assert '401' in str(exc.value) and TOKEN not in str(exc.value) and 'Rejected' in str(exc.value)


@pytest.mark.parametrize('config', [
    {'operation':'send_sms','sender_key':'sender','recipient':'+919876543210'},
    {'operation':'send_sms','sender_key':'sender','recipient':'+919876543210','template_key':ID,'template_alias':'both'},
    {'operation':'get_sms_logs','date_from':'2026-09-22T00:00:00'},
    {'operation':'get_sms_message_details','message_id':'../../secrets'},
    {'operation':'send_email','from_address':'a@b.com','to_json':'{}','subject':'x','textbody':'hello'},
])
def test_invalid_input_rejected(config):
    with pytest.raises(ValueError):node(config)


@pytest.mark.asyncio
async def test_canvas_metadata_is_accepted_without_becoming_api_parameters(monkeypatch):
    calls = mock_http(monkeypatch, example('sms'))
    await node({'operation':'get_sms_logs','goal':'check delivery','label':'My log','operationReason':'follow up','userFields':{},'unexpected_api_parameter':'never send this'}).execute({})
    assert dict(calls[0].url.params) == {'offset':'0','limit':'10'}
