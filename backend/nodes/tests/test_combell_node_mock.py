"""Exercise real request construction, HMAC bytes and published v2 responses."""
import base64
import hashlib
import hmac
import json
from pathlib import Path
from urllib.parse import quote

import httpx
import pytest
from pydantic import ValidationError

from nodes import combell_node as native
from nodes.core.credential_connect import shape_credential
from nodes.core.registry import NodeFactory

CREDENTIAL = {'credential_type': 'combell_api_key', 'api_key': 'fixture-key', 'api_secret': 'fixture-secret'}


def node(config):
    return NodeFactory.create_node(node_id='combell-test', node_type='automation-combell', node_data={'config': config, 'credentials': CREDENTIAL})


def transport(monkeypatch, status=200, payload=None, headers=None):
    calls = []
    def respond(request):
        calls.append(request)
        if status == 204 or payload is None:
            return httpx.Response(status, headers=headers)
        return httpx.Response(status, json=payload, headers=headers)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return calls


def test_hmac_published_protocol_signs_exact_query_and_body():
    request = httpx.Request('PUT', 'https://api.combell.com/v2/dns/Example.COM/records/A1?skip=0&type=TXT', content=b'{"content":"Hello + world"}')
    body_hash = base64.b64encode(hashlib.md5(request.content).digest()).decode()
    message = 'fixture-keyput%2Fv2%2Fdns%2Fexample.com%2Frecords%2Fa1%3Fskip%3D0%26type%3Dtxt1700000000unique' + body_hash
    signature = base64.b64encode(hmac.new(b'fixture-secret', message.encode(), hashlib.sha256).digest()).decode()
    assert native.authorization(request, native.CombellAPIKeyCredential(**CREDENTIAL), nonce='unique', timestamp=1700000000) == f'hmac fixture-key:{signature}:unique:1700000000'
    empty = httpx.Request('GET', 'https://api.combell.com/v2/accounts')
    message = b'fixture-keyget%2Fv2%2Faccounts1700000000unique'
    signature = base64.b64encode(hmac.new(b'fixture-secret', message, hashlib.sha256).digest()).decode()
    assert native.authorization(empty, native.CombellAPIKeyCredential(**CREDENTIAL), nonce='unique', timestamp=1700000000) == f'hmac fixture-key:{signature}:unique:1700000000'


@pytest.mark.asyncio
async def test_each_operation_has_one_pinned_request(monkeypatch):
    # Config samples here exercise construction only; contract validation is a
    # separate harness run against the provider's immutable OpenAPI document.
    # Explicit values cover all required fields, including body/path collisions.
    values = {'account_id': 12, 'identifier': 'example.com', 'servicepack_id': 3,
        'domain_name': 'Example.com', 'record_id': 'rec1', 'type': 'TXT', 'content': 'text',
        'name_servers': ['ns1.example.com'], 'will_renew': True, 'version': '8.3',
        'mailbox_name': 'person@example.com', 'email_address': 'person@example.com', 'password': 'Asecure123',
        'enabled': True, 'database_name': 'example_db', 'job_id': '00000000-0000-4000-8000-000000000001'}
    golden = json.loads((Path(__file__).parent / 'fixtures/combell/operations.json').read_text())
    assert len(golden) == 25
    for operation, route in native.ROUTES.items():
        model = next(m for m in native.CombellOperation.__origin__.__args__ if m.model_fields['operation'].default == operation)
        config = {'operation': operation, **{k: v for k, v in values.items() if k in model.model_fields}}
        status = next(iter(route['responses']))
        shape = route['responses'][status]
        payload = [] if shape == 'list' else {} if shape == 'object' else None
        calls = transport(monkeypatch, status, payload)
        output = await node(config).execute({})
        assert output['success'], (operation, output)
        assert len(calls) == 1
        request = calls[0]
        assert request.method == golden[operation]['method']
        assert request.url.host == 'api.combell.com'
        path = golden[operation]['path']
        for placeholder, key in route['paths'].items():
            path = path.replace('{' + placeholder + '}', quote(str(config[key]), safe=''))
        assert request.url.raw_path.decode().split('?')[0] == '/v2' + path
        expected_body = {k: v for k, v in node(config).config.config.model_dump(mode='json', exclude_none=True).items() if k in route['body']}
        assert (json.loads(request.content) if request.content else {}) == expected_body
        scheme, auth = request.headers['authorization'].split(' ', 1)
        key, signature, nonce, timestamp = auth.split(':')
        assert scheme == 'hmac' and key == CREDENTIAL['api_key']
        assert request.headers['authorization'] == native.authorization(request, native.CombellAPIKeyCredential(**CREDENTIAL), nonce=nonce, timestamp=timestamp)


