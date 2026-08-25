"""
Auto-injected ``email__reply`` tool — the opaque reply channel for the
inbound-email trigger.

Unlike other channel triggers (Slack/Telegram), email replies do NOT come from
a provider node the user wires into the agent's bottom handle: a general
send-email surface on our domain would invite cold-email campaigns and burn
the shared deliverability of the trigger domain. Instead, when the FIRED
trigger of a run is an inbound-email trigger wired directly into the agent,
the agent gets one tool whose recipient and threading are locked server-side
to the triggering email (HMAC reply token minted at receipt — see
utils/email_reply.py). The model chooses only body and subject. Every send is
credit-gated and charged a flat fee (billing.pricing.EMAIL_SEND_PRICE) as
the backstop even if the containment logic were ever bypassed.
"""

import asyncio
import logging
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple

from litellm import ChatCompletionToolParam, ChatCompletionToolParamFunctionChunk

logger = logging.getLogger(__name__)

EMAIL_REPLY_TOOL_NAME = "email__reply"
# Deliverability guard for runaway agent loops; legitimate use is 1-2 sends.
MAX_REPLIES_PER_RUN = 5


def build_email_reply_tool(
    trigger_node_id: str, output: Dict[str, Any]
) -> Optional[Tuple[ChatCompletionToolParam, Dict[str, Any]]]:
    """(tool_param, tool_config) for the locked reply tool, or None when the
    fired output can't anchor a verified reply (no sender / no reply token)."""
    from utils.email_reply import build_reply_context

    context = build_reply_context(output)
    if context is None:
        return None

    description = (
        f"Reply to the email that triggered this run (from {context['to']}, "
        f"subject: {context['subject'] or '(no subject)'}). The reply is sent "
        f"from {context['from_addr']} back to the original sender only — "
        f"recipients cannot be chosen. Each send costs 0.01 credits."
    )
    parameters = {
        "type": "object",
        "properties": {
            "body": {
                "type": "string",
                "description": (
                    "Body of the reply. Markdown is rendered into formatted "
                    "HTML automatically; ready-made HTML is used as-is."
                ),
            },
            "subject": {
                "type": "string",
                "description": "Optional subject override; defaults to 'Re: <original subject>'.",
            },
            "attachment_resource_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Optional workflow resource ids of files to attach "
                    "(max 10MB per file, 20MB total)."
                ),
            },
        },
        "required": ["body"],
    }
    tool_param = ChatCompletionToolParam(
        type="function",
        function=ChatCompletionToolParamFunctionChunk(
            name=EMAIL_REPLY_TOOL_NAME,
            description=description,
            parameters=parameters,
        ),
    )
    tool_config = {
        "node_id": trigger_node_id,
        "tool_type": "email_reply",
        "operation": "reply",
        # Locked server-side at collection time; never rides through the model.
        "reply_context": context,
        # Schema for delegated tool injection (CLI agents).
        "_description": description,
        "_parameters": parameters,
    }
    return tool_param, tool_config


async def execute_email_reply(
    node, arguments: Dict[str, Any], tool_info: Dict[str, Any]
) -> Dict[str, Any]:
    """Verify the locked context, gate + charge credits, send via Cloudflare
    Email Service.

    Gate failures raise (InsufficientBalanceError / OwnerResolutionError) and
    surface to the model through execute_tool's catch-all.
    """
    from billing.pricing import EMAIL_SEND_PRICE
    from billing.markup import dollars_to_credits
    from billing.schema import UsageEventData
    from billing.usage_tracker import usage_tracker
    from utils.email_reply import reply_refusal, send_email_reply

    body = (arguments or {}).get("body")
    if not body or not str(body).strip():
        return {"success": False, "error": "Reply body is required"}

    context = tool_info.get("reply_context") or {}
    refusal = reply_refusal(context)
    if refusal:
        return {"success": False, "error": f"Reply refused: {refusal}"}

    sent = getattr(node, "_email_replies_sent", 0)
    if sent >= MAX_REPLIES_PER_RUN:
        return {
            "success": False,
            "error": f"Reply limit reached ({MAX_REPLIES_PER_RUN} emails per run)",
        }

    # Pre-flight on the same pool the charge lands on (organization attribution policy).
    await usage_tracker.enforce_credit_gate(
        node.user_id,
        organization_id=node.organization_id,
        sio=node.sio,
        sid=node.sid,
        user_resource=False,
        surface="email_reply",
    )

    result = await send_email_reply(
        context,
        str(body),
        subject=(arguments or {}).get("subject"),
        attachment_resource_ids=(arguments or {}).get("attachment_resource_ids"),
    )
    node._email_replies_sent = sent + 1

    # Pass the raw runner + org; track_usage_event's organization attribution policy choke point
    # resolves the billed pool.
    await usage_tracker.track_usage_event(
        UsageEventData(
            user_id=node.user_id,
            total_cost=EMAIL_SEND_PRICE,
            usage_type="api_usage",
            usage_subtype="email/agent_reply",
            quantity=Decimal("1"),
            unit_type="requests",
            user_resource=False,
            organization_id=node.organization_id,
            metadata={
                "to": context.get("to"),
                "from": context.get("from_addr"),
                "workflow_id": str(node.workflow_id) if getattr(node, "workflow_id", None) else None,
                "trigger_node_id": tool_info.get("node_id"),
                "message_id": result.get("message_id"),
                "delivery_status": result.get("delivery_status"),
            },
        ),
        sio=node.sio,
        sid=node.sid,
    )
    return {
        "success": True,
        "to": result["to"],
        "from": result["from"],
        "message_id": result.get("message_id"),
        # delivered / queued / bounced / accepted — surfaced so the agent can
        # tell the user when the reply hard-bounced (still charged: a bounce
        # consumes sending quota and reputation).
        "delivery_status": result.get("delivery_status"),
        "credits_charged": float(dollars_to_credits(EMAIL_SEND_PRICE)),
    }
