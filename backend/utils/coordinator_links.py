"""Low-latency delivery of committed human-link results.

This is optional acceleration: the resource transaction owns the durable result,
and the shared cloud/local recovery tick dispatches it if this process stops.
"""
from repositories.coordinator_links import CoordinatorLinkRepo
from utils.async_helpers import spawn


def dispatch_link(pool, kind, resource_id):
    spawn(CoordinatorLinkRepo(pool).dispatch(kind, resource_id), name=f"coordinator-link:{kind}:{resource_id}")
