"""Actual Vervoe native factory/transport/access seams; synthetic external boundaries only."""
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timezone
from dataclasses import asdict
import json
import socket
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

USER = "00000000-0000-4000-8000-000000000001"
OWNER = "00000000-0000-4000-8000-000000000002"
CID = "00000000-0000-4000-8000-000000000003"
WORKFLOW = "00000000-0000-4000-8000-000000000004"
TOKEN = "synthetic_vervoe_bearer_token"
FAMILY = "vervoe_bearer_token"
BLOB = {"access_token": TOKEN}
NOW = datetime(2026, 10, 6, tzinfo=timezone.utc)


@pytest.fixture
def ensure_native_db_pool():
    yield


APP = "00000000-0000-4000-8000-000000000010"
FOLDER = "00000000-0000-4000-8000-000000000011"
SLUG = "fixture_assessment"
PAIR = {"api_key": "synthetic_api_key", "secret_key": "synthetic_secret_key"}
MINT = "synthetic_minted_vervoe_token"


def assessment(**changes):
    return {"slug": SLUG, "name": "Fixture assessment", "skills": ["Fixture skill"], "auditionFolder": {"uuid": FOLDER, "name": "Fixture folder"}, "description": "private description", **changes}


def report(**changes):
    return {"candidateAssessmentUuid": APP, "assessmentSlug": SLUG, "status": "complete", "completedAt": "2026-10-06T00:00:00Z", "score": {"score": 100}, "candidateEmail": "private@example.test", "integrationCandidateCardUrl": "https://example.test/?token="+TOKEN, "plagiarismDetected": True, **changes}


def page(items, current=1, more=False):
    return {"items": items, "count": len(items), "total": len(items)+(1 if more else 0), "currentPage": current, "hasMorePages": more}


