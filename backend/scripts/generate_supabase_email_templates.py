"""
Render the Supabase auth email templates (confirm signup, reset password)
from the shared NoClick email shell (utils/notification_templates), so auth
mail matches every other NoClick email and restyles with the shell.

Outputs checked-in HTML to infra/supabase/templates/. Supabase's Go template
variables ({{ .RedirectTo }}, {{ .TokenHash }}) ride through as literal text.
Local dev picks the files up via config.toml [auth.email.template.*]; prod needs
a paste into Dashboard → Authentication → Email Templates after each re-run —
and only AFTER the frontend that reads these links is deployed.

Run from backend/:  python scripts/generate_supabase_email_templates.py
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.notification_templates import FONT, MUTED, para, strong  # noqa: E402
from utils.email import _transactional_html  # noqa: E402

OUT_DIR = Path(__file__).parent.parent.parent / "infra" / "supabase" / "templates"


def _portable_transactional_html(**kwargs) -> str:
    """Render an auth template using Supabase's configured installation URL.

    Auth email opens must not contact a fixed vendor host. The text wordmark is
    deliberately self-contained; no remote image is loaded by the mail client.
    """
    rendered = _transactional_html(**kwargs)
    rendered = re.sub(
        r'<a href="[^"]+/dashboard" style="text-decoration:none;">',
        '<a href="{{ .SiteURL }}/dashboard" style="text-decoration:none;">',
        rendered,
        count=1,
    )
    rendered = re.sub(
        r'\s*<img src="[^"]+/apple-touch-icon[.]png"[^>]*>\n',
        "\n",
        rendered,
        count=1,
    )
    return re.sub(
        r'Sent from <a href="[^"]+"',
        'Sent from <a href="{{ .SiteURL }}"',
        rendered,
        count=1,
    )

# Links are token_hash-based ({{ .TokenHash }} + /auth/confirm verifyOtp), NOT
# {{ .ConfirmationURL }}: ConfirmationURL routes through GoTrue /verify into the
# PKCE ?code= exchange, which depends on the initiating browser's code-verifier
# cookie and therefore fails for cross-context opens. Build on {{ .RedirectTo }}
# rather than {{ .SiteURL }} so the link carries the correct per-environment
# origin. auth.server.ts always
# passes redirect_to as /auth/confirm?next=..., so the '&' concatenation is safe.
CONFIRM_LINK = "{{ .RedirectTo }}&token_hash={{ .TokenHash }}&type=email"
RECOVERY_LINK = "{{ .RedirectTo }}&token_hash={{ .TokenHash }}&type=recovery"


def _fallback_link(url: str) -> str:
    return (
        f'<p style="margin:0 0 14px;font-size:12px;line-height:1.6;color:{MUTED};font-family:{FONT};">'
        f'Or copy this link into your browser:<br>'
        f'<a href="{url}" style="color:{MUTED};word-break:break-all;">{url}</a></p>'
    )


TEMPLATES = {
    "confirmation": {
        "subject": "Confirm your NoClick email",
        "html": _portable_transactional_html(
            preheader="Confirm your email address to start building on NoClick",
            eyebrow="Welcome to NoClick",
            heading="Confirm your email",
            blocks_html=(
                para(
                    f"Thanks for signing up. Confirm {strong('{{ .Email }}')} to "
                    "activate your account and start building."
                )
                + _fallback_link(CONFIRM_LINK)
            ),
            cta_text="Confirm Email",
            cta_url=CONFIRM_LINK,
            footer_notes=[
                "If you didn't create a NoClick account, you can safely ignore this email.",
            ],
        ),
    },
    "recovery": {
        "subject": "Reset your NoClick password",
        "html": _portable_transactional_html(
            preheader="Use this link to set a new NoClick password",
            eyebrow="Account",
            heading="Reset your password",
            blocks_html=(
                para(
                    f"We received a request to reset the password for {strong('{{ .Email }}')}. "
                    "Use the button below to choose a new one. For security, the link expires soon."
                )
                + _fallback_link(RECOVERY_LINK)
            ),
            cta_text="Reset Password",
            cta_url=RECOVERY_LINK,
            footer_notes=[
                "If you didn't request a password reset, you can safely ignore this email — "
                "your password won't change.",
            ],
        ),
    },
}


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, spec in TEMPLATES.items():
        path = OUT_DIR / f"{name}.html"
        path.write_text(spec["html"])
        print(f"  {path.relative_to(OUT_DIR.parent.parent.parent)}  (subject: {spec['subject']})")
    print("\nProd: paste each file into Supabase Dashboard → Authentication → Email Templates.")


if __name__ == "__main__":
    main()
