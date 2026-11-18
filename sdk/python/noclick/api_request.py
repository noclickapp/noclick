"""The API request log: every write and every failed request made with your
keys and sessions (successful reads aren't logged), newest first.

    page = noclick.ApiRequest.list_page(method="POST", status="4xx", key="nk_live_ab12")
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Any, Dict, List, Optional, Union

from ._client import Client
from ._object import Page, iso_time, list_all, list_page, parse_time
from ._sync import synced
from ._scope import AMBIENT

_PATH = "/v1/requests"


def _params(method: Optional[str], status: Union[None, str, int], error_type: Optional[str], key: Optional[str],
            route: Optional[str], since: Any, until: Any) -> Dict[str, Any]:
    return {
        "method": method, "status": status, "error_type": error_type, "key_id": key, "route": route,
        "since": iso_time(since), "until": iso_time(until),
    }


@dataclass(frozen=True)
class ApiRequest:
    """One logged request. ``actor`` is ``key``, ``session`` or ``owner``;
    ``route`` is the template (``/v1/agents/{agent_id}/messages``)."""

    id: str
    actor: Optional[str]
    key_id: Optional[str]
    user_id: Optional[str]
    session_id: Optional[str]
    method: str
    route: str
    path_params: Dict[str, Any]
    status: Optional[int]
    error_type: Optional[str]
    duration_ms: Optional[int]
    idempotency_replayed: bool
    operation_id: Optional[str]
    request_id: Optional[str]
    created_at: Any
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any], _scope: Any = None) -> "ApiRequest":
        return cls(
            id=raw.get("id"), actor=raw.get("actor"), key_id=raw.get("key_id"), user_id=raw.get("user_id"),
            session_id=raw.get("session_id"), method=raw.get("method") or "", route=raw.get("route") or "",
            path_params=dict(raw.get("path_params") or {}), status=raw.get("status"),
            error_type=raw.get("error_type"), duration_ms=raw.get("duration_ms"),
            idempotency_replayed=raw.get("idempotency_replayed") is True, operation_id=raw.get("operation_id"),
            request_id=raw.get("request_id"), created_at=parse_time(raw.get("created_at")), raw=raw,
        )

    @synced
    @classmethod
    async def list(
        cls, *, method: Optional[str] = None, status: Union[None, str, int] = None, error_type: Optional[str] = None,
        key: Optional[str] = None, route: Optional[str] = None, since: Any = None, until: Any = None,
        limit: Optional[int] = None, user_filter: Any = None, user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> List["ApiRequest"]:
        """Every matching request (or the first ``limit``). ``status`` is a class
        (``"4xx"``) or a code; ``key`` a key id or prefix.

        Returns:
            Every matching request, newest first, fetched page by page.

        Usage:
            See the writes one key had refused::

                for request in noclick.ApiRequest.list(method="POST", status="4xx", key="nk_live_ab12", limit=50):
                    print(request.created_at, request.route, request.status, request.error_type)

            Or every request a spend cap turned away::

                capped = noclick.ApiRequest.list(error_type="spend_cap_exceeded", limit=20)

            ``route`` takes the template, and ``status`` a single code::

                limited = noclick.ApiRequest.list(route="/v1/agents/{agent_id}/messages", status=429)
        """
        return await list_all(
            _PATH, cls._from, params=_params(method, status, error_type, key, route, since, until),
            user=user, user_filter=user_filter, limit=limit, client=client,
        )

    @synced
    @classmethod
    async def list_page(
        cls, *, cursor: Optional[str] = None, limit: Optional[int] = None, method: Optional[str] = None,
        status: Union[None, str, int] = None, error_type: Optional[str] = None, key: Optional[str] = None,
        route: Optional[str] = None, since: Any = None, until: Any = None, user_filter: Any = None,
        user: Any = AMBIENT, client: Optional[Client] = None,
    ) -> Page:
        """One page of matching requests; pass ``next_cursor`` back as ``cursor``.

        Returns:
            A page whose ``data`` holds up to ``limit`` requests (at most 200) and whose ``next_cursor``
            is ``None`` on the last page.

        Usage::

            page = noclick.ApiRequest.list_page(status="5xx", limit=200)
            while True:
                for request in page.data:
                    print(request.request_id, request.route, request.status)
                if page.next_cursor is None:
                    break
                page = noclick.ApiRequest.list_page(status="5xx", limit=200, cursor=page.next_cursor)
        """
        return await list_page(
            _PATH, cls._from, params=_params(method, status, error_type, key, route, since, until),
            user=user, user_filter=user_filter, cursor=cursor, limit=limit, client=client,
        )
