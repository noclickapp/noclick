"""SAP Concur native dispatch, transport, validation and response privacy."""
import asyncio
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
import json
import socket
from types import SimpleNamespace
from unittest.mock import AsyncMock
import httpx
import pytest

USER="00000000-0000-4000-8000-000000000001"
OWNER="00000000-0000-4000-8000-000000000002"
CID="00000000-0000-4000-8000-000000000003"
WORKFLOW="00000000-0000-4000-8000-000000000004"
LIST="00000000-0000-4000-8000-000000000010"
ITEM="00000000-0000-4000-8000-000000000011"
TOKEN="synthetic_concur_access_token"
REFRESH="synthetic_concur_refresh_token"
FAMILY="sap_concur_oauth"
BLOB={"access_token":TOKEN,"geolocation":"https://us2.api.concursolutions.com"}
NOW=datetime(2026,10,6,tzinfo=timezone.utc)
EXPIRED={**BLOB,"refresh_token":REFRESH,"client_id":OWNER,"client_secret":"synthetic_client_secret","expires_at":"2000-01-01T00:00:00+00:00","scope":"spend.list.read"}


@pytest.fixture
def ensure_native_db_pool():
    yield


def listing(**extra):return {"id":LIST,"value":"Fixture list","isReadOnly":False,"isDeleted":False,**extra}
def item(**extra):return {"id":ITEM,"value":"Fixture item","shortCode":"FIXTURE","lists":[{"id":LIST,"hasChildren":False}],**extra}
def page(rows,number=1,pages=1):return {"content":rows,"page":{"size":100,"totalElements":len(rows)+(1 if pages>number else 0),"totalPages":pages,"number":number},"links":[{"rel":"next","href":"https://hostile.invalid/?token="+TOKEN}]}


@pytest.fixture
async def native(monkeypatch):
    from nodes import sap_concur_node as provider
    from nodes.oauth import sap_concur_oauth as oauth
    from nodes.core import credential_connect, connection_evidence
    from utils import ssrf
    state = SimpleNamespace(requests=[], replies={}, constructors=[], writes=[])
    monkeypatch.setattr(credential_connect, '_collect_evidence', connection_evidence.collect_evidence)
    credential_connect._class_index.cache_clear()
    monkeypatch.setattr(asyncio.get_running_loop(), 'getaddrinfo', AsyncMock(return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443))]))
    def respond(request):
        state.requests.append(request)
        if getattr(state,'transport_error',None):raise state.transport_error
        key=(request.method,request.url.path);reply=state.replies.get(key)
        if reply is None:
            route=request.url.path
            if route=='/oauth2/v0/token':reply=(200,{"access_token":"synthetic_new_access","refresh_token":"synthetic_new_refresh","expires_in":"3600","token_type":"Bearer","scope":"spend.list.read","geolocation":"https://eu2.api.concursolutions.com","id_token":"private_ignored_id_token"})
            elif route=='/list/v4/lists':reply=(200,page([listing()],int(request.url.params.get('page','1'))))
            elif route=='/list/v4/lists/'+LIST:reply=(200,listing())
            elif route=='/list/v4/lists/'+LIST+'/children':reply=(200,page([item()],int(request.url.params['page'])))
            elif route=='/list/v4/items/'+ITEM:reply=(200,item())
            elif route=='/profile/identity/v4/Users':reply=(200,{"Resources":[{"id":OWNER,"displayName":"Fixture user","active":True,"emails":[TOKEN]}],"startIndex":int(request.url.params['startIndex']),"itemsPerPage":1,"totalResults":1})
            elif route=='/profile/identity/v4/Users/'+OWNER:reply=(200,{"id":OWNER,"displayName":"Fixture user","active":True,"dateOfBirth":TOKEN,"emails":[TOKEN]})
            elif route.endswith('/reports/FIXTUREREPORT'):reply=(200,{"reportId":"FIXTUREREPORT","userId":OWNER,"name":"Fixture report","approvalStatus":"Not Submitted","reportTotal":{"value":999},"customData":[TOKEN],"businessPurpose":TOKEN})
        assert reply is not None,key
        code,payload,*headers=reply
        if request.url.path!='/oauth2/v0/token' and getattr(state,'after_read',None):
            callback,state.after_read=state.after_read,None;callback()
        return httpx.Response(code,content=b'' if payload is None else json.dumps(payload).encode(),headers={"Content-Type":"application/json",**(headers[0] if headers else {})})
    original=ssrf.guarded_async_client
    def client(**kwargs):state.constructors.append(kwargs);return original(**kwargs,transport=httpx.MockTransport(respond))
    monkeypatch.setattr(provider,'guarded_async_client',client);monkeypatch.setattr(oauth,'guarded_async_client',client)
    async def run(operation, args=None, *, blob=None):
        from nodes.core.run_op import run_node_operation
        return await run_node_operation(node_type='automation-sap-concur', operation=operation, arguments=args or {}, user_id=USER,
            credential_data=deepcopy(BLOB) if blob is None else blob)
    state.run = run
    yield state
    credential_connect._class_index.cache_clear()


