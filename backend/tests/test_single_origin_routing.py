"""On one origin, a backend route outside the front door's list is served the
app's HTML.

`docker/single-origin.Dockerfile` puts the backend, the app and nginx behind a
single port — the shape every one-click host can run. The backend's paths were
never designed to share an origin with the app's, so the split is a list of
prefixes rather than a rule, and a list goes stale: a new route under a new
prefix reaches the app instead, which answers 200 with a page. The caller sees a
successful request and nonsense in the body, and the cause is a file nobody
edited.

So the list is checked against the application's own route table.
"""

import os
import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
TEMPLATE = REPO / "docker" / "gateway" / "single-origin.conf.template"

BACKEND_UPSTREAM = "127.0.0.1:8000"
APP_UPSTREAM = "127.0.0.1:3000"

# Reachable on the loopback interface only, by deliberate omission.
NOT_PUBLISHED = {
    # The turn-scoped MCP endpoint a local CLI agent calls from inside this
    # container. It is a capability URL; there is no reason for the internet to
    # be able to reach it.
    "/local-agent-mcp",
    # FastAPI's own docs. Publishing the API surface of a self-hosted instance
    # to anonymous visitors is a choice its operator should make, not a default.
    "/docs",
    "/redoc",
    "/openapi.json",
    # Operator tooling: the execution-store admin views, the metrics endpoint
    # and the memory probe. Useful from inside the container, and an
    # unauthenticated window into every workflow's execution history from
    # outside it.
    "/admin",
    "/api/metrics",
    "/debug",
    # Legacy managed telemetry endpoint; absent from this edition.
    "/apps/perf-beacon",
}


def _locations() -> list[tuple[str, bool, str]]:
    """(path, is_exact, upstream) for each location, longest-prefix first —
    nginx's own resolution order, so the tests reason the way nginx does."""
    text = TEMPLATE.read_text()
    found = []
    for match in re.finditer(
        r"location\s+(=\s+)?(\S+)\s*\{(.*?)\n    \}", text, re.S
    ):
        exact = bool(match.group(1))
        path = match.group(2)
        upstream = re.search(r"proxy_pass\s+http://([^;/]+)", match.group(3))
        assert upstream, f"location {path} has no proxy_pass"
        found.append((path, exact, upstream.group(1)))
    # Exact matches first, then longest prefix — what nginx does.
    return sorted(found, key=lambda loc: (not loc[1], -len(loc[0])))


def _resolve(path: str) -> str:
    """Which upstream nginx would hand this path to."""
    for location, exact, upstream in _locations():
        if exact:
            if path == location:
                return upstream
        elif path.startswith(location):
            return upstream
    raise AssertionError(f"no location matched {path} — the catch-all is missing")


def _backend_paths() -> list[str]:
    os.environ.setdefault("POSTGRES_POOLER_URL", "postgres://unused/unused")
    for key, value in (
        ("PUBLIC_API_URL", "http://localhost:8000"),
        ("FRONTEND_URL", "http://localhost:3000"),
        ("MCP_BASE_URL", "http://localhost:8000"),
    ):
        os.environ.setdefault(key, value)
    import server
    from utils.route_inventory import route_paths

    # Not `app.routes`: since Starlette 1.6 an included router is one opaque
    # wrapper in that list, so the obvious expression reports four paths for an
    # application serving sixty-two — and this test passes without checking
    # anything.
    return sorted(route_paths(server.fastapi_app))


def test_template_exists_and_has_a_catch_all():
    locations = _locations()
    assert locations, "no locations parsed — has the template changed shape?"
    catch_all = [loc for loc in locations if loc[0] == "/" and not loc[1]]
    assert catch_all and catch_all[0][2] == APP_UPSTREAM, (
        "the app must be the catch-all; anything else means an unmatched path 404s"
    )


def test_every_backend_route_reaches_the_backend():
    unrouted = []
    for path in _backend_paths():
        if any(path.startswith(prefix) for prefix in NOT_PUBLISHED):
            continue
        # Path parameters never affect which prefix matches.
        concrete = path.split("{")[0] or "/"
        if _resolve(concrete) != BACKEND_UPSTREAM:
            unrouted.append(path)
    assert not unrouted, (
        "These backend routes would be served the app's HTML on a single-origin\n"
        "install, because nothing in docker/gateway/single-origin.conf.template\n"
        "claims them:\n  " + "\n  ".join(unrouted)
        + "\n\nAdd a location for the new prefix, or add it to NOT_PUBLISHED with\n"
        "a reason it should stay on the loopback interface."
    )


def test_deliberately_unpublished_routes_stay_that_way():
    """The omissions are the interesting half of the list: a location added for
    convenience would publish a capability URL or an API catalogue."""
    for prefix in NOT_PUBLISHED:
        assert _resolve(prefix) == APP_UPSTREAM, (
            f"{prefix} is now routed to the backend. It was left on the loopback\n"
            f"interface on purpose — see NOT_PUBLISHED."
        )


def test_the_consent_page_belongs_to_the_app():
    """The backend's /mcp/authorize redirects the browser to the consent page.
    Were both the same URL — as they were before the page moved to /mcp/consent
    — that redirect would point at itself."""
    assert _resolve("/mcp/consent") == APP_UPSTREAM
    assert _resolve("/mcp/authorize") == BACKEND_UPSTREAM
    assert "/mcp/consent" not in _backend_paths(), (
        "the backend has taken the consent path back; the redirect now loops"
    )


@pytest.mark.parametrize(
    "path,upstream",
    [
        ("/", APP_UPSTREAM),
        ("/dashboard", APP_UPSTREAM),
        ("/api/auth/google/callback", APP_UPSTREAM),
        ("/a/some-link-id", APP_UPSTREAM),
        ("/health", BACKEND_UPSTREAM),
        ("/socket.io/", BACKEND_UPSTREAM),
        ("/relay", BACKEND_UPSTREAM),
        ("/webhook/abc", BACKEND_UPSTREAM),
        ("/api/models", BACKEND_UPSTREAM),
        ("/api/public/instance-status", BACKEND_UPSTREAM),
        ("/.well-known/oauth-authorization-server", BACKEND_UPSTREAM),
    ],
)
def test_known_paths_go_where_they_should(path, upstream):
    """Both directions, because the app owns /api/auth while the backend owns
    four other things under /api — the one place the split is not by prefix."""
    assert _resolve(path) == upstream
