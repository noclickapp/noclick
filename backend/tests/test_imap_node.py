"""The IMAP/SMTP node without a server: what the connect form turns a typed-in
mailbox into (provider presets, pasted hosts, refused hosts and ports, Gmail and
Outlook pointed to their own steps), the agent-tool surface, the agent event a
new email becomes, and the protocol parsing its server tests rely on. Its
behaviour against a real mail server is ``test_imap_greenmail.py``."""

from __future__ import annotations

import pytest

from nodes import imap_mailbox as mailbox
from nodes.core.credential_connect import shape_credential, validate_for_connect
from nodes.imap_node import ImapCredential, ImapNode

YAHOO = ("imap.mail.yahoo.com", 993, "ssl", "smtp.mail.yahoo.com", 465, "ssl")


def shaped(**blob):
    data, errors, _ = shape_credential("imap_smtp", {"password": "app-password", **blob})
    return data, errors


def servers(data):
    return tuple(data[k] for k in ("imap_host", "imap_port", "imap_security", "smtp_host", "smtp_port",
                                   "smtp_security"))


@pytest.mark.parametrize("address,expected", [
    ("me@yahoo.com", YAHOO),
    ("me@ymail.com", YAHOO),
    ("me@yahoo.co.uk", YAHOO),
    ("me@yahoo.co.in", YAHOO),
    ("me@aol.com", ("imap.aol.com", 993, "ssl", "smtp.aol.com", 465, "ssl")),
    ("me@verizon.net", ("imap.aol.com", 993, "ssl", "smtp.aol.com", 465, "ssl")),
    ("me@icloud.com", ("imap.mail.me.com", 993, "ssl", "smtp.mail.me.com", 587, "starttls")),
    ("me@me.com", ("imap.mail.me.com", 993, "ssl", "smtp.mail.me.com", 587, "starttls")),
    ("me@mac.com", ("imap.mail.me.com", 993, "ssl", "smtp.mail.me.com", 587, "starttls")),
    ("me@zoho.com", ("imap.zoho.com", 993, "ssl", "smtp.zoho.com", 465, "ssl")),
    ("me@zohomail.com", ("imap.zoho.com", 993, "ssl", "smtp.zoho.com", 465, "ssl")),
    ("me@zohomail.eu", ("imap.zoho.eu", 993, "ssl", "smtp.zoho.eu", 465, "ssl")),
    ("me@zohomail.in", ("imap.zoho.in", 993, "ssl", "smtp.zoho.in", 465, "ssl")),
    ("me@fastmail.com", ("imap.fastmail.com", 993, "ssl", "smtp.fastmail.com", 465, "ssl")),
    ("me@fastmail.fm", ("imap.fastmail.com", 993, "ssl", "smtp.fastmail.com", 465, "ssl")),
    ("me@gmx.com", ("imap.gmx.com", 993, "ssl", "mail.gmx.com", 465, "ssl")),
    ("me@gmx.co.uk", ("imap.gmx.com", 993, "ssl", "mail.gmx.com", 465, "ssl")),
    ("me@gmx.net", ("imap.gmx.net", 993, "ssl", "mail.gmx.net", 465, "ssl")),
    ("me@gmx.de", ("imap.gmx.net", 993, "ssl", "mail.gmx.net", 465, "ssl")),
    ("me@mail.com", ("imap.mail.com", 993, "ssl", "smtp.mail.com", 465, "ssl")),
    ("me@email.com", ("imap.mail.com", 993, "ssl", "smtp.mail.com", 465, "ssl")),
])
def test_a_known_provider_needs_only_an_address_and_an_app_password(address, expected):
    data, errors = shaped(email=address)
    assert not errors
    assert servers(data) == expected


def test_the_address_is_tidied_and_a_grouped_app_password_loses_its_spaces():
    data, errors = shaped(email=" Dhruv@Yahoo.COM ", password="abcd efgh ijkl mnop")
    assert not errors
    assert data["email"] == "Dhruv@yahoo.com"
    assert data["password"] == "abcdefghijklmnop"
    # A password a person chose keeps its spaces.
    assert shaped(email="me@yahoo.com", password="correct horse battery")[0]["password"] == "correct horse battery"


