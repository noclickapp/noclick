"""App services: email, payments and sign-in for a project.

Reached through the project: ``app.email``, ``app.payments``, ``app.sign_in``.

    app = noclick.Project.from_name("booking")
    app.email.enable(domain="acmebooking.com")
    app.email.send(to="ana@example.com", subject="Your booking", text="See you Friday at 3pm.")
    app.email.broadcast(["ana@example.com"], "October at Acme", text="...", idempotency_key="october-news")
    print(app.payments.enable(country="US").claim_url)
    app.sign_in.enable(providers=["email", "google"]).wait()
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Union

from ._object import compact, paginate, parse_time, ref_id
from ._sync import synced
from .domain import DnsRecord, domain_name
from .operation import Operation, register_result

if TYPE_CHECKING:
    from .project import Project


class _Service:
    """One of a project's services, at ``/v1/projects/{id}/<name>``; it acts for the project's user."""

    _name = ""

    def __init__(self, project: "Project") -> None:
        self._project = project

    def __repr__(self) -> str:
        return f"{type(self).__name__}(project={self._project._known('id') or self._project._known('name')!r})"

    async def _path(self, *rest: str) -> str:
        return "/".join((f"/v1/projects/{await ref_id(self._project)}", self._name, *rest))

    async def _request(self, method: str, *rest: str, **kwargs: Any) -> Any:
        path = await self._path(*rest)
        return await self._project._request(method, path, **kwargs)


# --- email -------------------------------------------------------------------


@dataclass(frozen=True)
class EmailSetup:
    """How an app sends email: the sender, its domain's DNS records and whether it can send.
    ``status`` is ``off`` (never enabled), ``pending`` (NoClick is setting up the app's sending,
    usually within a minute; mail sent meanwhile goes out once it's set up, and ``pending_reason``
    says why when setting it up failed), ``pending_dns`` (the domain's records aren't seen yet: a
    domain bought through NoClick gets them written and turns ``active`` within minutes),
    ``active``, or ``paused`` (too many bounces or spam complaints; ``paused_reason`` says which:
    ``bounce_rate``, ``complaint_rate``, ``mailbox_provider_feedback`` or ``blocklisted``).
    Broadcasts go out apart, from the domain's ``news.`` subdomain, with a status of their own."""

    status: str
    #: The address mail goes out from, like ``bookings@acmebooking.com``.
    from_address: Optional[str]
    #: The display name recipients see, like ``Acme Booking``.
    from_name: Optional[str]
    #: The sending domain; ``None`` while the app uses its default sender.
    domain: Optional[str]
    #: What DNS must hold for mail to send and land: DKIM and a bounce subdomain (MX and SPF) for the
    #: domain and for its ``news.`` subdomain, and a recommended DMARC policy.
    records: List[DnsRecord]
    #: How many messages the app may send a day; it grows as its mail keeps landing.
    daily_limit: Optional[int]
    #: How many it has sent since midnight UTC.
    sent_today: Optional[int]
    paused_reason: Optional[str]
    #: Why the app's sending isn't set up yet, once setting it up failed (NoClick keeps trying); else ``None``.
    pending_reason: Optional[str]
    #: The postal address every broadcast's footer carries (``None`` until you give one).
    postal_address: Optional[str]
    #: How many recipients its broadcasts may reach a day, apart from ``daily_limit``.
    broadcast_daily_limit: Optional[int]
    #: ``needs_domain`` (the default sender doesn't send broadcasts), ``pending``, ``pending_dns``, ``active`` or
    #: ``paused``.
    broadcast_status: str
    #: The address broadcasts go out from, on the ``news.`` subdomain: ``bookings@news.acmebooking.com``.
    broadcast_from_address: Optional[str]
    #: How many broadcast recipients it has sent to since midnight UTC.
    broadcast_sent_today: Optional[int]
    broadcast_paused_reason: Optional[str]
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Any) -> "EmailSetup":
        raw = raw if isinstance(raw, dict) else {}
        return cls(
            raw.get("status") or "off", raw.get("from_address"), raw.get("from_name"), raw.get("domain"),
            [DnsRecord._from(row) for row in raw.get("records") or []], raw.get("daily_limit"),
            raw.get("sent_today"), raw.get("paused_reason"), raw.get("pending_reason"), raw.get("postal_address"),
            raw.get("broadcast_daily_limit"), raw.get("broadcast_status") or "off", raw.get("broadcast_from_address"),
            raw.get("broadcast_sent_today"), raw.get("broadcast_paused_reason"), raw,
        )

    @property
    def can_send(self) -> bool:
        """Whether ``send`` goes out now (``status`` is ``active``)."""
        return self.status == "active"


