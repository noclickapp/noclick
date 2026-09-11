"""Facebook Page events prepared for isolated app-level webhook fan-out.

The receiver must authenticate the ORIGINAL body before calling this parser.
Every returned envelope contains exactly one Page and one event, preserving the
legacy Facebook node's ``object/entry`` contract without forwarding a whole
cross-customer batch. Registration and live credential checks remain required;
parsing an event is not authorization to execute a workflow.

Wire shapes: Meta's messenger-platform-samples/postman collection and the
Page Webhooks reference. All ten existing field triggers remain supported.
"""

import hashlib
from contextlib import asynccontextmanager
import json
import math
import re
from time import time as current_time
from uuid import UUID

from fastapi import HTTPException
from utils.app_delivery_guard import guard_app_delivery
from utils.redis_client import get_shared_redis


FB_WEBHOOK_FIELDS = [
    ("feed", "On Feed Activity"),
    ("mention", "On Page Mention"),
    ("ratings", "On New Rating"),
    ("messages", "On Message"),
    ("messaging_postbacks", "On Postback"),
    ("messaging_referrals", "On Referral"),
    ("message_reactions", "On Message Reaction"),
    ("message_deliveries", "On Message Delivered"),
    ("message_reads", "On Message Read"),
    ("standby", "On Standby (Handover)"),
]
CHANGE_FIELDS = frozenset({"feed", "mention", "ratings"})
MESSAGING_FIELDS = {
    "message": "messages",
    "postback": "messaging_postbacks",
    "referral": "messaging_referrals",
    "reaction": "message_reactions",
    "delivery": "message_deliveries",
    "read": "message_reads",
}
MAX_BODY_BYTES = 2 * 1024 * 1024
MAX_EVENT_AGE_SECONDS = 7 * 24 * 60 * 60
MAX_EVENT_FUTURE_SKEW_SECONDS = 300
EVENT_LEASE_SECONDS = 300
EVENT_PROCESSING_SECONDS = 240
EVENT_DEDUP_SECONDS = MAX_EVENT_AGE_SECONDS + MAX_EVENT_FUTURE_SKEW_SECONDS + 1
_NUMERIC_ID = re.compile(r"[1-9][0-9]{0,31}\Z")


def facebook_page_id(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    text = str(value)
    return text if _NUMERIC_ID.fullmatch(text) else None


def facebook_trigger_credential_id(credential_ids):
    """Managed callbacks bind to one company-app OAuth credential only.

    Manual/BYO app credentials keep the existing per-workflow callback path;
    accepting them here could route events signed by a different Meta app.
    """
    if not isinstance(credential_ids, dict):
        return None
    if credential_ids.get("credential_type") not in (None, "", "facebook_oauth"):
        return None
    populated = {key: value for key, value in credential_ids.items()
                 if value and key != "credential_type"}
    if set(populated) != {"facebook_oauth"}:
        return None
    try:
        return str(UUID(str(populated["facebook_oauth"])))
    except (ValueError, TypeError, AttributeError):
        return None


def facebook_event_matches_config(payload, config):
    """Pure live-graph gate; credential authorization MUST also be checked."""
    if not isinstance(payload, dict) or not isinstance(config, dict):
        return False
    page = facebook_page_id(payload.get("page_id"))
    field = payload.get("event_type")
    expected = "on_" + field if isinstance(field, str) else None
    return bool(
        payload.get("object") == "page" and page
        and isinstance(field, str) and field in dict(FB_WEBHOOK_FIELDS)
        and config.get("callback_mode") == "managed"
        and config.get("disabled") not in (True, "true")
        and facebook_page_id(config.get("page_id")) == page
        and config.get("operation") in (expected, "on_any_facebook_event")
        and facebook_trigger_credential_id(config.get("credentialIds"))
    )


@asynccontextmanager
async def facebook_event_guard(event_id):
    async with guard_app_delivery(
        event_id, client=get_shared_redis(), provider="facebook", label="Facebook",
        lease_seconds=EVENT_LEASE_SECONDS, processing_seconds=EVENT_PROCESSING_SECONDS,
        dedup_seconds=EVENT_DEDUP_SECONDS,
    ) as deliver:
        yield deliver


def _object(value):
    return value if isinstance(value, dict) else {}


def _items(value):
    return value if isinstance(value, list) else []


def _fresh_timestamp(value, *, now, milliseconds=False):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not 0 <= value <= 2**63 or not math.isfinite(value)):
        return False
    stamp = value / 1000 if milliseconds else value
    return now - MAX_EVENT_AGE_SECONDS <= stamp <= now + MAX_EVENT_FUTURE_SKEW_SECONDS