def test_icloud_signs_in_to_imap_with_the_name_before_the_at():
    credential = ImapCredential.model_validate({"email": "emily@icloud.com", "password": "x"})
    assert credential.logins() == ("emily", "emily@icloud.com")
    assert ImapCredential.model_validate({"email": "me@yahoo.com", "password": "x"}).logins() == (
        "me@yahoo.com", "me@yahoo.com")
    named = ImapCredential.model_validate({"email": "me@acme.io", "password": "x", "username": "ME01",
                                          "imap_host": "mail.acme.io", "smtp_host": "mail.acme.io"})
    assert named.logins() == ("ME01", "ME01")


@pytest.mark.parametrize("address,word", [
    ("me@gmail.com", "Gmail"), ("me@googlemail.com", "Gmail"),
    ("me@outlook.com", "Outlook"), ("me@hotmail.com", "Outlook"), ("me@live.com", "Outlook"),
])
def test_gmail_and_outlook_point_to_their_own_steps(address, word):
    _, errors = shaped(email=address)
    assert errors["email"].startswith(f"{word} doesn't take an app password here")
    assert "signs in with" in errors["email"]


def test_an_unknown_provider_asks_for_its_servers_and_takes_them_as_pasted():
    _, errors = shaped(email="me@acme.io")
    assert "enter the IMAP and SMTP servers" in errors["email"]
    _, errors = shaped(email="me@acme.io", imap_host="mail.acme.io")
    assert errors["email"] == "Under More options, enter the SMTP server too."
    data, errors = shaped(email="me@acme.io", imap_host="imaps://Mail.Acme.io:993/", smtp_host="mail.acme.io:587")
    assert not errors
    assert servers(data) == ("mail.acme.io", 993, "ssl", "mail.acme.io", 587, "starttls")
    data, _ = shaped(email="me@acme.io", imap_host="mail.acme.io", imap_port="143", smtp_host="mail.acme.io",
                     smtp_port="465", imap_security="auto", smtp_security="")
    assert servers(data) == ("mail.acme.io", 143, "starttls", "mail.acme.io", 465, "ssl")
    data, _ = shaped(email="me@acme.io", imap_host="mail.acme.io", smtp_host="mail.acme.io", smtp_security="starttls")
    assert data["smtp_port"] == 587


@pytest.mark.parametrize("field,value,message", [
    ("imap_host", "10.0.0.5", "on a private network"),
    ("imap_host", "169.254.169.254", "on a private network"),
    ("imap_host", "localhost", "on a private network"),
    ("smtp_host", "mail.corp.internal", "on a private network"),
    ("imap_host", "not a host!", "should be a host name"),
    ("imap_port", "22", "IMAP port must be one a mail server uses"),
    ("smtp_port", "8080", "SMTP port must be one a mail server uses"),
    ("password", "https://login.yahoo.com", "looks like a web address"),
])
def test_what_no_mailbox_can_be_is_refused_under_its_own_field(field, value, message):
    blob = {"email": "me@acme.io", "imap_host": "mail.acme.io", "smtp_host": "mail.acme.io", field: value}
    _, errors = shaped(**blob)
    assert message in errors[field]


def test_a_refused_credential_never_shows_its_password():
    with pytest.raises(Exception) as caught:
        ImapCredential.model_validate({"email": "not an address", "password": "hunter2-secret"})
    assert "hunter2-secret" not in str(caught.value)
    assert "hunter2-secret" not in repr(ImapCredential.model_validate({"email": "me@yahoo.com",
                                                                      "password": "hunter2-secret"}))
    account = mailbox.Account("me@yahoo.com", None, None, "hunter2-secret")  # type: ignore[arg-type]
    assert "hunter2-secret" not in repr(account)


@pytest.mark.asyncio
async def test_a_host_that_resolves_inside_the_network_is_refused_before_any_connection(monkeypatch):
    monkeypatch.delenv("OUTBOUND_ALLOW_PRIVATE_IPS", raising=False)
    monkeypatch.delenv("HTTP_NODE_ALLOW_PRIVATE_IPS", raising=False)

    async def private(host, port, **_):
        from utils.ssrf import SSRFError

        raise SSRFError(f"Refusing to connect to '{host}' — it resolves to non-public address 10.1.2.3")

    monkeypatch.setattr("utils.ssrf.resolve_host_addresses", private)
    credential = ImapCredential.model_validate({"email": "me@acme.io", "password": "x",
                                                "imap_host": "mail.acme.io", "smtp_host": "mail.acme.io"})
    with pytest.raises(mailbox.MailError, match="non-public address 10.1.2.3"):
        await credential.account()


