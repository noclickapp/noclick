"""A connect link's OAuth sign-in is the app's own. The provider's exchange handler
(``wss/handlers/oauth/<provider>_oauth_handler.py``) runs with the inputs the
link's connect form sent, exactly as it runs for a signed-in person, so the
credential a link stores has the fields, name and metadata the in-app connect
gives it (an account's id, a site, a workspace's bot token). Only two things
differ: the credential is stored where the link says (``SIGN_IN_STORE``, set
for the call), and the handler's answer comes back here instead of to a socket.
"""

from __future__ import annotations

import importlib
import inspect
from functools import lru_cache
from typing import Any, Dict, Optional, Tuple, Type

from pydantic import BaseModel, ValidationError

from repositories.credentials import SIGN_IN_STORE, SignInStore
from wss.sender.events import ResponseEvent

_SID = "connect-link"
# What a link's connect form sends beside its inputs; the request fills these itself.
_FILLED = ("request_id",)


class SignInFailed(Exception):
    """The sign-in didn't finish: the provider refused the code, an input was missing or wrong (``field``)."""

    def __init__(self, message: str, *, field: Optional[str] = None):
        super().__init__(message)
        self.field = field


class _Socket:
    """What the handler talks to: one session, as the person the link stores for, and its answer kept."""

    def __init__(self, user_id: str, tier: str):
        self._session = {"user_id": user_id, "user_data": {"subscription_tier": tier}}
        self.answer: Optional[Dict[str, Any]] = None

    async def get_session(self, sid: str) -> Dict[str, Any]:
        return self._session

    async def emit(self, event: str, data: Any = None, **_: Any) -> None:
        if event == ResponseEvent.event_name:
            self.answer = data


@lru_cache(maxsize=None)
def exchange_request(provider: str) -> Type[BaseModel]:
    """The provider's exchange event: what its sign-in takes, as the app's connect form sends it."""
    from wss.receiver import client_events

    name = f"{provider}:oauth:exchange"
    for model in vars(client_events).values():
        if inspect.isclass(model) and issubclass(model, BaseModel) and getattr(model, "event_name", None) == name:
            return model
    raise LookupError(f"No {name} event")


def _handler(provider: str, socket: _Socket):
    """The provider's own exchange handler, answering on ``socket``."""
    from wss.schema import SocketIOHandler

    module = importlib.import_module(f"wss.handlers.oauth.{provider}_oauth_handler")
    name = f"{provider}:oauth:exchange"
    for cls in vars(module).values():
        if inspect.isclass(cls) and issubclass(cls, SocketIOHandler) and cls.__module__ == module.__name__:
            events = cls(socket).get_events()
            if name in events:
                return events[name]
    raise LookupError(f"No handler for {name}")


def client_fields(provider: str, client: Dict[str, str]) -> Optional[Dict[str, str]]:
    """The exchange request's fields naming ``client`` (an OAuth app of the requester's), or None when the
    provider's sign-in can't run on one."""
    from nodes.core.oauth_refresh import CLIENT_PARAMS

    fields = exchange_request(provider).model_fields
    for id_key, secret_key in CLIENT_PARAMS:
        if id_key in fields and secret_key in fields:
            return {id_key: client["client_id"], secret_key: client["client_secret"]}
    return None


async def sign_in(provider: str, inputs: Dict[str, Any], *, user_id: str, tier: str,
                  store: SignInStore) -> Tuple[str, Dict[str, Any]]:
    """Run ``provider``'s sign-in for ``user_id`` on ``inputs`` (the code, redirect URI, scopes and the connect form's
    own inputs); its credential goes to ``store``. Returns the credential's id and the handler's answer."""
    model = exchange_request(provider)
    try:
        request = model.model_validate({**{k: v for k, v in inputs.items() if k in model.model_fields
                                            and k not in _FILLED}, "request_id": _SID})
    except ValidationError as exc:
        error = exc.errors()[0]
        field = ".".join(str(part) for part in error["loc"]) or None
        raise SignInFailed(f"{field}: {error['msg']}" if field else error["msg"], field=field) from None
    socket = _Socket(user_id, tier)
    token = SIGN_IN_STORE.set(store)
    try:
        await _handler(provider, socket)(_SID, request)
    finally:
        SIGN_IN_STORE.reset(token)
    answer = socket.answer or {}
    data = answer.get("data") if isinstance(answer.get("data"), dict) else {}
    if answer.get("error") or not data.get("success") or not data.get("credential_id"):
        raise SignInFailed(answer.get("error") or data.get("message") or "The sign-in didn't finish.")
    return str(data["credential_id"]), data
