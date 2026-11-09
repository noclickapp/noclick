"""Exercise ServiceTitan's real factory and transport boundary without an account."""
import json
import httpx
import pytest
from nodes import servicetitan_node as native
from nodes.core.registry import NodeFactory, NODE_REGISTRY

CREDS = {'credential_type': 'servicetitan_token', 'access_token': 'synthetic-access-44',
         'app_key': 'synthetic-app-55', 'tenant_id': '12345'}

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield

def node(config, **credentials):
    return NodeFactory.create_node(node_id='fixture', node_type='automation-servicetitan',
        node_data={'config': config, 'credentials': {**CREDS, **credentials}})

def transport(monkeypatch, body, status=200):
    requests = []
    def reply(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests

@pytest.mark.asyncio
@pytest.mark.parametrize('operation', native.OPERATIONS)
async def test_exact_contract_routes_bodies_auth_and_pagination(monkeypatch, operation):
    method, path, kind = native.OPERATIONS[operation]
    config = {'operation': operation}
    if '{id}' in path: config['id'] = 77
    if kind == 'update': config['summary' if operation.endswith('lead') else 'name'] = 'Updated'
    if kind == 'note': config.update(text='Please call tomorrow', pin_to_top=True)
    if kind == 'followup': config['follow_up_date'] = '2026-11-09T10:00:00Z'
    if kind == 'dismiss': config['dismissing_reason_id'] = 99
    body = {'page': 1, 'data': [{'id': 77, 'name': 'Account customer'}], 'hasMore': True, 'totalCount': 51} if kind == 'list' else {'id': 77}
    requests = transport(monkeypatch, body)
    result = await node(config).execute({})
    assert result['status'] == 'success'
    request, = requests
    assert request.method == method
    assert request.url.path == '/crm' + path.format(tenant='12345', id=77)
    assert request.headers['Authorization'] == 'Bearer ' + CREDS['access_token']
    assert request.headers['ST-App-Key'] == CREDS['app_key']
    if kind == 'list':
        assert dict(request.url.params) == {'page': '1', 'pageSize': '50', 'includeTotal': 'true'}
        assert result['next_page'] == 2
    elif kind == 'note': assert json.loads(request.content) == {'text': config['text'], 'pinToTop': True}
    elif kind == 'dismiss': assert json.loads(request.content) == {'dismissingReasonId': 99}
    elif kind == 'update': assert json.loads(request.content) == {k:v for k,v in config.items() if k not in {'id','operation'}}
    elif kind == 'followup': assert json.loads(request.content) == {'followUpDate': '2026-11-09T10:00:00+00:00'}

@pytest.mark.asyncio
async def test_environment_empty_last_page_and_error_redaction(monkeypatch):
    requests = transport(monkeypatch, {'page': 2, 'data': [], 'hasMore': False})
    result = await node({'operation': 'list_customers', 'page': 2}, environment='integration').execute({})
    assert requests[0].url.host == 'api-integration.servicetitan.io'
    assert result['next_page'] is None and result['data'] == []
    transport(monkeypatch, {'error': CREDS['access_token'] + CREDS['app_key']}, 401)
    result = await node({'operation': 'list_customers'}).execute({})
    assert result['status'] == 'error' and result['http_status'] == 401
    assert not any(secret in str(result) for secret in (CREDS['access_token'], CREDS['app_key']))

@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{}, {'page': 1, 'data': {}, 'hasMore': False}, {'page': 9, 'data': [], 'hasMore': False}])
async def test_malformed_or_mismatched_page_fails(monkeypatch, body):
    transport(monkeypatch, body)
    assert (await node({'operation': 'list_customers'}).execute({}))['status'] == 'error'

@pytest.mark.parametrize('change', [{'tenant_id': '../other'}, {'environment': 'https://evil.test'}, {'access_token': 'Bearer x'}])
def test_credential_boundaries(change):
    with pytest.raises(ValueError): native.ServiceTitanTokenCredential(**{**CREDS, **change})

