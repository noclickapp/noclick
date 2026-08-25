"""Tests for the Google OAuth scope-validation helpers.

These guard the fix for Google's "granular consent" UX, where users can
uncheck individual scopes on the consent screen while still clicking
Continue — producing tokens that look fine to the OAuth callback but fail
every API call at runtime. The handler now compares granted vs requested
scopes and refuses the credential up-front.
"""

import pytest

from wss.handlers.oauth.google_oauth_handler import (
    GoogleOAuthHandler,
    find_missing_granted_scopes,
    format_missing_scopes_message,
)


# ---------------------------------------------------------------------------
# _get_credential_type_from_scopes — scope → credential_type routing
# ---------------------------------------------------------------------------

_credential_type = GoogleOAuthHandler._get_credential_type_from_scopes


@pytest.mark.parametrize(
    "scopes,expected",
    [
        (["https://www.googleapis.com/auth/meetings.space.created"], "google_meet_oauth"),
        (["https://www.googleapis.com/auth/meetings.space.readonly"], "google_meet_oauth"),
        (["https://www.googleapis.com/auth/meetings.space.settings"], "google_meet_oauth"),
        (
            [
                "https://www.googleapis.com/auth/meetings.space.created",
                "https://www.googleapis.com/auth/meetings.space.readonly",
                "https://www.googleapis.com/auth/meetings.space.settings",
                "email",
                "profile",
            ],
            "google_meet_oauth",
        ),
        (["https://www.googleapis.com/auth/webmasters"], "google_search_console_oauth"),
        (["https://www.googleapis.com/auth/spreadsheets"], "google_sheets_oauth"),
        # DV360: either sensitive scope resolves to dv360_oauth (must beat the
        # generic drive/fallback branches so a connected DV360 account matches
        # the node's type filter).
        (["https://www.googleapis.com/auth/display-video"], "dv360_oauth"),
        (["https://www.googleapis.com/auth/doubleclickbidmanager"], "dv360_oauth"),
        (
            [
                "https://www.googleapis.com/auth/display-video",
                "https://www.googleapis.com/auth/doubleclickbidmanager",
                "email",
                "profile",
            ],
            "dv360_oauth",
        ),
        (["email", "profile"], "google_oauth"),
    ],
)
def test_credential_type_from_scopes(scopes, expected):
    # Meet's scopes must resolve to google_meet_oauth (the node's required type),
    # not the google_oauth fallback — else a freshly connected Meet credential
    # never matches the node. _get_credential_type_from_scopes ignores self.
    assert _credential_type(None, scopes) == expected


# ---------------------------------------------------------------------------
# find_missing_granted_scopes
# ---------------------------------------------------------------------------


GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.labels",
    "https://www.googleapis.com/auth/gmail.settings.basic",
    "email",
    "profile",
]


def test_all_requested_granted_returns_empty():
    granted = " ".join(GMAIL_SCOPES + ["openid"])
    assert find_missing_granted_scopes(GMAIL_SCOPES, granted) == []


def test_user_unchecked_all_api_scopes_returns_all_api_scopes():
    # This is the exact prod scenario that motivated the fix: user clicked
    # Continue on the granular consent screen with only the identity boxes
    # ticked, so Google returned a token with no real API scopes.
    granted = (
        "https://www.googleapis.com/auth/userinfo.profile "
        "openid "
        "https://www.googleapis.com/auth/userinfo.email"
    )
    missing = find_missing_granted_scopes(GMAIL_SCOPES, granted)
    # All four gmail.* scopes are missing; email/profile/openid are implicit.
    assert missing == [
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/gmail.compose",
        "https://www.googleapis.com/auth/gmail.labels",
        "https://www.googleapis.com/auth/gmail.settings.basic",
    ]


def test_partial_grant_returns_only_the_missing_ones():
    granted = (
        "https://www.googleapis.com/auth/gmail.modify "
        "https://www.googleapis.com/auth/userinfo.email "
        "openid"
    )
    missing = find_missing_granted_scopes(GMAIL_SCOPES, granted)
    assert missing == [
        "https://www.googleapis.com/auth/gmail.compose",
        "https://www.googleapis.com/auth/gmail.labels",
        "https://www.googleapis.com/auth/gmail.settings.basic",
    ]


def test_implicit_identity_scopes_dropped_from_requested_set():
    # If the caller requests only the implicit identity scopes, nothing can
    # be "missing" — they're always auto-granted. (Edge case: a credential
    # that genuinely only wants sign-in info.)
    requested = ["email", "profile"]
    granted = "openid https://www.googleapis.com/auth/userinfo.email https://www.googleapis.com/auth/userinfo.profile"
    assert find_missing_granted_scopes(requested, granted) == []


