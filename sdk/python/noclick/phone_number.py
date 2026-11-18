"""Phone numbers: a real number your agents answer and call from.

    [pick] = noclick.PhoneNumber.available(country="US", area_code="415", limit=1)
    number = noclick.PhoneNumber.buy(pick, max_monthly_usd=5)
    number.answer_with(host)                              # inbound calls reach this agent
    call = number.call("+14155550100", goal="Confirm Friday's 3pm booking.").wait()
    print(call.text)                                      # the transcript, one turn per line

Numbers in the countries NoClick sells in (``PhoneNumber.coverage()``), each at
its own price: billed monthly, and once when bought where its carrier charges
that; available on accounts with the phone feature (``noclick.NotAvailable``
otherwise). A number whose country asks for documents is bought with them
(``PhoneNumber.upload_document``, then ``requirements=`` on ``buy``): the
carrier reviews them first, so ``buy`` returns a ``PhoneNumberOrder`` that
becomes the number once the carrier approves it. A number you keep with your own
phone provider is connected through that provider account
(``PhoneNumber.connect``), which bills it. Numbers have names
(``PhoneNumber.from_name``). The answering agent can transfer a call to a
person, a caller proven to be one of your users runs as that user,
``callers`` says who gets through, calls both ways are listed, and a number can
record its calls. Invite-only beta: the agent texting the caller
(``answer_with(texts=True)``, under a ``TextingRegistration`` of your business
with the US carriers), porting numbers in (``PhoneNumber.port_in``) and moving
one away (``PhoneNumber.transfer_out``).
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass, field as dc_field
from typing import Any, Dict, List, Mapping, Optional, Union

from ._client import Client, resolve_client
from ._designed import designed, designed_params
from ._object import (
    UNSET, Page, _Object, check_unchanged, compact, field, iso_time, list_all, list_page, paginate, parse_time, ref_id,
)
from ._sync import synced
from ._scope import AMBIENT, resolve_scope
from .agent import agent_id
from .connection import Connection
from .exceptions import Conflict, NotFound
from .operation import Operation, _with_kinds, register_result

# Who a number answers: every caller, only your users, or only its owner (each a verified phone the carrier attests).
CALLERS = ("anyone", "users", "owner")
DIRECTIONS = ("inbound", "outbound")


# The kinds of number, as the carriers name them.
NUMBER_TYPES = ("local", "mobile", "toll_free", "national", "shared_cost")


@dataclass(frozen=True)
class AvailableNumber:
    """A number you can buy: ``noclick.PhoneNumber.buy(available, max_monthly_usd=...)``.

    ``monthly_usd`` it costs a month and ``upfront_usd`` once, when it's bought.
    ``requirements["needs"]`` is what its country asks before it's sold: ``none``,
    ``address`` (pass ``address=`` to ``buy``), ``documents`` (pass ``requirements=``
    to ``buy`` too, uploading each document with ``PhoneNumber.upload_document``;
    the carrier reviews them before the number is yours) or ``steps`` (it asks a
    step that can't be taken here, so it can't be bought through the API yet).
    ``requirements["items"]`` lists each thing asked: its ``id``, ``kind``
    (``address``, ``contact``, ``textual``, ``document`` or ``step``), ``name``,
    ``description``, the carrier's ``example`` and, for a textual one that takes
    only some answers, those ``values``. ``texting``: ``registration`` (a US local number,
    which texts under your business's US carrier registration), ``unavailable``
    (texting from its country, or from a toll-free number, isn't available yet) or
    ``none`` (it can't text)."""

    number: str
    monthly_usd: Optional[float]
    locality: Optional[str]
    region: Optional[str]
    raw: Dict[str, Any] = dc_field(repr=False)
    country: Optional[str] = None
    type: Optional[str] = None
    upfront_usd: Optional[float] = None
    capabilities: List[str] = dc_field(default_factory=list)
    requirements: Dict[str, Any] = dc_field(default_factory=dict)
    texting: Optional[str] = None

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "AvailableNumber":
        return cls(raw.get("number"), raw.get("monthly_usd"), raw.get("locality"), raw.get("region"), raw,
                   raw.get("country"), raw.get("type"), raw.get("upfront_usd"), list(raw.get("capabilities") or []),
                   dict(raw.get("requirements") or {}), raw.get("texting"))

    def __str__(self) -> str:
        return self.number


@dataclass(frozen=True)
class NumberHolder:
    """Who a number is registered to, for a country that asks who holds it (one of its
    requirements' ``kind`` is ``address`` or ``contact``): first and last ``name`` (and the
    business's, for a business's number) at a postal address; ``region`` is the
    state, province or county where the country has one, ``country`` ISO alpha-2.
    ``phone`` (E.164) is a number to contact them on, required where one of the
    requirements' ``kind`` is ``contact``."""

    name: str
    street: str
    city: str
    postal_code: str
    country: str
    business_name: Optional[str] = None
    street2: Optional[str] = None
    region: Optional[str] = None
    phone: Optional[str] = None

    def _wire(self) -> Dict[str, Any]:
        return compact(name=self.name, business_name=self.business_name, street=self.street, street2=self.street2,
                       city=self.city, region=self.region, postal_code=self.postal_code, country=self.country,
                       phone=self.phone)


@dataclass(frozen=True)
class NumberCoverage:
    """A country numbers are for sale in, the kinds in stock there, the kinds that can text, the kinds
    bought with documents the carrier reviews first (``documents_types``) and the kinds that ask a step
    that can't be taken here (``steps_types``: these can't be bought through the API yet)."""

    country: str
    types: List[str]
    texting_types: List[str]
    documents_types: List[str] = dc_field(default_factory=list)
    steps_types: List[str] = dc_field(default_factory=list)


@dataclass(frozen=True)
class NumberDocument:
    """A document you uploaded for one of a number's requirements (``PhoneNumber.upload_document``): pass
    it (or its ``id``) in ``requirements`` when you buy. The carrier holds the file; NoClick keeps its
    name and what it's for. One no purchase names within 25 minutes is gone; one a purchase named can be
    named again for your next number."""

    id: str
    requirement_id: str
    requirement_name: str
    filename: str
    uploaded_at: Any
    raw: Dict[str, Any] = dc_field(repr=False, default_factory=dict)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "NumberDocument":
        return cls(raw["id"], raw.get("requirement_id"), raw.get("requirement_name"), raw.get("filename"),
                   parse_time(raw.get("uploaded_at")), raw)

    def __str__(self) -> str:
        return self.id


def _requirements_wire(requirements: Optional[Mapping[str, Any]]) -> Optional[Dict[str, str]]:
    """``requirements`` on the wire: each answer's text, or a document's id."""
    if requirements is None:
        return None
    return {key: value.id if isinstance(value, NumberDocument) else value for key, value in requirements.items()}


@dataclass(frozen=True)
class NumberPlace:
    """A place numbers of a kind are for sale in: a city (``locality``), or an area code in North America."""

    kind: str
    value: str
    region: str


@dataclass(frozen=True)
class ConnectableNumber:
    """A number in your phone provider account, from ``noclick.PhoneNumber.connectable``:
    connect it with ``noclick.PhoneNumber.connect(connectable, connection=...)``.
    ``label`` is the provider account's own name for it. ``routed_elsewhere`` means its calls go
    somewhere today (a URL, an application or a SIP trunk): answering it takes them over, and
    ``disconnect()`` puts that back. ``phone_number_id`` is the NoClick number it's already
    connected as, and ``agent_id`` the agent answering it (both None when it isn't connected):
    connecting it again raises ``noclick.Conflict``, since one number rings one agent."""

    number: str
    label: Optional[str]
    routed_elsewhere: bool
    phone_number_id: Optional[str]
    agent_id: Optional[str]
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "ConnectableNumber":
        return cls(
            raw.get("number"), raw.get("label"), bool(raw.get("routed_elsewhere")),
            raw.get("phone_number_id"), raw.get("agent_id"), raw,
        )

    def __str__(self) -> str:
        return self.number


@dataclass(frozen=True)
class PhoneCall:
    """One call on a number, answered (``direction`` ``inbound``) or placed
    (``outbound``). ``transcript`` (turns of ``{role, text, at}``) is filled in
    at hang-up; ``text`` reads it as lines. ``status`` is ``calling`` while it
    runs and ends as ``completed``, ``not_connected``, ``refused`` (a caller the
    number's ``callers`` turned away, ``error`` says why), ``failed`` or ``lost``.
    ``PhoneNumber.get_call`` reads one while it goes, with what was said so far
    (``lines``)."""

    id: Optional[str]
    direction: Optional[str]
    to: Optional[str]
    from_number: Optional[str]
    status: Optional[str]
    goal: Optional[str]
    agent_id: Optional[str]
    transcript: List[Dict[str, Any]]
    seconds: Optional[float]
    #: What the call was charged, as your usage shows it (``None`` until it has ended and its charge is recorded,
    #: or when it never connected).
    cost_usd: Optional[float]
    error: Optional[str]
    created_at: Any
    ended_at: Any
    #: The user the call ran as: on an account number, a caller proven to be one of your users (their
    #: verified phone, attested by the carrier), whatever the number's ``callers``; on a user's number, its user.
    user_id: Optional[str]
    #: A signed link to the call's recording, both sides in one file, valid for an hour from when you read
    #: the call (``None`` unless the number records its calls, or once the recording is deleted).
    recording_url: Optional[str]
    #: Where the agent handed the caller (``to``) and whether they picked up (``status`` ``answered`` with
    #: the transfer's ``seconds``, or ``unanswered``); ``None`` for a call nobody was handed.
    transfer: Optional[Dict[str, Any]]
    #: When the call reached the agent's voice: a placed call's person picked up (``None`` while it rings, and
    #: for a call nobody answered).
    answered_at: Any
    #: ``hang_up`` when ``PhoneNumber.hang_up`` ended it; ``None`` when the other end, the agent or the call's
    #: limit did, and while it goes.
    ended_by: Optional[str]
    #: What was said so far, turn by turn (``{turn, who, text}``, ``who`` ``them`` or ``agent``), as
    #: ``PhoneNumber.get_call`` reads a call while it goes; empty in a number's ``calls()``.
    lines: List[Dict[str, Any]]
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Any) -> "PhoneCall":
        raw = raw if isinstance(raw, dict) else {}
        return cls(
            raw.get("id"), raw.get("direction"), raw.get("to"), raw.get("from"), raw.get("status"),
            raw.get("goal"), raw.get("agent_id"), list(raw.get("transcript") or []), raw.get("seconds"),
            raw.get("cost_usd"), raw.get("error"), parse_time(raw.get("created_at")), parse_time(raw.get("ended_at")),
            raw.get("user_id"), raw.get("recording_url"), raw.get("transfer"), parse_time(raw.get("answered_at")),
            raw.get("ended_by"), list(raw.get("lines") or []), raw,
        )

    @property
    def text(self) -> str:
        """The transcript as ``role: text`` lines."""
        return "\n".join(f"{turn.get('role')}: {turn.get('text')}" for turn in self.transcript)

    def __str__(self) -> str:
        return self.text


def _read_call(result: Any, op: Operation) -> PhoneCall:
    return PhoneCall._from(result)


async def _call_target(call: Any, user: Any, client: Optional[Client]):
    """The call ``call`` names and who reads it: an id, with ``user`` and ``client``; or the operation
    ``number.call()`` returned, with its own client and user unless they're given."""
    if not isinstance(call, Operation):
        if not isinstance(call, str) or not call:
            raise TypeError(f"call is a call's id or the operation number.call() returned, not {type(call).__name__}")
        return call, resolve_client(client), resolve_scope(user)
    raw = await call._ensure()
    call_id = raw.get("call_id") or (raw.get("result") or {}).get("id")
    if not call_id:
        raise TypeError(f"Operation {raw.get('id')} isn't a call: pass a call's id, or what number.call() returned.")
    return (call_id, resolve_client(client) if client is not None else call._api,
            call._call_scope() if user is AMBIENT else user)


register_result("phone.call", _read_call)


@designed
@dataclass(frozen=True)
class PhoneText:
    """A text a number's agent sent a caller (``direction`` ``outbound``) or one the number
    received (``inbound``). ``keyword`` is ``stop``, ``start`` or ``help`` when a received
    text was one: STOP stops texts to its sender, START lets them through again, and both
    are answered in your business's name. ``status`` is ``sent``, then ``delivered`` or
    ``failed``, for one sent; ``received`` for one received. ``cost_usd`` is what it was
    charged: its segments, and the other person's network fee once it's reported (a network
    may charge to send a text, to receive one, or both)."""

    id: Optional[str]
    direction: Optional[str]
    from_number: Optional[str]
    to: Optional[str]
    text: Optional[str]
    keyword: Optional[str]
    status: Optional[str]
    segments: Optional[int]
    cost_usd: Optional[float]
    call_id: Optional[str]
    error: Optional[str]
    created_at: Any
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "PhoneText":
        return cls(
            raw.get("id"), raw.get("direction"), raw.get("from"), raw.get("to"), raw.get("text"), raw.get("keyword"),
            raw.get("status"), raw.get("segments"), raw.get("cost_usd"), raw.get("call_id"), raw.get("error"),
            parse_time(raw.get("created_at")), raw,
        )

    def __str__(self) -> str:
        return self.text or ""


@designed
@dataclass(frozen=True)
class TransferOut:
    """What the carrier you're moving a number to asks for, from
    ``PhoneNumber.transfer_out``: the account the number is on (its name, its account and
    billing numbers, which are the number itself, and its service address) and a transfer
    ``pin`` for this number, good until ``expires_at``. Until then another carrier may take
    the number; after it, a request is refused."""

    phone_number_id: Optional[str]
    number: Optional[str]
    account_name: Optional[str]
    account_number: Optional[str]
    pin: Optional[str] = dc_field(repr=False)
    service_address: Optional[str] = None
    expires_at: Any = None
    billing_number: Optional[str] = None
    raw: Dict[str, Any] = dc_field(default_factory=dict, repr=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "TransferOut":
        return cls(raw.get("phone_number_id"), raw.get("number"), raw.get("account_name"), raw.get("account_number"),
                   raw.get("pin"), raw.get("service_address"), parse_time(raw.get("expires_at")),
                   raw.get("billing_number"), raw)


def _read_numbers(result: Any, op: Operation) -> List["PhoneNumber"]:
    """A finished port settles with ``{"phone_numbers": [<each number's view>]}``."""
    return [PhoneNumber._new(raw=raw, client=op._client, user=op._scope)
            for raw in (result or {}).get("phone_numbers") or []]


register_result("phone.port_in", _read_numbers)

_PORT_KINDS = ("phone.port_in",)


def _digits(number: Any) -> str:
    """A phone number's digits, so ``+1 415-555-0123`` and ``+14155550123`` compare equal."""
    return "".join(ch for ch in str(number or "") if ch.isdigit())


async def _connection_wire(connection: Any) -> str:
    """``connection=`` on the wire: a name or id in the number's own scope, or a ``Connection``'s id."""
    if isinstance(connection, str):
        return connection
    if isinstance(connection, Connection):
        return await ref_id(connection)
    raise TypeError(f"connection is a noclick.Connection or its name, not {type(connection).__name__}")


def _port_wire(
    account_holder: Any, account_name: Optional[str], service_address: Optional[Dict[str, str]],
    account_number: Optional[str], billing_number: Optional[str], pin: Optional[str], bill: Optional[bytes],
    requested_at: Any, remaining_numbers: Optional[List[str]],
) -> Dict[str, Any]:
    """A port's details on the wire; a ``None`` is left out (a retry keeps what it had)."""
    from .human import Human

    if isinstance(account_holder, Human):
        if not account_holder._to.get("email"):
            raise ValueError("account_holder takes a Human with an email, like noclick.Human(email='dana@co.test').")
        holder: Any = account_holder._to["email"]
    elif isinstance(account_holder, str) or account_holder is None:
        holder = account_holder
    else:
        raise TypeError(f"account_holder is a noclick.Human or an email, not {type(account_holder).__name__}")
    return compact(
        account_holder=holder, account_name=account_name, service_address=service_address,
        account_number=account_number, billing_number=billing_number, pin=pin,
        bill=base64.b64encode(bill).decode("ascii") if bill is not None else None, requested_at=iso_time(requested_at),
        remaining_numbers=list(remaining_numbers) if remaining_numbers is not None else None,
    )


@designed
class PortRequest(Operation):
    """Numbers moving to NoClick from their carrier on one letter of authorization: the
    operation ``PhoneNumber.port_in`` returns. It waits in ``awaiting_human`` until the
    account holder signs the letter at ``sign_url``, then runs (``step`` is ``submitted``,
    then ``scheduled`` once the carrier has given every number its date, ``port_at`` the
    latest), and ``wait()`` gives the ``PhoneNumber`` objects (``source`` ``ported``) once they've
    moved. A rejection fails it with the carrier's reason: ``noclick.InvalidRequest`` whose
    ``field`` names what didn't match its records (``account_name``, ``account_holder``,
    ``service_address``, ``account_number``, ``billing_number``, ``pin``, ``numbers``,
    ``remaining_numbers``, ``bill`` or ``requested_at``); ``retry()`` sends corrected details.
    ``cancel()`` works until the carrier has committed to a date. The numbers keep working
    with their carrier until they move."""

    number: Optional[str] = field("number", doc="The first number on the letter, in E.164 form.")
    numbers: Optional[List[Dict[str, Any]]] = field(
        "numbers", doc="Each number on the letter, with its own ``status`` (``draft``, ``submitted``, ``scheduled``, "
                       "``rejected``, ``ported``) and ``port_at``: a carrier can move them on different days.",
    )
    port_at: Any = field("port_at", parse_time, doc="When the last number moves, once every one is ``scheduled``.")
    monthly_usd: Optional[float] = field("monthly_usd", doc="What each number costs a month once it's yours, in US dollars.")

    @property
    def sign_url(self) -> Optional[str]:
        """While ``awaiting_human``: the page where the account holder signs the letter of
        authorization (it's emailed to them too; None otherwise)."""
        raw = self._sync_raw()
        return raw.get("sign_url") if raw.get("status") == "awaiting_human" else None

    @classmethod
    def _typed(cls, ops: List[Operation]) -> List["PortRequest"]:
        return [
            cls._from_payload(op._raw, client=op._client, user=op._scope, kind="phone.port_in", reader=_read_numbers)
            for op in ops
        ]

    @synced
    @classmethod
    async def list(cls, *, limit: Optional[int] = None, **filters: Any) -> List["PortRequest"]:
        """Port requests (kind ``phone.port_in``), newest first; takes ``Operation.list``'s
        filters except ``kind``.

        Returns:
            Every matching port request (or the first ``limit``), each with its ``numbers``,
            ``step``, ``port_at`` and ``sign_url``.

        Usage::

            for port in noclick.PortRequest.list(status="live", user_filter=noclick.ALL_USERS):
                print(port.number, port.status, port.step, port.port_at)
        """
        return cls._typed(await Operation.list.aio(limit=limit, **_with_kinds(filters, _PORT_KINDS, "PortRequest.list")))

    @synced
    @classmethod
    async def list_page(cls, *, cursor: Optional[str] = None, limit: Optional[int] = None, **filters: Any) -> Page:
        """One page of port requests; pass ``next_cursor`` back as ``cursor``.

        Returns:
            A page whose ``data`` holds the port requests and whose ``next_cursor`` is ``None`` on the last page.

        Usage::

            page = noclick.PortRequest.list_page(status="failed", limit=50)
            for port in page.data:
                print(port.number, port.error)
        """
        page = await Operation.list_page.aio(
            cursor=cursor, limit=limit, **_with_kinds(filters, _PORT_KINDS, "PortRequest.list_page"),
        )
        return Page(cls._typed(page.data), page.next_cursor)

    @synced
    async def retry(
        self,
        *,
        account_holder: Any = None,
        account_name: Optional[str] = None,
        service_address: Optional[Dict[str, str]] = None,
        account_number: Optional[str] = None,
        billing_number: Optional[str] = None,
        pin: Optional[str] = None,
        bill: Optional[bytes] = None,
        requested_at: Any = None,
        remaining_numbers: Optional[List[str]] = None,
    ) -> "PortRequest":
        """Send a port the carrier refused again with corrected details, for the numbers that
        haven't moved; a detail you leave out keeps what it had. A change to what the letter
        says (the account holder, the account's name, the service address, the account or
        billing number), or a refusal of the name it was signed with, asks the account holder
        to sign again; a new ``pin``, ``bill``, ``requested_at`` or ``remaining_numbers`` goes
        straight back.

        Returns:
            A new port request for the same numbers, waiting as ``port_in``'s does.

        Usage::

            port = noclick.PhoneNumber.port_in(
                "+14155550188", account_holder="dana@harbordental.test", account_name="Harbor Dental LLC",
                service_address={"street": "1 Ferry Building", "city": "San Francisco", "region": "CA",
                                 "postal_code": "94111"},
                account_number="8812-4410-09", max_monthly_usd=5,
            )
            try:
                numbers = port.wait()
            except noclick.InvalidRequest as err:
                print(err.field, err.message)   # account_number, The account number doesn't match.
                port = port.retry(account_number="8812-4410-07")
        """
        payload = await self._request(
            "POST", f"/v1/phone_numbers/port_in/{self._id()}/retry",
            json=_port_wire(account_holder, account_name, service_address, account_number, billing_number, pin, bill,
                            requested_at, remaining_numbers),
        )
        return PortRequest._from_payload(
            payload, client=self._client, user=self._call_scope(), kind="phone.port_in", reader=_read_numbers,
        )


@designed
class TextingRegistration(_Object):
    """Your business registered with the US carriers, which texting from a US number needs:
    the brand the carriers' registry verifies, and the campaign NoClick writes for it (a voice
    agent texting a caller one thing they asked for, after a spoken yes). One per scope: your
    account's, or one of your users' (a user's own number texts under its user's registration
    when there is one, else the account's). Review takes days to weeks; ``status`` follows it:
    ``pending``, ``awaiting_human`` (its contact must answer the registry: a public company's
    verification email, or a sole proprietor's texted code, sent back with ``verify``),
    ``in_review``, then ``approved``, ``rejected`` (``status_reason``, and ``fields`` names the
    facts to correct with ``update``) or ``suspended``. ``delete()`` stops texting and its
    monthly fee."""

    _repr_keys = ("id", "brand_name", "status")

    id: str = field("id")
    status: Optional[str] = field("status", doc="``pending``, ``awaiting_human``, ``in_review``, ``approved``, "
                                                "``rejected`` or ``suspended``.")
    status_reason: Optional[str] = field("status_reason", doc="The reviewer's words, when it refused or suspended it.")
    fields: Optional[List[str]] = field("fields", doc="The facts a refusal named, to correct with ``update``.")
    legal_name: Optional[str] = field("legal_name")
    brand_name: Optional[str] = field("brand_name", doc="What its texts are signed with: ``Harbor Dental: ...``.")
    entity_type: Optional[str] = field("entity_type")
    industry: Optional[str] = field("industry")
    website: Optional[str] = field("website")
    tax_id: Optional[str] = field("tax_id", doc="The EIN, its last four digits shown.")
    privacy_url: Optional[str] = field("privacy_url")
    terms_url: Optional[str] = field("terms_url")
    setup_usd: Optional[float] = field("setup_usd", doc="Charged once, as the registry charges it: the brand when "
                                                        "registered, the campaign's review and first months when it opens.")
    monthly_usd: Optional[float] = field("monthly_usd", doc="The campaign's monthly fee, after its first months.")
    segment_usd: Optional[float] = field(
        "segment_usd", doc="What a text costs a segment (160 characters), sent or received, before the other "
                           "person's network fee, which is charged as reported.",
    )
    user_id: Optional[str] = field("user_id")
    approved_at: Any = field("approved_at", parse_time)
    created_at: Any = field("created_at", parse_time)

    @synced
    @classmethod
    async def create(
        cls,
        *,
        legal_name: str,
        entity_type: str,
        industry: str,
        address: Dict[str, str],
        website: str,
        contact: Dict[str, str],
        privacy_url: str,
        terms_url: str,
        max_setup_usd: float,
        max_monthly_usd: float,
        tax_id: Optional[str] = None,
        brand_name: Optional[str] = None,
        stock: Optional[Dict[str, str]] = None,
        user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> "TextingRegistration":
        """Register the business with the US carriers, as the legal entity on its tax records:
        ``entity_type`` is ``private_company``, ``public_company``, ``nonprofit``,
        ``government`` or ``sole_proprietor``; ``tax_id`` its EIN (none for a sole
        proprietor); ``industry`` one of the registry's (``healthcare``, ``retail``,
        ``professional``, ...); ``address`` its US address (``street``, ``city``, ``region``,
        ``postal_code``); ``website``, ``privacy_url`` and ``terms_url`` pages anyone can open
        (the privacy policy must say phone numbers aren't shared); ``contact`` the person the
        registry contacts (``name``, ``email``, ``phone``: your business's own, never NoClick's);
        ``stock`` (``symbol``, ``exchange``) for a public company. ``brand_name`` is what texts
        are signed with (the legal name when omitted). Refused (``noclick.PriceExceeded``, nothing
        registered) above ``max_setup_usd`` once or ``max_monthly_usd`` a month.

        Returns:
            The registration, ``pending``; its brand's fee is charged now. A scope that has one
            raises ``noclick.Conflict`` with its ``existing_id``.

        Usage::

            registration = noclick.TextingRegistration.create(
                legal_name="Harbor Dental LLC", brand_name="Harbor Dental", entity_type="private_company",
                tax_id="12-3456789", industry="healthcare", website="https://harbordental.test",
                address={"street": "1 Ferry Building", "city": "San Francisco", "region": "CA",
                         "postal_code": "94111"},
                contact={"name": "Dana Ruiz", "email": "dana@harbordental.test", "phone": "+14155550142"},
                privacy_url="https://harbordental.test/privacy", terms_url="https://harbordental.test/terms",
                max_setup_usd=40, max_monthly_usd=5,
            )
            print(registration.status, registration.setup_usd, registration.monthly_usd)
        """
        scope = resolve_scope(user)
        raw = await resolve_client(client).request(
            "POST", "/v1/texting_registrations",
            json=compact(legal_name=legal_name, brand_name=brand_name, entity_type=entity_type, industry=industry,
                         tax_id=tax_id, address=address, website=website, contact=contact, stock=stock,
                         privacy_url=privacy_url, terms_url=terms_url, max_setup_usd=max_setup_usd,
                         max_monthly_usd=max_monthly_usd),
            user=scope,
        )
        return cls._new(raw=raw, client=client, user=scope)

    @classmethod
    def from_id(cls, registration_id: str, *, client: Optional[Client] = None,
                user: Any = AMBIENT) -> "TextingRegistration":
        """A lazy reference to a registration by id.

        Returns:
            A registration that loads the first time you read a field. Nothing is sent yet.

        Usage::

            registration = noclick.TextingRegistration.from_id("8e2f4b7a-1c3d-4a9e-b6f5-2d7c0e1a9b48")
            print(registration.status)
        """
        return cls._new(hints={"id": registration_id}, client=client, user=user)

    @synced
    @classmethod
    async def get(cls, registration_id: str, *, user: Any = AMBIENT,
                  client: Optional[Client] = None) -> "TextingRegistration":
        """Load a registration by id now; an unknown or deleted one raises ``noclick.NotFound``.

        Returns:
            The registration, loaded.

        Usage::

            registration = noclick.TextingRegistration.get("8e2f4b7a-1c3d-4a9e-b6f5-2d7c0e1a9b48")
            print(registration.status, registration.status_reason)
        """
        registration = cls.from_id(registration_id, client=client, user=user)
        await registration._ensure()
        return registration

    @synced
    @classmethod
    async def list(cls, *, limit: Optional[int] = None, user_filter: Any = None, user: Any = AMBIENT,
                   client: Optional[Client] = None) -> List["TextingRegistration"]:
        """The registrations of the current user (or, without one, the account's), or those
        ``user_filter`` covers.

        Returns:
            Every matching registration, newest first. Deleted ones aren't listed.

        Usage::

            for registration in noclick.TextingRegistration.list(user_filter=noclick.ALL_USERS):
                print(registration.brand_name, registration.status)
        """
        return await list_all(
            "/v1/texting_registrations", lambda raw, scope: cls._new(raw=raw, client=client, user=scope),
            user=user, user_filter=user_filter, limit=limit, client=client,
        )

    def _path(self) -> str:
        return f"/v1/texting_registrations/{self._known('id')}"

    async def _load(self) -> Dict[str, Any]:
        return await self._request("GET", self._path())

    @synced
    async def update(self, **corrections: Any) -> "TextingRegistration":
        """Resubmit a refused registration (or one waiting on its contact) with corrected
        facts, named as ``create`` names them; a fact you leave out keeps what it had. A
        corrected ``privacy_url`` or ``terms_url`` opens a new campaign, whose review and first
        months are charged again.

        Returns:
            This registration, back in review.

        Usage::

            registration = noclick.TextingRegistration.get("8e2f4b7a-1c3d-4a9e-b6f5-2d7c0e1a9b48")
            if registration.status == "rejected" and "tax_id" in registration.fields:
                registration.update(tax_id="98-7654321")
        """
        self._raw = await self._request("PATCH", self._path(), json=corrections)
        return self

    @synced
    async def verify(self, code: str) -> "TextingRegistration":
        """A sole proprietor's contact sends back the code the registry texted them
        (``noclick.InvalidRequest`` naming ``code`` when it's wrong or expired).

        Returns:
            This registration, its contact verified.

        Usage::

            registration = noclick.TextingRegistration.get("8e2f4b7a-1c3d-4a9e-b6f5-2d7c0e1a9b48")
            registration.verify("482913")
        """
        self._raw = await self._request("POST", f"{self._path()}/verify", json={"code": code})
        return self

    @synced
    async def delete(self) -> None:
        """Stop texting under it: its numbers stop texting, its campaign closes and its
        monthly fee ends.

        Usage::

            noclick.TextingRegistration.get("8e2f4b7a-1c3d-4a9e-b6f5-2d7c0e1a9b48").delete()
        """
        await self._request("DELETE", self._path())


class PhoneNumber(_Object):
    """A number you own. ``release()`` gives it back (billing stops); a number you keep with
    your own phone provider is ``disconnect()``ed instead."""

    _repr_keys = ("id", "number")

    id: str = field("id")
    name: Optional[str] = field(
        "name", doc="What your code calls it, unique among its user's numbers (None for one bought without a name).",
    )
    number: str = field("number", doc="The number in E.164 form.")
    source: Optional[str] = field(
        "source", doc="Where it came from: ``bought`` through NoClick or ``connected`` (kept with your own phone "
                      "provider account, which bills it); ``ported`` (moved to NoClick from its carrier) is in "
                      "invite-only beta.",
    )
    connection: Optional[str] = field(
        "connection", doc="The phone provider connection a connected number runs through, by name (None otherwise).",
    )
    agent_id: Optional[str] = field("agent_id", doc="The agent that answers inbound calls (None if none).")
    transfer_to: Optional[str] = field(
        "transfer_to", doc="Where the answering agent's ``transfer_call`` tool sends a call (None: no such tool).",
    )
    texts: Optional[bool] = field(
        "texts", doc="Whether the answering agent can text the caller (``send_text``; invite-only beta).",
    )
    texts_ready: Optional[bool] = field(
        "texts_ready", doc="Whether the US carriers have taken the number onto your registration's campaign, so "
                           "its texts go out (invite-only beta). Until then the agent has no ``send_text``.",
    )
    texts_error: Optional[str] = field(
        "texts_error", doc="Why the carriers didn't take the number onto the campaign, when they refused it "
                           "(invite-only beta).",
    )
    callers: Optional[str] = field(
        "callers", doc="Who gets through: ``anyone``, ``users`` or ``owner``. It never changes who a call runs as.",
    )
    record_calls: Optional[bool] = field(
        "record_calls", doc="Whether its calls, both ways, are recorded.",
    )
    monthly_usd: Optional[float] = field(
        "monthly_usd", doc="What NoClick bills for it a month, in US dollars (None for a connected number, which its "
                           "provider bills).",
    )
    user_id: Optional[str] = field("user_id")
    created_at: Any = field("created_at", parse_time)

    def _init(self, **kwargs: Any) -> None:
        self._create_with: Optional[Dict[str, Any]] = None
        # Set when ``from_name`` connects the number rather than buying one.
        self._connect_via: Any = None
        super()._init(**kwargs)

    @property
    def released(self) -> bool:
        """Whether ``release()`` gave the number back, or ``disconnect()`` handed it back to its provider account."""
        return bool(self._known("deleted"))

    # --- construction ----------------------------------------------------

    @synced
    @staticmethod
    async def available(
        *,
        country: Optional[str] = None,
        type: Optional[str] = None,
        area_code: Optional[Union[str, int]] = None,
        locality: Optional[str] = None,
        region: Optional[str] = None,
        contains: Optional[str] = None,
        starts_with: Optional[str] = None,
        ends_with: Optional[str] = None,
        features: Optional[str] = None,
        limit: Optional[int] = None,
        user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> List[AvailableNumber]:
        """Numbers for sale in ``country`` (``US`` by default) of ``type`` (``local`` by
        default: also ``mobile``, ``toll_free``, ``national``, ``shared_cost``), narrowed by
        ``area_code``, ``locality`` (a city), ``region``, ``contains`` (digits, letters or
        ``*`` wildcards), ``starts_with`` and ``ends_with`` (digits of the national number),
        and ``features`` (``voice``, or ``voice_sms`` for numbers that take texts too).

        Returns:
            Up to ``limit`` numbers (10 by default, at most 30), each with its
            ``monthly_usd`` and ``upfront_usd``, the ``locality`` and ``region`` it's local
            to, what it can do (``capabilities``), what its country asks before it's sold
            (``requirements``) and whether it can text (``texting``).

        Usage::

            for pick in noclick.PhoneNumber.available(area_code="415", limit=5):
                print(pick.number, pick.locality, pick.monthly_usd, pick.upfront_usd)

            with_digits = noclick.PhoneNumber.available(contains="2024")   # numbers containing these digits
            london = noclick.PhoneNumber.available(country="GB", locality="London")
        """
        response = await resolve_client(client).request(
            "GET", "/v1/phone_numbers/available",
            params={"country": country, "type": type, "area_code": area_code, "locality": locality,
                    "region": region, "contains": contains, "starts_with": starts_with, "ends_with": ends_with,
                    "features": features, "limit": limit},
            user=resolve_scope(user),
        ) or {}
        return [AvailableNumber._from(row) for row in response.get("data") or []]

    @synced
    @staticmethod
    async def coverage(*, user: Any = AMBIENT, client: Optional[Client] = None) -> List[NumberCoverage]:
        """The countries numbers are for sale in, with the kinds of number sold in each. Right after a
        deploy, while that is still being found out, the API answers 503 with ``Retry-After``, which the
        client retries on its own.

        Returns:
            A ``noclick.NumberCoverage`` per country: its ISO code, the kinds of number in stock
            there (``types``), the kinds that can text (``texting_types``), the kinds bought with
            documents the carrier reviews first (``documents_types``) and the kinds that ask a step
            that can't be taken here (``steps_types``), which can't be bought through the API yet.

        Usage::

            for country in noclick.PhoneNumber.coverage():
                print(country.country, country.types)
        """
        response = await resolve_client(client).request(
            "GET", "/v1/phone_numbers/coverage", user=resolve_scope(user)) or {}
        return [NumberCoverage(row["country"], list(row.get("types") or []), list(row.get("texting_types") or []),
                               list(row.get("documents_types") or []), list(row.get("steps_types") or []))
                for row in response.get("data") or []]

    @synced
    @staticmethod
    async def places(
        country: str, *, type: Optional[str] = None, user: Any = AMBIENT, client: Optional[Client] = None,
    ) -> List[NumberPlace]:
        """Where in ``country`` numbers of ``type`` (``local`` by default) are for sale:
        cities, or area codes in North America.

        Returns:
            A ``noclick.NumberPlace`` per place: its ``kind`` (``locality`` or ``area_code``),
            its ``value`` and the ``region`` it's in. Empty where the carrier doesn't say.

        Usage::

            [first, *_] = noclick.PhoneNumber.places("GB")
            numbers = noclick.PhoneNumber.available(country="GB", locality=first.value)
        """
        response = await resolve_client(client).request(
            "GET", "/v1/phone_numbers/places", params={"country": country, "type": type},
            user=resolve_scope(user)) or {}
        return [NumberPlace(row["kind"], row["value"], row.get("region") or "") for row in response.get("data") or []]

    @synced
    @classmethod
    async def buy(
        cls,
        number: Union[str, AvailableNumber],
        *,
        max_monthly_usd: float,
        max_upfront_usd: Optional[float] = None,
        country: Optional[str] = None,
        type: Optional[str] = None,
        address: Optional[NumberHolder] = None,
        requirements: Optional[Mapping[str, Union[str, NumberDocument]]] = None,
        name: Optional[str] = None,
        user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> Union["PhoneNumber", "PhoneNumberOrder"]:
        """Buy ``number`` (a string or an ``AvailableNumber``, whose ``country`` and
        ``type`` it takes). The purchase is refused (``noclick.PriceExceeded``) if it
        costs more than ``max_monthly_usd`` a month or ``max_upfront_usd`` once (by
        default, the ``upfront_usd`` an ``AvailableNumber`` showed; 0 for a number passed
        as a string). A number whose country asks who holds it takes ``address``
        (a ``noclick.NumberHolder``, with a ``phone`` where a requirement's ``kind`` is
        ``contact``). One whose country asks for documents takes ``requirements``: each
        textual and document requirement's answer by its ``id`` (the text, or a
        ``noclick.NumberDocument`` from ``PhoneNumber.upload_document``).
        ``name`` is what your code calls it, unique among its user's numbers
        (``noclick.Conflict`` with ``existing_id`` when taken, before anything is bought);
        ``PhoneNumber.from_name`` finds it by that.

        Returns:
            The number, now yours. Its first month is charged now and it renews monthly
            until you ``release()`` it. A number whose country asks for documents comes back
            as a ``noclick.PhoneNumberOrder`` instead, in the carrier's review (days,
            sometimes): nothing is charged until it completes, and ``order.phone_number()``
            is the number once it has.

        Usage:
            Pick one that's for sale and buy it with a ceiling on the monthly price::

                [pick] = noclick.PhoneNumber.available(area_code="415", limit=1)
                number = noclick.PhoneNumber.buy(pick, max_monthly_usd=5)
                print(number.number, number.monthly_usd)

            Nothing is bought when the price is above your ceiling::

                [pick] = noclick.PhoneNumber.available(area_code="415", limit=1)
                try:
                    number = noclick.PhoneNumber.buy(pick, max_monthly_usd=1)
                except noclick.PriceExceeded as err:
                    print(err.message)

            A number whose country asks for documents, filed for the carrier's review::

                [pick] = noclick.PhoneNumber.available(country="IT", limit=1)
                asked = {item["name"]: item for item in pick.requirements["items"]}
                passport = noclick.PhoneNumber.upload_document(
                    "passport.pdf", requirement=asked["Identity Document"], country="IT")
                order = noclick.PhoneNumber.buy(
                    pick, max_monthly_usd=5, max_upfront_usd=5,
                    address=noclick.NumberHolder(name="Giulia Rossi", street="Via Roma 1", city="Milano",
                                                 postal_code="20121", country="IT", phone="+393471234567"),
                    requirements={asked["Identity Document Type"]["id"]: "Passport",
                                  asked["Identity Document"]["id"]: passport})
                print(order.status)               # in_review
                order.refresh()                   # later: completed, rejected (order.reason) or failed
                if order.status == "completed":
                    number = order.phone_number()
        """
        scope = resolve_scope(user)
        picked = number if isinstance(number, AvailableNumber) else None
        raw = await resolve_client(client).request(
            "POST", "/v1/phone_numbers",
            json=compact(number=str(number), country=country or (picked.country if picked else None),
                         type=type or (picked.type if picked else None), max_monthly_usd=max_monthly_usd,
                         max_upfront_usd=max_upfront_usd if max_upfront_usd is not None
                         else (picked.upfront_usd if picked else None),
                         address=address._wire() if address is not None else None,
                         requirements=_requirements_wire(requirements), name=name), user=scope,
        )
        if (raw or {}).get("object") == "phone_number_order":
            return PhoneNumberOrder._new(raw=raw, client=client, user=scope)
        return cls._new(raw=raw, client=client, user=scope)

    @synced
    @staticmethod
    async def upload_document(
        file: Union[bytes, str, "os.PathLike[str]"],
        *,
        requirement: Union[str, Mapping[str, Any]],
        country: str,
        type: str = "local",
        filename: Optional[str] = None,
        user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> NumberDocument:
        """Upload a document one of a number's requirements asks for (a requirement of ``kind``
        ``document`` in ``country``'s numbers of ``type``): ``file`` is its bytes, or a path to
        read; ``filename`` defaults to the path's name and is required for bytes. ``requirement``
        is the requirement, or its ``id``. A PDF, PNG or JPEG, up to 20 MB. The carrier holds the
        file; NoClick keeps only its name and what it's for.

        Returns:
            A ``noclick.NumberDocument`` to pass in ``requirements`` when you buy. One no purchase
            names within 25 minutes is gone; one a purchase named can be named again.

        Usage::

            [pick] = noclick.PhoneNumber.available(country="IT", limit=1)
            [asked] = [item for item in pick.requirements["items"] if item["kind"] == "document"]
            passport = noclick.PhoneNumber.upload_document("passport.pdf", requirement=asked, country="IT")
            print(passport.id, passport.requirement_name)
        """
        if isinstance(file, (str, os.PathLike)):
            path = os.fspath(file)
            with open(path, "rb") as handle:
                content = handle.read()
            filename = filename or os.path.basename(path)
        else:
            content = bytes(file)
        if not filename:
            raise TypeError("Pass filename= with a document's bytes.")
        requirement_id = requirement if isinstance(requirement, str) else requirement["id"]
        raw = await resolve_client(client).request(
            "POST", "/v1/phone_numbers/documents",
            json={"country": country, "type": type, "requirement_id": requirement_id, "filename": filename,
                  "file": base64.b64encode(content).decode("ascii")},
            user=resolve_scope(user),
        )
        return NumberDocument._from(raw)

    @synced
    @staticmethod
    async def connectable(
        connection: Any, *, user: Any = AMBIENT, client: Optional[Client] = None,
    ) -> List[ConnectableNumber]:
        """The numbers in your phone provider account that ``connection`` (a ``noclick.Connection``
        or its name, in the current user) can route. The connection is the provider account's own:
        connected with the account's id and secret, since NoClick checks the provider's signed
        calls with that secret, which a restricted API key can't do (a connection holding one
        raises ``noclick.InvalidRequest`` naming ``connection``).

        Returns:
            Each number (up to 1,000) with its ``label``, whether its calls go somewhere today
            (``routed_elsewhere``), and, when it's already connected to NoClick, the number it's
            connected as (``phone_number_id``) and the agent answering it (``agent_id``).

        Usage::

            provider = noclick.Connection.from_name("phone-provider")
            for pick in noclick.PhoneNumber.connectable(provider):
                if pick.phone_number_id:
                    print(pick.number, "is already connected, answered by", pick.agent_id)
                else:
                    print(pick.number, pick.label, "(answered elsewhere today)" if pick.routed_elsewhere else "")
        """
        response = await resolve_client(client).request(
            "GET", "/v1/phone_numbers/connectable", params={"connection": await _connection_wire(connection)},
            user=resolve_scope(user),
        ) or {}
        return [ConnectableNumber._from(row) for row in response.get("data") or []]

    @synced
    @classmethod
    async def connect(
        cls,
        number: Union[str, ConnectableNumber],
        *,
        connection: Any,
        name: Optional[str] = None,
        record_calls: bool = False,
        user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> "PhoneNumber":
        """Connect ``number``, which you keep with your own phone provider, through
        ``connection`` (that account's connection: see ``connectable``). NoClick remembers where
        its calls go today and leaves them there until ``answer_with`` routes them to an agent;
        ``disconnect()`` puts them back. ``answer_with``, ``call``, ``calls`` and recording work
        on it as on a bought number, with calls placed through the provider account. The
        provider bills the number and its minutes to you directly; NoClick bills only what it
        adds (the agent's time on a call). Inside ``as_user`` it's the user's number, on the
        user's connection. A number already connected, or one another NoClick workflow answers,
        raises ``noclick.Conflict`` (its ``existing_id`` when it's yours): one number, one agent.
        A number on a SIP trunk can't be connected (``noclick.InvalidRequest``).

        Returns:
            The number, ``source`` ``connected``, with no agent yet.

        Usage::

            provider = noclick.Connection.from_name("phone-provider")
            number = noclick.PhoneNumber.connect("+14155550123", connection=provider, name="front-desk")
            number.answer_with(noclick.Agent.from_name("receptionist"))
        """
        scope = resolve_scope(user)
        raw = await resolve_client(client).request(
            "POST", "/v1/phone_numbers/connect",
            json=compact(number=str(number), connection=await _connection_wire(connection), name=name,
                         record_calls=record_calls or None), user=scope,
        )
        return cls._new(raw=raw, client=client, user=scope)

    @designed
    @synced
    @classmethod
    async def port_in(
        cls,
        numbers: Union[str, List[str]],
        *,
        account_holder: Any,
        account_name: str,
        service_address: Dict[str, str],
        account_number: str,
        max_monthly_usd: float,
        billing_number: Optional[str] = None,
        pin: Optional[str] = None,
        bill: Optional[bytes] = None,
        name: Optional[str] = None,
        requested_at: Any = None,
        remaining_numbers: Optional[List[str]] = None,
        user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> PortRequest:
        """Port US local numbers in from their carrier, so they become NoClick numbers: one, or
        several on one account at that carrier (one letter of authorization covers them).
        ``account_holder`` (a ``noclick.Human`` or an email: the person authorized on the
        account) signs the letter on a NoClick page, branded like your other pages. The rest is
        how the current carrier knows the account, as its bill shows it: ``account_name`` (the
        name on the account, often a business, not the signer), ``service_address``
        (``street``, ``city``, ``region``, ``postal_code``), ``account_number``,
        ``billing_number`` (the account's main number; the first number when omitted), ``pin``
        where the carrier has one (a mobile account's transfer PIN), and ``bill`` (a recent
        bill's PDF bytes) where it asks for one. Every number on the account moves unless
        ``remaining_numbers`` names the ones that stay with the carrier (then, when the billing
        number moves, the first of them becomes the account's billing number).
        ``requested_at`` (a timezone-aware ``datetime``) is when you'd like them to move; the
        carrier sets the dates, and refuses one it doesn't allow. Moving them is free; each is
        billed monthly once moved, like a bought number, refused (``noclick.PriceExceeded``,
        nothing sent) above ``max_monthly_usd``. ``name`` names a single number. A number you
        connected through your own phone provider is disconnected first (``noclick.InvalidRequest``
        otherwise); for one kept with Twilio, the account's name is "Twilio, Inc.", its number
        the last 8 characters of your Account SID, and the PIN comes from Twilio's support.

        Returns:
            The port request: an operation in ``awaiting_human`` until the account holder signs
            (``sign_url``), then ``submitted`` and ``scheduled`` (its ``step``), whose ``.wait()``
            gives the ``PhoneNumber`` objects once they've moved. They keep working with their carrier
            until then.

        Usage::

            port = noclick.PhoneNumber.port_in(
                "+14155550188",
                account_holder="dana@harbordental.test",
                account_name="Harbor Dental LLC",
                service_address={"street": "1 Ferry Building", "city": "San Francisco", "region": "CA",
                                 "postal_code": "94111"},
                account_number="8812-4410-09",
                pin="4410",
                max_monthly_usd=5,
                name="front-desk",
            )
            print(port.status, port.sign_url)   # awaiting_human, the page Dana signs
            [number] = port.wait()
            print(number.source)                # ported
        """
        scope = resolve_scope(user)
        payload = await resolve_client(client).request(
            "POST", "/v1/phone_numbers/port_in",
            json=compact(
                numbers=[numbers] if isinstance(numbers, str) else list(numbers), max_monthly_usd=max_monthly_usd,
                name=name, **_port_wire(account_holder, account_name, service_address, account_number,
                                        billing_number, pin, bill, requested_at, remaining_numbers),
            ),
            user=scope,
        )
        return PortRequest._from_payload(payload, client=client, user=scope, kind="phone.port_in",
                                         reader=_read_numbers)

    @classmethod
    def from_name(
        cls,
        name: str,
        *,
        create_if_missing: bool = False,
        area_code: Optional[Union[str, int]] = None,
        max_monthly_usd: Optional[float] = None,
        max_upfront_usd: Optional[float] = None,
        connect: Optional[str] = None,
        connection: Any = None,
        record_calls: Any = UNSET,
        user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> "PhoneNumber":
        """A lazy reference to the number called ``name`` in the current (or given) user.
        A ``record_calls`` you pass is set on it every run. With ``create_if_missing=True``, the
        first time it's used with none of that name, NoClick buys a US local number in
        ``area_code`` (any US area code when omitted) for at most ``max_monthly_usd`` a month and
        ``max_upfront_usd`` once (``noclick.PriceExceeded`` above either) and names it, or with
        ``connect=`` connects that number of yours through ``connection`` instead (as
        ``PhoneNumber.connect``); without it, a missing number raises ``noclick.NotFound``.
        ``area_code`` and the prices say how to buy one, so they matter only then. The number
        itself never changes, so the same code keeps the same number: an existing number other
        than ``connect`` raises ``noclick.Conflict`` naming it.

        Returns:
            A number that loads (or is bought, or has ``record_calls`` set) the first time it's used.
            Nothing is sent yet.

        Usage:
            Refer to a number by name::

                number = noclick.PhoneNumber.from_name("front-desk")
                print(number.number)

            Or own one idempotently: the first run buys it, every run after finds it::

                number = noclick.PhoneNumber.from_name(
                    "front-desk", create_if_missing=True, area_code="415", max_monthly_usd=5, max_upfront_usd=5,
                )
                number.answer_with(noclick.Agent.from_name("receptionist"))

            Or the number you already have, connected through your phone provider account::

                provider = noclick.Connection.from_name("phone-provider")
                number = noclick.PhoneNumber.from_name(
                    "front-desk", create_if_missing=True, connect="+14155550123", connection=provider,
                )
        """
        number = cls._new(hints={"name": name}, client=client, user=user)
        recording = None if record_calls is UNSET else record_calls
        if connect is not None:
            if create_if_missing and connection is None:
                raise ValueError("PhoneNumber.from_name(connect=...) needs connection=")
            if area_code is not None or max_monthly_usd is not None or max_upfront_usd is not None:
                raise ValueError(
                    "PhoneNumber.from_name takes connect= (a number you keep) or area_code= and max_monthly_usd= "
                    "(one to buy), not both"
                )
            number._connect_via = connection
            number._define(compact(name=name, number=connect, record_calls=recording),
                           create_if_missing=create_if_missing)
        else:
            if create_if_missing and max_monthly_usd is None:
                raise ValueError("PhoneNumber.from_name(create_if_missing=True) needs max_monthly_usd=")
            number._define(compact(
                name=name, area_code=None if area_code is None else str(area_code), max_monthly_usd=max_monthly_usd,
                max_upfront_usd=max_upfront_usd, record_calls=recording,
            ), create_if_missing=create_if_missing)
        return number

    @classmethod
    def from_id(cls, number_id: str, *, client: Optional[Client] = None, user: Any = AMBIENT) -> "PhoneNumber":
        """A lazy reference to a number you own, by id.

        Returns:
            A number that loads the first time you read a field. Nothing is sent yet.

        Usage::

            number = noclick.PhoneNumber.from_id("8e2f4b7a-1c3d-4a9e-b6f5-2d7c0e1a9b48")
            for call in number.calls():
                print(call.to, call.status)
        """
        return cls._new(hints={"id": number_id}, client=client, user=user)

    @synced
    @classmethod
    async def get(cls, number_id: str, *, user: Any = AMBIENT, client: Optional[Client] = None) -> "PhoneNumber":
        """Load a number by id now; an unknown id, or one you released, raises ``noclick.NotFound``.

        Returns:
            The number, loaded.

        Usage::

            number = noclick.PhoneNumber.get("8e2f4b7a-1c3d-4a9e-b6f5-2d7c0e1a9b48")
            print(number.number, number.agent_id)
        """
        number = cls.from_id(number_id, client=client, user=user)
        await number._ensure()
        return number

    @synced
    @classmethod
    async def list(
        cls, *, limit: Optional[int] = None, user_filter: Any = None, user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> List["PhoneNumber"]:
        """The numbers you own (the current user's inside ``as_user``, or those ``user_filter`` covers).

        Returns:
            Every matching number, newest first, fetched page by page. Released numbers aren't listed.

        Usage::

            for number in noclick.PhoneNumber.list():
                print(number.number, number.agent_id)

            theirs = noclick.PhoneNumber.list(user_filter="user_42")   # one user's, by your id for them
        """
        return await list_all(
            "/v1/phone_numbers", lambda raw, scope: cls._new(raw=raw, client=client, user=scope),
            user=user, user_filter=user_filter, limit=limit, client=client,
        )

    @synced
    @classmethod
    async def list_page(
        cls, *, cursor: Optional[str] = None, limit: Optional[int] = None, user_filter: Any = None,
        user: Any = AMBIENT, client: Optional[Client] = None,
    ) -> Page:
        """One page of numbers; pass ``next_cursor`` back as ``cursor``.

        Returns:
            A page whose ``data`` holds the numbers and whose ``next_cursor`` is ``None`` on the last page.

        Usage::

            page = noclick.PhoneNumber.list_page(limit=50)
            while True:
                for number in page.data:
                    print(number.number)
                if page.next_cursor is None:
                    break
                page = noclick.PhoneNumber.list_page(limit=50, cursor=page.next_cursor)
        """
        return await list_page(
            "/v1/phone_numbers", lambda raw, scope: cls._new(raw=raw, client=client, user=scope),
            user=user, user_filter=user_filter, cursor=cursor, limit=limit, client=client,
        )

    def _path(self) -> str:
        return f"/v1/phone_numbers/{self._known('id')}"

    async def _id_path(self) -> str:
        """``_path()`` once the id is known (a number reached by name loads first)."""
        if not self._known("id"):
            await self._ensure()
        return self._path()

    async def _load(self) -> Dict[str, Any]:
        if self._known("id"):
            return await self._request("GET", self._path())
        name = self._hints["name"]
        page = await self._request("GET", "/v1/phone_numbers", params={"name": name}) or {}
        rows = [row for row in page.get("data") or [] if row.get("name") == name]
        if rows:
            return await self._converge(rows[0])
        if not self._creates:
            raise NotFound(
                f"No phone number is named {name!r}.",
                next_step="Buy it with noclick.PhoneNumber.buy(..., name=...) or pass create_if_missing=True.",
                details={"name": name},
            )
        if self._connect_via is None:
            path, body = "/v1/phone_numbers", self._create_with
        else:
            path, body = "/v1/phone_numbers/connect", {
                **self._create_with, "connection": await _connection_wire(self._connect_via),
            }
        try:
            return await self._request("POST", path, json=body)
        except Conflict as exc:  # made concurrently
            if not exc.existing_id:
                raise
            return await self._converge(await self._request("GET", f"/v1/phone_numbers/{exc.existing_id}"))

    async def _converge(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Set ``record_calls`` on an existing number, once it's the number ``connect=`` named."""
        connect = (self._create_with or {}).get("number")
        if connect is not None and _digits(raw.get("number")) != _digits(connect):
            check_unchanged("phone number", raw, {"number": connect})
        wanted = (self._create_with or {}).get("record_calls")
        if wanted is None or raw.get("record_calls") == wanted:
            return raw
        return await self._request("PATCH", f"/v1/phone_numbers/{raw['id']}", json={"record_calls": wanted})

    def __str__(self) -> str:
        return self._known("number") or repr(self)

    # --- actions ---------------------------------------------------------

    @synced
    async def release(self) -> None:
        """Give the number back; it stops ringing and billing. A connected number isn't NoClick's
        to give back: it raises ``noclick.Conflict``, so ``disconnect()`` it.

        Usage::

            number = noclick.PhoneNumber.get("8e2f4b7a-1c3d-4a9e-b6f5-2d7c0e1a9b48")
            number.release()
            print(number.released)   # True
        """
        response = await self._request("DELETE", await self._id_path())
        self._raw = {**(self._raw or self._hints), **(response if isinstance(response, dict) else {}), "deleted": True}

    @synced
    async def disconnect(self) -> None:
        """Hand a connected number back to its provider account: NoClick takes it off its agent,
        puts back where its calls went before it was connected, and it leaves your list. A
        bought number raises ``noclick.Conflict``: ``release()`` it.

        Usage::

            number = noclick.PhoneNumber.from_name("front-desk")
            number.disconnect()
            print(number.released)   # True
        """
        response = await self._request("POST", f"{await self._id_path()}/disconnect")
        self._raw = {**(self._raw or self._hints), **(response if isinstance(response, dict) else {}), "deleted": True}

    @synced
    async def update(self, *, name: Any = UNSET, record_calls: Any = UNSET) -> "PhoneNumber":
        """Rename it (``name=None`` removes its name; one another of its user's numbers
        has raises ``noclick.Conflict``), or start or stop recording its calls
        (``record_calls``), from the next call. A recording holds both sides of a call
        in one file, and the caller hears that the call is recorded before the agent speaks.

        Returns:
            This number, updated. A field you leave out is unchanged.

        Usage::

            number = noclick.PhoneNumber.from_name("front-desk")
            number.update(name="reception")
            number.update(record_calls=True)
        """
        changes = {k: v for k, v in dict(name=name, record_calls=record_calls).items() if v is not UNSET}
        self._raw = await self._request("PATCH", await self._id_path(), json=changes)
        return self

    @designed_params("texts")
    @synced
    async def answer_with(
        self,
        agent: Any,
        *,
        transfer_to: Any = None,
        texts: bool = False,
        callers: str = "anyone",
        conversation: Optional[str] = None,
    ) -> "PhoneNumber":
        """Route inbound calls to ``agent`` (an ``noclick.Agent`` or id), an agent on the
        ``sdk`` harness, whose tools and connections work during a call as in a message; one on
        a coding harness can't answer calls (``noclick.NotAvailable``).

        ``conversation`` is the agent's conversation each call lands in, a template over
        ``{caller}`` and ``{number}``: ``"owner"`` puts every call in the same conversation as
        ``agent.message(..., conversation="owner")``, so a call, an email and a text from one
        person are one thread. Omitted, each caller has a conversation of their own on the number.

        ``transfer_to`` (a phone number in E.164 form, or a ``noclick.Human`` with a
        ``phone``) gives the agent a ``transfer_call`` tool that hands the caller to that
        number once the agent has said so; who picks up hears why first, and a transfer
        nobody picks up comes back to the agent, which is told.
        Invite-only beta: ``texts=True`` gives it a ``send_text`` tool that texts the
        caller, and only the caller (a link, a confirmation, an address), after asking and
        hearing a yes. Each text is signed with your brand (``Harbor Dental: ...``), the first
        to a caller says how to opt out, and a caller who texted STOP is never texted again.
        Texting from a US local number needs your business registered with the US carriers
        (``noclick.TextingRegistration``); until that's approved ``texts=True`` raises
        ``noclick.ActionRequired`` naming it, and a number that can't text (one kept with your
        own phone provider, a toll-free one) raises ``noclick.NotAvailable``. Until texting ships,
        ``texts=True`` raises ``noclick.NotAvailable``.
        On an account number, a caller whose number is one of your users' verified phones
        (``User.verify_phone``), with the carrier attesting the caller id (STIR/SHAKEN level
        A), runs as that user, in their connections, whatever ``callers`` says; any other
        call runs as your account. A user's own number runs every call as that user.
        ``callers`` only says who gets through: ``"anyone"`` (the default), ``"users"`` (only
        callers proven to be one of your users) or ``"owner"`` (only the number's own user,
        or your account's owner for an account number, by the phone verified on their
        NoClick account, attested the same way). Anyone else hears that the number doesn't
        take their call, and the call is listed as ``refused``. Each call to ``answer_with``
        sets these afresh: an option you leave out goes back to its default.

        Returns:
            This number, with ``agent_id`` naming the agent that now answers it.

        Usage:
            Every call to the number then reaches that agent. A number rings one agent
            at a time, so calling ``answer_with`` again moves it::

                number = noclick.PhoneNumber.get("8e2f4b7a-1c3d-4a9e-b6f5-2d7c0e1a9b48")
                receptionist = noclick.Agent.from_name(
                    "receptionist",
                    create_if_missing=True,
                    instructions="You answer calls for Harbor Dental: opening hours, directions, and what to bring.",
                )
                number.answer_with(receptionist)

            Let it hand callers to a person::

                number = noclick.PhoneNumber.from_name("front-desk")
                receptionist = noclick.Agent.from_name("receptionist")
                number.answer_with(
                    receptionist, transfer_to=noclick.Human(email="dana@harbordental.test", phone="+14155550142"),
                )

            And text them a link (invite-only beta)::

                number = noclick.PhoneNumber.from_name("front-desk")
                number.answer_with(noclick.Agent.from_name("receptionist"), transfer_to="+14155550142", texts=True)

            Answer only your users, each call acting for the user who called::

                number = noclick.PhoneNumber.from_name("assistant-line")
                number.answer_with(noclick.Agent.from_name("concierge"), callers="users")

            Or a user's own line that only they get through to::

                with noclick.as_user("user_42"):
                    number = noclick.PhoneNumber.from_name("my-assistant")
                    number.answer_with(noclick.Agent.from_name("assistant"), callers="owner")
        """
        if callers not in CALLERS:
            raise ValueError(f"callers must be one of {CALLERS}, not {callers!r}")
        body: Dict[str, Any] = {"agent_id": await agent_id(agent)}
        if transfer_to is not None:
            body["transfer_to"] = _phone_of(transfer_to)
        if texts:
            body["texts"] = True
        if callers != "anyone":
            body["callers"] = callers
        if conversation is not None:
            body["conversation"] = conversation
        response = await self._request("POST", f"{await self._id_path()}/answer", json=body)
        if isinstance(response, dict) and response.get("id"):
            self._raw = response
        return self

    @synced
    async def call(self, to: str, *, goal: str, agent: Any = None) -> Operation:
        """Call ``to`` with the number's answering agent working toward
        ``goal`` (``agent=``, if given, must be that agent).

        Returns:
            An operation whose ``.wait()`` gives the ``PhoneCall`` at hang-up, with its
            transcript, ``status`` (``completed`` or ``not_connected``), length and cost.

        Usage:
            The call goes out through the agent that answers the number, so route it
            with ``answer_with`` first; a number with no agent raises ``noclick.ActionRequired``::

                number = noclick.PhoneNumber.get("8e2f4b7a-1c3d-4a9e-b6f5-2d7c0e1a9b48")
                call = number.call(
                    "+14155550100",
                    goal="Confirm Friday's 3pm booking, or find a new time that works.",
                ).wait()
                print(call.status)
                print(call.text)   # the transcript, one turn per line
        """
        payload = await self._request(
            "POST", f"{await self._id_path()}/calls", json=compact(to=to, goal=goal, agent_id=await agent_id(agent)),
        )
        return Operation._from_payload(
            payload, client=self._client, user=self._call_scope(), kind="phone.call", reader=_read_call,
        )

    @synced
    @staticmethod
    async def get_call(call: Any, *, user: Any = AMBIENT, client: Optional[Client] = None) -> PhoneCall:
        """One call as it stands, read live while it goes. ``call`` is its id, or the operation
        ``number.call()`` returned.

        Returns:
            The ``noclick.PhoneCall``: its ``status``, when it was ``answered_at``, what was said so
            far turn by turn (``lines``), who ended it (``ended_by``) and, once it has ended, its
            ``transcript``. An unknown call raises ``noclick.NotFound``.

        Usage:
            Follow a call while it's on::

                import time

                op = number.call("+14155550100", goal="Confirm Friday's 3pm booking.")
                while (call := noclick.PhoneNumber.get_call(op)).status == "calling":
                    for line in call.lines:
                        print(line["who"], line["text"])
                    time.sleep(5)
        """
        call_id, api, scope = await _call_target(call, user, client)
        return PhoneCall._from(await api.request("GET", f"/v1/phone_numbers/calls/{call_id}", user=scope))

    @synced
    @staticmethod
    async def hang_up(call: Any, *, user: Any = AMBIENT, client: Optional[Client] = None) -> PhoneCall:
        """Hang up a call the number placed, ringing or live: the agent says goodbye and the call
        ends (a ringing one is cancelled). ``call`` is its id, or the operation ``number.call()``
        returned.

        Returns:
            The ``noclick.PhoneCall`` as it stands. It ends a moment later with ``ended_by``
            ``hang_up``, and its operation settles with the transcript as at any hang-up. A call
            that already ended raises ``noclick.Conflict``; one the number answered raises
            ``noclick.NotAvailable``.

        Usage::

            op = number.call("+14155550100", goal="Ask whether the order shipped.")
            noclick.PhoneNumber.hang_up(op)
            print(op.wait().ended_by)   # hang_up
        """
        call_id, api, scope = await _call_target(call, user, client)
        return PhoneCall._from(await api.request("POST", f"/v1/phone_numbers/calls/{call_id}/hang_up", user=scope))

    @synced
    async def calls(
        self, *, direction: Optional[str] = None, since: Any = None, limit: Optional[int] = None,
    ) -> List[PhoneCall]:
        """The calls on this number, newest first: the calls it answered with the ones it
        placed. ``direction`` (``"inbound"`` or ``"outbound"``) keeps one kind, ``since`` (a
        timezone-aware ``datetime``) those that started at or after it, and ``limit`` the
        newest that many.

        Returns:
            The matching calls, each with its ``direction`` and its transcript once it has
            ended (and ``recording_url`` when the number records its calls).

        Usage:
            See what the number placed::

                number = noclick.PhoneNumber.get("8e2f4b7a-1c3d-4a9e-b6f5-2d7c0e1a9b48")
                for call in number.calls():
                    print(call.to, call.status, call.seconds, call.cost_usd)

            Or what callers asked it this week::

                from datetime import datetime, timedelta, timezone

                number = noclick.PhoneNumber.from_name("front-desk")
                week_ago = datetime.now(timezone.utc) - timedelta(days=7)
                for call in number.calls(direction="inbound", since=week_ago, limit=50):
                    print(call.from_number, call.seconds, call.text)
        """
        if direction is not None and direction not in DIRECTIONS:
            raise ValueError(f"direction must be one of {DIRECTIONS}, not {direction!r}")
        rows = await paginate(
            self._api, f"{await self._id_path()}/calls", params={"direction": direction, "since": iso_time(since)},
            user=self._call_scope(), limit=limit,
        )
        return [PhoneCall._from(row) for row in rows]

    @designed
    @synced
    async def text_messages(
        self, *, direction: Optional[str] = None, since: Any = None, limit: Optional[int] = None,
    ) -> List[PhoneText]:
        """The texts its answering agent sent callers (``send_text``) and the texts the number
        received, newest first. A reply doesn't wake the agent: read it here, or take
        ``phone.text.received`` events. ``direction`` (``"inbound"`` or ``"outbound"``) keeps
        one kind, ``since`` (a timezone-aware ``datetime``) those at or after it.

        Returns:
            The matching texts, each with its ``direction``, ``text``, ``status`` and cost.

        Usage::

            number = noclick.PhoneNumber.from_name("front-desk")
            for text in number.text_messages(direction="inbound", limit=20):
                print(text.from_number, text.text, text.keyword)
        """
        if direction is not None and direction not in DIRECTIONS:
            raise ValueError(f"direction must be one of {DIRECTIONS}, not {direction!r}")
        rows = await paginate(
            self._api, f"{await self._id_path()}/texts", params={"direction": direction, "since": iso_time(since)},
            user=self._call_scope(), limit=limit,
        )
        return [PhoneText._from(row) for row in rows]

    @designed
    @synced
    async def transfer_out(self) -> TransferOut:
        """Move the number to another carrier: what that carrier asks for (the account it's on,
        whose account and billing numbers are the number itself, and a transfer PIN for it).
        Another carrier may take the number for 30 days from now; a request outside that
        window, or quoting another PIN, is refused, so nobody takes it without you. Once it
        moves, it leaves your numbers and its billing stops.

        Returns:
            The transfer's details, with its ``pin`` and ``expires_at``.

        Usage::

            number = noclick.PhoneNumber.from_name("front-desk")
            details = number.transfer_out()
            print(details.account_name, details.account_number, details.pin, details.expires_at)
        """
        return TransferOut._from(await self._request("POST", f"{await self._id_path()}/transfer_out"))


class PhoneNumberOrder(_Object):
    """A number ordered while the carrier reviews the documents filed for it (``PhoneNumber.buy`` of a
    number whose country asks for them). Nothing is yours, or charged, until it completes:
    ``status`` is ``in_review``, ``rejected`` (the carrier sent it back: ``reason`` says why;
    ``resubmit`` corrections before ``deadline``), ``completed`` (``phone_number()`` is the number) or
    ``failed`` (it ended without the number; nothing was charged)."""

    _repr_keys = ("id", "number", "status")

    id: str = field("id")
    number: str = field("number", doc="The number ordered, in E.164 form.")
    country: Optional[str] = field("country")
    type: Optional[str] = field("type")
    status: str = field("status", doc="``in_review``, ``rejected``, ``completed`` or ``failed``.")
    reason: Optional[str] = field(
        "reason", doc="The carrier's words when it sent the order back or ended it (None otherwise).")
    deadline: Any = field("deadline", parse_time, doc="When a sent-back order must be corrected by.")
    monthly_usd: Optional[float] = field("monthly_usd", doc="What the number costs a month, once it's yours.")
    upfront_usd: Optional[float] = field("upfront_usd", doc="What it costs once, charged when the order completes.")
    phone_number_id: Optional[str] = field("phone_number_id", doc="The number, once the order completed.")
    requirements: Optional[Dict[str, Any]] = field(
        "requirements", doc="While it's open: what its country asks, which a ``resubmit`` answers.")
    created_at: Any = field("created_at", parse_time)
    updated_at: Any = field("updated_at", parse_time)

    @synced
    @classmethod
    async def retrieve(cls, order_id: str, *, user: Any = AMBIENT,
                       client: Optional[Client] = None) -> "PhoneNumberOrder":
        """Load an order by id now; an unknown id raises ``noclick.NotFound``.

        Returns:
            The order, as it stands.

        Usage::

            order = noclick.PhoneNumberOrder.retrieve("5f1c2d3e-4a5b-4c6d-8e7f-9a0b1c2d3e4f")
            print(order.status, order.reason)
        """
        order = cls._new(hints={"id": order_id}, client=client, user=user)
        await order._ensure()
        return order

    async def _load(self) -> Dict[str, Any]:
        return await self._request("GET", f"/v1/phone_numbers/orders/{self._known('id')}")

    def __str__(self) -> str:
        return self._known("number") or repr(self)

    @synced
    async def resubmit(
        self, *, address: Optional[NumberHolder] = None,
        requirements: Optional[Mapping[str, Union[str, NumberDocument]]] = None,
    ) -> "PhoneNumberOrder":
        """File corrected answers for an order the carrier sent back (``status`` ``rejected``), for its
        review again: ``address`` and ``requirements`` as ``PhoneNumber.buy`` takes them. Any other
        order raises ``noclick.Conflict``.

        Returns:
            This order, ``in_review`` again.

        Usage::

            order = noclick.PhoneNumberOrder.retrieve(order_id)
            if order.status == "rejected":
                print(order.reason)
                clearer = noclick.PhoneNumber.upload_document("passport-full.pdf", requirement=passport_id,
                                                              country="IT")
                order.resubmit(address=holder, requirements={type_id: "Passport", passport_id: clearer})
        """
        self._raw = await self._request(
            "POST", f"/v1/phone_numbers/orders/{self._known('id')}/resubmit",
            json=compact(address=address._wire() if address is not None else None,
                         requirements=_requirements_wire(requirements)))
        return self

    @synced
    async def phone_number(self) -> PhoneNumber:
        """The number, once the order completed; ``noclick.Conflict`` while it hasn't (``refresh()`` first).

        Returns:
            The ``noclick.PhoneNumber`` the order became.

        Usage::

            order.refresh()
            if order.status == "completed":
                number = order.phone_number()
                number.answer_with(noclick.Agent.from_name("receptionist"))
        """
        raw = await self._ensure()
        if not raw.get("phone_number_id"):
            raise Conflict(f"Order {raw.get('id')} is {raw.get('status')}: the number is yours once it completes.",
                           next_step="Refresh the order, and read the number once its status is completed.",
                           details={"status": raw.get("status")})
        return PhoneNumber._new(raw=await self._request("GET", f"/v1/phone_numbers/{raw['phone_number_id']}"),
                                client=self._client, user=self._scope)


def _phone_of(target: Any) -> str:
    """``transfer_to`` on the wire: an E.164 string, or a ``Human``'s phone."""
    from .human import Human

    if isinstance(target, Human):
        phone = target._to.get("phone")
        if not phone:
            raise ValueError("transfer_to takes a Human with a phone, like noclick.Human(phone='+14155550142').")
        return phone
    if isinstance(target, str):
        return target
    raise TypeError(f"transfer_to is a phone number or a noclick.Human with a phone, not {type(target).__name__}")
