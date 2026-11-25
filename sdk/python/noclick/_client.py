"""HTTP transport: auth, the user a call acts for, idempotency, retries and error mapping."""

from __future__ import annotations

import asyncio
import email.utils
import inspect
import os
import random
import threading
import time
import json as jsonlib
import uuid
import weakref
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, Literal, Optional, Tuple, Union
from urllib.parse import quote

import httpx

from ._scope import AMBIENT, USER_HEADER, resolve_scope, user_ref
from ._version import __version__
from .exceptions import APIConnectionError, Error, Unauthenticated, error_from_payload

# The hosted API; ``NOCLICK_API_URL`` (or ``base_url=``) points a client elsewhere.
DEFAULT_BASE_URL = "https://api.noclick.com"
API_KEY_ENV = "NOCLICK_API_KEY"
API_URL_ENV = "NOCLICK_API_URL"
# A deployed app's own credential, which NoClick puts in its environment (``Project.current()``).
DEPLOYMENT_TOKEN_ENV = "NOCLICK_DEPLOYMENT_TOKEN"
DEPLOYMENT_TOKEN_PREFIX = "nk_dep_"
# Where the hosted API's objects are shown (only for the hosted base URL).
CONSOLE_BASE_URL = "https://noclick.com/dashboard/developers"

# A key, or a function returning one (or an awaitable of one) for each attempt.
ApiKey = Union[str, Callable[[], Union[str, Awaitable[str]]]]

# 520-524: Cloudflare's own answers when it got none from the API (a write retried carries its Idempotency-Key).
_RETRY_STATUSES = frozenset({408, 429, 500, 502, 503, 504, 520, 521, 522, 523, 524})
_MAX_RETRY_AFTER_S = 60.0


def _environment_key() -> Optional[str]:
    """The key a client given none signs in with, the same rule in both SDKs: ``NOCLICK_API_KEY``, else a
    deployed app's own credential, ``NOCLICK_DEPLOYMENT_TOKEN`` (so the whole client acts as the app)."""
    return os.environ.get(API_KEY_ENV) or os.environ.get(DEPLOYMENT_TOKEN_ENV) or None


def _missing_credential(needed: Literal["key", "app"]) -> Unauthenticated:
    """The refusal for a call with no credential (``needed``: a key, or the app's own), naming the fix."""
    if needed == "app":
        return Unauthenticated(
            f"Project.current() runs inside a deployed app, where NoClick sets {DEPLOYMENT_TOKEN_ENV}.",
            next_step="Outside a deployment, use noclick.Project.from_name(...) with your own key.",
        )
    return Unauthenticated(
        "No NoClick API key is configured.",
        next_step=f"Set {API_KEY_ENV} or pass noclick.Client(api_key=...). A deployed app needs neither: the client "
                  f"signs in with the credential NoClick puts in its environment, {DEPLOYMENT_TOKEN_ENV}.",
    )


