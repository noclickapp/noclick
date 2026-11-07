"""SendX workflows through staging’s factory, credential and HTTP seams."""
import asyncio
import json
from copy import deepcopy
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio

from nodes import sendx_node as provider
from nodes.sendx_node import SendXNode as Node, NODE_TYPE, OPERATIONS, MAX_BYTES
from nodes.core.registry import NodeFactory
from nodes.core import credential_connect as cc, connection_evidence as ce, run_op

TAG, SECRET, PRIVATE = 'sendx_team_api_key', 'SyntheticSendXPrivateKey42', 'SyntheticRecipientPrivate42'
WITNESS, LIST, CONTACT, TAG_ID, FIELD, CAMPAIGN = ['list_' + 'W' * 22, 'list_' + 'L' * 22, 'contact_' + 'C' * 22, 'tag_' + 'T' * 22, 'custom_field_' + 'F' * 22, 'campaign_' + 'A' * 22]
NEW = {'contacts': 'contact_' + 'N' * 22, 'lists': 'list_' + 'N' * 22, 'tags': 'tag_' + 'N' * 22}
TARGETS = {'contacts': CONTACT, 'lists': LIST, 'tags': TAG_ID, 'custom_fields': FIELD, 'campaigns': CAMPAIGN}


def credential():
    return {'credential_type': TAG, 'api_key': SECRET, 'witness_list_id': WITNESS, 'contact_ids': [CONTACT], 'list_ids': [WITNESS, LIST], 'tag_ids': [TAG_ID], 'custom_field_ids': [FIELD], 'campaign_ids': [CAMPAIGN], 'write_contact_ids': [CONTACT], 'write_list_ids': [LIST], 'write_tag_ids': [TAG_ID], 'disposable_contact_ids': [CONTACT], 'disposable_list_ids': [LIST], 'disposable_tag_ids': [TAG_ID], 'allowed_operations': list(OPERATIONS)}


def resource(kind, resource_id, **changes):
    raw = {'id': resource_id, 'name': 'Fixture metadata', 'created': '2026-10-06T00:00:00Z', 'updated': '2026-10-06T00:00:00Z', 'private_ignored': PRIVATE}
    if kind == 'contacts': raw.update(email='synthetic@example.invalid', firstName=PRIVATE, customFields={'field_unknown': PRIVATE}, unsubscribed=False, bounced=False, spam=False, blocked=False, dropped=False, lists=[LIST], tags=[TAG_ID], lastTrackedIp=PRIVATE)
    if kind in ('lists', 'custom_fields'): raw['type'] = 0
    if kind == 'custom_fields': raw['description'] = 'Fixture definition'
    if kind == 'campaigns': raw.update(status=0, sender=PRIVATE, subject=PRIVATE, campaignScreenshotURL='https://example.invalid/' + SECRET)
    return {**raw, **changes}


def arguments(op):
    verb, remainder = op.split('_', 1)
    if verb == 'list': return {}
    kind = 'campaigns' if remainder == 'campaign_report' else {'contact': 'contacts', 'list': 'lists', 'tag': 'tags', 'custom_field': 'custom_fields', 'campaign': 'campaigns'}[remainder]
    if op == 'get_list': return {}
    result = {} if verb == 'create' else {('custom_field' if kind == 'custom_fields' else kind[:-1]) + '_id': TARGETS[kind]}
    if op not in provider.READS:
        result['automation_effects_acknowledged'] = True
        if verb != 'delete': result.update({'email': 'changed@example.invalid', 'first_name': 'Changed'} if kind == 'contacts' else {'name': 'Changed'})
    return result


def node(op, raw=None, **changes):
    return NodeFactory.create_node(node_id='sendx-fixture', node_type=NODE_TYPE, node_data={'config': {'operation': op, **arguments(op), **changes}, 'credentials': deepcopy(raw or credential())}, sio=None, user_id='fixture-user')


