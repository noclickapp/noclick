"""Offline Nusii v2 request, response and manual-connect contracts."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import nusii_proposals_node as native
from nodes.core.registry import NodeFactory

TOKEN = 'synthetic-nusii-key-42'


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def credential():
    return {'credential_type': 'nusii_proposals_api_key', 'api_key': TOKEN}


def node(config):
    return NodeFactory.create_node(node_id='nusii-fixture', node_type=native.NusiiProposalsNode.integration_type,
                                   node_data={'config': config, 'credentials': credential()})


def transport(monkeypatch, body, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs == {'timeout': 30, 'trust_env': False, 'follow_redirects': False}
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


def resource():
    return {'data': {'id': '104', 'type': 'clients', 'attributes': {'name': 'John', 'email': 'john@doe.com'}}}


CASES = [
    ({'operation': 'create_client', 'name': 'John', 'email': 'john@doe.com'}, 'POST', '/clients', {'client[name]': ['John'], 'client[email]': ['john@doe.com']}),
    ({'operation': 'create_proposal', 'title': 'Webdesign yourwebsite.com', 'client_id': 100}, 'POST', '/proposals', {'proposal[title]': ['Webdesign yourwebsite.com'], 'proposal[client_id]': ['100']}),
    ({'operation': 'update_proposal', 'proposal_id': 126, 'title': 'Updated proposal'}, 'PUT', '/proposals/126', {'proposal[title]': ['Updated proposal']}),
    ({'operation': 'create_section', 'proposal_id': 126, 'title': 'Introduction', 'body': 'A & B + C'}, 'POST', '/sections', {'section[proposal_id]': ['126'], 'section[title]': ['Introduction'], 'section[body]': ['A & B + C'], 'section[section_type]': ['text']}),
    ({'operation': 'create_line_item', 'section_id': 100, 'name': 'Development Costs', 'amount': 10000}, 'POST', '/sections/100/line_items', {'line_item[name]': ['Development Costs'], 'line_item[amount]': ['10000'], 'line_item[cost_type]': ['fixed']}),
    ({'operation': 'update_line_item', 'line_item_id': 157, 'amount': 10000}, 'PUT', '/line_items/157', {'line_item[amount]': ['10000']}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize('config,method,path,form', CASES)
async def test_exact_documented_write_parameters(monkeypatch, config, method, path, form):
    requests = transport(monkeypatch, resource())
    result = await node(config).execute({})
    assert result['status'] == 'success'
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and str(request.url) == native.BASE + path
    assert request.headers['Authorization'] == 'Token token=' + TOKEN
    assert request.headers['Content-Type'] == 'application/json'
    expected = {}
    for key, value in form.items():
        envelope, field = key.split('[')
        expected.setdefault(envelope, {})[field[:-1]] = value[0]
    actual = json.loads(request.content)
    assert {k: {f: str(v) for f, v in fields.items()} for k, fields in actual.items()} == expected


@pytest.mark.asyncio
async def test_filters_paging_preserve_provider_metadata_without_following_links(monkeypatch):
    payload = {'data': [], 'meta': {'current_page': 2, 'next_page': 3}, 'links': {'next': 'https://elsewhere.invalid/'}}
    requests = transport(monkeypatch, payload)
    result = await node({'operation': 'list_proposals', 'page': 2, 'per': 10, 'status': 'draft'}).execute({})
    assert dict(requests[0].url.params) == {'page': '2', 'per': '10', 'status': 'draft'}
    assert result['meta'] == payload['meta'] and len(requests) == 1


@pytest.mark.asyncio
async def test_send_status_and_delete_acknowledgement(monkeypatch):
    requests = transport(monkeypatch, {'status': 'sent', 'sent_at': '2026-03-02T17:27:54.000Z', 'sender_id': 42, 'sender_name': 'Michael Koper'})
    result = await node({'operation': 'send_proposal', 'proposal_id': 100, 'email': 'your_client@email.com', 'subject': 'Your Proposal'}).execute({})
    assert result['status'] == 'success' and result['provider_status'] == 'sent'
    assert len(requests) == 1 and requests[0].url.path.endswith('/100/send_proposal')
    requests = transport(monkeypatch, resource())
    result = await node({'operation': 'delete_client', 'client_id': 104}).execute({})
    assert result['data']['id'] == '104' and requests[0].method == 'DELETE' and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('status,valid', [(401, False), (403, False), (429, None), (500, None)])
async def test_connect_rejection_is_definitive_only_for_auth(monkeypatch, status, valid):
    requests = transport(monkeypatch, {'errors': [{'detail': 'Rejected ' + TOKEN}]}, status)
    result = await native.NusiiProposalsNode.validate_credential_access(credential())
    assert result['valid'] is valid and TOKEN not in str(result)
    assert len(requests) == 1 and requests[0].url.path == '/api/v2/account/me'


@pytest.mark.asyncio
async def test_connect_account_and_error_envelope(monkeypatch):
    transport(monkeypatch, {'data': {'id': '3', 'type': 'accounts', 'attributes': {'name': 'Your Company Name'}}})
    assert (await native.NusiiProposalsNode.validate_credential_access(credential()))['valid'] is True
    transport(monkeypatch, {'unexpected': 'response'})
    assert (await native.NusiiProposalsNode.validate_credential_access(credential()))['valid'] is None
    requests = transport(monkeypatch, {'errors': [{'detail': TOKEN}]})
    with pytest.raises(ValueError) as exc:
        await node({'operation': 'create_client', 'name': 'John', 'email': 'john@doe.com'}).execute({})
    assert TOKEN not in str(exc.value) and len(requests) == 1


@pytest.mark.parametrize('value', ['Token token=abc', 'a\nb', 'https://app.nusii.com/settings/api', '“abc”'])
def test_keys_reject_header_and_paste_errors(value):
    with pytest.raises(ValueError):
        native.NusiiProposalsAPIKey(api_key=value)


@pytest.mark.parametrize('value', ['../clients', 'https://evil.invalid', 0, -1])
def test_ids_cannot_change_routes(value):
    with pytest.raises(ValidationError):
        native.GetClientConfig(client_id=value)


def test_catalog_schema_factory():
    schema = native.NusiiProposalsNode.get_config_schema()
    assert len(native.ROUTES) == 25
    assert schema and native.NusiiProposalsNode.connection_evidence.operation == 'list_clients'
    parsed = native.NusiiProposalsNode.parse_config({'config': {'operation': 'list_clients', 'page': ''}, 'credentials': credential()})
    assert parsed.config.page == 1
    with pytest.raises(ValueError):
        node({'operation': 'list_clients', 'undocumented_field': 'x'})


DOCUMENTED = json.loads((Path(__file__).parent / 'fixtures/nusii-proposals/documented-responses.json').read_text())


@pytest.mark.asyncio
@pytest.mark.parametrize('example', DOCUMENTED, ids=lambda example: example['operation'])
async def test_complete_provider_authored_responses(monkeypatch, example):
    """Narrative examples remain parseable even where OpenAPI snapshots are narrower."""
    requests = transport(monkeypatch, example['response'])
    result = await node(example['config']).execute({})
    assert result['status'] == 'success' and len(requests) == 1
    for key, value in example['response'].items():
        assert result['provider_status' if key == 'status' else key] == value


@pytest.mark.asyncio
async def test_connection_evidence_shows_client_names_and_empty_account_identity(monkeypatch):
    from nodes.core.connection_evidence import collect_evidence
    from nodes.core import run_op

    async def run_operation(**kwargs):
        return await node({'operation': kwargs['operation'], **kwargs['arguments']}).execute({})
    monkeypatch.setattr(run_op, 'run_node_operation', run_operation)
    transport(monkeypatch, {'data': [resource()['data']]})
    result = await collect_evidence(node_type='automation-nusii-proposals', user_id='fixture', credential_data=credential())
    assert result.reachable is True and [sample.label for sample in result.samples] == ['John']

    def client(**kwargs):
        def respond(request):
            body = {'data': []} if request.url.path.endswith('/clients') else {'data': {'id': '3', 'type': 'accounts', 'attributes': {'name': 'Your Company Name'}}}
            return httpx.Response(200, json=body)
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    result = await collect_evidence(node_type='automation-nusii-proposals', user_id='fixture', credential_data=credential())
    assert result.reachable is True and result.account_label == 'Your Company Name'
