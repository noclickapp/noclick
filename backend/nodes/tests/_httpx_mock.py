"""A minimal ``respx``-compatible httpx mock built on httpx's own
``MockTransport``, so the HTTP node tests don't depend on the external ``respx``
package (which isn't installed in CI — node tests only get pytest +
pytest-asyncio + pytest-timeout).

Only the slice of the respx API the tests use is implemented:
``respx.mock`` (decorator and context manager), ``respx.get/post/put/patch/
delete(url).mock(return_value=/side_effect=)``, and ``route.calls.last.request``
/ ``route.call_count``. Requests are matched by method + URL path (query string
ignored), mirroring respx's default behavior.
"""

import functools
import inspect

import httpx
from unittest.mock import patch as _mock_patch

_active = None  # the router for the currently-active respx.mock scope


class _Call:
    def __init__(self, request: httpx.Request):
        self.request = request


class _CallList(list):
    @property
    def last(self) -> "_Call":
        return self[-1]


class _Route:
    def __init__(self):
        self._return = None
        self._side_effect = None
        self.calls = _CallList()

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def mock(self, return_value=None, side_effect=None) -> "_Route":
        self._return = return_value
        self._side_effect = side_effect
        return self

    def _resolve(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(_Call(request))
        se = self._side_effect
        if se is not None:
            item = se[min(len(self.calls) - 1, len(se) - 1)] if isinstance(se, list) else se
            if isinstance(item, BaseException):
                raise item
            if isinstance(item, type) and issubclass(item, BaseException):
                raise item("mocked error")
            if isinstance(item, httpx.Response):
                return item
        if isinstance(self._return, httpx.Response):
            return self._return
        raise AssertionError("respx route has no mocked response/side_effect")


class _Router:
    def __init__(self):
        self._routes = {}

    def route(self, method: str, url: str) -> _Route:
        route = _Route()
        self._routes[(method, url)] = route
        return route

    def handler(self, request: httpx.Request) -> httpx.Response:
        base = str(request.url).split("?", 1)[0]
        route = self._routes.get((request.method, base))
        if route is None:
            raise httpx.ConnectError(f"No mock route for {request.method} {base}")
        return route._resolve(request)


class _Mock:
    """Usable as ``with respx.mock:`` and ``@respx.mock``."""

    def __enter__(self) -> "_Mock":
        global _active
        _active = _Router()
        real_client = httpx.AsyncClient

        def make(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(_active.handler)
            return real_client(*args, **kwargs)

        self._patcher = _mock_patch("httpx.AsyncClient", side_effect=make)
        self._patcher.start()
        return self

    def __exit__(self, *exc) -> bool:
        global _active
        self._patcher.stop()
        _active = None
        return False

    def __call__(self, fn):
        if inspect.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def awrapper(*a, **k):
                with _Mock():
                    return await fn(*a, **k)

            return awrapper

        @functools.wraps(fn)
        def wrapper(*a, **k):
            with _Mock():
                return fn(*a, **k)

        return wrapper


mock = _Mock()


def _route(method: str, url: str) -> _Route:
    if _active is None:
        raise RuntimeError("respx route registered outside an active respx.mock scope")
    return _active.route(method, url)


def get(url: str) -> _Route:
    return _route("GET", url)


def post(url: str) -> _Route:
    return _route("POST", url)


def put(url: str) -> _Route:
    return _route("PUT", url)


def patch(url: str) -> _Route:
    return _route("PATCH", url)


def delete(url: str) -> _Route:
    return _route("DELETE", url)
