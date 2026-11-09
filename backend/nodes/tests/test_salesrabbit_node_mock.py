"""Exercise every SalesRabbit operation with provider-published response examples."""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import salesrabbit_node as native
from nodes.core.registry import NodeFactory

EXAMPLES = json.loads((Path(__file__).parent / 'fixtures/salesrabbit/contract_examples.json').read_text())
TOKEN = 'salesrabbit-synthetic-key'


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, **credentials):
    return NodeFactory.create_node(node_id='salesrabbit-test', node_type='automation-salesrabbit',
        node_data={'config': config, 'credentials': {'credential_type': 'salesrabbit_api_key', 'api_key': TOKEN, **credentials}})


def mock_client(monkeypatch, handler):
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False
        assert kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', list(native.OPERATIONS))
async def test_published_examples_and_exact_requests(monkeypatch, operation):
    config = EXAMPLES['inputs'][operation]
    example = EXAMPLES['responses'][operation]
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(example['status'], json=example['body']) if example['body'] is not None else httpx.Response(example['status'])
    mock_client(monkeypatch, handle)
    result = await node(config).execute({})
    method, path = native.OPERATIONS[operation]
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert request.url.path == path.replace('{id}', config.get('id', ''))
    assert request.headers['Authorization'] == 'Bearer ' + TOKEN
    assert request.url.host == 'integrate.salesrabbit.com'
    if method in {'POST', 'PATCH'}:
        sent = json.loads(request.content)['data']
        attrs = {k: v for k, v in config.items() if k not in {'operation', 'id'}}
        assert sent['attributes'] == attrs
        if method == 'PATCH' and operation != 'update_lead':
            assert sent['id'] == config['id']
        assert request.headers['Content-Type'] == ('application/vnd.api+json' if operation in {'create_lead', 'update_lead'} else 'application/json')
    if operation.startswith('list_'):
        assert dict(request.url.params) == {'page[limit]': '25', 'page[offset]': '0'}
        assert result['has_more'] is (operation not in {'list_teams', 'list_areas'})
        assert result['next_offset'] == (None if operation in {'list_teams', 'list_areas'} else 1)
    assert result['status'] == 'success'
    assert TOKEN not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [401, 403, 429, 500])
async def test_failure_not_success_and_no_retry(monkeypatch, status):
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(status, json={'error': 'Provider rejected ' + TOKEN})
    mock_client(monkeypatch, handle)
    with pytest.raises(ValueError, match=f'HTTP {status}') as exc:
        await node({'operation': 'list_profiles'}).execute({})
    assert TOKEN not in str(exc.value)
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_ireland_and_untrusted_next_link(monkeypatch):
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(200, json={'data': [], 'links': {'next': 'https://attacker.invalid/leak?page[offset]=15'}})
    mock_client(monkeypatch, handle)
    result = await node({'operation': 'list_profiles', 'offset': 10, 'limit': 5}, region='Ireland').execute({})
    assert len(requests) == 1 and requests[0].url.host == 'integrate.ireland.salesrabbit.com'
    assert result['next_offset'] == 15


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{'error': 'rejected'}, {'errors': []}, {'data': None}, {'data': {}}, []])
async def test_bad_list_response_refused(monkeypatch, body):
    mock_client(monkeypatch, lambda request: httpx.Response(200, json=body))
    with pytest.raises(ValueError):
        await node({'operation': 'list_profiles'}).execute({})


def test_manual_credential_default_and_secret_shape():
    assert native.SalesRabbitAPIKeyCredential(api_key=TOKEN).credential_type == 'salesrabbit_api_key'
    for value in ['Bearer key', 'https://example.com/key']:
        with pytest.raises(ValidationError):
            native.SalesRabbitAPIKeyCredential(api_key=value)


def test_uuid_and_page_bounds():
    for config in [{'operation': 'get_lead', 'id': '../profiles'}, {'operation': 'list_leads', 'limit': 251}, {'operation': 'list_profiles', 'offset': -1}]:
        with pytest.raises(ValueError):
            node(config)


@pytest.mark.asyncio
async def test_empty_update_never_sent(monkeypatch):
    mock_client(monkeypatch, lambda request: pytest.fail('empty update was sent'))
    with pytest.raises(ValueError, match='at least one field'):
        await node({'operation': 'update_lead', 'id': '123e4567-e89b-12d3-a456-426614174000'}).execute({})


@pytest.mark.asyncio
async def test_connection_evidence_names_the_account_representatives(monkeypatch):
    from nodes.core.connection_evidence import _label_from, _rows_from_operation
    example = EXAMPLES['responses']['list_profiles']['body']
    mock_client(monkeypatch, lambda request: httpx.Response(200, json=example))
    result = await node({'operation': 'list_profiles'}).execute({})
    rows = _rows_from_operation(result)
    assert _label_from(rows[0], native.SalesRabbitNode.connection_evidence.label_keys) == 'John Doe'
