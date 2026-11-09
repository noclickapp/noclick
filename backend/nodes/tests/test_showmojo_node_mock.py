"""Exercise ShowMojo wire requests and poll lifecycle using published examples.

The fixtures retain provider payloads so parser, replacement-import and tour
consent behavior can be reviewed without a live customer account.
"""
import copy
import json
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest
from nodes.showmojo_node import ShowMojoNode, ShowMojoTokenCredential

FIXTURES = json.loads((Path(__file__).parent / 'fixtures/showmojo/documented.json').read_text())['examples']
TOKEN = 'test-showmojo-private-token'


def node(config):
    data = {'config': config, 'credentials': {'credential_type': 'showmojo_api_token', 'api_token': TOKEN}}
    return ShowMojoNode('n', 'automation-showmojo', data, config=ShowMojoNode.parse_config(data))


@pytest.fixture
def wire(monkeypatch):
    requests = []
    responses = []
    client = httpx.AsyncClient

    def handler(request):
        requests.append(request)
        status, payload = responses.pop(0)
        return httpx.Response(status, text=payload) if isinstance(payload, str) else httpx.Response(status, json=payload)

    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: client(transport=httpx.MockTransport(handler), **kwargs))
    return requests, responses


@pytest.mark.asyncio
@pytest.mark.parametrize('config,method,path', [
    ({'operation': 'list_listings', 'updated_since': '2026-10-15T00:00:00Z'}, 'GET', '/api/v3/listings'),
    ({'operation': 'get_listing', 'uid': 'abc123def'}, 'GET', '/api/v3/listings/abc123def'),
    ({'operation': 'list_properties'}, 'GET', '/api/v3/properties'),
    ({'operation': 'get_property', 'uid': 'abc123'}, 'GET', '/api/v3/properties/abc123'),
    ({'operation': 'get_available_tour_times', 'listing_id': 'abc123'}, 'GET', '/api/v3/tours/abc123/available_times'),
    ({'operation': 'get_screening_questions', 'listing_id': 'abc123'}, 'GET', '/api/v3/tours/abc123/screening_questions'),
    ({'operation': 'export_report_json', 'report_name': 'detailed_listing_data'}, 'POST', '/api/v3/reports/detailed_listing_data'),
    ({'operation': 'export_report_csv', 'report_name': 'detailed_listing_data'}, 'POST', '/api/v3/reports/detailed_listing_data.csv'),
    ({'operation': 'export_custom_report_json', 'report_id': 412}, 'POST', '/api/v3/reports/custom'),
    ({'operation': 'export_custom_report_csv', 'report_id': 412}, 'POST', '/api/v3/reports/custom.csv'),
])
async def test_showmojo_routes(wire, config, method, path):
    requests, responses = wire
    responses.append((200, 'Address,Rent\n401 Dains St.,2500\n' if config['operation'].endswith('_csv') else FIXTURES['report']))
    output = await node(config).execute({})
    assert output['success'] is True
    assert len(requests) == 1
    req = requests[0]
    assert req.method == method and req.url.path == path
    assert req.headers['authorization'] == 'Token ' + TOKEN
    if method == 'POST':
        assert req.headers['content-type'].startswith('application/x-www-form-urlencoded')
        if 'report_id' in config:
            assert parse_qs(req.content.decode())['report_id'] == ['412']
    if config['operation'] == 'list_listings':
        assert req.url.params['updated_since'] == config['updated_since']
        assert req.url.params['page'] == '1'


@pytest.mark.asyncio
async def test_showmojo_schedule_preserves_consent_and_pending_status(wire):
    requests, responses = wire
    body = {**FIXTURES['schedule_input'], 'can_contact_by_email': False}
    result = {**FIXTURES['schedule_result'], 'pending_acceptance': True}
    responses.append((200, result))
    output = await node({'operation': 'schedule_tour', **body}).execute({})
    assert requests[0].method == 'PUT'
    sent = json.loads(requests[0].content)
    assert sent == {**body, 'channel': 'THIRD_PARTY'}
    assert output['data']['pending_acceptance'] is True
    assert output['data']['tour_id'] == result['tour_id']


