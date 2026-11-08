"""Offline v2 contract examples and native execution regressions; no live key."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import echtpost_node as native
from nodes.core.registry import NODE_REGISTRY, NodeFactory

FIXTURES = json.loads((Path(__file__).parent / 'fixtures/echtpost/examples.json').read_text())
TOKEN = 'synthetic-echtpost-key-42'
CARD = '123e4567-e89b-12d3-a456-426614174000'


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='echtpost-fixture', node_type='automation-echtpost',
        node_data={'config': config, 'credentials': {'credential_type': 'echtpost_api_key', 'api_key': TOKEN}})


def transport(monkeypatch, *, body=None, status=200, headers=None):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body, headers=headers) if status != 204 else httpx.Response(204)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


def test_discovery_and_manual_key_default():
    assert NODE_REGISTRY['automation-echtpost'] is native.EchtpostNode
    c = native.EchtpostAPIKeyCredential(api_key=TOKEN)
    assert c.credential_type == 'echtpost_api_key'
    assert TOKEN not in repr(c)
    assert native.EchtpostNode.connection_evidence.identity_operation == 'get_account'


@pytest.mark.asyncio
async def test_documented_account_example_and_credential_transport(monkeypatch):
    requests = transport(monkeypatch, body=FIXTURES['account'])
    result = await node({'operation': 'get_account'}).execute({})
    assert result['account']['name'] == 'Acme'
    assert result['balance']['credits_eur'] == '10.00'
    request = requests[0]
    assert request.method == 'GET' and str(request.url) == 'https://api.echtpost.de/v2/me'
    assert request.headers['X-Api-Key'] == TOKEN
    assert 'authorization' not in request.headers and TOKEN not in str(result)


@pytest.mark.asyncio
async def test_contact_example_fields_are_flat_and_country_and_groups_are_preserved(monkeypatch):
    requests = transport(monkeypatch, body={'id': 101}, status=201)
    result = await node({'operation': 'create_contact', **FIXTURES['create_contact'], 'group_ids': [7]}).execute({})
    assert result == {'id': 101}
    assert json.loads(requests[0].content) == {**FIXTURES['create_contact'], 'group_ids': [7]}
    assert requests[0].url.path == '/v2/contacts'


@pytest.mark.asyncio
async def test_custom_card_example_with_false_flags_and_nested_values(monkeypatch):
    requests = transport(monkeypatch, body={'id': CARD, 'status': 'pending'}, status=201)
    body = {**FIXTURES['create_card'], 'move_to_next_print_date': False, 'deduplicate_recipients': False}
    result = await node({'operation': 'create_card', **body}).execute({})
    assert result['status'] == 'pending'
    assert json.loads(requests[0].content) == body
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_preview_fit_example_is_not_card_creation(monkeypatch):
    requests = transport(monkeypatch, body=FIXTURES['preview_fit_response'])
    result = await node({'operation': 'preview_card_fit', **FIXTURES['preview_fit']}).execute({})
    assert result['fits'] is True and result['lines_used'] == 3
    assert requests[0].url.path == '/v2/cards/preview_fit'
    assert json.loads(requests[0].content) == FIXTURES['preview_fit']


@pytest.mark.asyncio
async def test_list_filters_unicode_and_page_metadata(monkeypatch):
    requests = transport(monkeypatch, body=[{'id': 101, 'last_name': 'Doe'}],
        headers={'X-Total-Count': '201', 'X-Total-Pages': '3', 'Link': '<https://evil.example/>; rel="next"'})
    result = await node({'operation': 'list_contacts', 'page': 2, 'per_page': 100,
        'search': 'Müller + café', 'group_id': 7}).execute({})
    assert result['next_page'] == 3 and result['page'] == 2 and result['total_count'] == '201'
    assert dict(requests[0].url.params) == {'page': '2', 'per_page': '100', 'search': 'Müller + café', 'group_id': '7'}
    assert len(requests) == 1  # pagination never follows a provider-supplied URL
    transport(monkeypatch, body=[], headers={'X-Total-Pages': '1'})
    assert (await node({'operation': 'list_contacts'}).execute({}))['next_page'] is None


@pytest.mark.asyncio
async def test_update_query_does_not_leak_into_body_and_dates_serialize(monkeypatch):
    requests = transport(monkeypatch, body={'id': 101})
    body = {**FIXTURES['create_contact'], 'birthdate': '1990-01-02'}
    await node({'operation': 'update_contact', 'id': 101, 'include': 'groups,cards', **body}).execute({})
    assert requests[0].method == 'PATCH' and requests[0].url.path == '/v2/contacts/101'
    assert dict(requests[0].url.params) == {'include': 'groups,cards'}
    assert json.loads(requests[0].content) == body


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,path', [('delete_contact', '/v2/contacts/101'), ('delete_group', '/v2/groups/101')])
async def test_empty_deletion_response(monkeypatch, operation, path):
    requests = transport(monkeypatch, status=204)
    result = await node({'operation': operation, 'id': 101}).execute({})
    assert result == {'success': True, 'deleted': True}
    assert requests[0].method == 'DELETE' and requests[0].url.path == path
    assert requests[0].content == b''


@pytest.mark.asyncio
async def test_cancel_is_async_and_preserves_provider_status(monkeypatch):
    requests = transport(monkeypatch, status=202, body={'id': CARD, 'status': 'scheduled', 'cancelable': True})
    result = await node({'operation': 'cancel_card', 'id': CARD}).execute({})
    assert result['status'] == 'scheduled'  # acceptance does not mean cancellation completed
    assert requests[0].method == 'DELETE' and requests[0].url.path == '/v2/cards/' + CARD


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [302, 401, 402, 422, 429, 500])
async def test_provider_failure_never_retries_a_credit_spending_write(monkeypatch, status):
    requests = transport(monkeypatch, status=status, body={'detail': 'Provider rejected ' + TOKEN})
    with pytest.raises(ValueError) as exc:
        await node({'operation': 'create_card', **FIXTURES['create_card']}).execute({})
    assert TOKEN not in str(exc.value) and f'HTTP {status}' in str(exc.value)
    assert len(requests) == 1


@pytest.mark.parametrize('key', ['https://example.com/key', 'paste your API key', 'key\r\ninjected', 'Bearer key'])
def test_invalid_manual_keys(key):
    with pytest.raises(ValidationError):
        native.EchtpostAPIKeyCredential(api_key=key)


@pytest.mark.parametrize('config', [
    {'operation': 'list_contacts', 'page': 0},
    {'operation': 'list_cards', 'per_page': 201},
    {'operation': 'get_card', 'id': '../contacts'},
    {'operation': 'get_contact', 'id': '1/other'},
    {'operation': 'create_contact', 'last_name': 'Doe'},
    {'operation': 'create_card'},
    {'operation': 'create_card_from_template'},
])
def test_invalid_config_is_rejected_before_transport(config):
    with pytest.raises(ValueError):
        node(config)


@pytest.mark.asyncio
async def test_template_can_clear_inherited_vertical_text(monkeypatch):
    requests = transport(monkeypatch, status=201, body={'id': CARD})
    await node({'operation': 'create_card_from_template', 'template_id': 42,
        'use_default_vertical_text': True, 'content_vertical': 'Override me', 'recipient_ids': [101]}).execute({})
    assert json.loads(requests[0].content) == {'template_id': 42, 'content_vertical': '', 'recipient_ids': [101]}
