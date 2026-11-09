"""Offline regressions for Atlas's published v1 routes and response semantics."""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import atlas_ai_revenue_engine_node as atlas
from nodes.core.registry import NodeFactory

TOKEN = 'atlas-synthetic-api-key-42'
CONTACT = {'firstName': 'Ada', 'lastName': 'Lovelace', 'phoneNumber': '+14155552671'}
FIXTURES = Path(__file__).parent / 'fixtures' / 'atlas-ai-revenue-engine'


def node(config):
    return NodeFactory.create_node(node_id='atlas-fixture', node_type=atlas.AtlasAIRevenueEngineNode.integration_type,
        node_data={'config': config, 'credentials': {'credential_type': 'atlas_ai_revenue_engine_api_key', 'api_key': TOKEN}})


def transport(monkeypatch, payload, status=200):
    requests = []
    real_client = httpx.AsyncClient
    def handler(request):
        requests.append(request)
        return httpx.Response(status, json=payload)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return real_client(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(atlas.httpx, 'AsyncClient', client)
    return requests


# Independent route expectations, so an accidental catalog edit changes a request test.
CASES = [
    ({'operation': 'get_profile'}, 'GET', '/account/profile', None),
    ({'operation': 'list_campaigns'}, 'GET', '/campaign', None),
    ({'operation': 'get_campaign', 'campaign_id': 'campaign-1'}, 'GET', '/campaign/campaign-1', None),
    ({'operation': 'set_campaign_status', 'campaign_id': 'campaign-1', 'enabled': False}, 'PUT', '/campaign/campaign-1/status', {'enabled': False}),
    ({'operation': 'delete_campaign', 'campaign_id': 'campaign-1'}, 'DELETE', '/campaign/campaign-1', None),
    ({'operation': 'list_contacts', 'campaign_id': 'campaign-1'}, 'GET', '/contactlist/campaign-1', None),
    ({'operation': 'get_contact', 'campaign_id': 'campaign-1', 'contact_id': 'contact-1'}, 'GET', '/contactlist/campaign-1/contact-1', None),
    ({'operation': 'create_contacts', 'contacts': [CONTACT]}, 'POST', '/contactlist/contactlistmanual', {'contacts': [CONTACT]}),
    ({'operation': 'update_contact', 'campaign_id': 'campaign-1', 'contact_id': 'contact-1', 'contact': CONTACT}, 'PUT', '/contactlist/campaign-1/contact-1', CONTACT),
    ({'operation': 'delete_contact', 'campaign_id': 'campaign-1', 'contact_id': 'contact-1'}, 'DELETE', '/contactlist/campaign-1/contact-1', None),
    ({'operation': 'schedule_call', 'campaign_id': 'campaign-1', 'customer_phone_number': '+14155552671', 'customer_name': 'Ada'}, 'POST', '/campaign/createSchedule', {'campaignId': 'campaign-1', 'customerPhoneNumber': '+14155552671', 'customerName': 'Ada', 'respectCampaignSchedule': False}),
    ({'operation': 'list_calls', 'campaign_id': 'campaign-1', 'assistant_id': 'agent-1', 'success_result': 'true'}, 'GET', '/call', None),
    ({'operation': 'get_call', 'call_id': 'call-1'}, 'GET', '/call/call-1', None),
    ({'operation': 'delete_call', 'call_id': 'call-1'}, 'DELETE', '/call/call-1', None),
    ({'operation': 'list_scheduled_calls', 'campaign_id': 'campaign-1'}, 'GET', '/call/scheduled/campaign-1', None),
    ({'operation': 'list_bookings', 'campaign_id': 'campaign-1'}, 'GET', '/campaign/campaign-1/bookings', None),
    ({'operation': 'get_campaign_statistics', 'campaign_id': 'campaign-1'}, 'GET', '/call/stats/campaign-1', None),
    ({'operation': 'list_chat_sessions', 'campaign_id': 'campaign-1'}, 'GET', '/campaign-chat/campaign-1', None),
    ({'operation': 'list_chat_messages', 'session_id': 'session-1'}, 'GET', '/campaign-chat/sessions/session-1/messages', None),
    ({'operation': 'schedule_sms', 'campaign_id': 'campaign-1', 'customer_phone_number': '+14155552671', 'customer_name': 'Ada', 'custom_message': 'Hello'}, 'POST', '/campaign-chat/campaign-1/sessions/sms/schedule', {'customerPhoneNumber': '+14155552671', 'customerName': 'Ada', 'customMessage': 'Hello', 'respectCampaignSchedule': False}),
    ({'operation': 'send_human_response', 'campaign_id': 'campaign-1', 'session_id': 'session-1', 'message': 'Hello'}, 'POST', '/campaign-chat/campaign-1/send-human-response', {'sessionId': 'session-1', 'message': 'Hello'}),
    ({'operation': 'set_human_handoff', 'campaign_id': 'campaign-1', 'contact_identifier': '+14155552671', 'enabled': True}, 'POST', '/campaign-chat/campaign-1/contacts/%2B14155552671/human-handoff', {'enabled': True}),
    ({'operation': 'list_agents'}, 'GET', '/agent', None),
    ({'operation': 'list_phone_numbers'}, 'GET', '/phone-number', None),
    ({'operation': 'get_quota'}, 'GET', '/customer-quota', None),
]


@pytest.mark.asyncio
@pytest.mark.parametrize('config,method,path,body', CASES, ids=[c[0]['operation'] for c in CASES])
async def test_atlas_ai_revenue_engine_actual_requests(monkeypatch, config, method, path, body):
    payload = {'processed': [{'RowKey': 'contact-1'}], 'invalid': []} if config['operation'] == 'create_contacts' else {'value': [{'RowKey': 'owned-1', 'name': 'Owned record'}]}
    requests = transport(monkeypatch, payload)
    instance = node(config)
    instance.emit = AsyncMock()
    output = await instance.execute({})
    assert output['data'] == payload and output['status'] == 'success'
    instance.emit.assert_awaited_once_with(output)
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert request.url.host == 'api.youratlas.com'
    assert request.url.raw_path.split(b'?')[0] == ('/v1/api' + path).encode()
    assert request.headers['api-key'] == TOKEN
    assert (json.loads(request.content) if request.content else None) == body
    if config['operation'] == 'list_calls':
        assert dict(request.url.params) == {'campaignId': 'campaign-1', 'assistantId': 'agent-1', 'successResult': 'true'}
    else:
        assert not request.url.query


@pytest.mark.asyncio
@pytest.mark.parametrize('fixture,status', [('contacts-accepted.json', 'success'), ('contacts-partial.json', 'partial'), ('contacts-rejected.json', 'error')])
async def test_atlas_ai_revenue_engine_contact_rejections(monkeypatch, fixture, status):
    payload = json.loads((FIXTURES / fixture).read_text())
    transport(monkeypatch, payload)
    result = await node({'operation': 'create_contacts', 'contacts': [CONTACT]}).execute({})
    assert result['status'] == status and result['data'] == payload
    if status != 'success':
        assert result['success'] is False


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [302, 400, 401, 403, 429, 500])
async def test_atlas_ai_revenue_engine_errors_redact_and_never_retry(monkeypatch, status):
    requests = transport(monkeypatch, {'error': {'message': 'Rejected ' + TOKEN}}, status)
    with pytest.raises(ValueError) as error:
        await node({'operation': 'get_profile'}).execute({})
    assert str(status) in str(error.value) and TOKEN not in str(error.value)
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_atlas_ai_revenue_engine_error_envelope_and_secret_echo(monkeypatch):
    transport(monkeypatch, {'error': {'message': 'Refused ' + TOKEN}})
    with pytest.raises(ValueError, match='Refused'):
        await node({'operation': 'get_profile'}).execute({})
    # Restore before replacing the mock client again.
    monkeypatch.undo()
    transport(monkeypatch, {'user_metadata': {'full_name': TOKEN}})
    result = await node({'operation': 'get_profile'}).execute({})
    assert TOKEN not in str(result)


