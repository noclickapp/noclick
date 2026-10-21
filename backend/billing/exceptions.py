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
    # A balance in debt reads as none left: the recognizer takes no sign.
    return f"Insufficient credits: {max(remaining, 0.0):.2f} < {required:.2f} required"


def match_insufficient_credits(text: Optional[str]) -> Optional[re.Match]:
    return INSUFFICIENT_CREDITS_RE.search(text) if text else None


# The account's own monthly spending cap: minted only by spend_cap_message,
# recognised only by match_spend_cap. Group 1 is the cap in dollars.
WHERE_CAP_IS_RAISED = "Settings → Plan and billing"
# An account no person has claimed yet (an agent's own sign-up) spends only funds paid into it
# until one does: the cap's refusal in its own words, minted only by unclaimed_message and told
# apart by match_unclaimed (group 1 is then None).
_UNCLAIMED = "no person has claimed it yet, so it spends only funds paid into it"
UNCLAIMED_RE = re.compile(re.escape(_UNCLAIMED))
SPEND_CAP_RE = re.compile(r"your \$([\d,]+(?:\.\d{1,2})?) monthly cap\b[^\n]*" + re.escape(WHERE_CAP_IS_RAISED)
                          + "|" + UNCLAIMED_RE.pattern)


def _dollars(usd) -> str:
    value = float(usd)
    return f"${value:,.0f}" if value == int(value) else f"${value:,.2f}"


def spend_cap_message(cap_usd, resets_on: str, *, price_usd=None, left_usd=None) -> str:
    """The refusal at the account's monthly cap (``resets_on``: the day the period
    ends, as a person reads it), or of something priced at ``price_usd`` that
    would cross it with ``left_usd`` of it left."""
    if price_usd is not None:
        return (f"This costs {_dollars(price_usd)}, more than the {_dollars(max(float(left_usd or 0), 0.0))} left "
                f"of your {_dollars(cap_usd)} monthly cap. It resets on {resets_on}, or raise it in "
                f"{WHERE_CAP_IS_RAISED}.")
    return (f"You've hit your {_dollars(cap_usd)} monthly cap, so work that costs money waits until it resets on "
            f"{resets_on}, or until you raise it in {WHERE_CAP_IS_RAISED}.")


def unclaimed_message() -> str:
    return f"This account was made by an agent and {_UNCLAIMED}, and none are left for this."


def match_spend_cap(text: Optional[str]) -> Optional[re.Match]:
    return SPEND_CAP_RE.search(text) if text else None


def match_unclaimed(text: Optional[str]) -> Optional[re.Match]:
    return UNCLAIMED_RE.search(text) if text else None


def match_spend_refusal(text: Optional[str]) -> Optional[re.Match]:
    """Either of NoClick's own refusals to spend: credits ran out, or the account's cap was reached."""
    return match_insufficient_credits(text) or match_spend_cap(text)


class SpendCapReached(InsufficientBalanceError):
    """The paying account reached the monthly cap its owner set: stopped like
    credits running out, in its own words (``spend_cap_message``)."""


class AccountUnclaimed(SpendCapReached):
    """The paying account is one no person has claimed yet (``unclaimed_message``)."""


class UnpricedUsage(ValueError):
    """A charge its payer's plan bills at vendor cost, naming no vendor cost:
    refused (and logged) rather than priced at a guess."""


class OwnerResolutionError(RuntimeError):
    """Compatibility error for an unresolved usage-attribution subject."""


class OwnerLookupFailed(OwnerResolutionError):
    """The subject's owner couldn't be read (the database failed), as opposed to
    there being none: the same refusal, but worth retrying."""
