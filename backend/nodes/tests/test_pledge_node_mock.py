"""Pledge request and trigger regression checks against its published contract.

These tests exercise actual HTTP serialization and the primary-key signature
scheme, including filtering events that belong to another Pledge trigger.
"""
import base64
import hashlib
import hmac
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes.core.registry import NodeFactory
from nodes.pledge_node import PledgeNode, PledgeAPIKeyCredential, TOPICS

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/pledge/published.json').read_text())
CREDENTIAL = {"credential_type": "pledge_api_key", "api_key": "pledge-test-primary-key"}
ORG = FIXTURE['organization_id']
DONATION = {**FIXTURE['donation_field_examples'], 'organization_id': ORG}
CALCULATOR = {"name": "Clean Water", "icon": "clean-water", "color": "#443a4a", "formula": "organization_amount", "description": "people provided with clean drinking water for one year"}
FUNDRAISER = {"name": "Spring Charity Gala", "organization_ids": [ORG]}


def node(config):
    n = NodeFactory.create_node(node_id='pledge-test', node_type='automation-pledge',
        node_data={'config': config, 'credentials': CREDENTIAL})
    n.emit = AsyncMock()
    return n


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,method,path,fields', [
    ('list_donations', 'GET', '/donations', {'page': 2}),
    ('create_donation', 'POST', '/donations', {k: DONATION[k] for k in ('email', 'first_name', 'last_name', 'amount', 'organization_id')}),
    ('get_donation', 'GET', '/donations/' + DONATION['id'], {'id': DONATION['id']}),
    ('create_fundraiser', 'POST', '/fundraisers', FUNDRAISER),
    ('get_fundraiser', 'GET', '/fundraisers/9IEgDGbG9gMAEgFoKSvSpg', {'id': '9IEgDGbG9gMAEgFoKSvSpg'}),
    ('update_fundraiser', 'PATCH', '/fundraisers/9IEgDGbG9gMAEgFoKSvSpg', {'id': '9IEgDGbG9gMAEgFoKSvSpg', **FUNDRAISER}),
    ('place_fundraiser', 'PUT', '/fundraisers/9IEgDGbG9gMAEgFoKSvSpg', {'id': '9IEgDGbG9gMAEgFoKSvSpg', **FUNDRAISER}),
    ('list_impact_calculators', 'GET', '/impact_calculators', {'page': 2}),
    ('get_impact_calculator', 'GET', '/impact_calculators/AU9puRFzeJbU_EdMLoqwsA', {'id': 'AU9puRFzeJbU_EdMLoqwsA'}),
    ('create_impact_calculator', 'POST', '/impact_calculators', CALCULATOR),
    ('update_impact_calculator', 'PATCH', '/impact_calculators/AU9puRFzeJbU_EdMLoqwsA', {'id': 'AU9puRFzeJbU_EdMLoqwsA', **CALCULATOR}),
    ('search_organizations', 'GET', '/organizations', {'q': 'Red Cross', 'ngo_id': '53-0196605'}),
    ('request_organization', 'POST', '/organizations', {'ngo_id': '53-0196605'}),
    ('get_organization', 'GET', '/organizations/' + ORG, {'id': ORG}),
    ('list_webhooks', 'GET', '/webhooks', {'page': 2}),
    ('create_webhook', 'POST', '/webhooks', {'url': 'https://www.yourwebsite.com/webhook'}),
    ('get_webhook', 'GET', '/webhooks/8111970d-4047-4a45-b552-fbd7c7af922c', {'id': '8111970d-4047-4a45-b552-fbd7c7af922c'}),
    ('delete_webhook', 'DELETE', '/webhooks/8111970d-4047-4a45-b552-fbd7c7af922c', {'id': '8111970d-4047-4a45-b552-fbd7c7af922c'}),
])
async def test_pledge_wire(monkeypatch, operation, method, path, fields):
    async def request(self, actual_method, url, **kwargs):
        assert actual_method == method
        assert url == 'https://api.pledge.to/v1' + path
        assert kwargs['headers']['Authorization'] == 'Bearer ' + CREDENTIAL['api_key']
        if method == 'GET':
            assert kwargs['json'] is None
            assert all(kwargs['params'][k] == v for k, v in fields.items() if k != 'id')
        elif method in {'POST', 'PATCH', 'PUT'}:
            assert kwargs['json'] == {k: v for k, v in fields.items() if k != 'id'}
        else:
            assert kwargs['json'] is None
        return httpx.Response(204 if method == 'DELETE' else 200, json=None if method == 'DELETE' else {'id': 'provider-result'})
    monkeypatch.setattr(httpx.AsyncClient, 'request', request)
    out = await node({'operation': operation, **fields}).execute({})
    assert out['status'] == 'success'