def test_actual_factory_and_credential_discovery_parse_the_native_config():
    instance = node('get_contact')
    assert isinstance(instance.config, provider.SendXFullConfig)
    assert instance.config.config.contact_id == CONTACT
    assert instance.node_data['credentials'] == credential()
    assert cc.credential_classes_for_node(Node) == [provider.SendXTeamAPIKeyCredential]
    assert Node.connection_evidence.operation == 'get_list'
    assert Node.connection_evidence.proves == 'reachability' and Node.connection_evidence.identity_operation is None


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest_asyncio.fixture
async def transport(monkeypatch):
    from utils import ssrf
    state = SimpleNamespace(requests=[], override=None, on_request=None, addresses=['93.184.216.34'], rows={kind: {resource_id: resource(kind, resource_id)} for kind, resource_id in TARGETS.items()})
    state.rows['lists'][WITNESS] = resource('lists', WITNESS)
    state.rows['contacts']['contact_' + 'U' * 22] = resource('contacts', 'contact_' + 'U' * 22)
    monkeypatch.setattr(asyncio.get_running_loop(), 'getaddrinfo', AsyncMock(side_effect=lambda *a, **k: [(2 if ':' not in ip else 10, 1, 6, '', (ip, 443)) for ip in state.addresses]))

    def response(request):
        state.requests.append(request)
        if state.on_request: state.on_request(request)
        if state.override:
            answer = state.override(request)
            if answer is not None: return answer
        assert request.url.host == 'api.sendx.io' and request.headers['X-Team-ApiKey'] == SECRET
        parts = request.url.path.removeprefix('/api/v1/rest/').split('/')
        if parts[0] == 'report':
            assert request.method == 'GET' and parts == ['report', 'campaign', CAMPAIGN]
            return httpx.Response(200, json={'campaignId': CAMPAIGN, **{field: 1 for field in ('clickedUniqueContactCount', 'openedUniqueContactCount', 'sentContactCount', 'unsubscribeContactCount', 'bounceContactCount', 'spamContactCount', 'clickedContactCount', 'openedContactCount')}, 'linkStats': [{'url': 'https://example.invalid/' + SECRET, 'count': 1}]})
        kind = {'contact': 'contacts', 'list': 'lists', 'tag': 'tags', 'customfield': 'custom_fields', 'campaign': 'campaigns'}[parts[0]]
        resource_id = provider._id(kind, parts[1]) if len(parts) == 2 else None
        if request.method == 'GET':
            assert not request.content
            if resource_id is None:
                assert set(request.url.params) <= {'offset', 'limit', 'search', 'campaignType'}
                if kind == 'tags': assert 'search' not in request.url.params
                rows = list(state.rows[kind].values()); offset, limit = int(request.url.params['offset']), int(request.url.params['limit'])
                return httpx.Response(200, json=deepcopy(rows[offset:offset + limit]))
            if resource_id not in state.rows[kind]: return httpx.Response(404, json={'status': 'error', 'message': PRIVATE})
            return httpx.Response(200, json=deepcopy(state.rows[kind][resource_id]))
        assert kind in ('contacts', 'lists', 'tags') and not request.url.query
        if request.method == 'DELETE':
            assert not request.content
            del state.rows[kind][resource_id]
            return httpx.Response(200, json={'status': 'success', 'message': PRIVATE})
        assert request.method in ('POST', 'PUT') and request.headers['content-type'] == 'application/json'
        body = json.loads(request.content)
        assert set(body) <= ({'email', 'firstName', 'lastName', 'company', 'lists', 'tags'} if kind == 'contacts' else {'name'})
        if kind == 'contacts': assert 'email' in body
        created = request.method == 'POST'
        resource_id = NEW[kind] if created else resource_id
        raw = resource(kind, resource_id) if created else state.rows[kind][resource_id]
        raw.update(body); state.rows[kind][resource_id] = raw
        return httpx.Response(201 if created else 200, json=deepcopy(raw))

    def client(**kwargs):
        assert kwargs == {'timeout': 30, 'follow_redirects': False, 'trust_env': False}
        return ssrf.guarded_async_client(transport=httpx.MockTransport(response), **kwargs)
    monkeypatch.setattr(provider, 'guarded_async_client', client)
    return state


@pytest.mark.asyncio
@pytest.mark.parametrize('op', OPERATIONS)
async def test_actual_factory_run_all_twenty_contracts(transport, caplog, op):
    result = await node(op).run({})
    assert result['status'] == 'success' and result['action'] == op
    assert result['protected_witness_access_verified'] is True and result['account_identity_verified'] is False and result['provider_team_identity_verified'] is False
    assert all(value not in json.dumps(result) + caplog.text for value in (SECRET, PRIVATE, 'synthetic@example.invalid', 'changed@example.invalid'))
    mutations = [request for request in transport.requests if request.method != 'GET']
    assert len(mutations) == (0 if op in provider.READS else 1)
    if mutations:
        assert result['mutation_acknowledged'] and result['readback_verified'] and result['local_scope_auto_extended'] is False
        assert 'existing SendX automations' in result['effects']
    if op == 'delete_contact': assert result['deletion'] == 'soft' and result['erasure_or_history_retention_verified'] is False
    if op == 'get_campaign_report': assert result['report']['link_urls_returned'] is False
    if op == 'list_contacts':
        assert [row['id'] for row in result['resources']] == [CONTACT]
        assert result['provider_rows_received'] == 2 and result['has_more'] is None and result['next_page_token'] is None


