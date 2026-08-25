"""Compatibility exceptions for optional instance usage policy."""

import re
from typing import Optional


class InsufficientBalanceError(RuntimeError):
    """Raised when a registered operator policy denies a metered action."""


INSUFFICIENT_CREDITS_RE = re.compile(
    r"insufficient credits: (\d+(?:\.\d+)?) < (\d+(?:\.\d+)?) required",
    re.IGNORECASE,
)


def insufficient_credits_message(remaining: float, required: float) -> str:
    return f"Insufficient credits: {remaining:.2f} < {required:.2f} required"


def match_insufficient_credits(text: Optional[str]) -> Optional[re.Match]:
    return INSUFFICIENT_CREDITS_RE.search(text) if text else None


class OwnerResolutionError(RuntimeError):
    """Compatibility error for an unresolved usage-attribution subject."""
