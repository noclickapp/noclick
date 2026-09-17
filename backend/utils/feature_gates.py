"""Per-account rollout of features that are built but not yet for everyone.

A feature starts INTERNAL (the hosted team's own accounts, via
utils.internal_users) and flips to EVERYONE in one line when it launches. The
socket handler is the enforcement point; frontend/app/lib/featureGates.ts
mirrors this table only to hide the surface. A self-hosted install sees the
feature once it is EVERYONE.
"""

from __future__ import annotations

from utils.internal_users import is_internal_user

INTERNAL = "internal"
EVERYONE = "everyone"

FEATURE_ROLLOUT: dict[str, str] = {
    # Verified phone linking (Settings → Phone) and the channels keyed on it.
    "phone_channel": INTERNAL,
    # The account coordinator (Dashboard dock; later WhatsApp and calls).
    "coordinator": INTERNAL,
}


class FeatureNotAvailable(PermissionError):
    def __init__(self, feature: str):
        super().__init__("This feature isn't available on your account yet")
        self.feature = feature


def is_feature_enabled(feature: str, *, email: str | None) -> bool:
    rollout = FEATURE_ROLLOUT[feature]  # a typo is a KeyError, never a silent False
    if rollout == EVERYONE:
        return True
    return bool(email) and is_internal_user(email)


def require_feature(feature: str, *, email: str | None) -> None:
    if not is_feature_enabled(feature, email=email):
        raise FeatureNotAvailable(feature)