class Client:
    """Connection settings for the platform API.

    Most code never builds one: the module-level default reads
    ``NOCLICK_API_KEY`` and ``NOCLICK_API_URL`` (inside a deployed app without
    a key, its deployment's own credential, ``NOCLICK_DEPLOYMENT_TOKEN``). Pass
    ``client=`` to any constructor or classmethod to use another account or
    endpoint.
    ``api_key`` may be a function (sync or async) returning the bearer; it is
    called on every attempt, so a refreshing token stays current.

    Usage:
        Use a second account by passing its client as ``client=``::

            other = noclick.Client(api_key="nk_live_other")
            users = noclick.User.list(client=other)

        Tune retries and timeouts, and close the connections when the block ends::

            with noclick.Client(api_key="nk_live_other", timeout=30, max_retries=5) as other:
                print(noclick.User.list(client=other, limit=10))

        When your key comes from a secret store that rotates it, pass the function that reads it::

            client = noclick.Client(api_key=read_noclick_key)   # called before every attempt
    """

    # The key and your headers sit in slots, outside ``vars(client)``; ``repr`` shows only ``base_url``.
    __slots__ = ("_key", "_extra_headers", "__dict__", "__weakref__")

    def __init__(
        self,
        api_key: Optional[ApiKey] = None,
        base_url: Optional[str] = None,
        *,
        timeout: float = 60.0,
        max_retries: int = 3,
        backoff: float = 0.5,
        max_backoff: float = 8.0,
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        self._key = api_key if api_key is not None else _environment_key()
        self.base_url = (base_url or os.environ.get(API_URL_ENV) or DEFAULT_BASE_URL).rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff = backoff
        self.max_backoff = max_backoff
        self._extra_headers = dict(headers or {})
        # httpx pools are bound to the loop that opened them: one per loop.
        self._http_by_loop: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, httpx.AsyncClient]" = (
            weakref.WeakKeyDictionary()
        )
        self._sleep = asyncio.sleep

    def __repr__(self) -> str:
        return f"noclick.Client(base_url={self.base_url!r})"

    @property
    def api_key(self) -> Optional[ApiKey]:
        return self._key

    @api_key.setter
    def api_key(self, value: Optional[ApiKey]) -> None:
        self._key = value

    @property
    def in_app(self) -> bool:
        """Whether this client signs in as a deployed app's own code (its deployment's credential), where
        ``from_name`` resolves names in the app's own namespace for the environment it runs in."""
        return isinstance(self.api_key, str) and self.api_key.startswith(DEPLOYMENT_TOKEN_PREFIX)

    @classmethod
    def for_session(cls, session: Any, *, base_url: Optional[str] = None, **kwargs: Any) -> "Client":
        """Build a client that authenticates with a user session (a ``noclick.Session``
        or its ``nk_sess_...`` token). Every call acts for the session's user
        with the session's scopes; the same as ``noclick.Client(api_key=token)``.

        Returns:
            A client for that session, on the session's own API endpoint unless you pass ``base_url``.

        Usage::

            user = noclick.User.from_id("user_42")
            session = user.session(["agents"], ttl_s=3600)
            as_ana = noclick.Client.for_session(session)
            agents = noclick.Agent.list(client=as_ana)   # Ana's agents and the shared ones, nothing else
        """
        from .session import SESSION_TOKEN_PREFIX, Session

        token = session.token if isinstance(session, Session) else session
        if not isinstance(token, str) or not token.startswith(SESSION_TOKEN_PREFIX):
            raise ValueError(
                f"Client.for_session() takes an noclick.Session or a {SESSION_TOKEN_PREFIX}... token; "
                "use noclick.Client(api_key=...) for a secret key."
            )
        if base_url is None and isinstance(session, Session):
            base_url = session.base_url
        return cls(api_key=token, base_url=base_url, **kwargs)

    def _http(self) -> httpx.AsyncClient:
        loop = asyncio.get_running_loop()
        http = self._http_by_loop.get(loop)
        if http is None or http.is_closed:
            http = httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout)
            self._http_by_loop[loop] = http
        return http

    async def aclose(self) -> None:
        """Close the connection pool opened on the current event loop.

        Usage:
            In a long-lived async app, close the client when you shut down::

                await noclick.default_client().aclose()
        """
        http = self._http_by_loop.pop(asyncio.get_running_loop(), None)
        if http is not None:
            await http.aclose()

    def close(self) -> None:
        """Close the pool the blocking API uses.

        Usage::

            client = noclick.Client(api_key="nk_live_other")
            users = noclick.User.list(client=client, limit=10)
            client.close()
        """
        from ._sync import run_sync

        run_sync(self.aclose())

    async def __aenter__(self) -> "Client":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    def __enter__(self) -> "Client":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        content: Optional[bytes] = None,
        params: Optional[Dict[str, Any]] = None,
        user: Any = AMBIENT,
        idempotency_key: Optional[str] = None,
        timeout: Optional[float] = None,
        binary: bool = False,
        content_type: Optional[str] = None,
        anonymous: bool = False,
    ) -> Any:
        """Send one API call. ``content`` sends raw bytes instead of JSON (as ``content_type``, else
        ``application/octet-stream``); ``anonymous`` sends no key, for the calls made before there is one.

        Writes carry an ``Idempotency-Key`` (generated unless given) that is
        reused on every retry, so a retried POST can't do the work twice.

        Returns:
            The response's decoded JSON (``None`` for an empty body), or its raw bytes with ``binary=True``.
            An error response raises its ``noclick.Error`` instead.

        Usage:
            Call an endpoint directly, with the client's key, retries and errors. It is async only::

                client = noclick.default_client()
                page = await client.request("GET", "/v1/users", params={"limit": 5}, user=None)
                print([row["id"] for row in page["data"]])

            Pass your own ``idempotency_key`` to make a write safe to repeat across processes::

                client = noclick.default_client()
                user = await client.request(
                    "POST", "/v1/users", json={"id": "user_42"}, user=None, idempotency_key="signup-user_42",
                )
        """
        if not self.api_key and not anonymous:
            raise _missing_credential("key")
        method = method.upper()
        scope = resolve_scope(user)
        headers = await self._headers(method, "*/*" if binary else "application/json", scope, idempotency_key)
        if content is not None:
            headers["Content-Type"] = content_type or "application/octet-stream"
        if params:
            params = {k: v for k, v in params.items() if v is not None}

        timeout = timeout if timeout is not None else self.timeout
        attempt = 0
        try:
            while True:
                authorization = {} if anonymous else {"Authorization": f"Bearer {await self._bearer(timeout)}"}
                try:
                    response = await self._http().request(
                        method, path, json=json, content=content, params=params or None,
                        headers={**authorization, **headers}, timeout=timeout,
                    )
                except httpx.TransportError as exc:
                    if attempt >= self.max_retries:
                        raise APIConnectionError(
                            f"Could not reach the NoClick API at {self.base_url}: {exc.__class__.__name__}: {exc}",
                            next_step="Check your network and NOCLICK_API_URL, then retry.", attempts=attempt + 1,
                        ) from _frameless(exc)
                    await self._sleep(self._backoff_delay(attempt, None))
                    attempt += 1
                    continue

                if _retryable(method, response) and attempt < self.max_retries:
                    await self._sleep(self._backoff_delay(attempt, response))
                    attempt += 1
                    continue
                try:
                    return self._decode(response, binary=binary)
                except Error as err:
                    err._origin = (self, scope)  # lets an error's follow-up calls (e.g. an approval) use this client
                    err.attempts = attempt + 1
                    raise
        finally:
            # A traceback that shows locals (Sentry, pytest -l) prints this frame's: never the key or your headers.
            headers = authorization = None

    async def _headers(self, method: str, accept: str, scope: Any, idempotency_key: Optional[str]) -> Dict[str, str]:
        user_value = await user_ref(scope)  # first: a failure here mustn't show your headers among the frame's locals
        headers = {"Accept": accept, "User-Agent": f"noclick-python/{__version__}", **self._extra_headers}
        if user_value:
            headers[USER_HEADER] = user_value
        if method != "GET":
            headers["Idempotency-Key"] = idempotency_key or f"nc_{uuid.uuid4().hex}"
        return headers

    async def _events(
        self, method: str, path: str, *, json: Any = None, params: Optional[Dict[str, Any]] = None, user: Any = AMBIENT,
    ) -> AsyncIterator[Tuple[str, Dict[str, Any]]]:
        """``(event, data)`` from a server-sent-events response as each arrives; an
        ``error`` event (or data carrying an ``error``, OpenAI's way) raises its
        ``noclick.Error``, and ``data: [DONE]`` ends it. A stream refused before it
        starts is retried like a request; one that breaks raises
        ``APIConnectionError``. (The server sends a comment every 15 seconds, so
        the read timeout only trips on a dead stream.)"""
        if not self.api_key:
            raise _missing_credential("key")
        method = method.upper()
        headers = await self._headers(method, "text/event-stream", resolve_scope(user), None)
        attempt = 0
        try:
            while True:
                async with self._http().stream(
                    method, path, json=json, params=params,
                    headers={**headers, "Authorization": f"Bearer {await self._bearer(self.timeout)}"},
                ) as response:
                    if not response.is_success:
                        await response.aread()
                        if not (_retryable(method, response) and attempt < self.max_retries):
                            try:
                                self._decode(response)  # raises the response's error
                            except Error as err:
                                err.attempts = attempt + 1
                                raise
                        delay = self._backoff_delay(attempt, response)
                    else:
                        async for event in _sse(response):
                            yield event
                        return
                await self._sleep(delay)
                attempt += 1
        except httpx.TransportError as exc:
            raise APIConnectionError(
                f"The stream from the NoClick API broke: {exc.__class__.__name__}: {exc}",
                next_step="The work may still finish: read its result, or stream again.",
            ) from _frameless(exc)
        finally:
            headers = None  # as in ``request``

    async def _bearer(self, timeout: float) -> str:
        """The bearer for one attempt (a provider is asked each time, and given up on after ``timeout``)."""
        key = self.api_key() if callable(self.api_key) else self.api_key
        if inspect.isawaitable(key):
            try:
                key = await asyncio.wait_for(key, timeout)
            except asyncio.TimeoutError:
                raise Unauthenticated(
                    f"The NoClick API key provider did not return a key within {timeout:g}s.",
                    next_step="Make the api_key function return (or raise) promptly.",
                ) from None
        if not key:
            raise Unauthenticated(
                "The NoClick API key provider returned no key.",
                next_step="Return a key or token from the api_key function.",
            )
        return key

    def console_url(self, section: str, object_id: str) -> Optional[str]:
        """Link an object (in ``operations``, ``agents`` or ``users``) to its
        developer console page.

        Returns:
            The page's URL, or ``None`` when this client doesn't talk to the hosted API.

        Usage:
            Operations, agents and users have a ``console_url`` of their own. Build one from an id you stored::

                url = noclick.default_client().console_url("operations", "3b9e0f6a-1c2d-4e5f-8a9b-0c1d2e3f4a5b")
        """
        if self.base_url != DEFAULT_BASE_URL:
            return None
        ref = path_segment(str(object_id))
        if section == "operations":
            return f"{CONSOLE_BASE_URL}/operations?op={ref}"
        return f"{CONSOLE_BASE_URL}/{section}/{ref}"

    def _backoff_delay(self, attempt: int, response: Optional[httpx.Response]) -> float:
        retry_after = _retry_after_seconds(response) if response is not None else None
        if retry_after is not None:
            return min(retry_after, _MAX_RETRY_AFTER_S)
        delay = min(self.max_backoff, self.backoff * (2**attempt))
        return delay * (0.5 + random.random() / 2)

    @staticmethod
    def _decode(response: httpx.Response, *, binary: bool = False) -> Any:
        # Cloudflare's ray names a request the API never answered (its own 52x); NoClick support finds either.
        edge_id = response.headers.get("cf-ray")
        request_id = response.headers.get("x-request-id") or edge_id
        if binary and response.is_success:
            return response.content
        try:
            body = response.json() if response.content else None
        except ValueError:
            body = None
        if response.is_success:
            return body
        payload = body if isinstance(body, dict) and isinstance(body.get("error"), dict) else {
            "message": f"HTTP {response.status_code} from {response.request.method} {response.request.url.path}"
            + (f" (request {request_id})" if request_id else "")
            + (f": {response.text[:300]}" if response.text and body is None else ""),
        }
        err = error_from_payload(payload, status=response.status_code, request_id=request_id)
        if edge_id:
            err.details.setdefault("cf_ray", edge_id)
        retry_after = _retry_after_seconds(response)
        if retry_after is not None:
            err.details.setdefault("retry_after", retry_after)
        raise err