@pytest.mark.asyncio
async def test_actual_manual_connect_shape_only_proves_resource_reachability(transport, monkeypatch):
    monkeypatch.setattr(cc, '_collect_evidence', ce.collect_evidence)
    raw = credential(); raw.pop('credential_type')
    shaped, errors, _ = cc.shape_credential(TAG, raw)
    assert errors == {} and shaped['credential_type'] == TAG
    result = await cc.validate_for_connect(credential_type=TAG, credential_data=raw, user_id='fixture-user')
    assert result.ok and result.evidence.reachable is True
    assert result.evidence.account_label is None and result.evidence.samples == [] and 'verified_as' not in result.verified_metadata()
    assert len(transport.requests) == 1 and transport.requests[0].method == 'GET'
    assert SECRET not in json.dumps(asdict(result.evidence))


@pytest.mark.asyncio
@pytest.mark.parametrize('case', ['foreign', 'host', 'newline', 'scope', 'write', 'cleanup', 'witness', 'duplicate-alias'])
async def test_authority_and_disposable_restrictions_precede_network(transport, case):
    raw = credential()
    if case == 'foreign':
        nested = {'config': {'operation': 'get_list'}, 'credentials': raw}
        assert Node.validate_config(nested)['valid']
        raw['credential_type'] = 'sendx_identify_key'
        assert not Node.validate_config(nested)['valid']
        with pytest.raises(ValueError): Node.parse_config(nested)
        with pytest.raises(ValueError): await Node.load_field_options('list_id', raw)
        assert not (await cc.validate_for_connect(credential_type=TAG, credential_data=raw, user_id='fixture-user')).ok
    elif case in ('host', 'newline', 'witness', 'duplicate-alias'):
        raw.update({'api_base_url': 'https://example.invalid'} if case == 'host' else {'api_key': 'bad\nkey'} if case == 'newline' else {'disposable_list_ids': [WITNESS], 'write_list_ids': [WITNESS]} if case == 'witness' else {'list_ids': [WITNESS, LIST, LIST.removeprefix('list_')]})
        with pytest.raises(ValueError): node('get_list', raw)
    else:
        op = 'update_contact'
        if case == 'scope': raw['allowed_operations'] = ['get_list']
        elif case == 'write': raw.update(write_contact_ids=[], disposable_contact_ids=[])
        elif case == 'cleanup': op = 'delete_contact'; raw['disposable_contact_ids'] = []
        assert (await node(op, raw).run({}))['status'] == 'error'
    assert transport.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize('case', ['202', '204', '401', '403', '429', 'redirect', 'text', 'oversize', 'empty', 'wrong-id', 'bool-type', 'secret-name', 'nonfinite'])
async def test_documented_status_envelope_and_private_projection(transport, caplog, case):
    def answer(request):
        if case in ('202', '204', '401', '403', '429', 'redirect'): return httpx.Response(302 if case == 'redirect' else int(case), json={'message': SECRET})
        if case == 'text': return httpx.Response(200, text=PRIVATE)
        if case == 'oversize': return httpx.Response(200, content=b'x' * (MAX_BYTES + 1), headers={'content-type': 'application/json'})
        if case == 'nonfinite': return httpx.Response(200, content=b'{"type":NaN}', headers={'content-type': 'application/json'})
        row = resource('lists', WITNESS)
        if case == 'empty': row = {}
        elif case == 'wrong-id': row['id'] = LIST
        elif case == 'bool-type': row['type'] = True
        elif case == 'secret-name': row['name'] = SECRET
        return httpx.Response(200, json=row)
    transport.override = answer
    result = await node('get_list').run({})
    assert result['status'] == 'error' and len(transport.requests) == 1
    assert SECRET not in json.dumps(result) + caplog.text and PRIVATE not in json.dumps(result) + caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize('case', ['failed-readback', 'unchanged', 'still-present', 'invalid-404'])
async def test_acknowledged_mutation_never_replays_or_claims_erasure(transport, case):
    def answer(request):
        if request.method == 'GET' and any(old.method != 'GET' for old in transport.requests[:-1]):
            if case == 'failed-readback': return httpx.Response(503, json={'message': PRIVATE})
            if case == 'unchanged': return httpx.Response(200, json=resource('contacts', CONTACT))
            if case == 'still-present': return httpx.Response(200, json=resource('contacts', CONTACT))
            return httpx.Response(404, json={'unexpected': PRIVATE})
        return None
    transport.override = answer
    result = await node('delete_contact' if case in ('still-present', 'invalid-404') else 'update_contact').run({})
    assert result['status'] == 'error' and result['mutation_acknowledged'] is True and result['readback_verified'] is False
    assert result['resource_id'] == CONTACT and result['automatic_retry_performed'] is False
    assert sum(request.method != 'GET' for request in transport.requests) == 1


