"""Errors: every refusal the API makes, as a typed class that says what to do next.

The server renders every refusal as ``{"error": {"type", "message",
"next_step", ...details}}``; ``type`` picks the class here (the same names
and HTTP statuses the API uses). Extra keys land in ``details`` and read as
attributes: ``err.connect_url``, ``err.existing_id``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Type

if TYPE_CHECKING:
    from .operation import Operation


class Error(Exception):
    """Base class for every NoClick platform error."""

    type: str = "error"
    http_status: Optional[int] = None
    # (client, user scope) of the call that raised it; follow-up calls use them.
    _origin: tuple = (None, None)

    def __init__(
        self,
        message: str = "",
        *,
        next_step: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        status: Optional[int] = None,
        request_id: Optional[str] = None,
        attempts: Optional[int] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.next_step = next_step
        self.details: Dict[str, Any] = dict(details or {})
        self.status = status if status is not None else self.http_status
        self.request_id = request_id
        #: How many times the client sent the call before this error (1 + its retries); None when no request raised it.
        self.attempts = attempts

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        details = self.__dict__.get("details") or {}
        if name in details:
            return details[name]
        raise AttributeError(f"{type(self).__name__} has no attribute {name!r}")

    def __str__(self) -> str:
        return f"{self.message} Next step: {self.next_step}" if self.next_step else self.message

    def __repr__(self) -> str:
        return f"{type(self).__name__}(type={self.type!r}, message={self.message!r})"

    def __reduce__(self):
        return (_rebuild, (type(self), self.message, self.next_step, self.details, self.status, self.request_id,
                           self.attempts))


def _rebuild(cls, message, next_step, details, status, request_id, attempts=None):
    return cls(message, next_step=next_step, details=details, status=status, request_id=request_id, attempts=attempts)


# Mirrors of the server's classes (same ``type`` strings and statuses).
class InvalidRequest(Error):
    """The request is malformed or a value is out of range; ``field`` names the argument when there is one."""

    type, http_status = "invalid_request", 400


class Unauthenticated(Error):
    """No key was sent, or the key or session token isn't valid (revoked, expired, or not a platform key)."""

    type, http_status = "unauthenticated", 401


@dataclass(frozen=True)
class Offer:
    """One way past a refusal for money: a link a person opens to pay, no sign-in needed.
    Paying stays that person's act; hand them ``url``."""

    #: ``plan`` (a plan that includes what was refused), ``funds`` (an amount added to the
    #: balance) or ``topup`` (a monthly add-on, on the older plans).
    kind: str
    #: What it buys, in words: ``the Plus plan, billed monthly``.
    label: str
    price_usd: float
    url: str
    #: When the link stops working; refused again before then, the same link comes back.
    expires_at: Any
    #: The ``payment`` operation the link settles: ``wait()`` returns once it's paid,
    #: and raises ``OperationExpired`` if it never is.
    operation: "Operation"


class _Offering(Error):
    @property
    def offers(self) -> List[Offer]:
        """The links that would lift this refusal (empty for a user's scope, which never pays for the account)."""
        if "_offers" not in self.__dict__:
            from ._object import parse_time
            from .operation import Operation

            client, scope = self._origin
            self.__dict__["_offers"] = [
                Offer(o.get("kind"), o.get("label"), o.get("price_usd"), o.get("url"), parse_time(o.get("expires_at")),
                      Operation._from_payload(o.get("operation_id"), client=client, user=scope, kind="payment"))
                for o in self.details.get("offers") or []
            ]
        return self.__dict__["_offers"]


class PaymentRequired(_Offering):
    """Your account can't pay for this: ``balance_usd`` is what's left and
    ``required_usd`` what the call needs, in US dollars. ``offers`` are links a
    person opens to add funds or change plan; retry once one is paid. A model
    provider's account out of funds (your own key) raises it too, with ``reason``
    ``"provider_out_of_funds"``. A deployed app's paid call names the app in
    ``project`` and ``project_id`` (invite-only beta)::

        except noclick.PaymentRequired as short:
            for offer in short.offers:
                print(offer.label, offer.price_usd, offer.url)
    """

    type, http_status = "payment_required", 402

    @property
    def balance_usd(self) -> Optional[float]:
        return self.details.get("balance_usd")

    @property
    def required_usd(self) -> Optional[float]:
        return self.details.get("required_usd")


