"""Actual native company factory, parser, connect evidence, dispatcher and HTTP.

Only external database, crypto and transport boundaries are synthetic; fixtures
never query a provider, open an account or consume a company credit.
"""
import asyncio
import base64
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime,timezone
import json
import socket
from types import SimpleNamespace
from unittest.mock import AsyncMock,MagicMock

import httpx
import pytest

USER='00000000-0000-4000-8000-000000000001'
OWNER='00000000-0000-4000-8000-000000000002'
CID='00000000-0000-4000-8000-000000000003'
WORKFLOW='00000000-0000-4000-8000-000000000004'
FAMILY='people_data_labs_api_key'
KEY='synthetic_pdl_key'
BLOB={'api_key':KEY}
NOW=datetime(2026,10,7,tzinfo=timezone.utc)
COMPANY='company_fixture'
PRIVATE='private_contact_not_output'
QUERY={'query':{'term':{'industry':'computer software'}}}
ARGS={'confirm_credit_use':True}


def profile():return {'id':COMPANY,'name':'fixture company','website':'fixture.example.test','industry':'computer software','size':'11-50','employee_count':20,'linkedin_slug':'fixture-company','founded':2020,'location':{'country':'united states','street_address':PRIVATE,'geo':PRIVATE},'tags':['software'],'email':PRIVATE,'phone':PRIVATE,'employee_names':[PRIVATE],'ip_address':PRIVATE}


@pytest.fixture
def ensure_native_db_pool():yield


@pytest.fixture
async def native(monkeypatch):
    from nodes import people_data_labs_node as provider
    from nodes.core import credential_connect, connection_evidence, run_op
    from repositories.credential_approvals import CredentialApprovalRepo
    from utils import credential_approval, ssrf
    state = SimpleNamespace(blob={**BLOB, 'credential_type': FAMILY}, requests=[], constructors=[],
        replies={}, approval=None, pool=MagicMock())
    async def resolve(*args, **kwargs):
        return deepcopy(state.blob)
    state.resolve = AsyncMock(side_effect=resolve)
    monkeypatch.setattr(provider, 'resolve_credential_with_owner_fallback', state.resolve)
    monkeypatch.setattr(run_op, 'resolve_credential_with_owner_fallback', state.resolve)
    monkeypatch.setattr(CredentialApprovalRepo, 'admit', AsyncMock(side_effect=lambda **_: state.approval))
    monkeypatch.setattr(credential_approval, 'get_frontend_url', lambda: 'https://fixture.invalid')
    monkeypatch.setattr(credential_connect, '_collect_evidence', connection_evidence.collect_evidence)
    credential_connect._class_index.cache_clear()
    monkeypatch.setattr(asyncio.get_running_loop(), 'getaddrinfo', AsyncMock(return_value=[
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443))]))
    def respond(request):
        state.requests.append(request)
        route = request.url.path.removeprefix('/v5/')
        reply = state.replies.get(route)
        if reply is None:
            if route == 'company/enrich':
                payload = {'status': 200, **profile(), 'likelihood': 8, 'matched': ['website']}
            elif route == 'company/clean':
                payload = {'status': 200, **profile(), 'score': 3.0, 'fuzzy_match': False}
            else:
                payload = {'status': 200, 'data': [profile()], 'total': 1, 'scroll_token': None}
            reply = (200, payload)
        status, payload, *headers = reply
        return httpx.Response(status, content=payload if isinstance(payload, bytes) else json.dumps(payload).encode(),
            headers={'Content-Type': 'application/json', **(headers[0] if headers else {})})
    original = ssrf.guarded_async_client
    def client(**kwargs):
        state.constructors.append(kwargs)
        return original(**kwargs, transport=httpx.MockTransport(respond))
    monkeypatch.setattr(provider, 'guarded_async_client', client)
    async def run(operation, args=None, *, saved=False, blob=None, workflow_id=None):
        return await run_op.run_node_operation(node_type='automation-people-data-labs', operation=operation,
            arguments=args or {}, user_id=USER, pool=state.pool, organization_id=None,
            credential_id=CID if saved else None, credential_data=deepcopy(BLOB) if blob is None and not saved else blob,
            workflow_id=workflow_id)
    state.run = run
    yield state
    credential_connect._class_index.cache_clear()


