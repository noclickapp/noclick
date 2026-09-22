"""The phone sign-in routes: prepare answers the same for any valid number
and refuses a malformed one; confirmed needs the new session's token and
binds through the service."""

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from utils import phone_auth_routes
from utils.phone_identity import PhoneLinkError
from utils.supabase_admin import SupabaseAdminError

USER = "11111111-1111-1111-1111-111111111111"


@pytest.fixture
def client(monkeypatch):
    service = AsyncMock()
    monkeypatch.setattr(phone_auth_routes, "default_service", lambda: service)
    monkeypatch.setattr(phone_auth_routes, "verify_token", AsyncMock(return_value={"sub": USER}))
    app = FastAPI()
    app.include_router(phone_auth_routes.router)
    with TestClient(app) as c:
        c.service = service
        yield c


def test_prepare_passes_the_number_and_reveals_nothing(client):
    client.service.prepare_sign_in.return_value = "+15550100001"
    assert client.post("/api/auth/phone/prepare", json={"phone": "+1 555 010 0001"}).json() == {"phone": "+15550100001"}
    client.service.prepare_sign_in.assert_awaited_once_with("+1 555 010 0001")

    client.service.prepare_sign_in.side_effect = PhoneLinkError("invalid_number")
    response = client.post("/api/auth/phone/prepare", json={"phone": "5550100001"})
    assert response.status_code == 400 and response.json()["detail"]["kind"] == "invalid_number"
    client.service.prepare_sign_in.side_effect = SupabaseAdminError("down", status_code=500)
    assert client.post("/api/auth/phone/prepare", json={"phone": "+15550100001"}).status_code == 503
    assert client.post("/api/auth/phone/prepare", json={"phone": "+1", "extra": 1}).status_code == 422


def test_confirmed_binds_for_the_signed_in_account_only(client, monkeypatch):
    client.service.bind_signed_in.return_value = "+15550100001"
    assert client.post("/api/auth/phone/confirmed").status_code == 401
    response = client.post("/api/auth/phone/confirmed", headers={"Authorization": "Bearer tok"})
    assert response.json() == {"phone": "+15550100001"}
    client.service.bind_signed_in.assert_awaited_once_with(USER)
    monkeypatch.setattr(phone_auth_routes, "verify_token", AsyncMock(side_effect=ValueError("expired")))
    assert client.post("/api/auth/phone/confirmed", headers={"Authorization": "Bearer tok"}).status_code == 401