async def test_actual_factory_shape_connect_and_default_protected_account_evidence(native):
    from nodes.core.registry import NodeFactory
    from nodes.core.credential_connect import shape_credential,validate_for_connect
    from nodes.sap_concur_node import SAPConcurNode
    shaped,errors,resolved=shape_credential(FAMILY,BLOB)
    assert not errors and shaped==BLOB and resolved[0]=='automation-sap-concur'
    assert NodeFactory.is_registered('automation-sap-concur')
    schema=SAPConcurNode.get_config_schema();assert len(schema['properties']['config']['discriminator']['mapping'])==13
    assert 'value' in schema['$defs']['CreateList']['required'] and 'short_code' in schema['$defs']['CreateItem']['required']
    verdict=await validate_for_connect(credential_type=FAMILY,credential_data=BLOB,user_id=USER)
    assert verdict.ok and verdict.evidence.samples[0].label=='Fixture list'
    req=native.requests[-1];assert req.url.host=='us2.api.concursolutions.com' and req.url.path=='/list/v4/lists'
    assert req.headers['Authorization']=='Bearer '+TOKEN and dict(req.url.params)=={'page':'1'}
    assert all(x['trust_env'] is False and x['follow_redirects'] is False for x in native.constructors)


@pytest.mark.parametrize('tag',[None,'',7,[],{},'slack_oauth',' sap_concur_oauth '])
def test_native_supplied_foreign_family_before_inherited_parse(native,tag):
    from nodes.sap_concur_node import SAPConcurNode
    from nodes.core.base import ConfigValidationError
    from nodes.core.registry import NodeFactory
    raw={'config':{'operation':'list_lists'},'credentials':{**BLOB,'credential_type':tag}}
    assert not SAPConcurNode.validate_config(raw)['valid']
    with pytest.raises(ConfigValidationError):NodeFactory.create_node('fixture','automation-sap-concur',raw,user_id=USER)
    assert native.requests==[]


async def test_expired_connect_never_consumes_refresh_before_row_save(native):
    from nodes.core.credential_connect import validate_for_connect
    verdict=await validate_for_connect(credential_type=FAMILY,credential_data=EXPIRED,user_id=USER)
    assert verdict.ok and verdict.evidence.reachable is None and verdict.credential_data['refresh_token']==REFRESH
    assert native.requests==[] and native.writes==[]


