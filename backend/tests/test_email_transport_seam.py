"""Outbound email reaches its transport through one seam, in either edition.

``utils.email_sending.send_email`` is what every surface calls: the
installation's own Resend or SMTP by default, a platform's transport once it
registers one. The coordinator's email named a send function only one edition
had, and the code that connects a phone-only account to an email named a
function only one edition's system mail had; both imports failed only when a
message was due, which no test reached. These drive each send from its entry
point to the transport, against real Postgres."""

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from billing.usage_tracker import usage_tracker
from coder.coordinator import email_channel
from tests.test_account_merge_postgres import seed_phone_account
from tests.test_coordinator_email_reach import owner  # noqa: F401 — the shared fixture
from tests.test_phone_accounts_postgres import phones_db  # noqa: F401 — the shared fixture
from utils import email_sending
from utils.account_link import AccountLink

pytestmark = pytest.mark.asyncio


class RecordingTransport:
    message_usd = Decimal("0.0042")

    def __init__(self):
        self.sent = []

    async def send(self, **message):
        self.sent.append(message)
        return {"message_id": f"<m{len(self.sent)}@example.test>", "delivery_status": "accepted",
                "to": message["to"], "from": message["from_addr"]}


@pytest.fixture
def transport(monkeypatch):
    registered = RecordingTransport()
    monkeypatch.setattr(email_sending, "_transport", email_sending._transport)  # put back after the test
    email_sending.register_email_transport(registered)
    return registered


async def test_a_send_reaches_the_registered_transport_with_loop_suppression(transport):
    out = await email_sending.send_email(from_addr="notifications@example.test", to="owner@example.test",
                                         subject="Run finished", text="plain", auto_submitted="auto-replied",
                                         extra_headers={"In-Reply-To": "<a@example.test>"})
    assert out["message_id"] == "<m1@example.test>"
    (message,) = transport.sent
    assert message["headers"] == {"Auto-Submitted": "auto-replied", "X-Auto-Response-Suppress": "All",
                                  "In-Reply-To": "<a@example.test>"}
    assert email_sending.message_usd() == transport.message_usd


async def test_the_coordinators_email_reaches_the_transport_and_charges_its_rate(owner, transport, monkeypatch):
    pool, user_id, email = owner
    billed = []
    monkeypatch.setattr(usage_tracker, "enforce_credit_gate", AsyncMock())
    monkeypatch.setattr(usage_tracker, "track_usage_event", AsyncMock(side_effect=lambda e, **k: billed.append(e)))
    name = f"seam-{uuid.uuid4().hex[:6]}"
    address = await email_channel.set_coordinator_address(pool, user_id, name)

    out = await email_channel.send_owner_email(pool, user_id, "Your digest failed twice today.")

    assert out["success"] is True and out["message_id"] == "<m1@example.test>"
    (message,) = transport.sent
    assert (message["from_addr"], message["to"], message["from_name"]) == (address, email, "NoClick coordinator")
    assert message["headers"]["Auto-Submitted"] == "auto-generated"
    assert "Your digest failed twice today." in message["text"] and message["html"]
    (charge,) = billed
    assert charge.usage_subtype == "email/coordinator" and charge.cost_usd == transport.message_usd


async def test_the_account_link_code_reaches_the_system_mail_transport(phones_db, monkeypatch):
    pool, _, admin, svc = phones_db
    source, _ = await seed_phone_account(pool, svc, "+15550200009")
    email = f"{uuid.uuid4().hex[:8]}@example.com"
    sent = []

    def system_mail(to_email, subject, html_content, text_content, headers=None, from_email=None):
        sent.append((to_email, subject, html_content, text_content))
        return True
    monkeypatch.setattr("utils.email._send_email", system_mail)

    # No send_code: the account link sends through the module's own default.
    assert (await AccountLink(pool, admin=lambda: admin).start(source, email))["sent_to"] == email
    ((to, subject, html, text),) = sent
    code = subject.rsplit(" ", 1)[-1]
    assert to == email and subject == f"Your NoClick code: {code}" and len(code) == 6 and code.isdigit()
    assert code in html and code in text and "0009" in text
