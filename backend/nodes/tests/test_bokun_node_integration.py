"""Synthetic fixtures for Bókun's actual native factory and wire seams.
They cover authentication, staging credential handling, schema, responses and write uncertainty.
"""
import base64
import hashlib
import hmac
import json
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes.core.registry import NodeFactory
from nodes.bokun_node import BokunNode, BokunAppTokenCredential, credential_shape
from nodes import bokun_node as wire

KEY = {"credential_type":"bokun_rest_hmac","environment":"sandbox","access_key":"synthetic-access-key-001","secret_key":"synthetic-secret-key-001"}
APP = {"credential_type":"bokun_app_token","environment":"sandbox","tenant":"fixture-vendor","access_token":"synthetic-app-token-001"}
CID="00000000-0000-4000-8000-000000000001"
USER="00000000-0000-4000-8000-000000000002"
OWNER="00000000-0000-4000-8000-000000000003"
WORKFLOW="00000000-0000-4000-8000-000000000004"


def node(operation,arguments=None,credential=None,saved=True):
    value={'config':{'operation':operation,**(arguments or {})},'credentials':dict(credential or KEY)}
    if saved:value['credential_id']=CID
    return NodeFactory.create_node('fixture','automation-bokun',value,user_id=USER,workflow_id=WORKFLOW,organization_id=None)


def category(title='Adult'):
    return {'id':11,'title':title,'ticketCategory':'ADULT','occupancy':1,'ageQualified':False,'dependent':False,'internalUseOnly':True,'sumDependentCategories':False}


@pytest.fixture
def native(monkeypatch):
    state={'credential':dict(KEY)}
    calls=[]
    def install(handler):
        def request(req):calls.append(req);return handler(req)
        monkeypatch.setattr(wire,'_client',lambda:httpx.AsyncClient(transport=httpx.MockTransport(request),follow_redirects=False,trust_env=False))
    return state,calls,install


def test_actual_schema_and_family_privacy():
    schema=BokunNode.get_config_schema()
    operations={v['properties']['operation']['const'] for v in schema['$defs'].values() if 'operation' in v.get('properties',{})}
    assert len(operations)==19 and {'create_booking','checkout','cancel_booking','refund','create_pricing_category'}.isdisjoint(operations)
    for name in ('BokunRESTKeysCredential','BokunRESTHMACCredential'):
        assert schema['$defs'][name]['properties']['secret_key']['ui:widget']=='password'
    assert schema['$defs']['BokunAppTokenCredential']['properties']['access_token']['ui:widget']=='password'
    assert schema['$defs']['DeleteUnusedPricingCategory']['properties']['acknowledge_deletion']['const'] is True
    assert 'environment fallback' in schema['properties']['credentials']['description']
    with pytest.raises(Exception) as caught:BokunAppTokenCredential.model_validate({**APP,'tenant':'https://private.invalid/SECRET_SENTINEL'})
    assert 'SECRET_SENTINEL' not in str(caught.value)
    with pytest.raises(ValueError):credential_shape({**APP,'tenant':'api'})
    with pytest.raises(Exception):node('get_activity',{'activity_id':True,'currency':'USD'})


@pytest.mark.asyncio
async def test_actual_encoded_path_signature_and_direct_key_family(native):
    state,calls,install=native
    install(lambda req:httpx.Response(200,json={'id':31,'title':'Fixture','keywords':[],'shortDescription':''}))
    result=await node('get_experience_metadata',{'experience_id':31}).execute({})
    assert result['status']=='success'
    req=calls[0];assert req.url.host=='api.bokuntest.com' and req.method=='GET'
    assert req.url.params.get_list('componentType')==list(wire.COMPONENTS)
    date=req.headers['X-Bokun-Date']
    expected=hmac.new(KEY['secret_key'].encode(),(date+KEY['access_key']+'GET'+req.url.raw_path.decode()).encode(),hashlib.sha1).digest()
    assert req.headers['X-Bokun-Signature']==base64.b64encode(expected).decode()
    assert 'secret-key' not in req.headers and 'access-key' not in req.headers
    state['credential']={**KEY,'credential_type':'bokun_rest_keys','environment':'production'}
    result=await node('get_experience_metadata',{'experience_id':31},state['credential']).execute({})
    assert result['status']=='success' and calls[-1].url.host=='api.bokun.io'
    assert calls[-1].headers['secret-key']==KEY['secret_key'] and 'X-Bokun-Signature' not in calls[-1].headers


