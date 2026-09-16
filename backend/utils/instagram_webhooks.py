"""Signed Instagram Login webhooks, isolated to the currently connected account."""

from contextlib import asynccontextmanager
import hmac
import json
import logging
import math
import os
import re
import uuid
from time import time as current_time
from urllib.parse import urlsplit

from fastapi import HTTPException
from fastapi.responses import PlainTextResponse

from utils.credential_loader import load_credential
from utils.app_delivery_guard import guard_app_delivery
from utils.graph_nodes import node_config
from utils.redis_client import get_shared_redis
from utils.webhook_signatures import verify_hmac_sha256_hex

_NUMERIC_ID = re.compile(r"[1-9][0-9]{0,31}\Z")
_EVENT_OPERATIONS = {"comments": "on_comment", "messages": "on_message", "mentions": "on_mention"}
EVENT_LEASE_SECONDS = 300
EVENT_PROCESSING_SECONDS = 240
MAX_EVENT_AGE_SECONDS = 7 * 24 * 60 * 60
MAX_EVENT_FUTURE_SKEW_SECONDS = 300
EVENT_DEDUP_SECONDS = MAX_EVENT_AGE_SECONDS + MAX_EVENT_FUTURE_SKEW_SECONDS + 1
MAX_BODY_BYTES = 2 * 1024 * 1024
logger = logging.getLogger(__name__)


