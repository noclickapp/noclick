"""Rotation-response hardening: no silent refresh-token fallback (F05 prevention).

Providers with single-use rotating refresh tokens must never fall back to the
just-consumed token when the refresh response omits a new one — persisting it
guarantees the next refresh bricks the credential, silently and days later.
``require_rotated_refresh_token`` raises immediately instead, and the choke
point classifies it as ``provider_200_missing_field`` (F04).
"""

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from nodes.core.oauth_refresh import (
    RotatedRefreshTokenMissing,
    ensure_fresh_oauth_token,
    require_rotated_refresh_token,
)

BACKEND = Path(__file__).resolve().parent.parent

# Modules whose provider rotates single-use refresh tokens on every refresh.
ROTATING_OAUTH_MODULES = [
    "nodes/oauth/slack_oauth.py",
    "nodes/oauth/twitter_oauth.py",
    "nodes/oauth/linear_oauth.py",
    "nodes/oauth/typeform_oauth.py",
    "nodes/oauth/supabase_oauth.py",
    "nodes/oauth/tiktok_oauth.py",
    "nodes/oauth/canva_oauth.py",
    "nodes/oauth/gitlab_oauth.py",
    "nodes/oauth/box_oauth.py",
    "nodes/oauth/sentry_oauth.py",
]

_SILENT_FALLBACK = re.compile(
    r"""get\(\s*["']refresh_token["']\s*,\s*refresh_token\s*\)"""
)


def test_helper_returns_rotated_token():
    assert require_rotated_refresh_token(
        {"refresh_token": "rt-new"}, provider="slack"
    ) == "rt-new"


@pytest.mark.parametrize("payload", [{}, {"refresh_token": ""}, {"refresh_token": None}])
def test_helper_raises_on_missing_token(payload):
    with pytest.raises(RotatedRefreshTokenMissing, match="slack"):
        require_rotated_refresh_token(payload, provider="slack")


def test_no_silent_fallback_in_rotating_modules():
    """Structural pin: the ``get("refresh_token", refresh_token)`` fallback must
    not reappear in any rotating provider's oauth module."""
    violations = []
    for rel in ROTATING_OAUTH_MODULES:
        text = (BACKEND / rel).read_text()
        for match in _SILENT_FALLBACK.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            violations.append(f"{rel}:{line}")
    assert not violations, (
        "Silent refresh-token fallback in rotating provider modules — use "
        f"require_rotated_refresh_token instead: {violations}"
    )


async def test_choke_point_classifies_missing_rotation_as_f04():
    expired = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    cred = {"access_token": "stale", "refresh_token": "r1", "expires_at": expired}
    audit_rows = []

    async def capture(row):
        audit_rows.append(row)

    with patch(
        "utils.credential_loader.load_credential",
        new=AsyncMock(return_value=dict(cred)),
    ), patch(
        "nodes.core.oauth_refresh.record_refresh_event", new=capture
    ):
        with pytest.raises(ValueError, match="refresh failed"):
            await ensure_fresh_oauth_token(
                pool=object(), credential_id="cid", user_id="uid",
                credential=cred, provider="slack",
                refresh=AsyncMock(
                    side_effect=RotatedRefreshTokenMissing("slack response missing refresh_token")
                ),
            )
    assert len(audit_rows) == 1
    assert audit_rows[0]["phase_outcome"] == "provider_200_missing_field"
    assert audit_rows[0]["failure_mode_id"] == "F04"
