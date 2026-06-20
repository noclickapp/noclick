"""Shared helpers for ``WorkflowNode.load_field_options`` implementations.

Four primitives cover every dynamic-options field handler in the codebase:

- :func:`normalize_search` — call once in the handler to convert an empty /
  whitespace-only search to ``None`` so every per-node helper can treat
  ``not search`` uniformly as "no filter requested".
- :func:`require_credential_token` — fail loud when a loader has no
  credential token, so the load-options handler emits ``success=False`` and
  the frontend shows the "Open Credentials" prompt instead of a misleading
  "No options available".
- :func:`filter_options_by_search` — case-insensitive substring filter over
  the named option fields. Used by helpers whose upstream returns the whole
  set in one shot (no native search, no pagination).
- :func:`load_paginated_options` — the full paginate-all-then-filter
  strategy: when ``search`` is set, loops ``fetch_page`` until the cap or a
  null cursor and applies :func:`filter_options_by_search`; otherwise
  fetches a single page (preserving cursor pagination unchanged for
  non-search loads).

Use these instead of re-implementing per-node search loops — keeping the
``safety_cap`` constant, the substring-filter contract, and the cap-hit
logging in one place makes the behavior uniform across nodes and lets
future tuning (cap size, log format, search-field defaults) happen once.
"""

import logging
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    Iterable,
    List,
    Optional,
    Sequence,
    Tuple,
)

logger = logging.getLogger(__name__)

# Safety cap on items collected per paginate-all-then-filter load. Far above
# any real workspace's first-page size; high enough to make most searches
# find their match without devolving into an unbounded crawl when the user
# has 10,000+ items of whatever they're picking.
DYNAMIC_OPTIONS_SEARCH_CAP = 1000

OptionDict = Dict[str, Any]
PageFetcher = Callable[[Optional[str]], Awaitable[Tuple[Sequence[OptionDict], Optional[str]]]]


def normalize_search(search: Optional[str]) -> Optional[str]:
    """Trim ``search`` and return ``None`` if the result is empty.

    Apply once at the handler boundary so per-node helpers can treat
    ``not search`` as the single "no filter" sentinel.
    """
    if not search:
        return None
    trimmed = search.strip()
    return trimmed or None


def require_credential_token(token: Optional[str], message: str) -> str:
    """Return ``token`` or raise when it is missing.

    Dynamic-options loaders must fail loud (raise) — not return an empty list —
    when their credential token is absent. The load-options handler turns the
    raise into a ``success=False`` response, which is the only signal
    ``DynamicOptionsField`` treats as "show the Open Credentials button".
    Returning empty instead reads as a successful-but-empty load and renders
    "No options available", hiding the connect-account affordance.

    ``message`` is surfaced to the user in the dropdown, so phrase it as the
    action to take (e.g. "Connect a Google account to load spreadsheets").
    """
    if not token:
        raise ValueError(message)
    return token


def filter_options_by_search(
    options: Sequence[OptionDict],
    search: Optional[str],
    *,
    fields: Iterable[str] = ("label", "value"),
) -> List[OptionDict]:
    """Case-insensitive substring match on each option's named fields.

    Returns the input options unchanged (as a fresh list) when ``search`` is
    empty / ``None``. Defaults to searching both ``label`` and ``value``;
    pass a tighter ``fields`` tuple when an option carries IDs whose
    substrings would create false positives.
    """
    if not search:
        return list(options)
    needle = search.lower()
    return [
        opt
        for opt in options
        if any(needle in str(opt.get(field, "")).lower() for field in fields)
    ]


async def load_paginated_options(
    fetch_page: PageFetcher,
    *,
    page_token: Optional[str] = None,
    search: Optional[str] = None,
    cap: int = DYNAMIC_OPTIONS_SEARCH_CAP,
    fields: Iterable[str] = ("label", "value"),
    log_label: str = "dynamic_options",
) -> Dict[str, Any]:
    """Run the paginate-all-then-filter strategy in one call.

    ``fetch_page(cursor)`` returns ``(page_options, next_cursor)`` for the
    given cursor (or ``None`` for the first page).

    - With ``search``: loops ``fetch_page`` accumulating options until
      ``cap`` items are collected or the cursor runs out, then
      substring-filters by ``search`` on ``fields``. Returns the filtered
      set with ``next_page_token=None`` — the response represents a
      complete result-set for the query, not a window. Logs at INFO when
      ``cap`` is hit so partial coverage surfaces in backend logs.
    - Without ``search``: fetches a single page using ``page_token`` as the
      cursor and returns its ``(options, next_cursor)`` verbatim, so
      cursor-driven infinite scroll keeps working for non-search loads.
    """
    if not search:
        page_options, next_cursor = await fetch_page(page_token)
        return {
            "options": list(page_options),
            "next_page_token": next_cursor,
        }

    accumulated: List[OptionDict] = []
    cursor: Optional[str] = None
    while len(accumulated) < cap:
        page_options, next_cursor = await fetch_page(cursor)
        accumulated.extend(page_options)
        if not next_cursor:
            break
        cursor = next_cursor

    if len(accumulated) >= cap:
        logger.info(
            "[%s] search hit safety_cap=%d; results may be incomplete",
            log_label,
            cap,
        )
        accumulated = accumulated[:cap]

    return {
        "options": filter_options_by_search(accumulated, search, fields=fields),
        "next_page_token": None,
    }
