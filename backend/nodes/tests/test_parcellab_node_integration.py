"""Real parcelLab create/update/provide, post-connect and socket picker seams.

Only storage, encryption, session and HTTP boundaries use synthetic fixtures.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import HTTPException
from pydantic import ValidationError
import pytest

from nodes.tests.test_parcellab_node_mock import (
    native, ensure_native_db_pool, USER, CID, FAMILY, TOKEN, NOW, ORDER,
)


@pytest.fixture
def surfaces(native, monkeypatch):
    from repositories import credentials as repo
    from utils import credentials, credential_request_routes as public
    from wss.handlers import credentials_handler as handlers, workflow_handler

    monkeypatch.setattr(handlers, "get_encryption", lambda: native.crypto)
    monkeypatch.setattr(handlers, "get_user_org_context", AsyncMock(return_value=None))
    monkeypatch.setattr(workflow_handler, "get_user_org_context", AsyncMock(return_value=None))
    native.crypto.encrypt_credential.return_value = b"synthetic-new-blob"
    row = {**native.row, "credential_type": FAMILY}
    saved = SimpleNamespace(**row)
    create, update = AsyncMock(return_value=(row, None)), AsyncMock(return_value=True)
    monkeypatch.setattr(repo, "create_credential_with_limit_check", create)
    monkeypatch.setattr(credentials, "update_credential_data", update)
    monkeypatch.setattr(repo.CredentialsRepo, "has_edit_permission", AsyncMock(return_value=True))
    monkeypatch.setattr(repo.CredentialsRepo, "fetch_with_access", AsyncMock(return_value=saved))
    monkeypatch.setattr(repo.CredentialsRepo, "update_metadata_or_fetch", AsyncMock(return_value=saved))
    send = AsyncMock()
    monkeypatch.setattr(handlers, "send_event", send)
    handler = handlers.CredentialsHandler(SimpleNamespace(get_session=AsyncMock(return_value={"user_id": USER})))
    handler.get_pool = AsyncMock(return_value=native.pool)
    request_row = {"id": CID, "requester_id": USER, "token": "synthetic-provide-link", "credential_type": FAMILY,
        "status": "pending", "expires_at": None, "provision_attempts": 0, "target_email": None,
        "metadata": {}, "requester_email": "fixture@example.test"}
    monkeypatch.setattr(public, "get_native_pool", lambda: SimpleNamespace(
        fetchrow=AsyncMock(return_value=request_row), execute=AsyncMock()))

    def close_background(coroutine, *, name):
        assert name == "credential-request-attempt-counter"
        coroutine.close()

    monkeypatch.setattr(public, "spawn", close_background)
    fulfill = AsyncMock(return_value={"success": True, "credential_id": CID})
    monkeypatch.setattr(public, "_store_and_fulfill", fulfill)
    return SimpleNamespace(handler=handler, send=send, public=public, create=create, update=update, fulfill=fulfill)


async def connect(surface, kind, blob):
    from wss.receiver.client_events import CredentialCreateRequest, CredentialUpdateRequest
    if kind == "provide":
        return await surface.public.provide_credential("synthetic-provide-link",
            surface.public.ProvideCredentialBody(credential_data=blob))
    request = (CredentialCreateRequest(request_id="fixture-connect", name="Fixture token",
        credential_type=FAMILY, credential_data=blob) if kind == "create" else
        CredentialUpdateRequest(request_id="fixture-connect", credential_id=CID, credential_data=blob))
    await surface.handler.get_events()[request.event_name]("fixture-sid", request)
    return surface.send.await_args.args[2].model_dump()["data"]


@pytest.mark.parametrize("kind", ["create", "update", "provide"])
async def test_actual_connect_surfaces_preserve_encoded_token_and_owned_order_sample(native, surfaces, kind):
    result = await connect(surfaces, kind, {"api_token": TOKEN})
    assert result["success"] is True and result["verification"]["proves"] == "account"
    assert result["verification"]["account_label"] is None
    assert result["verification"]["samples"][0]["label"] == "fixture-order-42"
    assert all(r.url.path == "/v4/track/orders/" and not r.url.params for r in native.requests)
    assert all(r.headers["Authorization"] == "Parcellab-API-Token " + TOKEN for r in native.requests)
    if kind == "create":
        assert surfaces.create.await_args.args[3] == FAMILY
        assert "verified_as" not in surfaces.create.await_args.args[6]
    elif kind == "update":
        assert surfaces.update.await_args.kwargs["new_data"]["api_token"] == TOKEN
        assert "verified_as" not in surfaces.update.await_args.kwargs["metadata_updates"]
    else:
        assert surfaces.fulfill.await_args.args[2] == FAMILY
        assert surfaces.fulfill.await_args.args[3]["api_token"] == TOKEN
        assert "verified_as" not in surfaces.fulfill.await_args.args[5]


@pytest.mark.parametrize("kind", ["create", "update", "provide"])
@pytest.mark.parametrize("tag", ["slack_oauth", "", None])
async def test_actual_connect_refuses_foreign_supplied_family_before_probe_or_persist(native, surfaces, kind, tag):
    blob = {"api_token": TOKEN, "credential_type": tag}
    if kind == "provide":
        with pytest.raises(ValidationError if tag is None else HTTPException) as failure:
            await connect(surfaces, kind, blob)
        if tag is None:
            assert failure.value.errors()[0]["loc"] == ("credential_data", "credential_type")
        else:
            assert failure.value.status_code == 400
    else:
        result = await connect(surfaces, kind, blob)
        assert result["success"] is False and "credential_type" in result["field_errors"]
    assert native.requests == []
    surfaces.create.assert_not_awaited()
    surfaces.update.assert_not_awaited()
    surfaces.fulfill.assert_not_awaited()
    native.crypto.encrypt_credential.assert_not_called()


@pytest.mark.parametrize("status", [401, 403, 429, 503])
async def test_actual_postconnect_uses_staging_refusal_contract(native, surfaces, status):
    from wss.receiver.client_events import CredentialValidateAccessRequest
    native.replies[("GET", "/v4/track/orders/")] = (status, {"detail": TOKEN})
    await surfaces.handler.validate_access("fixture-sid", CredentialValidateAccessRequest(
        request_id="fixture-check", credential_id=CID, node_type="automation-parcellab"))
    result = surfaces.send.await_args.args[2].model_dump()["data"]
    assert result["valid"] is (False if status in {401, 403} else None)
    assert "name" not in result and len(native.requests) == 1


async def test_actual_postconnect_confirms_read(native, surfaces):
    from wss.receiver.client_events import CredentialValidateAccessRequest
    request = CredentialValidateAccessRequest(request_id="fixture-check", credential_id=CID, node_type="automation-parcellab")
    await surfaces.handler.validate_access("fixture-sid", request)
    assert surfaces.send.await_args.args[2].model_dump()["data"] == {"valid": True}
async def test_actual_socket_picker_loads_current_row(native, surfaces, monkeypatch):
    from wss.handlers import workflow_handler
    from wss.receiver.client_events import WorkflowNodeLoadOptionsRequest
    monkeypatch.setattr(workflow_handler, "get_encryption", lambda: native.crypto)
    send = AsyncMock()
    monkeypatch.setattr(workflow_handler, "send_event", send)
    handler = workflow_handler.WorkflowHandler.__new__(workflow_handler.WorkflowHandler)
    handler.sio = SimpleNamespace(get_session=AsyncMock(return_value={"user_id": USER}))
    handler.get_pool = AsyncMock(return_value=native.pool)
    await handler.load_node_options("fixture-sid", WorkflowNodeLoadOptionsRequest(request_id="fixture-picker",
        node_type="automation-parcellab", field_name="order_id", credential_id=CID,
        context={"_user_id": "forged-actor"}))
    result = send.await_args.args[2].model_dump()["data"]
    assert result["success"] is True
    assert result["options"] == [{"value": ORDER, "label": "fixture-order-42", "metadata": None}]
    assert [r.url.path for r in native.requests] == ["/v4/track/orders/"]
    assert len(native.sql) >= 3
