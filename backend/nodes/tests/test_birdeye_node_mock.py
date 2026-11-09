"""Exercise every Birdeye operation through the native operation runner.

Independent wire expectations pin methods, route casing, API-key placement and
bodies; provider examples protect parsing and error propagation.
"""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import birdeye_node as mod
from nodes.core.run_op import run_node_operation

CASES = json.loads((Path(__file__).parent / 'fixtures/birdeye/operations.json').read_text())
AUTH = {'credential_type': 'birdeye_api_key', 'api_key': 'fixture-birdeye-key', 'business_id': '12345678'}


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    async def send(request):
        requests.append(request)
        status, payload = replies.pop(0)
        return httpx.Response(status, json=payload)
    client = httpx.AsyncClient
    monkeypatch.setattr(mod.httpx, 'AsyncClient', lambda **kw: client(**kw, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(operation, config=None, credential=AUTH):
    return await run_node_operation(node_type='automation-birdeye', operation=operation,
        arguments=config or {}, credential_data=credential, user_id='00000000-0000-4000-8000-000000000001')


@pytest.mark.asyncio
@pytest.mark.parametrize('case', CASES, ids=lambda c: c['operation'])
async def test_birdeye_published_requests(transport, case):
    requests, replies = transport
    replies.append((200, case['response']))
    result = await run(case['operation'], case['config'])
    assert result['data'] == case['response']
    assert len(requests) == 1
    request = requests[0]
    assert request.url.host == 'api.birdeye.com'
    assert request.url.path == '/resources' + case['path']
    assert request.method == case['method']
    assert dict(request.url.params) == case['params']
    assert request.headers['x-api-key'] == AUTH['api_key']
    assert AUTH['api_key'] not in str(request.url)
    assert (json.loads(request.content) if request.content else None) == case['body']


@pytest.mark.asyncio
async def test_birdeye_business_override(transport):
    requests, replies = transport
    replies.append((200, {'name': 'Other Business'}))
    await run('get_business', {'business_id': '987654321'})
    assert requests[0].url.path.endswith('/business/987654321')


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [400, 401, 403, 404, 429, 500, 302])
async def test_birdeye_rejection_never_becomes_success(transport, status):
    requests, replies = transport
    replies.append((status, {'code': 1161, 'message': 'Invalid API key'}))
    with pytest.raises(Exception, match='Invalid API key'):
        await run('get_business')
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_birdeye_error_envelope_and_secret_redaction(transport):
    _, replies = transport
    replies.append((200, {'code': 1161, 'message': 'Invalid ' + AUTH['api_key']}))
    with pytest.raises(Exception) as exc:
        await run('get_business')
    assert AUTH['api_key'] not in str(exc.value)
    assert '[redacted]' in str(exc.value)


def test_birdeye_manual_credential_and_path_validation():
    assert mod.BirdeyeAPIKeyCredential(api_key='fixture-birdeye-key', business_id='12345678').credential_type == 'birdeye_api_key'
    for value in ['../admin', '123/456', 'https://example.com', '?key=oops']:
        with pytest.raises(ValidationError):
            mod.GetBusinessConfig(business_id=value)
    with pytest.raises(ValidationError):
        mod.ListReviewsConfig(sindex=99999, count=2)
    with pytest.raises(ValidationError):
        mod.DeleteContactConfig(id="115339282")


@pytest.mark.asyncio
async def test_birdeye_connection_evidence_names_the_business(transport):
    from nodes.core.connection_evidence import collect_evidence
    requests, replies = transport
    replies.append((200, {'businessId': 12345678, 'name': 'Fixture Business'}))
    evidence = await collect_evidence(node_type='automation-birdeye', credential_data=AUTH,
        user_id='00000000-0000-4000-8000-000000000001')
    assert evidence.reachable is True
    assert evidence.account_label == 'Fixture Business'
    assert len(requests) == 1 and requests[0].method == 'GET'


def test_birdeye_contact_writes_require_explicit_locations():
    with pytest.raises(ValidationError):
        mod.UpsertContactConfig(email="michael@test.com")
    with pytest.raises(ValidationError):
        mod.DeleteContactConfig(id="115339282", businessIds=[])