@pytest.mark.parametrize("granted_value", ["", "   ", None])
def test_empty_granted_treats_every_api_scope_as_missing(granted_value):
    # A malformed token response (empty scope string or null) should fail
    # closed — every API scope surfaces as missing rather than silently
    # accepting a useless token.
    requested = ["https://www.googleapis.com/auth/spreadsheets", "email"]
    assert find_missing_granted_scopes(requested, granted_value) == [
        "https://www.googleapis.com/auth/spreadsheets",
    ]


DV360_SCOPES = [
    "https://www.googleapis.com/auth/display-video",
    "https://www.googleapis.com/auth/doubleclickbidmanager",
    "email",
    "profile",
]


def test_dv360_optional_bidmanager_scope_does_not_block_connection():
    # DV360 requests both sensitive scopes, but doubleclickbidmanager only
    # powers the Bid Manager report ops. A user who unticks it on Google's
    # granular-consent screen must still be able to connect for the ~all
    # display-video operations — so it's absent from the missing set.
    granted = (
        "https://www.googleapis.com/auth/display-video "
        "https://www.googleapis.com/auth/userinfo.email "
        "openid"
    )
    assert find_missing_granted_scopes(DV360_SCOPES, granted) == []


def test_dv360_core_display_video_scope_is_still_required():
    # display-video is NOT optional — declining it yields an unusable
    # credential and must still be rejected.
    granted = (
        "https://www.googleapis.com/auth/doubleclickbidmanager "
        "https://www.googleapis.com/auth/userinfo.email "
        "openid"
    )
    assert find_missing_granted_scopes(DV360_SCOPES, granted) == [
        "https://www.googleapis.com/auth/display-video",
    ]


def test_granted_with_extra_scopes_is_still_satisfied():
    # If Google grants scopes we didn't ask for (e.g. legacy bundle), we
    # only care that all requested ones are present.
    granted = (
        "https://www.googleapis.com/auth/gmail.modify "
        "https://www.googleapis.com/auth/gmail.compose "
        "https://www.googleapis.com/auth/gmail.labels "
        "https://www.googleapis.com/auth/gmail.settings.basic "
        "https://www.googleapis.com/auth/userinfo.email "
        "https://www.googleapis.com/auth/userinfo.profile "
        "openid "
        "https://www.googleapis.com/auth/calendar"  # unrequested extra
    )
    assert find_missing_granted_scopes(GMAIL_SCOPES, granted) == []


# ---------------------------------------------------------------------------
# format_missing_scopes_message
# ---------------------------------------------------------------------------


def test_format_single_known_service():
    msg = format_missing_scopes_message(
        ["https://www.googleapis.com/auth/gmail.modify"]
    )
    assert "Gmail" in msg
    assert "Google's consent screen" in msg


def test_format_collapses_multiple_scopes_for_same_service():
    msg = format_missing_scopes_message(
        [
            "https://www.googleapis.com/auth/gmail.modify",
            "https://www.googleapis.com/auth/gmail.compose",
            "https://www.googleapis.com/auth/gmail.labels",
        ]
    )
    # Should mention Gmail once, not three times.
    assert msg.count("Gmail") == 1


def test_format_two_services_uses_and():
    msg = format_missing_scopes_message(
        [
            "https://www.googleapis.com/auth/gmail.compose",
            "https://www.googleapis.com/auth/spreadsheets",
        ]
    )
    assert "Gmail and Google Sheets" in msg


def test_format_three_services_uses_oxford_comma():
    msg = format_missing_scopes_message(
        [
            "https://www.googleapis.com/auth/gmail.compose",
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive.file",
        ]
    )
    assert "Gmail, Google Sheets, and Google Drive" in msg


def test_format_unknown_scope_falls_back_to_raw_url():
    msg = format_missing_scopes_message(
        ["https://www.googleapis.com/auth/some.future.scope"]
    )
    # No friendly name → show the URL so the message is still actionable.
    assert "some.future.scope" in msg


def test_format_cloud_storage_scope_uses_friendly_service_name():
    msg = format_missing_scopes_message(
        ["https://www.googleapis.com/auth/devstorage.read_write"]
    )
    assert "Google Cloud Storage" in msg


def test_scope_to_credential_type_maps_cloud_storage_scopes():
    handler = GoogleOAuthHandler(sio=None)
    credential_type = handler._get_credential_type_from_scopes(
        ["https://www.googleapis.com/auth/devstorage.read_write"]
    )
    assert credential_type == "google_cloud_storage_oauth"