def instagram_account_id(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    value = str(value)
    return value if _NUMERIC_ID.fullmatch(value) else None


def instagram_login_credential_id(credential_ids):
    if not isinstance(credential_ids, dict):
        return None
    if credential_ids.get("credential_type") not in (None, "", "instagram_login"):
        return None
    populated = {key: str(value) for key, value in credential_ids.items()
                 if value and key != "credential_type"}
    if set(populated) != {"instagram_login"}:
        return None
    try:
        return str(uuid.UUID(populated["instagram_login"]))
    except (ValueError, TypeError, AttributeError):
        return None


def require_instagram_webhook_configuration() -> str:
    """Return the non-secret Meta app ID; never expose configuration values."""
    for key in ("INSTAGRAM_WEBHOOK_APP_SECRET", "INSTAGRAM_WEBHOOK_VERIFY_TOKEN"):
        if not (os.environ.get(key) or "").strip():
            raise ValueError(f"{key} is required for Instagram webhook registration")
    app_id = instagram_account_id(os.environ.get("INSTAGRAM_WEBHOOK_APP_ID"))
    if not app_id:
        raise ValueError("INSTAGRAM_WEBHOOK_APP_ID must identify the Meta app")
    base = urlsplit(os.environ.get("APP_WEBHOOK_BASE_URL") or "")
    if (base.scheme != "https" or not base.hostname or base.username or base.password
            or base.query or base.fragment or base.path not in ("", "/")):
        raise ValueError("APP_WEBHOOK_BASE_URL must be a public HTTPS origin")
    return app_id


def verify_instagram_webhook(pool, body: bytes, headers: dict, request_url: str) -> bool:
    del pool, request_url
    secret = os.environ.get("INSTAGRAM_WEBHOOK_APP_SECRET") or ""
    signature = headers.get("x-hub-signature-256", "")
    if not signature:
        reason = "missing_header"
    elif not isinstance(signature, str) or not re.fullmatch(r"sha256=[0-9a-f]{64}", signature):
        reason = "invalid_format"
    elif not secret.strip():
        reason = "missing_secret"
    elif not verify_hmac_sha256_hex(body, secret, signature, prefix="sha256="):
        reason = "mismatch"
    else:
        return True
    # Fixed categories only: never log the request body, header, secret or
    # derived digests. These distinguish configuration from transport faults
    # without changing verification or trying another signing key.
    logger.warning("Instagram webhook signature rejected: %s", reason)
    return False


def instagram_handshake(query) -> PlainTextResponse:
    expected = os.environ.get("INSTAGRAM_WEBHOOK_VERIFY_TOKEN") or ""
    supplied = query.get("hub.verify_token", "")
    if (not expected.strip() or not isinstance(supplied, str)
            or not hmac.compare_digest(expected.encode(), supplied.encode())
            or query.get("hub.mode") != "subscribe"):
        raise HTTPException(status_code=403, detail="Invalid Instagram webhook verification")
    challenge = query.get("hub.challenge")
    if not isinstance(challenge, str) or not challenge or len(challenge) > 1024:
        raise HTTPException(status_code=400, detail="Missing or invalid webhook challenge")
    return PlainTextResponse(challenge, headers={"Cache-Control": "no-store"})


def _object(value):
    return value if isinstance(value, dict) else {}


def _items(value):
    return value if isinstance(value, list) else []


def _timestamp(value):
    return value if (isinstance(value, (int, float)) and not isinstance(value, bool)
                     and 0 <= value <= 2**63 and math.isfinite(value)) else None


def _fresh_timestamp(value, *, milliseconds=False):
    stamp = _timestamp(value)
    if stamp is None:
        return False
    seconds = stamp / 1000 if milliseconds else stamp
    now = current_time()
    return now - MAX_EVENT_AGE_SECONDS <= seconds <= now + MAX_EVENT_FUTURE_SKEW_SECONDS


def mentions_username(text, username):
    """Match an entire Instagram handle, never @name_extra or email addresses."""
    return bool(isinstance(text, str) and username and re.search(
        rf"(?<![\w.])@{re.escape(username.lstrip('@'))}(?![\w.])", text, re.IGNORECASE,
    ))


def _mention_data(value, field):
    """Normalize full comment notifications and ID-only mention notifications.

    Instagram Login carries mentions under the comments subscription; Facebook
    Login's documented mentions shape uses comment_id/media_id. Keep accepting
    that shape without requiring Facebook Login credentials for this trigger.
    """
    media_id = instagram_account_id(value.get("media_id")) or instagram_account_id(_object(value.get("media")).get("id"))
    comment_id = instagram_account_id(value.get("comment_id"))
    if not comment_id and field == "comments" and value.get("id"):
        # Ordinary comments share this subscription. The live credential guard
        # checks WHICH username was mentioned before enqueueing a workflow.
        if not re.search(r"(?<![\w.])@[\w.]+", str(value.get("text") or "")):
            return None
        comment_id = instagram_account_id(value.get("id"))
    if not media_id:
        return None
    if comment_id:
        kind = "comment"
    elif value.get("media_id") and not value.get("comment_id") and not value.get("id"):
        kind = "caption"
    else:
        return None
    return {**value, "mention_type": kind, "comment_id": comment_id, "media_id": media_id}


def parse_instagram_webhook(body: bytes) -> list:
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeError):
        return []
    if not isinstance(payload, dict) or payload.get("object") != "instagram":
        return []
    events = []
    for entry in _items(payload.get("entry")):
        entry = _object(entry)
        account = instagram_account_id(entry.get("id"))
        if not account:
            continue
        changes = _items(entry.get("changes"))
        if entry.get("field") in ("comments", "mentions"):
            changes = [*changes, entry]
        for change in changes:
            change = _object(change)
            field = change.get("field")
            if field not in ("comments", "mentions") or not _fresh_timestamp(entry.get("time")):
                continue
            value = _object(change.get("value"))
            mention = _mention_data(value, field)
            author_id = instagram_account_id(_object(value.get("from")).get("id"))
            if mention and author_id != account:
                object_id = mention["comment_id"] or mention["media_id"]
                events.append(_event(account, "mentions", f"{mention['mention_type']}:{object_id}",
                                     entry.get("time"), mention, mention["media_id"]))
            if field != "comments":
                continue
            comment_id = instagram_account_id(value.get("id"))
            author = instagram_account_id(_object(value.get("from")).get("id"))
            username = _object(value.get("from")).get("username")
            media = instagram_account_id(_object(value.get("media")).get("id"))
            if (not comment_id or not media or author == account
                    or not _fresh_timestamp(entry.get("time"))
                    or (not author and (not isinstance(username, str) or not username.strip()))):
                continue
            events.append(_event(account, "comments", comment_id, entry.get("time"), value, media))
        for message_event in _items(entry.get("messaging")):
            message_event = _object(message_event)
            sender = instagram_account_id(_object(message_event.get("sender")).get("id"))
            recipient = instagram_account_id(_object(message_event.get("recipient")).get("id"))
            message = _object(message_event.get("message"))
            message_id = message.get("mid")
            if (not sender or sender == account or recipient != account
                    or not _fresh_timestamp(message_event.get("timestamp"), milliseconds=True)
                    or not isinstance(message_id, str) or not message_id or len(message_id) > 1024
                    or message.get("is_echo") or message_event.get("is_echo")
                    or message.get("is_deleted") or message.get("is_self")):
                continue
            events.append(_event(account, "messages", message_id,
                                 message_event.get("timestamp"), message_event, sender))
    return events


