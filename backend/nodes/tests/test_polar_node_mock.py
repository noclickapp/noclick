"""Polar native operations using synthetic provider and storage boundaries."""
import asyncio
import json
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import pytest_asyncio

from nodes import polar_node as provider
from nodes.polar_node import PolarNode as Node, OPERATIONS, TAG, NODE_TYPE, VERSION, MAX_BYTES
from nodes.core.registry import NodeFactory
from nodes.core import credential_connect as cc, connection_evidence as ce, run_op

ORG = '11111111-1111-4111-8111-111111111111'
PRODUCT_ID = '22222222-2222-4222-8222-222222222222'
CUSTOMER_ID = '33333333-3333-4333-8333-333333333333'
BENEFIT_ID = '44444444-4444-4444-8444-444444444444'
SUBSCRIPTION_ID = '55555555-5555-4555-8555-555555555555'
ORDER_ID = '66666666-6666-4666-8666-666666666666'
FOREIGN = '77777777-7777-4777-8777-777777777777'
TOKEN = 'polar_oat_SyntheticPrivateFixture42'
PII = 'SyntheticCustomerPrivate42'
ORGANIZATION = {'id': ORG, 'name': 'Fixture Organization', 'slug': 'fixture-organization', 'email': PII, 'payout_account_id': FOREIGN}
PRODUCT = {'id': PRODUCT_ID, 'organization_id': ORG, 'name': 'Fixture Product', 'description': 'Fixture Description', 'visibility': 'draft', 'is_archived': False, 'is_deletable': True, 'is_recurring': False, 'prices': [{'amount_type': 'fixed', 'price_amount': 0, 'price_currency': 'usd'}], 'metadata': {'private': TOKEN}, 'medias': [{'url': TOKEN}]}
CUSTOMER = {'id': CUSTOMER_ID, 'organization_id': ORG, 'type': 'individual', 'email': 'fixture@example.invalid', 'name': PII, 'billing_address': {'city': PII}, 'tax_id': PII, 'metadata': {'private': TOKEN}}
BENEFIT = {'id': BENEFIT_ID, 'organization_id': ORG, 'type': 'custom', 'description': 'Fixture Benefit', 'visibility': 'draft', 'deletable': True, 'properties': {'note': TOKEN}, 'metadata': {'private': PII}}
SUBSCRIPTION = {'id': SUBSCRIPTION_ID, 'customer_id': CUSTOMER_ID, 'customer': CUSTOMER, 'product_id': PRODUCT_ID, 'product': PRODUCT, 'status': 'active', 'amount': 12300, 'customer_cancellation_comment': PII}
ORDER = {'id': ORDER_ID, 'customer_id': CUSTOMER_ID, 'customer': CUSTOMER, 'product_id': PRODUCT_ID, 'product': PRODUCT, 'status': 'paid', 'total_amount': 12300, 'invoice_number': PII}
RESOURCES = {'products': PRODUCT, 'customers': CUSTOMER, 'benefits': BENEFIT, 'subscriptions': SUBSCRIPTION, 'orders': ORDER}


def credential():
    return {'credential_type': TAG, 'organization_access_token': TOKEN, 'environment': 'sandbox', 'organization_id': ORG, 'declared_scopes': ['organizations:read', 'products:write', 'customers:write', 'benefits:write', 'subscriptions:read', 'orders:read'], 'allowed_operations': list(OPERATIONS), 'resource_bindings': [{'kind': kind, 'resource_id': row['id'], 'owned_disposable': True, **({'customer_id': CUSTOMER_ID} if kind in ('subscriptions', 'orders') else {})} for kind, row in RESOURCES.items()]}


def arguments(op):
    result = {} if op == 'check_connection' else {'organization_id': ORG}
    if op in ('get_product', 'update_product_metadata', 'archive_product', 'delete_product'): result['product_id'] = PRODUCT_ID
    if op in ('get_customer', 'update_customer_metadata', 'delete_customer', 'list_subscriptions', 'get_subscription', 'list_orders', 'get_order'): result['customer_id'] = CUSTOMER_ID
    if op in ('get_benefit', 'update_custom_benefit_metadata', 'delete_custom_benefit'): result['benefit_id'] = BENEFIT_ID
    if op == 'get_subscription': result['subscription_id'] = SUBSCRIPTION_ID
    if op == 'get_order': result['order_id'] = ORDER_ID
    if op.startswith(('create_', 'update_', 'delete_', 'archive_')): result['confirm_effects'] = True
    if op in ('create_draft_product', 'update_product_metadata'): result['name'] = 'Updated Fixture Product'
    if op in ('create_draft_custom_benefit', 'update_custom_benefit_metadata'): result['description'] = 'Updated Fixture Benefit'
    if op in ('create_customer', 'update_customer_metadata'): result['metadata'] = {'fixture': True}
    if op == 'create_customer': result['email'] = 'fixture@example.invalid'
    if op == 'delete_customer': result['confirm_cascade'] = True
    if op == 'delete_custom_benefit': result['confirm_revoke'] = True
    return result