class PlanRequired(_Offering):
    """The account's plan doesn't allow this: plans cap some resources. ``offers``
    are links to the plans that do."""

    type, http_status = "plan_required", 402


class PriceExceeded(Error):
    """It would cost more than the ceiling you set (``max_monthly_usd`` on ``PhoneNumber.buy``)."""

    type, http_status = "price_exceeded", 402


# The operation of a call NoClick holds for the account's owner, which runs the call once they approve.
HELD_CALL = "gate.held_call"


class ApprovalRequired(Error):
    """Policy wants a person to approve this call first. A ``Human.approve``
    request is already out; wait on it, then retry with ``approval_id=``::

        except noclick.ApprovalRequired as pending:
            if pending.operation.wait():
                noclick.run("gmail.send_email_message", args, approval_id=pending.approval_id)

    ``approve_url`` is set only when the approver is the one the call is made for. ``operation`` is
    ``None`` only when a user's session, or a key pinned to them, makes a call someone else approves.

    A call NoClick holds for the account's owner (a purchase, a deletion that can't be undone, a
    change from an agent or a connected app) waits on the owner instead, who approves it from the link
    NoClick sends them (``sent_to`` says where). NoClick makes the call itself once they do: wait on
    ``operation`` for its answer, and don't retry it::

        except noclick.ApprovalRequired as held:
            print(held.operation.wait()["response"])
    """

    type, http_status = "approval_required", 402

    @property
    def approval_id(self) -> Optional[str]:
        return self.details.get("approval_id")

    @property
    def approve_url(self) -> Optional[str]:
        """The page where the approver answers."""
        return self.details.get("approve_url")

    @property
    def operation(self) -> Optional["Operation"]:
        """The approval as an operation: ``.wait()`` returns ``True`` once approved. ``None`` when the
        call's credential can't read it: a user's session, or a key pinned to them, for a call someone
        else approves.

        A call NoClick holds for the account's owner (a purchase, a deletion that can't be undone, a
        raised limit, a change from an agent or a connected app) is the held call itself instead
        (``operation_id``): NoClick makes the call once they approve, so there's nothing to retry, and
        ``.wait()`` returns ``{"status", "response"}``, the call's HTTP status and its answer. It raises
        ``noclick.PolicyDenied`` if they decline, and ``noclick.Expired`` if nobody answers in time."""
        if "_operation" not in self.__dict__:
            from .human import HumanRequest
            from .operation import Operation

            client, scope = self._origin
            found: Optional["Operation"] = HumanRequest._held(self.details, client=client, user=scope)
            held = self.details.get("operation_id")
            if found is None and isinstance(held, str) and held:
                found = Operation._from_payload(held, client=client, user=scope, kind=HELD_CALL)
            self.__dict__["_operation"] = found
        return self.__dict__["_operation"]


class SpendCapExceeded(Error):
    """A monthly spend cap (``scope``: key, user, agent, ...) is used up. A deployed app's paid
    call names the app in ``project`` and ``project_id``, with ``scope`` ``project`` when it's
    the app's own ``budget_usd_per_month``."""

    type, http_status = "spend_cap_exceeded", 402

    @property
    def cap(self) -> Optional[float]:
        return self.details.get("cap")

    @property
    def spent(self) -> Optional[float]:
        return self.details.get("spent")

    @property
    def scope(self) -> Optional[str]:
        return self.details.get("scope")


class SpendingPaused(Error):
    """You paused this user's spending (``user.pause_spending()``), so nothing that costs
    money runs for them until ``user.resume_spending()``. ``message`` and ``next_step``
    are for you; ``user_message`` and ``action`` (a ``(label, url)`` pair, or ``None``) are
    what you asked NoClick to tell the user, to show them as they are; ``since`` is when
    you paused them::

        except noclick.SpendingPaused as paused:
            show_banner(paused.user_message, paused.action)
    """

    type, http_status = "spending_paused", 402

    @property
    def user_message(self) -> Optional[str]:
        return self.details.get("user_message")

    @property
    def action(self) -> Optional[Tuple[str, str]]:
        action = self.details.get("action")
        return (action["label"], action["url"]) if isinstance(action, dict) else None

    @property
    def since(self) -> Any:
        from ._object import parse_time

        return parse_time(self.details.get("since"))


class PermissionDenied(Error):
    """The key or session lacks the scope, or the user it acts for can't do this (another user's object, a suspended user)."""

    type, http_status = "permission_denied", 403