@pytest.mark.parametrize('operation,event', [
    ('donation/created', {'topic': 'donation/created', 'data': DONATION}),
    ('organization_request/approved', FIXTURE['organization_request_approved']),
    ('organization_request/declined', FIXTURE['organization_request_declined']),
])
def test_pledge_signed_events(operation, event):
    body = json.dumps(event).encode()
    signature = base64.b64encode(hmac.new(CREDENTIAL['api_key'].encode(), body, hashlib.sha256).digest()).decode()
    config = {'operation': 'on_event', 'event_type': operation, 'signing_secret': CREDENTIAL['api_key']}
    assert PledgeNode.verify_webhook_signature(body, {'Pledgeling-Signature': signature}, config)
    assert not PledgeNode.verify_webhook_signature(body + b' ', {'Pledgeling-Signature': signature}, config)
    assert not PledgeNode.verify_webhook_signature(body, {}, config)
    assert not PledgeNode.verify_webhook_signature(body, {'Pledgeling-Signature': signature}, {})
    assert PledgeNode.filter_trigger_payload(event, config)
    for other in set(TOPICS) - {operation}:
        assert not PledgeNode.filter_trigger_payload(event, {'operation': 'on_event', 'event_type': other})
    output = PledgeNode.resolve_trigger_payload(event, config)
    turn = PledgeNode.resolve_agent_event(output)
    assert turn['text'] and turn['conversation_key']
    assert event['data'].get('id', event['data'].get('ngo_id')) in turn['text']


@pytest.mark.asyncio
async def test_pledge_register_and_unregister(monkeypatch):
    calls = []
    async def request(cred, method, path, **kwargs):
        calls.append((method, path, kwargs))
        return {'id': '8111970d-4047-4a45-b552-fbd7c7af922c'}
    monkeypatch.setattr(PledgeNode, '_request', request)
    state = await PledgeNode._register_external_webhook(webhook_url='https://www.yourwebsite.com/webhook',
        credential=CREDENTIAL, config={'operation': 'on_event'}, node_id='test')
    assert state['signing_secret'] == CREDENTIAL['api_key']
    await PledgeNode._unregister_external_webhook(credential=CREDENTIAL, config=state, node_id='test')
    assert calls == [('POST', '/webhooks', {'body': {'url': 'https://www.yourwebsite.com/webhook'}}),
                     ('DELETE', '/webhooks/8111970d-4047-4a45-b552-fbd7c7af922c', {})]


@pytest.mark.asyncio
async def test_pledge_error_redacts_key_and_never_retries(monkeypatch):
    requests = []
    async def request(self, method, url, **kwargs):
        requests.append(url)
        return httpx.Response(401, text='Invalid key ' + CREDENTIAL['api_key'])
    monkeypatch.setattr(httpx.AsyncClient, 'request', request)
    with pytest.raises(ValueError) as error:
        await node({'operation': 'list_donations'}).execute({})
    assert CREDENTIAL['api_key'] not in str(error.value)
    assert '401' in str(error.value)
    assert len(requests) == 1


def test_pledge_manual_credential_has_default_type():
    assert PledgeAPIKeyCredential(api_key=CREDENTIAL['api_key']).credential_type == 'pledge_api_key'
