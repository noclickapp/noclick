"""Real Act credential create/update/provide, post-connect and stored socket picker."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import HTTPException
from pydantic import ValidationError
import pytest

from nodes.tests.test_act_crm_node_mock import native, ensure_native_db_pool, USER, CID, FAMILY, BLOB, NOW


@pytest.fixture
async def surfaces(native, monkeypatch):
    from repositories import credentials as repo
    from utils import credentials, credential_request_routes as public
    from wss.handlers import credentials_handler as handlers, workflow_handler
    monkeypatch.setattr(handlers,'get_encryption',lambda:native.crypto)
    monkeypatch.setattr(handlers,'get_user_org_context',AsyncMock(return_value=None))
    monkeypatch.setattr(workflow_handler,'get_user_org_context',AsyncMock(return_value=None))
    monkeypatch.setattr(workflow_handler,'get_encryption',lambda:native.crypto)
    native.crypto.encrypt_credential.return_value=b'synthetic-new-blob'
    row={**native.row,'credential_type':FAMILY};saved=SimpleNamespace(**row)
    create,update=AsyncMock(return_value=(row,None)),AsyncMock(return_value=True)
    monkeypatch.setattr(repo,'create_credential_with_limit_check',create)
    monkeypatch.setattr(credentials,'update_credential_data',update)
    monkeypatch.setattr(repo.CredentialsRepo,'has_edit_permission',AsyncMock(return_value=True))
    monkeypatch.setattr(repo.CredentialsRepo,'fetch_with_access',AsyncMock(return_value=saved))
    monkeypatch.setattr(repo.CredentialsRepo,'update_metadata_or_fetch',AsyncMock(return_value=saved))
    send=AsyncMock();monkeypatch.setattr(handlers,'send_event',send)
    handler=handlers.CredentialsHandler(SimpleNamespace(get_session=AsyncMock(return_value={'user_id':USER})))
    handler.get_pool=AsyncMock(return_value=native.pool)
    link={'id':CID,'requester_id':USER,'token':'synthetic-provide-link','credential_type':FAMILY,'status':'pending',
        'expires_at':None,'provision_attempts':0,'target_email':None,'metadata':{},'requester_email':'fixture@example.test'}
    monkeypatch.setattr(public,'get_native_pool',lambda:SimpleNamespace(fetchrow=AsyncMock(return_value=link),execute=AsyncMock()))
    def close_background(coroutine,*,name):
        assert name=='credential-request-attempt-counter';coroutine.close()
    monkeypatch.setattr(public,'spawn',close_background)
    fulfill=AsyncMock(return_value={'success':True,'credential_id':CID})
    monkeypatch.setattr(public,'_store_and_fulfill',fulfill)
    return SimpleNamespace(handler=handler,send=send,public=public,create=create,update=update,fulfill=fulfill)


async def connect(surface,kind,blob):
    from wss.receiver.client_events import CredentialCreateRequest,CredentialUpdateRequest
    if kind=='provide':return await surface.public.provide_credential('synthetic-provide-link',surface.public.ProvideCredentialBody(credential_data=blob))
    request=(CredentialCreateRequest(request_id='fixture-connect',name='Fixture Act',credential_type=FAMILY,credential_data=blob)
        if kind=='create' else CredentialUpdateRequest(request_id='fixture-connect',credential_id=CID,credential_data=blob))
    await surface.handler.get_events()[request.event_name]('fixture-sid',request)
    return surface.send.await_args.args[2].model_dump()['data']


@pytest.mark.parametrize('kind',['create','update','provide'])
async def test_actual_connect_surfaces_keep_instance_database_token_and_protected_sample(native,surfaces,kind):
    result=await connect(surfaces,kind,BLOB)
    assert result['success'] is True and result['verification']['proves']=='account'
    assert result['verification']['samples'][0]['label']=='Fixture company'
    assert all(r.url.path=='/tenant-api/act.web.api/api/companies' and r.headers['Act-Database-Name']==BLOB['database_name'] for r in native.requests)
    if kind=='create':assert surfaces.create.await_args.args[3]==FAMILY and surfaces.create.await_args.args[6]['verified_with']=='Fixture company'
    elif kind=='update':assert all(surfaces.update.await_args.kwargs['new_data'][k]==v for k,v in BLOB.items())
    else:assert surfaces.fulfill.await_args.args[2]==FAMILY and all(surfaces.fulfill.await_args.args[3][k]==v for k,v in BLOB.items())


@pytest.mark.parametrize('kind',['create','update','provide'])
@pytest.mark.parametrize('tag',['slack_oauth','',None])
async def test_actual_connect_family_refusal_before_probe_and_persistence(native,surfaces,kind,tag):
    blob={**BLOB,'credential_type':tag}
    if kind=='provide':
        if tag is None:
            with pytest.raises(ValidationError) as failure:await connect(surfaces,kind,blob)
            assert failure.value.errors()[0]['loc'] == ('credential_data', 'credential_type')
        else:
            with pytest.raises(HTTPException) as failure:await connect(surfaces,kind,blob)
            assert failure.value.status_code==400
    else:
        result=await connect(surfaces,kind,blob)
        assert result['success'] is False and 'credential_type' in result['field_errors']
    assert native.requests==[]
    surfaces.create.assert_not_awaited();surfaces.update.assert_not_awaited();surfaces.fulfill.assert_not_awaited()
    native.crypto.encrypt_credential.assert_not_called()


@pytest.mark.parametrize('status',[401,403,429,503])
async def test_actual_saved_probe_failure_stays_unknown(native,surfaces,status):
    from wss.receiver.client_events import CredentialValidateAccessRequest
    native.replies[('GET','companies')]=(status,{'private':BLOB['access_token']})
    await surfaces.handler.validate_access('fixture-sid',CredentialValidateAccessRequest(request_id='fixture-check',credential_id=CID,node_type='automation-act-crm'))
    result=surfaces.send.await_args.args[2].model_dump()['data']
    assert result['valid'] is (False if status in {401, 403} else None) and 'name' not in result and len(native.requests)==1




@pytest.mark.parametrize('allowed', [True, False])
async def test_actual_socket_picker_staging_access_and_trusted_actor(native, surfaces, monkeypatch, allowed):
    from nodes.act_crm_node import ActCRMNode
    from wss.handlers import workflow_handler
    from wss.receiver.client_events import WorkflowNodeLoadOptionsRequest
    native.blob['credential_type'] = 'slack_oauth'
    if not allowed:
        native.allowed.clear()
    original = ActCRMNode.load_field_options
    loader = AsyncMock(side_effect=original)
    monkeypatch.setattr(ActCRMNode, 'load_field_options', loader)
    send = AsyncMock()
    monkeypatch.setattr(workflow_handler, 'send_event', send)
    handler = workflow_handler.WorkflowHandler.__new__(workflow_handler.WorkflowHandler)
    handler.sio = SimpleNamespace(get_session=AsyncMock(return_value={'user_id': USER}))
    handler.get_pool = AsyncMock(return_value=native.pool)
    await handler.load_node_options('fixture-sid', WorkflowNodeLoadOptionsRequest(
        request_id='fixture-picker', node_type='automation-act-crm', field_name='company_id',
        credential_id=CID, context={'_user_id': 'forged-actor'}))
    result = send.await_args.args[2].model_dump()['data']
    if allowed:
        assert result['success'] is True
        assert result['options'] == [{'value': 'company-42', 'label': 'Fixture company', 'metadata': None}]
        assert loader.await_args.kwargs['context']['_user_id'] == USER
        assert loader.await_args.kwargs['credential_data']['credential_type'] == FAMILY
    else:
        assert result['success'] is False and native.requests == []
        loader.assert_not_awaited()
