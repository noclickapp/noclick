"""Synthetic responses shaped by OpenFEC Swagger 1.0; no live key used."""
import json
from pathlib import Path

import httpx
import pytest
from nodes import fec_node as native
from nodes.core.registry import NODE_REGISTRY, NodeFactory
from nodes.core.poll_trigger import poll_scope

TOKEN = 'synthetic-fec-api-key'

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='fec-test', node_type='automation-fec', node_data={
        'config': config, 'credentials': {'credential_type': 'fec_api_key', 'api_key': TOKEN}})


def transport(monkeypatch, reply):
    requests = []
    def respond(request):
        requests.append(request)
        return reply(request) if callable(reply) else httpx.Response(200, json=reply)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


PAGE = {'results': [], 'pagination': {'page': 1, 'pages': 1, 'per_page': 20, 'count': 0}}


def test_fec_registry_discovery():
    assert NODE_REGISTRY['automation-fec'] is native.FECNode


@pytest.mark.asyncio
async def test_fec_fixed_host_header_repeated_filters_and_pagination(monkeypatch):
    reqs = transport(monkeypatch, PAGE)
    result = await node({'operation': 'list_contributions', 'committee_id': ['C00000001', 'C00000002'],
                         'last_index': 123, 'last_contribution_receipt_date': '2026-01-01', 'per_page': 50}).execute({})
    assert result == PAGE
    r = reqs[0]
    assert r.method == 'GET' and r.url.host == 'api.open.fec.gov'
    assert r.url.path == '/v1/schedules/schedule_a/'
    assert r.url.params.get_list('committee_id') == ['C00000001', 'C00000002']
    assert r.url.params['last_index'] == '123' and r.url.params['per_page'] == '50'
    assert r.headers['X-Api-Key'] == TOKEN and TOKEN not in str(r.url)


@pytest.mark.asyncio
async def test_fec_path_selection_preserves_provider_results(monkeypatch):
    body = {'results': [{'candidate_id': 'H0XX00001', 'name': 'Example'}], 'pagination': {'pages': 1}}
    reqs = transport(monkeypatch, body)
    assert await node({'operation': 'get_candidate', 'candidate_id': 'H0XX00001'}).execute({}) == body
    assert reqs[0].url.path == '/v1/candidate/H0XX00001/'
    assert 'candidate_id' not in reqs[0].url.params


@pytest.mark.asyncio
async def test_fec_poll_baseline_new_amendment_dedup_and_repoint(monkeypatch):
    page = json.loads((Path(__file__).parent / 'fixtures/fec/filings.json').read_text())
    transport(monkeypatch, page)
    n = node({'operation': 'on_new_filing', 'committee_id': 'C00000001'})
    state = {}
    async def update(mutator, **kwargs):
        nonlocal state
        state, result = mutator(state)
        return result
    n._update_node_state = update
    assert (await n.execute({}))['filings'] == []
    page['results'].append({**page['results'][0], 'file_number': 2, 'amendment_indicator': 'A'})
    result = await n.execute({})
    assert result['new_filing_count'] == 1 and result['filings'][0]['file_number'] == 2
    assert n.trigger_emitted_event(result)
    assert 'file_number' in native.FECNode.resolve_agent_event(result)['text']
    assert (await n.execute({}))['filings'] == []
    assert n.trigger_produced_no_event({})
    first = poll_scope(native.FECNode, {'operation': 'on_new_filing', 'committee_id': 'C00000001'})
    assert first == poll_scope(native.FECNode, {'operation': 'on_new_filing', 'committee_id': 'C00000001', 'label': 'changed'})
    assert first != poll_scope(native.FECNode, {'operation': 'on_new_filing', 'committee_id': 'C00000002'})


@pytest.mark.asyncio
async def test_fec_poll_all_pages_and_refuses_truncated_baseline(monkeypatch):
    reqs = transport(monkeypatch, {'results': [{'file_number': 1}], 'pagination': {'pages': 11}})
    n = node({'operation': 'on_new_filing', 'committee_id': 'C00000001'})
    with pytest.raises(ValueError, match='1,000'):
        await n.execute({})
    assert len(reqs) == 10
    assert reqs[0].url.params['sort'] == '-receipt_date'


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 401, 403, 429, 500])
async def test_fec_provider_failures_never_become_success(monkeypatch, status):
    transport(monkeypatch, lambda request: httpx.Response(status, json={'error': {'message': 'API_KEY_INVALID'}}))
    with pytest.raises(ValueError):
        await node({'operation': 'list_candidates'}).execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{}, {'results': {}}, {'results': [None], 'pagination': {}}, {'results': [], 'pagination': None}])
async def test_fec_malformed_page_rejected(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError):
        await node({'operation': 'list_candidates'}).execute({})


def test_fec_manual_credential_and_closed_config():
    assert native.FECApiKeyCredential(api_key=TOKEN).credential_type == 'fec_api_key'
    for config in [
        {'operation': 'get_candidate', 'candidate_id': '../committees'},
        {'operation': 'list_filings', 'per_page': 101},
        {'operation': 'list_filings', 'url': 'https://example.test'},
        {'operation': 'list_elections'},
        {'operation': 'list_candidates', 'office': ['1']},
    ]:
        with pytest.raises(ValueError):
            native.FECNode.parse_config({'config': config})
    for key in ['https://example.test/key', 'key with spaces', '{{key}}']:
        with pytest.raises(ValueError):
            native.FECApiKeyCredential(api_key=key)
