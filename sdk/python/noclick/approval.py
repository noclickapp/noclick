"""Approvals: the calls NoClick holds for your account's owner's yes, read and answered from your own code.

When an agent, a connected app, a key used through MCP or an app's own code makes a purchase, a deletion that can't
be undone, a call your policy holds or one that raises a spending limit, NoClick holds the exact call and sends your
account's owner a link to approve it. Your code may answer it too, with one of your account's secret keys that
names the ``approvals:answer`` scope (a key with every scope, ``*``, holds it only when it's named too)::

    for approval in noclick.Approval.list(status="pending"):
        if approval.price and approval.price["amount_usd"] <= 20:
            approval.approve(note="Under $20: fine.")

A key never answers a call made with it (by its own code, through MCP, or by an agent or app acting as it), never
approves one whose terms a person accepts (it may decline it), and approves only what it could make itself: the
scopes the call needs (never a call only the owner and their NoClick assistant make), and a price that fits the key's
own monthly cap beside what it spent and approved this month (what it approves also counts against what it may
still spend itself). NoClick then runs an approved call itself, once, exactly as it was held, with no scope the
answering key lacks. While your account holds a key that would approve it, a call whose link reaches no person is
still held, with an empty ``sent_to``, for your code (or the owner, signed in) to answer.

Rather than poll, your code can hear each one: a webhook subscribed to ``approval.requested`` gets it as it's held,
and to ``approval.decided`` as it's approved, declined, expired or withdrawn. The event's ``data`` is the approval as
it reads here, never its link::

    event = noclick.Webhook.verify(body, headers, secret)
    if event.type == "approval.requested":
        noclick.Approval.from_id(event.data["id"]).decline(note="Nothing is bought on weekends.")

What NoClick holds, kind by kind and for which callers, reads as ``noclick.ApprovalPolicy.get()``, and your account
switches any kind it may (``noclick.ApprovalPolicy.set``) so it needn't wait for a person at all::

    noclick.ApprovalPolicy.set(settings={"purchase": {"disposition": "allow", "under_usd": 20}})

A key, or a connected app, sets its own within the account's ceiling (``set_for_key``, ``set_for_connected_app``), so
one autonomous key buys unasked while everything else still asks::

    noclick.ApprovalPolicy.set(ceilings={"purchase": {"disposition": "allow", "under_usd": 50}})
    noclick.ApprovalPolicy.set_for_key(key_id, {"purchase": {"disposition": "allow", "under_usd": 20}})

An agent does too (``Agent.update(approvals=...)``), and a child it spawns follows it, only ever tighter::

    noclick.Agent.from_name("buyer").update(approvals={"purchase": {"disposition": "allow", "under_usd": 20}})
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from ._client import Client, resolve_client
from ._object import UNSET, _Object, compact, field, list_all, parse_time
from ._sync import synced
from ._scope import AMBIENT

STATUSES = ("pending", "approved", "declined", "expired", "used", "canceled")


@dataclass(frozen=True)
class HoldKind:
    """One kind of call NoClick may hold for a person: what it does by default, and what your account switched."""

    #: Its name (``purchase``, ``delete``, ``raise_limit``, ...).
    kind: str
    #: What it covers, in a person's words.
    description: str
    #: Who answers it: ``owner`` (the account's owner, from the link NoClick sends them) or ``connection_owner``
    #: (whoever owns the connection the call runs on: its user, else the account's owner).
    approver: str
    #: It applies only on a turn answering someone outside the agent's scope.
    outside_only: bool
    #: What it does by default for each kind of caller it applies to (``ApprovalPolicy.callers`` names them):
    #: ``allow``, ``ask``, ``deny``, ``under_auto_approve`` (a quoted purchase at or under the connection's
    #: auto-approve amount runs, anything else asks) or ``once_previewed`` (a deletion its preview confirmed runs).
    defaults: Dict[str, str]
    #: Whether your account may switch it (``ApprovalPolicy.set``).
    settable: bool = False
    #: What your account set it to (``disposition``, ``under_usd``, ``until``, ``effective_at``, ``pending``), or None.
    setting: Optional[Dict[str, Any]] = None
    #: The loosest a narrower scope may set it to, or None.
    ceiling: Optional[Dict[str, Any]] = None
    #: What each caller meets now: a default, or ``allow``, ``ask``, ``deny`` or ``allow_under`` (a purchase at or
    #: under the setting's ``under_usd`` runs) by your account's setting (or the key's, connected app's or agent's
    #: own, read with ``get(key_id=...)`` or ``get(agent_id=...)``).
    effective: Dict[str, str] = dc_field(default_factory=dict)
    #: Read for a key, connected app or agent: what it sets for itself, or None.
    own: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class PolicyChange:
    """One change to your account's approval switches (``ApprovalPolicy.set``), a key's, connected app's or agent's own
    (``set_for_key``, ``set_for_connected_app``, an agent's ``approvals``), or a connection's approval rule lifted
    (``Connection.lift_approval``, or its owner's page in the app)."""

    id: str
    batch_id: str
    #: The kind it changed, and whether its setting, its ceiling, (``auto_approve``) a connected app's auto-approve
    #: amount or (``operations``, kind ``credential_rule``) a connection's approval rule.
    kind: str
    target: str
    before: Optional[Dict[str, Any]]
    #: What it set (``disposition``, ``under_usd``, ``until``; a connection's rule, its ``operations``); None put
    #: NoClick's default back.
    after: Optional[Dict[str, Any]]
    #: It lets a caller do more than before: a key's loosening waits out an undo window first.
    loosens: bool
    #: ``owner`` (signed in), ``key`` (with ``key_id``), or through NoClick's tools ``assistant`` (NoClick's),
    #: ``agent`` or ``connection`` (a connected app): on the owner's word or approval, or a loosening the account
    #: lets them make.
    changed_by: str
    key_id: Optional[str]
    effective_at: Any
    until: Any
    #: It still waits out its undo window: ``ApprovalPolicy.undo`` takes it back. A lift of a connection's rule waiting
    #: is taken back too by approval required for one of its operations again (``undone_by`` ``superseded``).
    pending: bool
    undone_at: Any
    undone_by: Optional[str]
    created_at: Any
    raw: Dict[str, Any] = dc_field(repr=False)
    #: Whose settings it changed: ``account``, ``key``, ``connected_app``, ``agent`` or ``credential`` (a connection's
    #: approval rule), and that key's, connected app's, agent's or connection's account's id.
    scope: str = "account"
    scope_id: Optional[str] = None

    @staticmethod
    def _from(raw: Dict[str, Any]) -> "PolicyChange":
        return PolicyChange(
            id=raw["id"], batch_id=raw["batch_id"], kind=raw["kind"], target=raw["target"], before=raw.get("before"),
            after=raw.get("after"), loosens=bool(raw.get("loosens")), changed_by=raw["changed_by"],
            key_id=raw.get("key_id"), effective_at=parse_time(raw.get("effective_at")), until=parse_time(raw.get("until")),
            pending=bool(raw.get("pending")), undone_at=parse_time(raw.get("undone_at")), undone_by=raw.get("undone_by"),
            created_at=parse_time(raw.get("created_at")), raw=raw, scope=raw.get("scope") or "account",
            scope_id=raw.get("scope_id"))


@dataclass(frozen=True)
class ApprovalExplanation:
    """What a call of one kind by one kind of caller meets now, and why."""

    kind: str
    caller: str
    #: ``allow``, ``ask``, ``deny``, or ``under_auto_approve`` where it turns on the connection's own amount.
    disposition: str
    #: ``key`` (the key's or connected app's own setting), ``account`` (your setting), ``bounds`` (NoClick asks this
    #: caller first) or ``default``.
    source: str
    #: What a held call's approval would say; None when it runs.
    why: Optional[str]
    setting: Optional[Dict[str, Any]]
    raw: Dict[str, Any] = dc_field(repr=False)


def _wire_setting(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in value.items()}
    return value


def settings_wire(settings: Dict[str, Any]) -> Dict[str, Any]:
    """Approval settings by kind as the API takes them (an agent's ``approvals`` among them)."""
    return {k: _wire_setting(v) for k, v in settings.items()}


@dataclass(frozen=True)
class OwnApprovals:
    """A key's or connected app's own approval settings, as a change left them."""

    #: ``key`` or ``connected_app``, and its id.
    kind: str
    id: str
    #: What it sets for itself, by kind (``disposition``, ``under_usd``, ``until``, ``effective_at``, ``pending``).
    settings: Dict[str, Dict[str, Any]]
    #: Each change the call made.
    changes: List[PolicyChange]
    raw: Dict[str, Any] = dc_field(repr=False)
    #: A connected app's auto-approve amount (None: it asks before every purchase); None for a key.
    auto_approve_under_usd: Optional[float] = None

    @staticmethod
    def _from(kind: str, raw: Dict[str, Any]) -> "OwnApprovals":
        return OwnApprovals(kind=kind, id=raw["id"], settings=dict(raw.get("approvals") or {}),
                            changes=[PolicyChange._from(c) for c in raw.get("approval_changes") or []], raw=raw,
                            auto_approve_under_usd=raw.get("auto_approve_under_usd"))


@dataclass(frozen=True)
class ApprovalPolicy:
    """What NoClick holds for a person, kind by kind and for which callers: its defaults, and what your account
    switched (``set``), so no call ever needs a person for good."""

    kinds: List[HoldKind]
    #: Each kind of caller, by name (``connected_app``, ``assistant``, ``agent``, ``key``, ``code``, ``app``), with
    #: what it is.
    callers: Dict[str, str]
    raw: Dict[str, Any] = dc_field(repr=False)
    #: Whether the account has a monthly spending cap: loosening a purchase or a deletion past the default needs one.
    spend_cap_set: bool = False
    #: The changes the call that returned it made (``set``); empty from ``get``.
    changes: List[PolicyChange] = dc_field(default_factory=list)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "ApprovalPolicy":
        return cls(
            kinds=[HoldKind(kind=k["kind"], description=k["description"], approver=k["approver"],
                            outside_only=bool(k.get("outside_only")), defaults=dict(k["defaults"]),
                            settable=bool(k.get("settable")), setting=k.get("setting"), ceiling=k.get("ceiling"),
                            effective=dict(k.get("effective") or k["defaults"]), own=k.get("own"))
                   for k in raw.get("kinds") or []],
            callers=dict(raw.get("callers") or {}), raw=raw, spend_cap_set=bool(raw.get("spend_cap_set")),
            changes=[PolicyChange._from(c) for c in raw.get("changes") or []])

    def _kind(self, kind: str) -> HoldKind:
        found = next((k for k in self.kinds if k.kind == kind), None)
        if found is None:
            raise KeyError(f"NoClick holds no kind '{kind}': it holds {', '.join(k.kind for k in self.kinds)}.")
        return found

    def default(self, kind: str, caller: str) -> Optional[str]:
        """What ``kind`` does by default for ``caller``, whatever your account switched.

        Returns:
            ``allow``, ``ask``, ``deny``, ``under_auto_approve`` or ``once_previewed``; None where the kind doesn't
            apply to that caller.

        Raises:
            KeyError: ``kind`` isn't one NoClick holds.

        Usage::

            policy = noclick.ApprovalPolicy.get()
            if policy.default("delete", "agent") == "ask":
                print("An agent's deletion waits for the owner by default.")
        """
        return self._kind(kind).defaults.get(caller)

    def effective(self, kind: str, caller: str) -> Optional[str]:
        """What ``kind`` does for ``caller`` now: your account's setting where it switched one, else the default.

        Returns:
            ``allow``, ``ask``, ``deny``, ``allow_under`` (a purchase at or under the setting's ``under_usd``),
            ``under_auto_approve`` or ``once_previewed``; None where the kind doesn't apply to that caller.

        Raises:
            KeyError: ``kind`` isn't one NoClick holds.

        Usage::

            policy = noclick.ApprovalPolicy.get()
            print(policy.effective("purge", "agent"))   # "ask", until the account allows it
        """
        return self._kind(kind).effective.get(caller)

    @synced
    @classmethod
    async def get(cls, *, key_id: Optional[str] = None, connected_app_id: Optional[str] = None,
                  agent_id: Optional[str] = None, client: Optional[Client] = None) -> "ApprovalPolicy":
        """What waits for a person: each kind of hold (a purchase, a deletion that can't be undone, a spending limit
        raised, a call whose terms a person accepts, ...), what it covers, who approves it, what it does by default
        for each kind of caller (a connected app, NoClick's assistant, an agent's tools, a key used through MCP,
        code, an app's own code), and what your account switched. With ``key_id``, ``connected_app_id`` or
        ``agent_id``, also what that key, connected app or agent sets for itself (each kind's ``own``), which
        ``effective`` reads for its calls (an agent's through its parent's, which it follows where it sets none).

        Returns:
            The policy: ``kinds``, each a ``HoldKind``, ``callers`` and ``spend_cap_set``.

        Usage::

            policy = noclick.ApprovalPolicy.get()
            print(policy.default("purchase", "agent"))   # "ask"
            for kind in policy.kinds:
                print(kind.kind, kind.effective)
            mine = noclick.ApprovalPolicy.get(key_id=key_id)
            print(mine.effective("purchase", "key"))
            buyer = noclick.ApprovalPolicy.get(agent_id=agent.id)
            print(buyer.effective("purchase", "agent"))   # "allow_under" once it's allowed under an amount
        """
        return cls._from(await resolve_client(client).request(
            "GET", "/v1/approvals/policy",
            params=compact(key_id=key_id, connected_app_id=connected_app_id, agent_id=agent_id), user=None))

    @synced
    @classmethod
    async def set(
        cls, *, settings: Optional[Dict[str, Any]] = None, ceilings: Optional[Dict[str, Any]] = None,
        client: Optional[Client] = None,
    ) -> "ApprovalPolicy":
        """Switch what NoClick holds for a person, for your whole account, from the kinds a ``get`` lists as
        ``settable``: each named kind to ``"allow"``, ``"ask"`` or ``"deny"``, a dict with ``disposition`` (and for a
        purchase ``under_usd``, allowed at or under it, asked above; any kind may take ``until``, when it lapses back),
        or None for NoClick's default. Kinds you don't name stay as they are. ``ceilings`` are the loosest a narrower
        scope (a key, an agent) may set.

        Signed in as the account's owner, or with one of its own secret keys naming the ``approvals:policy`` scope
        (``*`` holds it only when it's named too). A key's loosening takes effect after a 10-minute undo window, and
        the owner is told; the owner's own change applies at once.

        Returns:
            The policy as it stands after, with ``changes``: each change it made.

        Raises:
            noclick.PermissionDenied: the caller may not switch them, or loosening a purchase or a deletion past the
                default while the account has no monthly spending cap (``reason`` ``spend_cap_required``).
            noclick.InvalidRequest: a kind not settable yet, ``under_usd`` on anything but a purchase allowed, or a
                setting looser than its ceiling.

        Usage::

            noclick.ApprovalPolicy.set(settings={
                "purchase": {"disposition": "allow", "under_usd": 20},
                "purge": "allow",
                "outside_outbound": "allow",
            })
        """
        body = compact(settings={k: _wire_setting(v) for k, v in settings.items()} if settings is not None else None,
                       ceilings={k: _wire_setting(v) for k, v in ceilings.items()} if ceilings is not None else None)
        return cls._from(await resolve_client(client).request("PUT", "/v1/approvals/policy", json=body, user=None))

    @synced
    @classmethod
    async def explain(
        cls, kind: str, caller: str, *, amount_usd: Optional[float] = None, quoted: bool = True,
        previewed: bool = True, key_id: Optional[str] = None, connected_app_id: Optional[str] = None,
        agent_id: Optional[str] = None, client: Optional[Client] = None,
    ) -> ApprovalExplanation:
        """What a call of ``kind`` by ``caller`` would meet now, and why: the key's or connected app's own setting
        (``key_id``, ``connected_app_id``: the call is its), an agent's own or its parent's (``agent_id``, with
        ``caller="agent"``: ``source`` ``agent`` or ``parent``), your account's setting, what NoClick asks that caller
        first, or the default. Nothing runs and nothing is held.

        Returns:
            An ``ApprovalExplanation``: ``disposition``, ``source`` and ``why``.

        Usage::

            seen = noclick.ApprovalPolicy.explain("purchase", "agent", amount_usd=12)
            print(seen.disposition, seen.source, seen.why)
        """
        raw = await resolve_client(client).request("POST", "/v1/approvals/policy/explain", json=compact(
            kind=kind, caller=caller, amount_usd=amount_usd, quoted=quoted, previewed=previewed, key_id=key_id,
            connected_app_id=connected_app_id, agent_id=agent_id), user=None)
        return ApprovalExplanation(kind=raw["kind"], caller=raw["caller"], disposition=raw["disposition"],
                                   source=raw["source"], why=raw.get("why"), setting=raw.get("setting"), raw=raw)

    @synced
    @classmethod
    async def history(cls, *, limit: Optional[int] = None, client: Optional[Client] = None) -> List[PolicyChange]:
        """Every change to your account's approval switches, newest first: the first 20, or the first ``limit`` (at
        most 100).

        Returns:
            Each ``PolicyChange``.

        Usage::

            for change in noclick.ApprovalPolicy.history():
                print(change.kind, change.after, change.changed_by, change.pending)
        """
        raw = await resolve_client(client).request("GET", "/v1/approvals/policy/changes",
                                                   params=compact(limit=limit), user=None)
        return [PolicyChange._from(row) for row in raw.get("data") or []]

    @synced
    @classmethod
    async def undo(cls, change_id: str, *, client: Optional[Client] = None) -> PolicyChange:
        """Take back a change still waiting out its undo window (a key's loosening): what was in effect before it
        stands again. Signed in, or with a key naming ``approvals:policy``.

        Returns:
            The change, undone (``undone_at``, ``undone_by``).

        Raises:
            noclick.Conflict: it's in effect already, undone already, or a later change replaced it.

        Usage::

            for change in noclick.ApprovalPolicy.history():
                if change.pending and change.changed_by == "key":
                    noclick.ApprovalPolicy.undo(change.id)
        """
        raw = await resolve_client(client).request(
            "POST", f"/v1/approvals/policy/changes/{quote(change_id, safe='')}/undo", user=None)
        return PolicyChange._from(raw)

    @synced
    @classmethod
    async def set_for_key(cls, key_id: str, settings: Dict[str, Any], *,
                          client: Optional[Client] = None) -> OwnApprovals:
        """Switch what one of your secret keys waits for, in place of the account's, for the calls it makes through
        MCP and the code it runs: each named kind to ``"allow"``, ``"ask"`` or ``"deny"``, a dict as ``set`` takes,
        or None for the account's. Never looser than the account's ceiling for the kind (else its own setting, else
        NoClick's default for a key): raise the ceiling with ``set(ceilings=...)`` first. Lowering the ceiling later
        tightens every key at once. A purchase or a deletion past the default needs a monthly cap on the account.

        Any of your account's keys tightens them. Loosening takes one naming ``approvals:policy``: it waits a
        10-minute undo window and the owner is told, and a key never loosens itself. Your agents change them when you
        say so (a turn your own message started); one acting on its own waits for you.

        Returns:
            The key's own settings, with ``changes``.

        Raises:
            noclick.InvalidRequest: looser than the account allows a key, or a key that takes no settings (the
                console key, a publishable key).
            noclick.PermissionDenied: a key loosening without ``approvals:policy``, or its own settings, or a
                purchase or a deletion past the default with no monthly cap (``reason`` ``spend_cap_required``).

        Usage::

            noclick.ApprovalPolicy.set(ceilings={"purchase": {"disposition": "allow", "under_usd": 50}})
            mine = noclick.ApprovalPolicy.set_for_key(key_id, {"purchase": {"disposition": "allow", "under_usd": 20}})
            print(mine.settings["purchase"])
        """
        raw = await resolve_client(client).request(
            "PATCH", f"/v1/keys/{quote(key_id, safe='')}",
            json={"approvals": {k: _wire_setting(v) for k, v in settings.items()}}, user=None)
        return OwnApprovals._from("key", raw)

    @synced
    @classmethod
    async def set_for_connected_app(cls, connected_app_id: str, settings: Optional[Dict[str, Any]] = None, *,
                                    auto_approve_under_usd: Any = UNSET,
                                    client: Optional[Client] = None) -> OwnApprovals:
        """Switch what a connected app (an MCP client a person connected, NoClick's assistant's grant among them)
        waits for, in place of the account's, for its calls and its code's: ``settings`` as ``set_for_key`` takes,
        and its ``auto_approve_under_usd``, the price at or under which a purchase it makes goes through unasked
        (None: it asks before every one), at or under its monthly cap and the account's ceiling for purchases.

        Any of your account's keys tightens them. Loosening takes one naming ``approvals:policy`` (it waits a
        10-minute undo window, and only lowers an auto-approve amount). Your agents change them when you say so; a
        connected app or an agent acting on its own waits for you.

        Returns:
            The connected app's own settings and auto-approve amount, with ``changes``.

        Raises:
            noclick.InvalidRequest: looser than the account's ceiling, or an amount above its monthly cap.
            noclick.PermissionDenied: a key loosening without ``approvals:policy``, or raising an auto-approve
                amount.

        Usage::

            app = noclick.ApprovalPolicy.set_for_connected_app(app_id, auto_approve_under_usd=10)
            noclick.ApprovalPolicy.set_for_connected_app(app_id, {"delete": "ask"})
        """
        body: Dict[str, Any] = {}
        if settings is not None:
            body["approvals"] = {k: _wire_setting(v) for k, v in settings.items()}
        if auto_approve_under_usd is not UNSET:
            body["auto_approve_under_usd"] = auto_approve_under_usd
        raw = await resolve_client(client).request(
            "PATCH", f"/v1/connected_apps/{quote(connected_app_id, safe='')}", json=body, user=None)
        return OwnApprovals._from("connected_app", raw)


class Approval(_Object):
    """A call held for your account's owner's yes, as they see it on its page."""

    _repr_keys = ("id", "status", "action")

    id: str = field("id")
    status: str = field("status", doc=f"One of {', '.join(STATUSES)} (``used``: approved, and run).")
    action: Optional[str] = field("action", doc="What the call does, in a person's words.")
    price: Optional[Dict[str, Any]] = field(
        "price", doc="A purchase's price: ``amount_usd``, ``recurrence``, ``terms`` and ``renewal``; None for "
        "anything else.",
    )
    reason: Optional[str] = field("reason", doc="Why it waits for a person.")
    operation: str = field("operation", doc="The API operation it calls, by name (``phone_numbers_create``).")
    method: Optional[str] = field("method")
    path: Optional[str] = field("path")
    arguments: Dict[str, Any] = field("arguments", doc="Its arguments as the page shows them, secrets masked.")
    connection: Dict[str, Any] = field(
        "connection", doc="Who made it: ``kind`` (``assistant``, ``agent``, ``connected_app`` or ``key``) and "
        "``name``.",
    )
    user_id: Optional[str] = field("user_id", doc="The user it acts for (None for your account).")
    operation_id: str = field(
        "operation_id", doc="The held call's operation: ``noclick.Operation.from_id(...).wait()`` gives what it "
        "returned once approved, or raises once declined or expired.",
    )
    impact: Optional[Dict[str, Any]] = field("impact", doc="What a deletion takes with it; None for anything else.")
    consent: List[Dict[str, Any]] = field(
        "consent", doc="Terms a person accepts by approving it (each ``terms``, ``title``, ``url``): only the owner "
        "approves such a call.",
    )
    sent_to: List[str] = field("sent_to", doc="Where NoClick sent the owner its link: ``whatsapp``, ``imessage``, "
                               "``email``, or ``web`` (a card in the chat they were watching); empty when it reached "
                               "nobody and waits for your code.")
    created_at: Any = field("created_at", parse_time)
    expires_at: Any = field("expires_at", parse_time, doc="When it lapses unanswered (a day after it was held).")
    decided_at: Any = field("decided_at", parse_time)
    decided_by: Optional[str] = field(
        "decided_by", doc="Who decided: ``owner`` (signed in, or from NoClick's link) or ``code``; None while "
        "pending.",
    )
    decided_by_key: Optional[Dict[str, Any]] = field(
        "decided_by_key", doc="The key whose code decided (``key_id``, ``key_name``); None otherwise.",
    )
    note: Optional[str] = field("note", doc="What whoever decided wrote with it.")

    @classmethod
    def from_id(cls, approval_id: str, *, client: Optional[Client] = None) -> "Approval":
        """A lazy reference to an approval by its id (an ``noclick.ApprovalRequired``'s ``approval_id``).

        Returns:
            The approval; it loads the first time it's used.

        Usage::

            approval = noclick.Approval.from_id(held.approval_id)
            print(approval.status, approval.action, approval.price)
        """
        return cls._new(hints={"id": approval_id}, client=client, user=None)

    async def _load(self) -> Dict[str, Any]:
        return await self._request("GET", self._path(), user=None)

    def _path(self, suffix: str = "") -> str:
        return f"/v1/approvals/{quote(str(self._known('id')), safe='')}{suffix}"

    @synced
    @classmethod
    async def list(
        cls, *, status: Optional[str] = None, limit: Optional[int] = None, user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> List["Approval"]:
        """Calls held for your account's owner's yes, newest first: the first 20, or the first ``limit`` (at
        most 100), with ``status`` one of ``pending``, ``approved``, ``declined``, ``expired``, ``used`` or
        ``canceled``. Acting for a user, that user's alone.

        Returns:
            Each approval as its page shows it.

        Usage::

            for approval in noclick.Approval.list(status="pending"):
                print(approval.action, approval.connection["name"], approval.expires_at)
        """
        return await list_all("/v1/approvals", lambda raw, _scope: cls._new(raw=raw, client=client, user=None),
                              params={"status": status}, user=user, limit=limit, client=client)

    async def _answer(self, approved: bool, note: Optional[str]) -> "Approval":
        self._raw = await resolve_client(self._client).request(
            "POST", self._path("/answer"), json=compact(approved=approved, note=note), user=None)
        return self

    @synced
    async def approve(self, *, note: Optional[str] = None) -> "Approval":
        """Approve it from your own code, with one of your account's secret keys that names the
        ``approvals:answer`` scope; NoClick then runs the call itself, once, exactly as it was held. Refused
        with ``noclick.PermissionDenied`` for the key the call was made with, a call whose terms a person
        accepts, one needing a scope the key lacks or only the owner makes, a key acting for a user, and a key
        without the scope; with ``noclick.SpendCapExceeded`` when its price, beside what the key spent and
        approved this month, is past the key's own monthly cap.

        Returns:
            This approval, answered: ``status`` is ``approved``, then ``used`` once the call ran;
            ``decided_by`` is ``code``.

        Usage::

            approval = noclick.Approval.from_id(held.approval_id)
            approval.approve(note="Within this week's budget.")
            noclick.Operation.from_id(approval.operation_id).wait()
        """
        return await self._answer(True, note)

    @synced
    async def decline(self, *, note: Optional[str] = None) -> "Approval":
        """Decline it from your own code, as ``approve`` answers it: the call never runs, and whoever made it
        is told why, with your ``note``. A call whose terms a person accepts may be declined from code too.

        Returns:
            This approval, answered: ``status`` is ``declined``.

        Usage::

            for approval in noclick.Approval.list(status="pending"):
                if approval.impact:
                    approval.decline(note="Deletions wait for Monday's review.")
        """
        return await self._answer(False, note)