@pytest.fixture
async def native(monkeypatch):
    from nodes import vervoe_node as provider
    from nodes.core import credential_connect, connection_evidence
    from repositories.credentials import credential_access_predicate
    from repositories.organization import OrgRepo
    from repositories.credential_approvals import CredentialApprovalRepo
    from utils import credentials, encryption, credential_approval, ssrf
    state = SimpleNamespace(blob=deepcopy(BLOB), allowed={USER}, requests=[], replies={}, after_read=None, approval=None, constructors=[],
        row={"id": CID, "owner_id": USER, "credential_type": FAMILY, "credential": b"synthetic-blob", "token_version": 7,
        "updated_at": NOW, "created_at": NOW, "revoked_at": None, "approval_revision": 0, "name": "Fixture connection", "metadata": {}}, sql=[])

    class Pool:
        @asynccontextmanager
        async def acquire(self):
            yield self

        async def fetchrow(self, sql, *args):
            state.sql.append((sql, args))
            assert credential_access_predicate() in sql
            return deepcopy(state.row) if args[0] == CID and args[1] in state.allowed else None

    state.pool, state.crypto = Pool(), MagicMock()
    state.crypto.decrypt_credential.side_effect = lambda _: deepcopy(state.blob)
    monkeypatch.setattr(encryption, "get_encryption", lambda: state.crypto)
    monkeypatch.setattr(credentials, "get_encryption", lambda: state.crypto)
    monkeypatch.setattr(OrgRepo, "get_primary_org_id", AsyncMock(return_value=None))
    monkeypatch.setattr(credentials, "get_workflow_owner_id", AsyncMock(return_value=OWNER))
    state.workflow_grant = AsyncMock(return_value=True)
    monkeypatch.setattr(credentials, "is_credential_authorized_for_workflow", state.workflow_grant)
    state.admit = AsyncMock(side_effect=lambda **_: state.approval)
    monkeypatch.setattr(CredentialApprovalRepo, "admit", state.admit)
    monkeypatch.setattr(credential_approval, "get_frontend_url", lambda: "https://fixture.invalid")
    monkeypatch.setattr(credential_connect, "_collect_evidence", connection_evidence.collect_evidence)
    credential_connect._class_index.cache_clear()
    state.dns = AsyncMock(return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))])
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", state.dns)

    def respond(request):
        state.requests.append(request)
        if getattr(state, 'transport_error', None):
            raise state.transport_error
        route = request.url.path.removeprefix("/api/")
        reply = state.replies.get((request.method, route))
        if reply is None and request.method == "GET":
            if route == "public/ats-api/token":reply=(200,{"success":True,"data":{"token":MINT}})
            elif route == "integration/assessments":reply=(200,page([assessment()]))
            elif route == "integration/user-assessments":reply=(200,{"success":True,"data":page([report()],int(request.url.params.get('page','1')))})
            elif route == "integration/user-assessments/"+APP:reply=(200,{"success":True,"data":report()})
            elif route == "integration/assessments/"+SLUG+"/candidates":reply=(200,{"success":True,"data":page([{"fullName":"Fixture candidate","status":"Scored","email":"private@example.test","rank":1,"questions":[{"answer":TOKEN}],"geoLocationDetection":True}],int(request.url.params['page']))})
            elif route == "integration/brands":reply=(200,{"success":True,"data":[{"uuid":FOLDER,"title":"Fixture brand","color":"#008000","logoUrl":TOKEN}]})
        assert reply is not None, (request.method, route)
        status, payload, *headers = reply
        response = httpx.Response(status, content=b"" if payload is None else json.dumps(payload).encode(), headers={"Content-Type": "application/json", **(headers[0] if headers else {})})
        if request.method == "GET" and state.after_read:
            callback, state.after_read = state.after_read, None
            callback()
        return response

    original = ssrf.guarded_async_client
    def client(**kwargs):
        state.constructors.append(kwargs)
        return original(**kwargs, transport=httpx.MockTransport(respond))
    monkeypatch.setattr(provider, "guarded_async_client", client)

    async def run(operation, args=None, *, saved=False, blob=None, workflow_id=None):
        from nodes.core.run_op import run_node_operation
        return await run_node_operation(node_type="automation-vervoe", operation=operation, arguments=args or {}, user_id=USER,
            pool=state.pool, organization_id=None, credential_id=CID if saved else None,
            credential_data=deepcopy(BLOB) if blob is None and not saved else blob, workflow_id=workflow_id)
    state.run = run
    yield state
    credential_connect._class_index.cache_clear()


async def test_actual_factory_schema_connect_and_bearer_wire(native):
    from nodes.core.registry import NodeFactory
    from nodes.core.credential_connect import shape_credential, validate_for_connect
    from nodes.vervoe_node import VervoeNode
    shaped, errors, resolved=shape_credential(FAMILY,BLOB)
    assert not errors and shaped==BLOB and resolved[0]=='automation-vervoe'
    assert NodeFactory.is_registered('automation-vervoe')
    assert len(VervoeNode.get_config_schema()['properties']['config']['discriminator']['mapping'])==11
    verdict=await validate_for_connect(credential_type=FAMILY,credential_data=BLOB,user_id=USER)
    assert verdict.ok and verdict.evidence.reachable is True and verdict.evidence.samples[0].label=='Fixture assessment'
    request=native.requests[-1]
    assert request.url.host=='api.vervoe.com' and request.url.path=='/api/integration/assessments' and not request.url.params
    assert request.headers['Authorization']=='Bearer '+TOKEN and len(native.requests)==1
    assert all(c['trust_env'] is False and c['follow_redirects'] is False for c in native.constructors)


@pytest.mark.parametrize('operation,arguments',[
    ('create_folder',{'confirm_folder_change':True}),
    ('rename_folder',{'confirm_folder_change':True,'folder_uuid':FOLDER}),
])
def test_actual_native_schema_and_factory_require_folder_name(native,operation,arguments):
    from nodes.core.base import ConfigValidationError
    from nodes.core.registry import NodeFactory
    from nodes.vervoe_node import VervoeNode
    schema=VervoeNode.get_config_schema()
    for definition in ('CreateFolder','RenameFolder'):
        assert 'name' in schema['$defs'][definition]['required']
        assert 'default' not in schema['$defs'][definition]['properties']['name']
    with pytest.raises(ConfigValidationError):
        NodeFactory.create_node('fixture','automation-vervoe',{'config':{'operation':operation,**arguments},'credentials':BLOB},user_id=USER)
    assert native.requests==[]