class PolicyDenied(Error):
    """Your policy (``noclick.Policy``) forbids this tool."""

    type, http_status = "policy_denied", 403


class NotFound(Error):
    """Nothing by that id or name in this account, or owned by the user the call acts for."""

    type, http_status = "not_found", 404


class Conflict(Error):
    """It already exists (``existing_id`` names it), or another call holds it, like a conversation mid-turn.
    An edit of a workflow's graph checked against a version it has moved on from (``if_version``) carries the
    workflow as it stands: its ``version`` and ``graph`` (a ``noclick.WorkflowGraph``), to decide again from."""

    type, http_status = "conflict", 409
    #: The workflow's graph as it stands, on a refused edit of it (``None`` on any other conflict).
    graph: Any = None

    @property
    def existing_id(self) -> Optional[str]:
        return self.details.get("existing_id")

    @property
    def version(self) -> Optional[int]:
        """The version kept, on a refused edit of a workflow's graph or of your channel sections."""
        return self.details.get("version")


class NotAvailable(Error):
    """Not available here: a feature the account doesn't have yet (phone numbers), or a sandbox that has stopped."""

    type, http_status = "not_available", 409


class ActionRequired(Error):
    """Something has to be set up first, such as an agent answering a number before it can place calls."""

    type, http_status = "action_required", 409


class AnswerRequired(Error):
    """A workflow build waits on an answer, and ``question`` (a ``BuildQuestion``) says what. Answer it with
    ``build.answer(...)`` where ``question.answerable_from_code``; otherwise send a person to
    ``question.answer_url``. Then ``build.wait()`` again: it waits through a question it has raised."""

    type = "answer_required"
    question: Any = None


class _ConnectionError(Error):
    @property
    def connect_url(self) -> Optional[str]:
        """Where the user connects (or reconnects) the account."""
        return self.details.get("connect_url")

    @property
    def connection(self) -> Optional[str]:
        """The connection's name."""
        return self.details.get("connection")

    @property
    def integration(self) -> Optional[str]:
        return self.details.get("integration")


class NeedsConnection(_ConnectionError):
    """The connection has no account connected yet; send the person ``connect_url``."""

    type, http_status = "needs_connection", 424


class CredentialDisconnected(_ConnectionError):
    """The connection's account was revoked or stopped working; send the person
    ``connect_url`` to reconnect it (same name)."""

    type, http_status = "credential_disconnected", 424


class QuotaExceeded(Error):
    """An account limit is reached (live sandboxes, background commands, inboxes); retrying later won't help."""

    type, http_status = "quota_exceeded", 429


class PlanLimitReached(Error):
    """An agent's turn its model connection's Claude or ChatGPT plan turned down at its limit: ``connection``,
    ``window`` (``five_hour``, ``weekly``...), when it's back (``resets_at``) and what the agent did (``then``: it
    ``switched`` to another connection and carried on, or is ``waiting_until`` the reset, or ``asked`` the owner to
    allow a paid key)."""

    type, http_status = "plan_limit_reached", 429

    @property
    def connection(self) -> Optional[str]:
        return self.details.get("connection")

    @property
    def window(self) -> Optional[str]:
        return self.details.get("window")

    @property
    def resets_at(self) -> Optional[str]:
        return self.details.get("resets_at")

    @property
    def then(self) -> Optional[Dict[str, Any]]:
        return self.details.get("then")


class RateLimited(Error):
    """Too many requests, or a send cap reached (emails, inbox replies); ``retry_after`` says when to try again."""

    type, http_status = "rate_limited", 429


class UpstreamError(Error):
    """A service NoClick relays to refused the call or failed. A refusal, such as an integration's
    service answering a run with an error, comes in its own words, its HTTP status in
    ``upstream_status``, and answers 424: it isn't retried, since sending the same call again won't
    help. A failure (a model's provider down, a service that didn't answer) answers 503 and is
    retried; once retries run out, retrying in a moment usually works. Where it matters, as for a
    database's statements, ``applied`` says whether the call took effect::

        except noclick.UpstreamError as err:
            if err.applied is False:  # it didn't run, so sending it again is safe
                db.execute(sql, params)
    """

    type, http_status = "upstream_error", 503

    @property
    def applied(self) -> Optional[bool]:
        """``False`` when NoClick knows the call didn't take effect (a read, or a write the service never
        ran), so sending it again is safe; ``True`` when it did; ``None`` when NoClick can't tell, as for a
        write a database never answered (the message says so): check before sending it again."""
        value = self.details.get("applied")
        return value if isinstance(value, bool) else None

    @property
    def upstream_attempts(self) -> Optional[int]:
        """How many times NoClick sent the call to the service before giving up."""
        value = self.details.get("upstream_attempts")
        return value if isinstance(value, int) and not isinstance(value, bool) else None