def test_registration():
    assert NODE_REGISTRY['automation-servicetitan'] is native.ServiceTitanNode

def test_follow_up_requires_timezone():
    with pytest.raises(ValueError):
        native.CreateLeadFollowUpConfig(id=1, follow_up_date='2026-11-09T10:00:00')


# Resource examples copied verbatim from the published CRM contract:
# https://developer.servicetitan.io/api/docs/apis/tenant-crm
DOCUMENTED_RECORDS = {'customers': {'id': 0, 'active': True, 'name': 'string', 'type': {}, 'address': {'street': 'string', 'unit': 'string', 'city': 'string', 'state': 'string', 'zip': 'string', 'country': 'string', 'latitude': 0, 'longitude': 0}, 'customFields': [{'typeId': 0, 'name': 'string', 'value': 'string'}], 'balance': 0, 'taxExempt': True, 'tagTypeIds': [0], 'doNotMail': True, 'doNotService': True, 'nationalAccount': True, 'createdOn': 'string', 'createdById': 0, 'modifiedOn': 'string', 'mergedToId': 0, 'paymentTermId': 0, 'creditLimit': 0, 'creditLimitBalance': 0, 'externalData': [{'key': 'string', 'value': 'string'}]}, 'locations': {'id': 0, 'customerId': 0, 'active': True, 'name': 'string', 'address': {'street': 'string', 'unit': 'string', 'city': 'string', 'state': 'string', 'zip': 'string', 'country': 'string', 'latitude': 0, 'longitude': 0}, 'customFields': [{'typeId': 0, 'name': 'string', 'value': 'string'}], 'createdOn': 'string', 'createdById': 0, 'modifiedOn': 'string', 'mergedToId': 0, 'zoneId': 0, 'taxExempt': True, 'tagTypeIds': [0], 'externalData': [{'key': 'string', 'value': 'string'}], 'taxZoneId': 0}, 'leads': {'id': 0, 'status': {}, 'priority': {}, 'customerId': 0, 'locationId': 0, 'businessUnitId': 0, 'jobTypeId': 0, 'campaignId': 0, 'followUpDate': 'string', 'createdById': 0, 'createdOn': 'string', 'modifiedOn': 'string', 'tagTypeIds': [0], 'dismissingReasonId': 0, 'summary': 'string', 'callReasonId': 0, 'callId': 0, 'bookingId': 0, 'manualCallId': 0, 'leadUrl': 'string', 'leadCustomerName': 'string', 'leadPhone': 'string', 'leadEmail': 'string', 'leadStreet': 'string', 'leadUnit': 'string', 'leadCity': 'string', 'leadState': 'string', 'leadZip': 'string', 'leadCountry': 'string', 'captureSource': 'string'}}


def poll_state(instance, state=None):
    state = {} if state is None else state
    async def update(mutator, **kwargs):
        new_state, result = mutator(dict(state))
        if new_state is not None:
            state.clear()
            state.update(new_state)
        return result
    instance._update_node_state = update
    return state


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,resource', native.POLL_RESOURCES.items())
async def test_poll_baseline_creation_update_repeat_and_agent_context(monkeypatch, operation, resource):
    from copy import deepcopy
    record = deepcopy(DOCUMENTED_RECORDS[resource])
    # Preserve the provider's exact example, including id=0, for the baseline.
    body = {'page': 1, 'data': [record], 'hasMore': False}
    requests = transport(monkeypatch, body)
    instance = node({'operation': operation})
    state = poll_state(instance)
    assert (await instance.execute({}))['changed_count'] == 0
    assert not instance.should_propagate_output({'changed_count': 0}, {'operation': operation})
    assert instance.resolve_agent_event({'operation': operation, 'records': []}) is None
    # The following versions simulate changes to documented fields.
    record['id'] = 77
    result = await instance.execute({})
    assert result['changed_count'] == 1
    event = instance.resolve_agent_event(result)
    assert 'ServiceTitan' in event['text'] and 'id 77' in event['text']
    assert 'string' in event['text'] and event['conversation_key'] is None
    assert instance.trigger_emitted_event(result)
    assert (await instance.execute({}))['changed_count'] == 0
    record['modifiedOn'] = '2026-11-10T10:00:00Z'
    assert (await instance.execute({}))['changed_count'] == 1
    assert (await instance.execute({}))['changed_count'] == 0
    assert all(req.url.path == '/crm/v2/tenant/12345/' + resource for req in requests)
    assert all(req.url.params['sort'] == '-ModifiedOn' for req in requests)
    assert requests[0].headers['ST-App-Key'] == CREDS['app_key']
    assert requests[0].headers['Authorization'] == 'Bearer ' + CREDS['access_token']
    assert requests[0].url.params['active' if resource != 'leads' else 'genPermUrl'] == ('Any' if resource != 'leads' else 'true')
    assert state['scope']


