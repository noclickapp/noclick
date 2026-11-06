"""Real credential create/update/public-provide and saved validation fixtures.

Without a supplied product witness, validity is unknown and no provider request occurs.
A successful exact product read proves reachability without an invented identity.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import HTTPException
from pydantic import ValidationError
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
@pytest.mark.parametrize('tag',['slack_oauth','',None])
async def test_actual_connect_bad_family_before_persistence(native,surfaces,kind,tag):
    if kind=='provide':
        if tag is None:
            with pytest.raises(ValidationError) as failure:await connect(surfaces,kind,{**BLOB,'credential_type':tag})
            assert failure.value.errors()[0]['loc']==('credential_data','credential_type')
        else:
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
