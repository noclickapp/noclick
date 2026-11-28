"""``noclick changelog``'s source: the docs' changelog page as Markdown (``<docs>/changelog.md``), read with no key.

The page has a ``## <Month D, YYYY>`` heading a day, newest first, and under it a ``### <title>`` an entry: a
``<Kind> · <areas>`` line, then its body. Each entry's ``slug`` is its title's (``noclick changelog <slug>`` prints it
whole), and its URL its anchor on its month's page. ``NOCLICK_DOCS_URL`` points at another site's docs (a self-hosted
install's). The npm CLI reads it the same way (``src/cli/changelog.ts``).
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

DOCS_URL_ENV = "NOCLICK_DOCS_URL"
DEFAULT_DOCS_URL = "https://www.noclick.com/docs"
_DAY = re.compile(r"^## ([A-Z][a-z]+ \d{1,2}, \d{4})\s*$")
_KIND = re.compile(r"^(New|Improved|Fixed) · (.+)$")


def docs_url() -> str:
    return (os.environ.get(DOCS_URL_ENV) or DEFAULT_DOCS_URL).rstrip("/")


def page_url() -> str:
    return f"{docs_url()}/changelog.md"


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower().strip()).strip("-")


def parse(markdown: str, base: str) -> List[Dict[str, Any]]:
    """The page's entries, newest day first and a day's in the page's order: ``date``, ``title``, ``slug``, ``kind``
    and ``areas`` (null where the entry has no kind line), ``url`` and ``body``."""
    entries: List[Dict[str, Any]] = []
    date: Optional[str] = None
    current: Optional[Dict[str, Any]] = None
    lines: List[str] = []

    def close() -> None:
        if current is None:
            return
        while lines and not lines[0].strip():
            lines.pop(0)
        kind = _KIND.match(lines[0]) if lines else None
        if kind:
            lines.pop(0)
        current.update(kind=kind.group(1).lower() if kind else None, areas=kind.group(2) if kind else None,
                       body="\n".join(lines).strip())
        entries.append(current)

    for line in markdown.splitlines():
        if line.startswith("## "):
            close()
            current, lines = None, []
            day = _DAY.match(line)
            date = datetime.strptime(day.group(1), "%B %d, %Y").strftime("%Y-%m-%d") if day else None
        elif line.startswith("### ") and date:
            close()
            title = line[4:].strip()
            slug = slugify(title)
            current, lines = {"date": date, "title": title, "slug": slug,
                              "url": f"{base}/changelog/{date[:7]}#{date}-{slug}"}, []
        elif current is not None:
            lines.append(line)
    close()
    return sorted(entries, key=lambda e: e["date"], reverse=True)


def find(entries: List[Dict[str, Any]], query: str) -> List[Dict[str, Any]]:
    """The entries ``query`` names: by slug (with its date, after or before it, or without) or title, else those whose
    title holds it."""
    wanted = query.strip().lower()
    exact = [e for e in entries
             if wanted in (e["slug"], f"{e['slug']}-{e['date']}", f"{e['date']}-{e['slug']}", e["title"].lower())]
    slug = slugify(wanted)
    return exact or [e for e in entries if wanted and (wanted in e["title"].lower() or (slug and slug in e["slug"]))]


def ref(entry: Dict[str, Any], entries: List[Dict[str, Any]]) -> str:
    """What names ``entry`` alone: its slug, followed by its date where another day has a change so called."""
    alone = sum(e["slug"] == entry["slug"] for e in entries) == 1
    return entry["slug"] if alone else f"{entry['slug']}-{entry['date']}"
