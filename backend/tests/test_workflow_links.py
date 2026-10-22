"""A link the backend mints to a workflow opens it in the app: its path is served by the dashboard's route
(not a template's public page, which 404s on a workflow's id), and its query names the canvas tab and the
workflow the way the dashboard reads them."""

import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from utils.email import FRONTEND_URL, workflow_url

FRONTEND_APP = Path(__file__).resolve().parents[2] / "frontend" / "app"
ROUTE_ROOTS = ("routes", "cloud/routes")


def _route_for(path: str) -> Path:
    """The module ``frontend/app/routes.ts`` serves ``path`` from: files named by dot- or folder-delimited
    segments, ``$x`` a parameter, a static match ranked before a parameter's as React Router ranks them."""
    wanted = path.strip("/").split("/")
    matches = []
    for root in ROUTE_ROOTS:
        base = FRONTEND_APP / root
        for file in base.rglob("*.tsx") if base.exists() else ():
            if any(part in file.name for part in (".test.", ".server.", ".client.")):
                continue
            segments = re.split(r"[/.]", str(file.relative_to(base))[: -len(".tsx")])
            if segments[-1] == "index":
                segments.pop()
            if len(segments) == len(wanted) and all(s == w or s.startswith("$") for s, w in zip(segments, wanted)):
                matches.append((sum(s.startswith("$") for s in segments), str(file)))
    assert matches, f"no route serves {path}"
    return Path(min(matches)[1])


def test_a_workflow_link_opens_it_on_its_canvas():
    url = workflow_url("wf-1")
    parts = urlsplit(url)
    assert url.startswith(FRONTEND_URL)
    assert _route_for(parts.path) == FRONTEND_APP / "routes" / "dashboard.tsx", parts.path
    assert parse_qs(parts.query) == {"tab": ["workflows"], "workflow": ["wf-1"]}
    # The dashboard opens its canvas tab on tab=workflows, and the browser opens the workflow it names.
    assert "urlTab === 'workflows'" in (FRONTEND_APP / "components" / "Dashboard.tsx").read_text()
    assert "params.get('workflow')" in (FRONTEND_APP / "components" / "workflow" / "WorkflowBrowser.tsx").read_text()
