"""Exercise the real Award Force node through its factory and HTTP boundary.

Provider examples from the pinned v2.3 contract verify request construction,
response handling, regional authentication, failures and manual connection.
"""
import json
from pathlib import Path
from urllib.parse import quote

import httpx
import pytest
from pydantic import ValidationError
from nodes import award_force_node as native
from nodes.core.registry import NodeFactory
from nodes.core.credential_connect import shape_credential

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/award-force/documented.json').read_text())
OPS = FIXTURE['operations']
TOKEN = 'synthetic-award-force-key'


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, region='eu'):
    return NodeFactory.create_node(node_id='award-force-fixture', node_type='automation-award-force',
        node_data={'config': config, 'credentials': {'credential_type': 'award_force_api_key', 'api_key': TOKEN, 'region': region}})


def transport(monkeypatch, status, body=None, *, text=None):
    requests = []
    def reply(request):
        requests.append(request)
        return httpx.Response(status, text=text) if text is not None else httpx.Response(status, json=body) if body is not None else httpx.Response(status)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', OPS)
async def test_award_force_documented_contract_requests_and_responses(monkeypatch, operation):
    example = OPS[operation]
    requests = transport(monkeypatch, example['status'], example['body'])
    result = await node(example['config']).execute({})
    assert result['status'] == 'success', result
    request, = requests
    assert request.method == example['method']
    path = example['path']
    for key, value in example['config'].items():
        path = path.replace('{' + key + '}', quote(str(value), safe=''))
    assert request.url == httpx.URL('https://api.eu.cr4ce.com' + path, params={'page': 1, 'per_page': 10} if operation.startswith('list_') else {})
    assert request.headers['x-api-key'] == TOKEN
    assert request.headers['Accept'] == 'application/vnd.Creative Force.v2.3+json'
    if operation.startswith('list_'):
        assert result['data'] == example['body']['data']
        assert result['has_more'] == (result['next_page'] is not None)
    elif example['body'] is not None:
        assert result['data'] == example['body']
    elif operation == 'create_assignment':
        assert result['accepted'] is True and 'data' not in result
    else:
        assert result['deleted'] is True
    assert TOKEN not in str(result)


@pytest.mark.asyncio
async def test_award_force_write_bodies_do_not_send_config_or_absent_fields(monkeypatch):
    for operation, expected in {
        'create_entry': {'category': 'AbCdEfGh', 'entrant': 'YzAbCdEf', 'season': 'IjKlMnOp', 'title': 'Documentary series', 'entry_fields': {'UvWxYzAb': 'A short film about resilience.'}},
        'update_entry': {'title': 'Documentary series', 'status': 'submitted', 'moderation_status': 'approved', 'entry_fields': {'UvWxYzAb': 'A short film about resilience.'}},
        'update_entry_field': {'value': 'A short film about resilience.'},
        'update_entry_title': {'title': 'Documentary series'},
        'update_user': {'first_name': 'Ada', 'last_name': 'Lovelace'},
        'create_assignment': {'score_set': 'AbCdEfGh', 'entries': ['PqRsTuVw', 'YzAbCdEf'], 'judges': ['IjKlMnOp', 'MnOpQrSt'], 'rounds': ['UvWxYzAb']},
    }.items():
        example = OPS[operation]
        requests = transport(monkeypatch, example['status'], example['body'])
        assert (await node(example['config']).execute({}))['status'] == 'success'
        assert json.loads(requests[0].content) == expected


