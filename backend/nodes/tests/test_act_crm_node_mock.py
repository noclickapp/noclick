"""Actual Act native factory/transport/access seams; synthetic external boundaries only."""
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
TOKEN = "synthetic.header.signature"
FAMILY = "act_crm_jwt"
BASE = "https://crm.example.com/tenant-api/act.web.api"
BLOB = {"instance_url": BASE, "database_name": "Fixture database", "access_token": TOKEN}
NOW = datetime(2026, 10, 6, tzinfo=timezone.utc)


@pytest.fixture
def ensure_native_db_pool():
    yield


def record(kind, **changes):
    row = {"id": kind + "-42", "created": "2026-10-06T00:00:00Z", "customFields": {"token": TOKEN}, "emailAddress": "private@example.test", "attachment": {"url": "private URL"}}
    row.update({"contact": {"fullName": "Fixture contact", "companyID": "company-42"}, "company": {"name": "Fixture company"},
        "group": {"name": "Fixture group"}, "opportunity": {"name": "Fixture opportunity", "status": "Open", "weightedTotal": 123.0},
        "activity": {"subject": "Fixture activity", "contacts": [{"id": "contact-42"}], "details": TOKEN},
        "note": {"contacts": [{"id": "contact-42"}], "displayDate": "2026-10-06T00:00:00Z", "noteText": TOKEN}}[kind])
    return {**row, **changes}


@pytest.fixture
async def native(monkeypatch):
    from nodes import act_crm_node as provider
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
        route = request.url.path.removeprefix("/tenant-api/act.web.api/api/")
        reply = state.replies.get((request.method, route))
        if reply is None and request.method == "GET":
            lookup = {v: k for k, v in provider.RESOURCES.items()}
            if route in lookup:
                reply = (200, [record(lookup[route])])
            elif route.split('/')[0] in lookup and len(route.split('/')) == 2:
                reply = (200, record(lookup[route.split('/')[0]]))
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
        return await run_node_operation(node_type="automation-act-crm", operation=operation, arguments=args or {}, user_id=USER,
            pool=state.pool, organization_id=None, credential_id=CID if saved else None,
            credential_data=deepcopy(BLOB) if blob is None and not saved else blob, workflow_id=workflow_id)
    state.run = run
    yield state
    credential_connect._class_index.cache_clear()


async def test_actual_factory_schema_connect_and_tenant_headers(native):
    from nodes.core.credential_connect import shape_credential, validate_for_connect
    from nodes.core.registry import NodeFactory
    from nodes.act_crm_node import ActCRMNode
    shaped, errors, resolved = shape_credential(FAMILY, BLOB)
    assert not errors and shaped == BLOB and resolved[0] == "automation-act-crm"
    assert NodeFactory.is_registered("automation-act-crm")
    assert len(ActCRMNode.get_config_schema()["properties"]["config"]["discriminator"]["mapping"]) == 31
    verdict = await validate_for_connect(credential_type=FAMILY, credential_data=BLOB, user_id=USER)
    assert verdict.ok and ActCRMNode.connection_evidence.proves == "account" and verdict.evidence.samples[0].label == "Fixture company"
    request = native.requests[-1]
    assert request.url.path == "/tenant-api/act.web.api/api/companies" and request.url.host == "crm.example.com"
    assert dict(request.url.params) == {"$top": "3", "$skip": "0"}
    assert request.headers['Authorization'] == 'Bearer ' + TOKEN and request.headers['Act-Database-Name'] == BLOB['database_name']
    assert all(c['trust_env'] is False and c['follow_redirects'] is False for c in native.constructors)
    output = await native.run('get_contact', {'contact_id': 'contact-42'})
    assert TOKEN not in json.dumps(output) and 'private' not in json.dumps(output)


@pytest.mark.parametrize('url', ['http://crm.example.com/act.web.api','https://127.0.0.1/act.web.api','https://localhost/act.web.api','https://crm.example.com/act.web.api/api','https://crm.example.com/a/../act.web.api','https://user:pass@crm.example.com/act.web.api','https://crm.example.com/act.web.api?token=secret','https://crm.example.com/%2e/act.web.api'])
async def test_invalid_base_before_probe(native, url):
    from nodes.core.credential_connect import validate_for_connect
    verdict = await validate_for_connect(credential_type=FAMILY, credential_data={**BLOB,'instance_url':url},user_id=USER)
    assert not verdict.ok and verdict.field_errors and native.requests == [] and native.dns.await_count == 0


