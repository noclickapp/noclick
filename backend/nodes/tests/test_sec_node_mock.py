"""SEC published examples exercised through the registered node, without accounts."""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import sec_node as native
from nodes.core.registry import NodeFactory

EXAMPLES = json.loads((Path(__file__).parent / 'fixtures/sec/contract_examples.json').read_text())
CREDENTIAL = {'credential_type': native.TYPE, 'filer_api_token': 'synthetic-filer-token',
              'user_api_token': 'synthetic-user-token', 'cik': '0000000000'}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def config_for(operation):
    config = {'operation': operation}
    example = EXAMPLES[operation]
    if 'request' in example:
        field = {'request_delegation_invitations': 'ciks', 'send_delegation_invitations': 'ciks',
                 'add_individuals': 'individuals', 'change_individual_roles': 'individuals',
                 'remove_individuals': 'emails', 'get_multiple_submission_statuses': 'accession_numbers'}[operation]
        config[field] = example['request']['accessionNumbers'] if field == 'accession_numbers' else example['request']
    if operation == 'get_submission_status':
        config['accession_number'] = '0000000000-24-000001'
    return config


def node(config):
    return NodeFactory.create_node(node_id='sec-test', node_type='automation-sec',
        node_data={'config': config, 'credentials': CREDENTIAL})


def transport(monkeypatch, body, status=200):
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(status, json=body) if status != 204 else httpx.Response(204)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', EXAMPLES)
async def test_published_requests_and_responses(monkeypatch, operation):
    example = EXAMPLES[operation]
    calls = transport(monkeypatch, example['response'])
    result = await node(config_for(operation)).execute({})
    assert result['status'] == 'success'
    assert len(calls) == 1
    request = calls[0]
    assert request.method == example['method']
    assert str(request.url) == native.BASE + example['path'].format(cik=CREDENTIAL['cik'], accessionNumber='0000000000-24-000001')
    expected = 'Bearer ' + CREDENTIAL['filer_api_token']
    if '/fm/' in example['path']:
        expected += ',' + CREDENTIAL['user_api_token']
    assert request.headers['authorization'] == expected
    if 'request' in example:
        assert json.loads(request.content) == example['request']
    else:
        assert request.content == b''
    assert CREDENTIAL['filer_api_token'] not in str(result)
    assert CREDENTIAL['user_api_token'] not in str(result)
    if operation == 'get_filer_account':
        assert result['items'][0]['entityName'] == 'Filers Inc'
        assert 'ccc' not in result['items'][0]


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 401, 403, 404, 429, 500])
async def test_failure_is_not_evidence_and_never_follows_or_retries(monkeypatch, status):
    calls = transport(monkeypatch, {'messages': [{'type': 'ERROR', 'content': CREDENTIAL['user_api_token']}]}, status)
    result = await node({'operation': 'get_filer_account'}).execute({})
    assert result['status'] == 'error' and result['http_status'] == status
    assert len(calls) == 1 and 'items' not in result
    assert CREDENTIAL['user_api_token'] not in str(result)


@pytest.mark.asyncio
async def test_200_error_envelope_and_multiple_status_no_content(monkeypatch):
    transport(monkeypatch, {'messages': [{'type': 'ERROR', 'content': 'Forbidden'}]})
    assert (await node({'operation': 'get_filer_account'}).execute({}))['status'] == 'error'
    transport(monkeypatch, None, 204)
    result = await node(config_for('get_multiple_submission_statuses')).execute({})
    assert result['status'] == 'success' and result['items'] == []


@pytest.mark.asyncio
async def test_alternate_cik_and_false_role_values(monkeypatch):
    calls = transport(monkeypatch, EXAMPLES['change_individual_roles']['response'])
    config = config_for('change_individual_roles')
    config['cik'] = '0000000001'
    await node(config).execute({})
    assert calls[0].url.path == '/fm/0000000001/individuals'
    assert json.loads(calls[0].content)[0]['inAdminRole'] is False


@pytest.mark.parametrize('config', [
    {'operation': 'get_filer_account', 'cik': '../status'},
    {'operation': 'get_submission_status', 'accession_number': '../status'},
    {'operation': 'get_multiple_submission_statuses', 'accession_numbers': []},
    {'operation': 'get_multiple_submission_statuses', 'accession_numbers': ['0000000000-24-000001'] * 26},
    {'operation': 'send_delegation_invitations', 'ciks': ['1']},
    {'operation': 'remove_individuals', 'emails': ['not-email']},
    {'operation': 'get_system_status', 'url': 'https://other.test'},
])
def test_bad_inputs_fail_before_network(config):
    with pytest.raises(ValueError):
        native.SecNode.parse_config({'config': config, 'credentials': CREDENTIAL})


def test_manual_credential_default_and_token_boundaries():
    assert native.SecAPITokensCredential.model_validate({k: v for k, v in CREDENTIAL.items() if k != 'credential_type'}).credential_type == native.TYPE
    for value in ['Bearer secret', 'one,two', 'bad\r\nheader', 'https://secret.test']:
        with pytest.raises(ValidationError):
            native.SecAPITokensCredential.model_validate({**CREDENTIAL, 'filer_api_token': value})
