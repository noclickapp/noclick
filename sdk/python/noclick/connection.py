"""Connections: named links to your users' accounts on other services, and
what those services can do.

    gmail = noclick.Connection.from_name("gmail", integration="gmail", create_if_missing=True)
    if not gmail.connected:
        send_to_user(gmail.connect_url)
    gmail.wait()
    gmail.run("send_email_message", {...})

A connection is a name in one scope (a user, or your account's own). Code,
toolkits and agents name it, so they always act in exactly that account; two
accounts on one service are two connections. Reconnecting keeps the name.

An operation that needs no account (``exa``'s web search) needs no connection
either: ``noclick.run("exa.search", {...})`` and ``tools=["exa.search"]`` run it
on NoClick's key, for every user. A connection named ``exa`` holding your own
key takes over the same refs. ``Connection.integrations()`` finds a service,
and ``operations()`` says what a connection's service can do.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field as dc_field
from typing import Any, Dict, List, Optional, Sequence, Union

from ._client import Client, path_segment, resolve_client
from ._designed import designed
from ._object import (
    Page, _Object, bound_arguments, check_unchanged, compact, field, list_all, list_page, parse_time,
    ref_id, required_number, tool_entries,
)
from ._scope import AMBIENT, resolve_scope, user_ref
from ._sync import synced
from .exceptions import Conflict, Error, InvalidRequest, NotFound, OperationCanceled, OperationExpired, OperationTimeout
from .database import Database
from .operation import _LONG_POLL_S, Operation, OperationSummary, _with_kinds, register_result
from .repo import RepoCheckout, _folder, _pushable


@dataclass(frozen=True)
class Verification:
    """Whether the provider accepted the credential (``reachable`` None = cannot judge): things of the account's own
    as the provider sees them (``samples``, which are ``noun``, ``total`` of them when more), who it signs in as
    (``account_label``), whether that proves the account (``proves`` ``account``) or only that the key was accepted
    (``reachability``), and a refusal in the provider's own words (``error``)."""

    reachable: Optional[bool]
    samples: List[Any]
    message: Optional[str]
    hint: Optional[str] = None
    noun: Optional[str] = None
    total: Optional[int] = None
    account_label: Optional[str] = None
    proves: Optional[str] = None
    error: Optional[str] = None
    raw: Dict[str, Any] = dc_field(default_factory=dict, repr=False)

    @classmethod
    def _from(cls, raw: Optional[Dict[str, Any]]) -> Optional["Verification"]:
        if not isinstance(raw, dict):
            return None
        return cls(raw.get("reachable"), list(raw.get("samples") or []), raw.get("message"), raw.get("hint"),
                   raw.get("noun"), raw.get("total"), raw.get("account_label"), raw.get("proves"), raw.get("error"),
                   raw)


@dataclass(frozen=True)
class ConnectionShared:
    """How an account shared with yours reaches it: shared with your account's person (``with_`` ``you``) or with the
    team workspace it's read in (``workspace``), and who shared it (``by_name``, ``by_email``)."""

    with_: str
    by_name: Optional[str]
    by_email: Optional[str]
    raw: Dict[str, Any] = dc_field(default_factory=dict, repr=False)

    @classmethod
    def _from(cls, raw: Optional[Dict[str, Any]]) -> Optional["ConnectionShared"]:
        if not isinstance(raw, dict):
            return None
        by = raw.get("by") or {}
        return cls(raw.get("with") or "you", by.get("name"), by.get("email"), raw)


@dataclass(frozen=True)
class ConnectionHealth:
    """A provider's live word on a linked session (a WhatsApp number's, a Discord install's): ``healthy``, the
    provider's own word for its state (``status``) and, when it isn't healthy, what to do (``hint``)."""

    healthy: bool
    status: str
    hint: Optional[str]
    raw: Dict[str, Any] = dc_field(default_factory=dict, repr=False)

    @classmethod
    def _from(cls, raw: Optional[Dict[str, Any]]) -> Optional["ConnectionHealth"]:
        if not isinstance(raw, dict):
            return None
        return cls(raw.get("healthy") is True, raw.get("status") or "", raw.get("hint"), raw)


@dataclass(frozen=True)
class Plan:
    """A Claude or ChatGPT plan's tier: ``tier`` as NoClick names it (``"max_20x"``, ``"plus"``, ``"free"``) and
    ``label`` as its provider does (``"Ultra"``, ``"Plus"``), both None until NoClick has read them; the harnesses it
    runs (``runs``), and why it runs none (``refusal``: ``"ChatGPT Free doesn't include Codex."``)."""

    tier: Optional[str]
    label: Optional[str]
    runs: List[str]
    refusal: Optional[str]
    raw: Dict[str, Any] = dc_field(default_factory=dict, repr=False)

    @classmethod
    def _from(cls, raw: Optional[Dict[str, Any]]) -> Optional["Plan"]:
        if not isinstance(raw, dict):
            return None
        return cls(raw.get("tier"), raw.get("label"), list(raw.get("runs") or []), raw.get("refusal"), raw)


@dataclass(frozen=True)
class PlanWindow:
    """One of a plan's limits: ``kind`` (``five_hour``, ``weekly``, ``weekly_model``, ``other``), ``label``
    (``"5-hour"``, ``"Opus weekly"``), the ``models`` it limits (empty: every model), how much of it is ``used`` and
    ``left`` (0 to 1), when it ``resets_at``, and its ``state`` (``ok``, ``near`` from 80% used, ``used_up``)."""

    kind: str
    label: str
    models: List[str]
    used: float
    left: float
    resets_at: Any
    state: str
    raw: Dict[str, Any] = dc_field(default_factory=dict, repr=False)

    @classmethod
    def _from(cls, raw: Optional[Dict[str, Any]]) -> Optional["PlanWindow"]:
        if not isinstance(raw, dict):
            return None
        return cls(raw.get("kind") or "other", raw.get("label") or "", list(raw.get("models") or []),
                   float(raw.get("used") or 0), float(raw.get("left") or 0), parse_time(raw.get("resets_at")),
                   raw.get("state") or "ok", raw)


@dataclass(frozen=True)
class PlanNextStep:
    """What to do while a plan is near or past its limit: ``wait`` until it's back (``until``), run on another
    ``connection`` (a key ``pays`` ``per_use``), run on NoClick's key (``noclick_key``, ``at_cost``), or ``connect``
    another. ``state`` is another plan's own for the model asked about (``near``: nearly used too); None for a key."""

    kind: str
    label: str
    until: Any
    connection: Optional[Dict[str, Any]]
    pays: Optional[str]
    raw: Dict[str, Any] = dc_field(default_factory=dict, repr=False)
    state: Optional[str] = None

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "PlanNextStep":
        return cls(raw.get("kind") or "", raw.get("label") or "", parse_time(raw.get("until")), raw.get("connection"),
                   raw.get("pays"), raw, state=raw.get("state"))


@dataclass(frozen=True)
class PlanUsageSummary:
    """A plan's usage as a list shows it, over every window: its ``state`` (``ok``, ``near``, ``used_up``,
    ``unknown``), the window that stops it first (``tightest``), when a used-up plan is back (``available_at``) and
    when it was read (``as_of``)."""

    state: str
    tightest: Optional[PlanWindow]
    available_at: Any
    as_of: Any
    raw: Dict[str, Any] = dc_field(default_factory=dict, repr=False)

    @classmethod
    def _from(cls, raw: Optional[Dict[str, Any]]) -> Optional["PlanUsageSummary"]:
        if not isinstance(raw, dict):
            return None
        return cls(raw.get("state") or "unknown", PlanWindow._from(raw.get("tightest")),
                   parse_time(raw.get("available_at")), parse_time(raw.get("as_of")), raw)


@dataclass(frozen=True)
class PlanUsage(PlanUsageSummary):
    """How much of a plan is used: ``PlanUsageSummary``'s fields over the ``windows`` that can stop the model asked
    about, what to do meanwhile (``next_steps``), where the reading came from (``source``: ``provider`` or
    ``harness``), the ``plan``, the ``connection`` it's of and its provider (``integration``: ``anthropic`` or
    ``openai``)."""

    windows: List[PlanWindow] = dc_field(default_factory=list)
    next_steps: List[PlanNextStep] = dc_field(default_factory=list)
    source: Optional[str] = None
    plan: Optional[Plan] = None
    connection: Optional[str] = None
    integration: Optional[str] = None

    @classmethod
    def _from(cls, raw: Optional[Dict[str, Any]]) -> "PlanUsage":
        raw = raw if isinstance(raw, dict) else {}
        return cls(raw.get("state") or "unknown", PlanWindow._from(raw.get("tightest")),
                   parse_time(raw.get("available_at")), parse_time(raw.get("as_of")), raw,
                   [w for w in (PlanWindow._from(x) for x in raw.get("windows") or []) if w],
                   [PlanNextStep._from(x) for x in raw.get("next_steps") or [] if isinstance(x, dict)],
                   raw.get("source"), Plan._from(raw.get("plan")), raw.get("connection"), raw.get("integration"))


