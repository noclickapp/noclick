"""Outbound email on a self-hosted instance: Resend when a key is set, else the
SMTP server the instance configured, else a message that says where to add one.
Before this, the Send Email node ran and failed on every one-click deploy —
the transport wanted a Resend key nobody had been asked for."""

import base64
import os

import pytest

from utils import email_sending, smtp_transport


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    for name in ("RESEND_API_KEY", "SMTP_HOST", "SMTP_PORT", "SMTP_USERNAME", "SMTP_PASSWORD", "FROM_EMAIL", "INBOUND_EMAIL_DOMAIN"):
        monkeypatch.delenv(name, raising=False)


class FakeSmtp:
    sent = []
    logins = []

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port = host, port

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def ehlo(self):
        pass

    def has_extn(self, name):
        return False

    def login(self, user, password):
        FakeSmtp.logins.append((user, password))

    def send_message(self, message):
        FakeSmtp.sent.append(message)


@pytest.fixture
def fake_smtp(monkeypatch):
    FakeSmtp.sent, FakeSmtp.logins = [], []
    monkeypatch.setattr(smtp_transport.smtplib, "SMTP", FakeSmtp)
    monkeypatch.setattr(smtp_transport.smtplib, "SMTP_SSL", FakeSmtp)
    return FakeSmtp


@pytest.mark.asyncio
async def test_nothing_configured_says_where_to_configure_it():
    assert email_sending.outbound_email_configured() is False
    with pytest.raises(RuntimeError) as e:
        await email_sending.send_email(from_addr="a@b.c", to="x@y.z", subject="s", text="t")
    assert "Settings → Self-hosted" in str(e.value)


@pytest.mark.asyncio
async def test_smtp_sends_from_the_configured_sender_with_attachments(monkeypatch, fake_smtp):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USERNAME", "mailer")
    monkeypatch.setenv("SMTP_PASSWORD", "hunter2")
    monkeypatch.setenv("FROM_EMAIL", "NoClick <noclick@example.com>")
    assert email_sending.outbound_email_configured() is True
    assert email_sending.configured_sender_address() == "noclick@example.com"

    result = await email_sending.send_email(
        from_addr="noclick@example.com",
        from_name="NoClick",
        to="owner@example.org",
        subject="Run finished",
        text="plain",
        html="<p>rich</p>",
        extra_headers={"List-Unsubscribe": "<https://x/y>"},
        attachments=[{"content": base64.b64encode(b"hello").decode(), "filename": "a.txt", "content_type": "text/plain"}],
    )
    assert result["delivery_status"] == "accepted" and result["to"] == "owner@example.org"
    assert fake_smtp.logins == [("mailer", "hunter2")]
    (message,) = fake_smtp.sent
    assert message["From"] == "NoClick <noclick@example.com>"
    assert message["To"] == "owner@example.org"
    assert message["List-Unsubscribe"] == "<https://x/y>"
    assert message["Auto-Submitted"] == "auto-generated"
    parts = {p.get_content_type(): p for p in message.walk()}
    assert "text/plain" in parts and "text/html" in parts
    attachment = next(p for p in message.iter_attachments())
    assert attachment.get_filename() == "a.txt" and attachment.get_payload(decode=True) == b"hello"


@pytest.mark.asyncio
async def test_a_foreign_sender_is_refused_even_with_a_transport(monkeypatch, fake_smtp):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("FROM_EMAIL", "noclick@example.com")
    with pytest.raises(RuntimeError, match="must match FROM_EMAIL"):
        await email_sending.send_email(from_addr="someone@else.com", to="x@y.z", subject="s", text="t")
    assert fake_smtp.sent == []


@pytest.mark.asyncio
async def test_resend_wins_when_both_are_configured(monkeypatch, fake_smtp):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("RESEND_API_KEY", "re_x")
    monkeypatch.setenv("FROM_EMAIL", "noclick@example.com")
    calls = []

    async def via_resend(*args):
        calls.append(args)
        return "msg-1"

    monkeypatch.setattr(email_sending, "_send_via_resend", via_resend)
    result = await email_sending.send_email(from_addr="noclick@example.com", to="x@y.z", subject="s", text="t")
    assert result["message_id"] == "msg-1" and len(calls) == 1 and fake_smtp.sent == []
