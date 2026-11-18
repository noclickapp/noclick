"""Users: the people and companies your product acts for, each known by your own id."""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Tuple, Union

from ._client import Client, path_segment, resolve_client
from ._object import UNSET, Page, _Object, compact, field, list_all, list_page, parse_time
from ._scope import check_user_id
from ._sync import synced
from .exceptions import Conflict, NotFound
from .export import ExportBundle
from .operation import Operation, register_result
from .session import Session

if TYPE_CHECKING:
    from .human import Human


@dataclass(frozen=True)
class PhoneVerification:
    """A verification code on its way to the user's phone."""

    phone: Optional[str]
    status: Optional[str]
    expires_at: Any
    raw: Dict[str, Any] = dc_field(repr=False)


@dataclass(frozen=True)
class Spending:
    """Whether a user can spend right now, as ``user.spending`` reads it. A
    ``paused`` user can't start anything that costs money until you call
    ``resume_spending()``; ``message`` and ``action`` (a ``(label, url)`` pair) are what
    NoClick tells them meanwhile, ``since`` is when you paused them, ``held`` how many
    of their messages wait to run when you resume, and ``paused_by`` the key that
    paused them (``"console"`` from the console)."""

    paused: bool
    message: Optional[str]
    action: Optional[Tuple[str, str]]
    since: Any
    held: int
    paused_by: Optional[str]
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "Spending":
        action = raw.get("action") or None
        return cls(
            bool(raw.get("paused")), raw.get("message"), (action["label"], action["url"]) if action else None,
            parse_time(raw.get("since")), int(raw.get("held") or 0), raw.get("paused_by"), raw,
        )


def _action_wire(action: Any) -> Optional[Dict[str, str]]:
    if action is None:
        return None
    if not (isinstance(action, (tuple, list)) and len(action) == 2 and all(isinstance(part, str) for part in action)):
        raise TypeError(f"action is a (label, url) pair, like ('Top up', 'https://...'), not {action!r}")
    return {"label": action[0], "url": action[1]}


def _read_export(result: Any, op: Operation) -> ExportBundle:
    return ExportBundle._from(result)


register_result("user.export", _read_export)


def _path(user_id: str, rest: str = "") -> str:
    return f"/v1/users/{path_segment(user_id)}{rest}"