async def test_actual_profiles_and_report_metadata_parent_privacy(native):
    result=await native.run('list_identities',{'count':100,'start_index':1})
    assert result['data']['items']==[{'id':OWNER,'displayName':'Fixture user','active':True}]
    assert dict(native.requests[-1].url.params)=={'count':'100','startIndex':'1','attributes':'id,displayName,active'}
    assert (await native.run('get_identity',{'user_id':OWNER}))['data']['id']==OWNER
    result=await native.run('get_report',{'user_id':OWNER,'report_id':'FIXTUREREPORT'})
    assert result['data']=={'reportId':'FIXTUREREPORT','userId':OWNER,'name':'Fixture report','approvalStatus':'Not Submitted'}
    assert not any(x in json.dumps(result) for x in (TOKEN,'reportTotal','customData','businessPurpose','emails','dateOfBirth'))
    route=native.requests[-1].url.path;native.replies[('GET',route)]=(200,{'reportId':'FIXTUREREPORT','userId':USER})
    assert (await native.run('get_report',{'user_id':OWNER,'report_id':'FIXTUREREPORT'}))['status']=='error'


async def test_actual_parent_picker_cursor_binding_and_untrusted_links(native):
    from nodes.sap_concur_node import SAPConcurNode
    async def run_node_lookup(**kwargs):
        return await SAPConcurNode.load_field_options(kwargs["field_name"], BLOB, context=kwargs.get("context"), page_token=kwargs.get("page_token"), search=kwargs.get("search"))
    native.replies[('GET','/list/v4/lists')]=(200,page([listing(id=LIST[:-12]+f'{16+i:012x}') for i in range(100)],pages=2))
    a=await run_node_lookup(node_type='automation-sap-concur',field_name='list_id',user_id=USER,credential_id=CID)
    assert a['options'][0]['value']==LIST and a['next_page_token']
    native.requests.clear()
    with pytest.raises(ValueError):await run_node_lookup(node_type='automation-sap-concur',field_name='item_id',user_id=USER,credential_id=CID,context={})
    with pytest.raises(ValueError):await run_node_lookup(node_type='automation-sap-concur',field_name='list_id',user_id=USER,credential_id=CID,page_token=a['next_page_token'],search='different')
    assert native.requests==[]
    b=await run_node_lookup(node_type='automation-sap-concur',field_name='item_id',user_id=USER,credential_id=CID,context={'list_id':LIST})
    assert b['options'][0]['value']==ITEM and native.requests[-1].url.host=='us2.api.concursolutions.com'


async def test_actual_configuration_bodies_statuses_parent_scope_and_204(native):
    confirm={'confirm_configuration_change':True}
    native.replies[('POST','/list/v4/lists')]=(201,listing())
    result=await native.run('create_list',{**confirm,'value':'Fixture list'})
    assert result['status']=='success' and json.loads(native.requests[-1].content)=={'value':'Fixture list','searchCriteria':'TEXT','displayFormat':'(CODE) TEXT'}
    native.replies[('PUT','/list/v4/lists/'+LIST)]=(200,listing(value='Updated'))
    assert (await native.run('update_list',{**confirm,'list_id':LIST,'value':'Updated'}))['status']=='success'
    native.replies[('POST','/list/v4/items')]=(201,item())
    assert (await native.run('create_list_item',{**confirm,'list_id':LIST,'value':'Fixture item','short_code':'FIXTURE'}))['status']=='success'
    assert json.loads(native.requests[-1].content)=={'listId':LIST,'value':'Fixture item','shortCode':'FIXTURE'}
    native.replies[('PUT','/list/v4/items/'+ITEM)]=(200,item(value='Updated'))
    assert (await native.run('update_list_item',{**confirm,'list_id':LIST,'item_id':ITEM,'value':'Updated','short_code':'FIXTURE'}))['status']=='success'
    native.replies[('DELETE','/list/v4/lists/'+LIST+'/items/'+ITEM)]=(204,None)
    result=await native.run('remove_list_item',{**confirm,'list_id':LIST,'item_id':ITEM})
    assert result['status']=='success' and result['data']['verified_readback'] is None
    assert native.requests[-1].url.path=='/list/v4/lists/'+LIST+'/items/'+ITEM
    native.replies[('DELETE','/list/v4/lists/'+LIST)]=(204,None)
    assert (await native.run('delete_list',{**confirm,'list_id':LIST}))['status']=='success'
    native.replies[('GET','/list/v4/items/'+ITEM)]=(200,item(lists=[{'id':OWNER}]))
    before=len(native.requests)
    assert (await native.run('remove_list_item',{**confirm,'list_id':LIST,'item_id':ITEM}))['status']=='error'
    assert len(native.requests)==before+2 and native.requests[-1].method=='GET'