@dataclass(frozen=True)
class Token:
    """A short-lived OAuth access token (never a refresh token or API key)."""

    access_token: str
    token_type: Optional[str]
    expires_at: Any
    raw: Dict[str, Any] = dc_field(repr=False)

    def __repr__(self) -> str:
        return f"Token(token_type={self.token_type!r}, expires_at={self.expires_at!r})"


@dataclass(frozen=True)
class LookupOption:
    value: Any
    label: Optional[str]
    raw: Dict[str, Any] = dc_field(repr=False)


class LookupOptions(List[LookupOption]):
    """A page of options; pass ``next_page_token`` back as ``page_token``."""

    next_page_token: Optional[str] = None


@dataclass(frozen=True)
class IntegrationInfo:
    """A service NoClick can operate, such as ``gmail``, or a model provider an
    agent thinks with, such as ``anthropic``: one of ``Connection.integrations()``.
    Its ``name`` is what ``integration=`` takes."""

    name: str
    label: Optional[str]
    #: ``"app"``, a service whose operations are tools, or ``"model"``, a model provider whose
    #: connection an agent names as its ``model_connection`` (never in ``tools=``).
    kind: str
    #: Whether its connect link also offers signing in with the provider's plan (a Claude or
    #: ChatGPT subscription) instead of pasting a key, signed in by the person it belongs to.
    subscription: bool
    #: How a person connects an account: ``"oauth"`` (signing in), ``"key"`` (pasting a key or token),
    #: ``"qr"`` (scanning a code) or ``"purchase"`` (a phone number, bought rather than connected).
    connect_with: List[str]
    operation_count: Optional[int]
    #: How many of its operations need no account (0 for most): ``noclick.run`` and ``tools=`` run
    #: them on NoClick's key by the integration's name (``"exa.search"``), with no connection.
    account_free_operation_count: int
    #: The exact credential types it takes, for ``credential_type=`` when you import a key you hold
    #: (``connection.import_``, ``Connection.create``).
    credential_types: List[str]
    #: The app events an ``OnEvent`` trigger takes from it (``connection.events()`` has their filters).
    #: Empty for one that only acts: nothing it does wakes an agent.
    events: List[str]
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "IntegrationInfo":
        return cls(raw["name"], raw.get("label"), raw["kind"], bool(raw["subscription"]), list(raw["connect_with"]),
                   raw.get("operation_count"), required_number(raw, "account_free_operation_count"),
                   list(raw.get("credential_types") or []), list(raw.get("events") or []), raw)


@dataclass(frozen=True)
class IntegrationOperation:
    """One operation of a connection's integration, with the JSON schema of the
    ``parameters`` ``connection.run`` takes for it."""

    name: str
    description: Optional[str]
    parameters: Dict[str, Any]
    #: A hint from the operation's name (reads start with ``list_``, ``get_`` and the like), not a guarantee.
    read_only: Optional[bool]
    #: The OAuth scopes it needs, where NoClick knows them.
    scopes: List[str]
    #: False when it runs on NoClick's key with no account at all (web search, public data), so it runs with
    #: no connection (``"exa.search"``) and on a pending one; True otherwise, also when the need depends on its arguments.
    needs_account: bool
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "IntegrationOperation":
        return cls(raw["name"], raw.get("description"), raw.get("parameters") or {}, raw.get("read_only"),
                   list(raw.get("scopes") or []), raw.get("needs_account") is not False, raw)