def node(op, raw=None, **changes):
    return NodeFactory.create_node(node_id='polar-fixture', node_type=NODE_TYPE, node_data={'config': {'operation': op, **arguments(op), **changes}, 'credentials': deepcopy(raw or credential())}, sio=None, user_id='fixture-user')


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest_asyncio.fixture
async def transport(monkeypatch):
    from utils import ssrf
    state = SimpleNamespace(requests=[], override=None, on_request=None, addresses=['93.184.216.34'])
    monkeypatch.setattr(asyncio.get_running_loop(), 'getaddrinfo', AsyncMock(side_effect=lambda *a, **k: [(2 if ':' not in ip else 10, 1, 6, '', (ip, 443)) for ip in state.addresses]))

    def response(request):
        state.requests.append(request)
        if state.on_request: state.on_request(request)
        if state.override:
            answer = state.override(request)
            if answer is not None: return answer
        assert request.url.scheme == 'https' and request.url.host == 'sandbox-api.polar.sh'
        assert request.headers['Authorization'] == 'Bearer ' + TOKEN and request.headers['Polar-Version'] == VERSION
        segments = request.url.path.strip('/').split('/')
        assert segments[0] == 'v1'
        kind = segments[1]
        headers = {'Polar-Version': VERSION}
        if kind == 'organizations':
            assert request.method == 'GET' and segments[2] == ORG and not request.url.query and not request.content
            return httpx.Response(200, json=ORGANIZATION, headers=headers)
        row = deepcopy(RESOURCES[kind])
        if request.method == 'GET':
            assert not request.content
            if len(segments) == 2:
                params = dict(request.url.params)
                assert params['organization_id'] == ORG
                if kind in ('orders', 'subscriptions'): assert params['customer_id'] == CUSTOMER_ID
                return httpx.Response(200, json={'items': [row], 'pagination': {'total_count': 1, 'max_page': 1}}, headers=headers)
            assert segments[2] == row['id'] and not request.url.query
            return httpx.Response(200, json=row, headers=headers)
        assert kind in ('products', 'customers', 'benefits') and not request.url.query
        if request.method == 'DELETE':
            assert not request.content
            return httpx.Response(204, headers=headers)
        body = json.loads(request.content)
        if request.method == 'POST':
            assert len(segments) == 2 and body['organization_id'] == ORG
            if kind == 'products': assert body['visibility'] == 'draft' and body['recurring_interval'] is None and body['prices'] == [{'amount_type': 'fixed', 'price_amount': 0, 'price_currency': 'usd'}]
            if kind == 'benefits': assert body['type'] == 'custom' and body['visibility'] == 'draft' and body['properties'] == {}
        else:
            assert request.method == 'PATCH' and set(body) <= {'name', 'description', 'metadata', 'is_archived', 'type'}
        return httpx.Response(201 if request.method == 'POST' else 200, json={**row, **body}, headers=headers)

    def client(**kwargs):
        assert kwargs == {'timeout': 60, 'follow_redirects': False, 'trust_env': False}
        return ssrf.guarded_async_client(transport=httpx.MockTransport(response), **kwargs)
    monkeypatch.setattr(provider, 'guarded_async_client', client)
    return state


@pytest.mark.asyncio
@pytest.mark.parametrize('op', OPERATIONS)
async def test_actual_factory_all_operations_and_private_projection(transport, caplog, op):
    result = await node(op).run({})
    assert result['status'] == 'success' and result['action'] == op and result['account_identity_verified'] is False
    assert TOKEN not in json.dumps(result) + caplog.text and PII not in json.dumps(result) + caplog.text
    if op.startswith('delete_'): assert result['http_status'] == 204 and result['cleanup_verified'] is False
    if op.startswith('create_'): assert result['http_status'] == 201 and result['owned_disposable_binding_added'] is False
    if op.startswith(('create_', 'update_', 'delete_', 'archive_')): assert result['provider_effects_verified'] is False
    assert not any(hazard in str(r.url) for r in transport.requests for hazard in ('oauth2', 'customer-portal', 'checkouts', 'refunds', 'payouts', 'benefit-grants', 'customer-sessions', 'webhooks'))


