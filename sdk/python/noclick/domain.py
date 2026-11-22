"""Domains: buy one in your user's name, connect one they own, or transfer one in.

    [offer] = noclick.Domain.search("anasilva", tlds=["dev"], limit=1)
    ana = noclick.DomainContact(name="Ana Silva", email="ana@example.com", phone="+14155550123",
                                address="500 Market St", city="San Francisco", region="CA", postal_code="94105",
                                country="US", agreement_accepted_at=accepted_at)   # when she accepted the agreement
    with noclick.as_user("user_42"):
        bought = noclick.Domain.buy(offer, max_price_usd=20, registrant=ana).wait()   # Ana's, charged to you

    owned = noclick.Domain.connect("acme.test")              # one they already own
    for record in owned.records:
        print(record.type, record.name, record.value)       # add these where its DNS is hosted
    inbox = noclick.Inbox.create(local_part="help", domain="mail.acme.test")   # its own mail stays put

A bought domain is registered to the person (you, or the user it's bought for) and
charged to your account in dollars, like everything else: NoClick never bills your users.
It's never deleted: turn off auto-renew to let it lapse, or ``transfer_out()`` to move it
to another registrar. One registered elsewhere moves here with ``Domain.transfer_in``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field as dc_field
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Union

from ._client import Client, resolve_client
from ._object import UNSET, Page, _Object, compact, csv, field, list_all, list_page, parse_time
from ._sync import synced
from ._scope import AMBIENT, resolve_scope
from .exceptions import Conflict, NotFound
from .operation import Operation, register_result


@dataclass(frozen=True)
class DomainOffer:
    """A name from ``noclick.Domain.search``; buy it with ``noclick.Domain.buy(offer, max_price_usd=...)``.
    ``price_usd`` is what buying it charges now, for ``min_years`` (the TLD's shortest term: two
    years for ``.ai``), and ``renewal_usd`` what each renewal of ``min_years`` costs; ``max_years``
    is the longest term the TLD allows. ``premium`` means the registry prices this name above its
    usual rate, often far above.

    ``claims_notice`` is set during the TLD's trademark-claims period for a name that matches a
    registered trademark: the Trademark Clearinghouse notice (Markdown) the registrant must be
    shown before buying it, with ``accept_claims=True`` once they have. It's None otherwise."""

    name: str
    available: bool
    price_usd: Optional[float]
    renewal_usd: Optional[float]
    premium: bool
    min_years: Optional[int]
    max_years: Optional[int]
    claims_notice: Optional[str]
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "DomainOffer":
        return cls(
            raw.get("name"), bool(raw.get("available")), raw.get("price_usd"), raw.get("renewal_usd"),
            bool(raw.get("premium")), raw.get("min_years"), raw.get("max_years"), raw.get("claims_notice"), raw,
        )

    def __str__(self) -> str:
        return self.name


@dataclass(frozen=True)
class DomainContact:
    """The registrant: the person a domain is registered to, as the registry records it.
    ICANN requires real details, kept accurate (``domain.update(registrant=...)`` when they
    change), and ``email`` is sent a link to confirm the address, in your brand on ICANN's
    behalf; a person confirms once, for all their domains. ``phone`` is in E.164 form
    and ``country`` a two-letter code; a second street line follows a newline in ``address``.
    ``region`` is the state, province or region of the address; the registry requires one.
    Domains are registered through NoClick's registrar partner, which the public registration
    record names; privacy protection keeps the registrant's details out of it.

    ``organization``, when set, is the legal owner (ICANN's "Registered Name Holder"): never
    put your company on a user's domain unless your company means to own it.

    ``agreement_accepted_at`` is when this person explicitly accepted the domain registration
    agreement (``Domain.agreement().url``). A registration needs it: a registrant, or your
    account's default registrant, without it is refused with ``noclick.InvalidRequest`` naming
    ``registrant.agreement_accepted_at``.

    Usage::

        ana = noclick.DomainContact(
            name="Ana Silva", email="ana@example.com", phone="+14155550123",
            address="500 Market St", city="San Francisco", region="CA", postal_code="94105", country="US",
            agreement_accepted_at=accepted_at,   # when she accepted noclick.Domain.agreement()
        )
        [offer] = noclick.Domain.search("anasilva", tlds=["dev"], limit=1)
        purchase = noclick.Domain.buy(offer, max_price_usd=20, registrant=ana, user="user_42")
    """

    name: str
    email: str
    phone: str
    address: str
    city: str
    postal_code: str
    country: str
    region: str
    organization: Optional[str] = None
    agreement_accepted_at: Optional[datetime] = None

    def _wire(self) -> Dict[str, Any]:
        wire = compact(**asdict(self))
        if isinstance(self.agreement_accepted_at, datetime):
            wire["agreement_accepted_at"] = self.agreement_accepted_at.isoformat()
        return wire

    @classmethod
    def _from(cls, raw: Any) -> Optional["DomainContact"]:
        if not isinstance(raw, dict) or not raw:
            return None
        return cls(
            **{k: raw.get(k) for k in (
                "name", "email", "phone", "address", "city", "postal_code", "country", "region", "organization",
            )},
            agreement_accepted_at=parse_time(raw.get("agreement_accepted_at")),
        )


@dataclass(frozen=True)
class DomainAgreement:
    """NoClick's domain registration agreement, from ``noclick.Domain.agreement()``. The page at
    ``url`` is the agreement the registrant accepts (it names the sponsoring registrar, as ICANN
    requires), the fee schedule (registration, renewal, renewal after expiry, restore) and
    ICANN's registrant rights and responsibilities. Show it to the person and record when they
    accept it, as ``agreement_accepted_at`` on their ``DomainContact``. ``version`` names the
    revision."""

    url: str
    version: str
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "DomainAgreement":
        return cls(raw.get("url"), raw.get("version"), raw)


