"""Every operation uses the provider's published response property examples.

Source URLs and the unmodified spec hash are pinned beside the fixtures.
The full legacy clients response is from:
https://invoiceninja.github.io/docs/developer-guide/api/clients
"""
import json
from pathlib import Path
from unittest.mock import Mock, patch
import httpx
import pytest
from pydantic import ValidationError
from nodes.invoiceninja_node import InvoiceNinjaAPITokenCredential, InvoiceNinjaNode, InvoiceNinjaNodeConfig, OPERATIONS

FIXTURES = Path(__file__).parent / 'fixtures' / 'invoiceninja'
EXAMPLES = json.loads((FIXTURES / 'documented_examples.json').read_text())
TOKEN = 'test-invoiceninja-token'


def node(operation, config=None, credentials=None):
    return InvoiceNinjaNode(node_id='test', node_type='automation-invoiceninja', node_data={}, sio=Mock(),
        config=InvoiceNinjaNodeConfig.model_validate({
            'config': {'operation': operation, **(config if config is not None else EXAMPLES[operation]['config'])},
            'credentials': credentials or {'api_token': TOKEN}}))


async def execute(operation, handler, config=None, credentials=None):
    real_client = httpx.AsyncClient
    with patch('nodes.invoiceninja_node.guarded_async_client', side_effect=lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw)) as factory:
        result = await node(operation, config, credentials).execute({})
    factory.assert_called_once_with(timeout=30.0, follow_redirects=False)
    return result


@pytest.mark.parametrize('operation', EXAMPLES)
async def test_documented_operation(operation):
    example = EXAMPLES[operation]
    seen = []
    def handler(request):
        seen.append(request)
        assert request.method == example['method']
        assert request.url.path == example['path']
        assert request.url.host == 'invoicing.co'
        assert request.headers['X-API-TOKEN'] == TOKEN
        assert request.headers['X-Requested-With'] == 'XMLHttpRequest'
        assert request.headers['Accept'] == 'application/json'
        assert TOKEN not in str(request.url)
        if example['request_body'] is None:
            assert not request.content
            expected = {k: str(v) for k, v in example['config'].items()} if operation.startswith('list_') else {}
            assert dict(request.url.params) == expected
        else:
            assert json.loads(request.content) == example['request_body']
        return httpx.Response(200, json=example['response'])
    result = await execute(operation, handler)
    assert len(seen) == 1
    assert result['status'] == 'success'
    assert result['action'] == operation
    assert result['data'] == example['response'].get('data', example['response'])
    assert result['status_code'] == 200
    assert result['timing_ms']['api_request'] >= 0


def test_every_operation_has_a_documented_fixture():
    assert set(EXAMPLES) == set(OPERATIONS)
    assert len(EXAMPLES) == 20


async def test_full_published_client_response_and_pagination():
    published = json.loads((FIXTURES / 'clients_legacy_response.json').read_text())
    result = await execute('list_clients', lambda r: httpx.Response(200, json=published['body']))
    assert result['status'] == 'success'
    assert result['data'] == published['body']['data']
    assert result['meta'] == published['body']['meta']
    assert result['data'][0]['name'] == "O'Reilly-Metz"


async def test_empty_account_is_a_successful_read():
    result = await execute('list_clients', lambda r: httpx.Response(200, json={'data': []}))
    assert result['status'] == 'success'
    assert result['data'] == []


async def test_runtime_entity_envelope():
    entity = EXAMPLES['get_invoice']['response']
    result = await execute('get_invoice', lambda r: httpx.Response(200, json={'data': entity}))
    assert result['data'] == entity


@pytest.mark.parametrize('status', [401, 403, 404, 422, 429, 500])
async def test_provider_errors(status):
    result = await execute('list_clients', lambda r: httpx.Response(status, json={'message': 'Provider rejected this request'}))
    assert result['status'] == 'error'
    assert result['status_code'] == status
    assert result['error'] == 'Provider rejected this request'


async def test_secret_is_redacted_from_error():
    result = await execute('list_clients', lambda r: httpx.Response(401, json={'message': 'Invalid ' + TOKEN}))
    assert TOKEN not in json.dumps(result)


@pytest.mark.parametrize('body', [None, {}, {'data': 'bad'}, {'data': [1]}])
async def test_malformed_list_response(body):
    result = await execute('list_clients', lambda r: httpx.Response(200, json=body))
    assert result['status'] == 'error'


async def test_non_json_response():
    result = await execute('list_clients', lambda r: httpx.Response(200, text='<html>Sign in</html>'))
    assert result['status'] == 'error'


async def test_timeout_does_not_expose_request():
    def handler(request):
        raise httpx.ReadTimeout(TOKEN, request=request)
    result = await execute('list_clients', handler)
    assert result['status'] == 'error'
    assert TOKEN not in json.dumps(result)


async def test_redirect_is_not_followed_with_token():
    result = await execute('list_clients', lambda r: httpx.Response(302, headers={'Location': 'https://example.org'}))
    assert result['status_code'] == 302
    assert result['status'] == 'error'


@pytest.mark.parametrize('raw', ['invalid', '{}', '[1]'])
async def test_invalid_line_items_fail_before_network(raw):
    cfg = {**EXAMPLES['create_invoice']['config'], 'line_items_json': raw}
    with patch('nodes.invoiceninja_node.guarded_async_client') as factory:
        with pytest.raises(ValueError, match='JSON array'):
            await node('create_invoice', cfg).execute({})
    factory.assert_not_called()


@pytest.mark.parametrize('url', ['http://example.com', 'https://user:password@example.com'])
def test_invalid_server_url(url):
    with pytest.raises(ValidationError):
        InvoiceNinjaAPITokenCredential(api_token=TOKEN, base_url=url)


def test_pasted_server_url_is_normalized():
    creds = InvoiceNinjaAPITokenCredential(api_token=TOKEN, base_url='https://billing.example.com/#/settings')
    assert creds.base_url == 'https://billing.example.com'


async def test_self_hosted_requests_use_the_guarded_client():
    def handler(request):
        assert request.url.host == 'billing.example.com'
        return httpx.Response(200, json={'data': []})
    result = await execute('list_clients', handler, credentials={'api_token': TOKEN, 'base_url': 'https://billing.example.com'})
    assert result['status'] == 'success'


def test_connection_evidence_uses_an_account_read():
    evidence = InvoiceNinjaNode.connection_evidence
    assert evidence.operation == 'list_clients'
    assert evidence.proves == 'account'
    assert OPERATIONS[evidence.operation][0] == 'GET'
