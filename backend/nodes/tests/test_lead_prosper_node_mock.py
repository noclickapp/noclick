"""Replay the provider's own pinned examples through the real node factory."""
import copy
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import lead_prosper_node as native
from nodes.core.registry import NodeFactory
from nodes.core.poll_trigger import poll_scope

FIXTURES = Path(__file__).parent / 'fixtures' / 'lead-prosper'
CASES = json.loads((FIXTURES / 'responses.json').read_text())
TOKEN = 'synthetic-lead-prosper-test-key-42'


@pytest.fixture(autouse=True, params=[pytest.param("automation-lead-prosper", id="lead-prosper")])
def ensure_native_db_pool():
    """Keep every native case selectable by the canonical integration slug."""
    yield


def node(config):
    return NodeFactory.create_node(node_id='lead-prosper-test', node_type='automation-lead-prosper',
        node_data={'config': config, 'credentials': {'credential_type': native.CREDENTIAL_TYPE, 'api_token': TOKEN}})


def transport(monkeypatch, responder):
    requests = []
    def respond(request):
        requests.append(request)
        return responder(request) if callable(responder) else httpx.Response(200, json=responder)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', CASES)
async def test_lead_prosper_documented_response_and_exact_endpoint(monkeypatch, operation):
    case = CASES[operation]
    requests = transport(monkeypatch, case['body'])
    result = await node(case['config']).execute({})
    assert result['status'] == 'success'
    assert len(requests) == 1
    req = requests[0]
    expected = case['path']
    for k, v in case['config'].items():
        expected = expected.replace('{'+k+'}', str(v))
    expected = expected.replace('/{scope}', '').replace('/{target}', '')
    assert req.url.path == '/public' + expected
    assert req.method == case['method']
    assert req.url.host == 'api.leadprosper.io'
    assert req.headers['Authorization'] == 'Bearer ' + TOKEN
    assert TOKEN not in str(result) and TOKEN not in str(req.url)
    if operation == 'set_caps':
        assert json.loads(req.content) == {'leads': {'day': 100, 'total': 5000}}
    elif operation == 'return_lead':
        assert json.loads(req.content) == {'lead_id': case['config']['lead_id'], 'reason': 'test return'}
    elif operation == 'list_leads':
        assert dict(req.url.params) == {k: str(v) for k,v in case['config'].items() if k != 'operation'}
    elif operation.startswith(('pause_', 'resume_')):
        assert not req.content


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [400, 401, 403, 404, 422, 429, 500, 302])
async def test_lead_prosper_error_status_and_secret_redaction(monkeypatch, status):
    transport(monkeypatch, lambda req: httpx.Response(status, json={'status': 'error', 'message': 'Refused ' + TOKEN}))
    with pytest.raises(ValueError) as exc:
        await node({'operation': 'list_campaigns'}).execute({})
    assert TOKEN not in str(exc.value) and str(status) in str(exc.value)


@pytest.mark.asyncio
async def test_lead_prosper_documented_missing_lead(monkeypatch):
    transport(monkeypatch, [])
    result = await node({'operation': 'get_lead', 'id': 'missing'}).execute({})
    assert result['data'] == []


@pytest.mark.asyncio
async def test_lead_prosper_token_only_header_and_opaque_cursor(monkeypatch):
    requests = transport(monkeypatch, CASES['list_clients']['body'])
    await node({'operation': 'list_clients', 'search_after': 'opaque+/=cursor', 'include_deleted': False}).execute({})
    assert requests[0].url.params['search_after'] == 'opaque+/=cursor'
    assert requests[0].url.params['include_deleted'] == 'false'