async def test_staging_public_guard_blocks_private_dns(native, monkeypatch):
    monkeypatch.delenv('OUTBOUND_ALLOW_PRIVATE_IPS', raising=False)
    native.dns.return_value = [(socket.AF_INET,socket.SOCK_STREAM,6,'',('127.0.0.1',443))]
    result = await native.run('list_companies')
    assert result['status'] == 'error' and 'public HTTPS' in result['error'] and native.requests == []


@pytest.mark.parametrize('tag',[None,'',7,'slack_oauth',' act_crm_jwt '])
def test_raw_family_precedes_inherited_reconciliation(native,tag):
    from nodes.act_crm_node import ActCRMNode
    from nodes.core.registry import NodeFactory
    from nodes.core.base import ConfigValidationError
    raw={'config':{'operation':'list_companies'},'credentials':{**BLOB,'credential_type':tag}}
    assert ActCRMNode.validate_config(raw)['valid'] is False
    with pytest.raises(ConfigValidationError):NodeFactory.create_node('fixture','automation-act-crm',raw,user_id=USER)
    assert native.requests == []




async def test_real_dispatcher_uses_current_row_and_canonical_positive_owner_gate(native):
    native.blob['access_token']='current.header.signature'
    output=await native.run('list_companies',saved=True)
    assert output['status']=='success' and native.requests[-1].headers['Authorization']=='Bearer current.header.signature'
    native.allowed={OWNER};native.row['owner_id']=OWNER
    output=await native.run('list_companies',saved=True,workflow_id=WORKFLOW)
    assert output['status']=='success' and native.workflow_grant.await_count>=1
    native.workflow_grant.return_value=False;native.requests.clear()
    with pytest.raises(ValueError):await native.run('list_companies',saved=True,workflow_id=WORKFLOW)
    assert native.requests==[]




@pytest.mark.parametrize('kind,resource,field',[('contact','contacts','full_name'),('company','companies','name'),('group','groups','name'),('opportunity','opportunities','name')])
async def test_actual_crud_status_body_projection_and_empty_delete(native,kind,resource,field):
    native.replies[('POST',resource)]=(201,record(kind))
    result=await native.run('create_'+kind,{field:'Created record','confirm_record_change':True})
    assert result['status']=='success' and result['data']['resource']['id']==kind+'-42'
    body=json.loads(native.requests[-1].content)
    assert body['fullName' if kind=='contact' else 'name']=='Created record'
    assert 'customFields' not in body and 'recordOwner' not in body
    if kind=='opportunity':assert body['status']=='Open'
    native.replies[('PATCH',resource+'/'+kind+'-42')]=(200,record(kind))
    result=await native.run('update_'+kind,{kind+'_id':kind+'-42',field:'Changed record','confirm_record_change':True})
    assert result['status']=='success' and native.requests[-1].method=='PATCH'
    native.replies[('DELETE',resource+'/'+kind+'-42')]=(204,None)
    result=await native.run('delete_'+kind,{kind+'_id':kind+'-42','confirm_record_change':True})
    assert result['data']=={'id':kind+'-42','deletion_request_completed':True,'verified_readback':None}


async def test_note_text_is_write_only_and_bound_to_contact(native):
    native.replies[('POST','notes')]=(201,record('note'))
    result=await native.run('create_note',{'contact_id':'contact-42','note_text':'Plain fixture note','confirm_record_change':True})
    assert result['status']=='success' and 'noteText' not in result['data']['resource']
    assert dict(native.requests[-1].url.params)=={'format':'text'}
    assert json.loads(native.requests[-1].content)=={'noteText':'Plain fixture note','contacts':[{'id':'contact-42'}],'isPrivate':True}
    native.replies[('GET','notes/note-42')]=(200,record('note',contacts=[{'id':'different-contact'}]))
    native.requests.clear()
    result=await native.run('delete_note',{'contact_id':'contact-42','note_id':'note-42','confirm_record_change':True})
    assert result['status']=='error' and len(native.requests)==1 and native.requests[0].method=='GET'