async def test_actual_factory_schema_and_free_connection_probe(native):
    from nodes.core.registry import NodeFactory
    from nodes.people_data_labs_node import PeopleDataLabsNode
    assert NodeFactory.is_registered('automation-people-data-labs')
    schema = PeopleDataLabsNode.get_config_schema()
    assert set(schema['properties']['config']['discriminator']['mapping']) == {'check_connection', 'enrich_company', 'search_companies'}
    assert 'confirm_credit_use' in schema['$defs']['EnrichCompany']['required']
    result = await native.run('check_connection', saved=True, workflow_id=WORKFLOW)
    assert result['status'] == 'success'
    assert 'remain unverified' in result['data']['proof']
    assert set(result['data']) == {'proof'}
    request = native.requests[0]
    assert request.url.path == '/v5/company/clean' and request.method == 'GET'
    assert dict(request.url.params) == {'website': 'peopledatalabs.com'}
    assert request.headers['X-Api-Key'] == KEY
    native.resolve.assert_awaited_with(CID, USER, native.pool, org_id=None, workflow_id=WORKFLOW)


@pytest.mark.parametrize('tag', [None, '', 7, [], {}, 'slack_oauth', ' people_data_labs_api_key '])
def test_actual_native_foreign_family_before_base_reconciliation(native, tag):
    from nodes.core.registry import NodeFactory
    from nodes.core.base import ConfigValidationError
    from nodes.people_data_labs_node import PeopleDataLabsNode
    raw = {'config': {'operation': 'check_connection'}, 'credentials': {**BLOB, 'credential_type': tag}}
    assert PeopleDataLabsNode.validate_config(raw)['valid'] is False
    with pytest.raises(ConfigValidationError):
        NodeFactory.create_node('fixture', 'automation-people-data-labs', raw, user_id=USER)
    assert native.requests == []


@pytest.mark.parametrize('data', [None, {**BLOB, 'credential_type': None}, {**BLOB, 'credential_type': 'slack_oauth'}])
async def test_unavailable_or_foreign_saved_key_never_reaches_provider(native, data):
    from nodes.people_data_labs_node import freshen
    native.blob = data
    with pytest.raises(ValueError):
        await freshen(BLOB, user_id=USER, credential_id=CID, pool=native.pool)
    assert native.requests == []


async def test_saved_execution_reloads_reconnected_key(native):
    native.blob['api_key'] = 'replacement_key'
    result = await native.run('enrich_company', {**ARGS, 'website': 'fixture.example.test'}, saved=True)
    assert result['status'] == 'success'
    assert native.requests[0].headers['X-Api-Key'] == 'replacement_key'
    assert native.resolve.await_count == 2  # standalone resolution plus execute reload


async def test_actual_enrich_get_key_header_top_level_projection_and_id_precedence(native):
    result=await native.run('enrich_company',{**ARGS,'website':'fixture.example.test'})
    assert result['status']=='success' and result['data']['likelihood']==8 and result['data']['matched_inputs']==['website']
    req=native.requests[-1];assert req.method=='GET' and req.url.path=='/v5/company/enrich' and req.headers['X-Api-Key']==KEY
    assert req.url.host=='api.peopledatalabs.com' and KEY not in str(req.url) and not req.content
    assert req.url.params['min_likelihood']=='6' and req.url.params['include_if_matched']=='true' and 'data_include' in req.url.params
    assert PRIVATE not in json.dumps(result) and 'street_address' not in json.dumps(result)
    native.replies['company/enrich']=(200,{'status':200,**profile(),'likelihood':10,'matched':['pdl_id']})
    result=await native.run('enrich_company',{**ARGS,'pdl_id':COMPANY,'website':'ignored.example.test','name':'Ignored'})
    assert result['status']=='success' and result['data']['id_precedence_applied'] is True
    assert 'website' not in native.requests[-1].url.params and 'name' not in native.requests[-1].url.params
    native.replies['company/enrich']=(200,{'status':200,**profile(),'id':'different','likelihood':10})
    assert (await native.run('enrich_company',{**ARGS,'pdl_id':COMPANY}))['status']=='error'


