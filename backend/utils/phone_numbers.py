"""E.164 phone numbers: the one shape every phone-keyed table stores."""

from __future__ import annotations

import re

_E164 = re.compile(r"^\+[1-9][0-9]{6,14}$")
_FORMATTING = re.compile(r"[\s\-().]")


def normalize_e164(raw: str | None) -> str | None:
    """'+1 (424) 242-1064' -> '+14242421064'; None unless it is a full
    international number. A leading 00 is the dial-out prefix outside North
    America; a bare national number has no country and is refused."""
    value = _FORMATTING.sub("", raw or "")
    if value.startswith("00"):
        value = "+" + value[2:]
    return value if _E164.match(value) else None


def mask_e164(e164: str) -> str:
    """'+14242421064' -> '+1•••••••1064', for logs and audit lines."""
    if len(e164) <= 6:
        return e164
    return e164[:2] + "•" * (len(e164) - 6) + e164[-4:]
