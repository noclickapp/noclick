"""Provider adapters for app-level event webhooks (Slack, HubSpot, Discord).

Slack and HubSpot deliver every event for the whole NoClick app to one shared
URL. Each adapter knows how to verify a request against the app secret, answer
any handshake, and parse the body into
``(tenant_id, event_type, payload, event_channel)`` tuples that the receiver
fans out to subscribed workflows.

App secrets come from env (the ``backend-secrets`` managed secret): ``SLACK_SIGNING_SECRET``
and ``HUBSPOT_CLIENT_SECRET``.
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from fastapi import Response

from nodes.core.webhook_subscriptions import get_verification_key
from utils.webhook_signatures import (
    verify_ed25519,
    verify_hubspot_v3,
    verify_slack_v0,
)

logger = logging.getLogger(__name__)

# A parsed event: (tenant_id, event_type, payload, event_channel)
# event_channel is the channel the event occurred in, or None for events with
# no channel (workspace-level events, HubSpot). It feeds the fan-out filter.
ParsedEvent = Tuple[str, str, Dict[str, Any], Optional[str]]

_HUBSPOT_OBJECT_TYPE_IDS = {
    "0-1": "contact",
    "0-2": "company",
    "0-3": "deal",
    "0-5": "ticket",
}


# ============================================================================
# Slack
# ============================================================================


def _slack_verify(pool, body: bytes, headers: Dict[str, str], request_url: str) -> bool:
    del pool, request_url
    secret = os.environ.get("SLACK_SIGNING_SECRET")
    if not secret:
        logger.error("[app_webhooks] SLACK_SIGNING_SECRET is not configured")
        return False
    return verify_slack_v0(
        body,
        headers.get("x-slack-request-timestamp", ""),
        headers.get("x-slack-signature", ""),
        secret,
    )


def _slack_handshake(body: bytes) -> Dict[str, Any] | None:
    """Slack sends a one-off url_verification challenge when the Request URL
    is first configured — echo the challenge back."""
    try:
        data = json.loads(body) if body else {}
    except json.JSONDecodeError:
        return None
    if data.get("type") == "url_verification":
        return {"challenge": data.get("challenge", "")}
    return None


def _slack_parse(body: bytes) -> List[ParsedEvent]:
    try:
        data = json.loads(body) if body else {}
    except json.JSONDecodeError:
        return []
    if data.get("type") != "event_callback":
        return []
    team_id = data.get("team_id")
    event = data.get("event") or {}
    event_type = event.get("type")
    if not team_id or not event_type:
        return []
    # Drop THIS app's own bot-authored messages (send_as="bot" posts and
    # chat.scheduleMessage deliveries) — a channel agent replying into its
    # trigger channel must not re-trigger itself. Foreign bots pass: agents
    # legitimately react to other apps' messages. send_as="user" posts carry
    # no authorship marker at all — those are caught by the fingerprint check
    # (_slack_drop_event / utils.slack_self_echo).
    if event_type in ("message", "app_mention"):
        authored_app = event.get("app_id") or (event.get("bot_profile") or {}).get("app_id")
        receiving_app = data.get("api_app_id")
        if authored_app and receiving_app and authored_app == receiving_app:
            logger.info(
                f"[APP-WEBHOOK] Dropping own-bot {event_type} in "
                f"{event.get('channel')} (app {authored_app})"
            )
            return []
    # Channel scoping — different Slack event types carry the channel under
    # different keys (message/app_mention/member_joined_channel: "channel";
    # file_shared: "channel_id"; reaction_added: "item.channel").
    channel = (
        event.get("channel")
        or event.get("channel_id")
        or (event.get("item") or {}).get("channel")
    )
    channel = channel if isinstance(channel, str) else None
    return [(str(team_id), str(event_type), data, channel)]


# ============================================================================
# HubSpot
# ============================================================================


def _hubspot_verify(
    pool, body: bytes, headers: Dict[str, str], request_url: str
) -> bool:
    del pool
    secret = os.environ.get("HUBSPOT_CLIENT_SECRET")
    if not secret:
        logger.error("[app_webhooks] HUBSPOT_CLIENT_SECRET is not configured")
        return False
    return verify_hubspot_v3(
        "POST",
        request_url,
        body,
        headers.get("x-hubspot-request-timestamp", ""),
        headers.get("x-hubspot-signature-v3", ""),
        secret,
    )


def _hubspot_handshake(body: bytes) -> Dict[str, Any] | None:
    return None  # HubSpot has no handshake — it just starts delivering


def _hubspot_object_type_name(item: Dict[str, Any]) -> Optional[str]:
    object_type = item.get("objectType")
    if isinstance(object_type, str) and object_type:
        return object_type
    object_type_id = item.get("objectTypeId")
    if isinstance(object_type_id, str) and object_type_id:
        return _HUBSPOT_OBJECT_TYPE_IDS.get(object_type_id, object_type_id)
    return None


def _hubspot_parse(body: bytes) -> List[ParsedEvent]:
    try:
        data = json.loads(body) if body else []
    except json.JSONDecodeError:
        return []
    items = data if isinstance(data, list) else [data]
    events: List[ParsedEvent] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        portal_id = item.get("portalId")
        # Legacy app webhooks send subscriptionType (e.g. contact.creation).
        # Project-based HubSpot webhooks use eventType. Generic CRM object
        # subscriptions may arrive as object.creation + objectType/objectTypeId;
        # our internal subscription rows are keyed by the legacy-style names, so
        # normalize the generic form before fan-out lookup.
        event_type = item.get("subscriptionType") or item.get("eventType")
        object_type = _hubspot_object_type_name(item)
        if (
            isinstance(event_type, str)
            and event_type.startswith("object.")
            and isinstance(object_type, str)
            and object_type
        ):
            event_type = f"{object_type}.{event_type.split('.', 1)[1]}"
        if portal_id and event_type:
            events.append((str(portal_id), str(event_type), item, None))
    return events


# ============================================================================
# Discord
# ============================================================================


async def _discord_verify(
    pool, body: bytes, headers: Dict[str, str], request_url: str
) -> bool:
    del request_url
    signature = headers.get("x-signature-ed25519", "")
    timestamp = headers.get("x-signature-timestamp", "")
    if not signature or not timestamp:
        return False
    try:
        data = json.loads(body) if body else {}
    except json.JSONDecodeError:
        return False
    application_id = data.get("application_id")
    if not application_id:
        return False
    verify_key = await get_verification_key(pool, "discord", str(application_id))
    if not verify_key:
        logger.error(
            "[app_webhooks] No Discord verify_key stored for application %s",
            application_id,
        )
        return False
    return verify_ed25519(body, timestamp, signature, verify_key)


def _discord_handshake(body: bytes) -> Response | None:
    try:
        data = json.loads(body) if body else {}
    except json.JSONDecodeError:
        return None
    dtype = data.get("type")
    if dtype == 0:
        # Application webhooks PING — plain 204
        return Response(status_code=204, media_type="application/json")
    if dtype == 1 and "event" not in data:
        # Interactions PING (type=1 with no `event` key) — must return {"type":1}
        return Response(
            content='{"type":1}', status_code=200, media_type="application/json"
        )
    return None


def _discord_parse(body: bytes) -> List[ParsedEvent]:
    try:
        data = json.loads(body) if body else {}
    except json.JSONDecodeError:
        return []
    dtype = data.get("type")
    application_id = data.get("application_id")
    if not application_id:
        return []

    # Application event (type=1 with `event` key)
    if dtype == 1 and "event" in data:
        event = data.get("event") or {}
        event_type = event.get("type")
        if not event_type:
            return []
        event_data = event.get("data") if isinstance(event, dict) else None
        channel = None
        if isinstance(event_data, dict):
            channel = event_data.get("channel_id")
            channel = channel if isinstance(channel, str) else None
        return [(str(application_id), str(event_type), data, channel)]

    # Slash command interaction (type=2)
    if dtype == 2:
        channel_id = data.get("channel_id")
        return [(str(application_id), "INTERACTION_APPLICATION_COMMAND", data, channel_id)]

    return []


def _discord_ack(body: bytes) -> Response:
    try:
        dtype = json.loads(body).get("type", 0)
    except Exception:
        dtype = 0
    if dtype == 2:
        # Slash command — deferred response so Discord shows "thinking…" while
        # the workflow runs in the background
        return Response(
            content='{"type":5}', status_code=200, media_type="application/json"
        )
    return Response(status_code=204, media_type="application/json")


async def _slack_drop_event(payload: Dict[str, Any]) -> Optional[str]:
    """Fan-out-level drop for messages NoClick itself posted (fingerprint
    match — the only way to identify send_as="user" posts, which carry no
    authorship fields). Returns a reason string to drop, None to deliver."""
    from utils.slack_self_echo import is_self_echo_event

    event = (payload.get("event") or {})
    if await is_self_echo_event(event):
        return f"self-posted message {event.get('channel')}/{event.get('ts')}"
    return None


def _slack_event_id(payload: Dict[str, Any]) -> Optional[str]:
    return payload.get("event_id")


APP_PROVIDERS = {
    "slack": {
        "verify": _slack_verify,
        "handshake": _slack_handshake,
        "parse": _slack_parse,
        # Optional adapter capabilities (all consumed by
        # handle_app_webhook_payload / _fire_subscription):
        # - drop_event: async, runs per parsed event before fan-out; a
        #   returned string drops the event and is logged as the reason.
        # - event_id: pure extractor enabling generic redelivery dedup
        #   (utils/app_event_dedup.py). Providers that redeliver on slow ACK
        #   (HubSpot: payload eventId) opt in by adding an extractor.
        # - fire_budget: per-(node, channel) fire cap (utils/fire_budget.py)
        #   for channel-conversation providers where echo loops close. NOT
        #   for burst-legitimate providers (HubSpot bulk imports).
        "drop_event": _slack_drop_event,
        "event_id": _slack_event_id,
        "fire_budget": True,
    },
    "hubspot": {
        "verify": _hubspot_verify,
        "handshake": _hubspot_handshake,
        "parse": _hubspot_parse,
    },
    "discord": {
        "verify": _discord_verify,
        "handshake": _discord_handshake,
        "parse": _discord_parse,
        "ack": _discord_ack,
    },
}
