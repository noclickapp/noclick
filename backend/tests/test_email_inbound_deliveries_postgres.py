"""The email relay delivers each message (its requestId) until /email/inbound answers, so the route receives a
delivery once however often it arrives, against real Postgres and the real route: a retry of a received message
fires nothing, a retry while it is still being received is told to come back, a delivery that failed or was
refused leaves nothing behind, and a claim whose handler died is taken over after its lease."""

import base64
import json
import uuid
from email.message import EmailMessage
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from repositories.email_deliveries import EmailDeliveryRepo
from utils import email_reservation_manager, email_routes

pytestmark = pytest.mark.asyncio

DOMAIN = "mail.deliveries.example.test"
SECRET = "relay-secret"


@pytest.fixture
async def inbound(postgres_db, postgres_container, monkeypatch):
    """The database and the inbound route; yields (pool, owner id, client)."""
    from tests.fixtures.postgres_fixtures import asyncpg
    from utils.database_pool import setup_asyncpg_codecs

    monkeypatch.delenv("INBOUND_EMAIL_DOMAIN", raising=False)
    monkeypatch.delenv("NOCLICK_LOCAL", raising=False)
    monkeypatch.setattr(email_reservation_manager, "_platform_mail", ((), None))
    email_reservation_manager.register_mail_domains(DOMAIN)
    monkeypatch.setenv("EMAIL_RELAY_SECRET", SECRET)
    pool = await asyncpg.create_pool(
        host=postgres_container.get_container_host_ip(), port=postgres_container.get_exposed_port(5432),
        user=postgres_container.username, password=postgres_container.password, database=postgres_container.dbname,
        min_size=1, max_size=4, init=setup_asyncpg_codecs,
    )
    monkeypatch.setattr(email_routes, "get_native_pool", lambda: pool)
    owner = str(await pool.fetchval(
        "INSERT INTO auth.users (email, raw_user_meta_data) VALUES ($1, '{}'::jsonb) RETURNING id",
        f"{uuid.uuid4().hex[:8]}@example.com"))
    app = FastAPI()
    app.include_router(email_routes.router)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield pool, owner, client
    finally:
        await pool.close()


async def _listening(pool, owner) -> str:
    """An email trigger's address; returns its name."""
    graph = {"nodes": [{"id": "mail", "type": "trigger-email", "config": {}}], "edges": []}
    workflow_id = await pool.fetchval(
        "INSERT INTO workflows (owner_id, name, workflow) VALUES ($1::uuid, 'Orders', $2) RETURNING id", owner, graph)
    name = f"orders-{uuid.uuid4().hex[:6]}"
    await pool.execute("INSERT INTO email_reservations (user_id, workflow_id, node_id, local_part, domain) "
                       "VALUES ($1::uuid, $2, 'mail', $3, $4)", owner, workflow_id, name, DOMAIN)
    return name


def _relayed(to: str, request_id: str) -> str:
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"], msg["Message-ID"] = "alice@c.example", to, "Order 42", "<42@c.example>"
    msg.set_content("Where is it?")
    return json.dumps({"requestId": request_id, "timestamp": 0, "from": "alice@c.example", "to": to,
                       "subject": "Order 42", "rawBase64": base64.b64encode(bytes(msg)).decode(),
                       "headers": {"message-id": msg["Message-ID"]}, "spfPass": True})


async def _post(client, body: str) -> httpx.Response:
    return await client.post("/email/inbound", content=body,
                             headers={"Authorization": f"Bearer {SECRET}", "Content-Type": "application/json"})


async def test_a_retried_delivery_fires_the_workflow_once(inbound, monkeypatch):
    pool, owner, client = inbound
    name = await _listening(pool, owner)
    run = AsyncMock()
    monkeypatch.setattr(email_routes, "_execute_workflow_with_relay", run)
    body = _relayed(f"{name}@{DOMAIN}", str(uuid.uuid4()))

    first, again = await _post(client, body), await _post(client, body)
    assert first.status_code == 200 and first.json()["triggered"] is True
    assert again.status_code == 200 and again.json() == {
        "success": True, "message": "Already received", "triggered": False}
    assert run.await_count == 1
    assert await pool.fetchval("SELECT receive_count FROM email_reservations WHERE local_part = $1", name) == 1

    # Another message to the same address is another delivery.
    assert (await _post(client, _relayed(f"{name}@{DOMAIN}", str(uuid.uuid4())))).json()["triggered"] is True
    assert run.await_count == 2


