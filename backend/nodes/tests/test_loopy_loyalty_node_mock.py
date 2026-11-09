"""Exercise Loopy Loyalty through the native factory with offline HTTP fixtures.

Fixtures are synthetic contract-shaped records, not claimed live provider data.
Wire assertions cover authentication, pagination and each distinct write payload.
"""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import jwt
import pytest
from pydantic import ValidationError

from nodes import loopy_loyalty_node as ll
from nodes.core.registry import NodeFactory
from nodes.core.run_op import run_node_operation
from utils import ssrf

AUTH = {"credential_type": ll.TYPE, "api_key": "fixture-api-key", "api_secret": "fixture-signing-secret", "username": "fixture-user"}
REPLIES = json.loads((Path(__file__).parent / 'fixtures/loopy-loyalty/responses.json').read_text())
UNIQUE = {"campaign_id": "campaign-1", "unique_id_type": "email", "unique_id_value": "person@example.test"}


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    calls, replies = [], []
    monkeypatch.setattr(ssrf, '_resolve_host_addresses', AsyncMock(return_value=['93.184.216.34']))

    async def send(request):
        calls.append(request)
        claims = jwt.decode(request.headers['Authorization'], AUTH['api_secret'], algorithms=['HS256'])
        assert claims['uid'] == claims['pid'] == AUTH['api_key']
        assert claims['username'] == AUTH['username']
        assert claims['exp'] - claims['iat'] == 60
        assert request.url.host == 'api.loopyloyalty.com'
        code, payload = replies.pop(0)
        return httpx.Response(code, json=payload)

    native = ssrf.guarded_async_client
    monkeypatch.setattr(ll, 'guarded_async_client', lambda **kw: native(**kw, transport=httpx.MockTransport(send)))
    return calls, replies


async def run(operation, **arguments):
    return await run_node_operation(node_type=ll.LoopyLoyaltyNode.integration_type, operation=operation,
        arguments=arguments, credential_data=AUTH, user_id='00000000-0000-4000-8000-000000000001')


CASES = [
    ('list_campaigns', {}, 'GET', '/v1/campaigns', None, 'campaigns'),
    ('get_campaign', {'campaign_id': 'campaign-1'}, 'GET', '/v1/campaign/id/campaign-1', None, 'campaign'),
    ('get_campaign_by_name', {'name': 'Coffee Club'}, 'GET', '/v1/campaign/name/Coffee%20Club', None, 'campaign'),
    ('list_cards', {'campaign_id': 'campaign-1'}, 'POST', '/v1/card/cid/campaign-1', {'cid': 'campaign-1', 'dt': {'start': '0', 'length': '50'}}, 'cards'),
    ('list_events', {'campaign_id': 'campaign-1'}, 'POST', '/v1/events/analytics/transactions/campaign-1', {'cid': 'campaign-1', 'dt': {'start': '0', 'length': '50'}}, 'events'),
    ('get_card', {'card_id': 'card-1'}, 'GET', '/v1/card/card-1', None, 'card'),
    ('get_card_by_unique_id', UNIQUE, 'GET', '/v1/uniquecard/campaignid/campaign-1/email/person%40example.test', None, 'card'),
    ('enrol_customer', {'campaign_id': 'campaign-1', 'customer_data': {'Email': 'person@example.test'}, 'data_consent_opt_in': False, 'time_zone_offset': 480}, 'POST', '/v1/enrol/campaign-1', {'campaignId': 'campaign-1', 'customerData': {'Email': 'person@example.test'}, 'dataConsentOptIn': False, 'timeZoneOffset': '480'}, 'enrol'),
    ('add_stamps', {'card_id': 'card-1', 'stamps': -2, 'scan_latitude': 22.3}, 'POST', '/v1/card/cid/card-1/addStamps/-2', {'cid': 'card-1', 'stamps': '-2', 'scanLatitude': 22.3}, 'success'),
    ('redeem_reward', {'card_id': 'card-1', 'reward_type': 2}, 'POST', '/v1/card/cid/card-1/redeemReward/2/1', {'cid': 'card-1', 'rewardType': '2', 'rewardsToRedeem': '1'}, 'success'),
    ('add_stamps_by_unique_id', {**UNIQUE, 'stamps': 3}, 'POST', '/v1/uniquecard/campaignid/campaign-1/email/person%40example.test/addStamps/3', {'campaignId': 'campaign-1', 'uniqueIdType': 'email', 'uniqueIdValue': 'person@example.test', 'stamps': '3'}, 'success'),
    ('redeem_reward_by_unique_id', {**UNIQUE, 'reward_type': 1, 'rewards_to_redeem': 2}, 'POST', '/v1/uniquecard/campaignid/campaign-1/email/person%40example.test/redeemReward/1/2', {'campaignId': 'campaign-1', 'uniqueIdType': 'email', 'uniqueIdValue': 'person@example.test', 'rewardType': '1', 'rewardsToRedeem': '2'}, 'success'),
    ('send_card_message', {'card_id': 'card-1', 'message': 'Thank you'}, 'POST', '/v1/card/push', {'cardID': 'card-1', 'message': 'Thank you'}, 'success'),
    ('resync_card', {'card_id': 'card-1'}, 'PUT', '/v1/card/cid/card-1/resync', {'cid': 'card-1'}, 'success'),
    ('list_locations', {}, 'GET', '/v1/locations', None, 'locations'),
    ('get_location', {'location_id': 'location-1'}, 'GET', '/v1/location/location-1', None, 'location'),
]


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,arguments,method,path,body,response', CASES)
async def test_loopy_loyalty_native_operations(transport, operation, arguments, method, path, body, response):
    calls, replies = transport
    replies.append((200, REPLIES[response]))
    result = await run(operation, **arguments)
    assert result['status'] == 'success'
    assert result['data'] == REPLIES[response]
    assert len(calls) == 1
    request = calls[0]
    assert request.method == method
    assert request.url.raw_path.split(b'?')[0].decode() == path
    assert (json.loads(request.content) if request.content else None) == body
    if operation == 'get_card':
        assert dict(request.url.params) == {'includeEvents': 'false', 'includeRewards': 'false'}
    assert AUTH['api_secret'] not in json.dumps(result)