@pytest.mark.asyncio
async def test_a_port_outside_the_mail_ports_is_never_dialled(monkeypatch):
    monkeypatch.setenv("OUTBOUND_ALLOW_PRIVATE_IPS", "true")
    with pytest.raises(ValueError, match="IMAP port must be"):
        await mailbox.resolve_account(email_address="me@acme.io", password="x", imap=("127.0.0.1", 6379, "ssl", "me"),
                                      smtp=("127.0.0.1", 465, "ssl", "me"))


@pytest.mark.asyncio
async def test_the_connect_form_names_each_field_that_is_wrong_without_probing():
    verdict = await validate_for_connect(credential_type="imap_smtp", credential_data={
        "email": "me@acme.io", "password": "x", "imap_host": "mail.acme.io", "smtp_host": "mail.acme.io",
        "smtp_port": "8080"}, user_id="u1", probe=False)
    assert not verdict.ok and set(verdict.field_errors) == {"smtp_port"}
    verdict = await validate_for_connect(credential_type="imap_smtp", credential_data={
        "email": "me@yahoo.com", "password": "abcd efgh ijkl mnop"}, user_id="u1", probe=False)
    assert verdict.ok and verdict.credential_data["imap_host"] == "imap.mail.yahoo.com"


# ---------------------------------------------------------- agent surface


def test_every_operation_but_the_trigger_is_an_agent_tool():
    from nodes.agent.node_op_tools import build_node_op_tools, list_node_operations, node_supports_op_tools

    assert node_supports_op_tools("automation-imap")
    ops = {o["operation"] for o in list_node_operations("automation-imap")}
    assert ops == {"list_folders", "check_connection", "search_messages", "get_message", "mark_as_read",
                   "mark_as_unread", "move_message", "send_email", "reply_to_message"}
    params, configs = build_node_op_tools("automation-imap", ["reply_to_message", "search_messages"], node_id="n1")
    names = {p["function"]["name"] for p in params}
    assert {"imap__reply_to_message", "imap__search_messages", "imap__lookup_options"} <= names
    reply = next(p for p in params if p["function"]["name"] == "imap__reply_to_message")["function"]
    assert {"folder", "uid", "text", "reply_all"} <= set(reply["parameters"]["properties"])


@pytest.mark.parametrize("value,expected", [(1234, "1234"), ("1234", "1234"), (" 12 , 13 ", "12,13"),
                                            ([5, 6, 5], "5,6")])
def test_uids_arrive_as_numbers_lists_or_text(value, expected):
    from nodes.imap_node import ImapMarkAsReadConfig

    assert ImapMarkAsReadConfig(operation="mark_as_read", uid=value).uid == expected


@pytest.mark.parametrize("value", ["", "abc", "0", "12;13", True])
def test_a_uid_is_a_positive_number(value):
    from nodes.imap_node import ImapGetMessageConfig

    with pytest.raises(ValueError):
        ImapGetMessageConfig(operation="get_message", uid=value)


def test_one_message_is_read_once_and_one_uid_per_get():
    from nodes.imap_node import ImapGetMessageConfig

    with pytest.raises(ValueError, match="one message's UID"):
        ImapGetMessageConfig(operation="get_message", uid="1,2")


def test_a_message_needs_a_body():
    from nodes.imap_node import ImapSendEmailConfig

    with pytest.raises(ValueError, match="Write the message"):
        ImapSendEmailConfig(operation="send_email", to=["a@b.test"], subject="Hi")
    assert ImapSendEmailConfig(operation="send_email", to="a@b.test", subject="Hi", html="<p>x</p>").to == ["a@b.test"]


def test_one_new_email_is_one_threaded_conversation_with_its_attachments_as_media():
    attachment = {"filename": "scan.pdf", "mime_type": "application/pdf", "size_bytes": 4096,
                  "url": "https://files.test/scan.pdf", "resource_id": "res-1"}
    event = ImapNode.resolve_agent_event({"account": "ana@yahoo.com", "folder": "INBOX", "messages": [{
        "folder": "INBOX", "uid": 77, "from": "Priya <priya@client.test>", "subject": "Signed scan",
        "date": "2026-11-10T09:00:00+00:00", "text": "Here it is.", "thread": "<root@client.test>",
        "attachments": [attachment]}]})
    assert event["conversation_key"] == "<root@client.test>"
    assert event["title"] == "Signed scan"
    assert event["text"].startswith("New email in ana@yahoo.com, INBOX")
    assert "Folder: INBOX, UID 77" in event["text"] and "Here it is." in event["text"]
    assert "reply_to_message with folder 'INBOX' and uid 77" in event["text"]
    [media] = event["media"]
    assert media["resource_id"] == "res-1" and media["mime_type"] == "application/pdf" and media["record"] is attachment