@pytest.mark.asyncio
async def test_real_manual_connect_shaping_and_reachability_only(transport):
    raw = credential(); raw.pop('credential_type')
    shaped, errors, _ = cc.shape_credential(TAG, raw)
    assert not errors and shaped['credential_type'] == TAG
    result = await cc.validate_for_connect(credential_type=TAG, credential_data=raw, user_id='fixture-user')
    assert result.ok and result.evidence.reachable is True and Node.connection_evidence.proves == 'reachability'
    assert result.evidence.account_label is None and result.evidence.samples == [] and len(transport.requests) == 1
    assert TOKEN not in json.dumps(asdict(result.evidence)) and not result.verified_metadata().get('verified_as')


@pytest.mark.asyncio
@pytest.mark.parametrize('case', ['foreign', 'custom-host', 'scope', 'organization', 'resource', 'disposable'])
async def test_native_authority_denials_before_provider(transport, case):
    raw = credential()
    if case == 'foreign':
        raw['credential_type'] = 'stripe_api_key'
        assert not Node.validate_config({'operation': 'check_connection', 'credentials': raw})['valid']
        assert not (await cc.validate_for_connect(credential_type=TAG, credential_data=raw, user_id='fixture-user')).ok
        with pytest.raises(ValueError): await Node.load_field_options('organization_id', raw)
    elif case == 'custom-host':
        raw['api_base_url'] = 'https://example.invalid'
        with pytest.raises(ValueError): node('check_connection', raw)
    else:
        changes = {}
        if case == 'scope': raw['declared_scopes'].remove('products:write')
        elif case == 'organization': changes['organization_id'] = FOREIGN
        elif case == 'resource': changes['product_id'] = FOREIGN
        else: raw['resource_bindings'][0]['owned_disposable'] = False
        assert (await node('delete_product', raw, **changes).run({}))['status'] == 'error'
    assert transport.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize('case', ['organization', 'id', 'version', 'missing-version', '202', '204', '401', '403', '429', 'text', 'oversize', 'error', 'empty'])
async def test_version_identity_status_envelope_failures(transport, case):
    def response(request):
        if '/products/' not in request.url.path: return None
        headers = {'Polar-Version': VERSION}
        if case == 'version': headers['Polar-Version'] = '2027-01'
        if case == 'missing-version': headers = {}
        if case.isdigit(): return httpx.Response(int(case), json={'detail': TOKEN}, headers=headers)
        if case == 'text': return httpx.Response(200, content=PII, headers={**headers, 'content-type': 'text/plain'})
        if case == 'oversize': return httpx.Response(200, content=b'x' * (MAX_BYTES + 1), headers={**headers, 'content-type': 'application/json'})
        payload = {**PRODUCT, **({'organization_id': FOREIGN} if case == 'organization' else {'id': FOREIGN} if case == 'id' else {})}
        return httpx.Response(200, json={'detail': TOKEN} if case == 'error' else {} if case == 'empty' else payload, headers=headers)
    transport.override = response
    result = await node('get_product').run({})
    assert result['status'] == 'error' and TOKEN not in json.dumps(result) and PII not in json.dumps(result)


@pytest.mark.asyncio
async def test_real_run_op_sparse_patch_explicit_clear_and_no_price_changes(transport):
    result = await run_op.run_node_operation(node_type=NODE_TYPE, operation='update_product_metadata', arguments={**arguments('update_product_metadata'), 'operation': 'delete_product', 'description': None}, credential_data=credential(), user_id='fixture-user')
    assert result['status'] == 'success'
    body = json.loads(next(r for r in transport.requests if r.method == 'PATCH').content)
    assert body == {'name': 'Updated Fixture Product', 'description': ''}
    assert not {'prices', 'visibility', 'benefits'} & set(body)
    transport.override = lambda r: httpx.Response(202, headers={'Polar-Version': VERSION}) if r.method == 'DELETE' else None
    assert (await node('delete_customer').run({}))['status'] == 'error'


