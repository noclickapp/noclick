"""Browsers: a browser an agent drives, and profiles that keep a person's logins.

    profile = noclick.BrowserProfile.from_name("ana-work", create_if_missing=True, user="user_42")
    profile.login("https://portal.example.com", reason="to download your invoices").wait()

    with noclick.Browser.create(profile=profile, timeout_s=900) as browser:
        browser.goto("https://portal.example.com/invoices")
        result = browser.act("Download every invoice from September")
        print(result.summary)
    # closed on exit

A browser is Chromium in a sandbox, driven by a model that sees the page and
acts on it. NoClick solves the CAPTCHAs it can; when a page still needs a person
(a CAPTCHA it couldn't solve, a two-factor code), the browser parks, unbilled,
while that person finishes the step on a page NoClick sends them. A profile
keeps the sign-ins a person made once; when a site signs it out, the next
browser asks that person to sign in again the same way, and saves the new
sign-in. A profile counts as a credential, so it is never exported and only its
own user's browsers and agents use it.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Any, Dict, List, Literal, Optional, Union, overload
from urllib.parse import quote

from ._client import Client, resolve_client
from ._object import Page, _Object, compact, field, list_all, list_page, parse_time, ref_id
from ._sync import synced
from ._scope import AMBIENT, resolve_scope
from .exceptions import Conflict, NotFound
from .human import Human
from .operation import Operation, OperationSummary, _with_kinds, register_result


@dataclass(frozen=True)
class PageState:
    """Where the browser is: the page's ``url`` (after redirects) and ``title``."""

    url: Optional[str]
    title: Optional[str]
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Any) -> "PageState":
        raw = raw if isinstance(raw, dict) else {}
        return cls(raw.get("url"), raw.get("title"), raw)


@dataclass(frozen=True)
class ActResult:
    """How an ``act`` went: ``done`` says whether the task was finished (``False``:
    it ran out of steps or couldn't go on, and ``summary`` says why). ``steps`` are
    the actions it took (``action``, ``detail``, ``url``, and ``target``: the element it acted on, as the page names
    it); ``downloads`` the files it
    saved (``name``, ``size_bytes``, and a signed ``url`` valid for an hour)."""

    done: bool
    summary: str
    steps: List[Dict[str, Any]]
    url: Optional[str]
    downloads: List[Dict[str, Any]]
    cost_usd: Optional[float]
    raw: Dict[str, Any] = dc_field(repr=False)

    def __str__(self) -> str:
        return self.summary

    @classmethod
    def _from(cls, raw: Any) -> "ActResult":
        raw = raw if isinstance(raw, dict) else {}
        return cls(
            bool(raw.get("done")), raw.get("summary") or "", list(raw.get("steps") or []), raw.get("url"),
            list(raw.get("downloads") or []), raw.get("cost_usd"), raw,
        )


@dataclass(frozen=True)
class SiteLogin:
    """A site a profile is signed in to: its ``domain``, when the person signed in and
    who did, and when a browser last used the sign-in (None if never). When the site
    signs the profile out, the next browser that meets its sign-in page asks
    ``signed_in_by`` to sign in again in the live view, as it asks for a two-factor
    code, and saves the new sign-in; ``signed_in_at`` then moves."""

    domain: str
    signed_in_at: Any
    #: The email of the person who signed in (the one ``login`` asked), and who is asked again when the
    #: sign-in expires; None for a sign-in made through a link you passed on yourself, and then the
    #: browser's ``human`` is asked.
    signed_in_by: Optional[str]
    last_used_at: Any
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Any) -> "SiteLogin":
        raw = raw if isinstance(raw, dict) else {}
        return cls(
            raw.get("domain") or "", parse_time(raw.get("signed_in_at")), raw.get("signed_in_by"),
            parse_time(raw.get("last_used_at")), raw,
        )


@dataclass(frozen=True)
class BrowserWatchedStep:
    """A step of a browser's newest ``act``, as a person watching it is told: what it did (``action``) and the
    element it did it to (``target``: a field's label, a button's text), never what it typed."""

    action: str
    target: Optional[str]
    at: Any

    @classmethod
    def _from(cls, raw: Any) -> "BrowserWatchedStep":
        raw = raw if isinstance(raw, dict) else {}
        return cls(raw.get("action") or "", raw.get("target"), parse_time(raw.get("at")))