async def _sse(response: httpx.Response) -> AsyncIterator[Tuple[str, Dict[str, Any]]]:
    event, data = "message", []
    async for line in response.aiter_lines():
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].lstrip())
        elif not line and data:
            if data == ["[DONE]"]:
                return
            payload = jsonlib.loads("\n".join(data))
            if event == "error" or (isinstance(payload, dict) and isinstance(payload.get("error"), dict)):
                raise error_from_payload(payload, request_id=response.headers.get("x-request-id"))
            yield event, payload
            event, data = "message", []
        elif not line:
            event = "message"


def _frameless(exc: BaseException) -> BaseException:
    """``exc`` and the errors behind it, without their tracebacks: httpx's frames hold the request's
    headers, which a traceback that shows locals would print."""
    seen, pending = set(), [exc]
    while pending:
        link = pending.pop()
        if link is not None and id(link) not in seen:
            seen.add(id(link))
            link.__traceback__ = None
            pending += [link.__cause__, link.__context__]
    return exc


def _retryable(method: str, response: httpx.Response) -> bool:
    if response.status_code not in _RETRY_STATUSES:
        return False
    if response.status_code == 500 and method == "POST":  # replayed for the same Idempotency-Key
        return False
    # A replayed answer is the first one, every time: the server kept it because the work may have happened.
    if response.headers.get("idempotent-replayed") == "true":
        return False
    try:
        error = response.json().get("error") or {}
        # OpenAI-shaped errors (/v1/ai) carry the type in ``code``.
        kind = error.get("code") or error.get("type")
    except (ValueError, AttributeError):
        return True
    # A spent quota won't come back in seconds; a timeout's work may still be going on.
    return kind not in ("quota_exceeded", "request_timeout")