@pytest.mark.asyncio
async def test_showmojo_import_reports_partial_errors(wire):
    requests, responses = wire
    listing = {'code': 'DAINS401', 'address': '401 Dains St.', 'city': 'San Francisco', 'state': 'CA', 'zip': '94107', 'status': 'STATUS_ACTIVE'}
    responses.append((200, FIXTURES['import_result']))
    output = await node({'operation': 'import_listings', 'listings': [listing]}).execute({})
    assert json.loads(requests[0].content) == {'listings': [listing]}
    assert output['status'] == 'partial' and output['has_errors'] is True
    assert output['data']['response'][0]['status'] == 'created'


@pytest.mark.asyncio
async def test_showmojo_poll_baselines_then_emits_updates_and_new_listings(wire):
    requests, responses = wire
    n = node({'operation': 'on_listing_changed', 'updated_since': '2026-10-15T00:00:00Z'})
    state = {}

    async def update(mutator, **kwargs):
        changed, result = mutator(copy.deepcopy(state))
        if changed is not None:
            state.clear()
            state.update(changed)
        return result

    n._update_node_state = update
    page = copy.deepcopy(FIXTURES['listing_page'])
    responses.append((200, page))
    assert (await n.execute({}))['listings'] == []
    responses.append((200, page))
    assert (await n.execute({}))['new_or_updated_count'] == 0
    page['data'][0]['updated_at'] = '2026-10-16T14:22:00.000Z'
    responses.append((200, page))
    output = await n.execute({})
    assert output['new_or_updated_count'] == 1
    event = n.resolve_agent_event(output)
    assert page['data'][0]['uid'] in event['text']
    assert page['data'][0]['address'] in event['text']
    page['data'].append({**page['data'][0], 'uid': 'new-listing'})
    responses.append((200, page))
    assert (await n.execute({}))['new_or_updated_count'] == 1
    assert all(req.url.params['updated_since'] == '2026-10-15T00:00:00Z' for req in requests)


@pytest.mark.asyncio
async def test_showmojo_poll_reads_every_page_before_state_commit(wire):
    requests, responses = wire
    n = node({'operation': 'on_listing_changed'})
    page = copy.deepcopy(FIXTURES['listing_page'])
    page['pagination']['total_pages'] = 2
    second = copy.deepcopy(page)
    second['pagination']['page'] = 2
    second['data'][0]['uid'] = 'second-page'
    responses.extend([(200, page), (200, second)])
    seen = []

    async def filter_rows(rows, id_fn):
        seen.extend(id_fn(row) for row in rows)
        return rows

    n._filter_unseen = filter_rows
    assert (await n.execute({}))['new_or_updated_count'] == 2
    assert len(seen) == 2
    assert [r.url.params['page'] for r in requests] == ['1', '2']


@pytest.mark.asyncio
async def test_showmojo_poll_malformed_page_does_not_advance_state(wire):
    _, responses = wire
    responses.append((200, {'data': [], 'pagination': {}}))
    with pytest.raises(ValueError, match='pagination'):
        await node({'operation': 'on_listing_changed'}).execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [401, 403, 409, 429, 500])
async def test_showmojo_errors_do_not_echo_secret_or_retry_writes(wire, status):
    requests, responses = wire
    responses.append((status, {'error': TOKEN}))
    with pytest.raises(ValueError) as err:
        await node({'operation': 'list_listings'}).execute({})
    assert TOKEN not in str(err.value)
    assert len(requests) == 1


def test_showmojo_manual_credential_has_default_type():
    assert ShowMojoTokenCredential(api_token=TOKEN).credential_type == 'showmojo_api_token'
    with pytest.raises(ValueError):
        ShowMojoTokenCredential(api_token='Token ' + TOKEN)