@dataclass(frozen=True)
class BrowserWaitingOn:
    """A step a person is asked to finish in a browser, while its ``act`` waits on them: what they're asked to do
    (``person``), and whether it's you they asked (``for_you``): only that person takes the browser over and hands
    it back."""

    person: str
    for_you: bool

    @classmethod
    def _from(cls, raw: Any) -> "BrowserWaitingOn":
        raw = raw if isinstance(raw, dict) else {}
        return cls(raw.get("person") or "", raw.get("for_you") is True)


def _read_act(result: Any, op: Operation) -> ActResult:
    return ActResult._from(result)


def _read_login(result: Any, op: Operation) -> SiteLogin:
    return SiteLogin._from(result.get("site", result) if isinstance(result, dict) else result)


register_result("browser.act", _read_act)
register_result("browser.login", _read_login)

_LOGIN_KINDS = ("browser.login",)


def _human(human: Optional[Human]) -> Optional[Dict[str, Any]]:
    if human is None:
        return None
    if not isinstance(human, Human):
        raise TypeError(f"human takes a noclick.Human (user.human, or noclick.Human(email=...)), not {type(human).__name__}")
    return human._to


class BrowserLogin(Operation):
    """A live-browser link where a person signs in to a site, and the operation
    that finishes once they have: ``wait()`` returns the ``SiteLogin``."""

    #: The page where the person signs in, in a live browser.
    url: str
    expires_at: Any
    #: The site's domain.
    domain: Optional[str]
    #: Channels the link went out on (``["email"]``); empty when nobody was sent it.
    delivered_via: List[str]
    #: Channels that failed, each with a ``reason``: send the link yourself.
    undelivered: List[Dict[str, Any]]

    @synced
    @classmethod
    async def list(cls, *, limit: Optional[int] = None, **filters: Any) -> List[Operation]:
        """Sign-in operations (kind ``browser.login``), newest first; takes
        ``Operation.list``'s filters except ``kind``.

        Returns:
            Every matching operation (or the first ``limit``); ``wait()`` on one returns the ``SiteLogin``.

        Usage::

            for op in noclick.BrowserLogin.list(status="awaiting_human", user_filter=noclick.ALL_USERS):
                print(op.user_id, op.summary_text, op.created_at)   # ... Sign in to portal.example.com ...
        """
        return await Operation.list.aio(limit=limit, **_with_kinds(filters, _LOGIN_KINDS, "BrowserLogin.list"))

    @synced
    @classmethod
    async def list_page(cls, *, cursor: Optional[str] = None, limit: Optional[int] = None, **filters: Any) -> Page:
        """One page of sign-in operations; pass ``next_cursor`` back as ``cursor``.

        Returns:
            A page whose ``data`` holds the operations and whose ``next_cursor`` is ``None`` on the last page.

        Usage::

            page = noclick.BrowserLogin.list_page(status="expired", limit=50)
            while True:
                for op in page.data:
                    print(op.summary_text, op.updated_at)
                if page.next_cursor is None:
                    break
                page = noclick.BrowserLogin.list_page(status="expired", limit=50, cursor=page.next_cursor)
        """
        return await Operation.list_page.aio(
            cursor=cursor, limit=limit, **_with_kinds(filters, _LOGIN_KINDS, "BrowserLogin.list_page"),
        )

    @synced
    @classmethod
    async def summary(cls, **filters: Any) -> OperationSummary:
        """Count sign-in operations; takes ``Operation.summary``'s filters except ``kind``.

        Returns:
            The ``total`` that match and a count for every status in ``by_status``.

        Usage::

            counts = noclick.BrowserLogin.summary(user_filter=noclick.ALL_USERS)
            print(counts.by_status["awaiting_human"], counts.by_status["succeeded"])
        """
        return await Operation.summary.aio(**_with_kinds(filters, _LOGIN_KINDS, "BrowserLogin.summary"))

    @classmethod
    def _from_link(cls, payload: Dict[str, Any], *, client: Optional[Client], user: Any) -> "BrowserLogin":
        operation = payload.get("operation")
        hints: Dict[str, Any] = {"kind": "browser.login"}
        if isinstance(operation, str):
            hints["id"] = operation
        login = cls._new(raw=operation if isinstance(operation, dict) else None, hints=hints, client=client, user=user)
        login.url = payload.get("url") or ""
        login.expires_at = parse_time(payload.get("expires_at"))
        login.domain = payload.get("domain")
        delivery = payload.get("delivery") or {}
        login.delivered_via = list(delivery.get("delivered_via") or [])
        login.undelivered = list(delivery.get("undelivered") or [])
        return login

    def _repr_parts(self) -> list:
        return [f"domain={self.domain!r}", f"url={self.url!r}", f"operation={self._known('id')!r}",
                f"status={self._known('status')!r}"]

    def __str__(self) -> str:
        return self.url