@pytest.mark.asyncio
async def test_real_run_op_sparse_body_current_ids_and_picker_context(transport):
    result = await run_op.run_node_operation(node_type=NODE_TYPE, operation='update_contact', arguments={'operation': 'send_email', 'contact_id': CONTACT, 'email': 'changed@example.invalid', 'automation_effects_acknowledged': True}, credential_data=credential(), user_id='fixture-user')
    assert result['status'] == 'success' and result['action'] == 'update_contact'
    assert json.loads(next(request.content for request in transport.requests if request.method == 'PUT')) == {'email': 'changed@example.invalid'}
    options = await Node.load_field_options('list_id', credential(), context={'operation': 'update_list', 'list_id': LIST.removeprefix('list_'), 'list_id__label': 'Fixture', 'name': 'Changed', 'automation_effects_acknowledged': True, '_user_id': 'fixture-user'})
    assert {row['value'] for row in options['options']} == {LIST, WITNESS}
    before = len(transport.requests)
    for changes in ({'page_token': 'https://example.invalid'}, {'context': {'api_key': SECRET}}, {'context': {'contact_id': 'contact_' + 'U' * 22}}):
        with pytest.raises(ValueError): await Node.load_field_options('list_id', credential(), **changes)
    assert len(transport.requests) == before
    created = await node('create_contact', lists=[LIST.removeprefix('list_')], tags=[TAG_ID]).run({})
    assert created['status'] == 'success' and created['resource']['id'] == NEW['contacts']
    assert json.loads(next(request.content for request in transport.requests if request.method == 'POST'))['lists'] == [LIST.removeprefix('list_')]
    assert (await node('get_contact', contact_id=NEW['contacts']).run({}))['status'] == 'error'


def test_saved_flat_disconnected_editing_and_excluded_body_contracts():
    flat = {'operation': 'update_contact', 'contact_id': CONTACT, 'email': 'synthetic@example.invalid', 'automation_effects_acknowledged': True}
    assert Node.validate_saved_config(flat)['valid']
    parsed = Node.parse_config(Node._wrap_flat_config(flat, Node.get_config_model()))
    assert parsed.credentials is None and parsed.config.email == 'synthetic@example.invalid'
    for changes in ({'email': None}, {'customFields': {}}, {'lists': []}, {'lastTrackedIp': '127.0.0.1'}, {'sendEmail': False}, {'automation_effects_acknowledged': 1}):
        assert not Node.validate_saved_config({**flat, **changes})['valid']
    assert not Node.validate_saved_config({'operation': 'list_contacts', 'limit': 31})['valid']
    assert not Node.validate_saved_config({'operation': 'list_tags', 'search': 'XX'})['valid']


@pytest.mark.parametrize('config', [{'operation': PRIVATE}, {'operation': 'update_contact', 'contact_id': CONTACT, 'email': SECRET, 'automation_effects_acknowledged': True}])
def test_actual_factory_parse_diagnostics_never_echo_credential_or_invalid_operation(caplog, config):
    with pytest.raises(ValueError) as error:
        NodeFactory.create_node(node_id='sendx-private', node_type=NODE_TYPE, node_data={'config': config, 'credentials': credential()}, sio=None, user_id='fixture-user')
    assert SECRET not in str(error.value) + caplog.text and PRIVATE not in str(error.value) + caplog.text


@pytest.mark.asyncio
async def test_execute_uses_the_validated_credential_model(transport):
    instance = node('get_list')
    instance.node_data = {}
    result = await instance.execute({})
    assert result['status'] == 'success'
    assert len(transport.requests) == 1


@pytest.mark.asyncio
async def test_documented_custom_field_prefix(transport):
    # Current provider docs use custom_field_, unlike the pinned SDK path regex.
    # https://docs.sendx.io/api-reference/custom-field/get-custom-field-by-id.md
    documented_id = 'custom_field_MnuqBAG2NPLm7PZMWbjQxt'
    raw = credential()
    raw['custom_field_ids'] = [documented_id]
    transport.rows['custom_fields'][documented_id] = resource('custom_fields', documented_id)
    result = await node('get_custom_field', raw, custom_field_id=documented_id).run({})
    assert result['status'] == 'success'
    assert transport.requests[-1].url.path.endswith('/customfield/' + documented_id)