@pytest.mark.asyncio
async def test_actual_connect_evidence_and_pending_native_admission(native,monkeypatch):
    from nodes.core.connection_evidence import collect_evidence
    from nodes.core.credential_connect import validate_for_connect
    from nodes.core.run_op import run_node_operation
    _,calls,install=native;install(lambda _:httpx.Response(200,json=[]))
    evidence=await collect_evidence(node_type='automation-bokun',credential_data=dict(KEY),user_id=USER)
    assert evidence.reachable is True and evidence.account_label is None and BokunNode.connection_evidence.proves=='reachability'
    verdict=await validate_for_connect(credential_type='bokun_rest_hmac',credential_data=dict(KEY),user_id=USER)
    assert verdict.ok and verdict.evidence.account_label is None
    before=len(calls);pending={'status':'pending_approval','executed':False,'message':'Fixture pending','_halt_downstream':True}
    monkeypatch.setattr('utils.credential_approval.admit_node',AsyncMock(return_value=pending))
    result=await run_node_operation(node_type='automation-bokun',operation='check_connection',arguments={},user_id=USER,credential_id=CID,credential_data=dict(KEY))
    assert result==pending and len(calls)==before



@pytest.mark.asyncio
async def test_write_preserves_constraints_204_readback_and_empty_delete(native):
    _,calls,install=native;current=category()
    def response(req):
        if req.method=='PUT':current.update(json.loads(req.content));return httpx.Response(204)
        if req.method=='DELETE':return httpx.Response(200,content=b'')
        return httpx.Response(200,json=current)
    install(response)
    result=await node('update_pricing_category_title',{'pricing_category_id':11,'title':'Synthetic title'}).execute({})
    assert result['status']=='success' and result['data']==category('Synthetic title')
    assert [r.method for r in calls]==['GET','PUT','GET']
    assert json.loads(calls[1].content)==category('Synthetic title')
    result=await node('delete_unused_pricing_category',{'pricing_category_id':11,'acknowledge_deletion':True}).execute({})
    assert result['status']=='success' and result['data']['deleted_id']==11
    assert calls[-1].method=='DELETE' and calls[-1].url.path=='/restapi/v2.0/pricing/category/11'
    before=len(calls)
    install(lambda _:httpx.Response(503,json={'secret':KEY['secret_key']}))
    result=await node('update_pricing_category_title',{'pricing_category_id':11,'title':'Uncertain'}).execute({})
    assert result['status']=='error' and result['automatic_replay'] is False and len(calls)==before+1
    assert result['outcome_uncertain'] is False  # preflight failed before any write
    assert KEY['secret_key'] not in json.dumps(result)
    install(lambda req:httpx.Response(503,json={}) if req.method=='PUT' else httpx.Response(200,json=current))
    before=len(calls)
    result=await node('update_pricing_category_title',{'pricing_category_id':11,'title':'Uncertain'}).execute({})
    assert result['status']=='error' and result['outcome_uncertain'] is True and len(calls)==before+2


@pytest.mark.asyncio
@pytest.mark.parametrize('clear_keywords', [False, True])
async def test_component_clear_and_no_activation_or_price_payload(native, clear_keywords):
    _,calls,install=native;current={'id':31,'title':'Old','shortDescription':'Old','keywords':['old']}
    def response(req):
        if req.method=='PUT':current.update(json.loads(req.content))
        return httpx.Response(200,json=current)
    install(response)
    arguments={'experience_id':31,'clear_short_description':True,'short_description':''}
    if clear_keywords:arguments['keywords']=[]
    result=await node('update_experience_metadata',arguments).execute({})
    assert result['status']=='success' and result['data']['shortDescription']==''
    assert json.loads(calls[1].content)==({'shortDescription':'','keywords':[]} if clear_keywords else {'shortDescription':''})
    assert result['data']['keywords']==([] if clear_keywords else ['old'])
    with pytest.raises(ValueError):
        node('update_experience_metadata',{'experience_id':31,'clear_short_description':True,'short_description':'Old'})


@pytest.mark.asyncio
async def test_booking_status_projection_target_and_availability_parent(native):
    _,calls,install=native
    install(lambda _:httpx.Response(200,json={'bookingId':77,'status':'CONFIRMED','currency':'USD','totalPrice':1.1,'confirmationCode':'PRIVATE_SENTINEL','customer':{'email':'PRIVATE_SENTINEL'}}))
    result=await node('get_booking_status',{'booking_id':77,'currency':'USD'}).execute({})
    assert result['data']=={'bookingId':77,'status':'CONFIRMED','currency':'USD'} and 'PRIVATE_SENTINEL' not in json.dumps(result)
    install(lambda _:httpx.Response(200,json={'bookingId':78,'status':'CONFIRMED','currency':'USD'}))
    assert (await node('get_booking_status',{'booking_id':77,'currency':'USD'}).execute({}))['status']=='error'
    install(lambda _:httpx.Response(200,json=[{'activityId':9,'id':'9_20261007','date':1791331200000,'startTime':'09:00','availabilityCount':10}]))
    assert (await node('get_activity_availability',{'activity_id':8,'currency':'USD','start':'2026-10-07','end':'2026-10-08'}).execute({}))['status']=='error'