def _retry_after_seconds(response: httpx.Response) -> Optional[float]:
    value = response.headers.get("retry-after")
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, when.timestamp() - time.time())


_default_lock = threading.Lock()
_default: Optional[Client] = None


def default_client() -> Client:
    """Get the client used when no ``client=`` is given, built from the environment on first use.

    Returns:
        The shared default client: the one ``configure`` last set, else one built from ``NOCLICK_API_KEY``
        and ``NOCLICK_API_URL`` (inside a deployed app without a key, signed in as the app with
        ``NOCLICK_DEPLOYMENT_TOKEN``).

    Usage::

        client = noclick.default_client()
        print(client.base_url)   # https://api.noclick.com unless NOCLICK_API_URL says otherwise
    """
    global _default
    with _default_lock:
        if _default is None:
            _default = Client()
        return _default


def configure(api_key: Optional[ApiKey] = None, base_url: Optional[str] = None, **kwargs: Any) -> Client:
    """Replace the default client, e.g. ``noclick.configure(api_key="nk_live_...")``.

    Returns:
        The new default client, which every call without ``client=`` now uses.

    Usage::

        noclick.configure(api_key="nk_live_...", timeout=30, max_retries=5)
        users = noclick.User.list(limit=10)   # uses the new default
    """
    global _default
    client = Client(api_key=api_key, base_url=base_url, **kwargs)
    with _default_lock:
        _default = client
    return client


def resolve_client(client: Optional[Client]) -> Client:
    return client if client is not None else default_client()


def app_client() -> Client:
    """The client a deployed app's own code acts with (``Project.current()``): the default one when it signs
    in as the app (no ``NOCLICK_API_KEY`` beside the deployment's credential), else one with that credential."""
    client = default_client()
    if client.in_app:
        return client
    token = os.environ.get(DEPLOYMENT_TOKEN_ENV)
    if not token:
        raise _missing_credential("app")
    return Client(api_key=token)


def path_segment(value: str) -> str:
    """``value`` percent-encoded as one URL path segment."""
    return quote(value, safe="")
