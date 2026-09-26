"""Per-account rollout of features that are built but not yet for everyone.

A feature starts INTERNAL (the hosted team's own accounts, via
utils.internal_users) and flips to EVERYONE in one line when it launches. In
between, single accounts can be let in by name (``allow_accounts``): a
customer piloting a feature is not staff, and the staff list is an
authorization boundary (debug routes, admin tools), never a rollout list.
The socket handler is the enforcement point; frontend/app/lib/featureGates.ts
mirrors this table only to hide the surface. A self-hosted install sees the
feature once it is EVERYONE.
"""

from __future__ import annotations

from typing import Dict, Iterable, Set

from utils.internal_users import is_internal_user

INTERNAL = "internal"
EVERYONE = "everyone"

FEATURE_ROLLOUT: dict[str, str] = {
    # Verified phone linking (Settings → Phone) and the channels keyed on it.
    "phone_channel": EVERYONE,
    # The account coordinator, on every channel (it triages every account's
    # failures, so every account needs it).
    "coordinator": EVERYONE,
    # Plan, credit balance and owner confirmation still gate each purchase.
    "phone_numbers": EVERYONE,
}

# Accounts let into an INTERNAL feature by email, lower-cased. Empty in the
# engine; the hosted edition registers its pilots at bootstrap.
FEATURE_ALLOWLIST: Dict[str, Set[str]] = {}


class FeatureNotAvailable(PermissionError):
    def __init__(self, feature: str):
        super().__init__("This feature isn't available on your account yet")
        self.feature = feature


def allow_accounts(feature: str, emails: Iterable[str]) -> None:
    """Let these accounts use an INTERNAL feature ahead of its launch."""
    FEATURE_ROLLOUT[feature]  # a typo is a KeyError, never a silent no-op
    FEATURE_ALLOWLIST.setdefault(feature, set()).update(e.strip().lower() for e in emails if e and e.strip())


def is_feature_enabled(feature: str, *, email: str | None) -> bool:
    rollout = FEATURE_ROLLOUT[feature]  # a typo is a KeyError, never a silent False
    if rollout == EVERYONE:
        return True
    if not email:
        return False
    return is_internal_user(email) or email.lower() in FEATURE_ALLOWLIST.get(feature, ())


def require_feature(feature: str, *, email: str | None) -> None:
    if not is_feature_enabled(feature, email=email):
        raise FeatureNotAvailable(feature)
