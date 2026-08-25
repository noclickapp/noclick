"""
Email utility for sending transactional emails using Resend.
Handles organization invites and other system notifications.
"""

import os
import logging
from typing import Optional
import resend

from utils.edition import is_local_edition
from utils.hosted_defaults import frontend_url

logger = logging.getLogger(__name__)

# Initialize Resend with API key
_resend_api_key = os.getenv('RESEND_API_KEY')
if _resend_api_key:
    resend.api_key = _resend_api_key

# Frontend URL for constructing links. The edition-aware resolver requires a
# self-hosted operator's own URL and is the sole hosted fallback.
FRONTEND_URL = frontend_url()


def credential_provide_url(token: str, frontend_url: Optional[str] = None) -> str:
    """Build the public link where a recipient provides a requested credential.
    Single source of truth for the path — used by the request email and the
    copy-link response so the two never drift."""
    base_url = frontend_url or FRONTEND_URL
    return f"{base_url}/credential/provide/{token}"

# Sender identities (domains must be verified in Resend). Two streams by
# abuse-risk class: FROM_EMAIL is the default — system alerts and other mail
# to our own users; INVITE_FROM_EMAIL is user-TRIGGERED mail to arbitrary
# external recipients carrying user-authored strings (workspace invites,
# credential requests) — the stream that could get burned, kept on its own
# identity so complaint signals stay separable.
_configured_from_email = os.getenv("FROM_EMAIL")
if _resend_api_key and not _configured_from_email:
    raise RuntimeError(
        "RESEND_API_KEY is set but FROM_EMAIL is not; configure a sender on a "
        "domain verified in your Resend account"
    )
FROM_EMAIL = _configured_from_email or (
    "" if is_local_edition() else "NoClick <noreply@noclick.com>"
)
INVITE_FROM_EMAIL = os.getenv('INVITE_FROM_EMAIL', FROM_EMAIL)


class EmailError(Exception):
    """Exception raised for email sending failures."""
    pass


def _transactional_html(
    *,
    preheader: str,
    eyebrow: str,
    heading: str,
    blocks_html: str,
    cta_text: str,
    cta_url: str,
    footer_notes: list[str],
    badge_html: str = '',
) -> str:
    """Transactional variant of the shared shell (utils/notification_templates):
    standard "Sent from NoClick" footer with per-email notes (expiry, "you can
    ignore this") folded into the body's last block. One styling source for
    every NoClick email."""
    from utils.notification_templates import FAINT, FONT, build_email_shell

    notes = ''.join(
        f'<p style="margin:14px 0 0;font-size:12px;line-height:1.6;color:{FAINT};font-family:{FONT};">{line}</p>'
        for line in footer_notes
    )
    return build_email_shell(
        preheader=preheader,
        eyebrow=eyebrow,
        heading=heading,
        blocks_html=blocks_html,
        cta_text=cta_text,
        cta_url=cta_url,
        postscript_html=notes,
        badge_html=badge_html,
        frontend_url=FRONTEND_URL,
        title=heading,
    )


def _send_email(
    to_email: str,
    subject: str,
    html_content: str,
    text_content: str,
    headers: Optional[dict] = None,
    from_email: Optional[str] = None,
) -> bool:
    """Send an email via Resend. Returns True on success, False on failure.

    NOTE: blocking HTTP call — async callers must wrap in asyncio.to_thread
    (see utils/notifications.py) to keep it off the event loop.
    """
    if not _resend_api_key:
        logger.warning("RESEND_API_KEY not configured, skipping email send")
        return False

    try:
        params: resend.Emails.SendParams = {
            "from": from_email or FROM_EMAIL,
            "to": [to_email],
            "subject": subject,
            "html": html_content,
            "text": text_content,
        }
        if headers:
            params["headers"] = headers
        email_response = resend.Emails.send(params)
        logger.info("Email sent, provider_id=%s", email_response.get("id"))
        return True
    except Exception as e:
        logger.error("Email delivery failed: %s", e, exc_info=True)
        return False


async def send_organization_invite_email(
    to_email: str,
    organization_name: str,
    inviter_name: str,
    invite_token: str,
    role: str = 'member',
    organization_icon_url: Optional[str] = None,
    frontend_url: Optional[str] = None
) -> bool:
    """Send an organization invite email."""
    import html as html_lib

    from utils.notification_templates import kv_rows, para, strong

    base_url = frontend_url or FRONTEND_URL
    invite_url = f"{base_url}/organization/invite/{invite_token}"
    org_html = html_lib.escape(organization_name or "")
    inviter_html = html_lib.escape(inviter_name or "")

    if organization_icon_url:
        badge_html = (
            f'<img src="{html_lib.escape(organization_icon_url, quote=True)}" alt="{org_html}" '
            'width="48" height="48" style="width:48px;height:48px;object-fit:cover;border-radius:12px;display:block;border:1px solid #e4e4e7;">'
        )
    else:
        initials = html_lib.escape(organization_name[:2].upper() if organization_name else "NC")
        badge_html = (
            '<table role="presentation" cellspacing="0" cellpadding="0"><tr>'
            '<td width="48" height="48" align="center" style="width:48px;height:48px;background-color:#18181b;'
            'border-radius:12px;color:#ffffff;font-size:17px;font-weight:600;'
            f"font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;\">{initials}</td>"
            "</tr></table>"
        )

    html_content = _transactional_html(
        preheader=f"{inviter_name} invited you to join {organization_name} on NoClick",
        eyebrow="Workspace invitation",
        heading=f"Join {org_html} on NoClick",
        blocks_html=(
            para(f"{strong(inviter_html)} has invited you to join {strong(org_html)}.")
            + kv_rows([("Workspace", org_html), ("Invited by", inviter_html), ("Role", html_lib.escape(role))])
        ),
        cta_text="Accept Invitation",
        cta_url=invite_url,
        footer_notes=[
            "This invitation expires in 7 days. If you didn't expect it, you can safely ignore this email.",
        ],
        badge_html=badge_html,
    )

    text_content = f'''You're Invited to {organization_name}!

Hi there,

{inviter_name} has invited you to join {organization_name} on NoClick as a {role}.

Accept your invitation by clicking the link below:
{invite_url}

This invitation expires in 7 days.
If you didn't expect this invitation, you can safely ignore this email.

---
The NoClick Team
'''

    return _send_email(
        to_email,
        f"You're invited to join {organization_name} on NoClick",
        html_content,
        text_content,
        from_email=INVITE_FROM_EMAIL,
    )