async def test_actual_api_pair_mints_once_ephemeral_token_and_keeps_pair_out_of_outputs(native):
    import base64
    from nodes.core.credential_connect import validate_for_connect
    verdict=await validate_for_connect(credential_type='vervoe_api_key',credential_data=PAIR,user_id=USER)
    assert verdict.ok and all(verdict.credential_data[k]==v for k,v in PAIR.items())
    assert [r.url.path for r in native.requests]==['/api/public/ats-api/token','/api/integration/assessments']
    assert native.requests[0].headers['Authorization']=='Basic '+base64.b64encode((PAIR['api_key']+':'+PAIR['secret_key']).encode()).decode()
    assert native.requests[1].headers['Authorization']=='Bearer '+MINT
    assert MINT not in json.dumps(verdict.credential_data)
    native.crypto.encrypt_credential.assert_not_called()


@pytest.mark.parametrize('tag',[None,'',7,[],{},'slack_oauth',' vervoe_bearer_token '])
def test_native_raw_family_before_inherited_union_reconciliation(native,tag):
    from nodes.vervoe_node import VervoeNode
    from nodes.core.registry import NodeFactory
    from nodes.core.base import ConfigValidationError
    data={'config':{'operation':'list_assessments'},'credentials':{**BLOB,'credential_type':tag}}
    assert VervoeNode.validate_config(data)['valid'] is False
    with pytest.raises(ConfigValidationError):NodeFactory.create_node('fixture','automation-vervoe',data,user_id=USER)
    assert native.requests==[]


async def test_actual_dispatcher_current_token_and_canonical_owner_fallback(native):
    native.blob['access_token']='current_vervoe_token'
    result=await native.run('list_assessments',saved=True)
    assert result['status']=='success' and native.requests[-1].headers['Authorization']=='Bearer current_vervoe_token'
    native.allowed={OWNER};native.row['owner_id']=OWNER
    result=await native.run('list_assessments',saved=True,workflow_id=WORKFLOW)
    assert result['status']=='success' and native.workflow_grant.await_count>=1
    native.workflow_grant.return_value=False;native.requests.clear()
    with pytest.raises(ValueError):await native.run('list_assessments',saved=True,workflow_id=WORKFLOW)
    assert native.requests==[]


async def test_actual_report_pages_parent_binding_and_private_projection(native):
    result=await native.run('list_applications',{'page':3,'sort':'completed','status':'complete','order':'desc'})
    assert result['status']=='success' and result['data']['current_page']==3
    assert dict(native.requests[-1].url.params)=={'page':'3','sort':'completed','status':'complete','order':'desc'}
    result=await native.run('get_application',{'assessment_slug':SLUG,'candidate_assessment_uuid':APP})
    assert result['status']=='success' and result['data']['candidateAssessmentUuid']==APP
    for private in (TOKEN,'score','candidateEmail','integrationCandidateCardUrl','plagiarismDetected'):
        assert private not in json.dumps(result)
    native.replies[('GET','integration/user-assessments/'+APP)]=(200,{'success':True,'data':report(assessmentSlug='other_assessment')})
    result=await native.run('get_application',{'assessment_slug':SLUG,'candidate_assessment_uuid':APP})
    assert result['status']=='error'


