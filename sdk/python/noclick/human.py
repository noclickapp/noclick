"""Humans: ask a person, get an approval, send a notice, request a connection."""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from datetime import timedelta
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union

from ._client import Client, path_segment, resolve_client
from ._object import Page, compact, csv, list_all, list_page
from ._sync import synced
from ._scope import AMBIENT, resolve_scope, user_ref
from .connection import Connection, ConnectLink
from .operation import Many, Operation, OperationSummary, _with_kinds, register_result


def _request_params(status: Many, status_not: Many, kind: Many, answerable: Optional[str]) -> Dict[str, Any]:
    return {"status": csv(status), "status_not": csv(status_not), "kind": csv(kind), "answerable": answerable}


@dataclass(frozen=True)
class Answer:
    """What the person chose (``choice``) and/or wrote (``text``). A ``pick``'s answer names the
    choice in the account too (``value``: a repository's ``owner/name``, a channel's id); a question
    asked with ``multiple`` names each one they chose (``choices``, and a pick's ``values``). A
    ``connect`` question's names the connection set on the step (``connection``, its ref, also its
    ``value``; ``choice`` its name), a ``secret`` question's the secret its values went into
    (``secret``), never the values."""

    choice: Optional[str]
    text: Optional[str]
    raw: Any = dc_field(repr=False)
    value: Optional[str] = None
    choices: List[str] = dc_field(default_factory=list)
    values: List[str] = dc_field(default_factory=list)
    connection: Optional[str] = None
    secret: Optional[str] = None

    def __str__(self) -> str:
        return self.choice or ", ".join(self.choices) or self.text or self.secret or ""


@dataclass(frozen=True)
class OwnerEmail:
    """An email confirmed for the owner: ``status`` is ``added``, or ``verified`` when an
    agent's turn confirmed it (it's added once that turn ends); ``merged`` when an account
    that already had the email takes this one in."""

    email: str
    status: str
    merged: bool


@dataclass(frozen=True)
class OwnerLine:
    """One of NoClick's own numbers the owner texts it on (``Human.reach``): ``app`` is
    ``whatsapp`` or ``imessage``."""

    app: str
    number: str


@dataclass(frozen=True)
class OwnerEmailAddress:
    """The address the owner emails their assistant at (``OwnerReach.email``): ``paused`` when
    the owner turned its mail off (the address stays theirs), ``from_anyone`` when anyone's mail
    reaches the assistant, not only the owner's."""

    address: str
    paused: bool
    from_anyone: bool


@dataclass(frozen=True)
class OwnerReach:
    """Where the owner texts NoClick (``Human.reach``): NoClick's own numbers, one for each app
    it answers on, whether a phone of the owner's is linked to the account (which one is never
    said), and the address they email their assistant at (``None`` before it has one)."""

    lines: List[OwnerLine]
    phone_linked: bool
    email: Optional[OwnerEmailAddress] = None


def _read_answer(result: Any, _op: Operation) -> Answer:
    if isinstance(result, dict):
        return Answer(result.get("choice"), result.get("text"), result, value=result.get("value"),
                      choices=list(result.get("choices") or []), values=list(result.get("values") or []),
                      connection=result.get("connection"), secret=result.get("secret"))
    return Answer(None, None if result is None else str(result), result)


def _read_approval(result: Any, _op: Operation) -> bool:
    return bool(result.get("approved")) if isinstance(result, dict) else bool(result)


def _read_notice(result: Any, _op: Operation) -> None:
    return None


register_result("human.ask", _read_answer)
register_result("human.approve", _read_approval)
register_result("human.notify", _read_notice)


_HUMAN_KINDS = ("human.ask", "human.approve", "human.notify")