@dataclass(frozen=True)
class SentEmail:
    """One message an app sent. ``status`` is ``held`` (kept while the account can't pay: sent
    and charged once it can, or ``failed`` after 3 days, never charged), ``queued``, ``sent`` (on its
    way to the recipient's server), ``delivered``, ``bounced``, ``complained`` (marked as spam:
    best-effort, since some mailbox providers, Gmail among them, report no single complaint) or ``failed``;
    ``error`` says why a message bounced or failed. Sent to several recipients, it shows the
    worst any met (a bounce, a complaint), else how far the slowest got.

    A preview's code reaches only the account's own people (its owner and the members of the
    owner's workspaces): every other copy is kept, never sent or charged, and named in
    ``captured``; a message whose every copy was kept is ``captured``, with the ``text`` and
    ``html`` it would have sent. ``messages(environment="preview")`` is the preview's outbox."""

    id: str
    to: List[str]
    subject: Optional[str]
    status: str
    #: Whether the recipient opened it, as far as can be told: privacy proxies open some mail on the
    #: reader's behalf. ``None`` for a message with no HTML, or a sign-in code, which aren't tracked.
    opened: Optional[bool]
    bounced: bool
    error: Optional[str]
    #: When it was sent.
    at: Any
    #: ``message`` (``send``), ``code`` (``send_code``) or ``broadcast``.
    kind: str
    #: Where the code that sent it runs: ``production`` or ``preview``.
    environment: str
    #: The recipients a preview kept rather than sent to.
    captured: List[str]
    #: What a kept message would have said; ``None`` once a message went out.
    text: Optional[str]
    html: Optional[str]
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Any) -> "SentEmail":
        raw = raw if isinstance(raw, dict) else {}
        to = raw.get("to")
        return cls(
            raw.get("id"), [to] if isinstance(to, str) else list(to or []), raw.get("subject"),
            raw.get("status") or "queued", raw.get("opened"), bool(raw.get("bounced")), raw.get("error"),
            parse_time(raw.get("at")), raw.get("kind") or "message", raw.get("environment") or "production",
            list(raw.get("captured") or []), raw.get("text"), raw.get("html"), raw,
        )


@dataclass(frozen=True)
class Broadcast:
    """One broadcast an app sent: how many recipients it was ``sent`` to, and those it
    ``skipped``, each ``{to, reason}`` with ``reason`` ``unsubscribed``, ``bounced``,
    ``complained`` or ``invalid``. Each message's delivery shows in ``app.email.messages()``.
    From a preview, only the account's own people get it: ``captured`` counts the copies kept."""

    id: str
    subject: Optional[str]
    sent: int
    skipped: List[Dict[str, Any]]
    captured: int
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Any) -> "Broadcast":
        raw = raw if isinstance(raw, dict) else {}
        return cls(raw.get("id") or "", raw.get("subject"), int(raw.get("sent") or 0), list(raw.get("skipped") or []),
                   int(raw.get("captured") or 0), raw)


def _read_broadcast(result: Any, op: Operation) -> Broadcast:
    return Broadcast._from(result)


register_result("project.email.broadcast", _read_broadcast)


