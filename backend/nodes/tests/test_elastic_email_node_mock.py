"""Elastic Email v4 wire regressions through the native node factory.

Provider examples supply the fixtures. HTTP interception verifies routing,
headers, bodies, pagination and failure behavior without sending real mail.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import elastic_email_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-elastic-email-token"
FIXTURE = json.loads((Path(__file__).parent / 'fixtures/elastic-email/requests.json').read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def make_node(config, credential=None):
    return NodeFactory.create_node(node_id="elastic-email-test", node_type="automation-elastic-email",
        node_data={"config": config, "credentials": credential or {"credential_type": "elastic_email_api_key", "api_key": TOKEN}})


def intercept(monkeypatch, respond):
    requests=[]
    def reply(request):
        requests.append(request)
        return respond(request)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('case', FIXTURE['cases'], ids=lambda c:c['config']['operation'])
async def test_elastic_email_documented_wire_contract(monkeypatch, case):
    requests=intercept(monkeypatch, lambda r: httpx.Response(case['status'], **({'json':case['response']} if case['response'] is not None else {})))
    result=await make_node(case['config']).execute({})
    assert result['status']=='success', result
    assert result['status_code']==case['status']
    assert len(requests)==1
    request=requests[0]
    assert request.method==case['method'] and request.url.path==case['path']
    assert request.url.scheme=='https' and request.url.host=='api.elasticemail.com'
    assert request.headers['X-ElasticEmail-ApiKey']==TOKEN
    assert 'authorization' not in request.headers and TOKEN not in str(request.url)
    assert (json.loads(request.content) if request.content else None)==case['body']
    params={key:request.url.params.get_list(key) if isinstance(value,list) else request.url.params[key] for key,value in case['params'].items()}
    assert params==case['params'] and set(request.url.params)==set(case['params'])
    assert TOKEN not in str(result)
    if case['response'] is not None:
        assert result['data']==case['response']
    else:
        assert result['acknowledged'] is True
    if case['config']['operation']=='send_transactional_email':
        assert request.headers['Idempotency-Key']==case['config']['idempotency_key']
        assert result['accepted'] is True and result['delivery_verified'] is False


@pytest.mark.asyncio
async def test_elastic_email_explicit_offset_paging_and_empty_page(monkeypatch):
    requests=intercept(monkeypatch,lambda r:httpx.Response(200,json=[{'Email':'mail@example.com'}]*2))
    result=await make_node({'operation':'list_contacts','limit':2,'offset':20}).execute({})
    assert result['has_more'] is True and result['next_offset']==22
    assert len(requests)==1
    intercept(monkeypatch,lambda r:httpx.Response(200,json=[]))
    result=await make_node({'operation':'list_contacts','limit':2,'offset':22}).execute({})
    assert result['has_more'] is False and result['next_offset'] is None


@pytest.mark.asyncio
async def test_elastic_email_path_encoding_cannot_change_host_or_query(monkeypatch):
    requests=intercept(monkeypatch,lambda r:httpx.Response(200,json={'ListName':'A/B + ?# café'}))
    await make_node({'operation':'get_list','name':'A/B + ?# café'}).execute({})
    assert requests[0].url.raw_path==b'/v4/lists/A%2FB%20%2B%20%3F%23%20caf%C3%A9'
    for value in ('.','..'):
        with pytest.raises(ValueError):
            await make_node({'operation':'get_list','name':value}).execute({})
    assert len(requests)==1


@pytest.mark.asyncio
@pytest.mark.parametrize('status',[301,401,403,429,500])
async def test_elastic_email_provider_rejection_preserves_status_redacts_and_never_retries(monkeypatch,status):
    requests=intercept(monkeypatch,lambda r:httpx.Response(status,json={'Error':'Denied '+TOKEN},headers={'Location':'https://example.org','Retry-After':'1'}))
    result=await make_node({'operation':'send_transactional_email','from_email':'mail@example.com','to':['mail@example.com'],'subject':'Hello!','body':'Hello!'}).execute({})
    assert result['status']=='error' and result['status_code']==status
    assert 'Denied' in result['error'] and TOKEN not in str(result)
    assert len(requests)==1 and 'data' not in result


@pytest.mark.asyncio
@pytest.mark.parametrize('payload',[{},'wrong',[1],{'Error':'Denied'}])
async def test_elastic_email_rejects_malformed_list_or_error_envelope(monkeypatch,payload):
    intercept(monkeypatch,lambda r:httpx.Response(200,json=payload))
    result=await make_node({'operation':'list_lists'}).execute({})
    assert result['status']=='error' and 'data' not in result


@pytest.mark.asyncio
async def test_elastic_email_timeout_does_not_claim_success_or_repeat_send(monkeypatch):
    def timeout(request):
        raise httpx.ReadTimeout('synthetic timeout '+TOKEN, request=request)
    requests=intercept(monkeypatch,timeout)
    result=await make_node({'operation':'send_transactional_email','from_email':'mail@example.com','to':['mail@example.com'],'template_name':'Template01'}).execute({})
    assert result['status']=='error' and 'accepted' not in result and TOKEN not in str(result)
    assert len(requests)==1


@pytest.mark.parametrize('key',['https://example.com','<token>','abc\ndef','Bearer token','ékey',''])
def test_elastic_email_manual_credential_rejects_bad_key(key):
    with pytest.raises(ValidationError):
        native.ElasticEmailAPIKeyCredential(api_key=key)


def test_elastic_email_key_shaping_and_evidence_names():
    assert native.ElasticEmailAPIKeyCredential(api_key='  '+TOKEN+'\n').api_key==TOKEN
    evidence=native.ElasticEmailNode.connection_evidence
    assert evidence.operation=='list_lists' and evidence.label_keys==('ListName',)
    assert evidence.identity_operation=='get_account'
    with pytest.raises(ValidationError) as error:
        native.ElasticEmailFullConfig.model_validate({'config':{'operation':'get_account'},
            'credentials':{'api_key':TOKEN+' invalid'}})
    assert TOKEN not in str(error.value)


@pytest.mark.parametrize('config',[
    {'operation':'create_list','list_name':'My List 1','emails':[]},
    {'operation':'add_list_contacts','name':'My List 1','emails':[]},
    {'operation':'update_contact','email':'mail@example.com'},
    {'operation':'update_list','name':'My List 1'},
    {'operation':'send_transactional_email','from_email':'mail@example.com','to':['mail@example.com']},
    {'operation':'add_contacts','email':'mail@example.com','custom_fields_json':'{"age":34}'},
    {'operation':'send_transactional_email','from_email':'mail@example.com','to':['bad'],'template_name':'Template01'},
])
def test_elastic_email_invalid_writes_fail_before_network(config):
    with pytest.raises(ValueError):
        make_node(config)


@pytest.mark.asyncio
async def test_elastic_email_minimal_contact_omits_status_and_optional_fields(monkeypatch):
    requests=intercept(monkeypatch,lambda r:httpx.Response(200,json=[{'Email':'mail@example.com'}]))
    await make_node({'operation':'add_contacts','email':'mail@example.com'}).execute({})
    assert json.loads(requests[0].content)==[{'Email':'mail@example.com'}]
    assert not requests[0].url.params


@pytest.mark.asyncio
@pytest.mark.parametrize('status',[200,401,500])
async def test_elastic_email_connection_evidence_executes_account_read(monkeypatch,status):
    from nodes.core.connection_evidence import collect_evidence
    from nodes.core import run_op
    payload=[{'ListName':'My List 1'}] if status==200 else {'Error':'Invalid API key'}
    requests=intercept(monkeypatch,lambda r:httpx.Response(status,json=payload))
    async def native_run(**kwargs):
        return await make_node({'operation':kwargs['operation'], **kwargs['arguments']}).execute({})
    monkeypatch.setattr(run_op,'run_node_operation',native_run)
    evidence=await collect_evidence(node_type='automation-elastic-email',user_id='synthetic-user',
        credential_data={'credential_type':'elastic_email_api_key','api_key':TOKEN})
    assert len(requests)==1
    if status==200:
        assert evidence.reachable is True and evidence.samples[0].label=='My List 1'
    elif status==401:
        assert evidence.reachable is False and 'Invalid API key' in evidence.error
    else:
        assert evidence.reachable is None


@pytest.mark.asyncio
async def test_elastic_email_redacts_long_keys_before_truncating_errors(monkeypatch):
    key = "synthetic-key-" + "k" * 2500
    for status in (200, 401):
        requests = intercept(monkeypatch, lambda r: httpx.Response(status, json={"Error": "Denied " + key}))
        result = await make_node({"operation": "list_lists"},
            {"credential_type": "elastic_email_api_key", "api_key": key}).execute({})
        assert result["status"] == "error" and "[redacted]" in result["error"]
        assert key[:100] not in str(result) and len(requests) == 1