@pytest.mark.asyncio
@pytest.mark.parametrize('case', ['foreign-org', 'foreign-customer', 'foreign-product'])
async def test_order_and_subscription_actual_parent_witness(transport, case):
    def response(request):
        if request.url.path.endswith('/' + ORDER_ID):
            row = deepcopy(ORDER)
            if case == 'foreign-org': row['customer']['organization_id'] = FOREIGN
            if case == 'foreign-customer': row['customer_id'] = FOREIGN
            if case == 'foreign-product': row['product']['organization_id'] = FOREIGN
            return httpx.Response(200, json=row, headers={'Polar-Version': VERSION})
    transport.override = response
    assert (await node('get_order').run({}))['status'] == 'error'


@pytest.mark.asyncio
async def test_actual_parent_picker_counts_and_no_continuation_guess(transport):
    result = await Node.load_field_options('order_id', credential(), context={'organization_id': ORG, 'customer_id': CUSTOMER_ID})
    assert result['options'][0]['metadata'] == {'organization_id': ORG, 'environment': 'sandbox', 'customer_id': CUSTOMER_ID} and result['next_page_token'] is None
    before = len(transport.requests)
    with pytest.raises(ValueError): await Node.load_field_options('order_id', credential(), context={'organization_id': ORG})
    assert len(transport.requests) == before
    transport.override = lambda r: httpx.Response(200, json={'items': [], 'pagination': {'total_count': 51, 'max_page': 3}}, headers={'Polar-Version': VERSION}) if r.url.path == '/v1/products/' else None
    result = await Node.load_field_options('product_id', credential(), context={'organization_id': ORG})
    assert result['options'] == [] and result['next_page_token'] == '2'
    with pytest.raises(ValueError): await Node.load_field_options('product_id', credential(), context={'organization_id': ORG}, page_token='https://foreign.invalid/next')


@pytest.mark.asyncio
@pytest.mark.parametrize('case', ['success', '401', '403', '429', 'malformed'])
async def test_credential_access_uses_protected_organization(transport, case):
    if case.isdigit():
        transport.override = lambda _: httpx.Response(int(case), json={'detail': TOKEN})
    elif case == 'malformed':
        transport.override = lambda _: httpx.Response(200, json={}, headers={'Polar-Version': VERSION})
    result = await Node.validate_credential_access(credential())
    assert result['valid'] is (True if case == 'success' else False if case in ('401', '403') else None)
    assert len(transport.requests) == 1
    assert TOKEN not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize('case', ['unchanged', 'missing', 'token', 'environment', 'grant'])
async def test_saved_credential_recheck(transport, monkeypatch, case):
    from utils import credentials
    current = deepcopy(credential())
    if case == 'missing': current = None
    elif case == 'token': current['organization_access_token'] = 'polar_oat_OtherSyntheticToken42'
    elif case == 'environment': current['environment'] = 'production'
    elif case == 'grant': current['allowed_operations'] = ['check_connection']
    resolve = AsyncMock(return_value=current)
    monkeypatch.setattr(credentials, 'resolve_credential_with_owner_fallback', resolve)
    authority = {'credential_id': 'fixture', 'user_id': 'fixture-user', 'pool': object()}
    if case == 'unchanged':
        await Node._recheck(authority, provider._credential(credential()))
    else:
        with pytest.raises(ValueError):
            await Node._recheck(authority, provider._credential(credential()))
    resolve.assert_awaited_once_with(**authority)
    assert transport.requests == []