def _event(account, event_type, provider_id, timestamp, data, channel):
    # Only this individual event crosses the tenant boundary, never its batch.
    envelope = {
        "object": "instagram", "account_id": account, "event_type": event_type,
        "event_id": f"{account}:{event_type}:{provider_id}",
        "timestamp": _timestamp(timestamp), "data": data,
    }
    return account, event_type, envelope, channel


async def instagram_live_scope_filter(pool, sub: dict, payload: dict, trigger_node: dict):
    config = node_config(trigger_node)
    if config.get("disabled") in (True, "true"):
        return "Instagram trigger is disabled"
    event_type = payload.get("event_type")
    account = instagram_account_id(payload.get("account_id"))
    if (trigger_node.get("type") != "automation-instagram" or not account
            or sub.get("provider") != "instagram" or sub.get("event_type") != event_type
            or str(sub.get("tenant_id")) != account
            or config.get("operation") != _EVENT_OPERATIONS.get(event_type)):
        return "Instagram trigger or account binding changed"
    credential_id = instagram_login_credential_id(config.get("credentialIds"))
    if not credential_id or credential_id != str(sub.get("credential_id")):
        return "Instagram Login credential binding changed"
    credential = await load_credential(pool, str(sub["user_id"]), credential_id, raise_on_error=True)
    if (not credential or credential.get("credential_type") != "instagram_login"
            or instagram_account_id(credential.get("instagram_user_id")) != account):
        return "Instagram credential is unavailable or belongs to another account"
    if event_type in ("comments", "mentions"):
        author = _object(_object(payload.get("data")).get("from"))
        username = str(author.get("username") or "").casefold()
        own_username = str(credential.get("instagram_username") or "").casefold()
        if username and own_username and username == own_username:
            return "Instagram account's own comment"
        if event_type == "comments" and not instagram_account_id(author.get("id")) and not own_username:
            return "Instagram comment author cannot be safely identified"
        if event_type == "mentions":
            data = _object(payload.get("data"))
            if own_username and isinstance(data.get("text"), str) and not mentions_username(data["text"], own_username):
                return "Instagram event does not mention the connected account"
            return None
    field = "media_id" if event_type == "comments" else "sender_id"
    expected = config.get(field)
    if expected:
        data = _object(payload.get("data"))
        actual = _object(data.get("media" if event_type == "comments" else "sender")).get("id")
        if instagram_account_id(expected) != instagram_account_id(actual):
            return "Instagram event does not match the configured filter"
    return None


@asynccontextmanager
async def instagram_event_guard(event_id: str):
    """Serialize fan-out; a failed attempt remains retryable, never fail open.

    This protects enqueueing, not durable execution: process loss after marking
    but before running background tasks still requires a durable queue to close.
    """
    async with guard_app_delivery(
        event_id, client=get_shared_redis(), provider="instagram", label="Instagram",
        lease_seconds=EVENT_LEASE_SECONDS, processing_seconds=EVENT_PROCESSING_SECONDS,
        dedup_seconds=EVENT_DEDUP_SECONDS,
    ) as deliver:
        yield deliver


INSTAGRAM_WEBHOOK_ADAPTER = {
    "max_body_bytes": MAX_BODY_BYTES,
    "verify": verify_instagram_webhook,
    "handshake": lambda body: None,
    "parse": parse_instagram_webhook,
    "event_id": lambda payload: payload["event_id"],
    "event_guard": instagram_event_guard,
    "subscription_guard": instagram_event_guard,
    "live_scope_filter": instagram_live_scope_filter,
    "fire_budget": True,
}
