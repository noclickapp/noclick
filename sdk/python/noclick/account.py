"""Your account: its plan, balance, month's spend, counts, limits and defaults (``Account.get``), changing its
defaults (``update``), the account at a glance with what waits and what failed (``status``), the public endpoints a
publishable key may call, what an id or key prefix names (``resolve``), and a one-tap payment link for its owner."""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from ._client import Client, resolve_client
from ._object import UNSET, compact, parse_time
from ._sync import synced


@dataclass(frozen=True)
class PausedSpendingDefault:
    """What a paused user is told when a pause names no message (``message``), and the button with it (``action``:
    ``{"label", "url"}``)."""

    message: Optional[str]
    action: Optional[Dict[str, str]] = None


@dataclass(frozen=True)
class AccountStatus:
    """The account at a glance (``Account.status``): ``account`` (its ``id``, ``name``, ``email``, or ``acting_for``:
    the user a key acts for), ``user_id``, its ``plan``, ``balance``, ``month``, ``caps`` with what each spent, the
    approvals waiting on a person (``approvals_pending``), what failed in the last day (``failing``) and what ran
    last (``operations``)."""

    account: Dict[str, Any]
    user_id: Optional[str]
    plan: Optional[Dict[str, Any]]
    balance: Dict[str, Any]
    month: Dict[str, Any]
    caps: List[Dict[str, Any]]
    approvals_pending: List[Dict[str, Any]]
    failing: List[Dict[str, Any]]
    operations: Dict[str, Any]
    raw: Dict[str, Any] = dc_field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class PublicEndpoint:
    """Something the owner made public that a publishable key may call; ``name`` and ``url`` are ``None`` once it
    stopped being public."""

    kind: str
    id: str
    name: Optional[str]
    url: Optional[str]
    user_id: Optional[str]
    raw: Dict[str, Any] = dc_field(default_factory=dict, repr=False)

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "PublicEndpoint":
        return cls(raw.get("kind") or "", raw.get("id") or "", raw.get("name"), raw.get("url"), raw.get("user_id"), raw)