class HumanRequest(Operation):
    """A request to a person; also the operation that finishes when they answer."""

    _request_view: Dict[str, Any] = {}

    @classmethod
    def _from_view(cls, view: Dict[str, Any], *, client: Optional[Client], user: Any) -> "HumanRequest":
        """From a request view (a listing row): the operation stays lazy."""
        hints = compact(id=view.get("operation_id"), kind=f"human.{view['kind']}" if view.get("kind") else None)
        request = cls._new(hints=hints, client=client, user=user)
        request._request_view = dict(view)
        return request

    @classmethod
    def _held(cls, approval: Dict[str, Any], *, client: Optional[Client], user: Any) -> Optional["HumanRequest"]:
        """The request a held call waits on, from its ``approval_required`` details (``operation``,
        ``request_id``, ``approve_url``); None when your key can't read it (a user's session, or a key
        pinned to the user, for a call someone else approves). An approval asked as your account (the
        owner's, or a person's a rule names) is waited on as your account."""
        payload = approval.get("operation")
        if not isinstance(payload, (dict, str)):
            return None
        if isinstance(payload, dict) and "user_id" in payload and payload["user_id"] is None:
            user = None
        request = cls._from_payload(payload, client=client, user=user, kind="human.approve")
        request._request_view = compact(id=approval.get("request_id"), url=approval.get("approve_url"))
        return request

    @synced
    @classmethod
    async def list(
        cls, *, status: Many = None, status_not: Many = None, kind: Many = None, answerable: Optional[str] = None,
        limit: Optional[int] = None, user_filter: Any = None, user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> List["HumanRequest"]:
        """Requests your code and agents sent, newest first (or the first ``limit``).
        ``answerable="owner"``: only those the signed-in account owner may answer;
        ``answerable="code"``: only those your code may answer with ``approve`` or
        ``decline``. A call NoClick holds for the account's owner (a purchase or a
        deletion, whose ``request["owner_only"]`` is true) is listed only for a key that
        names the ``approvals:answer`` scope, and never one made with that key or one
        whose terms a person accepts (see ``noclick.Approval``).

        Returns:
            Every matching request, fetched page by page. Each is also the
            operation you can ``wait()`` on; ``request_status`` is the request's own status.

        Usage::

            for request in noclick.HumanRequest.list(status="pending", kind="approve"):
                print(request.request["message"], request.url)

            waiting_on_you = noclick.HumanRequest.list(answerable="owner")
            yours_to_answer = noclick.HumanRequest.list(status="pending", kind="approve", answerable="code")
        """
        return await list_all(
            "/v1/humans/requests", lambda raw, scope: cls._from_view(raw, client=client, user=scope),
            params=_request_params(status, status_not, kind, answerable),
            user=user, user_filter=user_filter, limit=limit, client=client,
        )

    @synced
    @classmethod
    async def list_page(
        cls, *, cursor: Optional[str] = None, limit: Optional[int] = None, status: Many = None,
        status_not: Many = None, kind: Many = None, answerable: Optional[str] = None,
        user_filter: Any = None, user: Any = AMBIENT, client: Optional[Client] = None,
    ) -> Page:
        """One page of requests; pass ``next_cursor`` back as ``cursor``.

        Returns:
            A page whose ``data`` holds the requests and whose ``next_cursor`` is ``None`` on the last page.

        Usage::

            page = noclick.HumanRequest.list_page(status="pending", limit=50)
            while True:
                for request in page.data:
                    print(request.request_status, request.url)
                if page.next_cursor is None:
                    break
                page = noclick.HumanRequest.list_page(status="pending", limit=50, cursor=page.next_cursor)
        """
        return await list_page(
            "/v1/humans/requests", lambda raw, scope: cls._from_view(raw, client=client, user=scope),
            params=_request_params(status, status_not, kind, answerable),
            user=user, user_filter=user_filter, cursor=cursor, limit=limit, client=client,
        )

    @synced
    @classmethod
    async def retrieve(cls, request_id: str, *, user: Any = AMBIENT, client: Optional[Client] = None) -> "HumanRequest":
        """One request by its own id (a ``request_id``, the ``/h/{id}`` page's): what it asks, how it stands
        (``request_status``) and, once answered, the answer. A user reads only their own; any other raises
        ``noclick.NotFound``. Answer it with ``answer``, ``approve`` or ``decline``.

        Returns:
            The request.

        Usage::

            request = noclick.HumanRequest.retrieve("hr_3f2a1c9e")
            if request.request_status == "pending":
                request.approve(note="Go ahead")
        """
        scope = resolve_scope(user)
        view = await resolve_client(client).request("GET", f"/v1/humans/requests/{path_segment(request_id)}",
                                                    user=scope) or {}
        return cls._from_view(view, client=client, user=scope)

    @synced
    @classmethod
    async def summary(cls, **filters: Any) -> OperationSummary:
        """How many human-request operations (ask, approve, notify) match, by operation
        status; takes ``Operation.summary``'s filters except ``kind``.

        Returns:
            The number that match in ``total``, and per operation status in ``by_status``.

        Usage::

            counts = noclick.HumanRequest.summary(status="live")
            print(counts.total, counts.by_status)
        """
        return await Operation.summary.aio(**_with_kinds(filters, _HUMAN_KINDS, "HumanRequest.summary"))

    @property
    def request_id(self) -> Optional[str]:
        """The request's own id (the operation's is ``id``)."""
        return self._request_view.get("id")

    @property
    def request_status(self) -> Optional[str]:
        """``pending``, ``answered``, ``delivered``, ``expired`` or ``canceled``."""
        return self._request_view.get("status")

    def _repr_parts(self) -> list:
        url = self.console_url
        parts = [f"{k}={self._known(k)!r}" for k in ("id", "kind", "status")]
        return parts + ([f"console_url={url!r}"] if url else [])

    @property
    def request(self) -> Dict[str, Any]:
        """The request as created: ``url``, ``delivered_via``, ``undelivered``, ..."""
        return dict(self._request_view)

    @property
    def url(self) -> Optional[str]:
        """The page where the person answers (``/h/{id}``); embed or send it yourself."""
        return self._request_view.get("url")

    @property
    def delivered_via(self) -> List[str]:
        return list(self._request_view.get("delivered_via") or [])

    @property
    def undelivered(self) -> List[Dict[str, Any]]:
        """Channels that failed, each with a ``reason``."""
        return list(self._request_view.get("undelivered") or [])

    @property
    def note(self) -> Optional[str]:
        """What the approver wrote with their answer (``None`` until answered, or if they wrote nothing)."""
        result = self._known("result")
        if isinstance(result, dict) and "note" in result:
            return result["note"]
        return self._request_view.get("note")

    async def _answer(self, body: Dict[str, Any]) -> "HumanRequest":
        if not self.request_id:
            raise ValueError("This request has no request id to answer; list it with noclick.HumanRequest.list(...).")
        self._request_view = dict(await self._request(
            "POST", f"/v1/humans/requests/{path_segment(self.request_id)}/answer", json=compact(**body),
        ) or {})
        return self

    @synced
    async def answer(
        self,
        *,
        choice: Optional[str] = None,
        choices: Optional[Sequence[str]] = None,
        text: Optional[str] = None,
        connection: Any = None,
        secret_values: Optional[Mapping[str, str]] = None,
    ) -> "HumanRequest":
        """Answer a question from your own code, as the person it waits on (who may: as ``approve``
        says). A question takes a ``choice`` (or ``choices`` for one asked with ``multiple``) and/or
        ``text``; a ``connect`` question, a ``connection`` (a ``Connection``, or its ref or name: one of
        the account's that fits), which NoClick sets on the step as your key, so it needs the
        ``workflows`` scope and a key acting for your whole account, never a user's or an agent's own
        tools; a ``secret`` question, ``secret_values`` (a value for each of its keys), kept in the
        secret and never with the answer, which needs the ``secrets`` scope.

        Returns:
            This request, answered: ``request_status`` is ``answered``.

        Usage::

            for request in noclick.HumanRequest.list(status="pending", kind="ask", answerable="code"):
                if request.request.get("connect"):
                    request.answer(connection="work-slack")
        """
        if isinstance(connection, Connection):
            connection = connection._ref()
        return await self._answer({"choice": choice, "choices": list(choices) if choices else None, "text": text,
                                   "connection": connection,
                                   "secret_values": dict(secret_values) if secret_values is not None else None})

    @synced
    async def approve(self, *, note: Optional[str] = None) -> "HumanRequest":
        """Approve it from your own code, as the person it waits on: with a key acting for your
        account, an approval routed to your account (a held call on one of its connections, say);
        with a user's session or inside ``as_user``, one addressed to that user. A held operation call
        then runs exactly as it was held (a held shell command or other tool, the agent makes again
        itself), and the agent gets a turn in the same conversation with its result, its reply going
        out wherever the conversation lives (the chat, the call, or on an email thread the same
        thread: an inbox agent's ``reply`` tool is bound to the thread's latest message, not to the
        message that woke a turn). A call NoClick holds for the account's owner is answered only
        with a key that names the ``approvals:answer`` scope, as ``noclick.Approval.approve`` answers
        it. Anyone else gets ``noclick.PermissionDenied``.

        Returns:
            This request, answered: ``request_status`` is ``answered`` and ``note`` is yours.

        Usage::

            for request in noclick.HumanRequest.list(status="pending", kind="approve", answerable="code"):
                if request.request["details"].get("amount_usd", 0) < 50:
                    request.approve(note="Under $50: fine.")
        """
        return await self._answer({"approved": True, "note": note})

    @synced
    async def decline(self, *, note: Optional[str] = None) -> "HumanRequest":
        """Decline it from your own code, as ``approve`` answers it. A held call never runs; the agent
        gets a turn saying it was declined, with your ``note``, so it can tell the person it was
        acting for why.

        Returns:
            This request, answered: ``request_status`` is ``answered`` and ``note`` is yours.

        Usage::

            [request] = noclick.HumanRequest.list(status="pending", kind="approve", answerable="code", limit=1)
            request.decline(note="Refunds over $500 go through finance; ask the customer for the invoice.")
        """
        return await self._answer({"approved": False, "note": note})


def _via(via: Union[str, Sequence[str]]) -> Union[str, List[str]]:
    if isinstance(via, str):
        return via if via == "auto" else [via]
    return list(via)


def _seconds(expires_in: Union[None, int, float, timedelta]) -> Optional[int]:
    if expires_in is None:
        return None
    if isinstance(expires_in, timedelta):
        return int(expires_in.total_seconds())
    return int(expires_in)


def _pick(pick: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    """The request's ``pick`` as sent: its ``connection`` a name or id, a ``Connection``'s own."""
    if pick is None:
        return None
    body = dict(pick)
    if isinstance(body.get("connection"), Connection):
        body["connection"] = body["connection"]._ref()
    return body


def _step_ask(ask: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    """A ``connect`` or ``secret`` question as sent: its step's workflow by id, a ``Workflow``'s own."""
    if ask is None:
        return None
    body = dict(ask)
    if isinstance(body.get("step"), Mapping):
        step = dict(body["step"])
        workflow = step.pop("workflow", None)
        if workflow is not None:
            step["workflow_id"] = workflow if isinstance(workflow, str) else workflow.id
        body["step"] = step
    if isinstance(body.get("keys"), (list, tuple)):
        body["keys"] = list(body["keys"])
    return body


_TOOLS = ("notify", "ask", "hand_off")


@dataclass(frozen=True)
class HumanOperations:
    """Some of a person's tools for an agent (``human.only(...)``), for ``tools=``."""

    human: "Human"
    tools: List[str]

    async def _tool_refs(self, scope: Any) -> List[Dict[str, Any]]:
        return [{"human": await self.human._address(), "tools": [t for t in _TOOLS if t in self.tools]}]


class Human:
    """A person to reach. ``user.human`` (or ``noclick.Human()``, meaning the
    user current at each call, or the one a session or user-pinned key acts
    for) is the user; ``noclick.Human.owner()`` is your account's owner;
    ``noclick.Human(email=...)`` is anyone else.
    Every method returns an ``Operation``: ``.wait()`` for the outcome.
    In an agent's ``tools=``, a person gives the agent tools that notify them,
    ask them, or hand them the conversation (``only``).

    ``via`` says where a message goes: ``"auto"`` (the default), or a list of
    ``"web"`` (only the page: you pass ``request.url`` on), ``"email"``, and for the
    owner ``"whatsapp"`` and ``"imessage"``, sent from NoClick's own numbers to the
    number they text NoClick from. ``"auto"`` is the app the owner last texted
    NoClick on, else email. ``"sms"`` and ``"call"`` raise ``noclick.NotAvailable``
    for now. What couldn't be sent is listed in ``undelivered``, never implied.

    Usage:
        Reach the person behind a user, or anyone by email::

            user = noclick.User.from_id("user_42")
            user.human.notify("Your export is ready. It's in your dashboard.")
            noclick.Human(email="finance@acme.com").approve("Refund $95.00 to Ana Lima?")

        ``noclick.Human()`` is the user you're acting for, and the only way to
        reach a person from a session or a key pinned to a user::

            with noclick.as_user(noclick.User.from_id("user_42")):
                noclick.Human().ask("Which time works for your cleaning?", options=["Thu 10:30", "Fri 14:00"])
    """

    def __init__(
        self,
        *,
        email: Optional[str] = None,
        phone: Optional[str] = None,
        user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> None:
        self._scope = user
        self._client = client
        if email or phone:
            self._to: Dict[str, Any] = compact(email=email, phone=phone)
        else:
            self._to = {"user": True}

    def __repr__(self) -> str:
        return f"Human(to={self._to!r})"

    @classmethod
    def owner(cls, *, client: Optional[Client] = None) -> "Human":
        """Your account's owner: the person behind the account, reached by email and on
        the app they text NoClick from. Only your account reaches them: it always acts as
        your account, inside ``as_user`` too, and a user's session or a key pinned to a user
        raises ``noclick.PermissionDenied``.

        Returns:
            The owner, to message, ask, put in an agent's ``tools=`` or ``answer_with``.

        Usage:
            Tell the owner something on the app they text NoClick on::

                noclick.Human.owner().notify("The site is live: https://morrowbakery.com")

            Or give an agent a way to reach them::

                assistant = noclick.Agent.from_name(
                    "assistant", create_if_missing=True, instructions="You run the bakery's errands.",
                    tools=["search", noclick.Human.owner()],
                )
        """
        human = cls(user=None, client=client)
        human._to = {"owner": True}
        return human

    @synced
    async def answer_with(self, agent: Any, *, conversation: Optional[str] = None) -> "Human":
        """Send what this person texts or says to NoClick's own numbers (its WhatsApp and
        iMessage numbers and its voice number) to ``agent`` (an ``noclick.Agent`` or id of your
        account's). A text's reply goes back on the app they texted on once the agent's turn
        ends, and texts sent while it's busy go in its next turn, in order; on a call, each thing
        they say is a turn whose reply is read aloud as it's written. ``None`` hands them back to
        NoClick's assistant. Only ``Human.owner()`` reaches NoClick's numbers: your users reach an
        agent on a number of your own (``PhoneNumber.answer_with``).

        ``conversation`` is the agent's conversation each text or call lands in, a template over
        ``{channel}`` (``whatsapp``, ``imessage`` or ``call``); omitted, ``"owner"``. Give an inbox
        and a number the same key and the person's email, calls and texts are one conversation.

        Returns:
            This person.

        Usage:
            Make an agent the owner's assistant on every channel::

                owner = noclick.Human.owner()
                assistant = noclick.Agent.from_name("assistant")
                owner.answer_with(assistant)
                noclick.Inbox.from_name("assistant", create_if_missing=True, agent=assistant, senders="owner",
                                        conversation="owner")
                assistant.message("What's on today?", conversation="owner")   # the same thread
        """
        if self._to != {"owner": True}:
            raise ValueError("Only noclick.Human.owner() texts NoClick's own numbers; give a user a number of your "
                             "own with PhoneNumber.answer_with.")
        from .agent import agent_id

        body = {"agent_id": await agent_id(agent), **compact(conversation=conversation)}
        await resolve_client(self._client).request("POST", "/v1/humans/owner/answer", json=body, user=None)
        return self

    @synced
    async def answering(self) -> Optional[Any]:
        """The agent this person's texts to NoClick's own numbers go to (``answer_with``), or
        ``None`` when NoClick's assistant answers them.

        Returns:
            The ``noclick.Agent``, or ``None``.

        Usage::

            agent = noclick.Human.owner().answering()
            print(agent.name if agent else "NoClick's assistant")
        """
        if self._to != {"owner": True}:
            raise ValueError("Only noclick.Human.owner() texts NoClick's own numbers.")
        from .agent import Agent

        raw = await resolve_client(self._client).request("GET", "/v1/humans/owner/answer", user=None)
        found = (raw or {}).get("agent_id")
        return Agent.from_id(found, client=self._client, user=None) if found else None

    @synced
    async def reach(self) -> OwnerReach:
        """NoClick's own numbers the owner texts it on, whether a phone of theirs is linked
        (never which), and the address they email their assistant at (``email``, ``None``
        before it has one). Show a number only once a phone is linked: a text from a phone the
        account hasn't linked starts an account of its own, and linking one is the owner's,
        signed in to NoClick. Your account's own key reads it, never a user's.

        Returns:
            The ``noclick.OwnerReach``.

        Usage::

            reach = noclick.Human.owner().reach()
            if reach.phone_linked:
                for line in reach.lines:
                    print(f"{line.app}: {line.number}")
        """
        if self._to != {"owner": True}:
            raise ValueError("Only noclick.Human.owner() texts NoClick's own numbers.")
        raw = await resolve_client(self._client).request("GET", "/v1/humans/owner/reach", user=None) or {}
        lines = [OwnerLine(app=line["app"], number=line["number"]) for line in raw.get("lines") or []]
        mail = raw.get("email")
        email = OwnerEmailAddress(address=mail["address"], paused=bool(mail.get("paused")),
                                  from_anyone=bool(mail.get("from_anyone"))) if mail else None
        return OwnerReach(lines=lines, phone_linked=bool(raw.get("phone_linked")), email=email)

    @synced
    async def set_timezone(self, timezone: str) -> None:
        """Where the signed-in owner is, from their browser (an IANA zone such as ``"Europe/London"``):
        the clock of the account's assistant, and of each of its own agents NoClick placed, moves
        there; a zone chosen through the API stays. The signed-in owner's alone: a key raises
        ``noclick.PermissionDenied``.

        Usage::

            noclick.Human.owner().set_timezone("Europe/London")
        """
        if self._to != {"owner": True}:
            raise ValueError("Only noclick.Human.owner() says where the owner is.")
        await resolve_client(self._client).request("PUT", "/v1/humans/owner/timezone", json={"timezone": timezone},
                                                   user=None)

    @synced
    async def add_email(self, email: str) -> None:
        """Send a code to ``email`` for the owner of an account made by texting NoClick (which
        has none); ``confirm_email`` with the code makes it theirs. Raises
        ``noclick.Conflict`` when the account already has an email, ``noclick.RateLimited``
        after too many codes.

        Usage::

            owner = noclick.Human.owner()
            owner.add_email("maya@morrowbakery.com")
            owner.confirm_email(input("The code in that email: "))
        """
        if self._to != {"owner": True}:
            raise ValueError("Only noclick.Human.owner() takes an email this way.")
        await resolve_client(self._client).request("POST", "/v1/humans/owner/email", json={"email": email},
                                                   user=None)

    @synced
    async def confirm_email(self, code: str) -> OwnerEmail:
        """The code ``add_email`` sent: on a match the email is the owner's to sign in with,
        or, when an account already has it, that account takes this one in (``merged``).
        Whether an account has the email is said only once the code matches.

        Returns:
            The confirmed email.

        Usage::

            confirmed = noclick.Human.owner().confirm_email("482913")
            print(confirmed.email, "merged" if confirmed.merged else "added")
        """
        if self._to != {"owner": True}:
            raise ValueError("Only noclick.Human.owner() takes an email this way.")
        raw = await resolve_client(self._client).request("POST", "/v1/humans/owner/email/confirm",
                                                         json={"code": code}, user=None)
        return OwnerEmail(email=raw["email"], status=raw["status"], merged=bool(raw.get("merged")))

    async def _address(self) -> Dict[str, Any]:
        """Who this person is in an agent's tools: an email or phone, a user by your id, or
        (``noclick.Human()``) the user each turn acts for."""
        if self._to != {"user": True} or self._scope is AMBIENT:
            return dict(self._to)
        user_id = await user_ref(resolve_scope(self._scope))
        return {"user_id": user_id} if user_id else dict(self._to)

    async def _tool_refs(self, scope: Any) -> List[Dict[str, Any]]:
        return [{"human": await self._address(), "tools": list(_TOOLS)}]

    def only(self, *tools: str) -> HumanOperations:
        """Some of the tools this person gives an agent, for ``tools=``. In an agent's tools
        a ``Human`` gives it three, each addressed only to this person: ``notify`` (a
        message), ``ask`` (a question, with ``options`` if it has some, or a ``pick`` from one of
        their connected accounts: the turn waits,
        ``awaiting_human``, and the answer arrives as the conversation's next turn) and
        ``hand_off`` (the conversation goes to this person: a page and an email with the
        transcript, the agent's summary and a reply box; their replies post as ``person``
        messages, the agent stays quiet until ``agent.hand_back(conversation)``, and on a
        call it's transferred to the person's ``phone``). Policy names them
        ``human.notify``, ``human.ask`` and ``human.hand_off``.

        ``noclick.Human()`` there is the user each turn acts for; ``user.human`` is that user;
        ``noclick.Human.owner()`` is your account's owner and ``noclick.Human(email=..., phone=...)``
        anyone else, neither of which a user's own agent may name.

        Returns:
            A ref to just those tools of this person, to list in ``tools=``.

        Usage:
            Let a support agent ask a manager before a big refund, but never hand them the chat::

                manager = noclick.Human(email="ops@acme.com", phone="+14155550123")
                support = noclick.Agent.from_name(
                    "support", create_if_missing=True,
                    instructions="You answer billing questions. Ask the manager before refunding over $200.",
                    tools=["stripe.create_refund", manager.only("notify", "ask")],
                )

            Or let it hand an upset customer to a person, who replies from their page::

                person = noclick.Human(email="support-lead@acme.com")
                support = noclick.Agent.from_name(
                    "support", create_if_missing=True,
                    instructions="Hand the conversation to a person when the customer asks for one.",
                    tools=["search", person.only("hand_off")],
                )
        """
        if not tools:
            raise ValueError("only() takes at least one of 'notify', 'ask' and 'hand_off'")
        unknown = [t for t in tools if t not in _TOOLS]
        if unknown:
            raise ValueError(f"A person's tools are 'notify', 'ask' and 'hand_off', not {unknown[0]!r}")
        return HumanOperations(self, list(tools))

    async def _send(self, kind: str, body: Dict[str, Any]) -> HumanRequest:
        raw = await resolve_client(self._client).request(
            "POST", "/v1/humans/requests",
            json={"kind": kind, "to": self._to, **compact(**body)},
            user=self._scope,
        )
        request = HumanRequest._from_payload(raw, client=self._client, user=self._scope, kind=f"human.{kind}")
        request._request_view = dict(raw.get("request") or {}) if isinstance(raw, dict) else {}
        return request

    @synced
    async def ask(
        self,
        message: str,
        *,
        options: Optional[Sequence[str]] = None,
        pick: Optional[Mapping[str, Any]] = None,
        multiple: bool = False,
        connect: Optional[Mapping[str, Any]] = None,
        secret: Optional[Mapping[str, Any]] = None,
        via: Union[str, Sequence[str]] = "auto",
        expires_in: Union[None, int, float, timedelta] = None,
    ) -> HumanRequest:
        """Ask a question; ``.wait()`` returns an ``Answer``.

        ``pick`` asks, in place of ``options``, for something in a connected account:
        ``{"connection": ..., "field": ..., "arguments": ...}``, the connection (a ``Connection``,
        or its id or name) and the field its lookup lists (``connection.lookup`` names them:
        ``repository``, ``team_id``, ``channel``), with the values that field depends on. NoClick
        reads the choices from the account, the person picks from it, and an account that holds
        just one answers at once with it, asking nobody. ``multiple`` lets them choose several of
        the options, or of a pick's choices.

        ``connect`` asks the owner which of the account's connections a workflow step uses:
        ``{"integration": "slack", "step": {"workflow": wf, "step_id": "post"}}`` (or
        ``credential_type`` in place of ``integration``; ``step["slot"]`` narrows it to one kind).
        Their page lists the connections that fit and connects another with the provider's own
        sign-in; NoClick sets the one they choose on the step as them, never as you, and an account
        holding just one that fits answers at once with it. Needs the ``workflows`` scope.

        ``secret`` asks for a secret's values: ``{"name": "warehouse", "keys": ["WAREHOUSE_TOKEN"]}``,
        typed on NoClick's page (its link carries a key, so the request's id alone opens nothing),
        kept as the account's secret ``name`` (made, or those keys replaced) and never shown to you
        or a model; with ``"step": {"workflow": wf, "step_id": "agent"}`` (the owner's only), the
        agent step's shell gets it too. Needs the ``secrets`` scope. Your code can answer either
        with ``HumanRequest.answer``.

        Returns:
            The request, already sent. ``wait()`` blocks until the person answers
            and gives what they picked (``choice``, a pick's ``value`` beside it; each of
            several in ``choices`` and ``values``) and wrote (``text``).

        Usage:
            Offer choices, then wait for the pick::

                human = noclick.User.from_id("user_42").human
                request = human.ask(
                    "Which time works for your cleaning?", options=["Thu 10:30", "Fri 14:00", "Neither"],
                )
                answer = request.wait()
                print(answer.choice or answer.text)

            Ask which repositories, from the person's own GitHub::

                answer = noclick.Human.owner().ask(
                    "Which repositories should the reviewer watch?",
                    pick={"connection": "github", "field": "repository"}, multiple=True,
                ).wait()
                print(answer.values)   # ['acme/site', 'acme/api']

            With ``via=["web"]`` nothing is sent: pass the answer page on
            yourself. ``expires_in`` is in seconds (or a ``timedelta``)::

                human = noclick.User.from_id("user_42").human
                request = human.ask("What should we call your workspace?", via=["web"], expires_in=3600)
                print(request.url)

            Ask the owner which Slack a step posts with, and for the token an agent step needs::

                wf = noclick.Workflow.from_id("wf_123")
                owner = noclick.Human.owner()
                slack = owner.ask("Which Slack should the Post step use?",
                                  connect={"integration": "slack", "step": {"workflow": wf, "step_id": "post"}})
                token = owner.ask("The warehouse API token, please.",
                                  secret={"name": "warehouse", "keys": ["WAREHOUSE_TOKEN"],
                                          "step": {"workflow": wf, "step_id": "agent"}})
                print(slack.wait().connection, token.wait().secret)
        """
        return await self._send("ask", {
            "message": message, "options": list(options) if options else None, "pick": _pick(pick),
            "multiple": True if multiple else None, "connect": _step_ask(connect), "secret": _step_ask(secret),
            "via": _via(via), "expires_in_s": _seconds(expires_in),
        })

    @synced
    async def approve(
        self,
        message: str,
        *,
        details: Any = None,
        via: Union[str, Sequence[str]] = "auto",
        expires_in: Union[None, int, float, timedelta] = None,
    ) -> HumanRequest:
        """Ask for a yes/no; ``.wait()`` returns ``True`` when approved.

        Returns:
            The request, already sent. ``wait()`` gives ``True`` if they approve
            and ``False`` if they decline.

        Usage:
            Put what the person needs to decide in ``details``; it's shown on the page::

                finance = noclick.Human(email="finance@acme.com")
                approved = finance.approve(
                    "Refund $95.00 to Ana Lima?",
                    details={"invoice": "INV-1042", "reason": "Charged for a cancelled visit"},
                ).wait()
                if approved:
                    issue_refund()

            In a web server, save the request's id and pick the answer up later::

                request = noclick.User.from_id("user_42").human.approve("Publish the new pricing page?")
                save(request.id)
                approved = noclick.Operation.from_id(saved_id).wait()   # later, from anywhere
        """
        return await self._send("approve", {
            "message": message, "details": details, "via": _via(via), "expires_in_s": _seconds(expires_in),
        })

    @synced
    async def notify(self, message: str, *, via: Union[str, Sequence[str]] = "auto") -> HumanRequest:
        """Send a notice (the operation succeeds once it's sent).

        Returns:
            The request, already sent and its operation already succeeded, so
            ``wait()`` returns ``None`` at once. ``undelivered`` names any channel that failed.

        Usage::

            human = noclick.User.from_id("user_42").human
            human.notify("Your export is ready. It's in your dashboard.")
        """
        return await self._send("notify", {"message": message, "via": _via(via)})

    @synced
    async def connect(
        self,
        connection: Any,
        *,
        reason: Optional[str] = None,
        redirect_url: Optional[str] = None,
    ) -> ConnectLink:
        """Ask this person to connect ``connection`` (a ``Connection`` or its
        name, this person's own); ``.wait()`` returns the connected
        ``Connection``.

        Returns:
            The link, already emailed: its ``url`` and when it ``expires_at``.
            ``wait()`` gives the connected ``Connection``.

        Usage:
            Email the user a link to connect their calendar, and wait until they have::

                user = noclick.User.from_id("user_42")
                calendar = noclick.Connection.from_name(
                    "calendar", integration="google_calendar", create_if_missing=True, user=user,
                )
                calendar = user.human.connect(calendar, reason="to book your appointments").wait()

            A connection the user already has can be named instead::

                user = noclick.User.from_id("user_42")
                user.human.connect("calendar", redirect_url="https://app.example.com/settings")
        """
        if isinstance(connection, str):
            connection = Connection.from_name(connection, user=self._scope, client=self._client)
        return await connection.connect_link.aio(reason=reason, redirect_url=redirect_url, send_to=self._to)
