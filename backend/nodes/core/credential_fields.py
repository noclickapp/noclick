"""Shaping rules for the fields of a manual credential.

A pasted value is rarely the value: a key arrives with a trailing newline, a
host arrives as the whole browser URL, a token field receives the page the
token was supposed to come from. These helpers turn the common paste into the
value the provider wants, and raise a plain ``ValueError`` — Pydantic shows its
text under the field — when no reading of the input can be right.

Credential classes call them from validators. ``credential_connect`` applies
``clean_secret`` to every password-widget field and strips every string field
without any declaration, so a class only declares what is specific to it.
"""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlsplit

_URL_SHAPED = re.compile(r"^(?:[a-z][a-z0-9+.-]*://|www\.)", re.I)
# Whole-value matches only: a short bracketed stub, a "your api key" prompt, or
# a run of x/*/. — never a JSON key file, which also starts with a brace.
_PLACEHOLDER = re.compile(
    r"^(?:<[^<>\"\n]{1,80}>|\[[^\[\]\"\n]{1,80}\]|\{[^{}\"\n]{1,80}\}"
    r"|(?:your|my|paste|enter|insert)[-_ ][a-z].{0,60}|x{6,}|\*{4,}|\.{3,})$",
    re.I,
)
_SECRET_FIELD = re.compile(r"(?:^|_)(?:api_?key|key|token|secret|password|passwd|pat)(?:_|$)", re.I)
_ADDRESS_FIELD = re.compile(r"url|uri|host|domain|endpoint", re.I)


def is_url_shaped(value: object) -> bool:
    return isinstance(value, str) and bool(_URL_SHAPED.match(value.strip()))


def is_placeholder(value: object) -> bool:
    return isinstance(value, str) and bool(_PLACEHOLDER.match(value.strip()))


def looks_like_secret_field(name: str) -> bool:
    """Field names that hold a secret by convention (``api_key``, ``pat_secret``).

    An address that merely mentions a token (``token_url``) is not a secret and
    must keep accepting URLs.
    """
    return bool(_SECRET_FIELD.search(name or "")) and not _ADDRESS_FIELD.search(name or "")


def clean_secret(value: object, *, field_name: str = "This value") -> str:
    """A secret with the paste noise removed, or a ValueError naming what is wrong.

    Emptiness is left to the schema (required vs optional); this only judges
    values that are present.
    """
    text = (value if isinstance(value, str) else str(value or "")).strip()
    if not text:
        return text
    if is_url_shaped(text):
        raise ValueError(
            f"{field_name} looks like a web address. Paste the value itself, "
            f"not the page it comes from."
        )
    if is_placeholder(text):
        raise ValueError(f"{field_name} still holds placeholder text.")
    return text


def https_origin(value: object, *, field_name: str = "Server URL") -> str:
    """The canonical origin out of anything a browser bar might hold.

    ``https://us-east-1.online.tableau.com/#/site/acme/home`` and
    ``us-east-1.online.tableau.com`` both become
    ``https://us-east-1.online.tableau.com``. Path, query and fragment are
    dropped — they are navigation, not the API host. Scheme defaults to https
    and http is kept only when written explicitly (self-hosted servers).
    """
    raw = (value if isinstance(value, str) else str(value or "")).strip()
    if not raw:
        return raw
    candidate = raw if "://" in raw else f"https://{raw}"
    try:
        parts = urlsplit(candidate)
        port = parts.port
    except ValueError as e:
        raise ValueError(f"{field_name} is not a valid URL.") from e
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise ValueError(f"{field_name} must start with https://")
    if parts.username is not None or parts.password is not None:
        raise ValueError(f"{field_name} must not contain a username or password.")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host or ("." not in host and host != "localhost"):
        raise ValueError(f"{field_name} needs a host name, e.g. https://example.com")
    return f"{scheme}://{host}" + (f":{port}" if port else "")


def segment_after(value: object, marker: str) -> Optional[str]:
    """The path segment following ``marker`` in a URL's path or fragment.

    ``segment_after("https://x.online.tableau.com/#/site/acme/home", "site")``
    is ``"acme"`` — the smart-paste primitive for tenant slugs a browser URL
    carries after a fixed word.
    """
    raw = (value if isinstance(value, str) else "").strip()
    if not raw or "/" not in raw:
        return None
    try:
        parts = urlsplit(raw if "://" in raw else f"https://{raw}")
    except ValueError:
        return None
    for route in (parts.fragment, parts.path):
        segments = [s for s in (route or "").split("/") if s]
        for i, seg in enumerate(segments[:-1]):
            if seg.lower() == marker.lower():
                return segments[i + 1] or None
    return None
