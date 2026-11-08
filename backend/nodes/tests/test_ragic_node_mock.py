"""Ragic factory/parser/dispatcher/evidence/picker fixtures on staging.

Only external DB/crypto/DNS/HTTP boundaries are synthetic. No real key or record
is read, and source fixtures are not live account/private-sheet proof.
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
FAMILY='ragic_api_key'
KEY='synthetic_ragic_key'
BLOB={'api_key':KEY,'server':'eu2.ragic.com','account':'fixture_account','folder':'fixtures','sheet_index':3}
SCOPE={'field_ids':[1000001,1000002],'confirm_safe_fields':True}
NOW=datetime(2026,10,7,tzinfo=timezone.utc)
RECORD='12345'
PRIVATE='unselected_private_fixture'


def record(identity=RECORD):return {str(identity):{'_ragicId':int(identity),'1000001':'Fixture workflow','1000002':7,'1000003':PRIVATE,'_index_title_':PRIVATE,'_subtable_123':{'secret':PRIVATE}}}


@pytest.fixture
def ensure_native_db_pool():yield


@pytest.fixture
async def native(monkeypatch):
    from nodes import ragic_node as provider
    from nodes.core import credential_connect,connection_evidence
    from repositories.credentials import credential_access_predicate
    from repositories.organization import OrgRepo
    from repositories.credential_approvals import CredentialApprovalRepo
    from utils import credentials,encryption,credential_approval,ssrf
    state=SimpleNamespace(blob=deepcopy(BLOB),allowed={USER},requests=[],constructors=[],reply=None,approval=None,sql=[],after_read=None,
        row={'id':CID,'owner_id':USER,'credential_type':FAMILY,'credential':b'synthetic-blob','token_version':7,'updated_at':NOW,'created_at':NOW,'revoked_at':None,'approval_revision':0,'name':'Fixture Ragic','metadata':{}})
    class Pool:
        @asynccontextmanager
        async def acquire(self):yield self
        async def fetchrow(self,sql,*args):
            state.sql.append((sql,args));assert credential_access_predicate() in sql
            return deepcopy(state.row) if args[0]==CID and args[1] in state.allowed else None
    state.pool,state.crypto=Pool(),MagicMock();state.crypto.decrypt_credential.side_effect=lambda _:deepcopy(state.blob)
    monkeypatch.setattr(encryption,'get_encryption',lambda:state.crypto);monkeypatch.setattr(credentials,'get_encryption',lambda:state.crypto)
    monkeypatch.setattr(OrgRepo,'get_primary_org_id',AsyncMock(return_value=None));monkeypatch.setattr(credentials,'get_workflow_owner_id',AsyncMock(return_value=OWNER))
    state.workflow_grant=AsyncMock(return_value=True);monkeypatch.setattr(credentials,'is_credential_authorized_for_workflow',state.workflow_grant)
    state.admit=AsyncMock(side_effect=lambda **_:state.approval);monkeypatch.setattr(CredentialApprovalRepo,'admit',state.admit)
    monkeypatch.setattr(credential_approval,'get_frontend_url',lambda:'https://fixture.invalid')
    monkeypatch.setattr(credential_connect,'_collect_evidence',connection_evidence.collect_evidence);credential_connect._class_index.cache_clear()
    state.dns=AsyncMock(return_value=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('8.8.8.8',443))]);monkeypatch.setattr(asyncio.get_running_loop(),'getaddrinfo',state.dns)
    def respond(request):
        state.requests.append(request)
        if getattr(state,'transport_error',None):raise state.transport_error
        status,payload,*headers=state.reply or (200,record())
        response=httpx.Response(status,content=payload if isinstance(payload,bytes) else json.dumps(payload).encode(),headers={'Content-Type':'application/json',**(headers[0] if headers else {})})
        if state.after_read:
            callback,state.after_read=state.after_read,None;callback()
        return response
    original=ssrf.guarded_async_client
    def client(**kwargs):state.constructors.append(kwargs);return original(**kwargs,transport=httpx.MockTransport(respond))
    monkeypatch.setattr(provider,'guarded_async_client',client)
    async def run(operation,args=None,*,saved=False,blob=None,workflow_id=None):
        from nodes.core.run_op import run_node_operation
        return await run_node_operation(node_type='automation-ragic',operation=operation,arguments={} if args is None else args,user_id=USER,pool=state.pool,organization_id=None,credential_id=CID if saved else None,credential_data=deepcopy(BLOB) if blob is None and not saved else blob,workflow_id=workflow_id)
    state.run=run;yield state;credential_connect._class_index.cache_clear()


async def test_factory_and_unknown_without_witness(native):
    from nodes.core.registry import NodeFactory
    from nodes.core.credential_connect import shape_credential
    from nodes.ragic_node import RagicNode
    shaped, errors, resolved = shape_credential(FAMILY, BLOB)
    assert shaped == BLOB and not errors and resolved[0] == 'automation-ragic'
    assert NodeFactory.is_registered('automation-ragic')
    schema = RagicNode.get_config_schema()
    assert set(schema['properties']['config']['discriminator']['mapping']) == {'check_connection', 'list_records', 'get_record', 'search_records'}
    assert {'field_ids', 'confirm_safe_fields'}.issubset(schema['$defs']['ListRecords']['required'])
    assert schema['$defs']['ListRecords']['properties']['limit']['maximum'] == 1000
    result = await native.run('check_connection')
    assert result['status'] == 'error'
    assert native.requests == [] and native.constructors == []


async def test_exact_raw_header_and_paired_witness(native):
    blob = {**BLOB, 'witness_record_id': RECORD, 'witness_field_id': 1000001}
    result = await native.run('check_connection', blob=blob)
    assert result['status'] == 'success' and result['data']['items'] == []
    assert result['data']['identity_verified'] is False
    assert result['data']['key_validity'] == 'unknown' and result['data']['private_sheet_access'] == 'unknown'
    request = native.requests[-1]
    assert request.url.host == 'eu2.ragic.com' and request.url.path == '/fixture_account/fixtures/3/' + RECORD
    assert request.headers['Authorization'] == 'Basic ' + KEY
    assert request.url.params['version'] == '2025-01-01'
    assert request.url.params['naming'] == 'EID' and request.url.params['subtables'] == '0'
    assert request.url.params.get_list('fetchDomainIds') == ['1000001']
    assert KEY not in str(request.url) and not request.content
    native.reply = (200, record('8'))
    assert (await native.run('check_connection', blob=blob))['status'] == 'error'


@pytest.mark.parametrize('tag',[None,'',7,[],{},'slack_oauth',' ragic_api_key '])
def test_supplied_foreign_family_before_base_parse(native,tag):
    from nodes.core.registry import NodeFactory
    from nodes.core.base import ConfigValidationError
    from nodes.ragic_node import RagicNode
    raw={'config':{'operation':'check_connection'},'credentials':{**BLOB,'credential_type':tag}}
    assert RagicNode.validate_config(raw)['valid'] is False
    with pytest.raises(ConfigValidationError):NodeFactory.create_node('fixture','automation-ragic',raw,user_id=USER)
    assert native.requests==[]


@pytest.mark.parametrize('change',[{'server':'evil.ragic.com'},{'server':'https://eu2.ragic.com'},{'server':'eu2.ragic.com.evil.test'},{'account':'../other'},{'folder':'path/nested'},{'folder':'fixtures?apiKey=x'},{'sheet_index':True},{'api_key':'Basic '+KEY},{'api_key':'Bearer '+KEY},{'api_key':123},{'witness_record_id':RECORD},{'witness_field_id':1000001}])
async def test_wrong_host_auth_scope_or_unpaired_witness_refused_before_provider(native,change):
    from nodes.core.base import ConfigValidationError
    with pytest.raises(ConfigValidationError):await native.run('list_records',SCOPE,blob={**BLOB,**change})
    assert native.requests==[]


async def test_canonical_positive_owner_fallback_and_removed_grant(native):
    native.row['owner_id']=OWNER;native.allowed={OWNER}
    assert (await native.run('list_records',SCOPE,saved=True,workflow_id=WORKFLOW))['status']=='success'
    assert native.workflow_grant.await_count>0
    native.requests.clear();native.workflow_grant.return_value=False
    with pytest.raises(ValueError):await native.run('list_records',SCOPE,saved=True,workflow_id=WORKFLOW)
    assert native.requests==[]


async def test_real_get_projection_drops_unselected_private_urls_images_and_nested_fields(native):
    values=record();values[RECORD].update({'1000001':'https://private.ragic.com/sims/file.jsp?sid=secret','1000002':{'nested':PRIVATE}});native.reply=(200,values)
    result=await native.run('get_record',{**SCOPE,'record_id':RECORD})
    assert result['status']=='success' and result['data']['fields']=={'1000001':None,'1000002':None}
    assert result['data']['redacted_field_ids']==[1000001,1000002] and PRIVATE not in json.dumps(result) and 'sid=' not in json.dumps(result)
    assert native.requests[-1].url.params.get_list('fetchDomainIds')==['1000001','1000002']
    assert all(x['trust_env'] is False and x['follow_redirects'] is False for x in native.constructors)
    native.reply=(200,{**record(),**record('3')})
    assert (await native.run('get_record',{**SCOPE,'record_id':RECORD}))['status']=='error'


@pytest.mark.parametrize('value',['data:image/png;base64,private','<img src="private">','file:///private','//private.example.test/capability',KEY,[{'nested':PRIVATE}],float('inf')])
async def test_selected_unsafe_cells_redacted_without_capability_or_secret_output(native,value):
    payload=record();payload[RECORD]['1000001']=value;native.reply=(200,payload)
    result=await native.run('get_record',{**SCOPE,'record_id':RECORD})
    assert result['status']=='success' and result['data']['fields']['1000001'] is None
    assert result['data']['redacted_field_ids']==[1000001] and KEY not in json.dumps(result) and PRIVATE not in json.dumps(result)


@pytest.mark.parametrize('operation,args',[('list_records',{}),('list_records',{'field_ids':[],'confirm_safe_fields':True}),('list_records',{'field_ids':['1000001'],'confirm_safe_fields':True}),('list_records',{'field_ids':[1000001],'confirm_safe_fields':1}),('list_records',{**SCOPE,'offset':3}),('list_records',{**SCOPE,'limit':1001}),('list_records',{**SCOPE,'limit':True}),('get_record',{**SCOPE,'record_id':'../other'}),('search_records',SCOPE),('search_records',{**SCOPE,'conditions':[{'field_id':1000003,'operator':'eq','value':'x'}]}),('search_records',{**SCOPE,'sql':'SELECT *'}),('delete_record',{}),('check_task_progress',{})])
async def test_missing_projection_or_escape_mutation_refused_before_http(native,operation,args):
    from nodes.core.base import ConfigValidationError
    with pytest.raises(ConfigValidationError):await native.run(operation,args)
    assert native.requests==[]


async def test_exact_fts_repeated_where_and_double_encoding_of_literal_comma_percent(native):
    args={**SCOPE,'full_text':'Fixture','conditions':[{'field_id':1000001,'operator':'eq','value':'A,B%20'},{'field_id':1000001,'operator':'like','value':''}]}
    assert (await native.run('search_records',args))['status']=='success'
    query=native.requests[-1].url.params
    assert query['fts']=='Fixture' and query.get_list('where')==['1000001,eq,A%2CB%2520','1000001,like,']
    assert '%252C' in str(native.requests[-1].url) and '%252520' in str(native.requests[-1].url)
    assert 'callback' not in query and 'format' not in query


async def test_bound_offset_continuation_is_unknown_total_and_capped(native):
    args={**SCOPE,'limit':1,'max_pages':2}
    first=await native.run('list_records',args,saved=True);token=first['data']['next_page_token'];assert token
    assert first['data']['has_more'] is None and first['data']['may_have_more'] is True and first['data']['snapshot_consistency']=='unverified'
    native.requests.clear()
    for changes in [{'limit':2},{'field_ids':[1000001]},{'max_pages':3}]:assert (await native.run('list_records',{**args,**changes,'page_token':token},saved=True))['status']=='error'
    native.blob['server']='na3.ragic.com'
    assert (await native.run('list_records',{**args,'page_token':token},saved=True))['status']=='error' and native.requests==[]
    native.blob=deepcopy(BLOB);cursor=json.loads(base64.urlsafe_b64decode(token));cursor['offset']=999
    forged=base64.urlsafe_b64encode(json.dumps(cursor).encode()).decode()
    assert (await native.run('list_records',{**args,'page_token':forged},saved=True))['status']=='error' and native.requests==[]
    native.reply=(200,record('12346'));second=await native.run('list_records',{**args,'page_token':token},saved=True)
    assert native.requests[-1].url.params['offset']=='1' and second['data']['truncated'] is True and second['data']['next_page_token'] is None


async def test_repeated_page_and_empty_page_do_not_guess_provider_total(native):
    args={**SCOPE,'limit':1};first=await native.run('list_records',args);token=first['data']['next_page_token']
    assert (await native.run('list_records',{**args,'page_token':token}))['status']=='error'
    native.reply=(200,{})
    result=await native.run('list_records',SCOPE)
    assert result['status']=='success' and result['data']['items']==[] and result['data']['has_more'] is None and result['data']['stop_reason']=='short_page'


@pytest.mark.parametrize('payload',[{'status':'ERROR','code':303,'msg':KEY},{'taskId':'unsafe'},{RECORD:{'_ragicId':True}},{RECORD:{'_ragicId':4}},{'01':{'_ragicId':1}},[],{'record':{}}])
async def test_malformed_keyed_records_or_business_errors_sanitized(native,payload):
    native.reply=(200,payload);result=await native.run('list_records',SCOPE)
    assert result['status']=='error' and KEY not in json.dumps(result) and len(native.requests)==1


@pytest.mark.parametrize('status',[201,202,204,302,400,401,402,403,404,429,500,502,503,504])
async def test_exact_http200_error_status_contract_no_retry_or_revoke(native,status):
    native.reply=(status,{'msg':KEY,'status':'ERROR','code':106})
    result=await native.run('list_records',SCOPE)
    assert result['status']=='error' and result['status_code']==status and KEY not in json.dumps(result)
    assert len(native.requests)==1 and native.row['revoked_at'] is None


async def test_actual_picker_requires_confirmed_projection_and_admission(native):
    from nodes.core.run_op import run_node_lookup
    call=dict(node_type='automation-ragic',field_name='record_id',user_id=USER,pool=native.pool,organization_id=None,credential_id=CID)
    result=await run_node_lookup(**call,context=SCOPE)
    assert result['options']==[{'label':RECORD,'value':RECORD}]
    native.requests.clear()
    with pytest.raises(ValueError):await run_node_lookup(**call,context={'server':'evil.example.test','field_ids':KEY})
    assert native.requests==[]
    for status in ('pending_approval','rejected'):
        native.approval={'id':CID,'status':'pending' if status=='pending_approval' else 'rejected'}
        assert (await native.run('list_records',SCOPE,saved=True))['status']==status
        assert (await run_node_lookup(**call,context=SCOPE))['status']==status
    assert native.requests==[]


@pytest.mark.parametrize('payload,headers',[(b'not JSON',{'Content-Type':'application/json'}),(b'{}',{'Content-Type':'text/html'}),(b'x'*2_000_001,{'Content-Type':'application/json'})])
async def test_unreadable_or_oversized_transport_is_not_record_success(native,payload,headers):
    native.reply=(200,payload,headers)
    result=await native.run('list_records',SCOPE)
    assert result['status']=='error' and len(native.requests)==1 and KEY not in json.dumps(result)


async def test_transport_error_no_raw_secret_or_retry(native):
    native.transport_error=httpx.ReadError(KEY+' '+PRIVATE)
    result=await native.run('list_records',SCOPE)
    assert result['status']=='error' and KEY not in json.dumps(result) and PRIVATE not in json.dumps(result)
    assert len(native.requests)==1 and native.row['revoked_at'] is None


async def test_real_picker_refuses_possibly_incomplete_full_page(native):
    from nodes.core.run_op import run_node_lookup
    native.reply=(200,{str(i):record(str(i))[str(i)] for i in range(1000)})
    with pytest.raises(ValueError):await run_node_lookup(node_type='automation-ragic',field_name='record_id',user_id=USER,pool=native.pool,organization_id=None,credential_id=CID,context=SCOPE)
    assert len(native.requests)==1 and native.requests[0].url.params['limit']=='1000'