@pytest.mark.parametrize('status',[201,202,204,301,400,401,403,404,429,503])
async def test_unexpected_read_status_no_retry_raw_body_or_cross_origin(native,status):
    native.replies[('GET','/list/v4/lists')]=(status,{'message':TOKEN},{'Retry-After':'42','Location':'https://attacker.invalid'})
    result=await native.run('list_lists')
    assert result['status']=='error' and result['status_code']==status and result['retry_after']==42 and len(native.requests)==1
    assert TOKEN not in json.dumps(result)


async def test_transport_failure_is_unknown_and_private_output_is_refused(native):
    from nodes.core.credential_connect import validate_for_connect
    native.transport_error=httpx.ConnectError('Synthetic failure '+TOKEN)
    v=await validate_for_connect(credential_type=FAMILY,credential_data=BLOB,user_id=USER)
    assert v.ok and v.evidence.reachable is None and TOKEN not in json.dumps(asdict(v.evidence))
    native.transport_error=None;native.replies[('GET','/list/v4/lists')]=(200,page([listing(value=TOKEN)]))
    assert (await native.run('list_lists'))['status']=='error'


@pytest.mark.parametrize('status,code,dead',[(400,'invalid_grant',True),(401,'invalid_refresh_token',True),(400,'invalid_client',False),(403,'invalid_grant',False),(429,'invalid_grant',False),(503,'invalid_grant',False)])
async def test_refresh_classifies_only_documented_dead_grant_error_shape(native,status,code,dead):
    from nodes.oauth.sap_concur_oauth import make_refresh
    native.replies[('POST','/oauth2/v0/token')]=(status,{'error':code,'error_description':EXPIRED['client_secret']})
    with pytest.raises(Exception) as failure:await make_refresh(deepcopy(EXPIRED))(REFRESH)
    assert isinstance(failure.value,ValueError) is dead
    assert EXPIRED['client_secret'] not in str(failure.value) and len(native.requests)==1 and native.writes==[]


@pytest.mark.parametrize('origin',['http://us2.api.concursolutions.com','https://www-us2.api.concursolutions.com','https://us.api.concursolutions.com','https://us2.api.concursolutions.com:443','https://us2.api.concursolutions.com/?x=y','https://us2.api.concursolutions.com.attacker.invalid'])
async def test_connection_refuses_unapproved_origin_before_provider(native,origin):
    from nodes.core.credential_connect import validate_for_connect
    verdict=await validate_for_connect(credential_type=FAMILY,credential_data={**BLOB,'geolocation':origin},user_id=USER)
    assert not verdict.ok and 'geolocation' in verdict.field_errors and native.requests==[]


@pytest.mark.parametrize('field',['value','short_code'])
async def test_item_hyphen_refusal_before_native_write_preflight(native,field):
    from nodes.core.base import ConfigValidationError
    arguments={'confirm_configuration_change':True,'list_id':LIST,'value':'Fixture item','short_code':'FIXTURE',field:'unsupported-hyphen'}
    with pytest.raises(ConfigValidationError):await native.run('create_list_item',arguments)
    assert native.requests==[]


@pytest.mark.parametrize('status',[200,202,204])
async def test_delete_does_not_claim_completion_from_pending_or_nonempty_response(native,status):
    native.replies[('DELETE','/list/v4/lists/'+LIST)]=(status,{'success':True,'private':TOKEN})
    result=await native.run('delete_list',{'list_id':LIST,'confirm_configuration_change':True})
    assert result['status']=='error' and 'deletion_request_completed' not in result and TOKEN not in json.dumps(result)
    assert len(native.requests)==2 and native.requests[-1].method=='DELETE'