class ProjectEmail(_Service):
    """``app.email``: transactional email from the app's own address (receipts, booking
    confirmations), rate-capped and charged per recipient; a high bounce or complaint rate
    pauses sending. One-time sign-in codes go through ``send_code``, on a lane of their own.
    Newsletters and announcements go through ``broadcast``, on a stream of their own, so they
    never hold up a receipt.

    Usage::

        app = noclick.Project.from_name("booking")
        email = app.email   # this app's noclick.ProjectEmail
        email.enable(domain="acmebooking.com", from_address="bookings@acmebooking.com")
        email.send(to="ana@example.com", subject="Your booking", text="See you Friday at 3pm.")
    """

    _name = "email"

    @synced
    async def enable(
        self,
        *,
        domain: Any = None,
        from_address: Optional[str] = None,
        from_name: Optional[str] = None,
        postal_address: Optional[str] = None,
    ) -> EmailSetup:
        """Turn email on for the app, or change what you pass (the rest keeps its value).
        Without a ``domain`` the app sends from its default address
        (``noreply@booking.noclick.site``). With one (a ``Domain`` or its name), mail goes from
        ``from_address`` on it, ``noreply@<domain>`` unless you pass one, and broadcasts go from
        the same name on its ``news.`` subdomain, so their reputation stays apart from receipts'.
        The first call answers ``pending`` while NoClick sets up the app's sending (what it
        sends meanwhile goes out once that's done). A domain bought through NoClick gets its
        DNS records written for it and turns ``active`` within minutes; any other is connected
        for you, and ``records`` lists what to add at its DNS host (within seconds of this call).

        ``domain`` may also be a subdomain of a domain your account holds
        (``mail.ana.acmebooking.com`` under the account's ``acmebooking.com``), for any
        project, a user's included; only a key acting for the whole account may choose one.
        Its records are written for you under a bought domain, and listed in ``records`` under
        a connected one. ``postal_address`` is the address every broadcast's footer carries,
        as the law asks of bulk mail; ``broadcast`` needs one.

        Returns:
            The setup: ``active`` when the app can send now, ``pending`` while NoClick sets up
            its sending (what it sends meanwhile goes out once that's done), or ``pending_dns``
            while the domain's ``records`` aren't seen yet.

        Usage:
            Send from your own domain::

                app = noclick.Project.from_name("booking")
                setup = app.email.enable(domain="acmebooking.com", from_address="bookings@acmebooking.com", from_name="Acme Booking")
                print(setup.status, setup.from_address)

            A domain hosted elsewhere waits for its DNS records::

                app = noclick.Project.from_name("booking")
                setup = app.email.enable(domain="acme.test")
                for record in setup.records:
                    print(record.type, record.name, record.value)
        """
        body = compact(
            domain=await domain_name(domain), from_address=from_address, from_name=from_name,
            postal_address=postal_address,
        )
        return EmailSetup._from(await self._request("POST", json=body))

    @synced
    async def status(self) -> EmailSetup:
        """Read how the app sends email, checking the domain's DNS records again.

        Returns:
            The current setup; ``status`` is ``off`` if email was never enabled.

        Usage::

            app = noclick.Project.from_name("booking")
            setup = app.email.status()
            if setup.status == "pending_dns":
                print("Still waiting for", [record.name for record in setup.records])
        """
        return EmailSetup._from(await self._request("GET"))

    @synced
    async def send(
        self,
        to: Union[str, Sequence[str]],
        subject: str,
        *,
        text: Optional[str] = None,
        html: Optional[str] = None,
        reply_to: Optional[str] = None,
        time_sensitive: bool = False,
        idempotency_key: Optional[str] = None,
    ) -> SentEmail:
        """Send one message to ``to`` (an address, or a list of up to 10 that each
        receive it) with a ``text`` body, an ``html`` one, or both. Email must be
        ``active``, or ``pending`` (the message waits and goes once sending is set up):
        ``noclick.ActionRequired`` while the domain's records are pending,
        ``noclick.RateLimited`` past the daily limit.

        While the account can't pay (out of funds, or at a spend cap) the message is
        ``held``, sent and charged once it can, so a form never fails on it. A message
        only worth getting now (a magic link, a password reset) passes
        ``time_sensitive=True`` and is refused instead (``noclick.PaymentRequired``).

        Returns:
            The message as accepted, usually ``queued`` (``held`` while the account can't
            pay); ``messages()`` shows whether it was delivered.

        Usage:
            Pass an ``idempotency_key`` so a retried request can't send twice::

                app = noclick.Project.from_name("booking")
                sent = app.email.send(
                    to="ana@example.com",
                    subject="Your booking is confirmed",
                    text="See you Friday at 3pm.",
                    html="<p>See you <b>Friday at 3pm</b>.</p>",
                    idempotency_key="booking-1042-confirmation",
                )
                print(sent.id, sent.status)
        """
        if text is None and html is None:
            raise TypeError("Pass text=, html= or both.")
        recipients = [to] if isinstance(to, str) else list(to)
        response = await self._request(
            "POST", "send",
            json=compact(to=recipients, subject=subject, text=text, html=html, reply_to=reply_to,
                         time_sensitive=time_sensitive or None),
            idempotency_key=idempotency_key,
        )
        return SentEmail._from(response)

    @synced
    async def send_code(
        self,
        to: str,
        code: str,
        *,
        purpose: str = "sign_in",
        expires_in_s: Optional[int] = None,
        idempotency_key: Optional[str] = None,
    ) -> SentEmail:
        """Send a one-time ``code`` (4-12 letters and digits) to ``to``, in a short message NoClick
        writes in the app's name: ``purpose`` ``sign_in`` or ``verify_email``, and ``expires_in_s``
        said in it when you pass one. Codes have a daily limit of their own, apart from
        ``daily_limit``, so a new app's sign-ins never wait on its other mail; one address gets at
        most 5 codes in 15 minutes (``noclick.RateLimited``). Each is charged as one message.
        ``app.sign_in`` sends its codes this way.

        Returns:
            The message, ``kind`` ``code``; its subject names the purpose, never the code.

        Usage::

            app = noclick.Project.current()
            app.email.send_code("ana@example.com", "482913", expires_in_s=300)
        """
        response = await self._request(
            "POST", "codes", json=compact(to=to, code=code, purpose=purpose, expires_in_s=expires_in_s),
            idempotency_key=idempotency_key,
        )
        return SentEmail._from(response)

    @synced
    async def messages(self, *, to: Optional[str] = None, limit: Optional[int] = 50,
                       environment: Optional[str] = None) -> List[SentEmail]:
        """The messages the app sent, newest first; ``to`` keeps those sent to one address, and
        ``environment`` (``production`` or ``preview``) those its production or its previews sent.

        A preview's code reaches only the account's own people, so ``environment="preview"`` is
        its outbox: each message names the recipients it kept in ``captured``, with the ``text``
        and ``html`` it would have sent.

        Returns:
            Up to ``limit`` messages (50 unless you say; ``None`` reads them all), each with
            its delivery ``status``, whether it was ``opened`` and why it ``bounced``.

        Usage::

            app = noclick.Project.from_name("booking")
            for message in app.email.messages(to="ana@example.com", limit=10):
                print(message.at, message.subject, message.status, message.opened)
            for kept in app.email.messages(environment="preview"):
                print(kept.captured, kept.subject, kept.text)
        """
        path = await self._path("messages")
        rows = await paginate(
            self._project._api, path, params=compact(to=to, environment=environment),
            user=self._project._call_scope(), limit=limit,
        )
        return [SentEmail._from(row) for row in rows]

    @synced
    async def broadcast(
        self,
        to: Sequence[str],
        subject: str,
        *,
        idempotency_key: str,
        text: Optional[str] = None,
        html: Optional[str] = None,
        reply_to: Optional[str] = None,
    ) -> Operation:
        """Send one message to many people who asked for it: a newsletter, an announcement.
        ``to`` holds up to 50,000 addresses, and listing them says each one opted in to mail
        from the app. Anyone who unsubscribed from its broadcasts (until they opt in again and you
        ``resubscribe`` them), bounced or marked one as spam is skipped. It goes out on a bulk
        stream of its own, under ``broadcast_daily_limit``, from ``broadcast_from_address`` on the
        domain's ``news.`` subdomain, so a campaign's complaints never pause the app's transactional
        mail. It needs a domain of the app's own (``noclick.ActionRequired`` on the default sender).
        Every message carries its recipient's own ``List-Unsubscribe`` header, with one-click
        unsubscribe, and a footer with an unsubscribe link and the ``postal_address`` from
        ``enable()`` (``noclick.ActionRequired`` until there is one). Unsubscribing stops
        broadcasts, never receipts. It goes out at the pace mail can be sent, so a large one takes
        minutes.

        ``idempotency_key`` names the broadcast: sending again with the same key sends nothing
        new, so a job that crashes halfway can simply run again.

        Returns:
            An operation whose ``.wait()`` gives the ``Broadcast``: how many it was sent to and who
            was skipped, and why.

        Usage::

            app = noclick.Project.from_name("booking")
            subscribers = [row["email"] for row in app.database("DB").query("select email from subscribers")]
            result = app.email.broadcast(
                subscribers, "What's new at Acme Booking",
                html="<h1>Group bookings are here</h1><p>Book for up to 12 people at once.</p>",
                idempotency_key="newsletter-2026-10",
            ).wait()
            print(result.sent, len(result.skipped))
        """
        if text is None and html is None:
            raise TypeError("Pass text=, html= or both.")
        if isinstance(to, str):
            raise TypeError("broadcast() takes a list of addresses; send() is for one message.")
        payload = await self._request(
            "POST", "broadcasts",
            json=compact(to=list(to), subject=subject, text=text, html=html, reply_to=reply_to),
            idempotency_key=idempotency_key,
        )
        return Operation._from_payload(
            payload, client=self._project._client, user=self._project._call_scope(),
            kind="project.email.broadcast", reader=_read_broadcast,
        )

    @synced
    async def resubscribe(self, address: str) -> bool:
        """Lift ``address``'s unsubscribe from the app's broadcasts, once they've asked for them
        again and confirmed it: a click on a link you emailed that address, as when they first
        subscribed. Mail after an unsubscribe is spam unless the person opted in again, so call it
        only on a confirmed opt-in. A bounce or a spam complaint isn't lifted.

        Returns:
            ``True`` if the address was unsubscribed and now gets broadcasts again, ``False`` if it
            wasn't unsubscribed.

        Usage::

            app = noclick.Project.from_name("newsletter")
            # Ana clicked the confirmation link you emailed her after she signed up again.
            if app.email.resubscribe("ana@example.com"):
                print("Ana gets the newsletter again")
        """
        response = await self._request("POST", "resubscribe", json={"address": address}) or {}
        return bool(response.get("resubscribed"))


