"""Granted-vs-requested scope check for every Google connect path.

Google's granular consent screen lets a person untick API scopes and still click
Continue; the token then carries only identity scopes, so every API call fails
with "insufficient authentication scopes" while the credential looks healthy.
Each path that persists a Google token rejects it here first.
"""

from typing import List, Optional


# Google always grants these identity scopes when ``email``/``profile``/
# ``openid`` are requested, and normalises ``email``/``profile`` to their
# ``userinfo.*`` aliases in the granted scope string. They're invisible on the
# consent screen (no checkbox), so we mustn't treat them as "user-skippable"
# when computing whether the user opted out of any *real* API scopes.
_GOOGLE_IMPLICIT_IDENTITY_SCOPES = frozenset({
    "openid",
    "email",
    "profile",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
})

# Scopes a node REQUESTS but does not REQUIRE to connect — a secondary
# capability the core credential can live without. They ride the consent screen
# (so a user who grants them unlocks the extra feature), but declining one must
# not block the connection. DV360's Bid Manager reporting scope is the case: the
# node needs `display-video` for ~all operations, while `doubleclickbidmanager`
# only powers the 3 report ops — requiring both would reject every user who
# unticks Bid Manager on Google's granular-consent screen.
_GOOGLE_OPTIONAL_SCOPES = frozenset({
    "https://www.googleapis.com/auth/doubleclickbidmanager",
})


# Map well-known scope prefixes to the human service name shown on Google's
# consent screen. Used only to make the missing-scopes error message friendly
# — falls back to the bare scope URL when nothing matches.
_GOOGLE_SCOPE_SERVICE_NAMES = (
    ("https://www.googleapis.com/auth/gmail.", "Gmail"),
    ("https://www.googleapis.com/auth/spreadsheets", "Google Sheets"),
    ("https://www.googleapis.com/auth/drive", "Google Drive"),
    ("https://www.googleapis.com/auth/devstorage", "Google Cloud Storage"),
    ("https://www.googleapis.com/auth/calendar", "Google Calendar"),
    ("https://www.googleapis.com/auth/documents", "Google Docs"),
    ("https://www.googleapis.com/auth/presentations", "Google Slides"),
    ("https://www.googleapis.com/auth/forms", "Google Forms"),
    ("https://www.googleapis.com/auth/tasks", "Google Tasks"),
    ("https://www.googleapis.com/auth/contacts", "Google Contacts"),
    ("https://www.googleapis.com/auth/youtube", "YouTube"),
    ("https://www.googleapis.com/auth/analytics", "Google Analytics"),
    ("https://www.googleapis.com/auth/adwords", "Google Ads"),
    ("https://www.googleapis.com/auth/business.manage", "Google Business Profile"),
    ("https://www.googleapis.com/auth/webmasters", "Google Search Console"),
)


def find_missing_granted_scopes(requested: List[str], granted: Optional[str]) -> List[str]:
    """Return the subset of ``requested`` API scopes the user didn't grant.

    Compares against the space-separated ``granted`` string Google returned in
    the token response. ``_GOOGLE_IMPLICIT_IDENTITY_SCOPES`` (always granted) and
    ``_GOOGLE_OPTIONAL_SCOPES`` (requested-but-not-required secondary features)
    are dropped from the requested set first — they'd otherwise reject a
    perfectly usable credential when the user declines a non-essential scope.

    Empty / whitespace-only ``granted`` is treated as "nothing granted" so a
    malformed token response surfaces every API scope as missing.
    """
    granted_set = set((granted or "").split())
    return [
        scope
        for scope in requested
        if scope not in _GOOGLE_IMPLICIT_IDENTITY_SCOPES
        and scope not in _GOOGLE_OPTIONAL_SCOPES
        and scope not in granted_set
    ]


def format_missing_scopes_message(missing: List[str]) -> str:
    """Build the user-facing error for a missing-scopes credential rejection.

    Groups scopes by the well-known service name (Gmail, Google Sheets, etc.)
    so the message tells the user exactly which checkbox on Google's consent
    screen they need to tick on the next retry.
    """
    services = []
    leftover = []
    for scope in missing:
        for prefix, name in _GOOGLE_SCOPE_SERVICE_NAMES:
            if scope.startswith(prefix):
                if name not in services:
                    services.append(name)
                break
        else:
            leftover.append(scope)

    labels = services + leftover
    if len(labels) == 1:
        permission = labels[0]
    elif len(labels) == 2:
        permission = f"{labels[0]} and {labels[1]}"
    else:
        permission = ", ".join(labels[:-1]) + f", and {labels[-1]}"

    return (
        f"Google didn't grant the {permission} permission. "
        "Please reconnect and make sure every checkbox on Google's consent "
        "screen is checked before clicking Continue."
    )