@pytest.mark.asyncio
async def test_lead_prosper_new_lead_documented_payload_dedup_and_agent(monkeypatch):
    payload = copy.deepcopy(CASES['list_leads']['body'])
    requests = transport(monkeypatch, payload)
    n = node({'operation': 'on_new_lead', 'campaign': 6889})
    state = {}
    async def update(mutator, **kwargs):
        nonlocal state
        next_state, result = mutator(state)
        if next_state is not None:
            state = next_state
        return result
    monkeypatch.setattr(n, '_update_node_state', update)
    baseline = await n.execute({})
    assert baseline['new_lead_count'] == 0
    state['seen_ids'] = [payload['leads'][0]['id']]
    fresh = await n.execute({})
    assert fresh['leads'] == payload['leads'][1:] and fresh['new_lead_count'] == len(payload['leads']) - 1
    assert fresh['search_after'] == payload['search_after'] and fresh['snapshot_limit'] == 500
    assert n.trigger_emitted_event(fresh)
    event = n.resolve_agent_event(fresh)
    assert payload['leads'][1]['id'] in event['text'] and payload['leads'][1]['campaign_name'] in event['text']
    assert (await n.execute({}))['leads'] == []
    assert len(requests) == 3
    assert requests[0].url.params['limit'] == '500'
    assert requests[0].url.params['campaign'] == '6889'
    assert requests[0].url.params['timezone'] == 'UTC'


@pytest.mark.asyncio
async def test_lead_prosper_poll_invalid_page_does_not_mark_seen(monkeypatch):
    transport(monkeypatch, {'leads': [{'lead_date_ms': '1787567060007'}], 'search_after': None})
    n = node({'operation': 'on_new_lead', 'campaign': 6889})
    async def forbidden(*args, **kwargs):
        raise AssertionError('Never mark seen on malformed responses')
    monkeypatch.setattr(n, '_filter_unseen', forbidden)
    with pytest.raises(ValueError, match='invalid leads page'):
        await n.execute({})


@pytest.mark.asyncio
async def test_lead_prosper_decimal_lead_cursor_roundtrip(monkeypatch):
    payload = CASES['list_leads']['body']
    requests = transport(monkeypatch, payload)
    cfg = {**CASES['list_leads']['config'], 'search_after': payload['search_after']}
    await node(cfg).execute({})
    assert requests[0].url.params['search_after'] == payload['search_after']


def test_lead_prosper_poll_scope_uses_only_declared_fields():
    cfg = {'operation': 'on_new_lead', 'campaign': 6889}
    assert poll_scope(native.LeadProsperNode, cfg) == poll_scope(native.LeadProsperNode, {**cfg, 'label': 'Renamed'})
    assert poll_scope(native.LeadProsperNode, cfg) != poll_scope(native.LeadProsperNode, {**cfg, 'campaign': 8977})
    assert poll_scope(native.LeadProsperNode, cfg) != poll_scope(native.LeadProsperNode, {**cfg, 'lookback_hours': 24})


@pytest.mark.parametrize('config', [
    {'operation': 'update_campaign', 'campaign': 112},
    {'operation': 'set_caps', 'campaign': 112, 'scope': 'buyers', 'target': 571},
    {'operation': 'list_caps', 'campaign': 112, 'target': 571},
    {'operation': 'list_leads', 'campaign': 6889, 'start_date': '2026-08-25', 'end_date': '2026-08-01'},
    {'operation': 'list_filters', 'campaign': 112, 'scope': 'global', 'target': 571},
])
def test_lead_prosper_invalid_config_refused(config):
    with pytest.raises(ValueError):
        native.LeadProsperNode.parse_config({'config': config})


def test_lead_prosper_manual_credential_default():
    credential = native.LeadProsperAPITokenCredential(api_token=TOKEN)
    assert credential.credential_type == native.CREDENTIAL_TYPE
    assert not native.LeadProsperAPITokenCredential.model_fields['credential_type'].is_required()
    for bad in ['Bearer bad token', 'https://example.com/key', '<token>']:
        with pytest.raises(ValidationError):
            native.LeadProsperAPITokenCredential(api_token=bad)
