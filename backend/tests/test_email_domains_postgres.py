"""An installation that moved its mail to a new domain, against real Postgres
and the real inbound route: new addresses are minted on the new domain, an
address handed out on the old one keeps reaching the same reservation (and
answers at the new one too), re-reserving a name never moves it, and a reply
comes from the address the mail was sent to."""

import base64
import json
import uuid
from email.message import EmailMessage
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from utils import email_reservation_manager, email_routes
from utils.email_reply import build_reply_context, reply_refusal
from utils.email_reservation_manager import EmailReservationManager

pytestmark = pytest.mark.asyncio

NEW, OLD = "mail.new.example.test", "mail.old.example.test"
SECRET = "relay-secret"


@pytest.fixture
def domains(monkeypatch):
    """A platform whose mail moved from OLD to NEW."""
    monkeypatch.delenv("INBOUND_EMAIL_DOMAIN", raising=False)
    monkeypatch.delenv("NOCLICK_LOCAL", raising=False)
    monkeypatch.setattr(email_reservation_manager, "_platform_mail", ((), None))
    email_reservation_manager.register_mail_domains(NEW, OLD)
    monkeypatch.setenv("EMAIL_RELAY_SECRET", SECRET)


@pytest.fixture
async def moved(domains, postgres_db, postgres_container, monkeypatch):
    """Its database and inbound route; yields (pool, owner id, client)."""
    from tests.fixtures.postgres_fixtures import asyncpg
    from utils.database_pool import setup_asyncpg_codecs

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
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            yield pool, owner, client
    finally:
        await pool.close()


async def _workflow(pool, owner, node_id="mail"):
    graph = {"nodes": [{"id": node_id, "type": "trigger-email", "config": {}}], "edges": []}
    return str(await pool.fetchval(
        "INSERT INTO workflows (owner_id, name, workflow) VALUES ($1::uuid, 'Orders', $2) RETURNING id", owner, graph))


async def _held_before_the_move(pool, owner, workflow_id, local_part, node_id="mail"):
    await pool.execute(
        "INSERT INTO email_reservations (user_id, workflow_id, node_id, local_part, domain) "
        "VALUES ($1::uuid, $2::uuid, $3, $4, $5)", owner, workflow_id, node_id, local_part, OLD)


def _relayed(to: str, *, sender="alice@customer.example", subject="Order 42") -> str:
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"], msg["Message-ID"] = sender, to, subject, f"<{uuid.uuid4().hex}@c.example>"
    msg.set_content("Where is it?")
    return json.dumps({"from": sender, "to": to, "subject": subject, "rawBase64": base64.b64encode(bytes(msg)).decode(),
                       "headers": {"message-id": msg["Message-ID"]}, "spfPass": True})


async def _post(client, body: str) -> httpx.Response:
    return await client.post("/email/inbound", content=body,
                             headers={"Authorization": f"Bearer {SECRET}", "Content-Type": "application/json"})


async def test_an_address_handed_out_on_the_old_domain_keeps_working_on_both(moved, monkeypatch):
    pool, owner, client = moved
    workflow_id = await _workflow(pool, owner)
    name = f"orders-{uuid.uuid4().hex[:6]}"
    await _held_before_the_move(pool, owner, workflow_id, name)
    run = AsyncMock()
    monkeypatch.setattr(email_routes, "_execute_workflow_with_relay", run)

    for domain in (OLD, NEW):
        response = await _post(client, _relayed(f"{name}@{domain}"))
        assert response.status_code == 200 and response.json()["triggered"] is True, domain
        payload = next(n for n in run.await_args.kwargs["nodes"] if n["id"] == "mail")["config"]["_triggerPayload"]
        assert run.await_args.kwargs["workflow_id"] == workflow_id and payload["to"] == f"{name}@{domain}"
        # The reply goes from the address the sender wrote to, and its token holds for it.
        context = build_reply_context(payload)
        assert context["from_addr"] == f"{name}@{domain}" and reply_refusal(context) is None
    assert await pool.fetchval("SELECT receive_count FROM email_reservations WHERE local_part = $1", name) == 2

    # Nobody's name, on either domain, is still nobody's.
    assert (await _post(client, _relayed(f"ghost-{name}@{NEW}"))).status_code == 404


async def test_a_name_keeps_its_domain_and_a_new_one_goes_on_the_new_domain(moved):
    pool, owner, _ = moved
    workflow_id = await _workflow(pool, owner)
    name = f"invoices-{uuid.uuid4().hex[:6]}"
    await _held_before_the_move(pool, owner, workflow_id, name)

    # The name is held on every domain; free only to its own node.
    assert await EmailReservationManager.is_available(pool, name) is False
    assert await EmailReservationManager.is_available(
        pool, name, exclude_workflow_id=workflow_id, exclude_node_id="mail") is True

    kept = await EmailReservationManager.reserve(pool, owner, workflow_id, "mail", name)
    assert kept["email_address"] == f"{name}@{OLD}"
    assert await EmailReservationManager.get_for_node(pool, workflow_id, "mail") == kept

    renamed = await EmailReservationManager.reserve(pool, owner, workflow_id, "mail", f"{name}-2")
    assert renamed["email_address"] == f"{name}-2@{NEW}" and renamed["reservation_id"] == kept["reservation_id"]
    # The old name is free again, and a new holder gets it on the new domain.
    other = await EmailReservationManager.reserve(pool, owner, workflow_id, "other", name)
    assert other["email_address"] == f"{name}@{NEW}"


async def test_old_coordinator_and_agent_reply_addresses_route_from_either_domain(moved, monkeypatch):
    from coder.coordinator import email_channel
    from utils import capabilities

    # No agent answers this account; mail that moves an address to one is test_platform_inbox_senders'.
    monkeypatch.delitem(capabilities._providers, capabilities.ACCOUNT_AGENT_EMAIL, raising=False)
    pool, owner, client = moved
    name = f"ada-{uuid.uuid4().hex[:6]}"
    await pool.execute("INSERT INTO email_reservations (user_id, kind, local_part, domain) "
                       "VALUES ($1::uuid, 'coordinator', $2, $3)", owner, name, OLD)
    received = AsyncMock(return_value="delivered")
    monkeypatch.setattr(email_channel, "receive", received)
    assert (await _post(client, _relayed(f"{name}@{NEW}"))).status_code == 200
    # The coordinator hears it at the address it holds.
    assert received.await_args.args[1:3] == (name, OLD)
    assert await email_channel.coordinator_address(pool, owner) == f"{name}@{OLD}"

    # Reply capabilities resolve by id on every domain of the installation's own.
    for domain in (OLD, NEW):
        response = await _post(client, _relayed(f"agent-reply-{uuid.uuid4().hex}@{domain}"))
        assert response.status_code == 200 and response.json()["message"] == "Unknown reply address", domain
    # On a domain that isn't the installation's, the same name is nobody's.
    assert (await _post(client, _relayed(f"{name}@elsewhere.example.test"))).status_code == 404