@pytest.mark.asyncio
async def test_award_force_pagination_filter_and_untrusted_next_url(monkeypatch):
    body = {**OPS['list_entries']['body'], 'current_page': 2, 'last_page': 3, 'next_page_url': 'https://untrusted.example/steal'}
    requests = transport(monkeypatch, 200, body)
    result = await node({'operation': 'list_entries', 'page': 2, 'per_page': 25, 'season': 'AbCdEfGh', 'title': 'A + B', 'status': 'submitted'}).execute({})
    assert result['next_page'] == 3 and result['has_more']
    assert len(requests) == 1
    assert dict(requests[0].url.params) == {'page': '2', 'per_page': '25', 'season': 'AbCdEfGh', 'title': 'A + B', 'status': 'submitted'}


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 302, 400, 401, 403, 404, 422, 429, 500, 503])
async def test_award_force_failures_preserve_rejection_and_redact_key(monkeypatch, status):
    requests = transport(monkeypatch, status, text='Rejected key ' + TOKEN)
    result = await node({'operation': 'get_account'}).execute({})
    assert result['status'] == 'error' and result['status_code'] == status
    assert result['message'] == 'Rejected key [redacted]' and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{'errors': ['bad']}, [], {'data': 'wrong'}])
async def test_award_force_malformed_list_fails(monkeypatch, body):
    transport(monkeypatch, 200, body)
    assert (await node({'operation': 'list_entries'}).execute({}))['status'] == 'error'


@pytest.mark.asyncio
@pytest.mark.parametrize('region', ['us', 'eu', 'au', 'ca', 'hk'])
async def test_award_force_fixed_regional_hosts(monkeypatch, region):
    requests = transport(monkeypatch, 200, OPS['get_account']['body'])
    result = await node({'operation': 'get_account'}, region).execute({})
    assert result['data']['name'] == 'Example'
    assert requests[0].url.host == f'api.{region}.cr4ce.com'


def test_award_force_manual_connect_schema_and_rejections():
    shaped, errors, resolved = shape_credential('award_force_api_key', {'api_key': TOKEN})
    assert not errors and resolved is not None
    credential = native.AwardForceAPIKeyCredential.model_validate(shaped)
    assert credential.credential_type == 'award_force_api_key' and credential.region == 'us'
    assert native.AwardForceNode.connection_evidence.identity_operation == 'get_account'
    assert set(native.OPERATIONS) == set(OPS) and len(OPS) == 24
    for config in [
        {'operation': 'get_entry', 'entry_slug': '../entry'},
        {'operation': 'update_entry', 'entry_slug': 'AbCdEfGh'},
        {'operation': 'update_user', 'user_slug': 'AbCdEfGh'},
        {'operation': 'create_entry', 'title': 'Missing parent resources'},
        {'operation': 'list_entries', 'per_page': 101},
        {'operation': 'update_entry_field', 'entry_slug': 'AbCdEfGh', 'field_slug': 'AbCdEfGh', 'value_json': '{'},
        {'operation': 'tag_entry', 'entry_slug': 'AbCdEfGh', 'tags': '../escaped'},
        {'operation': 'tag_entry', 'entry_slug': 'AbCdEfGh', 'tags': '..'},
    ]:
        with pytest.raises((ValueError, ValidationError)):
            node(config)
    for region in ['https://evil.example', 'us.cr4ce.com/evil', '../eu']:
        with pytest.raises(ValidationError):
            native.AwardForceAPIKeyCredential(api_key=TOKEN, region=region)


@pytest.mark.asyncio
async def test_award_force_unsaved_key_connection_evidence(monkeypatch):
    from nodes.core.connection_evidence import collect_evidence
    requests = transport(monkeypatch, 200, OPS['get_account']['body'])
    evidence = await collect_evidence(node_type='automation-award-force', user_id='fixture-user',
        credential_data={'credential_type': 'award_force_api_key', 'api_key': TOKEN, 'region': 'au'})
    assert evidence.reachable is True and evidence.account_label == 'Example'
    assert len(requests) == 1 and requests[0].url.path == '/account'
    requests = transport(monkeypatch, 401, text='API key rejected')
    evidence = await collect_evidence(node_type='automation-award-force', user_id='fixture-user',
        credential_data={'credential_type': 'award_force_api_key', 'api_key': TOKEN, 'region': 'au'})
    assert evidence.reachable is False
    assert 'API key rejected' in str(evidence)
