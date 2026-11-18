"""The user a call acts for.

``with noclick.as_user(user):`` sets it for everything inside, sync or async:
``.aio`` calls, tasks and ``asyncio.to_thread``. A thread you start yourself
begins without it (a ``contextvars`` rule), so pass ``user=`` there. A
method's ``user=`` argument wins over it.
"""

from __future__ import annotations

import contextvars
from typing import Any, Optional

from .exceptions import InvalidRequest

USER_HEADER = "NoClick-User"
# Values for a read's ``user_filter``: every user plus account-level rows, or account-level only.
ALL_USERS = "all"
NO_USER = "none"
MAX_USER_ID_LENGTH = 255


class _Ambient:
    """Sentinel: use the user from ``as_user`` (if any)."""

    def __repr__(self) -> str:
        return "AMBIENT"


AMBIENT: Any = _Ambient()

_current: contextvars.ContextVar[Any] = contextvars.ContextVar("noclick_user", default=None)


def check_user_id(value: Any) -> str:
    """``value`` when it's a valid user id: 1 to 255 printable ASCII characters (no spaces), no ``/``,
    and not ``all``, ``none``, ``.`` or ``..``. Anything else raises ``InvalidRequest`` naming the rule it breaks."""
    if not isinstance(value, str):
        raise TypeError(f"A user id is a string, not {type(value).__name__}")
    bad = next((ch for ch in value if not "!" <= ch <= "~"), None)  # outside 0x21-0x7E
    if not 1 <= len(value) <= MAX_USER_ID_LENGTH:
        rule = f"A user id is 1 to {MAX_USER_ID_LENGTH} characters; this one has {len(value)}."
    elif bad is not None:
        rule = f"A user id is printable ASCII with no spaces; {value!r} has {bad!r}."
    elif "/" in value:
        rule = f"A user id can't contain '/': {value!r}."
    elif value in (ALL_USERS, NO_USER):
        rule = f"{value!r} is reserved for user_filter, so it can't be a user id."
    elif value in (".", ".."):
        rule = f"{value!r} can't be a user id: URLs resolve it away."
    else:
        return value
    raise InvalidRequest(
        rule,
        next_step="Use your own id for the user: 1 to 255 printable ASCII characters without spaces or '/', "
                  "other than 'all', 'none', '.' and '..'.",
        details={"field": "id"},
    )


def current_user() -> Any:
    """The user set by the innermost ``as_user`` (a ``User``, an id, or None).

    Returns:
        What the innermost ``as_user`` was given, as given (nothing is looked up), or ``None``
        outside every ``as_user`` block, where calls act for your account.

    Usage::

        with noclick.as_user("user_42"):
            print(noclick.current_user())   # user_42
        print(noclick.current_user())       # None
    """
    return _current.get()


class as_user:
    """Act for ``user`` inside the block: a ``User``, your id for the user, or None
    for the account itself. Any string is your id; a user id that breaks the id
    rules raises ``InvalidRequest`` here.

    Usage:
        Every call inside the block acts for the user: here, Ana's own Gmail and agent::

            with noclick.as_user("user_42"):
                gmail = noclick.Connection.from_name("gmail", integration="gmail", create_if_missing=True)
                assistant = noclick.Agent.from_name(
                    "assistant", create_if_missing=True, instructions="You help the user with their email.", tools=[gmail],
                )

        It works the same with ``async with``, and follows your code into tasks and
        ``asyncio.to_thread``::

            async with noclick.as_user(noclick.User.from_id("user_42")):
                agents = await noclick.Agent.list.aio()

        Your ids can take any shape, a UUID or an identity provider's subject::

            with noclick.as_user("auth0|6f1c2b7e9a"):
                connections = noclick.Connection.list()
    """

    def __init__(self, user: Any) -> None:
        if user is not None and not isinstance(user, str) and not hasattr(user, "_user_ref"):
            raise TypeError(f"as_user() takes a User or your id for the user, not {type(user).__name__}")
        if isinstance(user, str):
            check_user_id(user)
        self._user = user
        self._tokens: list = []

    def __enter__(self) -> Any:
        self._tokens.append(_current.set(self._user))
        return self._user

    def __exit__(self, *exc: Any) -> None:
        _current.reset(self._tokens.pop())

    async def __aenter__(self) -> Any:
        return self.__enter__()

    async def __aexit__(self, *exc: Any) -> None:
        self.__exit__(*exc)


def resolve_scope(user: Any) -> Any:
    """Turn a ``user=`` argument into what a call should carry: an explicit
    value, or the ambient user when the argument was omitted."""
    return current_user() if user is AMBIENT else user


async def user_ref(user: Any) -> Optional[str]:
    """Your id for the user a ``User`` or an id names (``None`` stays ``None``): the
    ``NoClick-User`` header value, and the ``user_id`` a body or filter carries."""
    if user is None:
        return None
    if isinstance(user, str):
        return check_user_id(user)
    if hasattr(user, "_user_ref"):
        return await user._user_ref()
    raise TypeError(f"user= takes a User or your id for the user, not {type(user).__name__}")


async def user_filter_param(user_filter: Any) -> str:
    """The ``user_id`` query value for a read's ``user_filter``: ``ALL_USERS``,
    ``NO_USER``, a ``User`` or your id for one. Sent as a query parameter, never
    as the header, so it filters without acting as the user."""
    if user_filter in (ALL_USERS, NO_USER):
        return user_filter
    if isinstance(user_filter, str) or hasattr(user_filter, "_user_ref"):
        return await user_ref(user_filter)
    raise TypeError(
        f"user_filter takes 'all', 'none', a User or your id for the user, not {type(user_filter).__name__}"
    )