@pytest.mark.asyncio
async def test_loopy_loyalty_pagination_and_search(transport):
    calls, replies = transport
    replies.append((200, REPLIES['cards']))
    result = await run('list_cards', campaign_id='campaign-1', length=1, search='Peter')
    assert result['next_start'] == 1
    assert json.loads(calls[0].content)['dt'] == {'start': '0', 'length': '1', 'search': 'Peter'}


@pytest.mark.asyncio
@pytest.mark.parametrize('status,payload', [(401, {'message': 'Invalid signature'}), (403, {'message': 'Access denied'}), (200, {'success': False}), (200, {'error': 'Invalid query'}), (200, [])])
async def test_loopy_loyalty_errors_do_not_succeed_or_retry(transport, status, payload):
    calls, replies = transport
    replies.append((status, payload))
    result = await run('resync_card', card_id='card-1')
    assert result['status'] == 'error'
    assert len(calls) == 1
    if isinstance(payload, dict) and payload.get('message'):
        assert result['error'] == payload['message']


@pytest.mark.asyncio
async def test_loopy_loyalty_campaign_evidence_uses_account_read(transport):
    calls, replies = transport
    replies.append((200, REPLIES['campaigns']))
    result = await ll.LoopyLoyaltyNode.load_field_options('campaign_id', AUTH)
    assert result == {'options': [{'value': 'campaign-1', 'label': 'Coffee Club'}], 'next_page_token': None}
    assert calls[0].url.path == '/v1/campaigns'


@pytest.mark.asyncio
async def test_loopy_loyalty_unique_identifier_cannot_change_route(transport):
    calls, replies = transport
    replies.append((200, REPLIES['card']))
    await run('get_card_by_unique_id', **{**UNIQUE, 'unique_id_value': 'a/b?c#d'})
    assert calls[0].url.raw_path == b'/v1/uniquecard/campaignid/campaign-1/email/a%2Fb%3Fc%23d'


@pytest.mark.parametrize('field', ['api_key', 'api_secret'])
def test_loopy_loyalty_manual_credentials_reject_urls_and_placeholders(field):
    for value in ['https://app.loopyloyalty.com/settings', '<token>']:
        with pytest.raises(ValidationError):
            ll.LoopyLoyaltyCredential.model_validate({**AUTH, field: value})
    assert ll.LoopyLoyaltyCredential.model_validate({k: v for k, v in AUTH.items() if k != 'credential_type'}).credential_type == ll.TYPE