async def test_candidate_page_has_no_invented_identifier_or_scoring_proctoring_fields(native):
    result=await native.run('list_assessment_candidates',{'assessment_slug':SLUG,'page':2})
    assert result['status']=='success' and result['data']['items']==[{'fullName':'Fixture candidate','status':'Scored'}]
    assert native.requests[-1].url.path=='/api/integration/assessments/'+SLUG+'/candidates'
    assert dict(native.requests[-1].url.params)=={'page':'2'}
    assert not any(x in json.dumps(result) for x in ('rank','questions','email','geoLocation','uuid'))


async def test_folder_and_application_pickers_use_actual_native_loader(native):
    from nodes.core.run_op import run_node_lookup
    result=await run_node_lookup(node_type='automation-vervoe',field_name='folder_uuid',user_id=USER,credential_id=CID,pool=native.pool)
    assert result['options']==[{'value':FOLDER,'label':'Fixture folder'}] and result['next_page_token'] is None
    result=await run_node_lookup(node_type='automation-vervoe',field_name='candidate_assessment_uuid',user_id=USER,credential_id=CID,pool=native.pool,context={'assessment_slug':SLUG})
    assert result['options'][0]['value']==APP
    native.requests.clear()
    with pytest.raises(ValueError):await run_node_lookup(node_type='automation-vervoe',field_name='candidate_assessment_uuid',user_id=USER,credential_id=CID,pool=native.pool,context={})
    assert native.requests==[]
    observed=await native.run('list_assessment_folders')
    assert observed['data']=={'items':[{'uuid':FOLDER,'name':'Fixture folder'}],'observed_assessment_page':1,'complete_folder_inventory':False}
    brands=await native.run('list_brands')
    assert brands['data']['items']==[{'uuid':FOLDER,'title':'Fixture brand','color':'#008000'}]


async def test_actual_internal_folder_crud_and_204_absence_ambiguity(native):
    resource={'uuid':FOLDER,'name':'Fixture folder'}
    native.replies[('POST','integration/assessments/folders')]=(201,{'success':True,'data':resource})
    result=await native.run('create_folder',{'name':'Fixture folder','confirm_folder_change':True})
    assert result['status']=='success' and json.loads(native.requests[-1].content)=={'name':'Fixture folder'}
    native.replies[('PATCH','integration/assessments/folders/'+FOLDER)]=(200,{'success':True,'data':resource})
    result=await native.run('rename_folder',{'folder_uuid':FOLDER,'name':'Fixture folder','confirm_folder_change':True})
    assert result['status']=='success' and native.requests[-1].method=='PATCH'
    native.replies[('PATCH','integration/assessments/'+SLUG+'/folders/'+FOLDER+'/move')]=(200,{'success':True,'data':assessment()})
    result=await native.run('move_assessment_to_folder',{'folder_uuid':FOLDER,'assessment_slug':SLUG,'confirm_folder_change':True})
    assert result['status']=='success'
    native.replies[('DELETE','integration/assessments/'+SLUG+'/folders')]=(200,{'success':True,'data':assessment(auditionFolder='null')})
    result=await native.run('remove_assessment_from_folder',{'assessment_slug':SLUG,'confirm_folder_change':True})
    assert result['status']=='success' and result['data']['resource']['auditionFolder'] is None
    native.replies[('DELETE','integration/assessments/folders/'+FOLDER)]=(204,None)
    result=await native.run('delete_folder',{'folder_uuid':FOLDER,'confirm_folder_change':True})
    assert result['data']=={'uuid':FOLDER,'deletion_request_completed':True,'previously_existed':None,'verified_readback':None}
    native.replies[('DELETE','integration/assessments/folders/'+FOLDER)]=(204,{'success':True})
    assert (await native.run('delete_folder',{'folder_uuid':FOLDER,'confirm_folder_change':True}))['status']=='error'


@pytest.mark.parametrize('status',[201,202,204,301,400,401,403,404,429,503])
async def test_unexpected_read_status_no_retry_or_raw_error_leak(native,status):
    native.replies[('GET','integration/assessments')]=(status,{'message':TOKEN,'private':MINT},{'Retry-After':'42'})
    result=await native.run('list_assessments')
    assert result['status']=='error' and result['status_code']==status and result['retry_after']==42 and len(native.requests)==1
    assert TOKEN not in json.dumps(result) and MINT not in json.dumps(result)