def test_a_batch_keys_no_conversation_and_an_empty_poll_is_no_event():
    batch = {"folder": "INBOX", "messages": [{"uid": n, "subject": f"s{n}", "thread": f"<t{n}@x>"}
                                              for n in range(7)]}
    event = ImapNode.resolve_agent_event(batch)
    assert event["conversation_key"] is None and event["title"] == "7 new emails"
    assert "…and 2 more: s5; s6" in event["text"]
    assert ImapNode.resolve_agent_event({"folder": "INBOX", "messages": []}) is None
    assert ImapNode.should_propagate_output({"new_message_count": 0}, {"operation": "on_new_email"}) is False
    assert ImapNode.should_propagate_output({"new_message_count": 2}, {"operation": "on_new_email"}) is True


def test_the_trigger_is_a_poll_in_the_schedule_family():
    assert ImapNode._is_schedule_operation("on_new_email")
    assert not ImapNode._is_schedule_operation("search_messages")


# ------------------------------------------------------------ protocol


def test_a_fetch_answer_regroups_per_message_whichever_order_the_server_writes():
    data = [
        (b'1 (UID 41 FLAGS (\\Seen) RFC822.SIZE 900 BODY[HEADER.FIELDS (FROM SUBJECT)] {30}',
         b"From: a@x.test\r\nSubject: A\r\n"),
        (b' BODY[]<0> {5}', b"hello"),
        b')',
        (b'2 (BODY[HEADER.FIELDS (FROM SUBJECT)] {14}', b"From: b@x.test"),
        b' UID 42 FLAGS () INTERNALDATE "10-Nov-2026 09:00:00 +0000")',
        b'3 (UID 43 FLAGS (\\Answered))',
    ]
    parsed = mailbox._parse_fetch(data)
    assert parsed[41]["flags"] == ["\\Seen"] and parsed[41]["size"] == 900
    assert parsed[41]["header"].startswith(b"From: a@x.test") and parsed[41]["body"] == b"hello"
    assert parsed[42]["header"] == b"From: b@x.test" and parsed[42]["internal_date"] == "2026-11-10T09:00:00+00:00"
    assert parsed[43]["flags"] == ["\\Answered"] and parsed[43]["body"] is None


@pytest.mark.parametrize("name", ["INBOX", "Envoyés", "Brouillons & notes", "日本語", "Archive/2026", "😀 Fun"])
def test_folder_names_round_trip_through_modified_utf7(name):
    encoded = mailbox.encode_folder(name)
    assert encoded.isascii()
    assert mailbox.decode_folder(encoded) == name
    assert mailbox.encode_folder("Envoyés") == "Envoy&AOk-s"


def test_a_reply_goes_to_reply_to_and_reply_all_leaves_out_this_mailbox():
    from nodes.imap_node import _reply_recipients

    original = {"from": "Bob <bob@x.test>", "reply_to": "Desk <desk@x.test>", "to": "me@yahoo.com, carol@x.test",
                "cc": "Me <ME@yahoo.com>, dan@x.test"}
    assert _reply_recipients(original, "me@yahoo.com", False) == (["desk@x.test"], [])
    assert _reply_recipients(original, "me@yahoo.com", True) == (["desk@x.test"], ["carol@x.test", "dan@x.test"])


def test_a_composed_message_refuses_a_header_smuggled_into_a_field():
    with pytest.raises(ValueError):
        mailbox.compose(sender="me@yahoo.com", from_name=None, to=["a@x.test"], cc=[],
                        subject="Hi\r\nBcc: everyone@x.test", text="x", html=None)
    message = mailbox.compose(sender="me@yahoo.com", from_name="Me", to=["a@x.test"], cc=[], subject="Hi",
                              text=None, html="<p>Hello <b>there</b></p>", in_reply_to="<m1@x>",
                              references=["<r@x>", "<m1@x>"])
    assert message.get_body(("plain",)).get_content().strip() == "Hello there"
    assert message["In-Reply-To"] == "<m1@x>" and message["References"] == "<r@x> <m1@x>"
    assert message["Message-ID"].endswith("@yahoo.com>")