@pytest.mark.parametrize('changes',[{}, {'website':'fixture.example.test','confirm_credit_use':False},{'website':'fixture.example.test','confirm_credit_use':1},{'website':'fixture.example.test','min_likelihood':True},{'website':'fixture.example.test','api_key':KEY},{'person_id':'person'}])
async def test_invalid_credit_or_match_inputs_before_provider(native,changes):
    from nodes.core.base import ConfigValidationError
    with pytest.raises(ConfigValidationError):await native.run('enrich_company',changes)
    assert native.requests==[]


@pytest.mark.parametrize('payload',[{'status':200,'data':[profile()],'likelihood':8},{'status':200,**profile(),'likelihood':True},{'status':200,**profile(),'likelihood':5},{'status':200,**profile(),'likelihood':8,'matched':['email']},{'status':401,**profile(),'likelihood':8},{'status':200,**profile(),'name':KEY,'likelihood':8}])
async def test_enrichment_malformed_or_wrong_envelope_safe(native,payload):
    native.replies['company/enrich']=(200,payload)
    result=await native.run('enrich_company',{**ARGS,'website':'fixture.example.test'})
    assert result['status']=='error' and KEY not in json.dumps(result)


@pytest.mark.parametrize('operation,args',[('enrich_company',{'website':'fixture.example.test'}),('search_companies',{'query':QUERY})])
async def test_documented_404_not_found_is_not_key_rejection(native,operation,args):
    route='company/enrich' if operation=='enrich_company' else 'company/search'
    native.replies[route]=(404,{'status':404,'error':{'type':'not_found','message':KEY}})
    result=await native.run(operation,{**ARGS,**args});assert result['status']=='success' and result['data']['request_status']==404
    assert KEY not in json.dumps(result)


async def test_actual_search_query_or_sql_wire_and_typed_supported_clauses(native):
    result=await native.run('search_companies',{**ARGS,'query':QUERY,'size':2})
    assert result['status']=='success' and result['data']['items'][0]['id']==COMPANY
    req=native.requests[-1];assert req.method=='GET' and req.url.path=='/v5/company/search' and req.headers['X-Api-Key']==KEY
    assert json.loads(req.url.params['query'])==QUERY and req.url.params['size']=='2' and 'sql' not in req.url.params and not req.content
    sql="SELECT * FROM company WHERE name='people data labs'"
    assert (await native.run('search_companies',{**ARGS,'sql':sql}))['status']=='success'
    assert native.requests[-1].url.params['sql']==sql and 'query' not in native.requests[-1].url.params
    for clause in [{'terms':{'tags':['software']*100}},{'bool':{'must':[{'term':{'industry':'software'}}],'must_not':[{'exists':{'field':'ticker'}}]}},{'range':{'employee_count':{'gte':10,'lt':100}}},{'match_all':{}}]:
        assert (await native.run('search_companies',{**ARGS,'query':{'query':clause}}))['status']=='success'
    assert all(v['trust_env'] is False and v['follow_redirects'] is False for v in native.constructors)
    assert PRIVATE not in json.dumps(result)


@pytest.mark.parametrize('changes',[{'query':QUERY,'sql':"SELECT * FROM company WHERE name='a'"},{'query':{'query':{'terms':{'tags':['a']*101}}}},{'query':{'query':{'term':{'email':'private'}}}},{'query':{'query':{'term':{'industry':'a'}},'aggs':{}}},{'query':{'query':{'match':{'industry':{'query':'a','boost':2}}}}},{'sql':"SELECT * FROM person WHERE name='a'"},{'sql':"SELECT name FROM company WHERE name='a' LIMIT 1"},{'sql':"SELECT * FROM company WHERE name='a';"},{'query':QUERY,'from':100},{'query':QUERY,'size':101},{'query':QUERY,'size':True},{'query':QUERY,'scroll_token':'raw'}])
async def test_untyped_query_person_sql_and_legacy_controls_refused_before_probe(native,changes):
    from nodes.core.base import ConfigValidationError
    with pytest.raises(ConfigValidationError):await native.run('search_companies',{**ARGS,**changes})
    assert native.requests==[]


