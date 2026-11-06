"""Actual Qonversion factory, parser, evidence, dispatcher, picker and transport fixtures.

Only external database, cryptography and HTTP/DNS boundaries are synthetic.
No fixture calls a provider, authenticates an account or changes an entitlement.
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
CONFIG_ID='00000000-0000-4000-8000-000000000005'
FAMILY='qonversion_secret_key'
KEY='sk_synthetic_qonversion_secret'
BLOB={'secret_key':KEY}
NOW=datetime(2026,10,7,tzinfo=timezone.utc)
STAMP='2026-10-07T00:00:00Z'
PRODUCT='premium_monthly'
PRIVATE='private_profile_not_output'


def product(identity=PRODUCT):return {'object':'product','id':identity,'url':'/v4/products/'+identity,'type':'subscription','duration':'P1M','apple_product_id':'example.app.monthly','created_at':STAMP,'updated_at':STAMP,'client_secret':PRIVATE}
def definition(identity='premium'):return {'object':'entitlement','id':identity,'url':'/v4/entitlements/'+identity,'description':'Premium metadata','product_ids':[PRODUCT],'created_at':STAMP,'updated_at':STAMP,'customer_email':PRIVATE}
def configuration(identity=CONFIG_ID):return {'object':'remote_configuration','id':identity,'url':'/v4/remote-configurations/'+identity,'name':'Fixture configuration','status':'draft','priority':None,'created_at':STAMP,'updated_at':STAMP,'segment_percent':100,'segmentation_conditions':[{'value':PRIVATE}],'payload':{'private':PRIVATE}}
def profile(identity='QON_fixture'):return {'object':'user','id':identity,'url':'/v4/users/'+identity,'environment':'sandbox','created_at':STAMP,'identity_id':PRIVATE,'email':PRIVATE,'properties':{'private':PRIVATE}}


@pytest.fixture
def ensure_native_db_pool():yield


@pytest.fixture
async def native(monkeypatch):
    from nodes import qonversion_node as provider
    from nodes.core import credential_connect,connection_evidence
    from repositories.credentials import credential_access_predicate
    from repositories.organization import OrgRepo
    from repositories.credential_approvals import CredentialApprovalRepo
    from utils import credentials,encryption,credential_approval,ssrf
    state=SimpleNamespace(blob=deepcopy(BLOB),allowed={USER},requests=[],constructors=[],replies={},approval=None,sql=[],after_read=None,
        row={'id':CID,'owner_id':USER,'credential_type':FAMILY,'credential':b'synthetic-blob','token_version':7,'updated_at':NOW,'created_at':NOW,'revoked_at':None,'approval_revision':0,'name':'Fixture Qonversion','metadata':{}})
    class Pool:
        @asynccontextmanager
        async def acquire(self):yield self
        async def fetchrow(self,sql,*args):
            state.sql.append((sql,args));assert credential_access_predicate() in sql
            return deepcopy(state.row) if args[0]==CID and args[1] in state.allowed else None
    state.pool,state.crypto=Pool(),MagicMock()
    state.crypto.decrypt_credential.side_effect=lambda _:deepcopy(state.blob)
    monkeypatch.setattr(encryption,'get_encryption',lambda:state.crypto);monkeypatch.setattr(credentials,'get_encryption',lambda:state.crypto)
    monkeypatch.setattr(OrgRepo,'get_primary_org_id',AsyncMock(return_value=None))
    monkeypatch.setattr(credentials,'get_workflow_owner_id',AsyncMock(return_value=OWNER))
    state.workflow_grant=AsyncMock(return_value=True);monkeypatch.setattr(credentials,'is_credential_authorized_for_workflow',state.workflow_grant)
    state.admit=AsyncMock(side_effect=lambda **_:state.approval);monkeypatch.setattr(CredentialApprovalRepo,'admit',state.admit)
    monkeypatch.setattr(credential_approval,'get_frontend_url',lambda:'https://fixture.invalid')
    monkeypatch.setattr(credential_connect,'_collect_evidence',connection_evidence.collect_evidence);credential_connect._class_index.cache_clear()
    state.dns=AsyncMock(return_value=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('8.8.8.8',443))]);monkeypatch.setattr(asyncio.get_running_loop(),'getaddrinfo',state.dns)
    def respond(request):
        state.requests.append(request)
        if getattr(state,'transport_error',None):raise state.transport_error
        route=request.url.path.removeprefix('/v4/');reply=state.replies.get(route)
        if reply is None:
            if route in ('products','entitlements','remote-configurations'):
                resource={'products':product,'entitlements':definition,'remote-configurations':configuration}[route]()
                reply=(200,{'object':'list','url':'/v4/'+route,'data':[resource],'has_more':False})
            else:
                kind,identity=route.split('/',1);reply=(200,{'products':product,'entitlements':definition,'remote-configurations':configuration,'users':profile}[kind](identity))
        status,payload,*headers=reply
        response=httpx.Response(status,content=payload if isinstance(payload,bytes) else json.dumps(payload).encode(),headers={'Content-Type':'application/json',**(headers[0] if headers else {})})
        if state.after_read:
            callback,state.after_read=state.after_read,None;callback()
        return response
    original=ssrf.guarded_async_client
    def client(**kwargs):state.constructors.append(kwargs);return original(**kwargs,transport=httpx.MockTransport(respond))
    monkeypatch.setattr(provider,'guarded_async_client',client)
    async def run(operation,args=None,*,saved=False,blob=None,workflow_id=None):
        from nodes.core.run_op import run_node_operation
        return await run_node_operation(node_type='automation-qonversion',operation=operation,arguments=args or {},user_id=USER,pool=state.pool,organization_id=None,credential_id=CID if saved else None,credential_data=deepcopy(BLOB) if blob is None and not saved else blob,workflow_id=workflow_id)
    state.run=run;yield state;credential_connect._class_index.cache_clear()


async def test_real_factory_shape_schema_and_unknown_connection_without_witness(native):
    from nodes.core.registry import NodeFactory
    from nodes.core.credential_connect import shape_credential
    from nodes.qonversion_node import QonversionNode,QonversionSecretKeyCredential
    shaped,errors,resolved=shape_credential(FAMILY,BLOB)
    assert shaped==BLOB and not errors and resolved[0]=='automation-qonversion'
    assert QonversionSecretKeyCredential.model_validate(shaped).credential_type==FAMILY
    assert NodeFactory.is_registered('automation-qonversion')
    schema=QonversionNode.get_config_schema()
    assert set(schema['properties']['config']['discriminator']['mapping'])=={'check_connection','list_products','get_product','list_entitlement_definitions','get_entitlement_definition','list_remote_configurations','get_remote_configuration','get_user'}
    assert 'confirm_user_metadata' in schema['$defs']['GetUser']['required']
    assert 'expected_environment' in schema['$defs']['GetUser']['required']
    result=await native.run('check_connection',saved=True)
    assert result['executed'] is False and result['verification']['reachable'] is None
    assert native.requests==[] and native.constructors==[];native.dns.assert_not_awaited()


async def test_real_supplied_product_witness_is_reachability_not_principal(native):
    blob={**BLOB,'witness_product_id':PRODUCT}
    result=await native.run('check_connection',blob=blob)
    assert result['status']=='success' and result['data']['identity_verified'] is False
    assert result['verification']=={'reachable':True,'proves':'reachability','account_label':None}
    request=native.requests[-1];assert request.url.path=='/v4/products/'+PRODUCT and request.headers['Authorization']=='Bearer '+KEY
    assert not request.url.query and not request.content and KEY not in str(request.url)
    native.replies['products/'+PRODUCT]=(200,product('another_product'))
    assert (await native.run('check_connection',blob=blob))['status']=='error'


@pytest.mark.parametrize('tag',[None,'',7,[],{},'slack_oauth',' qonversion_secret_key '])
def test_raw_foreign_native_family_before_inherited_reconciliation(native,tag):
    from nodes.core.registry import NodeFactory
    from nodes.core.base import ConfigValidationError
    from nodes.qonversion_node import QonversionNode
    raw={'config':{'operation':'check_connection'},'credentials':{**BLOB,'credential_type':tag}}
    assert QonversionNode.validate_config(raw)['valid'] is False
    with pytest.raises(ConfigValidationError):NodeFactory.create_node('fixture','automation-qonversion',raw,user_id=USER)
    assert native.requests==[]


@pytest.mark.parametrize('key',['public_sdk_key','test_sk_unsupported','Bearer sk_prefixed','sk_','https://secret.example.test','sk_internal space',None,123])
async def test_sdk_legacy_and_nonstring_keys_refused_before_provider(native,key):
    from nodes.core.base import ConfigValidationError
    with pytest.raises(ConfigValidationError):await native.run('list_products',blob={'secret_key':key})
    assert native.requests==[]


@pytest.mark.parametrize('change',[{'credential_type':None},{'credential_type':''},{'credential_type':7},{'credential_type':'slack_oauth'},{'token_version':True},{'token_version':'7'},{'token_version':0},{'owner_id':None},{'revoked_at':NOW}])
async def test_actual_authority_raw_headers_before_its_decrypt(native,change):
    from nodes.qonversion_node import freshen
    native.row.update(change)
    with pytest.raises(ValueError):await freshen(BLOB,user_id=USER,credential_id=CID,pool=native.pool)
    native.crypto.decrypt_credential.assert_not_called();assert native.requests==[]


async def test_actual_dispatch_null_row_blob_does_not_reach_provider(native):
    native.row['credential_type']=None;native.blob['credential_type']=FAMILY
    result=await native.run('list_products',saved=True)
    assert result['status']=='error' and native.requests==[]
    # Unchanged inherited generic getter's earlier decrypt is not qualified here.


async def test_current_key_witness_version_and_post_response_authority(native):
    from nodes.qonversion_node import freshen,request
    current=await freshen(BLOB,user_id=USER,credential_id=CID,pool=native.pool)
    native.blob['witness_product_id']=PRODUCT
    with pytest.raises(ValueError):await request(current,'products')
    assert native.requests==[]
    native.blob=deepcopy(BLOB);native.after_read=lambda:native.row.update(token_version=8)
    result=await native.run('get_product',{'product_id':PRODUCT},saved=True)
    assert result['status']=='error' and len(native.requests)==1


async def test_actual_canonical_workflow_owner_fallback_and_revocation(native):
    native.row['owner_id']=OWNER;native.allowed={OWNER}
    result=await native.run('list_products',saved=True,workflow_id=WORKFLOW)
    assert result['status']=='success' and native.workflow_grant.await_count>0
    native.requests.clear();native.workflow_grant.return_value=False
    with pytest.raises(ValueError):await native.run('list_products',saved=True,workflow_id=WORKFLOW)
    assert native.requests==[]


@pytest.mark.parametrize('operation,args',[('get_product',{'product_id':PRODUCT}),('get_entitlement_definition',{'entitlement_id':'premium'}),('get_remote_configuration',{'configuration_id':CONFIG_ID}),('get_user',{'user_id':'QON_fixture','expected_environment':'sandbox','confirm_user_metadata':True})])
async def test_actual_closed_get_paths_and_safe_projection(native,operation,args):
    result=await native.run(operation,args)
    assert result['status']=='success' and result['data']['id']==next(value for key,value in args.items() if key.endswith('_id'))
    request=native.requests[-1];assert request.method=='GET' and request.url.host=='api.qonversion.io' and request.headers['Authorization']=='Bearer '+KEY
    assert not request.url.query and not request.content and KEY not in str(request.url)
    assert PRIVATE not in json.dumps(result) and 'payload' not in result['data'] and 'identity_id' not in result['data']
    assert all(v['trust_env'] is False and v['follow_redirects'] is False for v in native.constructors)


async def test_user_explicit_environment_witness_not_a_rewritten_key(native):
    args={'user_id':'QON_fixture','expected_environment':'prod','confirm_user_metadata':True}
    result=await native.run('get_user',args)
    assert result['status']=='error' and native.requests[-1].headers['Authorization']=='Bearer '+KEY and not native.requests[-1].url.query


@pytest.mark.parametrize('operation,args',[('get_user',{'user_id':'QON_fixture','expected_environment':'sandbox'}),('get_user',{'user_id':'QON_fixture','expected_environment':'sandbox','confirm_user_metadata':1}),('get_product',{'product_id':'../other'}),('get_product',{'product_id':'https://foreign.example.test'}),('get_remote_configuration',{'configuration_id':'not-a-uuid'}),('list_products',{'limit':True}),('list_products',{'limit':101}),('list_products',{'starting_after':'raw'}),('list_products',{'environment':0}),('list_products',{'product_types':['subscription','subscription']}),('grant_entitlement',{}),('create_user',{})])
async def test_untyped_inputs_and_mutations_refused_before_provider(native,operation,args):
    from nodes.core.base import ConfigValidationError
    with pytest.raises(ConfigValidationError):await native.run(operation,args)
    assert native.requests==[]


async def test_product_filter_last_id_paging_scope_and_cap(native):
    native.replies['products']=(200,{'object':'list','url':'/v4/products','data':[product()],'has_more':True,'next_cursor':PRODUCT})
    args={'limit':1,'max_pages':2,'product_types':['subscription','lifetime']}
    first=await native.run('list_products',args,saved=True);token=first['data']['next_page_token'];assert token
    request=native.requests[-1];assert request.url.params.get_list('filter[type]')==['subscription','lifetime']
    assert request.url.params['limit']=='1' and 'environment' not in request.url.params
    native.requests.clear()
    for changed in [{'limit':2},{'max_pages':3},{'product_types':['lifetime']}]:
        assert (await native.run('list_products',{**args,**changed,'page_token':token},saved=True))['status']=='error'
    cursor=json.loads(base64.urlsafe_b64decode(token));cursor['after']='forged'
    forged=base64.urlsafe_b64encode(json.dumps(cursor).encode()).decode()
    assert (await native.run('list_products',{**args,'page_token':forged},saved=True))['status']=='error' and native.requests==[]
    assert (await native.run('list_entitlement_definitions',{'limit':1,'max_pages':2,'page_token':token},saved=True))['status']=='error'
    native.blob['secret_key']='sk_reconnected'
    assert (await native.run('list_products',{**args,'page_token':token},saved=True))['status']=='error' and native.requests==[]
    native.blob=deepcopy(BLOB);native.row['token_version']=8
    assert (await native.run('list_products',{**args,'page_token':token},saved=True))['status']=='error' and native.requests==[]
    native.row['token_version']=7
    native.replies['products']=(200,{'object':'list','url':'/v4/products','data':[product('second')],'has_more':True})
    second=await native.run('list_products',{**args,'page_token':token},saved=True)
    assert native.requests[-1].url.params['starting_after']==PRODUCT
    assert second['data']['truncated'] is True and second['data']['next_page_token'] is None and second['data']['stop_reason']=='local_page_cap'


async def test_ambiguous_next_cursor_preserves_page_without_guessing_next_request(native):
    native.replies['products']=(200,{'object':'list','url':'/v4/products','data':[product()],'has_more':True,'next_cursor':'opaque/cursor=='})
    result=await native.run('list_products')
    assert result['status']=='success' and result['data']['items'][0]['id']==PRODUCT
    assert result['data']['continuation_known'] is False and result['data']['next_page_token'] is None and result['data']['stop_reason']=='ambiguous_cursor_contract'
    assert len(native.requests)==1


@pytest.mark.parametrize('change',[{'has_more':'true'},{'has_more':True,'data':[]},{'has_more':False,'next_cursor':'stale'},{'object':'product'},{'url':'https://foreign.example.test/products'},{'data':[product(),product()]},{'data':[{'object':'product','id':PRODUCT}]},{'data':[product()],'error':{'message':KEY}}])
async def test_malformed_lists_and_business_errors_are_safe(native,change):
    native.replies['products']=(200,{'object':'list','url':'/v4/products','data':[product()],'has_more':False,**change})
    result=await native.run('list_products')
    assert result['status']=='error' and KEY not in json.dumps(result)


@pytest.mark.parametrize('status',[201,202,204,302,400,401,403,404,409,422,429,500,502,504])
async def test_exact_200_status_contract_sanitized_no_retry_or_revoke(native,status):
    native.replies['products']=(status,{'error':{'type':'request','code':'control_unauthorized','message':KEY,'details':[{'message':PRIVATE}]}})
    result=await native.run('list_products')
    assert result['status']=='error' and result['status_code']==status and KEY not in json.dumps(result) and PRIVATE not in json.dumps(result)
    assert len(native.requests)==1 and native.row['revoked_at'] is None


async def test_actual_native_picker_uses_complete_scoped_page_or_refuses_partial(native):
    from nodes.core.run_op import run_node_lookup
    result=await run_node_lookup(node_type='automation-qonversion',field_name='product_id',user_id=USER,pool=native.pool,organization_id=None,credential_id=CID)
    assert result['options']==[{'label':PRODUCT,'value':PRODUCT}]
    native.replies['products']=(200,{'object':'list','url':'/v4/products','data':[product()],'has_more':True})
    with pytest.raises(ValueError):await run_node_lookup(node_type='automation-qonversion',field_name='product_id',user_id=USER,pool=native.pool,organization_id=None,credential_id=CID)




@pytest.mark.parametrize('payload,headers',[(b'not JSON',{'Content-Type':'application/json'}),(b'{}',{'Content-Type':'text/html'}),(b'x'*2_000_001,{'Content-Type':'application/json'})])
async def test_unreadable_or_oversized_transport_response_never_counts_as_success(native,payload,headers):
    native.replies['products']=(200,payload,headers)
    result=await native.run('list_products')
    assert result['status']=='error' and len(native.requests)==1
    assert KEY not in json.dumps(result) and native.row['revoked_at'] is None


async def test_transport_failure_is_sanitized_without_retry(native):
    native.transport_error=httpx.ReadError(KEY+' '+PRIVATE)
    result=await native.run('list_products')
    assert result['status']=='error' and KEY not in json.dumps(result) and PRIVATE not in json.dumps(result)
    assert len(native.requests)==1 and native.row['revoked_at'] is None


async def test_complete_empty_list_and_documented_nullable_integer_priority(native):
    native.replies['products']=(200,{'object':'list','url':'/v4/products','data':[],'has_more':False,'next_cursor':None})
    result=await native.run('list_products')
    assert result['status']=='success' and result['data']['items']==[] and result['data']['stop_reason']=='provider_complete'
    native.replies['remote-configurations/'+CONFIG_ID]=(200,{**configuration(),'priority':-1})
    result=await native.run('get_remote_configuration',{'configuration_id':CONFIG_ID})
    assert result['status']=='success' and result['data']['priority']==-1


async def test_safe_output_refuses_key_reflection_and_bounds_definition_product_projection(native):
    native.replies['products/'+PRODUCT]=(200,{**product(),'apple_product_id':KEY})
    result=await native.run('get_product',{'product_id':PRODUCT})
    assert result['status']=='error' and KEY not in json.dumps(result)
    native.replies['entitlements/premium']=(200,{**definition(),'product_ids':['product_'+str(i) for i in range(101)]})
    result=await native.run('get_entitlement_definition',{'entitlement_id':'premium'})
    assert result['status']=='success' and len(result['data']['product_ids'])==100
    assert result['data']['product_count']==101 and result['data']['product_ids_truncated'] is True
