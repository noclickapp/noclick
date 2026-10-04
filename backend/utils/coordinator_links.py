"""Low-latency delivery of committed human-link results.

This is optional acceleration: the resource transaction owns the durable result,
and the shared cloud/local recovery tick dispatches it if this process stops.
"""
from repositories.coordinator_links import CoordinatorLinkRepo
from utils.async_helpers import spawn

# Extra consumers of committed link results: ``listener(pool, kind, resource_id)``.
_listeners = []


def on_link_result(listener):
    if listener not in _listeners:
        _listeners.append(listener)


def dispatch_link(pool, kind, resource_id):
    spawn(CoordinatorLinkRepo(pool).dispatch(kind, resource_id), name=f"coordinator-link:{kind}:{resource_id}")
    for listener in _listeners:
        spawn(listener(pool, kind, resource_id), name=f"link-listener:{kind}:{resource_id}")
