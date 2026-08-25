"""Every path an app actually serves.

`app.routes` stopped being that answer in Starlette 1.6 / FastAPI 0.141:
`include_router` no longer flattens the router's routes into the app, it appends
one `_IncludedRouter` wrapper that exposes neither `.path` nor `.routes`. So the
familiar

    {r.path for r in app.routes if hasattr(r, "path")}

now returns four paths for an application serving a hundred — the FastAPI
defaults, and nothing else. It does not raise. It reports a smaller world.

That silence already cost us twice: the OpenTelemetry FastAPI instrumentation
read `.path` off those wrappers and 500'd every request until it was upgraded,
and `test_single_origin_routing` — which exists to catch a backend route the
nginx front door does not claim — quietly went from checking every route to
checking four.
"""

from __future__ import annotations

from typing import Any, Iterator, Set


def iter_route_paths(app_or_routes: Any, prefix: str = "") -> Iterator[str]:
    """Yield the full path of every route, descending through included routers."""
    routes = getattr(app_or_routes, "routes", app_or_routes)
    for route in routes:
        path = getattr(route, "path", None)
        if path is not None:
            yield prefix + path
            continue
        # Starlette >= 1.6: an included router, carrying its own prefix.
        included = getattr(route, "original_router", None)
        if included is not None:
            context = getattr(route, "include_context", None)
            yield from iter_route_paths(
                included.routes, prefix + (getattr(context, "prefix", "") or "")
            )


def route_paths(app_or_routes: Any) -> Set[str]:
    return set(iter_route_paths(app_or_routes))
