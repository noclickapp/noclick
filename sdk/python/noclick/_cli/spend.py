"""``--max-usd``: anything that spends says what it would cost before it runs, and runs only under the ceiling the
command line set. The figure is NoClick's own estimate (``noclick.estimate``, what ``noclick estimate`` prints), so
an agent never spends without having been told."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..estimate import Estimate, estimate
from . import output
from .exits import OverLimit


def check(items: List[Dict[str, Any]], max_usd: Optional[float], *, what: str, per: str = "a month") -> Estimate:
    """Price ``items`` (an estimate's items), say it, and refuse (``OverLimit``, exit 4) when it passes ``max_usd``.

    ``what`` names the action ("This session"), ``per`` what the figure covers ("a month", "at most")."""
    priced = estimate(items)
    total = priced.monthly_usd
    said = f"{what} costs about {output.usd(total)} {per}"
    if max_usd is not None and total > max_usd:
        raise OverLimit(f"{said}, over --max-usd {output.usd(max_usd)}: nothing was done.",
                        next_step="Raise --max-usd, or see each line with: noclick estimate --json",
                        details={"estimate_usd": total, "max_usd": max_usd}, run=["noclick estimate --json"])
    output.note(f"{said}{'' if max_usd is None else f' (under --max-usd {output.usd(max_usd)})'}.")
    return priced


def add_flag(parser: Any, *, what: str) -> None:
    """The ``--max-usd`` flag, worded for ``what`` spends."""
    parser.add_argument("--max-usd", type=float, metavar="USD",
                        help=f"The most {what} may cost, in US dollars: it's priced first and refused above it.")
