"""Offline REST request, signature, response and credential regressions."""
import hashlib
import hmac
import json
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import ValidationError
from nodes import uploadcare_node as native
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / 'fixtures/uploadcare/rest_cases.json').read_text())
PUBLIC = 'synthetic-public-key'
SECRET = 'synthetic-secret-key'


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='uploadcare-test', node_type='automation-uploadcare',
        node_data={'config': config, 'credentials': {'credential_type': 'uploadcare_api_key', 'public_key': PUBLIC, 'secret_key': SECRET}})


def transport(monkeypatch, *, status=200, payload=None, raw=None):
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(status, content=raw) if raw is not None else httpx.Response(status, json=payload)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize('case', CASES, ids=lambda case: case['operation'])
async def test_one_contract_operation_signed_exactly_once(monkeypatch, case):
    payload = 'uploader' if case['operation'] in {'get_metadata_value', 'set_metadata_value'} else {'fixture': True}
    calls = transport(monkeypatch, payload=payload)
    result = await node({'operation': case['operation'], **case['config']}).execute({})
    assert result['data'] == payload and result['status'] == 'success'
    assert len(calls) == 1
    req = calls[0]
    assert req.url.host == 'api.uploadcare.com'
    assert req.method == case['method'] and req.url.path == case['path']
    assert req.headers['accept'] == native.ACCEPT
    to_sign = '\n'.join([req.method, hashlib.md5(req.content).hexdigest(), req.headers['content-type'], req.headers['date'], req.url.raw_path.decode()])
    expected = hmac.new(SECRET.encode(), to_sign.encode(), hashlib.sha1).hexdigest()
    assert req.headers['authorization'] == f'Uploadcare {PUBLIC}:{expected}'
    assert SECRET not in str(req.headers) and SECRET.encode() not in req.content
    if case['body'] is None:
        assert req.content == b''
    elif case['operation'].endswith('webhook'):
        assert parse_qs(req.content.decode()) == {k: [str(v).lower() if isinstance(v, bool) else str(v)] for k, v in case['body'].items()}
    else:
        assert json.loads(req.content) == case['body']


@pytest.mark.asyncio
async def test_pagination_preserves_filters_without_following_urls(monkeypatch):
    calls = transport(monkeypatch, payload={'results': [], 'next': 'https://attacker.invalid/?from=bad'})
    result = await node({'operation': 'list_files', 'from_time': '2015-09-10T10:00:00Z', 'stored': True, 'removed': False, 'limit': 1}).execute({})
    assert len(calls) == 1 and result['data']['next'].startswith('https://attacker.invalid/')
    assert dict(calls[0].url.params) == {'from': '2015-09-10T10:00:00Z', 'stored': 'true', 'removed': 'false', 'limit': '1', 'ordering': 'datetime_uploaded'}


@pytest.mark.asyncio
async def test_webhook_and_credential_secrets_redacted(monkeypatch):
    transport(monkeypatch, payload={'signing_secret': 'webhook-secret', 'echo': SECRET, 'nested': ['webhook-secret']})
    result = await node({'operation': 'create_webhook', 'target_url': 'https://example.com/hooks', 'event': 'file.uploaded', 'signing_secret': 'webhook-secret'}).execute({})
    assert SECRET not in str(result) and 'webhook-secret' not in str(result) and 'signing_secret' not in result['data']


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 400, 401, 403, 404, 429, 500])
async def test_http_failure_is_not_success_and_does_not_echo_secrets(monkeypatch, status):
    calls = transport(monkeypatch, status=status, payload={'detail': SECRET})
    with pytest.raises(ValueError, match=f'HTTP {status}') as exc:
        await node({'operation': 'get_project'}).execute({})
    assert len(calls) == 1 and SECRET not in str(exc.value)


@pytest.mark.asyncio
async def test_204_and_malformed_json(monkeypatch):
    transport(monkeypatch, status=204, raw=b'')
    result = await node({'operation': 'delete_webhook', 'target_url': 'https://example.com/hooks'}).execute({})
    assert result['data'] is None and result['http_status'] == 204
    transport(monkeypatch, raw=b'<html>not JSON</html>')
    with pytest.raises(ValueError, match='invalid JSON'):
        await node({'operation': 'get_project'}).execute({})


@pytest.mark.parametrize('secret', ['', 'https://example.com/key', '<token>', 'bad\nkey', 'key:secret'])
def test_invalid_credentials(secret):
    with pytest.raises((ValidationError, ValueError)):
        native.UploadcareAPIKeyCredential(public_key=PUBLIC, secret_key=secret)


@pytest.mark.parametrize('config', [
    {'operation': 'get_file', 'file_id': '../bad'},
    {'operation': 'get_group', 'group_id': '../bad'},
    {'operation': 'get_metadata_value', 'file_id': '21975c81-7f57-4c7a-aef9-acfe28779f78', 'key': '../escape'},
    {'operation': 'get_metadata_value', 'file_id': '21975c81-7f57-4c7a-aef9-acfe28779f78', 'key': '..'},
    {'operation': 'create_webhook', 'target_url': 'file:///etc/passwd', 'event': 'file.uploaded'},
    {'operation': 'list_files', 'limit': 1001},
])
def test_config_rejects_invalid_routes_and_bounds(config):
    assert not native.UploadcareNode.validate_config({'config': config})['valid']


@pytest.mark.asyncio
async def test_update_webhook_can_only_toggle_active(monkeypatch):
    calls = transport(monkeypatch, payload={'id': 143, 'is_active': False})
    await node({'operation': 'update_webhook', 'webhook_id': 143, 'is_active': False}).execute({})
    assert parse_qs(calls[0].content.decode()) == {'is_active': ['false']}


@pytest.mark.asyncio
async def test_project_evidence_uses_documented_identity(monkeypatch):
    transport(monkeypatch, payload={'collaborators': [], 'name': 'demo', 'pub_key': PUBLIC, 'autostore_enabled': True})
    from nodes.core.connection_evidence import collect_evidence
    result = await collect_evidence(node_type='automation-uploadcare', credential_data={
        'credential_type': 'uploadcare_api_key', 'public_key': PUBLIC, 'secret_key': SECRET,
    }, user_id='test-user', pool=None)
    assert result.reachable is True and result.account_label == 'demo'