def _envelope(page, field, timestamp, item, transport, channel):
    # Arrival batch time/order and JSON formatting are not event identity.
    # Include the event's own time and complete content: edits/reactions/read
    # watermarks must not collapse into an earlier create/delivery event.
    try:
        identity = json.dumps([page, transport, timestamp, item], sort_keys=True,
                              separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        digest = hashlib.sha256(identity.encode()).hexdigest()
    except (TypeError, ValueError, UnicodeError, RecursionError):
        return None
    entry = {"id": page, transport: [item]}
    if transport == "changes":
        entry["time"] = timestamp
    envelope = {
        "object": "page", "page_id": page, "event_type": field,
        # Shared across field projections of the SAME message (postback with
        # referral): a wildcard node's per-subscription guard runs it once.
        "event_id": f"{page}:{transport}:{digest}", "timestamp": timestamp,
        "entry": [entry],
    }
    return page, field, envelope, channel


def parse_facebook_webhook(body: bytes) -> list:
    """Return (Page, field, isolated payload, conversation) tuples.

    Malformed/unsupported individual events are ignored, not allowed to poison
    other Pages in a valid batch. Oversized bodies are refused, and stale/future
    events cannot outlive the intended redelivery-guard retention window.
    """
    if len(body) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Facebook webhook payload too large")
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeError, RecursionError):
        return []
    if not isinstance(payload, dict) or payload.get("object") != "page":
        return []
    now = current_time()
    events = []
    for entry in _items(payload.get("entry")):
        entry = _object(entry)
        page = facebook_page_id(entry.get("id"))
        if not page:
            continue
        if _fresh_timestamp(entry.get("time"), now=now):
            for change in _items(entry.get("changes")):
                change = _object(change)
                field, value = change.get("field"), change.get("value")
                if not isinstance(field, str) or field not in CHANGE_FIELDS or not isinstance(value, dict) or not value:
                    continue
                # A post/comment scopes the fire budget more narrowly than
                # the whole Page; no sibling event enters this envelope.
                channel = value.get("post_id") or value.get("comment_id") or page
                if not isinstance(channel, (str, int)) or isinstance(channel, bool):
                    continue
                event = _envelope(page, field, entry["time"], change, "changes", str(channel))
                if event:
                    events.append(event)
        for transport in ("messaging", "standby"):
            for item in _items(entry.get(transport)):
                item = _object(item)
                sender = facebook_page_id(_object(item.get("sender")).get("id"))
                recipient = facebook_page_id(_object(item.get("recipient")).get("id"))
                if (not sender or not recipient or sender == recipient
                        or page not in (sender, recipient)
                        or not _fresh_timestamp(item.get("timestamp"), now=now, milliseconds=True)):
                    continue
                # The Page's own outbound message must never wake a responder.
                message = _object(item.get("message"))
                if message and (message.get("is_echo") or message.get("is_deleted") or sender == page):
                    continue
                # Referral metadata can accompany a postback; route to both
                # requested fields without duplicating any unrelated event.
                fields = [field for key, field in MESSAGING_FIELDS.items()
                          if isinstance(item.get(key), dict) and item[key]]
                if transport == "standby":
                    fields = ["standby"] if fields else []
                channel = recipient if sender == page else sender
                for field in fields:
                    event = _envelope(page, field, item["timestamp"], item, transport, channel)
                    if event:
                        events.append(event)
    return events
