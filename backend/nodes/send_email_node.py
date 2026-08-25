"""
Send-email node — emails the workflow runner's own account address.

Deliberately recipient-less: v1 of outbound workflow email is
self-notification only (reports, alerts, digests to yourself). The recipient
is resolved server-side from the runner's auth.users row and is not a config
field, so neither a human configuring the node nor an agent calling it as a
tool can point it at anyone else. Broader recipients (prior correspondents,
double-opt-in allowlists) are future work; agents replying to inbound email
use the locked tool in nodes/agent/email_reply.py.

The body ships inside a branded wrapper with a provenance footer ("sent by
your workflow X") and a signed one-click disable link
(utils/email_unsubscribe.py) plus RFC 8058 List-Unsubscribe headers. Every
send is credit-gated and charged flat (billing.pricing.EMAIL_SEND_PRICE) and
rides the shared configured email transport (utils/email_sending.py) from the
platform notifications address.

The single ``send`` operation const makes the node an agent tool provider
(node_op_tools._iter_operation_defs): wired into an agent's bottom handle it
exposes ``send_email__send(subject, body)``.
"""

import asyncio
import html as html_lib
import logging
import time
from decimal import Decimal
from typing import Any, Dict, List, Literal, Optional, Tuple, Type

from pydantic import BaseModel, Field, field_validator

from nodes.core.base import WorkflowNode, NodeConfig
from utils.email_reservation_manager import require_inbound_email_domain

logger = logging.getLogger(__name__)

# run_op's synthetic node id — an agent-tool send has no canvas node to
# disable, so the footer link is omitted for it.
_RUN_OP_NODE_PREFIX = "node-op:"


class SendEmailConfig(BaseModel):
    """Send an email to YOUR OWN account email address. The recipient is
    always the account email of the user running the workflow — no other
    recipients can be specified."""
    operation: Literal["send"] = Field(
        default="send",
        json_schema_extra={
            "ui:hidden": True,
            "x-is-trigger": False,
            "x-display-name": "Email Myself",
        },
        title="Email Myself",
    )
    subject: str = Field(
        ...,
        title="Subject",
        description="Subject line of the email.",
        json_schema_extra={"placeholder": "Daily report ready"},
    )
    body: str = Field(
        ...,
        title="Body",
        description=(
            "Body of the email. Markdown is rendered into formatted HTML "
            "automatically; ready-made HTML is used as-is. The email is sent "
            "to your own account email address only — recipients cannot be "
            "chosen."
        ),
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 6},
    )
    attachments: List[str] = Field(
        default_factory=list,
        title="Attachments",
        description="Files to attach: workflow resource ids or URLs (max 10MB per file, 20MB total).",
        json_schema_extra={"ui:widget": "list", "placeholder": "{{node.resource_id}}"},
    )

    @field_validator("attachments", mode="before")
    @classmethod
    def filter_attachments(cls, v: Any) -> list:
        if not isinstance(v, list):
            return []
        return [a for a in v if isinstance(a, str) and a.strip()]


class SendEmailNodeConfig(NodeConfig[SendEmailConfig, None]):
    """Full configuration for the send-email node (no credentials needed)."""
    pass


def build_notification_email(
    body: str, workflow_name: Optional[str], disable_url: Optional[str]
) -> Tuple[str, str]:
    """(html, text) — the body in the shared NoClick email shell
    (utils/notification_templates.build_email_shell), with a workflow
    provenance footer + disable link. No heading or CTA: the subject and
    body are the user's own.

    The user/agent-authored body autodetects as HTML or markdown/plain text
    (utils/email_body.py); either way it lands as an inline-styled fragment.
    The shell has no dark bands, so forced dark mode inverts background and
    text together — the previous black-banner design needed a CID-embedded
    image lockup to survive Gmail's inconsistent recoloring; this one doesn't.
    """
    from utils.email import FRONTEND_URL
    from utils.email_body import _html_to_text, prepare_email_body
    from utils.notification_templates import MUTED, build_email_shell

    provenance = (
        f"Sent by your NoClick workflow “{workflow_name}”."
        if workflow_name
        else "Sent by your NoClick workflow."
    )

    body_html, body_text = prepare_email_body(body)

    text = body_text
    text += f"\n\n—\n{provenance}"
    if disable_url:
        text += f"\nDisable these emails: {disable_url}"

    # No trailing period before the · separator in the HTML footer.
    footer_bits = [html_lib.escape(provenance.rstrip("."))]
    if disable_url:
        footer_bits.append(
            f'<a href="{html_lib.escape(disable_url, quote=True)}" '
            f'style="color:{MUTED};">Disable these emails</a>'
        )

    # Preheader from the RENDERED body, not body_text — for markdown input the
    # text alternative keeps the raw source ("### Report"), which would leak
    # markdown syntax into the inbox preview line.
    preview = " ".join(_html_to_text(body_html).split())[:140]
    html = build_email_shell(
        preheader=html_lib.escape(preview),
        blocks_html=f'<div style="color:#18181b;font-size:15px;line-height:1.7;">{body_html}</div>',
        footer_html=" &middot; ".join(footer_bits),
        frontend_url=FRONTEND_URL,
    )
    return html, text