@dataclass(frozen=True)
class DnsRecord:
    """One DNS record: ``type`` (``A``, ``CNAME``, ``ALIAS``, ``MX``, ``TXT``, ...), ``name``
    (``@`` for the domain itself, or the label before it, like ``www``) and ``value``.

    ``status`` is ``verified`` once public DNS answers with it, ``pending`` until then, and
    ``conflict`` when another record at that name is in the way. ``purpose`` says what it's
    for. ``required`` is False for a record the domain works without (a connected domain's
    bare-name ``ALIAS``, which forwarding can replace). ``managed`` marks a record NoClick keeps
    for something the domain serves: change what it serves, not the record."""

    type: str
    name: str
    value: str
    status: Optional[str]
    purpose: Optional[str]
    required: bool
    managed: bool
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "DnsRecord":
        return cls(
            raw.get("type"), raw.get("name"), raw.get("value"), raw.get("status"), raw.get("purpose"),
            raw.get("required", True) is not False, bool(raw.get("managed")), raw,
        )

    def __str__(self) -> str:
        return f"{self.name} {self.type} {self.value}"


@dataclass(frozen=True)
class TransferQuote:
    """What ``noclick.Domain.transfer_quote`` finds: whether ``name`` can move to NoClick from its
    current registrar now, and what it costs. ``eligible`` is False, with ``reason``, while the
    domain is locked at its registrar, inside the registry's transfer lock after a domain is
    registered, transferred in or its registrant changes (until ``locked_until``), on a TLD
    NoClick doesn't register, or already with NoClick's registrar under another account (moving
    it between accounts isn't supported yet). ``price_usd`` is what the transfer charges your
    account, and it adds ``years`` to the registration (the TLD's minimum, one year for most);
    ``renewal_usd`` is what each renewal of ``years`` costs after."""

    name: str
    eligible: bool
    reason: Optional[str]
    price_usd: Optional[float]
    renewal_usd: Optional[float]
    years: Optional[int]
    locked_until: Any
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "TransferQuote":
        return cls(
            raw.get("name"), bool(raw.get("eligible")), raw.get("reason"), raw.get("price_usd"),
            raw.get("renewal_usd"), raw.get("years"), parse_time(raw.get("locked_until")), raw,
        )

    def __str__(self) -> str:
        return self.name


@dataclass(frozen=True)
class TransferCode:
    """What ``domain.transfer_out()`` gives: the ``auth_code`` the other registrar asks for,
    when the domain was unlocked for the move, and ``expires_at``: when the code stops working,
    where the registry limits it (None otherwise); call ``transfer_out()`` again for a fresh
    one. Printing it never shows the code."""

    auth_code: str = dc_field(repr=False)
    unlocked_at: Any = None
    expires_at: Any = None
    raw: Dict[str, Any] = dc_field(default_factory=dict, repr=False)


def _records(rows: Any) -> List[DnsRecord]:
    return [DnsRecord._from(row) for row in rows or []]


async def domain_name(ref: Any) -> Optional[str]:
    """The name of a ``Domain`` (loading a lazy one) or a name string."""
    if ref is None or isinstance(ref, str):
        return ref
    if isinstance(ref, Domain):
        return ref._known("name") or (await ref._ensure())["name"]
    raise TypeError(f"Expected a Domain or a domain name, not {type(ref).__name__}")


class DomainDns:
    """``domain.dns``: the records of a bought domain, whose DNS NoClick hosts. A connected
    domain's DNS stays where it is (``domain.records`` lists what to add there), so these
    raise ``noclick.NotAvailable`` on one."""

    _domain: "Domain"

    @classmethod
    def _for(cls, domain: "Domain") -> "DomainDns":
        dns = cls.__new__(cls)
        dns._domain = domain
        return dns

    def __repr__(self) -> str:
        return f"DomainDns(domain={self._domain._known('name') or self._domain._known('id')!r})"

    async def _path(self) -> str:
        return f"{await self._domain._path()}/dns"

    @synced
    async def records(self) -> List[DnsRecord]:
        """Every record in the domain's DNS: yours, and the ones NoClick keeps for what it serves.

        Returns:
            The records, each with its ``status``; ``managed`` marks NoClick's.

        Usage::

            domain = noclick.Domain.from_name("acmebooking.com")
            for record in domain.dns.records():
                print(record.name, record.type, record.value, "(managed)" if record.managed else "")
        """
        response = await self._domain._request("GET", await self._path()) or {}
        return _records(response.get("data"))

    @synced
    async def set(self, type: str, name: str, value: str) -> DnsRecord:
        """Add a record, or keep it if the same one is there. A ``CNAME`` replaces the
        name's existing ``CNAME`` (a name holds at most one); other types add alongside
        the records already at that name. A record that would clash with one NoClick
        manages raises ``noclick.Conflict``.

        Returns:
            The record as saved; its ``status`` turns ``verified`` once public DNS serves it,
            usually within minutes.

        Usage:
            Prove the domain to another service, or point a name at something you run elsewhere::

                domain = noclick.Domain.from_name("acmebooking.com")
                domain.dns.set("TXT", "@", "google-site-verification=3pL0x0kA1b2C")
                domain.dns.set("CNAME", "status", "acme.statuspage.example")
        """
        raw = await self._domain._request("POST", await self._path(), json={"type": type, "name": name, "value": value})
        return DnsRecord._from(raw or {})

    @synced
    async def delete(self, record: DnsRecord) -> None:
        """Remove ``record`` (from ``records()``). A record NoClick manages raises ``noclick.Conflict``.

        Usage::

            domain = noclick.Domain.from_name("acmebooking.com")
            for record in domain.dns.records():
                if record.type == "TXT" and record.value.startswith("google-site-verification="):
                    domain.dns.delete(record)
        """
        await self._domain._request(
            "DELETE", await self._path(), params={"type": record.type, "name": record.name, "value": record.value},
        )