async def test_a_retried_delivery_starts_one_coordinator_turn(inbound, monkeypatch):
    from coder.coordinator import email_channel

    pool, owner, client = inbound
    name = f"ada-{uuid.uuid4().hex[:6]}"
    await pool.execute("INSERT INTO email_reservations (user_id, kind, local_part, domain) "
                       "VALUES ($1::uuid, 'coordinator', $2, $3)", owner, name, DOMAIN)
    received = AsyncMock(return_value="delivered")
    monkeypatch.setattr(email_channel, "receive", received)
    body = _relayed(f"{name}@{DOMAIN}", str(uuid.uuid4()))

    assert [(await _post(client, body)).json()["triggered"] for _ in range(3)] == [True, False, False]
    assert received.await_count == 1


async def test_a_delivery_that_failed_is_received_when_retried(inbound, monkeypatch):
    pool, owner, client = inbound
    name = await _listening(pool, owner)
    run = AsyncMock()
    monkeypatch.setattr(email_routes, "_execute_workflow_with_relay", run)
    received_email = email_routes._received_email
    failures = [RuntimeError("storage is down")]

    async def flaky(*args, **kwargs):
        if failures:
            raise failures.pop()
        return await received_email(*args, **kwargs)

    monkeypatch.setattr(email_routes, "_received_email", flaky)
    request_id = str(uuid.uuid4())
    body = _relayed(f"{name}@{DOMAIN}", request_id)

    assert (await _post(client, body)).status_code == 500
    assert await pool.fetchval("SELECT count(*) FROM email_inbound_deliveries WHERE request_id = $1", request_id) == 0
    assert (await _post(client, body)).json()["triggered"] is True
    assert run.await_count == 1


async def test_a_refused_delivery_leaves_nothing_behind(inbound):
    pool, _, client = inbound
    request_id = str(uuid.uuid4())
    assert (await _post(client, _relayed(f"nobody-{request_id[:6]}@{DOMAIN}", request_id))).status_code == 404
    assert await pool.fetchval("SELECT count(*) FROM email_inbound_deliveries WHERE request_id = $1", request_id) == 0


async def test_a_delivery_being_received_waits_and_a_dead_claim_is_taken_over(inbound, monkeypatch):
    pool, owner, client = inbound
    name = await _listening(pool, owner)
    run = AsyncMock()
    monkeypatch.setattr(email_routes, "_execute_workflow_with_relay", run)
    request_id = str(uuid.uuid4())
    body = _relayed(f"{name}@{DOMAIN}", request_id)
    deliveries = EmailDeliveryRepo(pool)
    stalled = await deliveries.claim(request_id)

    busy = await _post(client, body)
    assert busy.status_code == 409 and run.await_count == 0

    # Its handler died: once the lease has run out the next delivery receives it, and the dead one can't undo that.
    await pool.execute("UPDATE email_inbound_deliveries SET claimed_at = now() - interval '16 minutes' "
                       "WHERE request_id = $1", request_id)
    assert (await _post(client, body)).json()["triggered"] is True
    await deliveries.release(request_id, stalled)
    assert await deliveries.received(request_id)
    assert (await _post(client, body)).json()["message"] == "Already received"
    assert run.await_count == 1


async def test_records_go_once_the_relay_can_no_longer_deliver_them(inbound):
    pool, _, _ = inbound
    old, recent = str(uuid.uuid4()), str(uuid.uuid4())
    deliveries = EmailDeliveryRepo(pool)
    for request_id in (old, recent):
        await deliveries.settle(request_id, await deliveries.claim(request_id))
    await pool.execute("UPDATE email_inbound_deliveries SET claimed_at = now() - interval '31 days' "
                       "WHERE request_id = $1", old)

    await deliveries.claim(str(uuid.uuid4()))
    assert not await deliveries.received(old) and await deliveries.received(recent)
