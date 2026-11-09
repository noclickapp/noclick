"""Exercise real factory, validation and HTTP serialization with an offline provider."""
import base64
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import checkfront_node as native
from nodes.core.registry import NODE_REGISTRY, NodeFactory

KEY = "checkfront-fixture-key"
SECRET = "checkfront-fixture-secret"
CREDS = {"credential_type": "checkfront_api_key", "tenant_url": "https://demo.checkfront.com", "api_key": KEY, "api_secret": SECRET}
CASES = json.loads((Path(__file__).parent / "fixtures/checkfront/requests.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="checkfront-fixture", node_type="automation-checkfront",
        node_data={"config": config, "credentials": CREDS})


def transport(monkeypatch, response):
    calls = []
    def reply(request):
        calls.append(request)
        return response(request) if callable(response) else response
    def client(**kwargs):
        assert kwargs == {"timeout": 30, "trust_env": False, "follow_redirects": False}
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c['config']['operation'])
async def test_all_published_operation_requests(monkeypatch, case):
    op = case['config']['operation']
    listing = op.startswith('list_')
    response = httpx.Response(200, json={"data": [{"id": 1, "name": "Harbour tour"}] if listing else {"id": 1}})
    if op in {'update_customer', 'archive_customer'}:
        response = httpx.Response(200, content=b'')
    calls = transport(monkeypatch, response)
    result = await node(case['config']).execute({})
    assert NODE_REGISTRY['automation-checkfront'] is native.CheckfrontNode
    assert result['status'] == 'success' and len(calls) == 1
    request = calls[0]
    assert request.method == case['method']
    assert str(request.url.copy_with(query=None)) == 'https://demo.checkfront.com/api/4.0' + case['path']
    assert dict(request.url.params) == case.get('query', {})
    assert (json.loads(request.content) if request.content else None) == case.get('body')
    assert request.headers['authorization'] == 'Basic ' + base64.b64encode((KEY + ':' + SECRET).encode()).decode()
    assert KEY not in str(result) and SECRET not in str(result)
    if case['method'] != 'GET':
        assert result['acknowledged'] and result['effect_verified'] is False


@pytest.mark.parametrize('url,expected', [
    ('demo.checkfront.com/', 'https://demo.checkfront.com'),
    ('https://Demo.checkfront.com/', 'https://demo.checkfront.com'),
    ('https://demo.manage.na1.bookingplatform.app', 'https://demo.manage.na1.bookingplatform.app'),
    ('https://demo.manage.eu1.bookingplatform.app/', 'https://demo.manage.eu1.bookingplatform.app'),
])
def test_manual_credential_normalization(url, expected):
    cred = native.CheckfrontAPIKeyCredential(**{**CREDS, 'tenant_url': url, 'credential_type': 'checkfront_api_key'})
    assert cred.tenant_url == expected
    assert native.CheckfrontAPIKeyCredential(**{k: v for k,v in CREDS.items() if k != 'credential_type'}).credential_type == 'checkfront_api_key'


@pytest.mark.parametrize('url', ['http://demo.checkfront.com', 'https://checkfront.com', 'https://demo.checkfront.com.evil.test',
    'https://user:password@demo.checkfront.com', 'https://demo.checkfront.com:443', 'https://demo.checkfront.com/api/4.0',
    'https://demo.checkfront.com?x=y', 'https://demo.checkfront.com/#x', 'https://127.0.0.1',
    'https://demo.manage.na2.bookingplatform.app', 'https://nested.demo.checkfront.com'])
def test_refuse_foreign_credential_destinations(url):
    with pytest.raises(ValueError):
        native.CheckfrontAPIKeyCredential(**{**CREDS, 'tenant_url': url})


@pytest.mark.parametrize('config', [
    {'operation': 'get_booking', 'booking_code': '../company'},
    {'operation': 'get_booking', 'booking_code': 'a?b'},
    {'operation': 'get_customer', 'customer_id': 0},
    {'operation': 'update_booking', 'booking_code': 'ABCD-010115'},
    {'operation': 'create_customer', 'fields': {}},
    {'operation': 'update_customer', 'customer_id': 1, 'fields': {'customer_phone': None}},
    {'operation': 'checkin_booking', 'booking_code': 'ABCD-010115', 'guest_activity_ids': [-1]},
    {'operation': 'list_bookings', 'start_min': 'yesterday'},
    {'operation': 'list_bookings', 'start_min': '2026-11-09T10:00:00'},
    {'operation': 'change_booking_status', 'booking_code': 'ABCD-010115', 'status_id': 'PAID', 'send_notifications': 'yes'},
    {'operation': 'custom_request', 'url': 'https://evil.test'},
])
def test_invalid_config_refused(config):
    with pytest.raises(ValueError):
        native.CheckfrontNode.parse_config({'config': config, 'credentials': CREDS})


@pytest.mark.asyncio
async def test_page_continuation_and_sensitive_booking_tokens(monkeypatch):
    calls = transport(monkeypatch, httpx.Response(200, json={'data': [{'id': 76, 'code': 'ABCD-010115',
        'cfx': 'private-booker-token', 'gcfx': 'private-guest-token', 'nested': {'api_secret': SECRET}}],
        'meta': {'records': {'count': 1, 'total': 4, 'limit': 2, 'offset': 0, 'nextPageUrl': 'https://evil.test'}}}))
    result = await node({'operation': 'list_bookings', 'limit': 2}).execute({})
    assert result['status'] == 'success' and result['has_more'] and result['next_offset'] == 2
    assert result['data'] == [{'id': 76, 'code': 'ABCD-010115', 'nested': {}}]
    assert len(calls) == 1  # A provider link never becomes a request destination.


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 401, 403, 429, 500])
async def test_provider_rejections_are_not_success_and_never_retry(monkeypatch, status):
    calls = transport(monkeypatch, httpx.Response(status, text='Rejected ' + KEY + ' ' + SECRET, headers={'location': 'https://evil.test'}))
    result = await node({'operation': 'create_booking_note', 'booking_code': 'ABCD-010115', 'body': 'Note'}).execute({})
    assert result['status'] == 'error' and result['http_status'] == status
    assert KEY not in str(result) and SECRET not in str(result) and len(calls) == 1
    if status == 500:
        assert result['write_outcome'] == 'unverified'


@pytest.mark.asyncio
async def test_transport_failure_write_outcome_unknown(monkeypatch):
    def fail(request):
        raise httpx.ReadTimeout('timed out', request=request)
    calls = transport(monkeypatch, fail)
    result = await node({'operation': 'create_customer', 'fields': {'customer_first_name': 'Jane'}}).execute({})
    assert result['status'] == 'error' and result['write_outcome'] == 'unverified' and len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{}, {'data': {}}, {'data': [], 'errors': ['rejected']},
    {'data': [], 'meta': {'records': {'total': 1, 'limit': 0, 'offset': 0}}}])
async def test_invalid_list_envelopes(monkeypatch, body):
    transport(monkeypatch, httpx.Response(200, json=body))
    result = await node({'operation': 'list_products'}).execute({})
    assert result['status'] == 'error'


@pytest.mark.asyncio
async def test_connection_evidence_is_account_product_read(monkeypatch):
    from nodes.core.connection_evidence import collect_evidence
    calls = transport(monkeypatch, httpx.Response(200, json={'data': [{'id': 1, 'name': 'Harbour tour'}]}))
    result = await collect_evidence(node_type='automation-checkfront', credential_data=CREDS, user_id='checkfront-fixture-user')
    assert len(calls) == 1 and calls[0].method == 'GET' and calls[0].url.path == '/api/4.0/products'
    assert result.reachable is True