@pytest.mark.asyncio
async def test_paging_headers_control_completion_and_empty_accounts_work(monkeypatch):
    calls = transport(monkeypatch, 200, [{'id': 12, 'identifier': 'example.com'}], {'X-Paging-Skipped': '4', 'X-Paging-Take': '1', 'X-Paging-TotalResults': '10'})
    result = await node({'operation': 'list_accounts', 'skip': 4, 'take': 20, 'identifier': 'Example + Co'}).execute({})
    assert result['pagination']['has_more'] is True and result['pagination']['next_skip'] == 5
    assert calls[0].url.params['identifier'] == 'Example + Co'
    transport(monkeypatch, 200, [])
    result = await node({'operation': 'list_accounts'}).execute({})
    assert result['success'] and result['data'] == []
    assert result['pagination']['completion_known'] is False


@pytest.mark.asyncio
async def test_account_creation_is_only_accepted_and_never_follows_location(monkeypatch):
    calls = transport(monkeypatch, 202, headers={'Location': 'https://api.combell.com/v2/provisioningjobs/job1'})
    result = await node({'operation': 'create_account', 'identifier': 'example.com', 'servicepack_id': 3}).execute({})
    assert result['write_outcome'] == 'accepted' and result['data'] is None
    assert len(calls) == 1 and result['location'].endswith('/job1')


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 401, 403, 404, 429, 500])
async def test_failure_statuses_do_not_claim_success_or_echo_secrets(monkeypatch, status):
    calls = transport(monkeypatch, status, {'error_text': 'Denied fixture-secret fixture-key'})
    result = await node({'operation': 'delete_mailbox', 'mailbox_name': 'person@example.com'}).execute({})
    assert not result['success'] and result['http_status'] == status
    assert 'fixture-secret' not in str(result) and 'fixture-key' not in str(result)
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{}, [1], {'error_code': 'denied'}, 'invalid'])
async def test_list_shape_errors_fail_closed(monkeypatch, body):
    transport(monkeypatch, 200, body)
    assert (await node({'operation': 'list_accounts'}).execute({}))['success'] is False


def test_manual_credential_defaults_and_path_safety():
    shaped, errors, _ = shape_credential('combell_api_key', {'api_key': ' fixture-key ', 'api_secret': ' fixture-secret '})
    assert not errors and shaped == {k: v for k, v in CREDENTIAL.items() if k != 'credential_type'}
    assert native.CombellAPIKeyCredential(**shaped).credential_type == 'combell_api_key'
    for value in ('../escape', 'a/b', 'a?x=1', 'a\\b'):
        with pytest.raises(ValidationError):
            native.CombellGetDomain(domain_name=value)
    assert native.CombellNode.connection_evidence.operation == 'list_accounts'


@pytest.mark.asyncio
async def test_manual_connect_runs_the_declared_account_evidence(monkeypatch):
    from nodes.core import credential_connect
    from nodes.core.connection_evidence import collect_evidence
    monkeypatch.setattr(credential_connect, '_collect_evidence', collect_evidence)
    calls = transport(monkeypatch, 200, [{'id': 12, 'identifier': 'example.com'}])
    verdict = await credential_connect.validate_for_connect(
        credential_type='combell_api_key', credential_data=CREDENTIAL,
        user_id='00000000-0000-4000-8000-000000000001', probe=True)
    assert verdict.field_errors == {} and verdict.evidence.reachable is True
    assert verdict.evidence.samples[0].label == 'example.com'
    assert calls[0].url.path == '/v2/accounts' and len(calls) == 1
    transport(monkeypatch, 401, {'error_text': 'Invalid API key'})
    rejected = await credential_connect.validate_for_connect(
        credential_type='combell_api_key', credential_data=CREDENTIAL,
        user_id='00000000-0000-4000-8000-000000000001', probe=True)
    assert rejected.evidence.reachable is False and rejected.rejection
