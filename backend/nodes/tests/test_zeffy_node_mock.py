"""Zeffy v1 exact HTTP contract regressions, entirely offline."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import zeffy_node as native
from nodes.core.registry import NodeFactory

FIXTURES = json.loads((Path(__file__).parent / 'fixtures/zeffy/resources.json').read_text())
TOKEN = 'synthetic-zeffy-key-93'
CREDENTIAL = {'credential_type': 'zeffy_api_key', 'api_key': TOKEN}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='zeffy-test', node_type='automation-zeffy',
        node_data={'config': config, 'credentials': CREDENTIAL})


def transport(monkeypatch, body, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body) if status != 204 else httpx.Response(204)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,method,resource,id_field', [
    (op, *route) for op, route in native.ROUTES.items()
])
async def test_every_operation_one_exact_contract_request(monkeypatch, operation, method, resource, id_field):
    singular = resource[:-1]
    record = FIXTURES[singular]
    config = {'operation': operation}
    if id_field:
        config[id_field] = record['id']
    if operation == 'create_payment':
        config.update(campaign_id='0d4f60d1-4f4f-4f4f-8f4f-0d4f60d14f4f', amount=2500)
    if operation in {'create_contact', 'upsert_contact', 'update_contact'}:
        config['email'] = 'jane@example.com'
    status = 204 if operation == 'delete_contact' else 201 if operation in {'create_contact','create_payment'} else 200
    response = {'object': 'list', 'data': [record], 'has_more': False, 'next_cursor': None} if operation.startswith('list_') else record
    requests = transport(monkeypatch, response, status)
    result = await node(config).execute({})
    assert result['status'] == 'success', result
    assert len(requests) == 1
    req = requests[0]
    assert req.method == method and req.url.host == 'api.zeffy.com'
    assert req.url.path == '/api/v1/' + resource + ('/' + record['id'] if id_field else '')
    assert req.headers['authorization'] == 'Bearer ' + TOKEN
    if operation.startswith('list_'):
        assert dict(req.url.params) == {'limit': '10'}
        assert result['data'] == [record] and result['has_more'] is False
    if operation == 'create_payment':
        assert json.loads(req.content) == {'campaign_id': config['campaign_id'], 'amount': 2500, 'payment_method': 'cash', 'generate_tax_receipt': False, 'send_confirmation_email': False}
    if operation in {'create_contact','upsert_contact','update_contact'}:
        assert json.loads(req.content) == {'email': 'jane@example.com'}
    if operation == 'delete_contact':
        assert result['deleted_id'] == record['id'] and result['deletion_acknowledged']
    assert TOKEN not in str(result)


@pytest.mark.asyncio
async def test_paginated_filter_encoding_and_resume_are_explicit(monkeypatch):
    record = FIXTURES['contact']
    page = {'object':'list','data':[record],'has_more':True,'next_cursor':record['id']}
    requests = transport(monkeypatch, page)
    config = {'operation':'list_contacts','email':'jane+donor@example.com','created_gte':1700000000,'updated_lt':1709856000,'limit':100}
    result = await node(config).execute({})
    assert result['has_more'] and result['next_cursor'] == record['id']
    assert dict(requests[0].url.params) == {'email':config['email'],'created[gte]':'1700000000','updated[lt]':'1709856000','limit':'100'}
    await node({**config,'starting_after':result['next_cursor']}).execute({})
    assert requests[1].url.params['starting_after'] == record['id']
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_patch_preserves_null_and_omitted_fields(monkeypatch):
    record = FIXTURES['contact']
    requests = transport(monkeypatch, record)
    result = await node({'operation':'update_contact','contact_id':record['id'],'phone_number':None,'address':None}).execute({})
    assert result['status'] == 'success'
    assert json.loads(requests[0].content) == {'phone_number':None,'address':None}


@pytest.mark.asyncio
async def test_full_documented_address_is_sent_without_extra_keys(monkeypatch):
    requests = transport(monkeypatch, FIXTURES['contact'], 201)
    address = {'line1':'123 Main St','city':'Montreal','state':'QC','postal_code':'H2X 1Y4','country':'CA'}
    result = await node({'operation':'create_contact','email':'jane@example.com','address':address}).execute({})
    assert result['status']=='success'
    assert json.loads(requests[0].content)=={'email':'jane@example.com','address':address}


@pytest.mark.asyncio
async def test_ticket_payment_body_and_explicit_email_opt_ins(monkeypatch):
    requests = transport(monkeypatch, FIXTURES['payment'], 201)
    config = {'operation':'create_payment','campaign_id':'campaign-1','tickets':[{'rate_id':'rate-1','quantity':2,'amount':1500}],
        'occurrence_id':'occurrence-1','extra_donation':500,'payment_date':'2026-01-15','generate_tax_receipt':True,'send_confirmation_email':True}
    assert (await node(config).execute({}))['status'] == 'success'
    assert json.loads(requests[0].content) == {**{k:v for k,v in config.items() if k!='operation'},'payment_method':'cash'}


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301,302,400,401,403,404,409,429,500])
async def test_provider_errors_are_not_success_or_retried(monkeypatch, status):
    requests = transport(monkeypatch, {'error':{'message':'Rejected ' + TOKEN,'code':'invalid_api_key'}},status)
    result = await node({'operation':'list_campaigns'}).execute({})
    assert result['status'] == 'error' and result['http_status'] == status
    assert result['error'] == 'Rejected [redacted]' and len(requests)==1


@pytest.mark.asyncio
@pytest.mark.parametrize('response', [{}, {'object':'list','data':[]}, {'object':'list','data':[],'has_more':'true','next_cursor':None},
    {'object':'list','data':[{'id':'wrong','object':'contact'}],'has_more':False,'next_cursor':None}, {'error':{'message':'bad'}}])
async def test_malformed_success_fails_closed(monkeypatch, response):
    transport(monkeypatch, response)
    assert (await node({'operation':'list_campaigns'}).execute({}))['status']=='error'


@pytest.mark.asyncio
async def test_detail_refuses_wrong_id_and_upsert_accepts_created(monkeypatch):
    record = FIXTURES['contact']
    transport(monkeypatch, record)
    assert (await node({'operation':'get_contact','contact_id':'different-id'}).execute({}))['status']=='error'
    transport(monkeypatch, record, 201)
    assert (await node({'operation':'upsert_contact','email':'jane@example.com'}).execute({}))['http_status']==201


@pytest.mark.parametrize('config', [
    {'operation':'get_contact','contact_id':'../other'}, {'operation':'list_users','limit':101},
    {'operation':'list_users','limit':True}, {'operation':'list_users','starting_after':'one','ending_before':'two'},
    {'operation':'create_contact'}, {'operation':'create_contact','email':'not-email'},
    {'operation':'create_contact','email':'jane@example.com','address':{'city':'Montreal'}},
    {'operation':'upsert_contact'}, {'operation':'update_contact','contact_id':'contact-1'},
    {'operation':'create_payment','campaign_id':'campaign-1'},
    {'operation':'create_payment','campaign_id':'campaign-1','amount':2500,'tickets':[{'rate_id':'rate-1','quantity':2}]},
    {'operation':'create_payment','campaign_id':'campaign-1','amount':2500,'payment_date':'2026-02-30'},
])
def test_invalid_configs_are_rejected(config):
    with pytest.raises((ValidationError, ValueError)):
        native.ZeffyNode.parse_config({'config':config,'credentials':CREDENTIAL})


def test_manual_credential_default_and_evidence_contract():
    credential = native.ZeffyAPIKeyCredential.model_validate({'api_key':TOKEN})
    assert credential.credential_type=='zeffy_api_key'
    assert native.ZeffyNode.connection_evidence.operation=='list_campaigns'
    assert native.ZeffyNode.connection_evidence.proves=='account'