@pytest.mark.asyncio
async def test_graphql_fixed_tenant_cursor_scope_and_partial_errors(native):
    state,calls,install=native;state['credential']=dict(APP)
    page={'edges':[{'cursor':'c1','node':{'id':'opaque-1','name':'Fixture','activated':False}}],'pageInfo':{'hasNextPage':True,'endCursor':'c1'},'totalCount':2}
    install(lambda _:httpx.Response(200,json={'data':{'productLists':page}}))
    result=await node('list_graphql_product_lists',{'first':1},APP).execute({})
    assert result['status']=='success' and calls[0].url.host=='fixture-vendor.bokuntest.com'
    assert calls[0].headers['X-Bokun-App-Access-Token']==APP['access_token']
    assert json.loads(calls[0].content)['query']==wire.GQL['productLists']
    token=result['data']['next_page_token'];data=await BokunNode.freshen_credential(APP,user_id=USER,credential_id=CID)
    assert wire.page_cursor(data,token,{'kind':'productLists','first':1})=='c1'
    decoded=base64.urlsafe_b64decode(token+'='*(-len(token)%4)).decode(errors='ignore')
    assert OWNER not in decoded and APP['access_token'] not in decoded
    state['credential']={**APP,'tenant':'other-vendor'}
    other=await BokunNode.freshen_credential(state['credential'],user_id=USER,credential_id=CID)
    with pytest.raises(ValueError):wire.page_cursor(other,token,{'kind':'productLists','first':1})
    state['credential']=dict(APP)
    install(lambda _:httpx.Response(200,json={'data':{'productLists':page},'errors':[{'message':APP['access_token']}]}))
    result=await node('list_graphql_product_lists',{},APP).execute({})
    assert result['status']=='error' and APP['access_token'] not in json.dumps(result)
    install(lambda _:httpx.Response(200,json={'data':{'productLists':page},'errors':[{'message':'Required permissions missing'}]}))
    result=await node('list_graphql_product_lists',{},APP).execute({})
    assert result['code']=='graphql_rejection' and 'data' not in result


@pytest.mark.asyncio
async def test_staging_supplied_credential_and_native_pagination(native):
    _,calls,install=native
    install(lambda _:httpx.Response(200,json=[]))
    assert (await node('list_owned_experience_ids',saved=False).execute({}))['status']=='success'
    before=len(calls)
    assert (await node('list_owned_experience_ids',credential=APP,saved=False).execute({}))['status']=='error'
    assert len(calls)==before
    install(lambda _:httpx.Response(200,json={'pageNo':0,'pageSize':1,'totalPageCount':2,'totalCount':2,'items':[category()]}))
    result=await node('list_pricing_categories',{'page_size':1}).execute({})
    assert result['status']=='success' and result['data']['next_page_no']==1
    assert dict(calls[-1].url.params)=={'pageNo':'0','pageSize':'1'}


@pytest.mark.asyncio
@pytest.mark.parametrize('status',[202,204,301,401,403,429,503])
async def test_read_status_uncertainty_never_replays(status,native):
    _,calls,install=native;install(lambda _:httpx.Response(status,json={'secret':KEY['secret_key']}))
    result=await node('check_connection',saved=False).execute({})
    assert result['status']=='error' and result['http_status']==status and len(calls)==1
    assert KEY['secret_key'] not in json.dumps(result)


def test_closed_public_transport_and_decimal_json(monkeypatch):
    capture={};monkeypatch.setattr(wire.httpx,'AsyncClient',lambda **kw:capture.update(kw));wire._client()
    assert not capture['follow_redirects'] and not capture['trust_env'] and capture['timeout']==20.0
    assert not wire._route('POST','/booking.json/activity-booking/reserve-and-confirm')
    assert not wire._route('GET','/booking.json/77/abort-reserved')
    assert str(wire.parse_json(b'{"amount":0.100000000000000001}')['amount'])=='0.100000000000000001'
    for raw in (b'{"id":1,"id":2}',b'{"amount":NaN}',b'not-json'):
        with pytest.raises(wire.BokunAPIError):wire.parse_json(raw)
