"""Unit tests for ``nodes.core.dynamic_options``.

These helpers back the dynamic-options ``search`` flow for ~27 node types;
the three primitives must hold strictly, otherwise per-node behavior drifts
silently across the codebase.
"""

import pytest

from nodes.core.dynamic_options import (
    DYNAMIC_OPTIONS_SEARCH_CAP,
    filter_options_by_search,
    load_paginated_options,
    normalize_search,
)


# ---------------------------------------------------------------------------
# normalize_search
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        (None, None),
        ("", None),
        ("   ", None),
        ("\t\n", None),
        ("foo", "foo"),
        ("  foo  ", "foo"),
        ("Mixed Case", "Mixed Case"),  # case is preserved; filter is case-insensitive
    ],
)
def test_normalize_search(raw, expected):
    assert normalize_search(raw) == expected


# ---------------------------------------------------------------------------
# filter_options_by_search
# ---------------------------------------------------------------------------


def _opts(*pairs):
    """Tiny helper for inline options."""
    return [{"label": label, "value": value} for label, value in pairs]


def test_filter_returns_unchanged_when_search_empty():
    options = _opts(("#general", "C1"), ("#random", "C2"))
    result = filter_options_by_search(options, None)
    assert result == options
    # Must be a fresh list — callers must be free to mutate without
    # surprising shared state.
    assert result is not options


def test_filter_is_case_insensitive_substring_on_label_and_value():
    options = _opts(("Announcements", "C1"), ("backend-team", "C2"), ("misc", "C3"))
    assert [o["value"] for o in filter_options_by_search(options, "BACK")] == ["C2"]
    assert [o["value"] for o in filter_options_by_search(options, "c2")] == ["C2"]


def test_filter_search_fields_can_be_restricted():
    options = _opts(("Reporting", "rpt-id-with-misc-token"), ("Random", "C2"))
    # Default scans label + value, so "misc" hits via value substring.
    assert len(filter_options_by_search(options, "misc")) == 1
    # Narrowing to label only ignores the value match.
    assert filter_options_by_search(options, "misc", fields=("label",)) == []


def test_filter_handles_missing_or_non_string_fields():
    options = [
        {"label": None, "value": "C1"},
        {"label": "thing", "value": 42},  # int value — must not crash
        {},  # entirely missing
    ]
    # 'thing' substring should hit; the others should silently drop out.
    assert filter_options_by_search(options, "thi") == [
        {"label": "thing", "value": 42},
    ]
    # An integer-valued search term shouldn't be passed to needle.lower() in
    # the first place — but a number-as-string in the value field should hit.
    assert filter_options_by_search(options, "42") == [
        {"label": "thing", "value": 42},
    ]


# ---------------------------------------------------------------------------
# load_paginated_options
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_search_returns_single_page_verbatim():
    calls = []

    async def fetch_page(cursor):
        calls.append(cursor)
        return _opts(("a", "A"), ("b", "B")), "next-cursor"

    out = await load_paginated_options(fetch_page, page_token="cur-7")
    # Single fetch with the supplied page_token forwarded as the cursor;
    # next_page_token is whatever the page returned (so scroll pagination
    # in the frontend keeps working unchanged).
    assert calls == ["cur-7"]
    assert out == {
        "options": _opts(("a", "A"), ("b", "B")),
        "next_page_token": "next-cursor",
    }


@pytest.mark.asyncio
async def test_search_paginates_until_cursor_exhausted_then_filters():
    pages = [
        (_opts(("apple", "1"), ("banana", "2")), "c2"),
        (_opts(("avocado", "3"), ("orange", "4")), "c3"),
        (_opts(("apricot", "5")), None),  # last page
    ]
    cursors_seen = []

    async def fetch_page(cursor):
        cursors_seen.append(cursor)
        return pages.pop(0)

    out = await load_paginated_options(fetch_page, search="ap")
    # All pages were walked (None → c2 → c3).
    assert cursors_seen == [None, "c2", "c3"]
    # Substring filter is case-insensitive and applied across labels (and
    # values, by default) on the accumulated set.
    assert [o["label"] for o in out["options"]] == ["apple", "apricot"]
    assert out["next_page_token"] is None  # filtered result = complete set


@pytest.mark.asyncio
async def test_search_stops_at_cap_and_filters_within_cap(caplog):
    # Every page returns 3 items; cap=4 means we stop after page 2 (6 items
    # accumulated, truncated to 4) and filter just those.
    pages = [
        (_opts(("foo-1", "1"), ("bar-2", "2"), ("foo-3", "3")), "c2"),
        (_opts(("bar-4", "4"), ("foo-5", "5"), ("bar-6", "6")), "c3"),
        # If pagination cap doesn't kick in, we'd reach this — would assert below.
        (_opts(("never-seen", "99")), None),
    ]

    async def fetch_page(cursor):
        return pages.pop(0)

    with caplog.at_level("INFO", logger="nodes.core.dynamic_options"):
        out = await load_paginated_options(
            fetch_page, search="foo", cap=4, log_label="test_cap"
        )
    # Accumulated set capped at 4: ["foo-1","bar-2","foo-3","bar-4"]; filtering
    # "foo" leaves the first and third.
    assert [o["label"] for o in out["options"]] == ["foo-1", "foo-3"]
    # The third page must NOT have been fetched once the cap was met.
    assert pages == [(_opts(("never-seen", "99")), None)]
    # Cap-hit message surfaces in backend logs.
    assert any("safety_cap=4" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_search_with_empty_first_page_returns_empty_no_filter_error():
    async def fetch_page(cursor):
        return [], None

    out = await load_paginated_options(fetch_page, search="anything")
    assert out == {"options": [], "next_page_token": None}


def test_default_cap_is_centralized_constant():
    # Guard against accidentally reintroducing magic numbers in callers.
    assert DYNAMIC_OPTIONS_SEARCH_CAP == 1000
