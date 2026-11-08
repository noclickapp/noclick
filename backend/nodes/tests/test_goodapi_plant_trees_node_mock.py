"""Request and response regressions against GoodAPI v2 published examples.

Source: https://app.thegoodapi.com/openapi.json. No live impact writes.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import goodapi_plant_trees_node as native
from nodes.core.registry import NodeFactory

EXAMPLES = json.loads((Path(__file__).parent / 'fixtures/goodapi-plant-trees/contract_examples.json').read_text())
TOKEN = 'test_sk_goodapi_fixture_123'


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='goodapi-fixture', node_type=native.GoodapiPlantTreesNode.integration_type,
        node_data={'config': config, 'credentials': {'credential_type': native.CREDENTIAL_TYPE, 'api_key': TOKEN}})


def transport(monkeypatch, body, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', EXAMPLES)
async def test_goodapi_plant_trees_documented_requests_and_responses(monkeypatch, operation):
    example = EXAMPLES[operation]
    body = example['response']
    if body is None:  # Minimal valid project shapes: the contract has no examples.
        body = {'projects': []} if operation == 'list_tree_projects' else {'id': 'veritree-kenya'}
    requests = transport(monkeypatch, body)
    result = await node(example['config']).execute({})
    assert result['status'] == 'success' and result['data'] == body
    assert len(requests) == 1
    req = requests[0]
    assert req.headers['Authorization'] == TOKEN
    assert req.method == example['method'] and req.url.host == 'app.thegoodapi.com'
    values = node(example['config']).config.config.model_dump(mode='json', exclude_none=True, exclude={'operation'})
    route = example['path']
    if '{id}' in route:
        route = route.replace('{id}', values.pop('id'))
    assert req.url.path == route
    if req.method == 'POST':
        assert (json.loads(req.content) if req.content else {}) == values
    else:
        assert dict(req.url.params) == {k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in values.items()}


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 400, 401, 403, 404, 429, 500])
async def test_goodapi_plant_trees_errors_never_retry_or_leak_key(monkeypatch, status):
    requests = transport(monkeypatch, {'error': 'Rejected ' + TOKEN}, status)
    result = await node({'operation': 'plant_trees', 'count': 1, 'idempotency_key': 'order-1234'}).execute({})
    assert result['status'] == 'error' and result['http_status'] == status
    assert TOKEN not in str(result) and len(requests) == 1


@pytest.mark.asyncio
async def test_goodapi_plant_trees_query_dates_metadata_boolean_and_partial_refund(monkeypatch):
    requests = transport(monkeypatch, {})
    await node({'operation': 'list_planted_trees', 'created_at': '2026-05-01', 'end_at': '2026-05-19', 'metadata': '{"order_id":786}'}).execute({})
    assert dict(requests[0].url.params) == {'created_at': '2026-05-01', 'end_at': '2026-05-19', 'metadata': '{"order_id":786}'}
    await node({'operation': 'list_tree_projects', 'all': True, 'locale': 'fr'}).execute({})
    assert dict(requests[1].url.params) == {'all': 'true', 'locale': 'fr'}
    await node({'operation': 'refund_trees', 'id': 'tree-1', 'count': 2, 'idempotency_key': 'refund-1', 'metadata': {'order': 786}}).execute({})
    assert json.loads(requests[2].content) == {'id': 'tree-1', 'count': 2, 'idempotency_key': 'refund-1', 'metadata': {'order': 786}}


@pytest.mark.asyncio
async def test_goodapi_plant_trees_account_evidence_preserves_identity(monkeypatch):
    body = {'org_id': 'org_abc123', 'dashboard_url': 'https://dashboard.thegoodapi.com/org_abc123?source=apiv2'}
    requests = transport(monkeypatch, body)
    evidence = native.GoodapiPlantTreesNode.connection_evidence
    assert evidence.identity_operation == 'get_dashboard_url' and evidence.proves == 'account'
    result = await node({'operation': evidence.identity_operation}).execute({})
    assert result['org_id'] == body['org_id'] and requests[0].method == 'GET'


@pytest.mark.parametrize('config', [
    {'operation': 'plant_trees', 'count': 0},
    {'operation': 'create_donation', 'amount_cents': 50},
    {'operation': 'refund_trees'},
    {'operation': 'list_donations', 'page_size': 101},
    {'operation': 'search_charities', 'page_size': 21},
    {'operation': 'get_tree_evidence', 'id': 'tree-1', 'evidence_stage': 'invalid'},
    {'operation': 'get_dashboard_url', 'url': 'https://evil.example/'},
])
def test_goodapi_plant_trees_invalid_input(config):
    with pytest.raises((ValueError, ValidationError)):
        node(config)


def test_goodapi_plant_trees_manual_credential_default():
    cred = native.GoodapiPlantTreesCredential(api_key=TOKEN)
    assert cred.credential_type == native.CREDENTIAL_TYPE
    assert native.GoodapiPlantTreesCredential.model_fields['credential_type'].is_required() is False