def test_atlas_ai_revenue_engine_manual_credential_and_schema():
    cred = atlas.AtlasAIRevenueEngineAPIKeyCredential(api_key=TOKEN)
    assert cred.credential_type == 'atlas_ai_revenue_engine_api_key'
    for key in ['https://example.com/key', ' bad key ', 'x\r\nInjected: true']:
        with pytest.raises(ValidationError):
            atlas.AtlasAIRevenueEngineAPIKeyCredential(api_key=key)
    for config in [dict(operation='schedule_call', campaign_id='c', customer_name='A', customer_phone_number='123'), dict(operation='set_campaign_status', campaign_id='c'), dict(operation='update_contact', campaign_id='c', contact_id='a', contact={'firstName':'Ada'})]:
        with pytest.raises(ValueError): node(config)
    assert len(atlas.ROUTES) == len(CASES) == 25


@pytest.mark.asyncio
async def test_atlas_ai_revenue_engine_custom_contacts_and_timed_call(monkeypatch):
    requests = transport(monkeypatch, {'processed': [{'RowKey': 'x'}], 'invalid': []})
    contact = {**CONTACT, 'appointmentDate': 'May 15'}
    await node({'operation': 'create_contacts', 'campaign_id': 'c', 'contacts': [contact]}).execute({})
    assert json.loads(requests[0].content) == {'campaignId': 'c', 'contacts': [contact]}
    monkeypatch.undo()
    requests = transport(monkeypatch, {'sequenceNumber': 1})
    await node({'operation': 'schedule_call', 'campaign_id': 'c', 'customer_name': 'Ada', 'customer_phone_number': CONTACT['phoneNumber'], 'scheduled_date': '2027-05-15T10:00:00Z', 'respect_campaign_schedule': True}).execute({})
    assert json.loads(requests[0].content)['scheduledDate'] == '2027-05-15T10:00:00Z'


@pytest.mark.asyncio
async def test_atlas_ai_revenue_engine_empty_write_response(monkeypatch):
    transport(monkeypatch, {})
    result = await node({'operation': 'set_human_handoff', 'campaign_id': 'c', 'contact_identifier': 'ada@example.com', 'enabled': False}).execute({})
    assert result['status'] == 'success' and result['data'] == {}


def test_atlas_ai_revenue_engine_path_boundaries():
    for identifier in ['.', '..', 'bad\nsegment']:
        config = atlas.GetCampaignConfig(campaign_id=identifier)
        with pytest.raises(ValueError): atlas.build_request(config)
    _, path, _, _ = atlas.build_request(atlas.GetCampaignConfig(campaign_id='abc/?#%'))
    assert path == '/campaign/abc%2F%3F%23%25'


def test_atlas_ai_revenue_engine_profile_identity_label():
    from nodes.core.connection_evidence import _identity_label
    spec = atlas.AtlasAIRevenueEngineNode.connection_evidence
    assert _identity_label({'user_metadata': {'full_name': 'Ada Lovelace', 'company': 'Analytical Engines'}}, spec.identity_keys) == 'Ada Lovelace'