# --- payments ----------------------------------------------------------------


@dataclass(frozen=True)
class PaymentsSetup:
    """Where an app's payments go. ``mode`` is ``off`` (never enabled), ``test`` (a test
    account that takes test cards, waiting to be claimed), ``claimed`` (the owner claimed it and
    is finishing the steps ``claim_step`` names), ``live`` (live keys are in the app's production
    secrets and the account can take payments) or ``disconnected`` (the owner removed NoClick's
    payments app or its keys). Money goes straight to the owner's account; NoClick takes no cut."""

    mode: str
    #: While claiming: ``claim`` (send the owner ``claim_url``), ``application`` (the owner gives the
    #: payment processor their business details), ``install`` (the owner installs NoClick's payments
    #: app on their live account) or ``verification`` (the processor is verifying the business).
    claim_step: Optional[str]
    #: What to do now, in a sentence.
    next_step: Optional[str]
    #: Where the owner claims the account: a NoClick link that always sends them to their next step,
    #: working until ``test_expires_at`` (``None`` once live).
    claim_url: Optional[str]
    #: When the test account and its test data are deleted unless it's claimed (60 days after
    #: ``enable()``); after that ``enable()`` opens a fresh one, with new keys.
    test_expires_at: Any
    #: The owner's own dashboard at the payment processor, once claimed.
    dashboard_url: Optional[str]
    #: The project secrets that hold the account's keys. Production gets the live keys once ``live``;
    #: preview deployments keep the test keys, so a preview never takes a real payment.
    secrets: List[str]
    #: Which payment processor apps are paid through, by the name its own client library goes by, so the
    #: app's code can pick the library that reads ``secrets``. It's the same for every app, so ``status()``
    #: reports it even while ``off``, and code can be written before ``enable()``.
    processor: Optional[str]
    #: Where the business is (ISO 3166-1 alpha-2), fixed when the account was opened.
    country: Optional[str]
    #: Where the processor delivers the account's events, signed with ``PAYMENTS_WEBHOOK_SECRET``: the
    #: app's ``/api/payments/webhook`` on its production URL.
    webhook_url: Optional[str]
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Any) -> "PaymentsSetup":
        raw = raw if isinstance(raw, dict) else {}
        return cls(
            raw.get("mode") or "off", raw.get("claim_step"), raw.get("next_step"), raw.get("claim_url"),
            parse_time(raw.get("test_expires_at")), raw.get("dashboard_url"), list(raw.get("secrets") or []),
            raw.get("processor"), raw.get("country"), raw.get("webhook_url"), raw,
        )