class BrowserProfile(_Object):
    """Saved sign-ins for one person. ``BrowserProfile.from_name("ana-work",
    create_if_missing=True, user="user_42")`` is lazy; ``profile.login(url)``
    asks the person to sign in once, and browsers started with the profile are signed in.
    Its ``region`` is where its browsers run; its sign-ins are kept in the US whatever the region."""

    _repr_keys = ("id", "name")

    id: str = field("id")
    name: str = field("name")
    region: Optional[str] = field("region", doc="Where its browsers run, fixed when it is created.")
    user_id: Optional[str] = field("user_id")
    last_used_at: Any = field("last_used_at", parse_time, doc="When a browser last used it (None if never).")
    created_at: Any = field("created_at", parse_time)

    def _init(self, **kwargs: Any) -> None:
        self._create_on_load = False
        self._region: Optional[str] = None
        super()._init(**kwargs)

    @property
    def sites(self) -> List[SiteLogin]:
        """The sites it is signed in to, most recently signed in first (loads the profile if needed)."""
        return [SiteLogin._from(site) for site in self._sync_raw().get("sites") or []]

    # --- construction ----------------------------------------------------

    @synced
    @classmethod
    async def create(
        cls, name: str, *, region: Optional[str] = None, allow_existing: bool = False, user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> "BrowserProfile":
        """Create an empty profile called ``name`` (unique per user; a duplicate
        raises ``noclick.Conflict`` with ``existing_id``, or with ``allow_existing=True``
        returns the profile already there, signed in where it was). ``region`` is where its
        browsers run (``noclick.regions(kind="browser")``; the account's default
        region when omitted), fixed for its life; its sign-ins are kept in the US.

        Returns:
            The new profile, signed in nowhere yet.

        Usage::

            profile = noclick.BrowserProfile.create("ana-work", user="user_42")
            login = profile.login("https://portal.example.com", reason="to download your invoices")
        """
        scope = resolve_scope(user)
        raw = await cls._create_named("/v1/browser_profiles", compact(name=name, region=region),
                                      allow_existing=allow_existing, user=scope, client=client)
        return cls._new(raw=raw, client=client, user=scope)

    @classmethod
    def from_name(
        cls, name: str, *, create_if_missing: bool = False, region: Optional[str] = None, user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> "BrowserProfile":
        """A lazy reference to the profile called ``name`` in the current (or given)
        user; with ``create_if_missing=True`` it's created, empty, on first use, in
        ``region`` when you pass one.

        Returns:
            A profile that loads, or is created, the first time it's used. Nothing is sent yet.

        Usage::

            profile = noclick.BrowserProfile.from_name("ana-work", create_if_missing=True, user="user_42")
            if not any(site.domain == "portal.example.com" for site in profile.sites):
                profile.login("https://portal.example.com", reason="to download your invoices").wait()
        """
        profile = cls._new(hints={"name": name}, client=client, user=user)
        profile._create_on_load = create_if_missing
        profile._region = region
        return profile

    @classmethod
    def from_id(cls, profile_id: str, *, client: Optional[Client] = None, user: Any = AMBIENT) -> "BrowserProfile":
        """A lazy reference to a profile by id.

        Returns:
            A profile that loads the first time you read a field. Nothing is sent yet.

        Usage::

            profile = noclick.BrowserProfile.from_id("b7e1d3a9-4c2f-4e6b-8a5d-1f9c0e3b7a24")
            print([site.domain for site in profile.sites])
        """
        return cls._new(hints={"id": profile_id}, client=client, user=user)

    @synced
    @classmethod
    async def get(cls, profile_id: str, *, user: Any = AMBIENT, client: Optional[Client] = None) -> "BrowserProfile":
        """Load a profile by id now; an unknown id raises ``noclick.NotFound``.

        Returns:
            The profile, loaded, with the ``sites`` it is signed in to.

        Usage::

            profile = noclick.BrowserProfile.get("b7e1d3a9-4c2f-4e6b-8a5d-1f9c0e3b7a24")
            for site in profile.sites:
                print(site.domain, site.signed_in_at, site.last_used_at)
        """
        profile = cls.from_id(profile_id, client=client, user=user)
        await profile._ensure()
        return profile

    @synced
    @classmethod
    async def list(
        cls, *, limit: Optional[int] = None, user_filter: Any = None, user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> List["BrowserProfile"]:
        """The current user's profiles (the account's own outside ``as_user``, or those ``user_filter`` covers).

        Returns:
            Every matching profile, newest first, fetched page by page, each with its ``sites``.

        Usage::

            for profile in noclick.BrowserProfile.list(user_filter=noclick.ALL_USERS):
                print(profile.user_id, profile.name, [site.domain for site in profile.sites])
        """
        return await list_all(
            "/v1/browser_profiles", lambda raw, scope: cls._new(raw=raw, client=client, user=scope),
            user=user, user_filter=user_filter, limit=limit, client=client,
        )

    @synced
    @classmethod
    async def list_page(
        cls, *, cursor: Optional[str] = None, limit: Optional[int] = None, user_filter: Any = None,
        user: Any = AMBIENT, client: Optional[Client] = None,
    ) -> Page:
        """One page of profiles; pass ``next_cursor`` back as ``cursor``.

        Returns:
            A page whose ``data`` holds the profiles and whose ``next_cursor`` is ``None`` on the last page.

        Usage::

            page = noclick.BrowserProfile.list_page(limit=50)
            while True:
                for profile in page.data:
                    print(profile.name, profile.last_used_at)
                if page.next_cursor is None:
                    break
                page = noclick.BrowserProfile.list_page(limit=50, cursor=page.next_cursor)
        """
        return await list_page(
            "/v1/browser_profiles", lambda raw, scope: cls._new(raw=raw, client=client, user=scope),
            user=user, user_filter=user_filter, cursor=cursor, limit=limit, client=client,
        )

    # --- hydration -------------------------------------------------------

    async def _load(self) -> Dict[str, Any]:
        profile_id = self._known("id")
        if profile_id:
            return await self._request("GET", f"/v1/browser_profiles/{profile_id}")
        name = self._hints["name"]
        page = await self._request("GET", "/v1/browser_profiles", params={"name": name}) or {}
        rows = [row for row in page.get("data") or [] if row.get("name") == name]
        if rows:
            return rows[0]
        if not self._create_on_load:
            raise NotFound(
                f"No browser profile is named {name!r}.",
                next_step="Create it with noclick.BrowserProfile.create(...) or pass create_if_missing=True.",
                details={"name": name},
            )
        try:
            return await self._request("POST", "/v1/browser_profiles", json=compact(name=name, region=self._region))
        except Conflict as exc:  # created concurrently
            if not exc.existing_id:
                raise
            return await self._request("GET", f"/v1/browser_profiles/{exc.existing_id}")

    async def _path(self) -> str:
        return f"/v1/browser_profiles/{await ref_id(self)}"

    # --- sign-ins --------------------------------------------------------

    @synced
    async def login(self, url: str, *, human: Optional[Human] = None, reason: Optional[str] = None) -> BrowserLogin:
        """Ask a person to sign in to the site at ``url`` in a live browser; the
        sign-in is saved to this profile. ``human`` is who is asked (a
        ``noclick.Human``): the profile's user when omitted. An account profile
        with no ``human`` sends nothing, so pass the link's ``url`` on yourself.
        You ask once: when the site signs the profile out later, the browser that
        meets its sign-in page asks the same person again (``SiteLogin.signed_in_by``)
        and saves the new sign-in. The link's browser starts (and is billed) only
        once the person opens it, so a link nobody opens costs nothing.

        Returns:
            The sign-in link, already sent: its ``url``, when it ``expires_at`` (in
            24 hours) and where it went. ``wait()`` returns the ``SiteLogin`` once the person has signed in.

        Usage:
            Ask the user once, then use the sign-in whenever you need it::

                profile = noclick.BrowserProfile.from_name("ana-work", create_if_missing=True, user="user_42")
                login = profile.login("https://portal.example.com", reason="to download your invoices")
                site = login.wait()
                print(site.domain, site.signed_in_at)

            Or, for your account's own profile, ask someone by email::

                profile = noclick.BrowserProfile.from_name("acme-ops", create_if_missing=True)
                login = profile.login("https://vendor.example.com", human=noclick.Human(email="ops@acme.test"))
                print(login.delivered_via)   # ['email']
        """
        payload = await self._request(
            "POST", f"{await self._path()}/login", json=compact(url=url, reason=reason, human=_human(human)),
        ) or {}
        return BrowserLogin._from_link(payload, client=self._client, user=self._call_scope())

    @synced
    async def forget(self, domain: str) -> None:
        """Sign the profile out of ``domain`` and drop what it and its subdomains
        stored. A short browser (about a minute, billed like any) clears them and
        saves the profile; this returns once it has. It refuses
        (``noclick.Conflict`` naming the browser) while another browser saves into
        the profile, and a browser already using the profile keeps the old state
        until it closes.

        Usage::

            profile = noclick.BrowserProfile.from_name("ana-work", user="user_42")
            profile.forget("portal.example.com")
        """
        await self._request("DELETE", f"{await self._path()}/sites/{quote(domain, safe='')}")
        if self._raw is not None:
            sites = [s for s in self._raw.get("sites") or [] if s.get("domain") != domain]
            self._raw = {**self._raw, "sites": sites}

    @synced
    async def delete(self) -> None:
        """Delete the profile and every sign-in in it.

        Usage::

            noclick.BrowserProfile.from_name("ana-work", user="user_42").delete()
        """
        await self._request("DELETE", await self._path())


class Browser(_Object):
    """A running browser. ``with noclick.Browser.create() as browser:`` closes it on
    exit; otherwise it closes at ``expires_at``. Billed per minute while it runs,
    plus the model tokens ``act`` and ``extract`` use; time it waits on a person
    is neither billed nor counted against ``timeout_s``."""

    _repr_keys = ("id", "status", "url")

    id: str = field("id")
    status: Optional[str] = field(
        "status", doc="``starting``, ``running``, ``parked`` (waiting on a person, or an agent's browser waiting for "
                      "its conversation's next turn), ``closed`` or ``failed``.",
    )
    region: Optional[str] = field("region", doc="Where it runs: its profile's region, else the one it was created in.")
    profile_id: Optional[str] = field("profile_id", doc="The profile it is signed in with (None if none).")
    agent_id: Optional[str] = field("agent_id", doc="The agent driving it, for an agent's browser.")
    conversation: Optional[str] = field(
        "conversation", doc="The conversation it works in, for a browser an agent's turn started.")
    act_id: Optional[str] = field("act_id", doc="Its newest ``act``'s operation.")
    acting: Optional[bool] = field("acting", doc="Whether an ``act`` is driving it now.")
    steps: List[BrowserWatchedStep] = field(
        "steps", lambda steps: [BrowserWatchedStep._from(s) for s in steps],
        doc="The steps its newest ``act`` has taken so far.")
    held: Optional[bool] = field(
        "held", doc="Whether a person has taken it over (``take_over``): its ``act`` waits until they hand it back.")
    waiting_on: Optional[BrowserWaitingOn] = field(
        "waiting_on", BrowserWaitingOn._from, doc="A step a person is asked to finish in it, while its ``act`` waits "
                                                  "on them.")
    live_url: Optional[str] = field(
        "live_url", doc="A NoClick page where you watch it live and can take over; it works while the browser runs, "
                        "with no sign-in, so treat it like a password. Only a caller that may take the browser over "
                        "reads it: your account's keys (one acting for a user too) and its signed-in owner. An MCP "
                        "connection, an agent's turn and an app's code read None.",
    )
    url: Optional[str] = field("url", doc="The page it is on.")
    title: Optional[str] = field("title")
    frame_url: Optional[str] = field(
        "frame_url", doc="A picture of the page it last stopped on (its ``act``'s end, or its conversation's turn's), "
                         "signed for an hour from each read; None before it first stopped.")
    timeout_s: Optional[int] = field("timeout_s", doc="How long it may run; parked time doesn't count.")
    solve_captchas: Optional[bool] = field("solve_captchas", doc="Whether NoClick solves CAPTCHAs before asking a person.")
    parked_s: Optional[int] = field("parked_s", doc="Seconds it has waited parked: not billed, not in timeout_s.")
    cost_usd: Optional[float] = field("cost_usd", doc="What it has cost so far: minutes and model tokens.")
    user_id: Optional[str] = field("user_id")
    created_at: Any = field("created_at", parse_time)
    started_at: Any = field("started_at", parse_time, doc="When it started running (None while it starts).")
    expires_at: Any = field("expires_at", parse_time)
    closed_at: Any = field("closed_at", parse_time)

    @synced
    @classmethod
    async def create(
        cls,
        *,
        profile: Any = None,
        timeout_s: Optional[int] = None,
        region: Optional[str] = None,
        solve_captchas: bool = True,
        human: Optional[Human] = None,
        user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> "Browser":
        """Start a browser that runs at most ``timeout_s`` seconds (300 by
        default, up to 3600; time it waits on a person doesn't count). With
        ``profile`` (a ``BrowserProfile`` or id) it is signed in to the profile's
        sites, acts for the profile's user, runs in the profile's region and saves
        new sign-ins into it when it closes: one such browser per profile at a
        time, so a second raises ``noclick.Conflict`` naming the first
        (``browser_id``). Without one, ``region`` is where it runs
        (``noclick.regions(kind="browser")``; the account's default when omitted).
        NoClick solves the CAPTCHAs it can before asking a person;
        ``solve_captchas=False`` turns that off for sites whose terms forbid it.
        ``human`` is who is asked when a page needs a person (the user by default,
        you for an account browser).

        Returns:
            The browser, ``running`` on a blank page, with its ``live_url``.

        Usage:
            Use it as a context manager, so it closes when the block ends::

                profile = noclick.BrowserProfile.from_name("ana-work", user="user_42")
                with noclick.Browser.create(profile=profile, timeout_s=900) as browser:
                    browser.goto("https://portal.example.com/invoices")
                    print(browser.act("Download every invoice from September").summary)

            Without ``with``, close it yourself or let it run out::

                browser = noclick.Browser.create(timeout_s=600)
                print(browser.live_url)   # watch it, or take over
                browser.close()
        """
        scope = resolve_scope(user)
        if user is AMBIENT and isinstance(profile, BrowserProfile):
            await profile._ensure()
            scope = profile._call_scope()
        raw = await resolve_client(client).request(
            "POST", "/v1/browsers",
            json=compact(profile_id=await ref_id(profile), timeout_s=timeout_s, region=region,
                         solve_captchas=None if solve_captchas else False, human=_human(human)), user=scope,
        )
        return cls._new(raw=raw, client=client, user=scope)

    @classmethod
    def from_id(cls, browser_id: str, *, client: Optional[Client] = None, user: Any = AMBIENT) -> "Browser":
        """A lazy reference to a browser by id, for one you started earlier.

        Returns:
            A browser that loads the first time you read a field. Nothing is sent yet.

        Usage::

            browser = noclick.Browser.from_id("e2c9a4f7-1b3d-4e8a-9c6f-5d0b7a2e1f83")
            print(browser.content(format="text"))
        """
        return cls._new(hints={"id": browser_id}, client=client, user=user)

    @synced
    @classmethod
    async def get(cls, browser_id: str, *, user: Any = AMBIENT, client: Optional[Client] = None) -> "Browser":
        """Load a browser by id now; an unknown id raises ``noclick.NotFound``.

        Returns:
            The browser, loaded: its ``status``, the page it is on and its ``live_url``.

        Usage::

            browser = noclick.Browser.get("e2c9a4f7-1b3d-4e8a-9c6f-5d0b7a2e1f83")
            print(browser.status, browser.url, browser.live_url)
        """
        browser = cls.from_id(browser_id, client=client, user=user)
        await browser._ensure()
        return browser

    @synced
    @classmethod
    async def list(
        cls, *, profile: Any = None, status: Optional[str] = None, agent: Any = None,
        conversation: Optional[str] = None, limit: Optional[int] = None, user_filter: Any = None,
        user: Any = AMBIENT, client: Optional[Client] = None,
    ) -> List["Browser"]:
        """The current user's browsers (the account's own outside ``as_user``, or those
        ``user_filter`` covers), optionally one ``profile``'s, or an ``agent``'s (one ``conversation``'s: an agent's
        browser works in the conversation whose turn started it, one at a time); ``status="live"`` lists those
        starting, running or parked.

        Returns:
            Every matching browser, newest first, fetched page by page. Agents' browsers are listed too.

        Usage::

            for browser in noclick.Browser.list(status="live", user_filter=noclick.ALL_USERS):
                print(browser.id, browser.url, browser.live_url)

            profile = noclick.BrowserProfile.from_name("ana-work", user="user_42")
            recent = noclick.Browser.list(profile=profile, limit=10)
        """
        return await list_all(
            "/v1/browsers", lambda raw, scope: cls._new(raw=raw, client=client, user=scope),
            params={"profile_id": await ref_id(profile), "status": status, "agent_id": await ref_id(agent),
                    "conversation": conversation}, user=user, user_filter=user_filter, limit=limit, client=client,
        )

    @synced
    @classmethod
    async def list_page(
        cls, *, cursor: Optional[str] = None, limit: Optional[int] = None, profile: Any = None,
        status: Optional[str] = None, agent: Any = None, conversation: Optional[str] = None,
        user_filter: Any = None, user: Any = AMBIENT, client: Optional[Client] = None,
    ) -> Page:
        """One page of browsers; pass ``next_cursor`` back as ``cursor``.

        Returns:
            A page whose ``data`` holds the browsers and whose ``next_cursor`` is ``None`` on the last page.

        Usage::

            page = noclick.Browser.list_page(status="closed", limit=50)
            while True:
                for browser in page.data:
                    print(browser.id, browser.cost_usd)
                if page.next_cursor is None:
                    break
                page = noclick.Browser.list_page(status="closed", limit=50, cursor=page.next_cursor)
        """
        return await list_page(
            "/v1/browsers", lambda raw, scope: cls._new(raw=raw, client=client, user=scope),
            params={"profile_id": await ref_id(profile), "status": status, "agent_id": await ref_id(agent),
                    "conversation": conversation}, user=user, user_filter=user_filter, cursor=cursor, limit=limit,
            client=client,
        )

    def _path(self) -> str:
        return f"/v1/browsers/{self._known('id')}"

    async def _load(self) -> Dict[str, Any]:
        return await self._request("GET", self._path())

    # --- driving ---------------------------------------------------------

    @synced
    async def goto(self, url: str) -> PageState:
        """Open ``url`` and wait for the page to load.

        Returns:
            The page it landed on: its ``url`` after redirects and its ``title``.

        Usage::

            with noclick.Browser.create() as browser:
                page = browser.goto("https://example.com")
                print(page.url, page.title)
        """
        state = PageState._from(await self._request("POST", f"{self._path()}/goto", json={"url": url}))
        self._raw = {**(self._raw or self._hints), "url": state.url, "title": state.title}
        return state

    @overload
    async def act(
        self, instruction: str, *, background: Literal[False] = False, max_steps: Optional[int] = None,
        files: Optional[List[str]] = None, timeout: Optional[float] = None,
    ) -> ActResult: ...

    @overload
    async def act(
        self, instruction: str, *, background: Literal[True], max_steps: Optional[int] = None,
        files: Optional[List[str]] = None, timeout: Optional[float] = None,
    ) -> Operation: ...

    @synced
    async def act(
        self, instruction: str, *, background: bool = False, max_steps: Optional[int] = None,
        files: Optional[List[str]] = None, timeout: Optional[float] = None,
    ) -> Union[ActResult, Operation]:
        """Have the model carry out ``instruction`` on the page: clicking, typing,
        scrolling, uploading, downloading, at most ``max_steps`` actions (50 by
        default, up to 200). ``files`` are https URLs (a bucket's ``signed_url``
        works) NoClick downloads into the browser first, for the task to put in a
        form, up to 5. NoClick solves the CAPTCHAs it can, giving one half a
        minute; one still there, or a two-factor prompt, parks the browser (not
        billed, not counted against its timeout) and sends a person a page carrying
        the live view, and the step waits until they have dealt with it. So does a sign-in page for a site
        whose saved sign-in expired: it asks the person who signed in
        (``SiteLogin.signed_in_by``) to sign in again, saves the new sign-in to the
        profile, and carries on.

        ``timeout`` is how many seconds to wait here; the step keeps going after it.
        ``background=True`` returns at once.

        Returns:
            How it went: whether it's ``done``, a ``summary``, the ``steps`` it took, the ``url``
            it ended on and any ``downloads``. With ``background=True``, an ``Operation`` at once,
            whose ``wait()`` gives that result.

        Usage:
            Describe the task, not the clicks::

                with noclick.Browser.create(profile=noclick.BrowserProfile.from_name("ana-work", user="user_42")) as browser:
                    browser.goto("https://portal.example.com/invoices")
                    result = browser.act("Download every invoice from September")
                    print(result.done, result.summary)
                    for file in result.downloads:
                        print(file["name"], file["url"])

            Run a long task in the background and pick it up later::

                browser = noclick.Browser.create(timeout_s=1800)
                task = browser.act("Compare the three cheapest flights from SFO to JFK on Oct 12", background=True)
                print(task.id)                                   # save it; then, later, anywhere:
                result = noclick.Operation.from_id(task.id).wait()

            Hand it the files a form needs::

                w9 = noclick.Bucket.from_name("forms").signed_url("w9-2026.pdf")
                with noclick.Browser.create(profile=noclick.BrowserProfile.from_name("ana-work", user="user_42")) as browser:
                    browser.goto("https://supplier.example.com/onboarding")
                    print(browser.act("Fill in the onboarding form and attach the W-9", files=[w9]).summary)
        """
        payload = await self._request(
            "POST", f"{self._path()}/act", json=compact(instruction=instruction, max_steps=max_steps, files=files),
        )
        op = Operation._from_payload(
            payload, client=self._client, user=self._call_scope(), kind="browser.act", reader=_read_act,
        )
        if background:
            return op
        return await op.wait.aio(timeout=timeout)

    @synced
    async def extract(self, query: str, *, schema: Optional[Dict[str, Any]] = None) -> Any:
        """Read what ``query`` describes off the current page, shaped by ``schema``
        (a JSON Schema) when you pass one.

        Returns:
            The data as JSON: an object or a list matching ``schema``, or the model's own shape without one.

        Usage::

            with noclick.Browser.create() as browser:
                browser.goto("https://portal.example.com/invoices")
                invoices = browser.extract(
                    "the invoice numbers and totals",
                    schema={"type": "array", "items": {"type": "object", "properties": {
                        "number": {"type": "string"}, "total_usd": {"type": "number"}}}},
                )
                print(invoices[0]["number"], invoices[0]["total_usd"])
        """
        response = await self._request("POST", f"{self._path()}/extract", json=compact(query=query, schema=schema)) or {}
        return response.get("data")

    @synced
    async def screenshot(self, *, full_page: bool = False) -> bytes:
        """A PNG of what the browser shows: the viewport, or the whole page with ``full_page=True``.

        Returns:
            The PNG's bytes.

        Usage::

            with noclick.Browser.create() as browser:
                browser.goto("https://example.com")
                with open("page.png", "wb") as f:
                    f.write(browser.screenshot(full_page=True))
        """
        return await self._request(
            "GET", f"{self._path()}/screenshot", params={"full_page": "true" if full_page else None}, binary=True,
        )

    @synced
    async def content(self, *, format: str = "markdown") -> str:
        """The current page's content as ``"markdown"``, ``"text"`` or ``"html"``.

        Returns:
            The page's content in that format; markdown keeps headings, links and tables.

        Usage::

            with noclick.Browser.create() as browser:
                browser.goto("https://example.com/pricing")
                print(browser.content(format="markdown"))
        """
        response = await self._request("GET", f"{self._path()}/content", params={"format": format}) or {}
        return response.get("content") or ""

    @synced
    async def take_over(self) -> None:
        """Take the browser over from its agent, as a person: it waits for you (unbilled), and an ``act`` in it
        stops at its next step until you ``hand_back()``. Drive it from its ``live_url``. Asked to finish a step in
        it (``waiting_on``), only the person asked takes it over.

        Usage::

            browser = noclick.Browser.list(agent=agent, conversation="owner", limit=1)[0]
            browser.take_over()
            print(browser.live_url)   # sign in there, then:
            browser.hand_back()
        """
        self._raw = await self._request("POST", f"{self._path()}/take_over")

    @synced
    async def hand_back(self) -> None:
        """Hand the browser back: a step you were asked to finish counts as finished (as Done on its page does),
        and the ``act`` waiting on you carries on; with nothing asked, it's the agent's again.

        Usage::

            if browser.waiting_on and browser.waiting_on.for_you:
                browser.take_over()
                # ...finish the step from browser.live_url, then:
                browser.hand_back()
        """
        self._raw = await self._request("POST", f"{self._path()}/hand_back")

    @synced
    async def close(self) -> None:
        """Close the browser now (billing stops with it). The profile keeps any new sign-ins.

        Usage::

            browser = noclick.Browser.create()
            try:
                print(browser.goto("https://example.com").title)
            finally:
                browser.close()
        """
        response = await self._request("DELETE", self._path())
        self._raw = {**(self._raw or self._hints), **(response if isinstance(response, dict) else {}), "status": "closed"}

    def __enter__(self) -> "Browser":
        return self

    def __exit__(self, *exc: Any) -> None:
        try:
            self.close()
        except NotFound:  # it already closed
            pass

    async def __aenter__(self) -> "Browser":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        try:
            await self.close.aio()
        except NotFound:  # it already closed
            pass