def _read_domain(result: Any, op: Operation) -> "Domain":
    """A buy, renewal or transfer in settles with ``{"domain": <the domain view>}``."""
    return Domain._new(raw=(result or {}).get("domain") or {}, client=op._client, user=op._scope)


register_result("domain.buy", _read_domain)
register_result("domain.renew", _read_domain)
register_result("domain.transfer_in", _read_domain)


class DomainPurchase(Operation):
    """A domain bought or renewed: the operation ``Domain.buy`` and ``domain.renew`` return.
    It's charged to your account when the registry confirms it, and one that fails is never
    charged; while your policy holds it for a person to approve, it waits in ``awaiting_human``.
    ``wait()`` gives the ``Domain``."""

    price_usd: Optional[float] = field("price_usd", doc="What it charges your account, in US dollars.")
    domain_id: Optional[str] = field("domain_id", doc="The domain being bought or renewed.")

    @property
    def domain(self) -> "Domain":
        """The domain, already listed while the purchase runs (its ``status`` follows it)."""
        return Domain._new(hints={"id": self.domain_id}, client=self._client, user=self._call_scope())


class DomainTransfer(DomainPurchase):
    """A domain moving to NoClick from another registrar: the operation ``Domain.transfer_in``
    returns. It's charged to your account like a purchase (the quote, which adds the quote's
    ``years`` to the registration) once the transfer completes, and waits in ``awaiting_human``
    while your policy holds it. The domain is ``transferring_in`` while the registry and its
    current registrar move it, up to about 5 days; ``wait()`` gives the ``Domain`` once it's
    ``active``. If the registry refuses, it fails with the registry's reason (a wrong auth code
    is ``noclick.InvalidRequest`` naming ``auth_code``) and nothing is charged."""


