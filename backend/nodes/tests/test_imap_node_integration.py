"""The IMAP/SMTP node against a real mailbox (Yahoo, iCloud, Zoho, Fastmail, …).

Runs only with a test mailbox's address and app password in the environment
(``IMAP_TEST_EMAIL``, ``IMAP_TEST_APP_PASSWORD``; ``IMAP_TEST_IMAP_HOST`` and
``IMAP_TEST_SMTP_HOST`` for a provider without a preset), and otherwise skips.
It sends mail from that mailbox to itself, replies to it, and moves both to
Trash when it's done. The same behaviour against a local server is
``tests/test_imap_greenmail.py``, which runs on every change.
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid

import pytest

from nodes.core.run_op import run_node_operation

EMAIL = os.getenv("IMAP_TEST_EMAIL")
PASSWORD = os.getenv("IMAP_TEST_APP_PASSWORD")

pytestmark = pytest.mark.skipif(not (EMAIL and PASSWORD), reason="IMAP_TEST_EMAIL / IMAP_TEST_APP_PASSWORD not set")


def _credential(password=None):
    blob = {"email": EMAIL, "password": password or PASSWORD}
    for key in ("imap_host", "imap_port", "smtp_host", "smtp_port"):
        value = os.getenv(f"IMAP_TEST_{key.upper()}")
        if value:
            blob[key] = value
    return blob


async def _op(operation, arguments=None):
    return await run_node_operation(node_type="automation-imap", operation=operation, arguments=arguments or {},
                                    user_id="imap-live-test", credential_data=_credential())


async def _arrival(subject, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        found = (await _op("search_messages", {"subject": subject, "limit": 5}))["messages"]
        if found:
            return found
        await asyncio.sleep(5)
    pytest.fail(f"{subject!r} didn't arrive within {timeout}s")


@pytest.fixture(autouse=True)
def _no_branding(monkeypatch):
    async def paid(*_a, **_k):
        return False

    monkeypatch.setattr("nodes.core.email_branding.sender_is_free_tier", paid)


@pytest.mark.asyncio
async def test_connecting_proves_the_mailbox_and_a_wrong_password_is_refused():
    from nodes.core.connection_evidence import collect_evidence

    ok = await collect_evidence(node_type="automation-imap", credential_data=_credential(), user_id="imap-live-test")
    assert ok.reachable is True and (ok.samples or ok.account_label)
    wrong = await collect_evidence(node_type="automation-imap", credential_data=_credential("wrongwrongwrong1"),
                                   user_id="imap-live-test")
    assert wrong.reachable is False and "authentication failed" in wrong.error


@pytest.mark.asyncio
async def test_send_read_reply_and_file_away_in_one_real_mailbox():
    folders = (await _op("list_folders"))["folders"]
    trash = next((f["name"] for f in folders if (f["special_use"] or "").lower() == "trash"), None)
    subject = f"NoClick IMAP check {uuid.uuid4().hex[:8]}"

    sent = await _op("send_email", {"to": [EMAIL], "subject": subject, "text": "First message.",
                                    "attachments": ["data:text/plain;base64,aGVsbG8K"]})
    [message] = await _arrival(subject)
    full = await _op("get_message", {"uid": message["uid"], "download_attachments": False})
    assert full["message_id"] == sent["message_id"] and full["text"].startswith("First message.")
    assert [a["filename"] for a in full["attachments"]] == ["file.txt"]

    await _op("mark_as_read", {"uid": message["uid"]})
    await _op("mark_as_unread", {"uid": message["uid"]})
    reply = await _op("reply_to_message", {"uid": message["uid"], "text": "And a reply."})
    found = await _arrival(f"Re: {subject}")
    replied = await _op("get_message", {"uid": found[0]["uid"]})
    assert replied["in_reply_to"] == sent["message_id"] and reply["thread"] == sent["message_id"]

    if trash:
        uids = ",".join(str(m["uid"]) for m in await _arrival(subject))
        await _op("move_message", {"uid": uids, "destination_folder": trash})
