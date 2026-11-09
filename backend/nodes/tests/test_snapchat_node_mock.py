"""Offline Snap CAPI contract and manual-connect regressions."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import snapchat_node as native
from nodes.core.registry import NODE_REGISTRY, NodeFactory
from nodes.core.base import ConfigValidationError

TOKEN = "synthetic-snapchat-capi-42"
ASSET = "1ec32188-754e-4be2-8e55-c949a984a39f"
EMAIL = "7b17fb0bd173f625b58636fb796407c22b3d16fc78302d79f0fd30c2fc2fc068"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def credential():
    return {"credential_type": native.FAMILY, "access_token": TOKEN, "asset_id": ASSET}


def web(operation):
    return {"operation": operation, "event_time": 1709761985, "event_id": "EBBE201",
        "event_source_url": "https://www.example.com/", "email_sha256": EMAIL,
        "currency": "USD", "value": 10}


def event():
    return {"event_name": "PAGE_VIEW", "event_time": 1709761985, "event_id": "EBBE201",
        "event_source_url": "https://www.example.com/", "action_source": "WEB", "user_data": {"em": [EMAIL]}}


def node(config):
    return NodeFactory.create_node(node_id="snapchat-test", node_type="automation-snapchat",
        node_data={"config": config, "credentials": credential()})


def transport(monkeypatch, body, code=200):
    requests = []
    original = httpx.AsyncClient
    def reply(request):
        requests.append(request)
        return httpx.Response(code, json=body)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return original(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native.httpx, "AsyncClient", client)
    return requests


def test_discovery_and_manual_credential_fields():
    assert NODE_REGISTRY['automation-snapchat'] is native.SnapchatNode
    shaped = native.SnapchatCAPITokenCredential(access_token=TOKEN, asset_id=ASSET)
    assert shaped.credential_type == 'snapchat_capi_token'
    assert native.SnapchatNode.connection_evidence.operation == 'get_validation_stats'
    schema = native.SnapchatCAPITokenCredential.model_json_schema()
    assert set(schema['required']) == {'access_token', 'asset_id'}


@pytest.mark.asyncio
@pytest.mark.parametrize(('operation', 'event_name'), [
    ('send_purchase', 'PURCHASE'), ('send_add_cart', 'ADD_CART'),
    ('send_start_checkout', 'START_CHECKOUT'), ('send_view_content', 'VIEW_CONTENT'),
    ('send_sign_up', 'SIGN_UP'), ('send_search', 'SEARCH'),
    ('send_subscribe', 'SUBSCRIBE'), ('send_add_to_wishlist', 'ADD_TO_WISHLIST'),
])
async def test_presets_use_one_v3_send_event_request(monkeypatch, operation, event_name):
    requests = transport(monkeypatch, {'status': 'VALID'})
    result = await node(web(operation)).execute({})
    assert result['status'] == 'success'
    assert len(requests) == 1
    request = requests[0]
    assert request.method == 'POST' and request.url.host == 'tr.snapchat.com'
    assert request.url.path == f'/v3/{ASSET}/events'
    assert dict(request.url.params) == {'access_token': TOKEN}
    body = json.loads(request.content)
    assert body == {'data': [{**event(), 'event_name': event_name, 'custom_data': {'currency': 'USD', 'value': 10.0}}]}
    assert TOKEN not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize(('operation', 'suffix'), [('send_events', ''), ('validate_events', '/validate')])
async def test_batch_and_validation_envelopes(monkeypatch, operation, suffix):
    requests = transport(monkeypatch, {'status': 'VALID', 'test_event': True})
    config = {'operation': operation, 'events_json': json.dumps([event()])}
    if operation == 'send_events': config['test_event_code'] = 'test-code'
    result = await node(config).execute({})
    assert result['status'] == 'success'
    assert len(requests) == 1 and requests[0].url.path == f'/v3/{ASSET}/events{suffix}'
    expected = {'data': [event()]}
    if operation == 'send_events': expected['test_event_code'] = 'test-code'
    assert json.loads(requests[0].content) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(('operation', 'suffix', 'reply'), [
    ('get_validation_logs', 'logs', {'status': 'SUCCESS', 'logs': []}),
    ('get_validation_stats', 'stats', {'status': 'SUCCESS', 'stats': {'live': {'event_count_past_hour': 0, 'latest_event_ts': 0}}}),
])
async def test_asset_diagnostics_are_read_only(monkeypatch, operation, suffix, reply):
    requests = transport(monkeypatch, reply)
    result = await node({'operation': operation}).execute({})
    assert result['data'] == reply
    assert len(requests) == 1 and requests[0].method == 'GET'
    assert requests[0].url.path == f'/v3/{ASSET}/events/validate/{suffix}'
    assert not requests[0].content


@pytest.mark.asyncio
@pytest.mark.parametrize(('reply', 'status'), [({'status': 'FAILURE', 'reason': 'Token rejected'}, 401),
    ({'status': 'INVALID', 'reason': 'Invalid event'}, 200), ({'status': 'UNKNOWN'}, 200)])
async def test_rejections_and_unknown_status_never_succeed_or_retry(monkeypatch, reply, status):
    requests = transport(monkeypatch, reply, status)
    result = await node(web('send_purchase')).execute({})
    assert result['status'] == 'error' and result['status_code'] == status
    assert len(requests) == 1
    if 'reason' in reply: assert result['error'] == reply['reason']


@pytest.mark.asyncio
async def test_provider_echo_is_redacted(monkeypatch):
    transport(monkeypatch, {'status': 'FAILURE', 'reason': f'Invalid token {TOKEN}', 'access_token': TOKEN}, 403)
    result = await node({'operation': 'get_validation_stats'}).execute({})
    assert TOKEN not in str(result) and 'access_token' not in result['data']


@pytest.mark.parametrize('asset', ['https://snapchat.com/pixel', '../stats', 'foo/bar', 'foo?token=x'])
def test_refuse_asset_path_injection(asset):
    with pytest.raises(ValidationError): native.SnapchatCAPITokenCredential(access_token=TOKEN, asset_id=asset)


def test_refuse_unhashed_email_and_missing_purchase_value():
    with pytest.raises(ConfigValidationError): node({**web('send_sign_up'), 'email_sha256': 'person@example.com'})
    config = web('send_purchase'); config.pop('value')
    with pytest.raises(ConfigValidationError): node(config)
    with pytest.raises(ConfigValidationError): node({'operation': 'send_events', 'events_json': json.dumps([{**event(), 'user_data': {'em': ['person@example.com']}}])})


@pytest.mark.asyncio
async def test_published_contract_response_fixtures(monkeypatch):
    fixtures = json.loads((Path(__file__).parent / 'fixtures/snapchat/responses.json').read_text())
    for operation, reply in fixtures.items():
        transport(monkeypatch, reply)
        config = {'operation': operation} if operation.startswith('get_') else web(operation)
        if operation == 'validate_events': config = {'operation': operation, 'events_json': json.dumps([event()])}
        assert (await node(config).execute({}))['status'] == 'success'
        monkeypatch.undo()
