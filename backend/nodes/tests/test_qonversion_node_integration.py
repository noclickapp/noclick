"""Real credential create/update/public-provide and saved validation fixtures.

Without a supplied product witness, validity is unknown and no provider request occurs.
A successful exact product read proves reachability without an invented identity.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import HTTPException
import pytest
from nodes.tests.test_qonversion_node_mock import native,ensure_native_db_pool,USER,CID,FAMILY,BLOB,NOW,PRODUCT


@pytest.fixture
async def surfaces(native,monkeypatch):
    from repositories import credentials as repo
    from utils import credentials,credential_request_routes as public
    from wss.handlers import credentials_handler as handlers,workflow_handler
    monkeypatch.setattr(handlers,'get_encryption',lambda:native.crypto)
    monkeypatch.setattr(handlers,'get_user_org_context',AsyncMock(return_value=None))
    monkeypatch.setattr(workflow_handler,'get_user_org_context',AsyncMock(return_value=None))
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
    link={'id':CID,'requester_id':USER,'token':'synthetic-provide-link','credential_type':FAMILY,'status':'pending','expires_at':None,'provision_attempts':0,'target_email':None,'metadata':{},'requester_email':'fixture@example.test'}
    monkeypatch.setattr(public,'get_native_pool',lambda:SimpleNamespace(fetchrow=AsyncMock(return_value=link),execute=AsyncMock()))
    def close_background(coroutine,*,name):
        assert name=='credential-request-attempt-counter';coroutine.close()
    monkeypatch.setattr(public,'spawn',close_background)
    fulfill=AsyncMock(return_value={'success':True,'credential_id':CID});monkeypatch.setattr(public,'_store_and_fulfill',fulfill)
    return SimpleNamespace(handler=handler,send=send,public=public,create=create,update=update,fulfill=fulfill)


async def connect(surface,kind,blob):
    from wss.receiver.client_events import CredentialCreateRequest,CredentialUpdateRequest
    if kind=='provide':return await surface.public.provide_credential('synthetic-provide-link',surface.public.ProvideCredentialBody(credential_data=blob))
    request=(CredentialCreateRequest(request_id='fixture-connect',name='Fixture Qonversion',credential_type=FAMILY,credential_data=blob) if kind=='create' else CredentialUpdateRequest(request_id='fixture-connect',credential_id=CID,credential_data=blob))
    await surface.handler.get_events()[request.event_name]('fixture-sid',request)
    return surface.send.await_args.args[2].model_dump()['data']


@pytest.mark.parametrize('kind',['create','update','provide'])
async def test_actual_connect_preserves_key_without_witness_probe_or_false_identity(native,surfaces,kind):
    result=await connect(surfaces,kind,BLOB)
    assert result['success'] is True and result['verification']['reachable'] is None
    assert result['verification']['proves']=='reachability' and result['verification']['account_label'] is None
    assert result['verification']['samples']==[] and native.requests==[] and native.constructors==[]
    if kind=='create':
        assert surfaces.create.await_args.args[3]==FAMILY
        metadata=surfaces.create.await_args.args[6] or {};assert 'verified_as' not in metadata and 'verified_at' not in metadata
    elif kind=='update':assert surfaces.update.await_args.kwargs['new_data']['secret_key']==BLOB['secret_key']
    else:assert surfaces.fulfill.await_args.args[2]==FAMILY and surfaces.fulfill.await_args.args[3]['secret_key']==BLOB['secret_key']


@pytest.mark.parametrize('kind',['create','update','provide'])
async def test_actual_connect_exact_product_reachability_has_no_principal_label(native,surfaces,kind):
    result=await connect(surfaces,kind,{**BLOB,'witness_product_id':PRODUCT})
    assert result['success'] is True and result['verification']['reachable'] is True and result['verification']['proves']=='reachability'
    assert result['verification']['account_label'] is None and result['verification']['samples']==[]
    assert len(native.requests)==1 and native.requests[0].url.path=='/v4/products/'+PRODUCT
    if kind=='create':assert 'verified_as' not in (surfaces.create.await_args.args[6] or {})
    elif kind=='update':assert surfaces.update.await_args.kwargs['new_data']['witness_product_id']==PRODUCT
    else:assert surfaces.fulfill.await_args.args[3]['witness_product_id']==PRODUCT


@pytest.mark.parametrize('kind',['create','update','provide'])
@pytest.mark.parametrize('tag',['slack_oauth','',None])
async def test_actual_connect_bad_family_before_persistence(native,surfaces,kind,tag):
    if kind=='provide':
        with pytest.raises(HTTPException) as failure:await connect(surfaces,kind,{**BLOB,'credential_type':tag})
        assert failure.value.status_code==400
    else:
        result=await connect(surfaces,kind,{**BLOB,'credential_type':tag})
        assert result['success'] is False and 'credential_type' in result['field_errors']
    surfaces.create.assert_not_awaited();surfaces.update.assert_not_awaited();surfaces.fulfill.assert_not_awaited()
    native.crypto.encrypt_credential.assert_not_called();assert native.requests==[]


async def test_actual_saved_validation_keeps_unknown_without_witness(native,surfaces):
    from wss.receiver.client_events import CredentialValidateAccessRequest
    await surfaces.handler.validate_access('fixture-sid',CredentialValidateAccessRequest(request_id='fixture-check',credential_id=CID,node_type='automation-qonversion'))
    result=surfaces.send.await_args.args[2].model_dump()['data']
    assert result['valid'] is None and 'name' not in result and native.requests==[] and native.constructors==[]


async def test_actual_saved_validation_exact_witness_access_and_changed_authority(native,surfaces):
    from wss.receiver.client_events import CredentialValidateAccessRequest
    native.blob['witness_product_id']=PRODUCT
    request=CredentialValidateAccessRequest(request_id='fixture-witness',credential_id=CID,node_type='automation-qonversion')
    await surfaces.handler.validate_access('fixture-sid',request)
    assert surfaces.send.await_args.args[2].model_dump()['data']['valid'] is True
    native.after_read=lambda:native.row.update(token_version=8)
    await surfaces.handler.validate_access('fixture-sid',request)
    assert surfaces.send.await_args.args[2].model_dump()['data']['valid'] is False


@pytest.mark.parametrize('failure',['null_type','foreign_type','revoked','denied'])
async def test_actual_saved_validation_current_family_access_denial(native,surfaces,failure):
    from wss.receiver.client_events import CredentialValidateAccessRequest
    if failure=='denied':native.allowed.clear()
    elif failure=='null_type':native.row['credential_type']=None
    elif failure=='foreign_type':native.row['credential_type']='slack_oauth'
    else:native.row['revoked_at']=NOW
    await surfaces.handler.validate_access('fixture-sid',CredentialValidateAccessRequest(request_id='fixture-check',credential_id=CID,node_type='automation-qonversion'))
    assert surfaces.send.await_args.args[2].model_dump()['data']['valid'] is False
    native.crypto.decrypt_credential.assert_not_called();assert native.requests==[]