@pytest.mark.asyncio
async def test_poll_paginates_before_dedup_and_rebaselines_changed_scope(monkeypatch):
    requests = []
    record = DOCUMENTED_RECORDS['customers']
    def reply(request):
        requests.append(request)
        page = int(request.url.params['page'])
        return httpx.Response(200, json={'page': page, 'data': [{**record, 'id': page}], 'hasMore': page == 1})
    monkeypatch.setattr(native, 'guarded_async_client', lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs))
    instance = node({'operation': 'on_new_or_updated_customer'})
    state = poll_state(instance, {'seen_ids': []})
    assert (await instance.execute({}))['changed_count'] == 2
    assert [r.url.params['page'] for r in requests] == ['1', '2']
    other = node({'operation': 'on_new_or_updated_customer', 'modified_on_or_after': '2026-11-01T05:30:00+05:30'})
    poll_state(other, state)
    assert (await other.execute({}))['changed_count'] == 0
    assert requests[-1].url.params['modifiedOnOrAfter'] == '2026-11-01T00:00:00+00:00'


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['later_page', 'malformed', 'missing_modified', 'overflow'])
async def test_poll_failure_does_not_consume_events(monkeypatch, failure):
    state = {'seen_ids': []}
    record = DOCUMENTED_RECORDS['customers']
    def reply(request):
        page = int(request.url.params['page'])
        if failure == 'later_page' and page == 2:
            return httpx.Response(401, text=CREDS['access_token'])
        if failure == 'malformed':
            return httpx.Response(200, json={'page': page + 1, 'data': [record], 'hasMore': False})
        if failure == 'missing_modified':
            return httpx.Response(200, json={'page': page, 'data': [{'id': 1}], 'hasMore': False})
        return httpx.Response(200, json={'page': page, 'data': [record], 'hasMore': True})
    monkeypatch.setattr(native, 'guarded_async_client', lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs))
    instance = node({'operation': 'on_new_or_updated_customer'})
    poll_state(instance, state)
    with pytest.raises(ValueError) as error:
        await instance.execute({})
    assert CREDS['access_token'] not in str(error.value)
    assert state == {'seen_ids': []}


def test_poll_schema_and_declared_scope():
    from nodes.core.poll_trigger import poll_scope
    schema = native.ServiceTitanFullConfig.model_json_schema()
    for operation in native.POLL_RESOURCES:
        parsed = node({'operation': operation}).config.config
        assert isinstance(parsed, native.ServiceTitanPollConfig)
        assert type(parsed).model_fields['operation'].json_schema_extra['x-is-trigger'] is True
        assert schema['$defs'][type(parsed).__name__]['x-requires-webhook'] is True
        native.SERVICETITAN_SCOPES.require(operation)
        assert poll_scope(native.ServiceTitanNode, {'operation': operation}) == poll_scope(
            native.ServiceTitanNode, {'operation': operation, 'label': 'Cosmetic edit'})
    with pytest.raises(ValueError):
        native.OnNewOrUpdatedCustomerConfig(modified_on_or_after='2026-11-01T00:00:00')
