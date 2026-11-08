"""Transport-level checks of the real Fiber node against pinned contract routes."""
import json
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest

from nodes import fiber_node as fiber
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / 'fixtures/fiber/contract-cases.json').read_text())
AUTH = {'credential_type': 'fiber_api_key', 'api_key': 'synthetic-fiber-test-key'}


async def run(operation, config=None, credentials=None):
    node = NodeFactory.create_node(node_id='fiber-test', node_type='automation-fiber',
        node_data={'config': {'operation': operation, **(config or {})}, 'credentials': credentials or AUTH})
    return await node.execute({})


@pytest.fixture
def transport(monkeypatch):
    calls, replies = [], []
    def handle(request):
        calls.append(request)
        status, body, headers = replies.pop(0)
        return httpx.Response(status, json=body, headers=headers)
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as value:
            yield value
    monkeypatch.setattr(fiber, 'guarded_async_client', client)
    return calls, replies


@pytest.mark.parametrize('case', CASES, ids=lambda c: c['operation'])
@pytest.mark.asyncio
async def test_contract_method_route_auth_and_payload(transport, case):
    calls, replies = transport
    replies.append((200, case['response'], {}))
    result = await run(case['operation'], case['config'])
    assert result['status'] == 'success' and result['data'] == case['response']['output']
    assert len(calls) == 1 and not replies
    request = calls[0]
    assert request.method == case['method'] and request.url.path == case['path']
    assert request.url.host == 'api.fiber.ai' and request.headers['accept'] == 'application/json'
    sent = dict(request.url.params) if request.method in {'GET', 'DELETE'} else json.loads(request.content)
    assert sent.pop('apiKey') == AUTH['api_key']
    assert 'audience_id' not in sent and 'operation' not in sent
    if case['operation'] == 'find_work_email':
        assert sent == {'name': {'mode': 'fullName', 'fullName': 'Sam Altman'}, 'company': {'mode': 'domain', 'domain': 'openai.com'}}
    else:
        for k, value in case['config'].items():
            if k != 'audience_id':
                assert sent[k] == (str(value) if request.method in {'GET', 'DELETE'} else value)
    assert AUTH['api_key'] not in json.dumps(result)


@pytest.mark.asyncio
async def test_pagination_and_async_state_preserved(transport):
    calls, replies = transport
    replies.append((200, {'output': {'data': [{'name': 'Company'}], 'nextCursor': 'next-page'}}, {}))
    result = await run('search_companies', {'searchParams': {'domains': ['openai.com']}})
    assert result['data']['nextCursor'] == 'next-page' and len(calls) == 1
    replies.append((200, {'output': {'enrichmentId': 'run-1', 'status': 'NOT_STARTED', 'estimatedCredits': 10}}, {}))
    result = await run('start_enrichment', {'audience_id': 'audience-123', 'maxProspectsToEnrich': 10, 'enrichmentType': {}})
    assert result['data']['status'] == 'NOT_STARTED' and len(calls) == 2
    body = json.loads(calls[-1].content)
    assert body['enrichmentType'] == {'getWorkEmails': True, 'getPersonalEmails': False, 'getPhoneNumbers': False}
    assert body['runContactEnrichment'] is True and body['runProfileSalesNav'] is False
    assert 'userEmail' not in body


@pytest.mark.parametrize('code', [301, 401, 403, 429, 500])
@pytest.mark.asyncio
async def test_failures_are_not_successful_and_do_not_leak_key(transport, code):
    calls, replies = transport
    replies.append((code, {'message': 'Rejected ' + AUTH['api_key']}, {}))
    result = await run('list_audiences')
    assert result['status'] == 'error' and result['http_status'] == code
    assert AUTH['api_key'] not in json.dumps(result) and len(calls) == 1


@pytest.mark.parametrize('body', [{}, [], {'output': []}, {'output': {'audiences': 'invalid'}}])
@pytest.mark.asyncio
async def test_malformed_envelopes_cannot_prove_connection(transport, body):
    transport[1].append((200, body, {}))
    with pytest.raises(ValueError):
        await run('list_audiences')


@pytest.mark.asyncio
async def test_error_envelope_and_success_echo_are_redacted(transport):
    transport[1].append((200, {'error': {'apiKey': AUTH['api_key'], 'message': AUTH['api_key']}}, {}))
    result = await run('list_audiences')
    assert result['status'] == 'error' and AUTH['api_key'] not in json.dumps(result)
    transport[1].append((200, {'output': {'count': 1, 'apiKey': AUTH['api_key'], 'message': AUTH['api_key']}}, {}))
    result = await run('count_companies', {'searchParams': {}})
    assert AUTH['api_key'] not in json.dumps(result) and 'apiKey' not in result['data']


@pytest.mark.asyncio
async def test_account_audience_picker(transport):
    case = next(c for c in CASES if c['operation'] == 'list_audiences')
    transport[1].append((200, case['response'], {}))
    result = await fiber.FiberNode.load_field_options('audience_id', AUTH, search='fintech')
    assert result == {'options': [{'value': 'audience-123', 'label': 'Fintech VPs in NYC'}], 'next_page_token': None}
    assert transport[0][0].method == 'GET'


@pytest.mark.parametrize('config', [
    {'operation': 'get_audience_status', 'audience_id': '../other'},
    {'operation': 'list_audience_companies', 'audience_id': 'a', 'pageSize': 501},
    {'operation': 'resolve_companies', 'companies': [{'identifier': 'linkedinOrgId', 'value': 'not-a-number'}]},
    {'operation': 'resolve_people', 'people': []},
    {'operation': 'start_enrichment', 'audience_id': 'a', 'maxProspectsToEnrich': 0, 'enrichmentType': {}},
    {'operation': 'search_companies', 'searchParams': {'apiKey': 'override'}},
    {'operation': 'create_audience', 'name': 'A', 'apiKey': 'override'},
])
def test_invalid_inputs_refused_before_transport(config):
    with pytest.raises(ValueError):
        fiber.FiberNode.parse_config({'config': config, 'credentials': AUTH})


@pytest.mark.parametrize('key', ['https://fiber.ai/app/api', '<token>', 'bad key', 'abc\nxyz'])
def test_credential_can_be_connected_by_hand_and_rejects_bad_pastes(key):
    assert fiber.FiberAPIKeyCredential(api_key=AUTH['api_key']).credential_type == 'fiber_api_key'
    with pytest.raises(ValueError):
        fiber.FiberAPIKeyCredential(api_key=key)