class SendEmailNode(WorkflowNode):
    """
    Sends an email to the running user's account address.

    The recipient is not configurable — see the module docstring for the
    containment rationale.
    """

    edit_examples = [
        "Email me a summary of the results",
        "Send myself the daily report when the cron fires",
        "Change the subject to include the item count",
        "Email me when the scraper finds new listings",
    ]

    @classmethod
    def get_config_model(cls) -> Optional[Type]:
        return SendEmailNodeConfig

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        logger.info(f"[SendEmailNode] Executing node {self.node_id}")

        node_config = self.config
        if not node_config or not isinstance(node_config, SendEmailNodeConfig):
            raise ValueError(f"[SendEmailNode] Configuration required for node {self.node_id}")
        config = node_config.config
        if not self.user_id:
            raise ValueError("[SendEmailNode] No user context to resolve the recipient")

        # This node sends through the same operator-owned mail domain as the
        # inbound/reply channel. Do not construct ``notifications@`` (or fall
        # back to any managed domain) when that channel is unconfigured.
        email_domain = require_inbound_email_domain()
        from_addr = f"notifications@{email_domain}"

        to_addr = await self._resolve_account_email()
        # Account emails are never on the trigger domain; refuse rather than
        # let a send loop back into a workflow trigger.
        if to_addr.lower().endswith(f"@{email_domain}"):
            raise ValueError(
                f"[SendEmailNode] Refusing to send to a {email_domain} address"
            )

        from billing.usage_tracker import usage_tracker

        # Pre-flight on the same pool the charge lands on (organization attribution policy).
        await usage_tracker.enforce_credit_gate(
            self.user_id,
            organization_id=self.organization_id,
            sio=self.sio,
            sid=self.sid,
            user_resource=False,
            surface="send_email",
        )

        workflow_name = await self._resolve_workflow_name()
        disable_url = None
        extra_headers: Dict[str, str] = {}
        if self.workflow_id and not self.node_id.startswith(_RUN_OP_NODE_PREFIX):
            from utils.email_unsubscribe import build_disable_url

            disable_url = build_disable_url(str(self.workflow_id), self.node_id)
            # RFC 8058 one-click unsubscribe for mail clients.
            extra_headers["List-Unsubscribe"] = f"<{disable_url}>"
            extra_headers["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"

        html, text = build_notification_email(config.body, workflow_name, disable_url)

        from utils.email_sending import resolve_attachment_entries, send_email

        attachments = await resolve_attachment_entries(config.attachments)
        result = await send_email(
            from_addr=from_addr,
            from_name="NoClick",
            to=to_addr,
            subject=config.subject,
            text=text,
            html=html,
            extra_headers=extra_headers,
            attachments=attachments,
        )

        from billing.pricing import EMAIL_SEND_PRICE
        from billing.schema import UsageEventData

        # Raw runner + org; the tracker's organization attribution policy choke point resolves the
        # billed pool.
        await usage_tracker.track_usage_event(
            UsageEventData(
                user_id=self.user_id,
                total_cost=EMAIL_SEND_PRICE,
                usage_type="api_usage",
                usage_subtype="email/send_node",
                quantity=Decimal("1"),
                unit_type="requests",
                user_resource=False,
                organization_id=self.organization_id,
                metadata={
                    "to": to_addr,
                    "workflow_id": str(self.workflow_id) if self.workflow_id else None,
                    "node_id": self.node_id,
                    "message_id": result.get("message_id"),
                    "delivery_status": result.get("delivery_status"),
                },
            ),
            sio=self.sio,
            sid=self.sid,
        )

        output = {
            "type": "send-email",
            "status": "sent",
            "timestamp": time.time(),
            "to": to_addr,
            "from": from_addr,
            "subject": config.subject,
            "message_id": result.get("message_id"),
            "delivery_status": result.get("delivery_status"),
        }
        await self.emit(output)
        return output

    async def _resolve_account_email(self) -> str:
        """The runner's auth.users email — the only recipient this node can have."""
        from repositories.users import get_user_email
        from utils.database_pool import get_native_pool

        email = await get_user_email(get_native_pool(), self.user_id)
        if not email:
            raise ValueError(f"[SendEmailNode] No account email found for user {self.user_id}")
        return str(email)

    async def _resolve_workflow_name(self) -> Optional[str]:
        """Workflow name for the provenance footer; None outside a workflow."""
        if not self.workflow_id:
            return None
        from utils.database_pool import get_native_pool

        try:
            name = await get_native_pool().fetchval(
                "SELECT name FROM workflows WHERE id = $1", self.workflow_id
            )
            return str(name) if name else None
        except Exception as e:
            # Provenance is decoration — never fail a send over it.
            logger.warning(f"[SendEmailNode] Workflow name lookup failed: {e}")
            return None