async def test_saved_same_query_scroll_binding_cap_unknown_and_explicit_end(native):
    native.replies['company/search']=(200,{'status':200,'data':[profile()],'total':100,'scroll_token':'opaque$cursor1'})
    args={**ARGS,'query':QUERY,'size':1,'max_pages':2}
    first=await native.run('search_companies',args,saved=True);token=first['data']['next_page_token'];assert token
    native.requests.clear()
    cursor=json.loads(base64.urlsafe_b64decode(token));cursor['scroll']='forged$cursor'
    forged=base64.urlsafe_b64encode(json.dumps(cursor).encode()).decode()
    assert (await native.run('search_companies',{**args,'page_token':forged},saved=True))['status']=='error'
    for changed in [{'size':2},{'max_pages':3},{'fields':['name']},{'query':{'query':{'term':{'industry':'other'}}}}]:
        assert (await native.run('search_companies',{**args,**changed,'page_token':token},saved=True))['status']=='error'
    assert native.requests==[]
    native.blob['api_key']='replacement_key'
    assert (await native.run('search_companies',{**args,'page_token':token},saved=True))['status']=='error' and native.requests==[]
    native.blob={**BLOB,'credential_type':FAMILY};native.replies['company/search']=(200,{'status':200,'data':[profile()],'total':100,'scroll_token':'opaque$cursor2'})
    second=await native.run('search_companies',{**args,'page_token':token},saved=True)
    assert native.requests[-1].url.params['scroll_token']=='opaque$cursor1' and json.loads(native.requests[-1].url.params['query'])==QUERY
    assert second['data']['truncated'] is True and second['data']['stop_reason']=='local_page_cap' and second['data']['next_page_token'] is None
    native.replies['company/search']=(200,{'status':200,'data':[],'total':0})
    result=await native.run('search_companies',args);assert result['data']['continuation_known'] is False
    native.replies['company/search']=(404,{'status':404,'error':{'type':'not_found'}})
    result=await native.run('search_companies',{**args,'page_token':token},saved=True);assert result['data']['pagination_complete'] is True


@pytest.mark.parametrize('status,kind',[(201,'provider_failure'),(202,'provider_failure'),(204,'provider_failure'),(302,'provider_failure'),(400,'invalid_request'),(401,'authentication'),(402,'credits_exhausted'),(405,'method'),(429,'rate_limit'),(503,'provider_failure')])
async def test_actual_status_errors_no_raw_body_or_retry(native,status,kind):
    native.replies['company/search']=(status,{'status':status,'error':{'type':KEY,'message':PRIVATE}})
    result=await native.run('search_companies',{**ARGS,'query':QUERY})
    assert result['status']=='error' and result['status_code']==status and result['error_kind']==kind
    assert len(native.requests)==1 and KEY not in json.dumps(result) and PRIVATE not in json.dumps(result)


@pytest.mark.parametrize('payload',[{'status':200,'data':[profile(),profile()],'total':2,'scroll_token':None},{'status':200,'data':[profile()],'total':True},{'status':200,'data':{},'total':1},{'status':200,'data':[],'total':100,'scroll_token':'nonprogress'},{'status':200,'data':[profile()],'total':1,'scroll_token':KEY}])
async def test_malformed_search_collection_and_protected_scroll_are_not_valid_pages(native,payload):
    native.replies['company/search']=(200,payload)
    result=await native.run('search_companies',{**ARGS,'query':QUERY})
    assert result['status']=='error' and KEY not in json.dumps(result)


@pytest.mark.parametrize('approval',['pending','rejected'])
async def test_actual_admission_stays_nonexecuted_before_paid_query(native,approval):
    native.approval={'id':CID,'status':approval,'new_request':False}
    result=await native.run('search_companies',{**ARGS,'query':QUERY},saved=True)
    assert result['executed'] is False and result['status']==('pending_approval' if approval=='pending' else 'rejected')
    assert native.requests==[] and native.constructors==[]
