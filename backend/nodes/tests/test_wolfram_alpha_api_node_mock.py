"""Verify AppID transport, computational task queries and connection evidence.

The provider's published text example exercises the real factory and parser;
HTTP failures verify that rejected keys and outages never become successes.
"""
from pathlib import Path
import json
import httpx
import pytest
from pydantic import ValidationError
from nodes import wolfram_alpha_api_node as native
from nodes.core.registry import NodeFactory

TOKEN = 'synthetic-wolfram-app-id-42'
CASES = [
    ({'operation': 'check_connection'}, '10 densest elemental metals'),
    ({'operation': 'query', 'input': '10 densest elemental metals'}, '10 densest elemental metals'),
    ({'operation': 'calculate', 'expression': '2+2'}, '2+2'),
    ({'operation': 'solve_equation', 'equation': 'x^2=4', 'variable': 'x'}, 'solve x^2=4 for x'),
    ({'operation': 'integrate', 'expression': 'sin(x)', 'variable': 'x'}, 'integrate sin(x) with respect to x'),
    ({'operation': 'differentiate', 'expression': 'x^2', 'variable': 'x'}, 'differentiate x^2 with respect to x'),
    ({'operation': 'convert_units', 'quantity': '5 miles', 'target_unit': 'km'}, 'convert 5 miles to km'),
    ({'operation': 'statistics', 'values': '1,2,3'}, 'descriptive statistics {1,2,3}'),
    ({'operation': 'factor_integer', 'integer': 42}, 'factor 42'),
    ({'operation': 'currency_conversion', 'amount': '100 USD', 'target_currency': 'EUR'}, 'convert 100 USD to EUR'),
    ({'operation': 'date_difference', 'start_date': 'January 1, 2025', 'end_date': 'January 2, 2025'}, 'days between January 1, 2025 and January 2, 2025'),
]


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='wolfram-fixture', node_type='automation-wolfram-alpha-api',
        node_data={'config': config, 'credentials': {'credential_type': 'wolfram_alpha_api_app_id', 'app_id': TOKEN}})


def transport(monkeypatch, respond):
    requests = []
    def handler(request):
        requests.append(request)
        return respond(request)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('config,expected', CASES)
async def test_one_contract_get_per_task_and_provider_text(monkeypatch, config, expected):
    body = json.loads((Path(__file__).parent / 'fixtures/wolfram-alpha-api/llm-result.json').read_text())['body']
    requests = transport(monkeypatch, lambda r: httpx.Response(200, text=body))
    result = await node(config).execute({})
    assert result['status'] == 'success' and result['result'] == body
    assert result['identity_verified'] is False
    assert len(requests) == 1
    r = requests[0]
    assert r.method == 'GET' and str(r.url.copy_with(query=None)) == native.BASE
    assert dict(r.url.params) == {'input': expected}
    assert r.headers['authorization'] == 'Bearer ' + TOKEN
    assert TOKEN not in str(r.url) and r.content == b''


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 400, 401, 403, 429, 500, 501, 503])
async def test_provider_errors_preserve_explanation_and_redact_key(monkeypatch, status):
    requests = transport(monkeypatch, lambda r: httpx.Response(status, text='Invalid appid: ' + TOKEN,
        headers={'Location': 'https://example.org/'}))
    result = await node({'operation': 'check_connection'}).execute({})
    assert result['status'] == 'error' and result['status_code'] == status
    assert result['message'] == 'Invalid appid: [redacted]' and TOKEN not in str(result)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('response', [httpx.Response(200, text=''), httpx.Response(200, text='<html>Login</html>', headers={'content-type': 'text/html'}), httpx.Response(200, json={'error': 'bad key'})])
async def test_empty_or_nontext_never_proves_connection(monkeypatch, response):
    transport(monkeypatch, lambda r: response)
    assert (await node({'operation': 'check_connection'}).execute({}))['status'] == 'error'


@pytest.mark.asyncio
async def test_network_failure_hides_url_and_credentials(monkeypatch):
    def fail(r):
        raise httpx.ConnectError('network failed ' + TOKEN, request=r)
    transport(monkeypatch, fail)
    result = await node({'operation': 'check_connection'}).execute({})
    assert result['status'] == 'error' and TOKEN not in str(result)


def test_hand_connect_and_invalid_config():
    assert native.WolframAlphaApiCredential(app_id='  '+TOKEN+' ').model_dump() == {
        'credential_type': 'wolfram_alpha_api_app_id', 'app_id': TOKEN}
    for value in ['', '<token>', 'https://example.org/key', 'Bearer abc', 'key\nvalue']:
        with pytest.raises(ValidationError):
            native.WolframAlphaApiCredential(app_id=value)
    for config in [{'operation':'query'}, {'operation':'query','input':'\n'}, {'operation':'factor_integer','integer':True}, {'operation':'delete'}, {'operation':'calculate','expression':'1','host':'https://example.org'}]:
        with pytest.raises(ValueError):
            node(config)


@pytest.mark.asyncio
@pytest.mark.parametrize('status,message,reachable', [(200,'Query: 2+2\nResult: 4',True), (403,'Invalid appid',False), (503,'Service temporarily unavailable',None)])
async def test_connection_evidence_distinguishes_key_rejection_from_outage(monkeypatch, status, message, reachable):
    from nodes.core.connection_evidence import collect_evidence
    from nodes.core import run_op
    transport(monkeypatch, lambda r: httpx.Response(status, text=message))
    async def run(**kwargs):
        assert kwargs['operation'] == 'check_connection'
        return await node({'operation': kwargs['operation']}).execute({})
    monkeypatch.setattr(run_op, 'run_node_operation', run)
    result = await collect_evidence(node_type='automation-wolfram-alpha-api', user_id='synthetic-user',
        credential_data={'credential_type':'wolfram_alpha_api_app_id','app_id':TOKEN})
    assert result.reachable is reachable
    if status == 403:
        assert message in result.error