@pytest.mark.asyncio
async def test_explicit_production_root_without_fallback(transport):
    raw = credential(); raw['environment'] = 'production'
    def response(request):
        assert request.url.host == 'api.polar.sh' and request.url.path == '/v1/organizations/' + ORG
        return httpx.Response(200, json=ORGANIZATION, headers={'Polar-Version': VERSION})
    transport.override = response
    assert (await node('check_connection', raw).run({}))['status'] == 'success' and len(transport.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('case', ['not-deletable', 'public-benefit', 'non-custom-benefit', 'changed-metadata', 'nonzero-price'])
async def test_actual_disposable_and_write_response_constraints(transport, case):
    def response(request):
        if case == 'not-deletable' and request.url.path.endswith('/' + PRODUCT_ID): return httpx.Response(200, json={**PRODUCT, 'is_deletable': False}, headers={'Polar-Version': VERSION})
        if case in ('public-benefit', 'non-custom-benefit') and request.url.path.endswith('/' + BENEFIT_ID): return httpx.Response(200, json={**BENEFIT, **({'visibility': 'public'} if case == 'public-benefit' else {'type': 'discord'})}, headers={'Polar-Version': VERSION})
        if case == 'changed-metadata' and request.method == 'PATCH': return httpx.Response(200, json={**CUSTOMER, 'metadata': {'fixture': False}}, headers={'Polar-Version': VERSION})
        if case == 'nonzero-price' and request.method == 'POST': return httpx.Response(201, json={**PRODUCT, **json.loads(request.content), 'prices': [{'amount_type': 'fixed', 'price_amount': 50, 'price_currency': 'usd'}]}, headers={'Polar-Version': VERSION})
    transport.override = response
    op = 'delete_product' if case == 'not-deletable' else 'delete_custom_benefit' if case in ('public-benefit', 'non-custom-benefit') else 'update_customer_metadata' if case == 'changed-metadata' else 'create_draft_product'
    assert (await node(op).run({}))['status'] == 'error'
    if case in ('not-deletable', 'public-benefit', 'non-custom-benefit'): assert not any(r.method == 'DELETE' for r in transport.requests)


@pytest.mark.asyncio
@pytest.mark.parametrize('status', ['pending', 'rejected'])
async def test_actual_admission_precedes_request_and_evidence(transport, monkeypatch, status):
    from repositories.credential_approvals import CredentialApprovalRepo
    monkeypatch.setattr(run_op, 'resolve_credential_with_owner_fallback', AsyncMock(return_value=credential()))
    monkeypatch.setattr(CredentialApprovalRepo, 'admit', AsyncMock(return_value={'id': 'approval-fixture', 'status': status, 'new_request': False}))
    kwargs = {'node_type': NODE_TYPE, 'credential_id': 'row-fixture', 'user_id': 'fixture-user', 'pool': object()}
    result = await run_op.run_node_operation(operation='check_connection', arguments={}, **kwargs)
    evidence = await ce.collect_evidence(**kwargs)
    assert result['executed'] is False and evidence.reachable is None and transport.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize('context', [{}, {'organization_id': FOREIGN, 'customer_id': CUSTOMER_ID}])
async def test_picker_parent_restrictions_before_provider(transport, context):
    with pytest.raises(ValueError):
        await Node.load_field_options('order_id', credential(), context=context)
    assert transport.requests == []


def test_saved_config_strict_confirmations_and_closed_financial_surface():
    assert Node.validate_saved_config({'operation': 'get_order', **arguments('get_order')})['valid']
    for value in (1, False, 'true'):
        with pytest.raises(ValueError): node('delete_customer', confirm_cascade=value)
    for op in ('create_order', 'refund_order', 'cancel_subscription', 'grant_benefit', 'send_invoice', 'create_checkout', 'create_webhook', 'update_price', 'publish_product'):
        with pytest.raises(ValueError): node(op)


@pytest.mark.asyncio
@pytest.mark.parametrize('addresses', [['127.0.0.1'], ['::1'], ['93.184.216.34', '10.0.0.1'], []])
async def test_public_transport_denial_before_token_use(transport, monkeypatch, addresses):
    from utils import ssrf
    monkeypatch.setattr(ssrf, 'allow_private_hosts', lambda: False)
    transport.addresses = addresses
    assert (await node('check_connection').run({}))['status'] == 'error' and transport.requests == []


@pytest.mark.asyncio
async def test_parsed_credentials_without_duplicate_raw_blob(transport):
    instance = Node(
        node_id='polar-parsed-config',
        node_type=NODE_TYPE,
        node_data={},
        config=provider.PolarFullConfig.model_validate({
            'config': {'operation': 'check_connection'},
            'credentials': credential(),
        }),
        sio=None,
    )
    assert (await instance.execute({}))['status'] == 'success'
    assert len(transport.requests) == 1


@pytest.mark.asyncio
async def test_raw_credential_mismatch_still_rejected(transport):
    instance = node('check_connection')
    instance.node_data['credentials'] = {**credential(), 'environment': 'production'}
    assert (await instance.execute({}))['status'] == 'error'
    assert transport.requests == []


# Event envelope and fields: https://polar.sh/docs/openapi/2026-10.openapi.json.
# These synthetic records exercise the documented customer/order/subscription schemas.
@pytest.mark.parametrize('operation,event,record', [
    (op, event, {'on_order_event': ORDER, 'on_subscription_event': SUBSCRIPTION, 'on_customer_event': CUSTOMER}[op])
    for op, events in provider.TRIGGER_EVENTS.items() for event in events
])
def test_trigger_delivery_and_agent_turn(operation, event, record):
    payload = {'type': event, 'timestamp': '2026-01-01T00:00:00.000000Z', 'api_version': VERSION, 'data': deepcopy(record)}
    config = {'operation': operation, 'event_type': event, 'organization_id': ORG}
    assert Node.filter_trigger_payload(payload, config)
    assert not Node.filter_trigger_payload(payload, {**config, 'event_type': 'order.unsupported'})
    assert Node.resolve_trigger_payload(payload, config) is payload
    turn = Node.resolve_agent_event(payload)
    assert event in turn['text'] and record['id'] in turn['text'] and ORG in turn['text']
    assert turn['conversation_key'] == record['id']
    assert Node.registration_fingerprint_fields(config) == {'event_type': event, 'organization_id': ORG}


@pytest.mark.parametrize('legacy', [False, True])
def test_polar_documented_signature_keys_and_tampering(monkeypatch, legacy):
    import base64
    import hashlib
    import hmac
    # Both schemes: https://polar.sh/docs/integrate/webhooks/delivery#custom-validation.
    secret = 'whsec_' + base64.b64encode(b'unit-test-signing-key').decode().rstrip('=')
    key = secret.encode() if legacy else b'unit-test-signing-key'
    monkeypatch.setattr(provider.time, 'time', lambda: 1800000000)
    body = json.dumps({'type': 'customer.created', 'timestamp': '2026-01-01T00:00:00.000000Z', 'api_version': VERSION, 'data': CUSTOMER}).encode()
    signature = base64.b64encode(hmac.new(key, b'delivery-id.1800000000.' + body, hashlib.sha256).digest()).decode()
    headers = {'Webhook-Id': 'delivery-id', 'Webhook-Timestamp': '1800000000', 'Webhook-Signature': 'v1,invalid v1,' + signature}
    assert Node.verify_webhook_signature(body, headers, {'signing_secret': secret})
    assert not Node.verify_webhook_signature(body + b' ', headers, {'signing_secret': secret})
    for field, value in [('Webhook-Id', 'other'), ('Webhook-Timestamp', '1799999699'), ('Webhook-Timestamp', '1800000301')]:
        assert not Node.verify_webhook_signature(body, {**headers, field: value}, {'signing_secret': secret})
    assert not Node.verify_webhook_signature(body, {}, {'signing_secret': secret})
    assert not Node.verify_webhook_signature(body, headers, {})


@pytest.mark.asyncio
async def test_webhook_registration_cleanup_and_restrictions(monkeypatch):
    raw = credential()
    raw['allowed_operations'].append('on_order_event')
    raw['declared_scopes'].append('webhooks:write')
    config = {'operation': 'on_order_event', 'event_type': 'order.paid', 'organization_id': ORG}
    requests = []
    def response(request):
        requests.append(request)
        assert request.headers['Authorization'] == 'Bearer ' + TOKEN
        assert request.headers['Polar-Version'] == VERSION
        if request.method == 'POST':
            assert request.url.path == '/v1/webhooks/endpoints'
            assert json.loads(request.content) == {'url': 'https://example.com/webhook', 'format': 'raw', 'api_version': VERSION, 'events': ['order.paid'], 'organization_id': ORG}
            return httpx.Response(201, json={'id': 'endpoint-id', 'secret': 'whsec_dGVzdC1rZXk='})
        assert request.method == 'DELETE' and request.url.path == '/v1/webhooks/endpoints/endpoint-id'
        return httpx.Response(204)
    monkeypatch.setattr(provider, 'guarded_async_client', lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(response)))
    registration = await Node._register_external_webhook(webhook_url='https://example.com/webhook', credential=raw, config=config, node_id='test')
    assert registration == {'external_webhook_id': 'endpoint-id', 'signing_secret': 'whsec_dGVzdC1rZXk='}
    await Node._unregister_external_webhook(credential=raw, config={**config, **registration}, node_id='test')
    assert len(requests) == 2
    for bad in ({**raw, 'declared_scopes': ['organizations:read']}, {**raw, 'allowed_operations': ['check_connection']}):
        with pytest.raises(ValueError):
            await Node._register_external_webhook(webhook_url='https://example.com/webhook', credential=bad, config=config, node_id='test')
    with pytest.raises(ValueError):
        await Node._register_external_webhook(webhook_url='https://example.com/webhook', credential=raw, config={**config, 'organization_id': FOREIGN}, node_id='test')
    manual = NodeFactory.create_node(node_id='trigger', node_type=NODE_TYPE, node_data={'config': config, 'credentials': raw}, sio=None, user_id='test')
    assert (await manual.execute({}))['status'] == 'no_event'
    assert len(requests) == 2