@pytest.mark.parametrize('payload',[{'success':False,'items':[]},page([assessment(),assessment()]),page([assessment(name=TOKEN)]),{**page([assessment()]),'count':2}])
async def test_malformed_page_never_becomes_evidence(native,payload):
    from nodes.core.connection_evidence import collect_evidence
    native.replies[('GET','integration/assessments')]=(200,payload)
    evidence=await collect_evidence(node_type='automation-vervoe',credential_data=BLOB,user_id=USER)
    assert evidence.reachable is not True and TOKEN not in json.dumps(asdict(evidence))


@pytest.mark.parametrize('payload',[{'success':False,'data':{'token':MINT}},{'success':True,'data':{}},{'success':True,'data':{'token':'Bearer '+MINT}}])
async def test_bad_token_success_response_cannot_probe_or_leak(native,payload):
    from nodes.core.credential_connect import validate_for_connect
    native.replies[('GET','public/ats-api/token')]=(200,payload)
    verdict=await validate_for_connect(credential_type='vervoe_api_key',credential_data=PAIR,user_id=USER)
    assert verdict.ok and verdict.evidence.reachable is None
    assert [r.url.path for r in native.requests]==['/api/public/ats-api/token']


async def test_actual_transport_failure_is_unknown_and_does_not_leak_or_retry(native):
    from nodes.core.credential_connect import validate_for_connect
    native.transport_error=httpx.ConnectError('Synthetic transport error '+TOKEN)
    verdict=await validate_for_connect(credential_type=FAMILY,credential_data=BLOB,user_id=USER)
    assert verdict.ok and verdict.evidence.reachable is None and len(native.requests)==1
    assert TOKEN not in json.dumps(asdict(verdict.evidence))


async def test_pending_rejected_saved_key_admission_never_mints(native):
    native.blob=dict(PAIR);native.row['credential_type']='vervoe_api_key'
    for approval in [{'id':CID,'status':'pending'},{'id':CID,'status':'rejected'}]:
        native.approval=approval
        result = await native.run('list_assessments',saved=True)
        assert result['status']==('pending_approval' if approval['status']=='pending' else 'rejected')
        assert result['executed'] is False and result['approval_id']==CID
        assert native.requests==[]


@pytest.mark.parametrize('operation,args,route,fixture',[
    ('list_applications',{},'integration/user-assessments','applications'),
    ('get_application',{'assessment_slug':'assessment-slug','candidate_assessment_uuid':'cbb3e136-ef30-4452-955b-1835a79caa65'},'integration/user-assessments/cbb3e136-ef30-4452-955b-1835a79caa65','application'),
    ('list_assessment_candidates',{'assessment_slug':'assessment-slug','page':2},'integration/assessments/assessment-slug/candidates','candidates'),
    ('rename_folder',{'folder_uuid':'7c5b2adf-4bb2-4283-8e72-6d9a50952f66','name':'New folder name','confirm_folder_change':True},'integration/assessments/folders/7c5b2adf-4bb2-4283-8e72-6d9a50952f66','rename_folder'),
])
async def test_provider_authored_examples_parse_without_relaxing_validation(native,operation,args,route,fixture):
    from pathlib import Path
    payload=json.loads((Path(__file__).parent/'fixtures'/'vervoe'/(fixture+'.json')).read_text())
    method='PATCH' if operation=='rename_folder' else 'GET'
    native.replies[(method,route)]=(200,payload)
    result=await native.run(operation,args)
    assert result['status']=='success'
    assert native.requests[-1].url.path=='/api/'+route
    if operation=='list_assessment_candidates':assert dict(native.requests[-1].url.params)=={'page':'2'}
    assert not any(key in json.dumps(result) for key in ('scoreByFormat','candidateEmail','integrationCandidateCardUrl','questions','predictedOverallScore'))