class User(_Object):
    """One of your users, a person or a company, known by your own id for it.
    ``User.from_id("user_42", create_if_missing=True)`` is lazy: nothing is sent
    until the user is used."""

    _repr_keys = ("id", "status")

    id: str = field("id", doc="Your id for the user.")
    name: Optional[str] = field("name")
    email: Optional[str] = field("email")
    phone: Optional[str] = field("phone")
    phone_verified_at: Any = field("phone_verified_at", parse_time, doc="When the phone was proven (None if never).")
    spend_cap_usd_per_month: Optional[float] = field("spend_cap_usd_per_month")
    metadata: Optional[Dict[str, Any]] = field("metadata")
    timezone: Optional[str] = field(
        "timezone",
        doc="Their IANA timezone, like ``Europe/Lisbon``: agents acting for them tell "
            "the time in it, and ``Cron(tz=\"user\")`` fires in it. None: UTC.",
    )
    status: str = field("status")
    created_at: Any = field("created_at", parse_time)
    spending: Optional[Spending] = field(
        "spending", Spending._from,
        doc="Whether they can spend right now: paused or not, what NoClick tells them, and how many of their "
            "messages wait (see ``pause_spending``).",
    )

    def _init(self, **kwargs: Any) -> None:
        self._create_with: Optional[Dict[str, Any]] = None
        super()._init(**kwargs)

    # User routes are account-level; they never carry a user header.
    def _call_scope(self) -> Any:
        return None

    # --- construction ----------------------------------------------------

    @synced
    @classmethod
    async def create(
        cls,
        id: str,
        *,
        name: Optional[str] = None,
        email: Optional[str] = None,
        phone: Optional[str] = None,
        spend_cap_usd_per_month: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
        timezone: Optional[str] = None,
        allow_existing: bool = False,
        idempotency_key: Optional[str] = None,
        client: Optional[Client] = None,
    ) -> "User":
        """Create a user, keyed by your own ``id`` for it: 1 to 255 printable ASCII
        characters, without spaces or ``/``, other than ``all`` and ``none``. An id
        another live user has raises ``noclick.Conflict`` (its ``existing_id`` is
        that id), or with ``allow_existing=True`` returns that user, as it is: its details
        don't change. ``timezone`` is where they are, as an IANA
        name (``"America/New_York"``): every turn of an agent acting for them starts
        with the date and time there, unless the agent has a ``timezone`` of its own.

        Returns:
            The new user, loaded.

        Usage:
            Create one when a user signs up, keyed by your own id for them::

                user = noclick.User.create("user_42", name="Ana Lima", email="ana@example.com")
                print(user.id)   # user_42

            If the user may already exist, take it as it is::

                user = noclick.User.create("user_42", allow_existing=True)

            Say where they are, so their agents know what "tomorrow morning" means::

                user = noclick.User.create("user_42", email="ana@example.com", timezone="America/Sao_Paulo")
        """
        body = compact(
            id=check_user_id(id), name=name, email=email, phone=phone,
            spend_cap_usd_per_month=spend_cap_usd_per_month, metadata=metadata, timezone=timezone,
        )
        raw = await cls._create_named("/v1/users", body, allow_existing=allow_existing, user=None, client=client,
                                      key="id", existing_path=_path, idempotency_key=idempotency_key)
        return cls._new(raw=raw, client=client, user=None)

    @classmethod
    def from_id(
        cls,
        id: str,
        *,
        create_if_missing: bool = False,
        name: Any = UNSET,
        email: Any = UNSET,
        phone: Any = UNSET,
        spend_cap_usd_per_month: Any = UNSET,
        metadata: Any = UNSET,
        timezone: Any = UNSET,
        client: Optional[Client] = None,
    ) -> "User":
        """A lazy reference to the user with your ``id``. Given fields, it gets the user and sets
        the ones you pass, on every run: an existing user whose ``name``, ``email``, ``phone``,
        ``spend_cap_usd_per_month``, ``metadata`` or ``timezone`` differ gets yours. A field you
        leave out is never changed, and ``None`` clears one, as in ``update()``.
        ``create_if_missing=True`` creates it with the given fields when there's none; without
        it, a missing user raises ``noclick.NotFound``.

        Returns:
            A user that loads, or is created, the first time it's used. Nothing is sent yet.

        Usage:
            Refer to a user by your id without a request::

                user = noclick.User.from_id("user_42")
                print(user.status)   # loads it now; noclick.NotFound if there's none

            Or create it the first time it's used, so sign-up needs no extra call.
            Two requests that race both get the same user::

                user = noclick.User.from_id("user_42", create_if_missing=True, email="ana@example.com")
                with noclick.as_user(user):
                    agent = noclick.Agent.from_name("assistant")

            Run at every sign-in, it sets the user's details to yours::

                user = noclick.User.from_id("user_42", create_if_missing=True, name="Ana Lima", email="ana@example.com")
                print(user.email)   # ana@example.com, even if it was another address before

            Pass the timezone your product already knows::

                user = noclick.User.from_id("user_42", create_if_missing=True, timezone="Europe/Lisbon")
                print(user.timezone)
        """
        user = cls._new(hints={"id": check_user_id(id)}, client=client, user=None)
        user._define({"id": id, **{k: v for k, v in dict(
            name=name, email=email, phone=phone, spend_cap_usd_per_month=spend_cap_usd_per_month,
            metadata=metadata, timezone=timezone,
        ).items() if v is not UNSET}}, create_if_missing=create_if_missing, key="id")
        return user

    @synced
    @classmethod
    async def get(cls, id: str, *, client: Optional[Client] = None) -> "User":
        """Load a user by your id now; an unknown id raises ``noclick.NotFound``.

        Returns:
            The user, loaded.

        Usage::

            user = noclick.User.get("user_42")
            print(user.name, user.status)
        """
        user = cls.from_id(id, client=client)
        await user._ensure()
        return user

    @synced
    @classmethod
    async def list(
        cls, *, q: Optional[str] = None, status: Optional[str] = None, spending: Optional[str] = None,
        limit: Optional[int] = None, client: Optional[Client] = None,
    ) -> List["User"]:
        """Your users, newest first (or the first ``limit``). ``q`` is a
        case-insensitive prefix of the id, name or email; ``status``
        ``active`` or ``suspended``; ``spending`` ``"paused"`` or ``"active"``, to find the users
        whose spending you've paused (say, to check them against your billing after an outage).

        Returns:
            Every matching user, fetched page by page.

        Usage::

            for user in noclick.User.list(q="ana"):
                print(user.id, user.email)

            suspended = noclick.User.list(status="suspended", limit=20)
            paused = noclick.User.list(spending="paused")
        """
        return await list_all(
            "/v1/users", lambda raw, _scope: cls._new(raw=raw, client=client, user=None),
            params={"q": q, "status": status, "spending": spending}, user=None, limit=limit, client=client,
        )

    @synced
    @classmethod
    async def list_page(
        cls, *, cursor: Optional[str] = None, limit: Optional[int] = None, q: Optional[str] = None,
        status: Optional[str] = None, spending: Optional[str] = None, client: Optional[Client] = None,
    ) -> Page:
        """One page of users; pass ``next_cursor`` back as ``cursor``. Takes ``list``'s filters.

        Returns:
            A page whose ``data`` holds the users and whose ``next_cursor`` is ``None`` on the last page.

        Usage::

            page = noclick.User.list_page(limit=50)
            while True:
                for user in page.data:
                    print(user.id)
                if page.next_cursor is None:
                    break
                page = noclick.User.list_page(limit=50, cursor=page.next_cursor)
        """
        return await list_page(
            "/v1/users", lambda raw, _scope: cls._new(raw=raw, client=client, user=None),
            params={"q": q, "status": status, "spending": spending}, user=None, cursor=cursor, limit=limit,
            client=client,
        )

    @property
    def console_url(self) -> Optional[str]:
        """This user in the developer console (None off the hosted API)."""
        return self._api.console_url("users", self.id)

    # --- hydration -------------------------------------------------------

    async def _load(self) -> Dict[str, Any]:
        user_id = self._known("id")
        try:
            found = await self._request("GET", _path(user_id))
        except NotFound:
            if not self._creates:
                raise
        else:
            return await self._converge(found)
        try:
            return await self._request("POST", "/v1/users", json=compact(**self._create_with))
        except Conflict as exc:  # created concurrently
            if not exc.existing_id:
                raise
            return await self._converge(await self._request("GET", _path(exc.existing_id)))

    async def _converge(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Set the fields ``from_id`` was given on an existing user."""
        if self._create_with is None:
            return raw
        changes = {k: v for k, v in self._create_with.items() if k != "id" and raw.get(k) != v}
        return await self._request("PATCH", _path(raw["id"]), json=changes) if changes else raw

    async def _user_ref(self) -> str:
        if self._create_with is not None:
            await self._ensure()  # created, or its fields set, before anything acts for it
        return self._known("id")

    # --- actions ---------------------------------------------------------

    @synced
    async def update(
        self,
        *,
        id: Any = UNSET,
        name: Any = UNSET,
        email: Any = UNSET,
        phone: Any = UNSET,
        spend_cap_usd_per_month: Any = UNSET,
        metadata: Any = UNSET,
        timezone: Any = UNSET,
    ) -> "User":
        """Change fields (``None`` clears one); a field you leave out is unchanged.
        A new ``id`` renames the user: everything it owns follows, and an id another
        user has raises ``noclick.Conflict``. A user acting for themselves may change
        their own ``timezone``, their session included (it may change nothing else).

        Returns:
            This user, updated.

        Usage:
            Change a user's details::

                user = noclick.User.from_id("user_42")
                user.update(name="Ana Lima-Souza", phone=None, spend_cap_usd_per_month=50)

            Move a user to a new id, say when your own ids change::

                user = noclick.User.from_id("user_42")
                user.update(id="acct_9f3a")
                print(user.id)   # acct_9f3a

            They moved: their agents' next turns and ``Cron(tz="user")`` schedules follow::

                user = noclick.User.from_id("user_42")
                user.update(timezone="Asia/Tokyo")
        """
        if id is not UNSET:
            check_user_id(id)
        changes = {
            k: v for k, v in dict(
                id=id, name=name, email=email, phone=phone,
                spend_cap_usd_per_month=spend_cap_usd_per_month, metadata=metadata, timezone=timezone,
            ).items() if v is not UNSET
        }
        # No read first: a user's session, which may change only its own timezone, can't read the user.
        self._raw = await self._request("PATCH", _path(await self._user_ref()), json=changes)
        return self

    @synced
    async def suspend(self) -> "User":
        """Stop all activity for this user: every call made for it then fails
        with ``noclick.PermissionDenied``, and its history stays readable.

        Returns:
            This user, now ``suspended``.

        Usage::

            user = noclick.User.from_id("user_42")
            user.suspend()
            print(user.status)   # suspended
        """
        raw = await self._ensure()
        self._raw = await self._request("POST", _path(raw["id"], "/suspend")) or {**raw, "status": "suspended"}
        return self

    @synced
    async def pause_spending(
        self, *, message: Optional[str] = None, action: Optional[Tuple[str, str]] = None,
    ) -> "User":
        """Stop everything that costs money for this user until ``resume_spending()``, and
        say what they can do about it. Call it from your billing when they run out (say, at a
        balance alert) or fall behind. ``message`` is what NoClick tells them, in your words,
        up to 500 characters; ``action`` is a ``(label, url)`` pair, your checkout or billing
        page, up to 40 characters and an ``https`` URL. Both may use ``{{user.id}}``,
        ``{{user.name}}``, ``{{user.email}}`` and ``{{user.metadata.<key>}}``, filled in now;
        a field this user lacks raises ``noclick.InvalidRequest``. Without ``message``, the
        default you set in the console (Settings, Paused spending) is used, and with no default
        either it raises ``noclick.InvalidRequest``; without ``action``, the default's button.

        While paused, a call your code makes for them raises ``noclick.SpendingPaused``; a
        message they send an agent (an email to its inbox, a post in their channel) is answered
        once per conversation with ``message`` and ``action`` and held, up to 24 hours, to run
        when you resume; a call to a number they reach hears ``message``; schedules, webhooks
        and app events for their agents are skipped. Work under way finishes the step it's on.
        What they already have keeps running and billing: pausing isn't cancelling. Reads
        still work. Pausing a paused user changes its message and action and keeps ``since``
        and what's held. Only a key acting for your whole account can pause or resume: never
        the user's own session.

        Returns:
            This user, with ``spending`` paused.

        Usage:
            Pause a user when their balance runs low, with your top-up page::

                user = noclick.User.from_id("user_42")
                user.pause_spending(
                    message="You've used your credits.",
                    action=("Top up", "https://acme.com/billing/top-up?user={{user.id}}"),
                )
                print(user.spending.paused, user.spending.since)

            Or with the message you set in the console::

                noclick.User.from_id("user_42").pause_spending()
        """
        raw = await self._ensure()
        body = compact(message=message, action=_action_wire(action))
        self._raw = await self._request("POST", _path(raw["id"], "/spending/pause"), json=body)
        return self

    @synced
    async def resume_spending(self) -> "User":
        """Let this user spend again, say once your billing has their payment. What was held
        for them runs now, in the order it arrived: each message as the turn it would have
        been, with when it arrived, so the agent knows it waited. Resuming a user who isn't
        paused changes nothing.

        Returns:
            This user, with ``spending`` no longer paused.

        Usage::

            user = noclick.User.from_id("user_42")
            held = user.spending.held
            user.resume_spending()
            print(f"Resumed; {held} held messages are running now")
        """
        raw = await self._ensure()
        self._raw = await self._request("POST", _path(raw["id"], "/spending/resume"))
        return self

    @synced
    async def delete(self, *, export: bool = False) -> Optional[Operation]:
        """Mark the user deleted, which frees its id for reuse. Nothing acts for
        them afterwards (invite-only beta): their connections' grants are
        revoked at each provider, their agents' triggers stop, their inboxes stop
        receiving mail and their phone numbers are released. What's kept is the
        record: operations, tool calls, conversations, usage and spend stay readable
        with ``user_filter``, and their databases, buckets, repos and files stay until
        you delete them. ``export=True`` packs up everything the user holds first,
        as ``export()`` does, and deletes the user once the export is stored; nothing
        is deleted if the export fails or is canceled. Only a call acting for the
        account deletes users.

        Returns:
            ``None``; with ``export=True``, an operation whose ``.wait()`` gives the
            ``ExportBundle`` once the user is deleted.

        Usage:
            Delete a user::

                noclick.User.from_id("user_42").delete()

            Or hand the user their data, then delete them::

                user = noclick.User.from_id("user_42")
                bundle = user.delete(export=True).wait()
                print(bundle.url, bundle.expires_at)
        """
        raw = await self._ensure()
        if export:
            payload = await self._request("POST", _path(raw["id"], "/export"), json={"delete_after": True})
            return Operation._from_payload(payload, client=self._client, user=None, kind="user.export", reader=_read_export)
        result = await self._request("DELETE", _path(raw["id"]))
        self._raw = result if isinstance(result, dict) and result.get("id") else {**raw, "status": "deleted"}
        return None

    @synced
    async def export(self) -> Operation:
        """Pack up everything the user holds, in forms that work without
        NoClick: their own agents' definitions as JSON, their conversations with
        any agent as JSON Lines transcripts, what agents remember about them as
        Markdown, their databases as SQL, their buckets' and volumes' files,
        their dicts and queues as JSON Lines, their repos as git bundles, their
        apps' settings, connections and secrets by name only (never a token or a
        value), and each phone number and domain with the call that moves it
        (``transfer_out``). The user keeps working; one export of a user runs at
        a time (another raises ``noclick.Conflict`` naming it).

        Returns:
            An operation whose ``.wait()`` gives the ``ExportBundle``: a zip ``url``
            valid until ``expires_at`` (7 days), its ``contents``, and
            ``remaining_dependencies``, what still runs on NoClick.

        Usage::

            user = noclick.User.from_id("user_42")
            bundle = user.export().wait()
            print(bundle.url, bundle.expires_at)
            for item in bundle.contents:
                print(item.kind, item.name, item.detail)
            print("Still on NoClick:", ", ".join(bundle.remaining_dependencies))
        """
        raw = await self._ensure()
        payload = await self._request("POST", _path(raw["id"], "/export"), json={})
        return Operation._from_payload(payload, client=self._client, user=None, kind="user.export", reader=_read_export)

    @synced
    async def verify_phone(self, *, phone: Optional[str] = None) -> PhoneVerification:
        """Text a verification code to the user's phone (or ``phone=``, which
        becomes its number); confirm it with ``check_phone(code)``.

        Returns:
            The number the code went to, and when the code expires.

        Usage::

            user = noclick.User.from_id("user_42")
            sent = user.verify_phone(phone="+14155550100")
            print(sent.phone, sent.expires_at)
        """
        raw = await self._ensure()
        response = await self._request(
            "POST", _path(raw["id"], "/phone/verify"), json=compact(phone=phone),
        ) or {}
        if response.get("object") == "user":
            self._raw = response
        return PhoneVerification(
            phone=response.get("phone") or phone or raw.get("phone"),
            status=response.get("status"),
            expires_at=parse_time(response.get("expires_at")),
            raw=response,
        )

    @synced
    async def check_phone(self, code: str) -> bool:
        """Check the code the user received. A wrong code raises
        ``InvalidRequest``, an expired one ``Expired``, and too many tries
        ``RateLimited``.

        Returns:
            ``True`` once the phone is verified; ``phone_verified_at`` is then set.

        Usage::

            user = noclick.User.from_id("user_42")
            try:
                user.check_phone("482913")
                print(user.phone_verified_at)
            except noclick.InvalidRequest as err:
                print(err.message)   # That code isn't right.
        """
        raw = await self._ensure()
        response = await self._request(
            "POST", _path(raw["id"], "/phone/check"), json={"code": str(code)},
        ) or {}
        user = response if response.get("object") == "user" else response.get("user")
        if isinstance(user, dict):
            self._raw = user
        if "verified" in response:
            return bool(response["verified"])
        return bool((user or {}).get("phone_verified_at"))

    @synced
    async def session(
        self,
        scopes: Union[str, Sequence[str]],
        *,
        ttl_s: Union[None, int, float, timedelta] = None,
    ) -> Session:
        """Mint a short-lived token that acts only as this user, with
        ``scopes`` (a subset of your key's: ``agents``, ``humans``,
        ``credentials:request``, ``credentials:use``, ``channels``, ``inbox``, ``ai``).
        ``ttl_s`` is at most 24h. Hand ``session.token`` to your frontend, or
        use ``noclick.Client.for_session(session)``. Revoking the minting key
        revokes its sessions.

        Returns:
            The session: its ``token``, the ``scopes`` it carries and when it expires.

        Usage:
            Mint one per page load on your server and hand the token to the browser::

                user = noclick.User.from_id("user_42")
                session = user.session(["agents", "humans"], ttl_s=3600)
                token = session.token   # for the browser; it acts only as this user

            Or act as the user from your own code, with only those scopes::

                client = noclick.Client.for_session(session)
                agent = noclick.Agent.from_name("assistant", client=client)
        """
        user_id = await self._user_ref()  # minted per page load: no GET unless it may need creating
        body = compact(
            scopes=[scopes] if isinstance(scopes, str) else list(scopes),
            ttl_s=int(ttl_s.total_seconds()) if isinstance(ttl_s, timedelta) else ttl_s,
        )
        response = await self._request("POST", _path(user_id, "/sessions"), json=body) or {}
        return Session(
            token=response.get("token"),
            id=response.get("id"),
            user_id=response.get("user_id") or user_id,
            scopes=list(response.get("scopes") or []),
            expires_at=parse_time(response.get("expires_at")),
            raw=response,
            base_url=self._api.base_url,
        )

    @property
    def human(self) -> "Human":
        """The person behind this user: ``user.human.approve("Send it?").wait()``."""
        from .human import Human

        return Human(user=self, client=self._client)
