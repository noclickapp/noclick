"""Community email bodies are never modified for plan branding."""

from typing import Optional


SENT_BY_URL = ""
SENT_BY_FOOTER_HTML = ""
SENT_BY_FOOTER_TEXT = ""


async def sender_is_free_tier(
    user_id: Optional[str], organization_id: Optional[str] = None
) -> bool:
    return False


async def maybe_brand_email_body(
    body: str,
    *,
    user_id: Optional[str],
    organization_id: Optional[str] = None,
    html: bool = True,
) -> str:
    return body
