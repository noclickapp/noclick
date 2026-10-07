"""What every automated phone call obeys, whichever path places or speaks it:
it never dials an emergency, crisis or service number, and its voice never
denies being an AI. Import-light, so a voice process reads it without
loading the node registry."""

from __future__ import annotations

import re
from typing import Optional

# Every live-call prompt carries it: the voice, the agent behind it, the coordinator on a call.
NEVER_DENY_AI = ("Don't volunteer that you're an AI, but if the person on the call sincerely asks whether they're "
                 "talking to a person or a bot, never claim to be human.")

# Never dialed by an automated call: emergency lines (911, 112, 999, 000, 110,
# 111, 119), 911's test line (933), the 988 crisis line and every N11 service
# code (211 crisis and community referral, 311, 711 relay, …).
SERVICE_CODES = frozenset({"000", "110", "111", "112", "119", "933", "988", "999"}
                          | {f"{n}11" for n in range(2, 10)})
# The dialed part: an optional tel:/sip: scheme, then digits, keypad symbols
# and formatting, up to anything else (an extension, a pause, a SIP host).
_DIALED = re.compile(r"\s*(?:(?:tel|sips?):)?([\d\s\-().+*#]*)", re.IGNORECASE)
_DIAL_OUT = re.compile(r"^(?:011|00)")

EMERGENCY_REFUSAL = ("No call was placed: {code} is an emergency, crisis or public service line, and NoClick never "
                     "places automated calls to one.")
OWNER_EMERGENCY_STEP = ("If anyone needs help, tell the owner to call or text 911 themselves right now (text-to-911 "
                        "works in most of the US; outside the US, their local emergency number). If they shared where "
                        "they are in this conversation, give that location back to them to tell the dispatcher; never "
                        "guess one.")


def service_code(dialed: Optional[str]) -> Optional[str]:
    """The emergency, crisis or service code ``dialed`` reaches, or None.
    Formatting, a dial-out prefix (00, 011) and up to three leading digits (a
    country code, a trunk 1, an outside-line 9) still reach it: '+1 911',
    '1-911', '9-911', '+44 999'. A full number (seven digits or more) never does."""
    digits = re.sub(r"\D", "", _DIALED.match(dialed or "").group(1))
    for candidate in (digits, _DIAL_OUT.sub("", digits)):
        if 3 <= len(candidate) <= 6 and candidate[-3:] in SERVICE_CODES:
            return candidate[-3:]
    return None


def emergency_refusal(dialed: Optional[str], *, for_owner: bool = False) -> Optional[str]:
    """Why a call to ``dialed`` is refused, or None when it may be dialed.
    ``for_owner``: the account's coordinator asked, so the refusal tells it how
    the owner gets help themselves."""
    code = service_code(dialed)
    if code is None:
        return None
    refusal = EMERGENCY_REFUSAL.format(code=code)
    return f"{refusal} {OWNER_EMERGENCY_STEP}" if for_owner else refusal