class ProjectPayments(_Service):
    """``app.payments``: take payments in the app without a payments account of your own.
    NoClick opens a test account for the app and puts its keys in the app's secrets; the
    owner claims it to take real money.

    Usage::

        app = noclick.Project.from_name("booking")
        payments = app.payments   # this app's noclick.ProjectPayments
        setup = payments.enable(country="US")
        print(setup.mode, setup.claim_url)
    """

    _name = "payments"

    @synced
    async def enable(
        self, *, country: Optional[str] = None, owner_email: Optional[str] = None, business_name: Optional[str] = None,
    ) -> PaymentsSetup:
        """Open a test payments account for the app and put its keys in the app's secrets
        (for production and previews). ``country`` is where the owner's business is: required
        the first time, since the account can only ever be in that country (``noclick.NotAvailable``,
        listing the countries, for one the processor doesn't serve). ``owner_email`` is who the
        processor reminds before an unclaimed test account expires (your NoClick account's email
        unless you pass one); ``business_name`` prefills the claim (the app's name unless you pass one).

        Calling it again returns the same account, with its webhook endpoint following the app's
        URL. After ``test_expires_at`` passes unclaimed, it opens a fresh test account with new
        keys and no data, and the app must deploy again; once the owner has reinstalled NoClick's
        payments app on a ``disconnected`` account, it reconnects it.

        Returns:
            The setup in ``test`` mode, with the ``claim_url`` to send the owner.

        Usage::

            app = noclick.Project.from_name("booking")
            setup = app.payments.enable(country="US")
            print(setup.secrets)   # read these in the app's code
            print("Claim it before", setup.test_expires_at, setup.claim_url)
        """
        body = compact(country=country, owner_email=owner_email, business_name=business_name)
        return PaymentsSetup._from(await self._request("POST", json=body))

    @synced
    async def status(self) -> PaymentsSetup:
        """Read where the app's payments stand.

        Returns:
            The current setup; ``mode`` moves from ``test`` to ``claimed`` to ``live``. ``processor``
            is there even while ``off``, so an app's payment code can be written before ``enable()``.

        Usage::

            app = noclick.Project.from_name("booking")
            if app.payments.status().mode == "live":
                app.deploy()   # production picks up the live keys

            processor = noclick.Project.from_name("booking").payments.status().processor   # before enable()
        """
        return PaymentsSetup._from(await self._request("GET"))