class RequestTimeout(Error, TimeoutError):
    """The work outlasted what one request may wait (about 90 seconds); it answers 503. The client
    doesn't retry it, since the work may still be going on: an agent's turn goes on
    and lands in its conversation (``operation_id`` and ``conversation`` say where)."""

    type, http_status = "request_timeout", 503


# Client-side conditions with no server class.
class ServerError(Error):
    """A 5xx the server could not describe as a platform error."""

    type = "server_error"


class APIConnectionError(Error):
    """The API could not be reached, even after retries."""

    type = "connection_error"


class OperationFailed(Error):
    """An operation finished ``failed`` without a more specific error type."""

    type = "operation_failed"


class OperationCanceled(Error):
    """The operation was canceled before it finished."""

    type = "operation_canceled"


class Expired(Error):
    """A request or operation expired before anyone acted on it."""

    type, http_status = "expired", 410


OperationExpired = Expired


class WebhookSignatureError(Error):
    """A webhook delivery's ``NoClick-Signature`` doesn't match its body, or its timestamp is too old.
    Raised by ``Webhook.verify`` in your receiver; answer it with a 400 and drop the delivery."""

    type = "webhook_signature_invalid"


class OperationTimeout(Error, TimeoutError):
    """``Operation.wait(timeout=...)`` ran out before the operation finished."""

    type = "operation_timeout"


_BY_TYPE: Dict[str, Type[Error]] = {}


def _register(cls: Type[Error]) -> None:
    _BY_TYPE.setdefault(cls.type, cls)
    for sub in cls.__subclasses__():
        _register(sub)


_register(Error)

_BY_STATUS: Dict[int, Type[Error]] = {
    400: InvalidRequest,
    401: Unauthenticated,
    403: PermissionDenied,
    404: NotFound,
    409: Conflict,
    410: Expired,
    424: NeedsConnection,
    429: RateLimited,
}

_BASE_KEYS = ("type", "message", "next_step")


def error_from_payload(
    payload: Any,
    *,
    status: Optional[int] = None,
    request_id: Optional[str] = None,
    default: Type[Error] = Error,
) -> Error:
    """Build the matching exception from an ``error`` object (or a whole
    ``{"error": {...}}`` body)."""
    if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
        payload = payload["error"]
    if not isinstance(payload, dict):
        payload = {"message": str(payload) if payload else ""}
    type_ = payload.get("type")
    if isinstance(payload.get("code"), str) and payload["code"] in _BY_TYPE:
        # OpenAI's envelope (``/v1/ai``): ``type`` is OpenAI's, ``code`` the platform's.
        type_ = payload["code"]
    cls = _BY_TYPE.get(type_) if isinstance(type_, str) else None
    if cls is None or cls is Error:
        if status is not None and status >= 500:
            cls = ServerError
        else:
            cls = _BY_STATUS.get(status or 0, default)
    err = cls(
        payload.get("message") or f"Request failed ({type_ or status or 'unknown'}).",
        next_step=payload.get("next_step"),
        details={k: v for k, v in payload.items() if k not in _BASE_KEYS},
        status=status,
        request_id=request_id,
    )
    if isinstance(type_, str) and type_ != cls.type:
        err.type = type_  # an unknown server type stays visible on the base class
    return err


__all__ = [
    "Error",
    "Offer",
    "InvalidRequest",
    "Unauthenticated",
    "PaymentRequired",
    "PlanRequired",
    "PriceExceeded",
    "ApprovalRequired",
    "SpendCapExceeded",
    "PermissionDenied",
    "PolicyDenied",
    "NotFound",
    "Conflict",
    "NotAvailable",
    "ActionRequired",
    "AnswerRequired",
    "NeedsConnection",
    "CredentialDisconnected",
    "QuotaExceeded",
    "PlanLimitReached",
    "RateLimited",
    "UpstreamError",
    "RequestTimeout",
    "ServerError",
    "APIConnectionError",
    "OperationFailed",
    "OperationCanceled",
    "Expired",
    "OperationExpired",
    "OperationTimeout",
    "error_from_payload",
]