def _format_credential_type_label(credential_type: str) -> str:
    """Convert credential_type DB identifier to a human-readable label.
    E.g. 'google_sheets_oauth' -> 'Google Sheets', 'openai_api_key' -> 'OpenAI API Key'
    """
    label = credential_type.replace('_oauth', '').replace('_pat', ' PAT').replace('_api_key', ' API Key').replace('_bot_token', ' Bot Token')
    return label.replace('_', ' ').title()


def credential_provide_url(token: str, frontend_url: Optional[str] = None) -> str:
    """The hosted page where a user provides a requested credential (OAuth or
    API key). One definition so email + the MCP connect tool can't drift."""
    return f"{frontend_url or FRONTEND_URL}/credential/provide/{token}"


async def send_credential_request_email(
    to_email: str,
    requester_name: str,
    credential_type: str,
    token: str,
    message: Optional[str] = None,
    frontend_url: Optional[str] = None,
) -> bool:
    """Send an email to an external user requesting them to provide a credential."""
    import html as html_lib

    from utils.notification_templates import FONT, HAIRLINE, MUTED, kv_rows, para, strong

    provide_url = credential_provide_url(token, frontend_url)
    credential_label = _format_credential_type_label(credential_type)
    requester_html = html_lib.escape(requester_name or "")

    blocks = para(
        f"{strong(requester_html)} is asking you to provide a "
        f"{strong(html_lib.escape(credential_label))} credential on NoClick."
    )
    if message:
        blocks += (
            f'<p style="margin:0 0 14px;padding:10px 14px;border-left:3px solid {HAIRLINE};'
            f'font-size:14px;line-height:1.65;color:{MUTED};font-style:italic;font-family:{FONT};">'
            f"&ldquo;{html_lib.escape(message)}&rdquo;</p>"
        )
    blocks += kv_rows([
        ("Requested by", requester_html),
        ("Credential", html_lib.escape(credential_label)),
    ])
    blocks += para(
        "The credential is submitted over a secure form — you don't need a NoClick account."
    )

    html_content = _transactional_html(
        preheader=f"{requester_name} is requesting a {credential_label} credential",
        eyebrow="Credential request",
        heading=f"{requester_html} needs a {html_lib.escape(credential_label)} credential",
        blocks_html=blocks,
        cta_text="Provide Credential",
        cta_url=provide_url,
        footer_notes=[
            "This request expires in 7 days. If you didn't expect it, you can safely ignore this email.",
        ],
    )

    message_line = f'\nMessage: "{message}"\n' if message else ''
    text_content = f'''Credential Request from {requester_name}

Hi there,

{requester_name} is requesting a {credential_label} credential from you on NoClick.
{message_line}
Provide the credential by clicking the link below (no NoClick account needed):
{provide_url}

This request expires in 7 days.
If you didn't expect this request, you can safely ignore this email.

---
The NoClick Team
'''

    return _send_email(
        to_email,
        f"{requester_name} is requesting a {credential_label} credential on NoClick",
        html_content,
        text_content,
        from_email=INVITE_FROM_EMAIL,
    )


async def send_credential_fulfilled_email(
    to_email: str,
    provider_email: str,
    credential_type: str,
    frontend_url: Optional[str] = None,
) -> bool:
    """Notify the requester that their credential request has been fulfilled."""
    import html as html_lib

    from utils.notification_templates import kv_rows, para, strong

    base_url = frontend_url or FRONTEND_URL
    dashboard_url = f"{base_url}/dashboard"
    credential_label = _format_credential_type_label(credential_type)

    html_content = _transactional_html(
        preheader=f"{provider_email} provided the {credential_label} credential you requested",
        eyebrow="Credential update",
        heading="Credential received",
        blocks_html=(
            para(
                f"{strong(html_lib.escape(provider_email))} has provided the "
                f"{strong(html_lib.escape(credential_label))} credential you requested. "
                "It's available in your account and ready to use in your workflows."
            )
            + kv_rows([
                ("Provided by", html_lib.escape(provider_email)),
                ("Credential", html_lib.escape(credential_label)),
            ])
        ),
        cta_text="Go to Dashboard",
        cta_url=dashboard_url,
        footer_notes=[
            "You received this email because you requested a credential on NoClick.",
        ],
    )

    text_content = f'''Credential Request Fulfilled

Hi there,

{provider_email} has provided the {credential_label} credential you requested.
The credential is now available in your account and ready to use in your workflows.

Go to your dashboard: {dashboard_url}

---
The NoClick Team
'''

    return _send_email(
        to_email,
        f"Your {credential_label} credential request has been fulfilled",
        html_content,
        text_content,
    )
