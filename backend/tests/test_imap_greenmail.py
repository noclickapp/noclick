"""The IMAP/SMTP node against a real mail server: GreenMail in Docker, over TLS
that is verified end to end (the server holds a certificate for the test's own
host name, and the node dials the address ``utils.ssrf`` resolved while TLS
checks that name).

Each test talks to the server the way a person's mailbox would be talked to:
the connect seam proving a typed-in credential, searches, reads, flags, moves,
sends and threaded replies (read back from the recipient's own mailbox), and the
New email trigger's baseline, one-fire-per-message and held backlog.
"""

from __future__ import annotations

import datetime
import imaplib
import io
import ipaddress
import json
import os
import smtplib
import socket
import ssl
import tarfile
import threading
import time
from email.message import EmailMessage
from typing import Any, Dict, List

import pytest

from nodes import imap_mailbox as mailbox
from nodes.core.run_op import run_node_operation

IMAGE = "greenmail/standalone:2.1.5"
ANA, ANA_PASSWORD = "ana@acme.test", "secret-pass"
BOB, BOB_PASSWORD = "bob@acme.test", "bob-pass"


def _certificate(host: str):
    """A self-signed certificate naming ``host``, as GreenMail's keystore and the PEM the client trusts."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "greenmail.test")])
    try:
        san = x509.IPAddress(ipaddress.ip_address(host))
    except ValueError:
        san = x509.DNSName(host)
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1)).not_valid_after(now + datetime.timedelta(days=2))
        .add_extension(x509.SubjectAlternativeName([san]), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    keystore = pkcs12.serialize_key_and_certificates(
        b"greenmail", key, cert, None, serialization.BestAvailableEncryption(b"changeit"))
    return keystore, cert.public_bytes(serialization.Encoding.PEM).decode()


def _docker_host() -> str:
    url = os.environ.get("DOCKER_HOST", "")
    if url.startswith("tcp://"):
        return url[len("tcp://"):].rsplit(":", 1)[0]
    return "127.0.0.1"


@pytest.fixture(scope="module")
def greenmail():
    docker = pytest.importorskip("docker")
    try:
        client = docker.from_env()
        client.ping()
    except Exception as e:  # noqa: BLE001 - no daemon on this machine
        pytest.skip(f"Docker isn't available: {e}")
    host = _docker_host()
    keystore, pem = _certificate(host)
    opts = " ".join([
        "-Dgreenmail.setup.test.all", "-Dgreenmail.hostname=0.0.0.0", "-Dgreenmail.users.login=email",
        f"-Dgreenmail.users=ana:{ANA_PASSWORD}@acme.test,bob:{BOB_PASSWORD}@acme.test",
        "-Dgreenmail.tls.keystore.file=/certs/test.p12", "-Dgreenmail.tls.keystore.password=changeit",
    ])
    container = client.containers.create(
        IMAGE, environment={"GREENMAIL_OPTS": opts},
        ports={"3993/tcp": None, "3465/tcp": None, "3143/tcp": None, "3025/tcp": None},
    )
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w") as tar:
        info = tarfile.TarInfo("certs/test.p12")
        info.size, info.mode = len(keystore), 0o644
        tar.addfile(info, io.BytesIO(keystore))
    container.put_archive("/", archive.getvalue())
    try:
        container.start()
        deadline = time.time() + 90
        while b"Starting GreenMail API server" not in container.logs():
            if time.time() > deadline:
                pytest.fail(f"GreenMail didn't start:\n{container.logs().decode(errors='replace')[-2000:]}")
            time.sleep(0.5)
        container.reload()
        ports = {k.split("/")[0]: int(v[0]["HostPort"]) for k, v in container.attrs["NetworkSettings"]["Ports"].items()
                 if v}
        yield {"host": host, "pem": pem, "imaps": ports["3993"], "smtps": ports["3465"], "imap": ports["3143"],
               "smtp": ports["3025"]}
    finally:
        container.remove(force=True)


@pytest.fixture
def server(greenmail, monkeypatch):
    """GreenMail as a mailbox's provider: its ports are mail ports, its certificate is trusted, the test's own
    host is reachable, and every mailbox starts empty."""
    import utils.smtp_transport as transport

    monkeypatch.setenv("OUTBOUND_ALLOW_PRIVATE_IPS", "true")
    for port, security in ((greenmail["imaps"], "ssl"), (greenmail["imap"], "starttls")):
        monkeypatch.setitem(mailbox.IMAP_PORTS, port, security)
    for port, security in ((greenmail["smtps"], "ssl"), (greenmail["smtp"], "starttls")):
        monkeypatch.setitem(mailbox.SMTP_PORTS, port, security)
    monkeypatch.setattr(transport, "tls_context", lambda: ssl.create_default_context(cadata=greenmail["pem"]))

    async def paid(*_a, **_k):
        return False

    monkeypatch.setattr("nodes.core.email_branding.sender_is_free_tier", paid)
    for user, password in ((ANA, ANA_PASSWORD), (BOB, BOB_PASSWORD)):
        _empty(greenmail, user, password)
    return greenmail


def _empty(server, user, password) -> None:
    """Every folder empty, as a new mailbox is."""
    client = raw_imap(server, user, password)
    _, listed = client.list('""', '"*"')
    for line in listed:
        name = line.decode().rsplit(" ", 1)[-1].strip('"')
        typ, data = client.select(mailbox.quote(name))
        if typ == "OK" and int(data[0] or 0):
            client.store("1:*", "+FLAGS.SILENT", r"(\Deleted)")
            client.expunge()
    client.logout()


def credential(server, *, email=ANA, password=ANA_PASSWORD, **overrides) -> Dict[str, Any]:
    return {"email": email, "password": password, "imap_host": server["host"], "imap_port": server["imaps"],
            "smtp_host": server["host"], "smtp_port": server["smtps"], **overrides}


async def op(server, operation: str, arguments: Dict[str, Any] | None = None, **cred) -> Dict[str, Any]:
    return await run_node_operation(node_type="automation-imap", operation=operation, arguments=arguments or {},
                                    user_id="user-1", workflow_id="wf-1", credential_data=credential(server, **cred))


def deliver(server, *, sender: str, to: str, subject: str, text: str | None = "Hello", html: str | None = None,
            headers: Dict[str, str] | None = None, attachments: List[tuple] = ()) -> EmailMessage:
    message = EmailMessage()
    message["From"], message["To"], message["Subject"] = sender, to, subject
    message["Date"] = "Tue, 10 Nov 2026 09:00:00 +0000"
    for name, value in (headers or {}).items():
        message[name] = value
    if text is None:
        message.set_content(html, subtype="html")
    else:
        message.set_content(text)
        if html:
            message.add_alternative(html, subtype="html")
    for filename, mime, data in attachments:
        maintype, subtype = mime.split("/")
        message.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)
    with smtplib.SMTP_SSL(server["host"], server["smtps"],
                          context=ssl.create_default_context(cadata=server["pem"])) as smtp:
        smtp.send_message(message)
    return message


def raw_imap(server, user=ANA, password=ANA_PASSWORD) -> imaplib.IMAP4_SSL:
    client = imaplib.IMAP4_SSL(server["host"], server["imaps"],
                               ssl_context=ssl.create_default_context(cadata=server["pem"]))
    client.login(user, password)
    return client


def create_folder(server, name: str) -> None:
    client = raw_imap(server)
    client.create(mailbox.quote(mailbox.encode_folder(name)))  # NO when it's there already
    client.logout()


def read_mailbox(server, user, password, folder="INBOX") -> List[EmailMessage]:
    client = raw_imap(server, user, password)
    client.select(mailbox.quote(folder), readonly=True)
    _, data = client.uid("SEARCH", "ALL")
    out = []
    for uid in data[0].split():
        _, fetched = client.uid("FETCH", uid, "(BODY.PEEK[])")
        out.append(mailbox.parse(fetched[0][1]))
    client.logout()
    return out


def flags_of(server, uid: int, folder="INBOX") -> List[str]:
    client = raw_imap(server)
    client.select(mailbox.quote(folder), readonly=True)
    _, data = client.uid("FETCH", str(uid), "(FLAGS)")
    client.logout()
    return mailbox._parse_fetch(data)[uid]["flags"]


# ---------------------------------------------------------------- connect


@pytest.mark.asyncio
async def test_connecting_shows_the_newest_senders_and_a_wrong_password_is_refused_in_the_servers_words(
        server, monkeypatch):
    from nodes.core import connection_evidence, credential_connect

    monkeypatch.setattr(credential_connect, "_collect_evidence", connection_evidence.collect_evidence)
    blob = {k: str(v) for k, v in credential(server).items()}

    empty = await credential_connect.validate_for_connect(credential_type="imap_smtp", credential_data=blob,
                                                          user_id="user-1")
    assert empty.ok and empty.evidence.reachable is True
    assert empty.evidence.account_label == ANA, "an empty inbox still names the account it signed in as"

    deliver(server, sender="Priya Raman <priya@client.test>", to=ANA, subject="Q3 invoice")
    deliver(server, sender="Marco <marco@vendor.test>", to=ANA, subject="Delivery window")
    verdict = await credential_connect.validate_for_connect(credential_type="imap_smtp", credential_data=blob,
                                                            user_id="user-1")
    assert verdict.ok and verdict.evidence.reachable is True
    assert [s.label for s in verdict.evidence.samples] == ["Marco", "Priya Raman"]
    assert verdict.verified_metadata()["verified_with"] == "Marco"
    assert verdict.credential_data["imap_security"] == "ssl" and verdict.credential_data["smtp_security"] == "ssl"

    wrong = await credential_connect.validate_for_connect(
        credential_type="imap_smtp", credential_data={**blob, "password": "not-the-password"}, user_id="user-1")
    assert not wrong.ok, "a refused sign-in is never saved"
    assert "LOGIN failed. Invalid login/password" in wrong.rejection, "the server's own words"
    assert "authentication failed" in wrong.rejection
    assert "app password was rejected" in (wrong.hint or "")
    assert "not-the-password" not in wrong.rejection


@pytest.mark.asyncio
async def test_a_server_that_wont_encrypt_never_receives_the_password(server):
    with pytest.raises(mailbox.MailError, match="doesn't offer STARTTLS"):
        await op(server, "list_folders", imap_port=server["imap"], imap_security="starttls")
    with pytest.raises(mailbox.MailError, match="doesn't offer STARTTLS"):
        await op(server, "check_connection", smtp_port=server["smtp"], smtp_security="starttls")


@pytest.mark.asyncio
async def test_a_certificate_for_another_name_is_refused(server, monkeypatch):
    import utils.smtp_transport as transport

    monkeypatch.setattr(transport, "tls_context", lambda: ssl.create_default_context())
    with pytest.raises(mailbox.MailError, match="certificate that couldn't be verified"):
        await op(server, "list_folders")


# ----------------------------------------------------------------- reading


@pytest.mark.asyncio
async def test_search_is_newest_first_with_filters_snippets_and_non_ascii_terms(server):
    deliver(server, sender="Priya <priya@client.test>", to=ANA, subject="Invoice 1041", text="Amount due: 120 EUR")
    deliver(server, sender="News <news@list.test>", to=ANA, subject="Weekly digest", text=None,
            html="<html><head><title>x</title></head><body><p>Top <b>stories</b> this week</p></body></html>")
    deliver(server, sender="Priya <priya@client.test>", to=ANA, subject="Café menu for Friday",
            text="Croissants à la crème")

    everything = await op(server, "search_messages", {"limit": 2})
    assert [m["subject"] for m in everything["messages"]] == ["Café menu for Friday", "Weekly digest"]
    assert everything["total_matches"] == 3
    assert everything["messages"][1]["snippet"] == "Top stories this week", "an HTML-only message reads as text"
    first = everything["messages"][0]
    assert first["unread"] is True and first["from_address"] == "priya@client.test"
    assert first["uidvalidity"] == everything["uidvalidity"]

    from_priya = await op(server, "search_messages", {"sender": "priya@client.test"})
    assert [m["subject"] for m in from_priya["messages"]] == ["Café menu for Friday", "Invoice 1041"]

    cafe = await op(server, "search_messages", {"subject": "Café", "sender": "priya@client.test"})
    assert [m["subject"] for m in cafe["messages"]] == ["Café menu for Friday"], "a UTF-8 term goes as a literal"
    both = await op(server, "search_messages", {"subject": "Café", "text": "crème"})
    assert [m["subject"] for m in both["messages"]] == ["Café menu for Friday"], "two UTF-8 terms, intersected"
    assert (await op(server, "search_messages", {"subject": "Café", "text": "brûlée"}))["messages"] == []

    await op(server, "mark_as_read", {"uid": first["uid"]})
    unread = await op(server, "search_messages", {"unread_only": True})
    assert first["uid"] not in [m["uid"] for m in unread["messages"]]
    assert len(unread["messages"]) == 2

    headers_only = await op(server, "search_messages", {"include_snippet": False, "limit": 1})
    assert "snippet" not in headers_only["messages"][0]


@pytest.mark.asyncio
async def test_get_message_reads_both_bodies_keeps_attachments_as_files_and_leaves_it_unread(server, monkeypatch):
    stored: List[Dict[str, Any]] = []

    async def store(pool, *, workflow_id, node_id, body, source, mimetype, filename):
        stored.append({"workflow_id": workflow_id, "body": body, "mimetype": mimetype, "filename": filename,
                       "source": source})
        return {"url": f"https://files.test/{filename}", "resource_id": f"res-{len(stored)}", "rehosted": True}

    monkeypatch.setattr("utils.inbound_media.store_inbound_media", store)
    monkeypatch.setattr("utils.database_pool.get_native_pool", lambda: object())
    pdf = b"%PDF-1.4\n" + os.urandom(2048)
    deliver(server, sender="Priya <priya@client.test>", to=ANA, subject="Signed contract",
            text="Attached, signed.", html="<p>Attached, <i>signed</i>.</p>",
            headers={"Message-ID": "<contract-2@client.test>", "References": "<contract-1@client.test>"},
            attachments=[("contract.pdf", "application/pdf", pdf)])
    uid = (await op(server, "search_messages"))["messages"][0]["uid"]

    message = await op(server, "get_message", {"uid": str(uid)})
    assert message["text"] == "Attached, signed." and message["html"] == "<p>Attached, <i>signed</i>.</p>"
    assert message["message_id"] == "<contract-2@client.test>"
    assert message["thread"] == "<contract-1@client.test>", "a message's thread is the one its References start"
    [attachment] = message["attachments"]
    assert attachment["url"] == "https://files.test/contract.pdf" and attachment["resource_id"] == "res-1"
    assert stored[0]["body"] == pdf and stored[0]["workflow_id"] == "wf-1", "the bytes kept are the bytes sent"
    assert "base64" not in json.dumps(message) and pdf[:20].decode(errors="ignore") not in json.dumps(message)
    assert "\\Seen" not in flags_of(server, uid), "reading a message doesn't mark it read"

    listed = await op(server, "get_message", {"uid": uid, "download_attachments": False})
    assert "url" not in listed["attachments"][0] and len(stored) == 1


@pytest.mark.asyncio
async def test_a_message_over_the_size_cap_is_read_in_part(server, monkeypatch):
    monkeypatch.setattr(mailbox, "MAX_MESSAGE_BYTES", 4000)
    monkeypatch.setattr(mailbox, "PARTIAL_BYTES", 1500)
    deliver(server, sender="Big <big@client.test>", to=ANA, subject="Large", text="Start of a long message. " * 4,
            attachments=[("photo.bin", "application/octet-stream", os.urandom(20_000))])
    uid = (await op(server, "search_messages"))["messages"][0]["uid"]
    message = await op(server, "get_message", {"uid": uid})
    assert message["text"].startswith("Start of a long message.")
    assert message["attachments"] == []
    assert "over the 4 KB NoClick reads" in message["attachments_note"]
    assert "attachments weren't read" in message["attachments_note"]


# ------------------------------------------------------------ changing it


@pytest.mark.asyncio
async def test_mark_read_unread_and_move_to_trash_and_refuse_what_isnt_there(server):
    create_folder(server, "Trash")
    deliver(server, sender="a@x.test", to=ANA, subject="one")
    deliver(server, sender="b@x.test", to=ANA, subject="two")
    found = (await op(server, "search_messages"))["messages"]
    uids = sorted(m["uid"] for m in found)
    uidvalidity = found[0]["uidvalidity"]

    await op(server, "mark_as_read", {"uid": ",".join(map(str, uids))})
    assert all("\\Seen" in flags_of(server, u) for u in uids)
    await op(server, "mark_as_unread", {"uid": uids[0]})
    assert "\\Seen" not in flags_of(server, uids[0])

    moved = await op(server, "move_message", {"uid": uids[0], "destination_folder": "Trash",
                                              "uidvalidity": uidvalidity})
    assert moved["status"] == "success"
    assert [m["subject"] for m in (await op(server, "search_messages"))["messages"]] == ["two"]
    assert [m["subject"] for m in (await op(server, "search_messages", {"folder": "Trash"}))["messages"]] == ["one"]

    with pytest.raises(mailbox.MailError, match="no message with UID 999"):
        await op(server, "mark_as_read", {"uid": 999})
    with pytest.raises(mailbox.MailError, match="UIDVALIDITY changed"):
        await op(server, "move_message", {"uid": uids[1], "destination_folder": "Trash",
                                          "uidvalidity": uidvalidity + 1})
    with pytest.raises(mailbox.MailError, match="no folder 'Nope'"):
        await op(server, "search_messages", {"folder": "Nope"})


@pytest.mark.asyncio
async def test_send_reaches_the_recipient_with_attachments_and_files_a_copy_in_sent(server):
    create_folder(server, "Sent")
    sent = await op(server, "send_email", {
        "to": ["Bob <bob@acme.test>"], "subject": "Plan for Friday", "text": "See the plan.",
        "html": "<p>See the <b>plan</b>.</p>", "from_name": "Ana Lima",
        "attachments": ["data:text/csv;base64,ZGF5LHRhc2sKRnJpLHNoaXAK"], "save_to_sent": True,
    })
    assert sent["status"] == "sent" and sent["saved_to"] == "Sent"
    [received] = read_mailbox(server, BOB, BOB_PASSWORD)
    assert received["From"] == "Ana Lima <ana@acme.test>" and received["Subject"] == "Plan for Friday"
    assert received["Message-ID"] == sent["message_id"]
    assert received.get_body(("plain",)).get_content().strip() == "See the plan."
    [attached] = list(received.iter_attachments())
    assert attached.get_content_type() == "text/csv" and attached.get_payload(decode=True) == b"day,task\nFri,ship\n"
    [copy] = read_mailbox(server, ANA, ANA_PASSWORD, "Sent")
    assert copy["Message-ID"] == sent["message_id"]

    with pytest.raises(ValueError, match="isn't an email address"):
        await op(server, "send_email", {"to": ["bob at acme"], "subject": "x", "text": "y"})
    with pytest.raises(ValueError, match="can't be written as given"):
        await op(server, "send_email", {"to": [BOB], "subject": "Hi\r\nBcc: everyone@x.test", "text": "y"})


@pytest.mark.asyncio
async def test_a_reply_threads_under_the_message_and_reply_all_copies_everyone_else(server):
    deliver(server, sender="Bob <bob@acme.test>", to="ana@acme.test, carol@acme.test", subject="Launch date",
            text="Can we ship Friday?", headers={"Message-ID": "<launch-2@acme.test>",
                                                 "References": "<launch-1@acme.test>", "Cc": "dan@acme.test"})
    uid = (await op(server, "search_messages"))["messages"][0]["uid"]

    reply = await op(server, "reply_to_message", {"uid": uid, "text": "Friday works.", "reply_all": True})
    assert reply["to"] == ["bob@acme.test"] and reply["cc"] == ["carol@acme.test", "dan@acme.test"]
    assert reply["in_reply_to"] == "<launch-2@acme.test>" and reply["thread"] == "<launch-1@acme.test>"
    [received] = read_mailbox(server, BOB, BOB_PASSWORD)
    assert received["Subject"] == "Re: Launch date"
    assert received["In-Reply-To"] == "<launch-2@acme.test>"
    assert received["References"].split() == ["<launch-1@acme.test>", "<launch-2@acme.test>"]

    again = await op(server, "reply_to_message", {"uid": uid, "text": "Only to Bob."})
    assert again["to"] == ["bob@acme.test"] and again["cc"] == []


# ----------------------------------------------------------------- trigger


def _trigger(server, **config):
    from nodes.core.registry import NodeFactory

    node = NodeFactory.create_node(
        node_id="trigger-1", node_type="automation-imap",
        node_data={"config": {"operation": "on_new_email", **config}, "credentials": credential(server)},
        sio=None, sid=None, workflow_id="wf-1", user_id="user-1",
    )
    state: Dict[str, Any] = {}

    async def update(mutator, *, max_retries=4, skip_result=None):
        new_state, result = mutator(dict(state))
        if new_state is not None:
            state.clear()
            state.update(new_state)
        return result

    node._update_node_state = update
    node.state = state
    return node


@pytest.mark.asyncio
async def test_new_email_baselines_then_fires_each_message_once_and_holds_a_backlog(server, monkeypatch):
    from nodes import imap_node

    monkeypatch.setattr(imap_node, "TRIGGER_MAX_PER_POLL", 3)
    deliver(server, sender="old@x.test", to=ANA, subject="before the trigger")
    node = _trigger(server)

    assert (await node.run({}))["messages"] == [], "the first poll records what's there and fires nothing"
    assert node.trigger_produced_no_event({}) is True

    for n in range(5):
        deliver(server, sender=f"Customer {n} <c{n}@x.test>", to=ANA, subject=f"Order {n}", text=f"Order body {n}")
    first = await node.run({})
    assert [m["subject"] for m in first["messages"]] == ["Order 0", "Order 1", "Order 2"], "oldest first, at most 3"
    assert first["messages"][0]["text"] == "Order body 0"
    second = await node.run({})
    assert [m["subject"] for m in second["messages"]] == ["Order 3", "Order 4"], "the backlog waited, nothing lost"
    assert (await node.run({}))["messages"] == []

    event = imap_node.ImapNode.resolve_agent_event({**second, "messages": second["messages"][:1]})
    assert event["text"].startswith(f"New email in {ANA}, INBOX")
    assert "Customer 3 <c3@x.test>" in event["text"] and "reply_to_message" in event["text"]


@pytest.mark.asyncio
async def test_a_message_that_cant_be_read_stays_new_for_the_next_poll(server, monkeypatch):
    node = _trigger(server)
    await node.run({})
    deliver(server, sender="a@x.test", to=ANA, subject="flaky read")
    real = mailbox.Imap.fetch
    calls = {"n": 0}

    def failing_fetch(self, uids, items):
        if "BODY.PEEK[]" in items and calls["n"] == 0:
            calls["n"] += 1
            raise mailbox.MailError("connection dropped while reading")
        return real(self, uids, items)

    monkeypatch.setattr(mailbox.Imap, "fetch", failing_fetch)
    with pytest.raises(mailbox.MailError, match="connection dropped"):
        await node.run({})
    retried = await node.run({})
    assert [m["subject"] for m in retried["messages"]] == ["flaky read"]


@pytest.mark.asyncio
async def test_the_arm_time_baseline_reads_no_message_and_filters_scope_the_trigger(server):
    deliver(server, sender="a@x.test", to=ANA, subject="already here")
    node = _trigger(server, sender="vip@client.test")
    node._poll_baseline_only = True
    assert (await node.run({}))["messages"] == []
    assert node.state["seen_ids"] == [], "only mail matching the filters is watched"
    node._poll_baseline_only = False
    deliver(server, sender="noise@x.test", to=ANA, subject="not for this trigger")
    deliver(server, sender="VIP <vip@client.test>", to=ANA, subject="Urgent")
    assert [m["subject"] for m in (await node.run({}))["messages"]] == ["Urgent"]


# --------------------------------------------------------------- bounding


@pytest.mark.asyncio
async def test_mail_work_leaves_the_event_loop_free(server):
    from tests.loop_watch import longest_loop_gap

    for n in range(3):
        deliver(server, sender="a@x.test", to=ANA, subject=f"m{n}", text="x" * 5000)
    result, gap = await longest_loop_gap(op(server, "search_messages"))
    assert result["count"] == 3
    assert gap < 0.5, f"the event loop stopped answering for {gap:.2f}s"


@pytest.mark.asyncio
async def test_a_server_that_stalls_is_cut_off_at_the_deadline(monkeypatch):
    silent = socket.socket()
    silent.bind(("127.0.0.1", 0))
    silent.listen(1)
    port = silent.getsockname()[1]
    held: List[socket.socket] = []
    threading.Thread(target=lambda: held.append(silent.accept()[0]), daemon=True).start()
    monkeypatch.setenv("OUTBOUND_ALLOW_PRIVATE_IPS", "true")
    monkeypatch.setitem(mailbox.IMAP_PORTS, port, "ssl")
    account = await mailbox.resolve_account(email_address=ANA, password="x", imap=("127.0.0.1", port, "ssl", ANA),
                                            smtp=("127.0.0.1", 465, "ssl", ANA))
    started = time.monotonic()
    with pytest.raises(mailbox.MailError, match="didn't finish listing folders within 1 seconds"):
        await mailbox.run_on_mailbox(lambda c: mailbox.Imap(account, c, timeout=60).folders(), deadline_s=1,
                                     what="listing folders")
    assert time.monotonic() - started < 5
    silent.close()
