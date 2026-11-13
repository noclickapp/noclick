"""Crisp plugin web hooks: every workspace that installed NoClick's Crisp
plugin delivers its events to one app-level URL (``/webhook/app/crisp``).

Crisp has no API to register a hook, and the hooks a workspace adds in its own
settings are unsigned and never retried; only a Marketplace plugin's hooks are
signed (``X-Crisp-Signature``) and retried. So NoClick hears Crisp through its
own plugin, configured by environment (``CRISP_PLUGIN_*``), and fans each event
out to the triggers subscribed to its workspace (``webhook_subscriptions``,
tenant = website id). Reference: https://docs.crisp.chat/references/web-hooks/v1/
"""

import hashlib
import hmac
import json
import logging
import os
from typing import Any, Dict, List, Optional

from utils.self_echo import is_self_post

logger = logging.getLogger(__name__)

PROVIDER = "crisp"
HOOK_SECRET_ENV = "CRISP_PLUGIN_HOOK_SECRET"
# A visitor's message. An operator's (and every message NoClick sends, which
# goes out as the operator) is ``message:received``.
VISITOR_MESSAGE = "message:send"


def sent_message_key(session_id: Optional[str], fingerprint: Any) -> Optional[str]:
    """One Crisp message wherever it's seen: a fingerprint is unique in its conversation."""
    if not session_id or fingerprint is None:
        return None
    return f"{session_id}:{fingerprint}"


def crisp_verify(pool, body: bytes, headers: Dict[str, str], request_url: str) -> bool:
    """HMAC-SHA256 (hex) of ``[timestamp;body]`` with the plugin hook's
    signing secret, over the raw body as Crisp's Go client checks it."""
    del pool, request_url
    secret = os.environ.get(HOOK_SECRET_ENV, "").strip()
    if not secret:
        logger.error(f"[app_webhooks] {HOOK_SECRET_ENV} is not configured")
        return False
    timestamp = headers.get("x-crisp-request-timestamp", "")
    signature = headers.get("x-crisp-signature", "")
    if not timestamp or not signature:
        return False
    trace = b"[" + timestamp.encode() + b";" + body + b"]"
    expected = hmac.new(secret.encode(), trace, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def crisp_parse(body: bytes) -> List[tuple]:
    """A visitor's message → one event for its workspace, its conversation as
    the channel (the fire budget's key). Operators' messages, notes and every
    other event are no trigger's."""
    try:
        envelope = json.loads(body) if body else {}
    except json.JSONDecodeError:
        return []
    data = envelope.get("data") if isinstance(envelope, dict) else None
    if envelope.get("event") != VISITOR_MESSAGE or not isinstance(data, dict) or data.get("from") != "user":
        return []
    website_id = envelope.get("website_id") or data.get("website_id")
    session_id = data.get("session_id")
    if not website_id or not session_id:
        return []
    return [(str(website_id), VISITOR_MESSAGE, envelope, str(session_id))]


async def crisp_drop_event(payload: Dict[str, Any]) -> Optional[str]:
    """A message a NoClick Crisp node sent never wakes a trigger (utils/self_echo.py)."""
    data = payload.get("data") or {}
    key = sent_message_key(data.get("session_id"), data.get("fingerprint"))
    if key and await is_self_post(PROVIDER, key):
        return f"message {key} was sent by a NoClick Crisp node"
    return None


def crisp_event_id(payload: Dict[str, Any]) -> Optional[str]:
    """Plugin hooks are retried: a message is one event however often it arrives."""
    data = payload.get("data") or {}
    return sent_message_key(data.get("session_id"), data.get("fingerprint"))


CRISP_WEBHOOK_ADAPTER = {
    "verify": crisp_verify,
    "handshake": lambda body: None,
    "parse": crisp_parse,
    "drop_event": crisp_drop_event,
    "event_id": crisp_event_id,
    "fire_budget": True,
}