# --- sign-in -----------------------------------------------------------------


@dataclass(frozen=True)
class SignInSetup:
    """An app's sign-in. ``status`` is ``off``, ``installing`` (a change is being committed and
    deployed), ``active`` or ``failed`` (the first change failed; ``error`` says why: a later
    change that fails leaves sign-in ``active`` as it was, with ``error``). The code lives in the
    app's repo and the users in ``users_table`` of the app's own database."""

    status: str
    #: ``email`` (a one-time code by email), ``google``, ``apple``, ``microsoft``, ``github``.
    providers: List[str]
    #: The providers that sign in through NoClick, with nothing to set up at the provider (its screen
    #: names NoClick). The rest of ``providers`` but ``email`` use your own client there.
    managed_providers: List[str]
    users_table: Optional[str]
    #: Every table sign-in keeps in the database: ``users_table`` first, then its sessions, the
    #: accounts people sign in with, the pending codes and its rate limits.
    tables: List[str]
    #: The binding of the database the users are kept in.
    database: Optional[str]
    #: The open-source library the code is written with, and its version, so code written against
    #: the app's sign-in uses the right calls.
    library: str
    version: Optional[str]
    #: A newer version NoClick ships (``upgrade()`` moves to it), else ``None``.
    update_available: Optional[str]
    #: The commit that added or last changed sign-in.
    commit: Optional[str]
    #: Where that commit went when it wasn't the production branch: the one you passed, or the one
    #: NoClick made because files it would change hold edits of yours (``edited_files``).
    branch: Optional[str]
    edited_files: List[str]
    #: Where each provider on your own client sends people back to; register it with that provider.
    #: They're on the app's own NoClick address, so adding a domain doesn't change them.
    callback_urls: Dict[str, str]
    #: Project secrets a provider on your own client still needs (``GOOGLE_CLIENT_ID``, ...); it works
    #: once they're set.
    missing_secrets: List[str]
    #: The secrets NoClick writes itself and never shows: ``AUTH_SECRET``, ``AUTH_URL``,
    #: ``AUTH_PROXY_SECRET``, and the app's client of NoClick's sign-in (``NOCLICK_SIGN_IN_CLIENT_ID``,
    #: ``NOCLICK_SIGN_IN_CLIENT_SECRET``) while any provider signs in through NoClick.
    secrets: List[str]
    error: Optional[Dict[str, Any]]
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Any) -> "SignInSetup":
        raw = raw if isinstance(raw, dict) else {}
        return cls(
            raw.get("status") or "off", list(raw.get("providers") or []), list(raw.get("managed_providers") or []),
            raw.get("users_table"),
            list(raw.get("tables") or []), raw.get("database"), raw.get("library") or "", raw.get("version"),
            raw.get("update_available"), raw.get("commit"), raw.get("branch"), list(raw.get("edited_files") or []),
            dict(raw.get("callback_urls") or {}), list(raw.get("missing_secrets") or []),
            list(raw.get("secrets") or []), raw.get("error"), raw,
        )


