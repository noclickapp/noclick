"""E.164 phone numbers: the one shape every phone-keyed table stores."""

from __future__ import annotations

import re

_E164 = re.compile(r"^\+[1-9][0-9]{6,14}$")
_FORMATTING = re.compile(r"[\s\-().]")
# A requirement for a number that asks for its holder's contact information (their name, their business's, a
# phone): an offer's ``requirements.items[].kind``; a purchase then needs the holder's ``phone``.
CONTACT_KIND = "contact"
# One that takes an answer in text (``values``: the only answers it takes, where it names any), and one that takes a
# document (the id ``PHONE_NUMBERS.upload_document`` gave it): a purchase answers each by the requirement's ``id``.
TEXT_KIND, DOCUMENT_KIND = "textual", "document"


class PhonePurchaseRejected(ValueError):
    """The provider definitively refused a purchase; no number was bought."""


class CoverageNotReady(RuntimeError):
    """Where numbers are for sale hasn't been found out yet (the first check runs in the background)."""


class PhoneDocumentRefused(ValueError):
    """A document for a number's requirement that can't be taken or filed (its type, its size, a requirement
    that takes none, one no longer on file); the message says what to do."""


class PhoneOrderNotFound(LookupError):
    """No order of the account's has that id."""


def normalize_e164(raw: str | None) -> str | None:
    """'+1 (424) 242-1064' -> '+14242421064'; None unless it is a full
    international number. A leading 00 is the dial-out prefix outside North
    America; a bare national number has no country and is refused."""
    value = _FORMATTING.sub("", raw or "")
    if value.startswith("00"):
        value = "+" + value[2:]
    return value if _E164.match(value) else None


# Why a send to NoClick's own line is refused, to the agent that tried. The owner's phone holds a chat with NoClick, so
# an agent going through their chats takes it for a contact; and on their linked phone it would read as the owner's own
# text to their assistant.
NOCLICK_LINE_REFUSAL = (
    "Not sent: that number is NoClick's own line, where the owner texts their NoClick assistant. It isn't one of their "
    "contacts, and a message there would read as the owner's own text to the assistant. Send to the person's own "
    "number or chat id instead: to answer someone, the sender's id from the event that woke you; otherwise find them "
    "among the owner's contacts and chats, leaving this one out. To tell the owner something, use your tool for that "
    "(human__notify or email_user)."
)


def is_noclick_number(raw: str | None) -> bool:
    """Whether ``raw`` (E.164, bare digits, Twilio's ``whatsapp:+…`` or a WhatsApp
    chat id, ``…@c.us``) is a number NoClick itself texts people from: the
    assistant's WhatsApp line or its iMessage line. A message from one never wakes
    an owner's trigger: the assistant answers on the owner's own linked phone, so
    an agent listening there would spend its turns on NoClick's replies, and answer
    them. A send to one is refused (``noclick_line_refusal``). A ``@lid`` or group
    id names no number."""
    from utils.sendblue import line_number
    from utils.whatsapp_cloud_api import display_number

    value, _, server = str(raw or "").strip().removeprefix("whatsapp:").partition("@")
    if server:
        if server not in ("c.us", "s.whatsapp.net"):
            return False
        value = value.split(":", 1)[0]
    number = normalize_e164(value if value.startswith(("+", "00")) else "+" + value)
    if number is None:
        return False
    return any(normalize_e164(line() or "") == number for line in (display_number, line_number))


def noclick_line_refusal(recipient: str | None) -> str | None:
    """Why a message to ``recipient`` is refused, or None when it may be sent."""
    return NOCLICK_LINE_REFUSAL if is_noclick_number(recipient) else None


def valid_e164(raw: str | None) -> str | None:
    """``raw`` in E.164 when it's a number in use somewhere ('+31 6 1234 5678'
    -> '+31612345678', by ``phonenumbers``' own numbering plans); None otherwise."""
    import phonenumbers

    try:
        parsed = phonenumbers.parse(raw or "")
    except phonenumbers.NumberParseException:
        return None
    if not phonenumbers.is_valid_number(parsed):
        return None
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def readable(raw: str | None) -> str | None:
    """A number as people write it, '+1 202-555-0101' (``phonenumbers``' international format), from E.164, bare
    digits ('12025550101', as WhatsApp keeps a linked number) or a phone chat id ('12025550101@c.us'). None for what
    names no number (a @lid, a group); one its numbering plans can't place stays E.164."""
    import phonenumbers

    local, _, server = str(raw or "").strip().removeprefix("whatsapp:").partition("@")
    if server and server not in ("c.us", "s.whatsapp.net"):
        return None
    local = local.split(":", 1)[0]
    number = normalize_e164(local if local.startswith(("+", "00")) else "+" + local)
    if number is None:
        return None
    parsed = phonenumbers.parse(number)
    if not phonenumbers.is_possible_number(parsed):
        return number
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL)


def mask_e164(e164: str) -> str:
    """'+14242421064' -> '+1•••••••1064', for logs and audit lines."""
    if len(e164) <= 6:
        return e164
    return e164[:2] + "•" * (len(e164) - 6) + e164[-4:]


def country_of(e164: str) -> str | None:
    """The ISO alpha-2 country an E.164 number belongs to (a shared calling
    code's numbers by their own ranges: +1 416… is CA); None when it can't tell."""
    import phonenumbers

    try:
        region = phonenumbers.region_code_for_number(phonenumbers.parse(e164))
    except phonenumbers.NumberParseException:
        return None
    return region if region and region != "ZZ" else None


def priced_country(e164: str) -> str | None:
    """The country a vendor that prices messages by country prices ``e164``
    in: its own (``country_of``), else its calling code's main country (+44 →
    GB, +1 → US) for a number in a range the numbering plans can't place."""
    import phonenumbers

    try:
        code = phonenumbers.parse(e164).country_code
    except phonenumbers.NumberParseException:
        return None
    region = country_of(e164) or phonenumbers.region_code_for_country_code(code)
    return region if region and region != "ZZ" else None


# US toll-free prefixes; every other ten-digit North American number is local.
_TOLL_FREE_PREFIXES = ("800", "833", "844", "855", "866", "877", "888")


def is_us_local_number(e164: str) -> bool:
    """A ten-digit North American number outside the toll-free prefixes: what
    a port moves (porting takes local numbers only)."""
    digits = e164.lstrip("+")
    if len(digits) != 11 or not digits.startswith("1") or not digits.isdigit():
        return False
    area = digits[1:4]
    # NANP area codes never start with 0 or 1; toll-free codes are 8xx pairs.
    return area[0] not in "01" and area not in _TOLL_FREE_PREFIXES
