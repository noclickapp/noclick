"""Exercise every published request and response through the normal node runner."""
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError
from nodes import content_snare_node as provider
from nodes.core.run_op import run_node_operation
from utils import ssrf

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/content-snare/published_examples.json').read_text())
AUTH = {'credential_type': provider.CREDENTIAL, 'access_token': 'cs_pat_fixture_secret_1234567890'}


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, '_resolve_host_addresses', AsyncMock(return_value=['93.184.216.34']))
    async def send(request):
        requests.append(request)
        status, body = replies.pop(0)
        if body is None:
            return httpx.Response(status)
        return httpx.Response(status, content=body) if isinstance(body, bytes) else httpx.Response(status, json=body)
    native = ssrf.guarded_async_client
    monkeypatch.setattr(provider, 'guarded_async_client', lambda **kw: native(**kw, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(op, config=None, auth=None):
    return await run_node_operation(node_type='automation-content-snare', operation=op,
        arguments=deepcopy(config or {}), credential_data=deepcopy(auth or AUTH),
        user_id='00000000-0000-4000-8000-000000000001')


@pytest.mark.asyncio
@pytest.mark.parametrize('case', FIXTURE['cases'], ids=lambda c: c['operation'])
async def test_content_snare_published_operations(transport, case):
    requests, replies = transport
    replies.append((case['status'], deepcopy(case['response'])))
    output = await run(case['operation'], case['config'])
    assert len(requests) == 1 and not replies
    req = requests[0]
    assert req.method == case['method']
    path = case['path']
    id_key = next((k for k in ('request_id', 'field_id', 'client_id') if k in case['config'] and '{id}' in path), None)
    if id_key:
        path = path.replace('{id}', case['config'][id_key])
    assert req.url.path == '/partner_api/v1' + path
    assert req.url.host == 'api.contentsnare.com'
    assert req.headers['Authorization'] == 'Bearer ' + AUTH['access_token']
    assert AUTH['access_token'] not in str(req.url) + req.content.decode() + json.dumps(output)
    if case['method'] in {'POST', 'PUT'} and case['config'] and case['operation'] not in {'approve_request_fields', 'submit_request_fields'}:
        expected = {k:v for k,v in case['config'].items() if k != id_key}
        assert json.loads(req.content) == expected
    if case['operation'].startswith('list_'):
        assert req.url.params['limit'] == '20'
        assert req.url.params['offset'] == '0'
        assert output['results'] == case['response']['results']
        assert output['next_offset'] == 20
    elif case['response'] is not None:
        assert output == case['response']
    else:
        assert output['http_status'] == case['status']


@pytest.mark.asyncio
async def test_content_snare_query_filters_and_pagination(transport):
    transport[1].append((200, {'results': [], 'pagination': {'limit': 20, 'offset': 40, 'total_count': 40}}))
    out = await run('list_requests', {'offset': 40, 'statuses': ['published', 'completed'], 'q': 'Acme'})
    assert transport[0][0].url.params.get_list('filter_by[statuses][]') == ['published', 'completed']
    assert out['next_offset'] is None
    transport[1].append((200, {'results': [], 'pagination': {'total_count': 0}}))
    await run('list_clients', {'email': 'clayschaden@mail.org', 'include_external': False})
    assert transport[0][-1].url.params['filter_by[email]'] == 'clayschaden@mail.org'
    assert transport[0][-1].url.params['include_external'] == 'false'


@pytest.mark.asyncio
@pytest.mark.parametrize('status,body', [(401, {'errors':['Token expired']}), (403, {'errors':['Missing scope']}),
    (429, {'errors':['Rate limited']}), (500, b'<html>Error</html>'), (302, {}), (200, {}), (200, []),
    (200, {'errors':['Rejected']}), (200, {'full_name': ''})])
async def test_content_snare_rejects_unconfirmed_identity_without_retry(transport, status, body):
    transport[1].append((status, body))
    with pytest.raises(ValueError):
        await run('get_identity')
    assert len(transport[0]) == 1


@pytest.mark.asyncio
async def test_content_snare_errors_are_verbatim_and_redacted(transport):
    transport[1].append((403, {'errors':['Missing scope ' + AUTH['access_token']]}))
    with pytest.raises(ValueError, match='Missing scope') as err:
        await run('get_identity')
    assert AUTH['access_token'] not in str(err.value)


@pytest.mark.asyncio
async def test_content_snare_build_status_and_encoded_id(transport):
    transport[1].append((201, {'id':'req_abc', 'build_status':'building'}))
    result = await run('create_request', {'name':'Request 1', 'client_id':'acc_MORVw9Cyq97AyN'})
    assert result['build_status'] == 'building' and len(transport[0]) == 1
    transport[1].append((200, {'id':'req_a/b', 'build_status':'ready'}))
    await run('get_request', {'request_id':'req_a/b'})
    assert b'req_a%2Fb' in transport[0][-1].url.raw_path


@pytest.mark.parametrize('op,config', [('create_client', {'email':'x'}), ('create_request', {'name':'x'}),
    ('review_field', {'field_id':'fld_x', 'status':'invalid'}), ('list_clients', {'limit':0}),
    ('update_request', {'request_id':'req_x','due':'2026-02-30'})])
def test_content_snare_required_fields_and_enums(op, config):
    with pytest.raises(ValueError):
        provider.ContentSnareNode.parse_config({'config':{'operation':op, **config}, 'credentials':AUTH})


def test_content_snare_manual_credential_default_and_secret_cleaning():
    assert provider.ContentSnarePersonalToken(access_token=AUTH['access_token']).credential_type == provider.CREDENTIAL
    with pytest.raises(ValidationError):
        provider.ContentSnarePersonalToken(access_token='Bearer example')


@pytest.mark.asyncio
async def test_content_snare_bulk_review_rejects_error_envelope(transport):
    transport[1].append((200, {'errors':['Review not permitted']}))
    with pytest.raises(ValueError, match='Review not permitted'):
        await run('approve_request_fields', {'request_id':'req_y8k0w9ASlnD4YX'})
    assert len(transport[0]) == 1