def _read_sign_in(result: Any, op: Operation) -> SignInSetup:
    return SignInSetup._from(result)


register_result("project.sign_in.enable", _read_sign_in)
register_result("project.sign_in.upgrade", _read_sign_in)


class ProjectSignIn(_Service):
    """``app.sign_in``: accounts for the app's own users. Enabling it commits sign-in code
    into the app's repo, where you can read and change it, and keeps the users in the app's
    bound database.

    Usage::

        app = noclick.Project.from_name("booking")
        sign_in = app.sign_in   # this app's noclick.ProjectSignIn
        setup = sign_in.enable(providers=["email", "google"]).wait()
        print(setup.commit, setup.managed_providers)
    """

    _name = "sign_in"

    @synced
    async def enable(
        self, providers: Sequence[str], *, own_credentials: Optional[Sequence[str]] = None,
        users_table: str = "users", database: Optional[str] = None, branch: Optional[str] = None,
        deploy: bool = True,
    ) -> Operation:
        """Add sign-in with ``providers`` (``email``, ``google``, ``apple``, ``microsoft``,
        ``github``) to the app: commit the code for its framework to ``branch`` (the repo's default
        branch unless you pass one), create ``users_table`` and the tables it needs in its bound
        database and deploy. Calling it again with another list changes the providers.

        ``google``, ``apple`` and ``microsoft`` sign in through NoClick, with nothing to set up at
        the provider: its screen names NoClick. To show your own name there instead, list ``google``
        or ``microsoft`` in ``own_credentials`` and set its client's id and secret as the app's
        secrets (``SignInSetup.missing_secrets`` names them, ``callback_urls`` where to register it);
        ``apple`` signs in only through NoClick, and ``github`` only with your own client. Omitted,
        each provider keeps how it signs in now: one on your own client stays there.

        The app needs a bound database (``noclick.ActionRequired`` otherwise; ``database`` names
        the binding when it has several). It works on ``nextjs``, ``remix`` and ``astro`` apps, and
        on a ``static`` site as it is: a worker in front of its files answers sign-in, and its pages
        include ``/auth.js`` (``noclick.NotAvailable`` for a client-only ``vite`` app, or a site that
        already runs its own worker). ``email`` sends its codes through ``app.email.send_code``, which
        is enabled with the default sender if it isn't yet.

        A file the change would replace that holds edits of yours is never overwritten: the change
        goes on a branch of its own (``SignInSetup.branch``, with a preview to review), and naming
        a ``branch`` whose files hold edits raises ``noclick.Conflict`` naming them.

        ``deploy=False`` sets it up (its secrets and tables) and commits its code without
        deploying: it goes live with the branch's next deploy, so you can commit changes of your
        own beside it first.

        Returns:
            An operation whose ``wait()`` gives the ``SignInSetup`` once the code is
            committed and deployed (committed alone with ``deploy=False``).

        Usage:
            Add it straight to production::

                app = noclick.Project.from_name("booking")
                setup = app.sign_in.enable(providers=["email", "google"]).wait()
                print(setup.managed_providers)   # ['google']: nothing to set up

            With your own Google client, to show your name on Google's screen::

                app = noclick.Project.from_name("booking")
                setup = app.sign_in.enable(providers=["email", "google"], own_credentials=["google"]).wait()
                print(setup.callback_urls, setup.missing_secrets)

            Or on a branch, to review the commit on its preview deployment first::

                app = noclick.Project.from_name("booking")
                op = app.sign_in.enable(providers=["email"], branch="add-sign-in")
                print(op.wait().commit)

            Commit it without deploying, to ship it with your own changes in one deploy::

                app = noclick.Project.from_name("booking")
                app.sign_in.enable(providers=["email"], deploy=False).wait()
                app.repo.commit({"app/routes/_index.tsx": page}, message="Show who's signed in")
                app.deploy().wait()
        """
        payload = await self._request(
            "POST", json=compact(providers=list(providers), users_table=users_table, database=database,
                                 branch=branch,
                                 own_credentials=None if own_credentials is None else list(own_credentials),
                                 deploy=None if deploy else False),
        )
        return Operation._from_payload(
            payload, client=self._project._client, user=self._project._call_scope(),
            kind="project.sign_in.enable", reader=_read_sign_in,
        )

    @synced
    async def upgrade(self, *, branch: Optional[str] = None, deploy: bool = True) -> Operation:
        """Move the app's sign-in code to the library version NoClick ships now (``update_available``),
        with the same providers: the same commit, migrate and deploy as ``enable``, and the same care
        for files you edited (``deploy=False`` commits it without deploying, as ``enable`` takes it).
        Security fixes come this way; NoClick tells you of one with the
        ``project.sign_in.update_available`` event and never pushes it to production by itself.

        Returns:
            An operation whose ``wait()`` gives the ``SignInSetup``.

        Usage::

            app = noclick.Project.from_name("booking")
            if app.sign_in.status().update_available:
                print(app.sign_in.upgrade(branch="sign-in-update").wait().commit)
        """
        payload = await self._request("POST", "upgrade", json=compact(branch=branch, deploy=None if deploy else False))
        return Operation._from_payload(
            payload, client=self._project._client, user=self._project._call_scope(),
            kind="project.sign_in.upgrade", reader=_read_sign_in,
        )

    @synced
    async def status(self) -> SignInSetup:
        """Read the app's sign-in: its providers, where its users are kept, and what it still needs.

        Returns:
            The current setup; ``status`` is ``off`` if sign-in was never enabled.

        Usage::

            app = noclick.Project.from_name("booking")
            setup = app.sign_in.status()
            print(setup.status, setup.providers, setup.tables, setup.library, setup.version)
        """
        return SignInSetup._from(await self._request("GET"))