async def test_linked_notes_bound_page_and_picker(native):
    from nodes.act_crm_node import ActCRMNode
    native.replies[('GET','contacts/contact-42/notes')]=(200,[record('note')])
    result=await native.run('list_contact_notes',{'contact_id':'contact-42','top':2,'skip':10})
    assert result['data']['requested_skip']==10 and result['data']['has_more'] is None
    assert dict(native.requests[-1].url.params)=={'$top':'2','$skip':'10'}
    result=await ActCRMNode.load_field_options('note_id',BLOB,{'contact_id':'contact-42'})
    assert result['options'][0]['value']=='note-42' and result['next_page_token'] is None
    native.requests.clear()
    with pytest.raises(ValueError):await ActCRMNode.load_field_options('note_id',BLOB,{})
    assert native.requests==[]


async def test_opportunity_notes_use_documented_plural_and_enforce_binding(native):
    route = 'opportunities/opportunity-42/notes'
    native.replies[('GET', route)] = (200, [record('note', opportunities=[{'id': 'opportunity-42'}])])
    result = await native.run('list_opportunity_notes', {'opportunity_id': 'opportunity-42'})
    assert result['status'] == 'success'
    assert result['data']['items'][0]['opportunities'] == [{'id': 'opportunity-42'}]
    assert native.requests[-1].url.path.endswith('/api/' + route)
    native.replies[('GET', route)] = (200, [record('note', opportunities=[{'id': 'different-opportunity'}])])
    result = await native.run('list_opportunity_notes', {'opportunity_id': 'opportunity-42'})
    assert result['status'] == 'error' and 'parent record binding' in result['error']


@pytest.mark.parametrize('status',[201,202,204,301,400,401,403,404,429,503])
async def test_unexpected_read_status_safe_no_retry(native,status):
    native.replies[('GET','companies')]=(status,{'message':TOKEN,'exception':'private error'},{'Retry-After':'42'})
    result=await native.run('list_companies')
    assert result['status']=='error' and result['status_code']==status and result['retry_after']==42
    assert TOKEN not in json.dumps(result) and 'private' not in json.dumps(result) and len(native.requests)==1


@pytest.mark.parametrize('payload',[{'value':[record('company')]},[record('company'),record('company')],[{'id':'company-42','name':TOKEN}]])
async def test_actual_malformed_page_never_becomes_connection_proof(native,payload):
    from nodes.core.connection_evidence import collect_evidence
    native.replies[('GET','companies')]=(200,payload)
    evidence=await collect_evidence(node_type='automation-act-crm',credential_data=BLOB,user_id=USER)
    assert evidence.reachable is not True and TOKEN not in json.dumps(asdict(evidence))


async def test_pending_and_rejected_actual_operation_admission_never_probes(native):
    for status in ['pending', 'rejected']:
        approval = {'id': CID, 'status': status}
        native.approval=approval
        result=await native.run('list_companies',saved=True)
        assert result['status'] == ('pending_approval' if status == 'pending' else 'rejected')
        assert result['approval_id'] == CID and result['executed'] is False
        assert result['_halt_downstream'] is True and native.requests == []


@pytest.mark.parametrize("change", [{"credential_type": None}, {"credential_type": "slack_oauth"}, {"revoked_at": NOW}])
async def test_saved_act_crm_connection_refuses_wrong_family_or_revocation(native, change):
    from nodes.act_crm_node import freshen
    native.row.update(change)
    with pytest.raises(ValueError):
        await freshen(BLOB, user_id=USER, pool=native.pool, credential_id=CID)
    assert native.requests == []


async def test_saved_act_crm_connection_requires_authenticated_actor(native):
    from nodes.act_crm_node import freshen
    with pytest.raises(ValueError, match="authenticated actor"):
        await freshen(BLOB, pool=native.pool, credential_id=CID)
    native.crypto.decrypt_credential.assert_not_called()
