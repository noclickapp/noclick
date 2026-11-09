"""Cin7 Core contract examples at the HTTP boundary; no provider account needed."""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import cin7_core_node as native
from nodes.core.registry import NodeFactory

FIXTURES = Path(__file__).parent / 'fixtures/cin7-core'
CONFIGS = json.loads((FIXTURES / 'requests.json').read_text())
RESPONSES = json.loads((FIXTURES / 'responses.json').read_text())
CREDENTIAL = {'credential_type': 'cin7_core_api_key', 'account_id': 'synthetic-account-42', 'application_key': 'synthetic-key-42'}
ID = '524c20a3-a8ec-44f2-9685-311f1f7d1498'
CASES = [
    ('get_me', 'GET', '/me'),
    ('list_products', 'GET', '/product'), ('create_product', 'POST', '/product'), ('update_product', 'PUT', '/product'),
    ('list_customers', 'GET', '/customer'), ('create_customer', 'POST', '/customer'), ('update_customer', 'PUT', '/customer'),
    ('list_suppliers', 'GET', '/supplier'), ('create_supplier', 'POST', '/supplier'), ('update_supplier', 'PUT', '/supplier'),
    ('list_product_availability', 'GET', '/ref/productavailability'), ('list_locations', 'GET', '/ref/location'),
    ('list_sales', 'GET', '/saleList'), ('get_sale', 'GET', '/sale'),
    ('list_purchases', 'GET', '/purchaseList'), ('get_purchase', 'GET', '/purchase'),
    ('list_stock_adjustments', 'GET', '/stockadjustmentList'), ('get_stock_adjustment', 'GET', '/stockadjustment'),
    ('create_stock_adjustment', 'POST', '/stockadjustment'), ('update_stock_adjustment', 'PUT', '/stockadjustment'),
    ('list_categories', 'GET', '/ref/category'), ('create_category', 'POST', '/ref/category'), ('update_category', 'PUT', '/ref/category'),
]


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='cin7-fixture', node_type='automation-cin7-core',
        node_data={'config': config, 'credentials': CREDENTIAL})


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
@pytest.mark.parametrize('operation,method,path', CASES)
async def test_cin7_core_documented_operations_through_factory(monkeypatch, operation, method, path):
    config = CONFIGS.get(operation, {'operation': operation})
    if operation in {'get_sale', 'get_purchase', 'update_category'}:
        config = {**config, 'id': ID}
    if operation == 'get_stock_adjustment':
        config = {**config, 'task_id': ID}
    if operation in {'create_category', 'update_category'}:
        config = {**config, 'name': 'Test'}
    body = RESPONSES[method + ' ' + path]
    requests = transport(monkeypatch, body)
    result = await node(config).execute({})
    assert result['status'] == 'success' and result['data'] == body
    assert result.get('acknowledged', False) is (method != 'GET')
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert str(request.url).split('?')[0] == 'https://inventory.dearsystems.com/ExternalApi/v2' + path
    assert request.headers['api-auth-accountid'] == CREDENTIAL['account_id']
    assert request.headers['api-auth-applicationkey'] == CREDENTIAL['application_key']
    assert 'authorization' not in request.headers
    if method != 'GET':
        payload = json.loads(request.content)
        assert 'operation' not in payload
        assert payload.get('Name', payload.get('EffectiveDate')) is not None
        if operation.startswith('create_'):
            assert 'ID' not in payload and 'TaskID' not in payload
        if operation == 'update_stock_adjustment':
            assert payload['TaskID'] == config['task_id']
            assert payload['Lines'][0]['ProductID'] == config['lines'][0]['ProductID']


@pytest.mark.asyncio
async def test_cin7_core_query_case_pagination_and_false(monkeypatch):
    requests = transport(monkeypatch, RESPONSES['GET /ref/productavailability'])
    result = await node({'operation': 'list_product_availability', 'page': 2, 'limit': 50,
        'sku': 'Bread + café', 'non_zero_products_only': False}).execute({})
    assert dict(requests[0].url.params) == {'Page': '2', 'Limit': '50', 'Sku': 'Bread + café', 'NonZeroProductsOnly': 'false'}
    assert result['data']['Total'] == 4 and result['data']['Page'] == 1
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [202, 204, 301, 400, 401, 403, 404, 429, 500])
async def test_cin7_core_errors_are_redacted_and_never_retried(monkeypatch, status):
    requests = transport(monkeypatch, [{'Exception': 'Rejected ' + CREDENTIAL['application_key']}], status)
    result = await node({'operation': 'get_me'}).execute({})
    assert result['status'] == 'error' and result['http_status'] == status
    assert CREDENTIAL['application_key'] not in str(result) and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{}, [], {'Exception': 'invalid'}, {'Company': ''}, {'Company': 42}])
async def test_cin7_core_connection_needs_company_identity(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError):
        await node({'operation': 'get_me'}).execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{}, {'Products': {}}, {'Products': [1], 'Total': 1, 'Page': 1}, {'Products': [], 'Total': True, 'Page': 1}])
async def test_cin7_core_incomplete_collection_is_not_success(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError):
        await node({'operation': 'list_products'}).execute({})


def test_cin7_core_hand_connect_and_schema_bounds():
    credential = native.Cin7CoreAPIKeyCredential(account_id=' synthetic-account-42 ', application_key=' synthetic-key-42 ')
    assert credential.credential_type == 'cin7_core_api_key' and credential.account_id == CREDENTIAL['account_id']
    assert native.Cin7CoreNode.connection_evidence.identity_operation == 'get_me'
    for config in [{'operation': 'list_products', 'limit': 1001}, {'operation': 'list_products', 'page': 0},
        {'operation': 'get_sale'}, {'operation': 'update_category', 'name': 'Test'},
        {'operation': 'get_me', 'url': 'https://other.example'}, {'operation': 'list_products', 'page': True}]:
        with pytest.raises(ValidationError):
            native.Cin7CoreFullConfig.model_validate({'config': config, 'credentials': CREDENTIAL})
    with pytest.raises(ValidationError):
        native.NewStockLineModel(Quantity=1, UnitCost=1)
