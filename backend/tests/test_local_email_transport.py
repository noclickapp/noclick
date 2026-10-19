"""Outbound email through the installation's own transport (the default
behind ``utils.email_sending.send_email``, which a platform may replace):
Resend when a key is set, else the SMTP server the instance configured, else a
message that says where to add one. Before this, the Send Email node ran and
failed on every one-click deploy — the transport wanted a Resend key nobody had
been asked for."""

import base64
import smtplib

import pytest
import resend

from utils import email_sending, smtp_transport


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.setattr(email_sending, "_transport", email_sending.ConfiguredTransport())
    for name in ("RESEND_API_KEY", "SMTP_HOST", "SMTP_PORT", "SMTP_USERNAME", "SMTP_PASSWORD", "FROM_EMAIL", "INBOUND_EMAIL_DOMAIN"):
        monkeypatch.delenv(name, raising=False)


class FakeSmtp:
    sent = []
    logins = []
    fail = {}  # stage ("connect", "login", "send") -> the exception the server's answer raises

    def __init__(self, host, port, timeout=None, context=None):
        if "connect" in FakeSmtp.fail:
            raise FakeSmtp.fail["connect"]
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
        if "login" in FakeSmtp.fail:
            raise FakeSmtp.fail["login"]
        FakeSmtp.logins.append((user, password))

    def send_message(self, message):
        if "send" in FakeSmtp.fail:
            raise FakeSmtp.fail["send"]
        FakeSmtp.sent.append(message)


@pytest.fixture
def fake_smtp(monkeypatch):
    FakeSmtp.sent, FakeSmtp.logins, FakeSmtp.fail = [], [], {}
    monkeypatch.setattr(smtp_transport.smtplib, "SMTP", FakeSmtp)
    monkeypatch.setattr(smtp_transport.smtplib, "SMTP_SSL", FakeSmtp)
    return FakeSmtp


@pytest.mark.asyncio
async def test_nothing_configured_says_where_to_configure_it():
    assert email_sending.outbound_email_configured() is False
    with pytest.raises(email_sending.EmailNotSent) as e:
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
    with pytest.raises(email_sending.EmailNotSent, match="must match FROM_EMAIL"):
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


def _smtp_configured(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_USERNAME", "mailer")
    monkeypatch.setenv("FROM_EMAIL", "NoClick <noclick@example.com>")


async def _send():
    return await email_sending.send_email(from_addr="noclick@example.com", to="owner@example.org", subject="s", text="t")


@pytest.mark.asyncio
async def test_an_smtp_send_carries_a_message_id_on_the_senders_domain(monkeypatch, fake_smtp):
    _smtp_configured(monkeypatch)
    result = await _send()
    (message,) = fake_smtp.sent
    # A reply's In-Reply-To names it, so the thread holds together.
    assert result["message_id"] == message["Message-ID"]
    assert message["Message-ID"].startswith("<") and message["Message-ID"].endswith("@example.com>")


@pytest.mark.asyncio
@pytest.mark.parametrize("stage,error,words", [
    ("send", smtplib.SMTPRecipientsRefused({"owner@example.org": (550, b"5.1.1 No such user")}),
     "smtp.example.com refused the message: 550 5.1.1 No such user"),
    ("send", smtplib.SMTPSenderRefused(553, b"5.7.1 Sender not allowed", "noclick@example.com"),
     "smtp.example.com refused the message: 553 5.7.1 Sender not allowed"),
    ("login", smtplib.SMTPAuthenticationError(535, b"5.7.8 Authentication failed"),
     "smtp.example.com refused the message: 535 5.7.8 Authentication failed"),
    ("connect", ConnectionRefusedError(61, "Connection refused"),
     "Could not reach smtp.example.com: Connection refused"),
])
async def test_a_server_that_refuses_says_nothing_was_sent_in_its_own_words(monkeypatch, fake_smtp, stage, error, words):
    _smtp_configured(monkeypatch)
    fake_smtp.fail[stage] = error
    with pytest.raises(email_sending.EmailNotSent) as e:
        await _send()
    assert str(e.value) == words


@pytest.mark.asyncio
async def test_a_connection_dropped_mid_send_stays_an_open_question(monkeypatch, fake_smtp):
    _smtp_configured(monkeypatch)
    fake_smtp.fail["send"] = smtplib.SMTPServerDisconnected("Connection unexpectedly closed")
    with pytest.raises(smtplib.SMTPServerDisconnected) as e:
        await _send()
    assert not isinstance(e.value, email_sending.EmailNotSent)


def _resend_raises(monkeypatch, error):
    monkeypatch.setenv("RESEND_API_KEY", "re_x")
    monkeypatch.setenv("FROM_EMAIL", "noclick@example.com")

    def send(params):
        raise error
    monkeypatch.setattr(resend.Emails, "send", send)


@pytest.mark.asyncio
async def test_a_resend_refusal_says_nothing_was_sent_in_resends_words(monkeypatch):
    _resend_raises(monkeypatch, resend.exceptions.ResendError(
        code=403, error_type="validation_error", suggested_action="",
        message="The example.com domain is not verified. Please, add and verify your domain."))
    with pytest.raises(email_sending.EmailNotSent) as e:
        await _send()
    assert str(e.value) == ("Resend refused the message: The example.com domain is not verified. "
                            "Please, add and verify your domain.")


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [
    # No answer reached us: the SDK wraps the network failure.
    resend.exceptions.ResendError(code=500, error_type="HttpClientError", message="Request failed: timed out",
                                  suggested_action="Request failed, please try again."),
    # An answer, but a server error: it may still have gone.
    resend.exceptions.ResendError(code=500, error_type="application_error", message="Internal server error",
                                  suggested_action=""),
])
async def test_a_resend_failure_with_no_refusal_stays_an_open_question(monkeypatch, error):
    _resend_raises(monkeypatch, error)
    with pytest.raises(resend.exceptions.ResendError) as e:
        await _send()
    assert not isinstance(e.value, email_sending.EmailNotSent)
