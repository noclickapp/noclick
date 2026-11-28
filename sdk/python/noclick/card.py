"""Cards: virtual cards with limits, for agents that buy things.

    card = noclick.Card.create("Office supplies", limit_usd=1500, interval="month",
                               merchants=["office_supplies"], agent=buyer, require_approval_above_usd=200)
    details = card.purchase(124.50, "Staples", reason="Toner").wait()   # approved first when above $200
    for charge in card.transactions(limit=20):
        print(charge.merchant, charge.amount_usd, charge.status)
    card.freeze()

Cards are your company's commercial cards, for US businesses, in dollars. They spend
your company's own card balance, held by Stripe Payments Company (``Card.funding()``), which you
fund by bank transfer: what a card pays isn't charged to your NoClick account, which
pays only $0.13 per card number issued. Cards need card issuing, which your company
applies for once in the console (``Card.program()``); until it's active these calls
raise ``noclick.NotAvailable``. A card number is shown only on a page where the card
issuer's own element displays it (``reveal()``): it never passes through NoClick,
your code or a model.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from ._client import Client, resolve_client
from ._designed import designed
from ._object import UNSET, Page, _Object, compact, field, list_all, list_page, paginate, parse_time
from ._sync import synced
from .operation import Operation, register_result
from ._scope import AMBIENT, resolve_scope
from .agent import agent_id
from .exceptions import Conflict, NotFound

# What ``from_name`` sets on an existing card.
_CONVERGED = ("limit_usd", "interval", "merchants", "require_approval_above_usd", "agent_id", "single_use")


@designed
@dataclass(frozen=True)
class CardDispute:
    """A settled charge disputed with the card network. ``status`` is ``submitted``,
    then ``won`` (the money comes back to your card balance), ``lost`` or ``expired``."""

    id: Optional[str]
    transaction_id: Optional[str]
    # ``fraudulent``, ``canceled``, ``duplicate``, ``not_received``, ``not_as_described`` or ``incorrect_amount``.
    reason: Optional[str]
    status: Optional[str]
    amount_usd: Optional[float]
    created_at: Any
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Any) -> "CardDispute":
        raw = raw if isinstance(raw, dict) else {}
        return cls(raw.get("id"), raw.get("transaction_id"), raw.get("reason"), raw.get("status"),
                   raw.get("amount_usd"), parse_time(raw.get("created_at")), raw)


@designed
@dataclass(frozen=True)
class CardTransaction:
    """One charge or refund on a card. A ``charge`` is ``approved`` (its amount held
    until the merchant settles it), ``settled`` (``settled_amount_usd``, which can
    differ for tips and shipping), ``reversed`` (released unsettled), ``declined`` or
    ``pending_approval`` (held for a person). A ``refund`` is settled, its
    ``amount_usd`` below zero. A decline says why in ``decline_reason``: ``over_limit``,
    ``over_budget`` (an app's card, past what's left of the app's budget), ``merchant_not_allowed``, ``frozen``, ``insufficient_funds``, ``amount_mismatch``
    (more than a purchase's number allows), ``not_approved``, ``approval_expired``,
    ``awaiting_approval``, ``card_closed``, ``card_expired``, ``invalid_cvc``,
    ``invalid_expiry``, ``3ds_failed`` or ``issuer_declined``."""

    id: Optional[str]
    card_id: Optional[str]
    kind: Optional[str]
    amount_usd: Optional[float]
    settled_amount_usd: Optional[float]
    merchant: Optional[str]
    # The ``Card.merchant_categories()`` name its ``merchant_mcc`` is in (None: none of them).
    merchant_category: Optional[str]
    merchant_mcc: Optional[str]
    status: Optional[str]
    decline_reason: Optional[str]
    # The held charge's approval, an operation: ``Operation.from_id(approval_id).wait()`` is ``True`` once approved.
    approval_id: Optional[str]
    # The ``card.purchase`` operation whose number paid it.
    purchase_id: Optional[str]
    # The number it was on (a single-use card has one per checkout).
    last4: Optional[str]
    dispute: Optional[CardDispute]
    at: Any
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Any) -> "CardTransaction":
        raw = raw if isinstance(raw, dict) else {}
        dispute = raw.get("dispute")
        return cls(
            raw.get("id"), raw.get("card_id"), raw.get("kind"), raw.get("amount_usd"), raw.get("settled_amount_usd"),
            raw.get("merchant"), raw.get("merchant_category"), raw.get("merchant_mcc"), raw.get("status"),
            raw.get("decline_reason"), raw.get("approval_id"), raw.get("purchase_id"), raw.get("last4"),
            CardDispute._from(dispute) if dispute else None, parse_time(raw.get("at")), raw,
        )


@designed
@dataclass(frozen=True)
class CardDetails:
    """A card number to pay with, shown only at ``url``: a page where the card
    issuer's own element displays the number, CVC and expiry to whoever opens it,
    until ``expires_at``. The number never passes through NoClick, your code or a
    model, so send ``url`` only to the person who pays. Its ``repr`` leaves ``url`` out."""

    url: str = dc_field(repr=False)
    expires_at: Any
    last4: Optional[str]
    brand: Optional[str]
    exp_month: Optional[int]
    exp_year: Optional[int]
    # A number that takes one charge (every number of a single-use card, every purchase's).
    single_use: Optional[bool]
    # A purchase's exact amount: the most its one charge may be.
    amount_usd: Optional[float]
    # When a single-use number nobody paid with closes.
    closes_at: Any
    # The name and billing address a checkout asks for: your company's.
    cardholder: Optional[str]
    billing_address: Optional[Dict[str, Any]]
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Any) -> "CardDetails":
        raw = raw if isinstance(raw, dict) else {}
        return cls(
            str(raw.get("url") or ""), parse_time(raw.get("expires_at")), raw.get("last4"), raw.get("brand"),
            raw.get("exp_month"), raw.get("exp_year"), raw.get("single_use"), raw.get("amount_usd"),
            parse_time(raw.get("closes_at")), raw.get("cardholder"), raw.get("billing_address"), raw,
        )


@designed
@dataclass(frozen=True)
class CardBankTransfer:
    """Where your company sends money to fund its card balance: a wire lands the
    same day, an ACH transfer within a few business days."""

    bank_name: Optional[str]
    routing_number: Optional[str]
    account_number: Optional[str]
    # ``ach`` and ``wire``.
    networks: List[str]


@designed
@dataclass(frozen=True)
class CardFunding:
    """Your company's card balance, held by Stripe Payments Company: every card spends from it.
    ``pending_usd`` is held by charges that haven't settled. The balance can drop
    below zero when a merchant takes a charge without asking (allowed even after a
    number closes); NoClick then freezes every card until it's funded again
    (``frozen_since``, and the ``card.balance.negative`` event)."""

    balance_usd: Optional[float]
    pending_usd: Optional[float]
    # What cards can still spend: the balance less what's pending.
    available_usd: Optional[float]
    # The console page with these bank details.
    top_up_url: Optional[str]
    bank_transfer: Optional[CardBankTransfer]
    # Since when your cards have been frozen because the balance is below zero (None: they aren't).
    frozen_since: Any
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Any) -> "CardFunding":
        raw = raw if isinstance(raw, dict) else {}
        transfer = raw.get("bank_transfer")
        return cls(
            raw.get("balance_usd"), raw.get("pending_usd"), raw.get("available_usd"), raw.get("top_up_url"),
            CardBankTransfer(transfer.get("bank_name"), transfer.get("routing_number"), transfer.get("account_number"),
                             list(transfer.get("networks") or [])) if isinstance(transfer, dict) else None,
            parse_time(raw.get("frozen_since")), raw,
        )


@designed
@dataclass(frozen=True)
class CardProgram:
    """Card issuing for your company. ``status``: ``not_started``, then
    ``pending_verification`` while the card issuer verifies the company (what it
    still needs is in ``requirements_due``), ``active``; or ``rejected``, or
    ``restricted`` (it was active and needs something again). Your company applies
    once, in the console at ``onboarding_url``: US-registered businesses, in dollars."""

    status: str
    requirements_due: List[str]
    company_name: Optional[str]
    country: Optional[str]
    currency: Optional[str]
    onboarding_url: Optional[str]
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Any) -> "CardProgram":
        raw = raw if isinstance(raw, dict) else {}
        return cls(str(raw.get("status") or ""), list(raw.get("requirements_due") or []), raw.get("company_name"),
                   raw.get("country"), raw.get("currency"), raw.get("onboarding_url"), raw)


@designed
@dataclass(frozen=True)
class CardOnboardingSession:
    """A session for the card issuer's embedded onboarding form (``Card.onboarding_session()``): ``client_secret``
    and ``publishable_key`` open it on the company's ``account`` at the issuer."""

    client_secret: str
    publishable_key: str
    account: str
    expires_at: Optional[datetime]
    program: CardProgram
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Any) -> "CardOnboardingSession":
        raw = raw if isinstance(raw, dict) else {}
        return cls(str(raw.get("client_secret") or ""), str(raw.get("publishable_key") or ""),
                   str(raw.get("account") or ""), parse_time(raw.get("expires_at")),
                   CardProgram._from(raw.get("program")), raw)


@designed
@dataclass(frozen=True)
class CardMerchantCategory:
    """A name ``merchants`` takes, and the merchant category codes it covers."""

    name: str
    description: Optional[str]
    mccs: List[str]


register_result("card.purchase", lambda raw, op: CardDetails._from(raw))


def _merchants(merchants: Optional[Sequence[str]]) -> Optional[List[str]]:
    if merchants is None:
        return None
    return [merchants] if isinstance(merchants, str) else list(merchants)


@designed
class Card(_Object):
    """A virtual card with a spending limit. ``Card.from_name("Office supplies",
    create_if_missing=True, limit_usd=1500)`` is lazy; ``card.purchase(...)`` approves
    and pays one purchase, ``card.reveal()`` shows its number to a person.

    A card is always your company's, for its business, including buying for one of
    your users: a card issued for a user (``user=``) is one only that user's agents
    can pay with, never a card the user owns or funds. It may be held by one agent,
    which pays with it at checkouts in its browser.
    """

    _repr_keys = ("id", "name", "last4", "status")

    id: str = field("id")
    name: str = field("name")
    last4: Optional[str] = field("last4")
    brand: Optional[str] = field("brand", doc="The card network, like ``visa``.")
    exp_month: Optional[int] = field("exp_month")
    exp_year: Optional[int] = field("exp_year")
    status: str = field("status", doc="``active``, ``frozen`` or ``closed``.")
    status_reason: Optional[str] = field(
        "status_reason",
        doc="Why it's frozen when nobody froze it: ``negative_balance`` while your card balance is below zero "
            "(it pays again once funded). None otherwise.",
    )
    limit_usd: Optional[float] = field("limit_usd", doc="The most it spends per ``interval`` (None: no limit).")
    interval: Optional[str] = field(
        "interval", doc="What ``limit_usd`` covers: ``transaction``, ``day``, ``month`` or ``all_time``.",
    )
    spent_usd: Optional[float] = field(
        "spent_usd", doc="Spent in the current interval (this calendar month's spend for a per-transaction limit).",
    )
    resets_at: Any = field("resets_at", parse_time, doc="When ``spent_usd`` starts over (None for ``all_time``).")
    merchants: Optional[List[str]] = field("merchants", doc="The merchant categories it may pay (None: any).")
    require_approval_above_usd: Optional[float] = field(
        "require_approval_above_usd", doc="Charges above this wait for a person (None: never).",
    )
    agent_id: Optional[str] = field("agent_id", doc="The agent that pays with it (None if none).")
    single_use: Optional[bool] = field(
        "single_use",
        doc="Whether every checkout gets a fresh number that takes one charge (``last4`` is the latest one's).",
    )
    user_id: Optional[str] = field("user_id")
    created_at: Any = field("created_at", parse_time)

    def _init(self, **kwargs: Any) -> None:
        self._create_with: Optional[Dict[str, Any]] = None
        super()._init(**kwargs)

    @staticmethod
    def _body(
        name: Optional[str], limit_usd: Optional[float], interval: Optional[str], merchants: Optional[Sequence[str]],
        agent: Any, require_approval_above_usd: Optional[float], single_use: Optional[bool] = None,
    ) -> Dict[str, Any]:
        # ``agent_id`` may still be a lazy Agent here; ``_wire`` resolves it.
        return compact(
            name=name, limit_usd=limit_usd, interval=interval, merchants=_merchants(merchants),
            agent_id=agent, require_approval_above_usd=require_approval_above_usd, single_use=single_use,
        )

    @staticmethod
    async def _wire(body: Dict[str, Any]) -> Dict[str, Any]:
        if body.get("agent_id") is not None:
            body = {**body, "agent_id": await agent_id(body["agent_id"])}
        return body

    # --- construction ----------------------------------------------------

    @synced
    @classmethod
    async def create(
        cls,
        name: str,
        *,
        limit_usd: float,
        interval: str = "month",
        merchants: Optional[Sequence[str]] = None,
        agent: Any = None,
        require_approval_above_usd: Optional[float] = None,
        single_use: bool = False,
        allow_existing: bool = False,
        user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> "Card":
        """Issue a virtual card called ``name`` (unique among your open cards in
        its user; a duplicate raises ``noclick.Conflict`` with ``existing_id``). With
        ``allow_existing=True`` a taken name returns the open card already there, as it is:
        nothing about it changes, and no number is issued.

        ``limit_usd`` caps what it spends per ``interval`` (``"transaction"``,
        ``"day"``, ``"month"`` or ``"all_time"``). ``merchants`` names the merchant
        categories it may pay (``"office_supplies"``, ``"software"``, ``"travel"``,
        ...; any when omitted; never cash, money transfers, gambling or securities).
        ``agent`` (an ``noclick.Agent`` or id) is the agent that pays with it. A purchase
        above ``require_approval_above_usd`` is approved by a person before anything is
        paid (``purchase``); a charge above it that nobody announced is declined and the
        merchant's retry passes once they approve. ``single_use=True`` gives every
        checkout (every purchase, every ``reveal()``) a fresh number that takes one charge
        and then closes, so a merchant that keeps a number can never charge it again;
        together they spend within ``limit_usd`` per ``interval`` (UTC days and months).

        Returns:
            The new card, ``active``, with its ``last4`` and expiry (a single-use card has none until its first
            checkout). Its number is only ever shown on ``reveal()``'s page. Each number costs $0.13.

        Usage:
            A monthly card for one agent, where anything over $200 needs a yes::

                buyer = noclick.Agent.from_name("concierge", user="acme")
                card = noclick.Card.create(
                    "Office supplies", limit_usd=1500, interval="month",
                    merchants=["office_supplies"], agent=buyer, require_approval_above_usd=200, user="acme",
                )
                print(card.last4, card.limit_usd, card.interval)

            A card for your own code, capped per charge instead of per month::

                card = noclick.Card.create("Software", limit_usd=200, interval="transaction", merchants=["software"])

            A fresh number for every purchase, for merchants you'd rather not keep one::

                buyer = noclick.Agent.from_name("buyer")
                card = noclick.Card.create("Marketplace", limit_usd=500, interval="month", agent=buyer, single_use=True)
        """
        scope = resolve_scope(user)
        body = await cls._wire(cls._body(
            name, limit_usd, interval, merchants, agent, require_approval_above_usd, single_use or None,
        ))
        raw = await cls._create_named("/v1/cards", body, allow_existing=allow_existing, user=scope, client=client)
        return cls._new(raw=raw, client=client, user=scope)

    @classmethod
    def from_name(
        cls,
        name: str,
        *,
        create_if_missing: bool = False,
        limit_usd: Optional[float] = None,
        interval: Optional[str] = None,
        merchants: Optional[Sequence[str]] = None,
        agent: Any = UNSET,
        require_approval_above_usd: Any = UNSET,
        single_use: Optional[bool] = None,
        user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> "Card":
        """A lazy reference to the open card called ``name`` in the current (or
        given) user. Given fields, it gets the card and sets the ones you pass, on every run: an
        existing card whose limit, interval, merchants, approval threshold, agent or ``single_use``
        differ is updated to yours. ``create_if_missing=True`` issues it with ``create``'s fields
        when there's none (``interval`` is ``"month"`` unless you pass one); without it, a missing
        card raises ``noclick.NotFound``. A field you leave out is never changed,
        and ``None`` clears ``agent`` or ``require_approval_above_usd``, as in ``update()``.
        Each run with fields is a write: set them at startup or in a setup script, and take the
        bare ``from_name`` in request handlers.

        Returns:
            A card that loads (or is issued, or has your fields set) the first time it's used.
            Nothing is sent yet.

        Usage:
            Refer to a card by name::

                card = noclick.Card.from_name("Office supplies", user="acme")
                print(card.spent_usd, card.limit_usd)

            Or get it, issuing it if it's missing, and set its limits. ``limit_usd`` is required then::

                card = noclick.Card.from_name(
                    "Travel", create_if_missing=True, limit_usd=3000, interval="month",
                    merchants=["travel"], agent=noclick.Agent.from_name("assistant", user="user_42"), user="user_42",
                )
                print(card.last4)
        """
        card = cls._new(hints={"name": name}, client=client, user=user)
        if create_if_missing and limit_usd is None:
            raise ValueError("Card.from_name(create_if_missing=True) needs limit_usd=")
        nullable = dict(agent_id=agent, require_approval_above_usd=require_approval_above_usd)
        card._define({
            **cls._body(name, limit_usd, interval, merchants, None if agent is UNSET else agent,
                        None if require_approval_above_usd is UNSET else require_approval_above_usd,
                        single_use),
            # An explicit None is a field you pass: it clears it on an existing card.
            **{k: None for k, v in nullable.items() if v is None},
        }, create_if_missing=create_if_missing)
        return card

    @classmethod
    def from_id(cls, card_id: str, *, client: Optional[Client] = None, user: Any = AMBIENT) -> "Card":
        """A lazy reference to a card by id.

        Returns:
            A card that loads the first time you read a field. Nothing is sent yet.

        Usage::

            card = noclick.Card.from_id("c4a7e2b9-3d1f-4a8e-b6c5-9f2d0e7a1b36")
            card.freeze()
        """
        return cls._new(hints={"id": card_id}, client=client, user=user)

    @synced
    @classmethod
    async def get(cls, card_id: str, *, user: Any = AMBIENT, client: Optional[Client] = None) -> "Card":
        """Load a card by id now; an unknown id raises ``noclick.NotFound``.

        Returns:
            The card, loaded, with this interval's ``spent_usd``.

        Usage::

            card = noclick.Card.get("c4a7e2b9-3d1f-4a8e-b6c5-9f2d0e7a1b36")
            print(card.name, card.status, card.spent_usd, card.limit_usd)
        """
        card = cls.from_id(card_id, client=client, user=user)
        await card._ensure()
        return card

    @synced
    @classmethod
    async def list(
        cls, *, status: Optional[str] = None, agent: Any = None, limit: Optional[int] = None,
        user_filter: Any = None, user: Any = AMBIENT, client: Optional[Client] = None,
    ) -> List["Card"]:
        """The current user's cards (the account's own outside ``as_user``, or those
        ``user_filter`` covers), optionally one ``status`` or one ``agent``'s.

        Returns:
            Every matching card, newest first, fetched page by page. Closed cards are listed only with ``status="closed"``.

        Usage::

            for card in noclick.Card.list(user_filter=noclick.ALL_USERS):
                print(card.name, card.last4, card.status, card.spent_usd)

            frozen = noclick.Card.list(status="frozen", user="user_42")
        """
        return await list_all(
            "/v1/cards", lambda raw, scope: cls._new(raw=raw, client=client, user=scope),
            params={"status": status, "agent_id": await agent_id(agent)}, user=user,
            user_filter=user_filter, limit=limit, client=client,
        )

    @synced
    @classmethod
    async def list_page(
        cls, *, cursor: Optional[str] = None, limit: Optional[int] = None, status: Optional[str] = None,
        agent: Any = None, user_filter: Any = None, user: Any = AMBIENT, client: Optional[Client] = None,
    ) -> Page:
        """One page of cards; pass ``next_cursor`` back as ``cursor``.

        Returns:
            A page whose ``data`` holds the cards and whose ``next_cursor`` is ``None`` on the last page.

        Usage::

            page = noclick.Card.list_page(limit=50, user_filter=noclick.ALL_USERS)
            while True:
                for card in page.data:
                    print(card.name, card.status)
                if page.next_cursor is None:
                    break
                page = noclick.Card.list_page(limit=50, user_filter=noclick.ALL_USERS, cursor=page.next_cursor)
        """
        return await list_page(
            "/v1/cards", lambda raw, scope: cls._new(raw=raw, client=client, user=scope),
            params={"status": status, "agent_id": await agent_id(agent)}, user=user,
            user_filter=user_filter, cursor=cursor, limit=limit, client=client,
        )

    @synced
    @classmethod
    async def funding(cls, *, client: Optional[Client] = None) -> CardFunding:
        """Your company's card balance, which every card (the account's and every user's) spends from.

        Returns:
            The ``balance_usd``, what pending charges hold (``pending_usd``), what cards can still spend
            (``available_usd``), and the ``bank_transfer`` details that fund it.

        Usage::

            funding = noclick.Card.funding()
            print(funding.balance_usd, funding.pending_usd, funding.available_usd)
            if funding.available_usd is not None and funding.available_usd < 100:
                bank = funding.bank_transfer
                print("Wire funds to", bank.bank_name, bank.routing_number, bank.account_number)
        """
        return CardFunding._from(await resolve_client(client).request("GET", "/v1/cards/funding", user=None))

    @synced
    @classmethod
    async def program(cls, *, client: Optional[Client] = None) -> CardProgram:
        """Where your company's card issuing stands. It's applied for once, in the console.

        Returns:
            The program's ``status`` (``not_started``, ``pending_verification``, ``active``, ``rejected`` or
            ``restricted``), what it still needs (``requirements_due``) and where to apply (``onboarding_url``).

        Usage::

            program = noclick.Card.program()
            if program.status != "active":
                print("Apply for cards at", program.onboarding_url, program.requirements_due)
        """
        return CardProgram._from(await resolve_client(client).request("GET", "/v1/cards/program", user=None))

    @synced
    @classmethod
    async def onboarding_session(cls, *, client: Optional[Client] = None) -> CardOnboardingSession:
        """Open your company's card program on first use and start a session of the card issuer's embedded
        onboarding form, where it applies. The signed-in owner's alone (a key gets ``PermissionDenied``);
        ``Conflict`` once the issuer rejected the company, ``NotAvailable`` where cards aren't enabled.

        Returns:
            The form's ``client_secret`` and ``publishable_key``, the company's ``account`` at the issuer, when the
            session ``expires_at``, and the ``program`` as it stands.

        Usage::

            session = noclick.Card.onboarding_session()
            print(session.account, session.program.status)
        """
        return CardOnboardingSession._from(
            await resolve_client(client).request("POST", "/v1/cards/program/session", user=None))

    @synced
    @classmethod
    async def merchant_categories(cls, *, client: Optional[Client] = None) -> List[CardMerchantCategory]:
        """The names ``merchants`` takes, each with the merchant category codes it covers (a 4-digit code works too).

        Returns:
            Every category, like ``office_supplies``, ``software`` and ``travel``.

        Usage::

            for category in noclick.Card.merchant_categories():
                print(category.name, category.description, category.mccs)
        """
        page = await resolve_client(client).request("GET", "/v1/cards/merchant_categories", user=None) or {}
        return [CardMerchantCategory(row["name"], row.get("description"), list(row.get("mccs") or []))
                for row in page.get("data") or []]

    # --- hydration -------------------------------------------------------

    def _path(self) -> str:
        return f"/v1/cards/{self._known('id')}"

    async def _load(self) -> Dict[str, Any]:
        card_id = self._known("id")
        if card_id:
            return await self._request("GET", f"/v1/cards/{card_id}")
        name = self._hints["name"]
        page = await self._request("GET", "/v1/cards", params={"name": name}) or {}
        rows = [row for row in page.get("data") or [] if row.get("name") == name and row.get("status") != "closed"]
        if rows:
            return await self._converge(rows[0])
        if not self._creates:
            raise NotFound(
                f"No open card is named {name!r}.",
                next_step="Issue it with noclick.Card.create(...) or pass create_if_missing=True.",
                details={"name": name, "kind": "card"},
            )
        try:
            # A card is issued monthly unless the code says otherwise; an existing one keeps its interval.
            body = {"interval": "month", **self._create_with}
            return await self._request("POST", "/v1/cards", json=compact(**await self._wire(body)))
        except Conflict as exc:  # issued concurrently
            if not exc.existing_id:
                raise
            return await self._converge(await self._request("GET", f"/v1/cards/{exc.existing_id}"))

    async def _converge(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Set the fields ``from_name`` was given on an existing card."""
        if self._create_with is None:
            return raw
        wanted = await self._wire({k: v for k, v in self._create_with.items() if k in _CONVERGED})
        changes = {k: v for k, v in wanted.items() if raw.get(k) != v}
        if not changes:
            return raw
        return await self._request("PATCH", f"/v1/cards/{raw['id']}", json=changes)

    async def _act(self, verb: str) -> "Card":
        raw = await self._ensure()
        self._raw = await self._request("POST", f"/v1/cards/{raw['id']}/{verb}")
        return self

    # --- use -------------------------------------------------------------

    @synced
    async def transactions(self, *, status: Optional[str] = None, limit: Optional[int] = 20) -> List[CardTransaction]:
        """Its charges and refunds, newest first: ``status`` narrows to ``approved``,
        ``settled``, ``reversed``, ``declined`` or ``pending_approval``.

        Returns:
            The newest ``limit`` (20 by default; ``None`` for every one), each with its amount,
            merchant, status, for a decline why, and any dispute.

        Usage:
            See what the card paid and what it refused::

                card = noclick.Card.from_name("Office supplies", user="acme")
                for charge in card.transactions(limit=20):
                    print(charge.at, charge.merchant, charge.amount_usd, charge.status, charge.decline_reason)

            Wait on a charge that's held for a person::

                card = noclick.Card.from_name("Office supplies", user="acme")
                for charge in card.transactions(status="pending_approval"):
                    approved = noclick.Operation.from_id(charge.approval_id).wait()
                    print(charge.merchant, "approved" if approved else "declined")
        """
        raw = await self._ensure()
        rows = await paginate(
            self._api, f"/v1/cards/{raw['id']}/transactions", params={"status": status},
            user=self._call_scope(), limit=limit,
        )
        return [CardTransaction._from(row) for row in rows]

    @synced
    async def reveal(self) -> CardDetails:
        """A page that shows the card's number to a person: the card issuer's own
        element displays it there, for 10 minutes, so the number never passes
        through NoClick or your code. On a single-use card it's a fresh number,
        which closes unused after an hour. Needs a key with the ``cards:reveal``
        scope; every reveal is recorded with the key that made it.

        Returns:
            The page's ``url``, when it stops showing the number, the number's ``last4`` and expiry, and the
            cardholder name and billing address a checkout asks for.

        Usage::

            card = noclick.Card.from_name("Software")
            details = card.reveal()
            print(details)   # CardDetails(expires_at=..., last4='4242', ...): the url stays out of logs
            send_to_finance(details.url)   # a person opens it and pays the invoice
        """
        raw = await self._ensure()
        return CardDetails._from(await self._request("POST", f"/v1/cards/{raw['id']}/reveal"))

    @synced
    async def purchase(self, amount_usd: float, merchant: str, *, reason: Optional[str] = None) -> Operation:
        """Approve one purchase before paying it: a number for exactly this purchase,
        which takes one charge of at most ``amount_usd`` (tax and shipping included)
        and then closes. At or under ``require_approval_above_usd`` it's ready at once;
        above it, the card's user (or your account's owner) is asked first, with
        ``merchant`` and ``reason`` shown. Needs the ``cards:reveal`` scope.

        Returns:
            A ``card.purchase`` operation; ``wait()`` returns the ``CardDetails`` to pay with once approved, and
            raises ``noclick.PolicyDenied`` (declined) or ``noclick.Expired`` (nobody answered in 30 minutes).

        Usage::

            card = noclick.Card.from_name("Office supplies", user="acme")
            details = card.purchase(124.50, "Staples", reason="Toner for the office").wait()
            send_to_buyer(details.url)
        """
        raw = await self._ensure()
        payload = await self._request("POST", f"/v1/cards/{raw['id']}/purchases",
                                      json=compact(amount_usd=amount_usd, merchant=merchant, reason=reason))
        return Operation._from_payload(payload, client=self._client, user=self._call_scope(), kind="card.purchase")

    @synced
    async def dispute(
        self,
        transaction: Any,
        *,
        reason: str,
        explanation: str,
        amount_usd: Optional[float] = None,
        product: Optional[str] = None,
        duplicate_of: Any = None,
    ) -> CardDispute:
        """Dispute a settled charge with the card network: ``fraudulent`` (nobody
        here made it), ``canceled``, ``duplicate`` (name the charge it copies in
        ``duplicate_of``), ``not_received``, ``not_as_described`` (say whether it was
        ``merchandise`` or a ``service`` in ``product``) or ``incorrect_amount`` (with
        the ``amount_usd`` in dispute). A wrong purchase your agent made is a merchant
        dispute, not fraud.

        Returns:
            The dispute, ``submitted``; ``card.dispute.updated`` events follow it to ``won`` or ``lost``.

        Usage::

            card = noclick.Card.from_name("Office supplies", user="acme")
            [charge] = card.transactions(limit=1)
            dispute = card.dispute(charge, reason="not_received", explanation="Ordered Sep 2, never delivered.")
            print(dispute.status)   # submitted
        """
        raw = await self._ensure()
        transaction_id = transaction.id if isinstance(transaction, CardTransaction) else transaction
        original = duplicate_of.id if isinstance(duplicate_of, CardTransaction) else duplicate_of
        return CardDispute._from(await self._request(
            "POST", f"/v1/cards/{raw['id']}/transactions/{transaction_id}/dispute",
            json=compact(reason=reason, explanation=explanation, amount_usd=amount_usd, product=product,
                         duplicate_of=original)))

    # --- management ------------------------------------------------------

    @synced
    async def update(
        self,
        *,
        name: Any = UNSET,
        limit_usd: Any = UNSET,
        interval: Any = UNSET,
        merchants: Any = UNSET,
        agent: Any = UNSET,
        require_approval_above_usd: Any = UNSET,
        single_use: Any = UNSET,
    ) -> "Card":
        """Change its limits, merchants, approval threshold, agent, name or
        ``single_use`` (from its next checkout).
        ``None`` clears a field: ``merchants=None`` allows any merchant,
        ``require_approval_above_usd=None`` never asks, ``agent=None`` takes it
        from its agent.

        Returns:
            This card, updated. A field you leave out is unchanged, and changes apply from the next charge.

        Usage::

            card = noclick.Card.from_name("Office supplies", user="acme")
            card.update(limit_usd=2000, require_approval_above_usd=300)
            card.update(merchants=None)   # any merchant from now on
        """
        changes: Dict[str, Any] = {
            k: v for k, v in dict(
                name=name, limit_usd=limit_usd, interval=interval,
                require_approval_above_usd=require_approval_above_usd, single_use=single_use,
            ).items()
            if v is not UNSET
        }
        if merchants is not UNSET:
            changes["merchants"] = _merchants(merchants)
        if agent is not UNSET:
            changes["agent_id"] = await agent_id(agent)
        raw = await self._ensure()
        self._raw = await self._request("PATCH", f"/v1/cards/{raw['id']}", json=changes)
        return self

    @synced
    async def freeze(self) -> "Card":
        """Decline every charge until ``unfreeze()``; the card keeps its number and limits.

        Returns:
            This card, ``frozen``.

        Usage::

            card = noclick.Card.from_name("Travel", user="user_42")
            card.freeze()
            print(card.status)   # frozen
        """
        return await self._act("freeze")

    @synced
    async def unfreeze(self) -> "Card":
        """Let a frozen card pay again. While your card balance is below zero every
        card stays frozen (``status_reason`` ``negative_balance``): this raises
        ``noclick.Conflict`` until it's funded.

        Returns:
            This card, ``active``.

        Usage::

            card = noclick.Card.from_name("Travel", user="user_42")
            card.unfreeze()
            print(card.status)   # active
        """
        return await self._act("unfreeze")

    @synced
    async def close(self) -> "Card":
        """Close the card for good: it declines every charge from now on and its
        number is never reissued. Its transactions stay readable.

        Returns:
            This card, ``closed``.

        Usage::

            card = noclick.Card.from_name("Software")
            card.close()
            print(card.status)   # closed
        """
        return await self._act("close")