@dataclass(frozen=True)
class IntegrationEvent:
    """An app event a connection's integration can deliver to an agent's
    ``noclick.OnEvent`` trigger, a channel's subscription or an app's: its ``name``
    (``channel_message``, ``contact_created``), what it means, and ``filters``, the
    keyword arguments that narrow it, each with what it matches (one marked
    ``Required.`` must be given). ``shape`` is what its data holds, each field's type
    (``"string"``, ``"integer"``, ``"boolean"``, ``"null"``, an object, ``[...]`` for a
    list) as the event has reached your account, and ``sample`` that shape with a
    placeholder for each value (what ``subscription.test()`` sends as ``data``); both
    ``None`` until one has. Another account's events never show here."""

    name: str
    description: Optional[str]
    filters: Dict[str, str]
    shape: Optional[Dict[str, Any]] = None
    sample: Optional[Dict[str, Any]] = None
    raw: Dict[str, Any] = dc_field(default_factory=dict, repr=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "IntegrationEvent":
        return cls(raw["name"], raw.get("description"),
                   {str(k): str(v) for k, v in (raw.get("filters") or {}).items()},
                   raw.get("shape"), raw.get("sample"), raw)


def _integration_name(integration: Any) -> Optional[str]:
    if integration is None or isinstance(integration, str):
        return integration
    return integration.name


def normalize_send_to(send_to: Any) -> Any:
    """The wire ``send_to``: ``{"user": true}``, ``{"owner": true}`` or an address with an email.
    Connect links are delivered by email only, so a phone alone is refused."""
    if send_to is None:
        return None
    if send_to == "user" or send_to is True:
        return {"user": True}
    if send_to == "owner":
        return {"owner": True}
    if isinstance(send_to, str) and "@" in send_to:
        return {"email": send_to}
    phone_only = isinstance(send_to, str) and send_to.startswith("+") or (
        isinstance(send_to, dict) and send_to.get("phone") and not send_to.get("email") and not send_to.get("user"))
    if phone_only:
        raise InvalidRequest(
            "Connect links are delivered by email only, and this person has only a phone number.",
            next_step="Pass an email, or send the link's url yourself.",
        )
    if isinstance(send_to, dict):
        return send_to
    raise ValueError(f"send_to must be 'user', 'owner', an email or a dict, not {send_to!r}")


def _link_options(redirect_url: Optional[str], reason: Optional[str], send_to: Any) -> Dict[str, Any]:
    return compact(redirect_url=redirect_url, reason=reason, send_to=normalize_send_to(send_to))


class Connection(_Object):
    """A named connection to an account on another service. Secrets never come
    back; ``token()`` mints an OAuth access token when the key has
    ``credentials:token``.

    ``status`` is ``pending`` until someone connects an account at
    ``connect_url``, ``connected`` after, and ``disconnected`` once the account
    is revoked (``connect_link()`` mints a link to reconnect it). Operations
    that need no account run on NoClick's key even while it's pending.

    The accounts connected in the NoClick app are connections too, in your
    account's own scope: ``origin`` is ``"app"`` and the id is
    ``credential:<id>`` (their name is the app's, so refer to them by id).
    They run, look up, verify and take ``require_approval`` like any
    connection, and an account agent takes one as a tool (the ``Connection``,
    or ``"credential:<id>"``, ``"credential:<id>.operation"``; a user's agent
    can't); the app connects and reconnects them, and ``delete()`` removes
    one as the app does. One shared with your account has ``access``
    ``"view"`` or ``"edit"``: it runs, but its token, approval rules and
    deletion stay its owner's. A Claude or ChatGPT plan you
    signed in to in the app is one too, an account agent's
    ``model_connection``; a plan shared with you, or filled in by someone
    else, isn't.

    One a teammate shared with a team workspace you're in is that team's to
    use, in its workspace only: name the workspace (``organization_id=``)
    to list, find and run it there. A connection read in a team workspace
    carries it (``organization_id``), and everything it does goes there, as
    the team's work.

    An app's preview only reads through a connection: an operation that writes
    in its account is refused (``noclick.PermissionDenied``) unless the
    connection is a test account (``mark_test_account()``)."""

    _repr_keys = ("name", "integration", "status")

    id: str = field("id")
    name: str = field("name")
    integration: str = field("integration")
    credential_type: Optional[str] = field("credential_type")
    user_id: Optional[str] = field("user_id")
    status: str = field("status")
    origin: str = field("origin", doc="``api`` for a named connection, ``app`` for an account connected in the app.")
    access: str = field("access", doc="Your account's access: ``owner``, or ``edit``/``view`` on one shared with it.")
    organization_id: Optional[str] = field("organization_id", doc=(
        "The team workspace it was read in (``organization_id=``), where it runs; ``None`` in your account's own."))
    approval_operations: List[str] = field(
        "approval_operations",
        doc="Operations its owner approves call by call wherever it runs (``*``: all of them); "
        "``require_approval`` adds to them.",
    )
    account: Optional[str] = field("account", doc=(
        "The account it reaches, as the app's Connections list names it: its login, else its email, else who a "
        "check verified it as, else the number it links; ``None`` when none is known."))
    test_account: bool = field(
        "test_account", bool, doc="Whether it's a test account, which an app's preview writes through as well as reads.",
    )
    used_by: List[Dict[str, Any]] = field(
        "used_by",
        doc="What holds it: agents (in their tools, as their ``model_connection``, given it by their user, or with a "
        "trigger on it), channels and workspaces subscribed to its events, hosted MCP servers with it in their tools, "
        "apps that bind it or whose code made it, numbers connected through it, and the automations whose steps use "
        "its account (yours, and for an account yours owns, those in its workspace). Each is ``kind`` (``agent``, "
        "``channel``, ``workspace``, ``mcp_server``, ``project``, ``phone_number`` or ``workflow``), ``id``, "
        "``name``, ``user_id`` and an app's ``binding`` name.",
    )
    connected_at: Any = field("connected_at", parse_time)
    created_at: Any = field("created_at", parse_time)
    updated_at: Any = field("updated_at", parse_time)

    def _init(self, **kwargs: Any) -> None:
        self._create_with: Optional[Dict[str, Any]] = None
        # from_name's integration=: what the catalog reads use before the connection is loaded.
        self._integration_hint: Optional[str] = None
        # What from_name says the connection is (its integration, credential type): checked once it's found.
        self._identity: Dict[str, Any] = {}
        super()._init(**kwargs)

    @property
    def connected(self) -> bool:
        return self.status == "connected"

    @property
    def connect_url(self) -> Optional[str]:
        """The open link where someone connects (or reconnects) the account, if one is open."""
        return (self._sync_raw().get("connect_link") or {}).get("url")

    @property
    def verification(self) -> Optional[Verification]:
        return Verification._from(self._sync_raw().get("verification"))

    @property
    def shared(self) -> Optional[ConnectionShared]:
        """How one connected in the app and shared with your account reaches it, and who shared it; None for your
        own and for a named connection."""
        return ConnectionShared._from(self._sync_raw().get("shared"))

    @property
    def health(self) -> Optional[ConnectionHealth]:
        """The provider's live word on a linked session (a WhatsApp number's, a Discord install's), read with the
        connection; None where there's nothing to ask or no telling."""
        return ConnectionHealth._from(self._sync_raw().get("health"))

    @property
    def plan(self) -> Optional[Plan]:
        """A Claude or ChatGPT plan's tier, what it runs and why it runs none; None on anything but a plan."""
        return Plan._from(self._sync_raw().get("plan"))

    @property
    def usage_summary(self) -> Optional[PlanUsageSummary]:
        """A plan's usage as last read, over every window; None on anything but a plan, or one never read.
        ``usage()`` reads it in full, for a model."""
        return PlanUsageSummary._from(self._sync_raw().get("usage"))

    # --- construction ----------------------------------------------------

    @classmethod
    def from_name(
        cls,
        name: str,
        *,
        integration: Any = None,
        create_if_missing: bool = False,
        credential_type: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
        redirect_url: Optional[str] = None,
        reason: Optional[str] = None,
        send_to: Any = None,
        user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> "Connection":
        """A lazy reference to the connection called ``name`` in the current
        (or given) user. With ``create_if_missing=True`` it's created on
        first use, for ``integration`` (a name, or an ``IntegrationInfo``):
        holding ``data`` when given (a key you hold), else pending with a
        connect link (the link options are ``create``'s). An existing
        connection is used as it is: ``data`` and the link options apply only when it's
        created. ``integration`` and ``credential_type`` say what the connection is, so they're
        checked, with or without ``create_if_missing``: one of another integration or credential
        type raises ``noclick.Conflict`` naming it. ``operations()``, ``operation()`` and
        ``events()`` read ``integration``'s catalog without loading or
        creating it.

        Returns:
            A connection that loads, or is created, the first time it's used. Nothing is sent yet.

        Usage:
            Refer to a connection that already exists::

                gmail = noclick.Connection.from_name("gmail", user="user_42")
                print(gmail.status)   # loads it now; noclick.NotFound if there's none

            Or create it the first time it's used, pending with a link for the user.
            The same line works for a new user and a returning one::

                with noclick.as_user("user_42"):
                    gmail = noclick.Connection.from_name(
                        "gmail", integration="gmail", create_if_missing=True,
                        reason="to send your weekly summaries",
                    )
                    print(gmail.status, gmail.connect_url)   # pending https://noclick.com/credential/provide/...

            With a key you already hold, it's created holding that key (and never overwrites one)::

                crm = noclick.Connection.from_name(
                    "crm", integration="affinity", data={"api_key": "..."},
                    create_if_missing=True, user="user_42",
                )
        """
        connection = cls._new(hints={"name": name}, client=client, user=user)
        connection._integration_hint = _integration_name(integration)
        connection._identity = compact(integration=connection._integration_hint, credential_type=credential_type)
        if create_if_missing:
            if integration is None and credential_type is None:
                raise ValueError("Connection.from_name(create_if_missing=True) needs integration=")
            connection._create_with = compact(
                name=name, integration=_integration_name(integration), credential_type=credential_type,
                data=data, **_link_options(redirect_url, reason, send_to),
            )
        return connection

    @classmethod
    def from_id(
        cls, connection_id: str, *, organization_id: Optional[str] = None, client: Optional[Client] = None,
        user: Any = AMBIENT,
    ) -> "Connection":
        """A lazy reference to a connection by NoClick id, in the current (or
        given) user; ``credential:<id>`` for an account connected in the app.
        ``organization_id`` names a team workspace you're in, where one shared
        with that team is used.

        Returns:
            A connection that loads the first time you read a field. Nothing is sent yet.

        Usage::

            connection = noclick.Connection.from_id("3f1d2c4b-8a7e-4f6d-9b2a-1c5e7d9f0a31", user="user_42")
            print(connection.name, connection.status)

            slack = noclick.Connection.from_id("credential:9b2a1c5e-7d9f-4a31-8f6d-3f1d2c4b8a7e")
            slack.run("send_message", {"channel": "#ops", "text": "Deployed."})
        """
        return cls._new(hints=compact(id=connection_id, organization_id=organization_id), client=client, user=user)

    @synced
    @classmethod
    async def create(
        cls,
        name: str,
        *,
        integration: Any = None,
        credential_type: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
        redirect_url: Optional[str] = None,
        reason: Optional[str] = None,
        send_to: Any = None,
        allow_existing: bool = False,
        user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> "Connection":
        """Create a connection called ``name`` (unique per user; a duplicate
        raises ``noclick.Conflict`` with ``existing_id``). With ``allow_existing=True``
        a taken name returns the connection already there, as it is: its credential isn't
        replaced and no link is made. One of another integration still raises the ``Conflict``.
        With ``data`` it holds that credential at once (validated and probed first); without, it's
        pending and ``connect_url`` is where someone connects it. ``send_to``
        ("user", an email, or a dict) also delivers the link.

        Returns:
            The new connection: ``pending`` with its ``connect_url``, or ``connected``
            (with its ``verification``) when you passed ``data``.

        Usage:
            Create a pending connection and show the user its link::

                with noclick.as_user("user_42"):
                    slack = noclick.Connection.create("slack", integration="slack", reason="to post your team's standup")
                    print(slack.connect_url)

            Or create it holding a key you already have. A key the provider
            rejects raises ``noclick.InvalidRequest`` and saves nothing::

                crm = noclick.Connection.create("crm", integration="affinity", data={"api_key": "..."}, user="user_42")
                print(crm.status)   # connected

            A model provider's connection is what an agent on a CLI harness thinks with (its
            ``model_connection``). Pass a key as ``api_key``; a Claude or ChatGPT plan is
            signed in only at the link, by the person it belongs to, on your account's
            connection as on a user's::

                claude = noclick.Connection.create("claude", integration="anthropic", data={"api_key": "sk-ant-..."})
                with noclick.as_user("user_42"):
                    plan = noclick.Connection.create("claude", integration="anthropic")
                    print(plan.connect_url)   # "Paste a Claude key" or "Sign in with Claude"

            If the name may be taken, take the connection already there as it is::

                slack = noclick.Connection.create("slack", integration="slack", user="user_42", allow_existing=True)
                if not slack.connected:
                    print(slack.connect_url)
        """
        scope = resolve_scope(user)
        body = compact(name=name, integration=_integration_name(integration), credential_type=credential_type,
                       data=data, **_link_options(redirect_url, reason, send_to))
        raw = await cls._create_named("/v1/connections", body, allow_existing=allow_existing, user=scope, client=client)
        if allow_existing:
            check_unchanged("connection", raw, compact(integration=body.get("integration"),
                                                       credential_type=credential_type))
        return cls._new(raw=raw, client=client, user=scope)

    @synced
    @classmethod
    async def get(
        cls, ref: str, *, organization_id: Optional[str] = None, user: Any = AMBIENT, client: Optional[Client] = None,
    ) -> "Connection":
        """Load the connection with this id or name now; an unknown one raises ``noclick.NotFound``.
        ``organization_id`` names a team workspace you're in, where one shared with that team is found.

        Returns:
            The connection, loaded.

        Usage::

            with noclick.as_user("user_42"):
                gmail = noclick.Connection.get("gmail")
                print(gmail.status, gmail.account)
        """
        connection = cls._new(hints=compact(ref=ref, organization_id=organization_id), client=client, user=user)
        await connection._ensure()
        return connection

    @synced
    @classmethod
    async def list(
        cls, *, integration: Any = None, origin: Optional[str] = None, organization_id: Optional[str] = None,
        limit: Optional[int] = None, user_filter: Any = None, user: Any = AMBIENT, client: Optional[Client] = None,
    ) -> List["Connection"]:
        """The current user's connections (the account's own outside
        ``as_user``), or those ``user_filter`` covers: named ones newest first,
        then, in the account's own scope, the accounts connected in the app.
        ``origin`` keeps only ``"api"`` or ``"app"`` ones; ``organization_id``
        reads in a team workspace you're in, where those shared with that team
        are listed too (and each runs there).

        Returns:
            Every matching connection (or the first ``limit``), fetched page by page.

        Usage::

            with noclick.as_user("user_42"):
                for connection in noclick.Connection.list():
                    print(connection.name, connection.integration, connection.status)

            every_gmail = noclick.Connection.list(integration="gmail", user_filter=noclick.ALL_USERS)
            from_the_app = noclick.Connection.list(origin="app")
            the_teams = noclick.Connection.list(organization_id="5c0d9e4a-7b1f-4e2a-9c3d-8f6b2a1e4d70")
        """
        return await list_all(
            "/v1/connections", lambda raw, scope: cls._new(raw=raw, client=client, user=scope),
            params={"integration": _integration_name(integration), "origin": origin,
                    "organization_id": organization_id}, user=user,
            user_filter=user_filter, limit=limit, client=client,
        )

    @synced
    @classmethod
    async def list_page(
        cls, *, cursor: Optional[str] = None, limit: Optional[int] = None, integration: Any = None,
        origin: Optional[str] = None, organization_id: Optional[str] = None, user_filter: Any = None,
        user: Any = AMBIENT, client: Optional[Client] = None,
    ) -> Page:
        """One page of connections; pass ``next_cursor`` back as ``cursor``.

        Returns:
            A page whose ``data`` holds the connections and whose ``next_cursor`` is ``None`` on the last page.

        Usage::

            page = noclick.Connection.list_page(limit=50, user_filter=noclick.ALL_USERS)
            while True:
                for connection in page.data:
                    print(connection.user_id, connection.name, connection.status)
                if page.next_cursor is None:
                    break
                page = noclick.Connection.list_page(limit=50, user_filter=noclick.ALL_USERS, cursor=page.next_cursor)
        """
        return await list_page(
            "/v1/connections", lambda raw, scope: cls._new(raw=raw, client=client, user=scope),
            params={"integration": _integration_name(integration), "origin": origin,
                    "organization_id": organization_id}, user=user,
            user_filter=user_filter, cursor=cursor, limit=limit, client=client,
        )

    @synced
    @classmethod
    async def integrations(
        cls, query: Optional[str] = None, *, kind: Optional[str] = None, client: Optional[Client] = None,
    ) -> List[IntegrationInfo]:
        """The services NoClick can operate and the model providers its agents think
        with: every one, or those whose name or label contains ``query`` (ignoring
        case). ``kind="app"`` keeps the services, whose operations are tools;
        ``kind="model"`` keeps the model providers (``anthropic``, ``openai``,
        ``openrouter``, ...), which an agent names as its ``model_connection``. The
        catalog is your account's, the same for every user.

        Returns:
            Each one's ``name`` (what ``integration=`` takes), ``label``, ``kind``, ``operation_count``,
            ``account_free_operation_count`` (how many run with no account, by the service's name),
            ``connect_with`` (how a person connects an account), ``events`` (the app events an
            ``OnEvent`` trigger takes from it, empty for one that only acts) and ``subscription``
            (whether its link also offers signing in with a Claude or ChatGPT plan).

        Usage:
            Find a service, then make a connection to it::

                [crm] = noclick.Connection.integrations("affinity")
                print(crm.label, crm.connect_with)   # Affinity ['key']
                with noclick.as_user("user_42"):
                    affinity = noclick.Connection.from_name("crm", integration=crm, create_if_missing=True)
                    print(affinity.connect_url)

            Or list every service a person connects by signing in::

                for service in noclick.Connection.integrations():
                    if "oauth" in service.connect_with:
                        print(service.name, service.label)

            Or the services with operations that need no account, which run by the service's
            name with no connection (``noclick.run("exa.search", ...)``)::

                for service in noclick.Connection.integrations():
                    if service.account_free_operation_count:
                        print(service.name, service.account_free_operation_count)   # exa 4

            Or whether a service can wake an agent at all, before you build on it::

                [tiktok] = noclick.Connection.integrations("tiktok")
                print(tiktok.events)   # [] : it publishes, and no OnEvent hears it

            Or the model providers an agent's ``model_connection`` can name::

                for provider in noclick.Connection.integrations(kind="model"):
                    print(provider.name, provider.connect_with, provider.subscription)   # anthropic ['key'] True
        """
        page = await resolve_client(client).request(
            "GET", "/v1/integrations", params={"q": query, "kind": kind}, user=None,
        )
        return [IntegrationInfo._from(row) for row in page["data"]]

    @property
    def console_url(self) -> Optional[str]:
        """This connection's kind in the developer console (None off the hosted API)."""
        return self._api.console_url("resources", "connections")

    # --- hydration -------------------------------------------------------

    def _ref(self) -> str:
        return self._known("id") or self._hints.get("ref") or self._hints["name"]

    def _path(self) -> str:
        return f"/v1/connections/{self._ref()}"

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        """Every call on the connection goes to the team workspace it was read in (``organization_id``)."""
        organization_id = self._known("organization_id")
        if organization_id is not None and path.startswith("/v1/connections/"):
            kwargs["params"] = {**(kwargs.get("params") or {}), "organization_id": organization_id}
        return await super()._request(method, path, **kwargs)

    async def _load(self) -> Dict[str, Any]:
        try:
            return self._checked(await self._request("GET", self._path()))
        except NotFound:
            if self._create_with is None:
                raise
        try:
            return await self._request("POST", "/v1/connections", json=self._create_with)
        except Conflict as exc:  # created concurrently
            if not exc.existing_id:
                raise
            return self._checked(await self._request("GET", f"/v1/connections/{exc.existing_id}"))

    def _checked(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """The connection ``from_name`` found, once it's what its ``integration`` and ``credential_type`` said."""
        check_unchanged("connection", raw, self._identity)
        return raw

    async def _act(self, method: str, suffix: str, *, write: bool = False, **kwargs: Any) -> Any:
        """Act by id or name with no read first. A lazy ``create_if_missing``
        connection is created first: a write creates it outright (a name
        already taken is simply used), a use reads it first."""
        if self._raw is None and self._create_with is not None:
            if write:
                try:
                    self._raw = await self._request("POST", "/v1/connections", json=self._create_with)
                except Conflict as exc:
                    if not exc.existing_id:
                        raise
                    self._raw = self._checked(await self._request("GET", f"/v1/connections/{exc.existing_id}"))
                self._create_with = None
            else:
                await self._ensure()
        return await self._request(method, f"{self._path()}{suffix}", **kwargs)

    def only(self, *operations: str) -> "ConnectionOperations":
        """A tool ref to some of its operations, for ``tools=`` (``gmail.only("send_email_message")``);
        a lazy ``create_if_missing`` connection is still created first.

        Returns:
            A ref to just those operations of this connection, to list in ``tools=``; ``bind(...)`` on it fixes
            arguments the model mustn't choose.

        Usage:
            A large integration doesn't fit an agent whole, so name the operations it needs::

                with noclick.as_user("user_42"):
                    stripe = noclick.Connection.from_name("stripe", integration="stripe", create_if_missing=True)
                    support = noclick.Agent.from_name(
                        "support", create_if_missing=True,
                        instructions="You answer the user's billing questions.",
                        tools=[stripe.only("list_invoices", "search_charges"), "search"],
                    )
        """
        if not operations:
            raise ValueError("only() takes at least one operation name")
        return ConnectionOperations(self, list(operations))

    def checkout(
        self,
        repository: str,
        *,
        branch: Optional[str] = None,
        path: Optional[str] = None,
        push: Union[None, str, Sequence[str]] = None,
    ) -> RepoCheckout:
        """One of this connection's repositories (``owner/name`` on its git host; a
        ``github`` connection) checked out in an agent's workspace, for ``Agent(repos=[...])``:
        cloned into ``/workspace/<path>`` (the repository's name when omitted) at a
        conversation's first turn, on ``branch`` (its default when omitted). The agent's git
        reaches this repository only, through NoClick, with a key made for its sandbox and
        revoked when the sandbox ends; the connection's own token never enters it. ``push``
        is the branches it may push to, as globs: NoClick refuses a push to any other ref,
        and without ``push`` the checkout is read-only. ``gh`` reads the repository
        (``gh api repos/<owner>/<name>/...``) and nothing more, since its writes could move a
        branch past ``push``: give the agent the connection's operations
        (``github.only("create_pull_request")``) for pull requests and issues, which your policy
        judges. Sends nothing; a lazy ``create_if_missing`` connection is created when the agent
        is saved, and the connection must be connected before a turn can clone.

        Returns:
            A ``RepoCheckout`` to list in an agent's ``repos``.

        Usage:
            A docs agent that pushes only to branches it names ``noclick/...``::

                github = noclick.Connection.from_name("github", integration="github", create_if_missing=True)
                writer = noclick.Agent.from_name(
                    "docs-writer",
                    create_if_missing=True,
                    instructions="You fix the docs issues you're given in /workspace/docs and open a pull request.",
                    harness="claude_code",
                    model_connection="claude",
                    tools=[github.only("create_pull_request")],
                    repos=[github.checkout("acme/docs", push="noclick/*")],
                )

            Read-only, on a branch, in a folder of your choosing::

                github = noclick.Connection.from_name("github")
                reference = github.checkout("acme/api", branch="release-2.4", path="api")
        """
        if not isinstance(repository, str) or repository.count("/") < 1 or " " in repository:
            raise ValueError(f"repository is 'owner/name' on the connection's service, not {repository!r}")
        return RepoCheckout(
            repository=repository, connection=self, branch=branch, path=_folder(path), push=_pushable(push),
        )

    # --- what its service can do -------------------------------------------

    async def _catalog(self, suffix: str, **kwargs: Any) -> Any:
        """A catalog read for this connection's integration: the loaded connection's, else
        ``from_name``'s ``integration=`` (nothing is loaded or created), else it loads to learn it.
        The catalog is the account's, so no user is sent."""
        integration = self._known("integration") or self._integration_hint
        if integration is None:
            integration = (await self._ensure())["integration"]
        return await self._request("GET", f"/v1/integrations/{path_segment(integration)}{suffix}", user=None, **kwargs)

    @synced
    async def operations(self, search: Optional[str] = None) -> List[IntegrationOperation]:
        """The operations of this connection's integration: every one, or those
        whose name or description contains ``search`` (ignoring case).

        Returns:
            Each operation's ``name``, ``description``, the JSON schema of its ``parameters``,
            ``needs_account`` (False when it runs on NoClick's key, with no connection or on a
            pending one) and ``read_only``, a hint from its name rather than a guarantee.

        Usage:
            See what a user's Slack can do before anyone has connected it. With ``integration=``
            nothing is loaded or created to answer::

                with noclick.as_user("user_42"):
                    slack = noclick.Connection.from_name("slack", integration="slack", create_if_missing=True)
                    for op in slack.operations(search="message"):
                        print(op.name, op.read_only, op.description)

            Find the operations that need no account. They run by the integration's name with no
            connection at all (``noclick.run("exa.search", ...)``), and reading them creates nothing::

                exa = noclick.Connection.from_name("exa", integration="exa")
                keyless = [op.name for op in exa.operations() if not op.needs_account]
        """
        response = await self._catalog("/operations", params={"q": search})
        return [IntegrationOperation._from(row) for row in response["data"]]

    @synced
    async def operation(self, name: str) -> IntegrationOperation:
        """One operation of this connection's integration; an unknown name raises ``noclick.NotFound``.

        Returns:
            The operation, with the JSON schema of the ``parameters`` that ``run`` takes for it.

        Usage:
            Read an operation's parameters before running it::

                slack = noclick.Connection.from_name("slack", integration="slack", user="user_42")
                send = slack.operation("send_message_to_channel")
                print(send.description, send.parameters["required"])
                slack.run("send_message_to_channel", {"channel": "#general", "text": "Standup in 5"})
        """
        return IntegrationOperation._from(await self._catalog(f"/operations/{path_segment(name)}"))

    @synced
    async def events(self) -> List[IntegrationEvent]:
        """The app events this connection's integration can wake an agent with, for ``noclick.OnEvent``.
        A poll (new mail in Gmail, say) is no event here: only what the app pushes as it happens.

        Returns:
            Every event, with its ``description`` and the ``filters`` it takes
            (``channel`` for a Slack message, ``repository`` for a GitHub issue).

        Usage::

            slack = noclick.Connection.from_name("slack", integration="slack", user="user_42")
            for event in slack.events():
                print(event.name, event.description, list(event.filters))
        """
        response = await self._catalog("/events")
        return [IntegrationEvent._from(row) for row in response["data"]]

    # --- connecting ------------------------------------------------------

    @synced
    async def connect_link(
        self, *, redirect_url: Optional[str] = None, reason: Optional[str] = None, send_to: Any = None,
    ) -> "ConnectLink":
        """Mint a new link where someone connects (or reconnects) this
        connection's account. ``send_to`` ("user", "owner" for your account's
        owner, an email, or a dict) also delivers it.

        Returns:
            The link: its ``url``, when it ``expires_at``, and where it went when
            you set ``send_to``. It's also the operation that finishes when
            someone connects: ``link.wait()`` returns the connected ``Connection``.
            The connection's own ``connect_url`` is now this link's.

        Usage:
            Make a link and show it in your product yourself::

                gmail = noclick.Connection.from_name("gmail", user="user_42")
                link = gmail.connect_link(redirect_url="https://app.example.com/settings/connections")
                print(link.url, link.expires_at)

            Or have NoClick email it. From code that isn't acting for a user,
            ``send_to`` can be any email address::

                ops_slack = noclick.Connection.from_name("ops-slack")
                link = ops_slack.connect_link(send_to="ops@example.com", reason="to post alerts in #ops")
                print(link.delivered_via, link.undelivered)   # ['email'] []
                ops_slack = link.wait()
        """
        payload = await self._act("POST", "/connect_links", write=True, json=_link_options(redirect_url, reason, send_to))
        link = ConnectLink._from_link(payload, client=self._client, user=self._call_scope())
        if self._raw is not None:
            # The newest open link is the connection's (as its next read would say); unloaded, that read says it.
            self._raw = {**self._raw, "connect_link": {"id": payload.get("id"), "url": link.url,
                                                       "expires_at": payload.get("expires_at"),
                                                       "operation_id": link._known("id")}}
        return link

    @synced
    async def request(
        self, *, reason: Optional[str] = None, send_to: Any = "user", redirect_url: Optional[str] = None,
    ) -> "ConnectLink":
        """Ask the user (or ``send_to``) to connect it: a new connect link, emailed. A
        connection of your account's own has no user: send it to ``"owner"`` (your
        account's owner) or an email.

        Returns:
            The link, already sent: ``delivered_via`` says where it went, and
            ``.wait()`` on it returns the connected ``Connection``.

        Usage::

            gmail = noclick.Connection.from_name("gmail", user="user_42")
            if gmail.refresh().status == "disconnected":
                link = gmail.request(reason="Gmail stopped working. Reconnect it to keep your summaries coming.")
                print(link.delivered_via)   # ['email']
        """
        return await self.connect_link.aio(redirect_url=redirect_url, reason=reason, send_to=send_to)

    @synced
    async def wait(self, timeout: Optional[float] = None) -> "Connection":
        """Block until an account is connected (returns at once when it is). It
        follows the connection, not one link: an account connected through any
        of its links ends the wait, and a link that lapses after a fresh one was
        made (``connect_link()`` or ``request()``, from anywhere) hands the wait
        to the fresh one. Raises ``noclick.OperationExpired`` when the open link
        lapses with no fresh one, or ``noclick.OperationTimeout`` after
        ``timeout`` seconds.

        Returns:
            This connection, ``connected``. After a wait it's reloaded, so ``account``
            names the account when the provider says who it is.

        Usage:
            Wait in a background job, not while a web request is open::

                gmail = noclick.Connection.from_name("gmail", user="user_42")
                gmail.wait(timeout=3600)
                print(gmail.account)   # ana@example.com

            If the link lapses first, send a fresh one and keep waiting::

                gmail = noclick.Connection.from_name("gmail", user="user_42")
                try:
                    gmail.wait()
                except noclick.OperationExpired:
                    gmail.request(reason="to send your weekly summaries")
                    gmail.wait()
        """
        loop = asyncio.get_running_loop()
        deadline = None if timeout is None else loop.time() + timeout
        raw, lapsed = await self._ensure(), None
        while raw.get("status") != "connected":
            link = raw.get("connect_link")
            if not link:
                if lapsed is not None:
                    raise lapsed
                raise InvalidRequest(
                    f"The '{raw['name']}' connection has no open connect link to wait on.",
                    next_step="Create one with connection.connect_link() and send it to the user.",
                )
            remaining = None if deadline is None else deadline - loop.time()
            window = _LONG_POLL_S if remaining is None else max(0.0, min(_LONG_POLL_S, remaining))
            operation = Operation._new(hints={"id": link["operation_id"], "kind": "credential.connect"},
                                       client=self._client, user=self._call_scope())
            try:
                await operation.wait.aio(timeout=window)
            except OperationTimeout:
                if remaining is not None and remaining <= _LONG_POLL_S:
                    raise
            except (OperationExpired, OperationCanceled) as ended:
                lapsed = ended  # this link ended unused; the connection says what's open now
            raw = self._raw = await self._load()
        return self

    @synced
    async def import_(self, data: Dict[str, Any], *, credential_type: Optional[str] = None) -> "Connection":
        """Replace the connection's credential with one you hold (a rotated
        key), validated and probed first. ``credential_type``, when the
        integration takes more than one, is one of its ``credential_types``
        (``Connection.integrations()``).

        Returns:
            This connection, holding the new key, with the probe's ``verification``.
            The key it replaced is deleted.

        Usage:
            Rotate a key::

                crm = noclick.Connection.from_name("crm", user="user_42")
                crm.import_({"api_key": "..."})
                print(crm.status, crm.verification)

            Or bring your own key for a service whose operations need no account: a connection
            named after it runs its refs (``"exa.search"``) on your key instead of NoClick's::

                exa = noclick.Connection.from_name("exa", integration="exa", create_if_missing=True)
                exa.import_({"api_key": "..."})
                print(exa.verification)
        """
        self._raw = await self._act("POST", "/import", write=True, json=compact(data=data, credential_type=credential_type))
        return self

    # --- acting ----------------------------------------------------------

    @synced
    async def run(self, operation: str, arguments: Optional[Dict[str, Any]] = None, *,
                  approval_id: Optional[str] = None) -> Any:
        """Run one of the integration's operations in this account. An operation
        that needs no account (``needs_account`` False in ``operations()``) runs
        on NoClick's key while the connection is pending, and needs no connection
        at all through ``noclick.run``; any other raises
        ``noclick.NeedsConnection`` until it's connected and ``noclick.CredentialDisconnected``
        once revoked (both carry ``connect_url``). A connection holding your own
        key runs every operation on it. Policy may raise
        ``noclick.PolicyDenied`` or ``noclick.ApprovalRequired`` (retry with its
        ``approval_id=`` once ``.operation.wait()`` is ``True``). When the service
        refuses the call, it raises ``noclick.UpstreamError`` in the service's own
        words, with its HTTP status in ``upstream_status``.

        Returns:
            The operation's data, as plain data (what the service answered).

        Usage:
            Run an operation in the user's account::

                gmail = noclick.Connection.from_name("gmail", user="user_42")
                gmail.run("send_email_message", {
                    "to": ["ana@example.com"],
                    "subject": "Your weekly summary",
                    "body": "Three invoices were paid this week.",
                })

            A pending connection runs the operations that need no account at once, on NoClick's key::

                exa = noclick.Connection.from_name("exa", integration="exa", create_if_missing=True)
                results = exa.run("search", {"query": "invoice automation for small businesses"})

            If nothing is connected yet, send the user the link and retry once they've connected::

                gmail = noclick.Connection.from_name("gmail", user="user_42")
                args = {"to": ["ana@example.com"], "subject": "Your weekly summary", "body": "..."}
                try:
                    gmail.run("send_email_message", args)
                except noclick.NeedsConnection as err:
                    notify_user(err.connect_url)
                    gmail.wait()
                    gmail.run("send_email_message", args)

            When your policy holds the call for a person's approval, wait for it and
            repeat the identical call with the approval's id::

                gmail = noclick.Connection.from_name("gmail", user="user_42")
                args = {"to": ["ana@example.com"], "subject": "Your weekly summary", "body": "..."}
                try:
                    gmail.run("send_email_message", args)
                except noclick.ApprovalRequired as pending:
                    if pending.operation.wait():
                        gmail.run("send_email_message", args, approval_id=pending.approval_id)
        """
        body = compact(arguments=arguments or {}, approval_id=approval_id)
        response = await self._act("POST", f"/operations/{operation}/run", json=body)
        return response.get("result") if isinstance(response, dict) and "result" in response else response

    @synced
    async def lookup(
        self,
        field: str,
        arguments: Optional[Dict[str, Any]] = None,
        *,
        search: Optional[str] = None,
        page_token: Optional[str] = None,
    ) -> LookupOptions:
        """List the allowed values of an ID-like field (channels, repos, sheets) in this account.

        Returns:
            One page of options, each with a ``value`` to pass and a ``label`` to show;
            ``next_page_token`` is set when there are more.

        Usage:
            Fill a picker from the user's own Slack::

                slack = noclick.Connection.from_name("slack", user="user_42")
                for option in slack.lookup("channel", search="gen"):
                    print(option.value, option.label)

            A lookup that depends on another argument (a sheet inside a spreadsheet)
            takes it in ``arguments``; pass ``next_page_token`` back as ``page_token`` for more::

                sheets = noclick.Connection.from_name("sheets", user="user_42")
                spreadsheet = {"spreadsheet_id": "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"}
                tabs = sheets.lookup("sheet_name", spreadsheet)
                if tabs.next_page_token:
                    more = sheets.lookup("sheet_name", spreadsheet, page_token=tabs.next_page_token)
        """
        body = compact(field=field, arguments=arguments or None, search=search, page_token=page_token)
        response = await self._act("POST", "/lookup", json=body) or {}
        options = LookupOptions(
            LookupOption(opt.get("value"), opt.get("label"), opt) for opt in response.get("options") or []
        )
        options.next_page_token = response.get("next_page_token")
        return options

    @synced
    async def usage(self, model: Optional[str] = None, *, fresh: bool = False) -> PlanUsage:
        """How much of a Claude or ChatGPT plan is used.

        Args:
            model: Only the windows that can stop this model (``"claude-opus-5-5"``): a per-model window of
                another model is left out. None: every window.
            fresh: Ask the provider when the last reading is a few minutes old (2 for ChatGPT, 5 for Claude);
                else the last reading NoClick kept, whether a provider's or what a harness reported after a turn.

        Returns:
            Its ``state`` (``ok``, ``near`` from 80% used, ``used_up``, ``unknown``), its ``windows``, the one that
            stops it first (``tightest``), when a used-up plan runs again (``available_at``) and what to do meanwhile
            (``next_steps``). Raises ``InvalidRequest`` for a connection that isn't a plan.

        Usage::

            plan = noclick.Connection.from_id("credential:3f2a...")
            used = plan.usage(model="claude-opus-5-5", fresh=True)
            print(used.state, used.tightest.label, used.tightest.left)   # near  5-hour  0.09
        """
        raw = await self._act("GET", "/usage", params=compact(model=model, fresh="true" if fresh else None))
        return PlanUsage._from(raw)

    @synced
    async def verify(self) -> Optional[Verification]:
        """Re-check the account against the provider. Each check asks the provider, so an
        account makes at most 20 a minute (``noclick.RateLimited`` past them).

        Returns:
            The provider's verdict, also kept as ``verification``: ``reachable`` is
            ``True`` when it accepted the account, ``False`` when it refused it, and
            ``None`` when NoClick can't tell; ``message`` says what was found, and
            ``samples``, ``noun``, ``total``, ``account_label`` and ``error`` what
            the provider showed or said.

        Usage::

            gmail = noclick.Connection.from_name("gmail", user="user_42")
            check = gmail.verify()
            print(check.reachable, check.message)   # True  Signed in as ana@example.com.
        """
        self._raw = await self._act("POST", "/verify") or {}
        return Verification._from(self._raw.get("verification"))

    @synced
    async def require_approval(self, *operations: str) -> "Connection":
        """From now on its owner approves each call of these operations, wherever
        it runs: your code, agents, and the app's workflows. ``"*"`` means every
        operation. It only ever adds to ``approval_operations``; lifting one is
        done in the app. On one shared with your account, ``noclick.PermissionDenied``.

        Returns:
            The connection, with its ``approval_operations``.

        Usage::

            gmail = noclick.Connection.from_name("gmail")
            gmail.require_approval("send_email_message", "delete_message")
            print(gmail.approval_operations)   # ['delete_message', 'send_email_message']
        """
        self._raw = await self._act("POST", "/require_approval", json={"operations": list(operations)}) or {}
        return self

    @synced
    async def rename(self, name: str) -> "Connection":
        """Rename an account connected in the app (``origin`` ``app``): the name your
        account and the app see, which nothing finds it by. Its owner renames it, or someone
        it's shared with to edit (``noclick.PermissionDenied`` otherwise). A named
        connection's name is how code finds it, so it isn't renamed (``noclick.InvalidRequest``).

        Returns:
            The connection, with its new ``name``.

        Usage::

            inbox = noclick.Connection.get("credential:...")
            inbox.rename("Sales inbox")
            print(inbox.name)   # Sales inbox
        """
        self._raw = await self._act("PATCH", "", write=True, json={"name": name}) or {}
        return self

    @synced
    async def mark_test_account(self, test_account: bool = True) -> "Connection":
        """Mark it as a test account (or, with ``False``, not one). An app's preview only reads
        through a connection; through a test account it writes as well, as production does. Only
        the account that connected it marks it (``noclick.PermissionDenied`` on one shared with
        yours), and it must hold an account (``noclick.InvalidRequest`` while pending).

        Returns:
            The connection, with ``test_account`` set.

        Usage::

            slack = noclick.Connection.from_name("slack-sandbox")
            slack.mark_test_account()
            print(slack.test_account)   # True
        """
        self._raw = await self._act("POST", "/test_account", json={"test_account": test_account}) or {}
        return self

    @synced
    async def token(self) -> Token:
        """Mint a fresh OAuth access token for calling the provider yourself. A model
        provider's connection never hands out its key or plan token
        (``noclick.PermissionDenied``).

        Returns:
            The access token, its ``token_type`` and when it ``expires_at``; never a
            refresh token or an API key.

        Usage::

            gmail = noclick.Connection.from_name("gmail", user="user_42")
            token = gmail.token()
            headers = {"Authorization": f"{token.token_type} {token.access_token}"}
        """
        raw = await self._act("POST", "/token")
        return Token(raw["access_token"], raw.get("token_type"), parse_time(raw.get("expires_at")), raw)

    @synced
    async def delete(self) -> None:
        """Delete the connection, revoking its account at the provider where possible.

        Usage::

            noclick.Connection.from_name("gmail", user="user_42").delete()
        """
        await self._act("DELETE", "", write=True)


@dataclass(frozen=True)
class ConnectionOperations:
    """Some of a connection's operations as tools (``connection.only(...)``), with
    the arguments ``bind(...)`` fixed."""

    connection: Connection
    operations: List[str]
    #: The arguments NoClick fills on every call, out of the model's reach.
    bindings: Dict[str, Any] = dc_field(default_factory=dict)

    def bind(self, **arguments: Any) -> "ConnectionOperations":
        """Fix arguments of these operations: a bound parameter leaves the tool's schema,
        so the model never sees or sets it, and NoClick fills it on every call. A value may
        name the user the call acts for: ``{{user.id}}``, ``{{user.email}}``,
        ``{{user.name}}`` or ``{{user.metadata.<key>}}``. A bound value always wins,
        over what a model passes through in an operation's free-form parameters too; a
        tool whose binding can't be filled (a user with no email, say) isn't offered that
        turn. Policy judges the call's final arguments. Every operation listed must take
        each bound parameter. Works wherever ``tools`` do: agents, toolkits and hosted MCP
        servers. Sends nothing.

        Returns:
            A new ref with these arguments bound on top of any bound before.

        Usage:
            An assistant that can email only its own user, whatever a message it reads says::

                with noclick.as_user("user_42"):
                    gmail = noclick.Connection.from_name("gmail", integration="gmail", create_if_missing=True)
                    assistant = noclick.Agent.from_name(
                        "assistant",
                        create_if_missing=True,
                        instructions="You summarize the user's inbox and email them the summary.",
                        tools=[gmail.only("fetch_emails_from_inbox"), gmail.only("send_email_message").bind(to="{{user.email}}")],
                    )

            Pin a shared account connection to each user's own records::

                hubspot = noclick.Connection.from_name("hubspot")
                crm = hubspot.only("search_contacts").bind(owner_id="{{user.metadata.hubspot_owner}}")
                toolkit = noclick.Toolkit([crm, "search"])
        """
        return ConnectionOperations(self.connection, list(self.operations), {**self.bindings, **bound_arguments(arguments)})


async def _connection_ref(connection: Connection, scope: Any) -> str:
    """Its name where the tools run in its own scope (one connected in the app by its id,
    ``credential:<id>``); ``connection:<id>`` from another scope, another user's or the
    account's."""
    raw = await connection._ensure()
    if raw.get("origin") == "app":
        return raw["id"]
    if connection._scope == scope or raw.get("user_id") == await user_ref(scope):
        return raw["name"]
    return f"connection:{raw['id']}"


def _wire_entry(tool: Any) -> bool:
    """A wire entry as ``agent.tools`` reads it back, so tools round-trip."""
    return isinstance(tool, dict) and (
        (isinstance(tool.get("tool"), str) and isinstance(tool.get("bind"), dict))
        or (isinstance(tool.get("human"), dict) and isinstance(tool.get("tools"), list))
    )


async def tool_refs(tools: Any, *, scope: Any = AMBIENT) -> Optional[List[Any]]:
    """The wire refs for ``tools=`` that run in ``scope`` (a user, or None for the
    account): names, ``"name.operation"`` strings, ``Connection`` objects and
    ``connection.only(...)`` (a lazy ``create_if_missing`` connection is created
    first; one from another scope is ``"connection:<id>"``), a ``Database`` or
    ``db.only(...)`` (``"database:<id>"``, ``"database:<id>.query"``), a ``Toolkit``,
    or the ``agents`` capability (``noclick.Agents``: ``"agents"``, ``"agents.spawn"``).
    A string names a connection in ``scope``, else an integration's operations that need
    no account (on NoClick's key), so ``"exa.search"`` needs no connection. Anything else
    that says its own wire entries (``_tool_refs(scope)``: a string, or an object for what a
    string can't say) is taken as it says, and so is an entry read back from ``agent.tools``
    (``{tool, bind}``, ``{human, tools}``)."""
    if tools is None:
        return None
    scope = resolve_scope(scope)
    if isinstance(tools, (str, Connection, ConnectionOperations, Database)) or hasattr(tools, "_tool_refs"):
        tools = [tools]
    elif not isinstance(tools, (list, tuple)) and hasattr(tools, "refs"):  # a Toolkit
        tools = tools.refs
    refs: List[Any] = []
    for tool in tools:
        if isinstance(tool, str):
            refs.append(tool)
        elif isinstance(tool, Connection):
            refs.append(await _connection_ref(tool, scope))
        elif isinstance(tool, ConnectionOperations):
            base = await _connection_ref(tool.connection, scope)
            refs.extend(tool_entries(base, tool.operations, tool.bindings))
        elif isinstance(tool, Database):
            refs.append(f"database:{await ref_id(tool)}")
        elif hasattr(tool, "_tool_refs"):  # db.only(...), a bucket, a person, ...
            refs.extend(await tool._tool_refs(scope))
        elif _wire_entry(tool):
            refs.append(dict(tool))
        else:
            raise TypeError(
                f"A tool is a Connection, a Database, or a name like 'gmail' or 'gmail.send_email_message', not {tool!r}"
            )
    return refs


async def model_connection_ref(connection: Any, *, scope: Any = AMBIENT) -> Optional[str]:
    """The wire ``model_connection`` for an agent in ``scope``: a name as given, or a ``Connection``
    (a lazy ``create_if_missing`` one is created first; one from another scope is sent as
    ``connection:<id>``, shared under the rule for shared tools: only a key acting for the whole
    account may set it, and a connection holding a person's plan is never shared; invite-only beta)."""
    if connection is None or isinstance(connection, str):
        return connection
    if isinstance(connection, Connection):
        return await _connection_ref(connection, resolve_scope(scope))
    raise TypeError(f"model_connection is a Connection or its name, not {connection!r}")


def _operation_ref(ref: Any) -> str:
    """``ref`` when it names one operation, ``"name.operation"`` (the server splits at the first dot)."""
    if not isinstance(ref, str):
        raise TypeError(f"noclick.run() takes a ref like 'exa.search', not {type(ref).__name__}")
    name, _, operation = ref.partition(".")
    if not name or not operation:
        raise InvalidRequest(
            f"noclick.run() runs one operation, named 'name.operation'; {ref!r} names none.",
            next_step="Name the connection or integration and the operation: 'exa.search', 'gmail.send_email_message'.",
            details={"field": "ref"},
        )
    return ref


@synced
async def run(
    ref: str,
    arguments: Optional[Dict[str, Any]] = None,
    *,
    approval_id: Optional[str] = None,
    user: Any = AMBIENT,
    client: Optional[Client] = None,
) -> Any:
    """Run one operation by its ref, ``"name.operation"``, as ``tools=`` names it. ``name``
    is a connection in the scope the call acts for (the user's, else the account's), else
    an integration whose operation needs no account, which then runs on NoClick's key with
    no connection at all. A connection named like the integration (``exa``, holding your
    own key) wins, so the same ref then runs on your key. An account connected in the app
    is ``"credential:<id>.operation"``.

    It raises like ``connection.run``: ``noclick.NeedsConnection`` (or
    ``noclick.CredentialDisconnected``) with the ``connect_url`` when the connection has no
    working account, ``noclick.InvalidRequest`` when the operation needs an account and no
    connection has that name, ``noclick.NotFound`` when ``name`` is neither a connection nor
    an integration, ``noclick.PolicyDenied`` or ``noclick.ApprovalRequired`` (retry with
    its ``approval_id=`` once ``.operation.wait()`` is ``True``), and ``noclick.UpstreamError``
    when the service refuses the call (its own words, its HTTP status in ``upstream_status``).

    Returns:
        The operation's data, as plain data (what the service answered).

    Usage:
        Search the web with nothing to create or connect, on NoClick's key::

            results = noclick.run("exa.search", {"query": "invoice automation for small businesses"})

        A name that is a connection runs through it, here the user's own Gmail::

            with noclick.as_user("user_42"):
                noclick.run("gmail.send_email_message", {
                    "to": ["ana@example.com"],
                    "subject": "Your weekly summary",
                    "body": "Three invoices were paid this week.",
                })

        Bring your own key: a connection named ``exa`` holding it takes over the same ref::

            noclick.Connection.create("exa", credential_type="exa_api_key", data={"api_key": "..."})
            results = noclick.run("exa.search", {"query": "invoice automation for small businesses"})

        When your policy holds the call for a person's approval, wait for it and repeat the
        identical call with the approval's id::

            args = {"to": ["ana@example.com"], "subject": "Your weekly summary", "body": "..."}
            try:
                noclick.run("gmail.send_email_message", args, user="user_42")
            except noclick.ApprovalRequired as pending:
                if pending.operation.wait():
                    noclick.run("gmail.send_email_message", args, user="user_42", approval_id=pending.approval_id)
    """
    body = compact(ref=_operation_ref(ref), arguments=arguments or {}, approval_id=approval_id)
    response = await resolve_client(client).request("POST", "/v1/run", json=body, user=user)
    if not isinstance(response, dict) or "result" not in response:
        raise Error("The response is missing `result`.", details={"field": "result"})
    return response["result"]


_CONNECT_KINDS = ("credential.connect",)


class ConnectLink(Operation):
    """A connect page URL that is also the operation tracking it."""

    url: str
    expires_at: Any
    #: The connection the link fills.
    connection: Optional[str]
    #: Channels the link went out on when ``send_to`` was set (``["email"]``); empty otherwise.
    delivered_via: List[str]
    #: Channels that failed, each with a ``reason``: send the link yourself.
    undelivered: List[Dict[str, Any]]

    @synced
    @classmethod
    async def list(cls, *, limit: Optional[int] = None, **filters: Any) -> List[Operation]:
        """Connect-link operations (kind ``credential.connect``), newest first; takes
        ``Operation.list``'s filters except ``kind``. Rows are operations: the link's
        URL is only in the response that created it (and on its pending connection).

        Returns:
            Every matching operation (or the first ``limit``), fetched page by page;
            ``wait()`` on one returns the connected ``Connection``.

        Usage::

            for op in noclick.ConnectLink.list(status="awaiting_human", user_filter=noclick.ALL_USERS):
                print(op.user_id, op.summary_text, op.created_at)   # ... Connect gmail ...
        """
        return await Operation.list.aio(limit=limit, **_with_kinds(filters, _CONNECT_KINDS, "ConnectLink.list"))

    @synced
    @classmethod
    async def list_page(cls, *, cursor: Optional[str] = None, limit: Optional[int] = None, **filters: Any) -> Page:
        """One page of connect-link operations; pass ``next_cursor`` back as ``cursor``.

        Returns:
            A page whose ``data`` holds the operations and whose ``next_cursor`` is ``None`` on the last page.

        Usage::

            page = noclick.ConnectLink.list_page(status="expired", limit=50)
            while True:
                for op in page.data:
                    print(op.summary_text, op.updated_at)
                if page.next_cursor is None:
                    break
                page = noclick.ConnectLink.list_page(status="expired", limit=50, cursor=page.next_cursor)
        """
        return await Operation.list_page.aio(
            cursor=cursor, limit=limit, **_with_kinds(filters, _CONNECT_KINDS, "ConnectLink.list_page"),
        )

    @synced
    @classmethod
    async def summary(cls, **filters: Any) -> OperationSummary:
        """Count connect-link operations; takes ``Operation.summary``'s filters except ``kind``.

        Returns:
            The ``total`` that match and a count for every status in ``by_status``.

        Usage:
            How many of last week's links were used, and how many lapsed::

                from datetime import datetime, timedelta, timezone

                week_ago = datetime.now(timezone.utc) - timedelta(days=7)
                counts = noclick.ConnectLink.summary(created_after=week_ago, user_filter=noclick.ALL_USERS)
                print(counts.total, counts.by_status["succeeded"], counts.by_status["expired"])
        """
        return await Operation.summary.aio(**_with_kinds(filters, _CONNECT_KINDS, "ConnectLink.summary"))

    @classmethod
    def _from_link(cls, payload: Dict[str, Any], *, client: Optional[Client], user: Any) -> "ConnectLink":
        operation = payload.get("operation")
        hints: Dict[str, Any] = {"kind": "credential.connect"}
        raw = operation if isinstance(operation, dict) else None
        if isinstance(operation, str):
            hints["id"] = operation
        link = cls._new(raw=raw, hints=hints, client=client, user=user)
        link.url = payload.get("url")
        link.expires_at = parse_time(payload.get("expires_at"))
        link.connection = payload.get("connection")
        delivery = payload.get("delivery") or {}
        link.delivered_via = list(delivery.get("delivered_via") or [])
        link.undelivered = list(delivery.get("undelivered") or [])
        return link

    def _repr_parts(self) -> list:
        url = self.console_url
        parts = [f"url={self.url!r}", f"operation={self._known('id')!r}", f"status={self._known('status')!r}"]
        return parts + ([f"console_url={url!r}"] if url else [])

    def __str__(self) -> str:
        return self.url or ""


def _read_connection(result: Any, op: Operation) -> Connection:
    raw = result.get("connection", result) if isinstance(result, dict) else result
    if isinstance(raw, str):
        return Connection.from_id(raw, client=op._client, user=op._scope)
    return Connection._new(raw=raw, client=op._client, user=op._scope)


register_result("credential.connect", _read_connection)
