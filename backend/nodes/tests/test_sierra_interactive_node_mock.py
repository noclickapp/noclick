"""Sierra contract routing, typed bodies, key isolation and failure regressions."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import sierra_interactive_node as native
from nodes.core.registry import NodeFactory

TOKEN = "sierra-test-user-api-key"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credentials=None):
    return NodeFactory.create_node(node_id="sierra-test", node_type=native.SierraInteractiveNode.integration_type,
        node_data={"config": config, "credentials": credentials or {"credential_type": native.CREDENTIAL_TYPE, "api_key": TOKEN}})


def transport(monkeypatch, response=None):
    calls = []
    def respond(request):
        calls.append(request)
        return response(request) if callable(response) else httpx.Response(200, json=response if response is not None else {})
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False
        assert kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return calls


def configs():
    return json.loads((Path(__file__).parent / 'fixtures/sierra-interactive/requests.json').read_text())


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', native.ROUTES)
async def test_sierra_interactive_one_contract_request(monkeypatch, operation):
    calls = transport(monkeypatch, {'result': {'id': 42}})
    result = await node(configs()[operation]['config']).execute({})
    assert len(calls) == 1
    expected = configs()[operation]
    request = calls[0]
    assert request.method == expected['method']
    assert str(request.url) == native.BASE_URL + expected['path']
    assert request.headers['Sierra-User-ApiKey'] == TOKEN
    assert 'Authorization' not in request.headers
    assert (json.loads(request.content) if request.content else None) == expected['body']
    assert result['data'] == {'result': {'id': 42}}
    assert result.get('readback_verified') is not True


@pytest.mark.asyncio
async def test_sierra_interactive_contact_identifier_is_one_segment(monkeypatch):
    calls = transport(monkeypatch)
    await node({'operation':'find_lead', 'leadIdOrEmail':'a+b@example.com/x?z=1'}).execute({})
    assert str(calls[0].url).endswith('/a%2Bb%40example.com%2Fx%3Fz%3D1')
    assert not calls[0].content


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 401, 403, 429, 500])
async def test_sierra_interactive_failures_do_not_leak_key_or_retry(monkeypatch, status):
    calls = transport(monkeypatch, lambda r: httpx.Response(status, text=TOKEN, headers={'Location':'https://example.com'}))
    with pytest.raises(ValueError) as exc:
        await node({'operation':'check_connection'}).execute({})
    assert str(status) in str(exc.value) and TOKEN not in str(exc.value)
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('payload', [[], None, {'success':False}, {'errors':['failure']}])
async def test_sierra_interactive_bad_or_error_envelope(monkeypatch, payload):
    transport(monkeypatch, lambda r: httpx.Response(200, json=payload))
    with pytest.raises(ValueError):
        await node({'operation':'check_connection'}).execute({})


@pytest.mark.asyncio
async def test_sierra_interactive_redacts_echoed_key(monkeypatch):
    transport(monkeypatch, {'nested':[TOKEN], TOKEN:TOKEN})
    result = await node({'operation':'check_connection'}).execute({})
    assert TOKEN not in json.dumps(result)


def test_sierra_interactive_credential_manual_default_and_foreign_tag():
    assert native.SierraInteractiveAPIKeyCredential(api_key=TOKEN).credential_type == native.CREDENTIAL_TYPE
    for bad in ['https://example.com/key', '<token>', 'x\r\ny', 'Bearer two-parts']:
        with pytest.raises((ValueError, ValidationError)):
            native.SierraInteractiveAPIKeyCredential(api_key=bad)
    with pytest.raises((ValueError, ValidationError)):
        node({'operation':'check_connection'}, {'credential_type':'other_api_key','api_key':TOKEN})


def test_sierra_interactive_rejects_unknown_fields_and_missing_required_body():
    for config in [{'operation':'create_lead'}, {'operation':'create_task','leadIdOrEmail':'42'},
                   {'operation':'check_connection','url':'https://example.com'}]:
        assert not native.SierraInteractiveNode.validate_config({'config':config})['valid']