@dataclass(frozen=True)
class ObjectRef:
    """What ``Account.resolve`` found: the object's ``type`` and ``id``, and the user it belongs to (``None``: the
    account)."""

    type: str
    id: str
    user_id: Optional[str]
    raw: Dict[str, Any] = dc_field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class PaymentLink:
    """A payment link (``Account.payment_link``): what it buys (``label``), what checkout charges (``price_usd``), its
    ``url``, when it lapses, and its operation."""

    kind: str
    label: str
    price_usd: float
    url: str
    expires_at: Optional[datetime]
    operation_id: Optional[str]
    raw: Dict[str, Any] = dc_field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class Account:
    """The account at a glance (``GET /v1/account``): its plan's ``plan_tier``, ``balance`` (``remaining_usd``,
    ``None`` when it can't be read, never 0), this ``month``'s spend, how many of each thing it has (``counts``), its
    ``limits`` and ``features``, its ``default_region`` and the default a paused user is told (``spending_paused``),
    and what the platform offers (``scopes``, ``explicit_scopes``). The signed-in owner also reads ``email``,
    ``spend_cap`` and ``console_key_id``; one of the account's own secret keys reads the rest."""

    id: str
    email: Optional[str]
    #: Who owns it, as NoClick knows them (``name``, ``email``, ``phone``, each only when known): the signed-in
    #: owner's view only.
    owner: Optional[Dict[str, str]]
    plan_tier: Optional[str]
    balance: Dict[str, Any]
    month: Dict[str, Any]
    spend_cap: Optional[Dict[str, Any]]
    counts: Dict[str, int]
    limits: Dict[str, int]
    features: Dict[str, bool]
    default_region: Optional[str]
    spending_paused: Optional[PausedSpendingDefault]
    console_key_id: Optional[str]
    #: What a key with every scope (``*``) holds.
    scopes: List[str]
    #: The scopes a key holds only when it names them.
    explicit_scopes: List[str]
    raw: Dict[str, Any] = dc_field(default_factory=dict, repr=False)

    @classmethod
    def _from(cls, raw: Any) -> "Account":
        raw = raw if isinstance(raw, dict) else {}
        meta = raw.get("meta") or {}
        paused = raw.get("spending_paused")
        return cls(
            str(raw.get("id") or ""), raw.get("email"), raw.get("owner"), (raw.get("plan") or {}).get("tier"), dict(raw.get("balance") or {}),
            dict(raw.get("month") or {}), raw.get("spend_cap"), dict(raw.get("counts") or {}),
            dict(raw.get("limits") or {}), dict(raw.get("features") or {}), raw.get("default_region"),
            PausedSpendingDefault(paused.get("message"), paused.get("action")) if isinstance(paused, dict) else None,
            raw.get("console_key_id"), list(meta.get("scopes") or []), list(meta.get("explicit_scopes") or []), raw,
        )

    @synced
    @classmethod
    async def get(cls, *, client: Optional[Client] = None) -> "Account":
        """Read the account: the signed-in owner, or one of the account's own secret keys acting for it (a key acting
        for one of its users gets ``noclick.PermissionDenied``).

        Returns:
            The account.

        Usage::

            account = noclick.Account.get()
            print(account.plan_tier, account.balance["remaining_usd"])
        """
        return cls._from(await resolve_client(client).request("GET", "/v1/account", user=None))

    @synced
    @classmethod
    async def update(
        cls, *, default_region: Any = UNSET, spending_paused: Any = UNSET, spend_cap_usd: Any = UNSET,
        client: Optional[Client] = None,
    ) -> "Account":
        """Change the account's defaults: only the fields given; ``None`` clears one. ``default_region`` is the region
        new resources take when a call names none; ``spending_paused`` what a paused user is told without a message
        (a ``PausedSpendingDefault``); ``spend_cap_usd`` the monthly spending cap in whole dollars. The signed-in
        owner's alone.

        Returns:
            The account as it is now.

        Usage::

            noclick.Account.update(default_region="eu", spend_cap_usd=200)
        """
        body: Dict[str, Any] = {}
        if default_region is not UNSET:
            body["default_region"] = default_region
        if spending_paused is not UNSET:
            body["spending_paused"] = None if spending_paused is None else compact(
                message=spending_paused.message, action=spending_paused.action)
        if spend_cap_usd is not UNSET:
            body["spend_cap_usd"] = spend_cap_usd
        return cls._from(await resolve_client(client).request("PATCH", "/v1/account", json=body, user=None))

    @synced
    @staticmethod
    async def status(*, client: Optional[Client] = None) -> AccountStatus:
        """The account at a glance, as the key calling sees it: which account (or which of its users the key acts
        for), its plan, balance, this month's spend against its caps, approvals waiting on a person, what failed in
        the last day and what ran last. A user's session is refused.

        Returns:
            The status.

        Usage::

            status = noclick.Account.status()
            print(status.account.get("name") or status.account["id"], status.balance.get("remaining_usd"))
        """
        raw = await resolve_client(client).request("GET", "/v1/status") or {}
        return AccountStatus(
            dict(raw.get("account") or {}), raw.get("user_id"), raw.get("plan"), dict(raw.get("balance") or {}),
            dict(raw.get("month") or {}), list(raw.get("caps") or []), list(raw.get("approvals_pending") or []),
            list(raw.get("failing") or []), dict(raw.get("operations") or {}), raw,
        )

    @synced
    @staticmethod
    async def public_endpoints(*, client: Optional[Client] = None) -> List[PublicEndpoint]:
        """What a publishable key may list: the account's public endpoints (a shared agent's page, a published
        workflow), each by ``kind`` and ``id``. The signed-in owner's alone.

        Returns:
            Each ``PublicEndpoint``.

        Usage::

            for endpoint in noclick.Account.public_endpoints():
                print(endpoint.kind, endpoint.name, endpoint.url)
        """
        page = await resolve_client(client).request("GET", "/v1/public_endpoints", user=None) or {}
        return [PublicEndpoint._from(row) for row in page.get("data") or []]

    @synced
    @staticmethod
    async def resolve(ref: str, *, client: Optional[Client] = None) -> ObjectRef:
        """What ``ref`` names in the account: an object's id, a key's prefix (``nk_live_ab12…``) or one of your users'
        ids. Nothing it names raises ``noclick.NotFound``. The signed-in owner's alone.

        Returns:
            Its ``type`` and ``id``, and the user it belongs to.

        Usage::

            found = noclick.Account.resolve("nk_live_ab12")
            print(found.type, found.id)
        """
        raw = await resolve_client(client).request("GET", f"/v1/objects/{quote(ref, safe='')}", user=None) or {}
        return ObjectRef(raw.get("type") or "", raw.get("id") or "", raw.get("user_id"), raw)

    @synced
    @staticmethod
    async def payment_link(
        *, kind: str = "funds", amount_usd: Optional[int] = None, plan: Optional[str] = None,
        billing_period: Optional[str] = None, credits_per_month: Optional[int] = None, client: Optional[Client] = None,
    ) -> PaymentLink:
        """A one-tap link that pays for the account, made for its owner to open: funds for its balance
        (``amount_usd``, whole dollars; the plan's fee is paid with them), or a ``plan`` to move to. Opening it needs
        no sign-in, so only the signed-in owner and the account's assistant make one. Its operation
        (``operation_id``) succeeds once they've paid; the same purchase asked for again while its link is open
        answers that link.

        Returns:
            The link.

        Usage::

            link = noclick.Account.payment_link(amount_usd=20)
            print(link.price_usd, link.url)
        """
        body = compact(kind=kind, amount_usd=amount_usd, plan=plan, billing_period=billing_period,
                       credits_per_month=credits_per_month)
        raw = await resolve_client(client).request("POST", "/v1/account/payment_links", json=body, user=None) or {}
        return PaymentLink(raw.get("kind") or "", raw.get("label") or "", float(raw.get("price_usd") or 0),
                           raw.get("url") or "", parse_time(raw.get("expires_at")), raw.get("operation_id"), raw)