class Domain(_Object):
    """A domain you bought through NoClick, transferred in, or connected from elsewhere, and what it serves."""

    _repr_keys = ("id", "name", "status")

    id: str = field("id")
    name: str = field("name", doc="The domain, like ``acmebooking.com``.")
    source: str = field(
        "source", doc="``bought`` (through NoClick), ``transferred`` (moved here from another registrar, then "
                      "registered through NoClick like a bought one) or ``connected`` (owned elsewhere).",
    )
    noclick_dns: bool = field(
        "noclick_dns", bool,
        doc="Whether NoClick hosts its DNS: a bought domain, or a transferred one after ``use_noclick_dns()``. When "
            "False, ``records`` are added where its DNS is hosted and ``dns`` raises ``noclick.NotAvailable``.",
    )
    wildcard: bool = field("wildcard", bool, doc="Whether its ``*.<name>`` records are set too, so every subdomain can serve.")
    status: str = field(
        "status",
        doc="``awaiting_human`` (its purchase held for your policy's approver), ``registering``, ``transferring_in`` "
            "(moving here from another registrar), ``pending_dns``, ``active``, ``registrant_unverified``, ``expiring``, "
            "``expired``, ``transferring_out`` or ``failed``.",
    )
    expires_at: Any = field("expires_at", parse_time, doc="When the registration runs out (None for a connected domain).")
    auto_renew: Optional[bool] = field(
        "auto_renew", doc="Whether it renews itself 30 days before ``expires_at`` (None for a connected domain).",
    )
    renewable_until: Any = field(
        "renewable_until", parse_time,
        doc="The end of the guaranteed renewal window after ``expires_at``: the last moment ``renew()`` works "
            "(None for a connected domain).",
    )
    renewal_usd: Optional[float] = field("renewal_usd", doc="What renewing for ``renewal_years`` costs, in US dollars.")
    renewal_years: Optional[int] = field(
        "renewal_years", doc="The term ``renewal_usd`` buys, in years: the TLD's minimum (None for a connected "
                             "domain).",
    )
    registrant: Optional[DomainContact] = field(
        "registrant", DomainContact._from,
        doc="The person it's registered to (None for a connected domain); ``update(registrant=...)`` changes it.",
    )
    records: List[DnsRecord] = field(
        "records", _records,
        doc="The records it needs for what it serves: on a connected domain, the ones to add where its DNS "
            "is hosted, each with its ``status``; on a bought one, the ones NoClick keeps for you.",
    )
    setup_url: Optional[str] = field(
        "setup_url", doc="A connected domain's one-click setup, where its DNS host supports the open Domain Connect "
                         "standard: the person signs in there and approves the records on the host's consent page, "
                         "which names NoClick alongside your brand (None otherwise).",
    )
    serves: List[Dict[str, Any]] = field(
        "serves", doc="What it points at, one entry per name of it: ``{kind, id, name, hostname}`` for each app "
                      "(``project``) and inbox, and ``brand`` when it serves your brand's pages "
                      "(``Brand.set(domain=)``); ``hostname`` is the name serving it.",
    )
    registrant_email: Optional[str] = field(
        "registrant_email",
        doc="Where the link to confirm the registrant's address went, sent in your brand on ICANN's behalf (a bought "
            "domain).",
    )
    registrant_verify_by: Any = field(
        "registrant_verify_by", parse_time,
        doc="While ``registrant_unverified``: the day (15 days on) the domain stops resolving unless the registrant "
            "has confirmed their address.",
    )
    transfer_locked_until: Any = field(
        "transfer_locked_until", parse_time,
        doc="Until then ``transfer_out()`` is refused: the registry's transfer lock after a domain is registered, "
            "transferred in or its registrant changes.",
    )
    user_id: Optional[str] = field("user_id")
    created_at: Any = field("created_at", parse_time)

    def _init(self, **kwargs: Any) -> None:
        self._create_with: Optional[Dict[str, Any]] = None
        super()._init(**kwargs)

    @property
    def dns(self) -> DomainDns:
        """The records of a bought domain: ``records()``, ``set(...)``, ``delete(record)``."""
        return DomainDns._for(self)

    def __str__(self) -> str:
        return self._known("name") or repr(self)

    # --- finding and buying ----------------------------------------------

    @synced
    @staticmethod
    async def search(
        query: str,
        *,
        tlds: Optional[Sequence[str]] = None,
        limit: Optional[int] = None,
        user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> List[DomainOffer]:
        """Names for sale built from ``query`` (a word, or a whole name like ``acmebooking.com``),
        in ``tlds`` or a common set, with close alternatives.

        Returns:
            Up to ``limit`` offers (10 by default, at most 50), exact matches first, each with its
            price and renewal price for the TLD's shortest term (``min_years``), the longest it
            allows (``max_years``), whether it's ``available``, and any trademark ``claims_notice``.
            Names that imitate well-known brands or banks aren't offered.

        Usage:
            See what's free and what it costs::

                for offer in noclick.Domain.search("acmebooking", tlds=["com", "ai"]):
                    print(offer.name, offer.available, offer.price_usd, offer.min_years, offer.renewal_usd, offer.premium)

            Or check one name::

                [offer] = noclick.Domain.search("acmebooking.com", limit=1)
                print(offer.available)
        """
        response = await resolve_client(client).request(
            "GET", "/v1/domains/search", params={"q": query, "tlds": csv(tlds), "limit": limit},
            user=resolve_scope(user),
        ) or {}
        return [DomainOffer._from(row) for row in response.get("data") or []]

    @synced
    @classmethod
    async def buy(
        cls,
        offer: Union[str, DomainOffer],
        *,
        max_price_usd: float,
        years: Optional[int] = None,
        registrant: Optional[DomainContact] = None,
        auto_renew: bool = True,
        accept_claims: bool = False,
        user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> DomainPurchase:
        """Register ``offer`` (a ``DomainOffer`` or a name) in the person's name: yours, or
        inside ``as_user`` the user's. ``years`` is the term, between the offer's ``min_years``
        and ``max_years``; left out, it's the TLD's minimum (two years for ``.ai``), and a term the
        TLD doesn't offer raises ``noclick.InvalidRequest`` naming ``years``, with the terms it
        does. It's charged to your account, never to the user, and refused
        (``noclick.PriceExceeded``) if it costs more than ``max_price_usd``.

        ``registrant`` is the person it's registered to, with the ``agreement_accepted_at`` that
        says when they accepted ``Domain.agreement()``. A user's domain is registered to that
        user: inside ``as_user`` a purchase naming none uses the user's registrant profile
        (``Domain.set_default_registrant(..., user=...)``), and with none on file it raises
        ``noclick.InvalidRequest`` naming ``registrant``. A domain your account buys for itself, outside
        ``as_user``, uses the account's default registrant when you pass none
        (``Domain.set_default_registrant``); with none set, it raises ``noclick.ActionRequired``
        whose ``next_step`` links to the console page where it's set, and nothing is bought. A
        ``registrant`` that is the one on file, without ``agreement_accepted_at``, takes its acceptance
        from there once it accepted the agreement as it stands.

        ``accept_claims=True`` says the registrant has been shown the offer's ``claims_notice``
        and still wants the name. A name with a notice is refused without it
        (``noclick.ActionRequired`` whose details carry ``claims_notice``), and nothing is bought.

        NoClick checks your account can pay before registering (``noclick.PaymentRequired``
        otherwise) and charges it when the registry confirms the registration; a registration
        that fails is never charged. When your policy holds purchases for a person to approve,
        it waits in ``awaiting_human`` until the approver answers; nobody answering within 24
        hours (the approval's life) expires it, and nothing is charged. The price is checked
        against ``max_price_usd`` again when it runs.

        Returns:
            The purchase: an operation whose ``.wait()`` gives the ``Domain`` once it's registered
            and its DNS is set up.

        Usage:
            Buy a name with a ceiling on the price, registered to the person you name::

                [offer] = noclick.Domain.search("acmebooking", tlds=["com"], limit=1)
                owner = noclick.DomainContact(
                    name="Dana Reyes", email="dana@acmebooking.test", phone="+14155550188",
                    address="1 Ferry Building", city="San Francisco", region="CA", postal_code="94111", country="US",
                    agreement_accepted_at=accepted_at,   # when Dana accepted noclick.Domain.agreement()
                )
                domain = noclick.Domain.buy(offer, max_price_usd=15, registrant=owner).wait()
                print(domain.name, domain.expires_at)

            Buy one for a user: registered to them, charged to you::

                ana = noclick.DomainContact(
                    name="Ana Silva", email="ana@example.com", phone="+14155550123",
                    address="500 Market St", city="San Francisco", region="CA", postal_code="94105", country="US",
                    agreement_accepted_at=accepted_at,
                )
                with noclick.as_user("user_42"):
                    domain = noclick.Domain.buy("anasilva.dev", max_price_usd=20, registrant=ana).wait()

            A name with a trademark claim, once the registrant has read its notice and still wants it::

                [offer] = noclick.Domain.search("acmebooking.ai", limit=1)
                print(offer.claims_notice)   # show this to the registrant first
                domain = noclick.Domain.buy(offer, max_price_usd=200, registrant=owner, accept_claims=True).wait()
        """
        scope = resolve_scope(user)
        payload = await resolve_client(client).request(
            "POST", "/v1/domains",
            json=compact(
                name=str(offer), max_price_usd=max_price_usd, years=years, auto_renew=auto_renew,
                registrant=registrant._wire() if registrant is not None else None,
                accept_claims=True if accept_claims else None,
            ),
            user=scope,
        )
        return DomainPurchase._from_payload(payload, client=client, user=scope, kind="domain.buy", reader=_read_domain)

    @synced
    @classmethod
    async def agreement(cls, *, client: Optional[Client] = None) -> DomainAgreement:
        """NoClick's domain registration agreement, which every registrant accepts. Its page
        names the sponsoring registrar, as ICANN requires, and carries the fee schedule
        (registration, renewal, renewal after expiry, restore) and ICANN's registrant rights and
        responsibilities. Show it to the person, and record when they accept it as
        ``agreement_accepted_at`` on their ``DomainContact``: a registration needs it.

        Returns:
            The agreement's ``url`` and ``version``.

        Usage::

            agreement = noclick.Domain.agreement()
            print(f"Before we register your domain, read and accept {agreement.url}")
        """
        raw = await resolve_client(client).request("GET", "/v1/domains/agreement", user=None)
        return DomainAgreement._from(raw or {})

    @synced
    @classmethod
    async def default_registrant(cls, *, user: Any = None,
                                 client: Optional[Client] = None) -> Optional[DomainContact]:
        """The registrant your account's own domains are registered to when a purchase names none; with
        ``user=`` (a ``User`` or your id for one), that user's registrant profile, which their domains use.

        Returns:
            The contact, or ``None`` until you set one.

        Usage::

            contact = noclick.Domain.default_registrant()
            print(contact.email if contact else "No default registrant yet")
            ana = noclick.Domain.default_registrant(user="user_42")
        """
        return DomainContact._from(await resolve_client(client).request("GET", "/v1/domains/registrant", user=user))

    @synced
    @classmethod
    async def set_default_registrant(
        cls, contact: Optional[DomainContact], *, user: Any = None, client: Optional[Client] = None,
    ) -> Optional[DomainContact]:
        """Set (or with ``None`` clear) the registrant your account's own domains use when a
        purchase names none: set it once, and ``Domain.buy`` or ``Domain.from_name(...,
        create_if_missing=True)`` outside ``as_user`` needs no contact in code. Until one is set, such
        a purchase raises ``noclick.ActionRequired`` whose ``next_step`` links to the console page
        that sets it. With ``user=`` (a ``User`` or your id for one) it's that user's registrant profile,
        with their own acceptance: their domains (``as_user``, or an app of theirs) are registered to it
        when a purchase names none. Like any registrant, it needs ``agreement_accepted_at``: when the
        person accepted ``Domain.agreement()``. It's a standing acceptance too: where your approval
        settings make ``terms`` and ``person_filing`` standing (``noclick.ApprovalPolicy.set``), a
        purchase it covers, an app's code's included, runs with no one asked.

        Returns:
            The contact now on file (``None`` once cleared).

        Usage::

            noclick.Domain.set_default_registrant(noclick.DomainContact(
                name="Dana Reyes", email="dana@acmebooking.test", phone="+14155550188", organization="Acme Booking",
                address="1 Ferry Building", city="San Francisco", region="CA", postal_code="94111", country="US",
                agreement_accepted_at=accepted_at,   # when Dana accepted noclick.Domain.agreement()
            ))
        """
        api = resolve_client(client)
        if contact is None:
            await api.request("DELETE", "/v1/domains/registrant", user=user)
            return None
        return DomainContact._from(await api.request("PUT", "/v1/domains/registrant", json=contact._wire(), user=user))

    @synced
    @classmethod
    async def connect(
        cls, name: str, *, wildcard: bool = False, user: Any = AMBIENT, client: Optional[Client] = None,
    ) -> "Domain":
        """Connect a domain the person already owns (``acme.com``, or a subdomain like
        ``book.acme.com``). Connecting it again returns the same domain; one another account
        has connected raises ``noclick.Conflict``.

        On a bare domain, ``www`` is the primary address and the bare name needs your DNS
        host's CNAME flattening (``ALIAS`` or ``ANAME``) or a forward to ``www``.

        ``wildcard=True`` adds the ``*.<name>`` records to ``records`` too, so once they're set
        every subdomain can serve an app (``Project.add_domain``) or send an app's email
        without a record of its own: the way to give each of your users an address under yours.
        Each subdomain goes live once its certificate is issued, usually within minutes of its
        first use.

        Returns:
            The domain, ``pending_dns`` until the records in ``records`` are added where its DNS is
            hosted, with ``setup_url`` when that host can add them in one click (the open Domain
            Connect standard; the host's consent page names NoClick alongside your brand).

        Usage:
            Connect a domain and add its records where its DNS is hosted::

                domain = noclick.Domain.connect("acme.test")
                if domain.setup_url:
                    print("Add the records in one click:", domain.setup_url)
                for record in domain.records:
                    print(record.type, record.name, record.value, record.purpose)

            Connect it for every subdomain::

                domain = noclick.Domain.connect("apps.acme.test", wildcard=True)
                print([record.name for record in domain.records])   # includes *.apps.acme.test
        """
        scope = resolve_scope(user)
        body: Dict[str, Any] = {"name": name, **({"wildcard": True} if wildcard else {})}
        raw = await resolve_client(client).request("POST", "/v1/domains/connect", json=body, user=scope)
        return cls._new(raw=raw, client=client, user=scope)

    @synced
    @staticmethod
    async def transfer_quote(name: str, *, user: Any = AMBIENT, client: Optional[Client] = None) -> TransferQuote:
        """Whether ``name``, registered elsewhere, can move to NoClick now, and what moving it
        costs. Nothing is charged. NoClick works it out from the domain's public registration
        data (its registrar lock, its transfer lock, whether NoClick registers the TLD) and the
        registrar's price, so it's a best answer until ``transfer_in`` is accepted. A domain
        already with NoClick's registrar under another account isn't eligible: ``reason`` says
        moving it between accounts isn't supported yet.

        Returns:
            The quote: ``eligible`` with the ``price_usd`` the transfer charges (it adds ``years``
            to the registration) and the ``renewal_usd`` after, or not eligible with the ``reason``
            and, inside the registry's transfer lock, ``locked_until``.

        Usage::

            quote = noclick.Domain.transfer_quote("acme.test")
            if quote.eligible:
                print(f"Moving it costs ${quote.price_usd} and adds {quote.years} year(s), then ${quote.renewal_usd}")
            else:
                print(quote.reason, quote.locked_until)
        """
        raw = await resolve_client(client).request(
            "GET", "/v1/domains/transfer_quote", params={"name": name}, user=resolve_scope(user),
        )
        return TransferQuote._from(raw or {})

    @synced
    @classmethod
    async def transfer_in(
        cls,
        name: Union[str, TransferQuote, "Domain"],
        *,
        auth_code: str,
        max_price_usd: float,
        registrant: Optional[DomainContact] = None,
        user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> DomainTransfer:
        """Move ``name`` (a name, a ``TransferQuote``, or a domain you connected) to NoClick from
        its current registrar, with the ``auth_code`` that registrar gives for it. It's charged to
        your account like a purchase: the quote, which adds the quote's ``years`` to the
        registration, charged once the transfer completes; refused (``noclick.PriceExceeded``)
        above ``max_price_usd``; held in ``awaiting_human`` while your policy holds purchases. It's
        registered to ``registrant`` on the same rule as ``Domain.buy``, ``agreement_accepted_at``
        included: a user's own, or their registrant profile on file (``noclick.InvalidRequest`` naming
        ``registrant`` with neither), else your account's default registrant. A name the
        registry won't move now raises ``noclick.NotAvailable`` with the reason
        (``transfer_quote`` says so first).

        Its nameservers don't change during the move, so its DNS keeps working where it's hosted.
        Once it's ``active``, ``use_noclick_dns()`` moves the DNS to NoClick, or it stays where it
        is like a connected domain. A connected domain keeps its id and what it serves, and passed
        as a ``Domain`` the transfer acts in that domain's own scope (its user, else your account);
        a name acts for the current user, or ``user=``.

        Returns:
            The transfer: an operation whose ``.wait()`` gives the ``Domain`` once it's moved,
            ``source`` ``transferred``. The domain is ``transferring_in`` meanwhile, up to about 5
            days; the current owner may be emailed by their registrar to approve. If the registry
            refuses (a wrong auth code is ``noclick.InvalidRequest`` naming ``auth_code``), the
            transfer fails with its reason and nothing is charged.

        Usage:
            Check it can move, then move it with the code from its current registrar::

                quote = noclick.Domain.transfer_quote("acme.test")
                if quote.eligible:
                    transfer = noclick.Domain.transfer_in(quote, auth_code="Xy7#pQ2!", max_price_usd=15)
                    domain = transfer.wait()
                    print(domain.source, domain.expires_at)   # transferred, quote.years later than before

            A user's domain is registered to them, charged to you::

                ana = noclick.DomainContact(
                    name="Ana Silva", email="ana@example.com", phone="+14155550123",
                    address="500 Market St", city="San Francisco", region="CA", postal_code="94105", country="US",
                    agreement_accepted_at=accepted_at,   # when she accepted noclick.Domain.agreement()
                )
                with noclick.as_user("user_42"):
                    transfer = noclick.Domain.transfer_in(
                        "anasilva.dev", auth_code="Kq9!mT4z", max_price_usd=20, registrant=ana,
                    )
        """
        if isinstance(name, Domain):
            if user is not AMBIENT:
                raise TypeError("A Domain transfers in its own scope; pass user= with a name instead.")
            wire_name = await domain_name(name)  # loads a lazy domain, so its user is known
            scope = name._call_scope()
        else:
            wire_name = name.name if isinstance(name, TransferQuote) else name
            scope = resolve_scope(user)
        payload = await resolve_client(client).request(
            "POST", "/v1/domains/transfer_in",
            json=compact(
                name=wire_name, auth_code=auth_code, max_price_usd=max_price_usd,
                registrant=registrant._wire() if registrant is not None else None,
            ),
            user=scope,
        )
        return DomainTransfer._from_payload(
            payload, client=client, user=scope, kind="domain.transfer_in", reader=_read_domain,
        )

    # --- references --------------------------------------------------------

    @classmethod
    def from_name(
        cls,
        name: str,
        *,
        create_if_missing: bool = False,
        max_price_usd: Optional[float] = None,
        years: Optional[int] = None,
        registrant: Optional[DomainContact] = None,
        auto_renew: Any = UNSET,
        client: Optional[Client] = None,
        user: Any = AMBIENT,
    ) -> "Domain":
        """A lazy reference to your domain called ``name``, bought or connected. An ``auto_renew``
        you pass is set on it every run. With ``create_if_missing=True`` your code owns it
        idempotently: the first time it's used with no such domain, it's bought as ``Domain.buy``
        would (``max_price_usd`` is required and ``years`` is the TLD's minimum when left out;
        inside ``as_user`` the user's ``registrant`` or registrant profile on file is required too, and
        outside it defaults to your account's own default registrant: with none set, the first use raises
        ``noclick.ActionRequired`` whose ``next_step`` links to where it's set). ``max_price_usd``,
        ``years`` and ``registrant`` say how to buy it, so they matter only then. A name someone
        else holds raises ``noclick.NotAvailable``.

        Returns:
            A domain that loads (or is bought) the first time you read a field; ``noclick.NotFound``
            then if there's none. A domain just bought is ``registering`` (``awaiting_human`` while
            your policy holds it) until the purchase finishes. Nothing is sent yet.

        Usage:
            Refer to a domain you have::

                domain = noclick.Domain.from_name("acmebooking.com")
                print(domain.status, domain.expires_at)

            Or own it from code, run at every deploy: the first run buys it::

                domain = noclick.Domain.from_name("acmebooking.com", create_if_missing=True, max_price_usd=15)
                print(domain.status)   # registering, then active
        """
        domain = cls._new(hints={"name": name}, client=client, user=user)
        if create_if_missing:
            if max_price_usd is None:
                raise ValueError("Domain.from_name(create_if_missing=True) needs max_price_usd=")
        domain._define(compact(
            name=name, max_price_usd=max_price_usd, years=years,
            registrant=registrant._wire() if registrant is not None else None,
            auto_renew=None if auto_renew is UNSET else auto_renew,
        ), create_if_missing=create_if_missing)
        return domain

    @classmethod
    def from_id(cls, domain_id: str, *, client: Optional[Client] = None, user: Any = AMBIENT) -> "Domain":
        """A lazy reference to a domain by id.

        Returns:
            A domain that loads the first time you read a field. Nothing is sent yet.

        Usage::

            domain = noclick.Domain.from_id("5c8e2a1f-7b3d-4e96-a0c4-9d1f6b2e8a57")
            print(domain.name, domain.serves)
        """
        return cls._new(hints={"id": domain_id}, client=client, user=user)

    @synced
    @classmethod
    async def get(cls, domain_id: str, *, user: Any = AMBIENT, client: Optional[Client] = None) -> "Domain":
        """Load a domain by id now; an unknown id raises ``noclick.NotFound``.

        Returns:
            The domain, loaded.

        Usage::

            domain = noclick.Domain.get("5c8e2a1f-7b3d-4e96-a0c4-9d1f6b2e8a57")
            print(domain.name, domain.source, domain.status)
        """
        domain = cls.from_id(domain_id, client=client, user=user)
        await domain._ensure()
        return domain

    @synced
    @classmethod
    async def list(
        cls, *, limit: Optional[int] = None, user_filter: Any = None, user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> List["Domain"]:
        """Your domains, bought and connected (the current user's inside ``as_user``, or those ``user_filter`` covers).

        Returns:
            Every matching domain, newest first, fetched page by page. A domain transferred out
            or disconnected isn't listed.

        Usage::

            for domain in noclick.Domain.list():
                print(domain.name, domain.source, domain.status, domain.expires_at)

            everyone = noclick.Domain.list(user_filter=noclick.ALL_USERS)   # every user's, plus your account's
        """
        return await list_all(
            "/v1/domains", lambda raw, scope: cls._new(raw=raw, client=client, user=scope),
            user=user, user_filter=user_filter, limit=limit, client=client,
        )

    @synced
    @classmethod
    async def list_page(
        cls, *, cursor: Optional[str] = None, limit: Optional[int] = None, user_filter: Any = None,
        user: Any = AMBIENT, client: Optional[Client] = None,
    ) -> Page:
        """One page of domains; pass ``next_cursor`` back as ``cursor``.

        Returns:
            A page whose ``data`` holds the domains and whose ``next_cursor`` is ``None`` on the last page.

        Usage::

            page = noclick.Domain.list_page(limit=50)
            while True:
                for domain in page.data:
                    print(domain.name)
                if page.next_cursor is None:
                    break
                page = noclick.Domain.list_page(limit=50, cursor=page.next_cursor)
        """
        return await list_page(
            "/v1/domains", lambda raw, scope: cls._new(raw=raw, client=client, user=scope),
            user=user, user_filter=user_filter, cursor=cursor, limit=limit, client=client,
        )

    async def _path(self) -> str:
        domain_id = self._known("id") or (await self._ensure())["id"]
        return f"/v1/domains/{domain_id}"

    async def _load(self) -> Dict[str, Any]:
        domain_id = self._known("id")
        if domain_id:
            return await self._request("GET", f"/v1/domains/{domain_id}")
        name = self._hints["name"]
        page = await self._request("GET", "/v1/domains", params={"name": name}) or {}
        rows = [row for row in page.get("data") or [] if row.get("name") == name]
        if rows:
            return await self._converge(rows[0])
        if not self._creates:
            raise NotFound(
                f"No domain is named {name!r}.",
                next_step="Buy it with noclick.Domain.buy(...) or connect it with noclick.Domain.connect(...).",
                details={"name": name},
            )
        try:
            purchase = await self._request("POST", "/v1/domains", json=self._create_with) or {}
        except Conflict as exc:  # bought concurrently
            if not exc.existing_id:
                raise
            return await self._converge(await self._request("GET", f"/v1/domains/{exc.existing_id}"))
        return await self._request("GET", f"/v1/domains/{purchase['domain_id']}")

    async def _converge(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Set ``auto_renew`` on an existing domain when ``from_name`` was given it."""
        wanted = (self._create_with or {}).get("auto_renew")
        if wanted is None or raw.get("auto_renew") == wanted:
            return raw
        return await self._request("PATCH", f"/v1/domains/{raw['id']}", json={"auto_renew": wanted})

    # --- actions ---------------------------------------------------------

    @synced
    async def verify(self) -> "Domain":
        """Check the domain's DNS now, rather than waiting for NoClick's own checks (every few
        minutes while records are pending).

        Returns:
            This domain, with each record's ``status`` and the domain's own ``status`` as found.

        Usage::

            domain = noclick.Domain.from_name("acme.test")
            domain.verify()
            print(domain.status)   # active once every required record is verified
            for record in domain.records:
                print(record.name, record.type, record.status)
        """
        self._raw = await self._request("POST", f"{await self._path()}/verify")
        return self

    @synced
    async def update(
        self, *, auto_renew: Optional[bool] = None, registrant: Optional[DomainContact] = None,
    ) -> "Domain":
        """Change a bought domain's settings; one you leave out is unchanged.

        ``registrant`` replaces the details of the person it's registered to. ICANN requires
        accurate details, so update them when the person's change. Changing the registrant's
        name, organization or email asks the new registrant to confirm their email again (the
        domain is ``registrant_unverified`` meanwhile) and may start the registry's transfer lock
        (see ``transfer_locked_until``).

        Returns:
            This domain, updated.

        Usage:
            Stop renewing, so the domain lapses at ``expires_at``::

                domain = noclick.Domain.from_name("acmebooking.com")
                domain.update(auto_renew=False)

            Keep the registrant's details current when they change::

                import dataclasses
                domain = noclick.Domain.from_name("anasilva.dev")
                domain.update(registrant=dataclasses.replace(domain.registrant, email="ana@newmail.example"))
                print(domain.status)   # registrant_unverified until Ana confirms the new address
        """
        self._raw = await self._request("PATCH", await self._path(), json=compact(
            auto_renew=auto_renew, registrant=registrant._wire() if registrant is not None else None,
        ))
        return self

    @synced
    async def renew(self, *, years: Optional[int] = None, max_price_usd: float) -> DomainPurchase:
        """Extend a bought domain's registration now, instead of waiting for auto-renew, by
        ``years``, or left out the TLD's minimum term (``renewal_years``, which ``renewal_usd``
        prices). It's charged to your account when the renewal lands, refused
        (``noclick.PriceExceeded``) above ``max_price_usd``, and like a purchase it may wait in
        ``awaiting_human`` for your policy's approver.

        An ``expired`` domain renews until ``renewable_until``. After that it raises
        ``noclick.NotAvailable``: renewing past the guaranteed renewal window, or restoring a
        domain the registry is about to delete, isn't an API call (NoClick support may be able to
        restore it, at the registry's restore fee).

        Returns:
            The renewal: an operation whose ``.wait()`` gives the ``Domain`` with its later ``expires_at``.

        Usage::

            domain = noclick.Domain.from_name("acmebooking.com")
            renewal = domain.renew(max_price_usd=15)   # renewal_years, at renewal_usd
            print(renewal.wait().expires_at)
        """
        payload = await self._request(
            "POST", f"{await self._path()}/renew", json=compact(years=years, max_price_usd=max_price_usd),
        )
        return DomainPurchase._from_payload(
            payload, client=self._client, user=self._call_scope(), kind="domain.renew", reader=_read_domain,
        )

    @synced
    async def use_noclick_dns(self) -> List[DnsRecord]:
        """Move a transferred domain's DNS hosting to NoClick. The records NoClick can read
        where its DNS is hosted now are copied first, then its nameservers change, so it keeps
        answering throughout. On a domain whose DNS NoClick already hosts, it copies nothing;
        a connected domain raises ``noclick.NotAvailable`` (transfer it in first).

        Returns:
            The records it copied, for review: add any it couldn't read with ``dns.set``.
            The domain's ``noclick_dns`` is now True.

        Usage::

            domain = noclick.Domain.from_name("acme.test")
            for record in domain.use_noclick_dns():
                print("Copied", record.type, record.name, record.value)
            domain.dns.set("TXT", "@", "google-site-verification=3pL0x0kA1b2C")   # one it couldn't read
        """
        raw = await self._request("POST", f"{await self._path()}/use_noclick_dns")
        self._raw = raw["domain"]
        return _records(raw.get("copied"))

    @synced
    async def transfer_out(self) -> TransferCode:
        """Unlock a bought or transferred domain to move it to another registrar. Inside the
        registry's transfer lock after a domain is registered, transferred in or its registrant
        changes (``transfer_locked_until``) it raises ``noclick.NotAvailable``, and a connected
        domain has nothing to transfer.

        Returns:
            The auth code to give the other registrar, until its ``expires_at`` (call
            ``transfer_out()`` again for a fresh one). The domain shows ``transferring_out``
            until the move completes, then leaves your list.

        Usage::

            domain = noclick.Domain.from_name("acmebooking.com")
            try:
                code = domain.transfer_out()
            except noclick.NotAvailable as err:
                print(err.message, domain.transfer_locked_until)
            else:
                print("Give your new registrar:", code.auth_code)
        """
        raw = await self._request("POST", f"{await self._path()}/transfer_out") or {}
        return TransferCode(
            raw.get("auth_code"), parse_time(raw.get("unlocked_at")), parse_time(raw.get("expires_at")), raw,
        )

    @synced
    async def delete(self) -> None:
        """Disconnect a connected domain: it stops serving your apps, and its DNS stays as it
        is where it's hosted. It raises ``noclick.Conflict`` while an inbox still uses the
        domain, and on a bought domain, which can only lapse or be transferred out.

        Usage::

            domain = noclick.Domain.from_name("acme.test")
            domain.delete()
        """
        await self._request("DELETE", await self._path())
