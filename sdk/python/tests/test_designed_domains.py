from datetime import datetime, timezone

import pytest

import noclick as nc
from platform_helpers import USER_ID, body, listing, operation

DOMAIN_ID = "5c8e2a1f-7b3d-4e96-a0c4-9d1f6b2e8a57"
BOOKING = {
    "object": "domain", "id": DOMAIN_ID, "name": "acmebooking.com", "source": "bought", "status": "active",
    "expires_at": "2027-09-01T00:00:00Z", "renewable_until": "2027-09-26T00:00:00Z", "auto_renew": True,
    "renewal_usd": 12.5, "renewal_years": 1, "setup_url": None,
    "records": [{"type": "ALIAS", "name": "@", "value": "cname.noclick.site", "status": "verified",
                 "purpose": "Serves booking", "managed": True}],
    "serves": [{"kind": "project", "id": "prj_1", "name": "booking"}],
    "registrant_email": "dana@acmebooking.test", "registrant_verify_by": None,
    "registrant": {"name": "Dana Reyes", "email": "dana@acmebooking.test", "phone": "+14155550188",
                   "address": "1 Ferry Building", "city": "San Francisco", "region": "CA", "postal_code": "94111",
                   "country": "US",
                   "organization": "Acme Booking", "agreement_accepted_at": "2026-09-01T08:00:00Z"},
    "transfer_locked_until": "2026-10-31T00:00:00Z", "user_id": None, "created_at": "2026-09-01T00:00:00Z",
}
ACME = {
    "object": "domain", "id": "dom_2", "name": "acme.test", "source": "connected", "status": "pending_dns",
    "expires_at": None, "auto_renew": None, "setup_url": "https://dns.example/connect?template=noclick",
    "records": [
        {"type": "CNAME", "name": "www", "value": "cname.noclick.site", "status": "verified", "purpose": "Primary address"},
        {"type": "ALIAS", "name": "@", "value": "cname.noclick.site", "status": "pending", "required": False},
    ],
    "serves": [], "user_id": USER_ID, "created_at": "2026-09-25T10:00:00Z",
}
ANA = nc.DomainContact(
    name="Ana Silva", email="ana@example.com", phone="+14155550123", address="500 Market St",
    city="San Francisco", postal_code="94105", country="US", region="CA",
    agreement_accepted_at=datetime(2026, 10, 2, 9, 30, tzinfo=timezone.utc),
)
ANA_WIRE = {"name": "Ana Silva", "email": "ana@example.com", "phone": "+14155550123", "address": "500 Market St",
            "city": "San Francisco", "postal_code": "94105", "country": "US", "region": "CA",
            "agreement_accepted_at": "2026-10-02T09:30:00+00:00"}


def test_search_reads_offers(api, client):
    route = api.get("/v1/domains/search").respond(json=listing(
        {"name": "acmebooking.com", "available": True, "price_usd": 11.25, "renewal_usd": 12.5, "premium": False,
         "min_years": 1, "max_years": 10, "claims_notice": None},
        {"name": "acmebooking.app", "available": False, "price_usd": None, "renewal_usd": None, "premium": False},
        {"name": "book.app", "available": True, "price_usd": 2400, "renewal_usd": 30, "premium": True},
        {"name": "acmebooking.ai", "available": True, "price_usd": 160, "renewal_usd": 160, "premium": False,
         "min_years": 2, "max_years": 10, "claims_notice": "**Trademark notice**: acmebooking matches a mark."},
    ))
    offers = nc.Domain.search("acmebooking", tlds=["com", "app", "ai"], limit=4)
    params = route.calls.last.request.url.params
    assert (params["q"], params["tlds"], params["limit"]) == ("acmebooking", "com,app,ai", "4")
    assert [(o.name, o.available, o.premium) for o in offers] == [
        ("acmebooking.com", True, False), ("acmebooking.app", False, False), ("book.app", True, True),
        ("acmebooking.ai", True, False)]
    assert (offers[0].price_usd, offers[0].renewal_usd, str(offers[0])) == (11.25, 12.5, "acmebooking.com")
    assert (offers[0].min_years, offers[0].max_years, offers[0].claims_notice) == (1, 10, None)
    assert (offers[1].min_years, offers[1].max_years) == (None, None)  # not available: no terms
    ai = offers[3]
    assert (ai.price_usd, ai.min_years, ai.max_years) == (160, 2, 10)  # what buying charges now, for two years
    assert ai.claims_notice.startswith("**Trademark notice**")


def test_buy_charges_and_waits_for_the_domain(api, client):
    start = api.post("/v1/domains").respond(json=operation(
        op_id="op_b", kind="domain.buy", status="running", domain_id=DOMAIN_ID, price_usd=11.25))
    api.get("/v1/operations/op_b/wait").respond(json=operation(
        op_id="op_b", kind="domain.buy", status="succeeded", result={"domain": BOOKING}))
    offer = nc.DomainOffer._from({"name": "acmebooking.com", "available": True, "price_usd": 11.25})
    purchase = nc.Domain.buy(offer, max_price_usd=15, registrant=ANA, years=2)
    assert body(start.calls.last.request) == {
        "name": "acmebooking.com", "max_price_usd": 15, "years": 2, "auto_renew": True, "registrant": ANA_WIRE,
    }
    assert "NoClick-User" not in start.calls.last.request.headers
    assert isinstance(purchase, nc.DomainPurchase) and isinstance(purchase, nc.Operation)
    assert (purchase.price_usd, purchase.domain_id, purchase.status) == (11.25, DOMAIN_ID, "running")
    domain = purchase.wait()
    assert isinstance(domain, nc.Domain)
    assert (domain.name, domain.source, domain.renewal_usd, domain.expires_at.year) == ("acmebooking.com", "bought", 12.5, 2027)
    assert domain.serves == [{"kind": "project", "id": "prj_1", "name": "booking"}]
    assert (domain.renewal_years, domain.renewable_until.day) == (1, 26)
    owner = domain.registrant
    assert isinstance(owner, nc.DomainContact)
    assert (owner.name, owner.region, owner.organization) == ("Dana Reyes", "CA", "Acme Booking")
    assert owner.agreement_accepted_at == datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc)


def test_years_are_sent_only_when_given_and_claims_only_when_accepted(api, client):
    start = api.post("/v1/domains").respond(json=operation(
        op_id="op_b", kind="domain.buy", status="running", domain_id=DOMAIN_ID, price_usd=160))
    nc.Domain.buy("acmebooking.ai", max_price_usd=200, registrant=ANA)  # the TLD's minimum term
    assert body(start.calls.last.request) == {
        "name": "acmebooking.ai", "max_price_usd": 200, "auto_renew": True, "registrant": ANA_WIRE}
    nc.Domain.buy("acmebooking.ai", max_price_usd=400, years=4, registrant=ANA, accept_claims=True)
    sent = body(start.calls.last.request)
    assert (sent["years"], sent["accept_claims"]) == (4, True)

    api.get("/v1/domains").respond(json=listing())
    api.get(f"/v1/domains/{DOMAIN_ID}").respond(json={**BOOKING, "name": "acmebooking.ai", "status": "registering"})
    nc.Domain.from_name("acmebooking.ai", create_if_missing=True, max_price_usd=200).hydrate()
    assert "years" not in body(start.calls.last.request)
    nc.Domain.from_name("acmebooking.co", create_if_missing=True, max_price_usd=200, years=5).hydrate()
    assert body(start.calls.last.request)["years"] == 5


def test_buy_refusals_for_a_claim_a_term_and_a_missing_agreement(api, client):
    api.post("/v1/domains").respond(status_code=409, json={"error": {
        "type": "action_required", "message": "acmebooking.ai matches a registered trademark.",
        "next_step": "Show the registrant claims_notice, then buy with accept_claims=True.",
        "claims_notice": "**Trademark notice**: acmebooking matches a mark."}})
    with pytest.raises(nc.ActionRequired) as claim:
        nc.Domain.buy("acmebooking.ai", max_price_usd=200, registrant=ANA)
    assert claim.value.claims_notice.startswith("**Trademark notice**")

    api.post("/v1/domains").respond(status_code=400, json={"error": {
        "type": "invalid_request", "message": ".co registers for 1 to 5 years.", "field": "years"}})
    with pytest.raises(nc.InvalidRequest) as term:
        nc.Domain.buy("acmebooking.co", max_price_usd=200, years=10, registrant=ANA)
    assert term.value.field == "years"

    api.post("/v1/domains").respond(status_code=400, json={"error": {
        "type": "invalid_request", "message": "The registrant hasn't accepted the registration agreement.",
        "field": "registrant.agreement_accepted_at"}})
    unaccepted = nc.DomainContact(**{**ANA_WIRE, "agreement_accepted_at": None})
    with pytest.raises(nc.InvalidRequest) as err:
        nc.Domain.buy("anasilva.dev", max_price_usd=20, registrant=unaccepted)
    assert err.value.field == "registrant.agreement_accepted_at"


def test_agreement_is_the_accounts(api, client):
    route = api.get("/v1/domains/agreement").respond(json={
        "object": "domain_agreement", "url": "https://agreements.example/domains", "version": "2026-10-02"})
    with nc.as_user("user_42"):
        agreement = nc.Domain.agreement()
    assert "NoClick-User" not in route.calls.last.request.headers  # account level, whoever asks
    assert isinstance(agreement, nc.DomainAgreement)
    assert (agreement.url, agreement.version) == ("https://agreements.example/domains", "2026-10-02")
    assert agreement.raw["object"] == "domain_agreement"


def test_a_contact_sends_and_reads_when_the_agreement_was_accepted():
    assert ANA._wire()["agreement_accepted_at"] == "2026-10-02T09:30:00+00:00"
    passed = nc.DomainContact(**{**ANA_WIRE, "agreement_accepted_at": "2026-10-02T09:30:00Z"})
    assert passed._wire()["agreement_accepted_at"] == "2026-10-02T09:30:00Z"  # a string passes through
    assert "agreement_accepted_at" not in nc.DomainContact(**{**ANA_WIRE, "agreement_accepted_at": None})._wire()
    read = nc.DomainContact._from({**ANA_WIRE, "agreement_accepted_at": "2026-10-02T09:30:00Z"})
    assert read == ANA
    assert nc.DomainContact._from({**ANA_WIRE, "agreement_accepted_at": None}).agreement_accepted_at is None


def test_a_users_domain_is_registered_to_them_and_charged_to_the_account(api, client):
    start = api.post("/v1/domains").respond(json=operation(
        op_id="op_u", kind="domain.buy", status="running", domain_id=DOMAIN_ID, price_usd=14))
    with nc.as_user("user_42"):
        # Naming none, the user's registrant profile on file is what it's registered to: NoClick reads it (and
        # refuses, naming registrant, where there's none).
        nc.Domain.buy("anasilva.dev", max_price_usd=20)
        assert "registrant" not in body(start.calls.last.request)
        assert start.calls.last.request.headers["NoClick-User"] == "user_42"

        purchase = nc.Domain.buy("anasilva.dev", max_price_usd=20, registrant=ANA)
    request = start.calls.last.request
    assert body(request)["registrant"]["email"] == "ana@example.com"
    assert request.headers["NoClick-User"] == "user_42"
    assert (purchase.status, purchase.price_usd) == ("running", 14)


def test_a_purchase_your_policy_holds_waits_for_approval(api, client):
    api.post("/v1/domains").respond(json=operation(
        op_id="op_p", kind="domain.buy", status="awaiting_human", domain_id=DOMAIN_ID, price_usd=19))
    api.get(f"/v1/domains/{DOMAIN_ID}").respond(json={**BOOKING, "name": "anasilva.dev", "status": "awaiting_human",
                                                     "user_id": USER_ID})
    purchase = nc.Domain.buy("anasilva.dev", max_price_usd=20, registrant=ANA)
    assert purchase.status == "awaiting_human"
    assert purchase.domain.status == "awaiting_human"

    # Resumed elsewhere, it still knows its outcome's type.
    api.get("/v1/operations/op_p").respond(json=operation(op_id="op_p", kind="domain.buy", status="awaiting_human"))
    assert nc.DomainPurchase.from_id("op_p").status == "awaiting_human"
    api.get("/v1/operations/op_p/wait").respond(json=operation(
        op_id="op_p", kind="domain.buy", status="succeeded", result={"domain": {**BOOKING, "name": "anasilva.dev"}}))
    assert nc.Operation.from_id("op_p").wait().name == "anasilva.dev"


def test_buy_above_the_ceiling_is_refused(api, client):
    api.post("/v1/domains").respond(status_code=402, json={"error": {
        "type": "price_exceeded", "message": "book.app costs $2,400.00, more than max_price_usd.", "price_usd": 2400}})
    with pytest.raises(nc.PriceExceeded) as err:
        nc.Domain.buy("book.app", max_price_usd=15)
    assert err.value.price_usd == 2400


def test_connect_lists_the_records_to_add(api, client):
    route = api.post("/v1/domains/connect").respond(json=ACME)
    domain = nc.Domain.connect("acme.test", user="acme")
    assert body(route.calls.last.request) == {"name": "acme.test"}
    assert route.calls.last.request.headers["NoClick-User"] == "acme"
    assert (domain.status, domain.source, domain.setup_url) == ("pending_dns", "connected", "https://dns.example/connect?template=noclick")
    www, apex = domain.records
    assert isinstance(www, nc.DnsRecord)
    assert (www.type, www.name, www.value, www.status, www.purpose, www.required, www.managed) == (
        "CNAME", "www", "cname.noclick.site", "verified", "Primary address", True, False)
    assert (apex.required, apex.status, str(apex)) == (False, "pending", "@ ALIAS cname.noclick.site")
    assert repr(domain).startswith("Domain(id='dom_2', name='acme.test', status='pending_dns'")


def test_from_name_looks_the_domain_up_once_and_acts_by_id(api, client):
    lookup = api.get("/v1/domains").respond(json=listing({**ACME, "name": "acme.test.example"}, ACME))
    verify = api.post("/v1/domains/dom_2/verify").respond(json={**ACME, "status": "active"})
    domain = nc.Domain.from_name("acme.test")
    assert lookup.call_count == 0 and str(domain) == "acme.test"
    domain.verify()
    assert lookup.calls.last.request.url.params["name"] == "acme.test"
    assert (lookup.call_count, domain.status, domain.id) == (1, "active", "dom_2")
    assert verify.calls.last.request.headers["NoClick-User"] == USER_ID  # the domain's own user

    api.get("/v1/domains").respond(json=listing())
    with pytest.raises(nc.NotFound) as err:
        nc.Domain.from_name("nope.test").hydrate()
    assert err.value.name == "nope.test"


def test_get_list_and_pages(api, client):
    listed = api.get("/v1/domains").respond(json=listing(BOOKING, ACME, next_cursor="c2"))
    api.get(f"/v1/domains/{DOMAIN_ID}").respond(json=BOOKING)
    page = nc.Domain.list_page(limit=2, user_filter=nc.ALL_USERS)
    params = listed.calls.last.request.url.params
    assert (params["user_id"], params["limit"]) == ("all", "2")
    assert [d.name for d in page.data] == ["acmebooking.com", "acme.test"] and page.next_cursor == "c2"
    assert nc.Domain.get(DOMAIN_ID) == page.data[0]
    assert nc.Domain.from_id(DOMAIN_ID).transfer_locked_until.month == 10


def test_dns_records_set_and_delete(api, client):
    base = f"/v1/domains/{DOMAIN_ID}/dns"
    records = api.get(base).respond(json=listing(
        {"type": "ALIAS", "name": "@", "value": "cname.noclick.site", "status": "verified", "managed": True},
        {"type": "TXT", "name": "@", "value": "google-site-verification=abc", "status": "verified"},
    ))
    create = api.post(base).respond(json={"type": "TXT", "name": "@", "value": "v=spf1 -all", "status": "pending"})
    remove = api.delete(base).respond(204)
    domain = nc.Domain.from_id(DOMAIN_ID)
    managed, mine = domain.dns.records()
    assert records.call_count == 1 and managed.managed and not mine.managed
    saved = domain.dns.set("TXT", "@", "v=spf1 -all")
    assert body(create.calls.last.request) == {"type": "TXT", "name": "@", "value": "v=spf1 -all"}
    assert (saved.value, saved.status) == ("v=spf1 -all", "pending")
    domain.dns.delete(mine)
    params = remove.calls.last.request.url.params
    assert (params["type"], params["name"], params["value"]) == ("TXT", "@", "google-site-verification=abc")
    assert repr(domain.dns) == f"DomainDns(domain={DOMAIN_ID!r})"


def test_dns_on_a_connected_domain_is_not_available(api, client):
    api.get("/v1/domains/dom_2/dns").respond(status_code=409, json={"error": {
        "type": "not_available", "message": "acme.test's DNS is hosted elsewhere."}})
    with pytest.raises(nc.NotAvailable):
        nc.Domain.from_id("dom_2").dns.records()


def test_update_renew_transfer_out_and_delete(api, client):
    path = f"/v1/domains/{DOMAIN_ID}"
    patch = api.patch(path).respond(json={**BOOKING, "auto_renew": False})
    renew = api.post(f"{path}/renew").respond(json=operation(op_id="op_r", kind="domain.renew", status="running"))
    api.get("/v1/operations/op_r/wait").respond(json=operation(
        op_id="op_r", kind="domain.renew", status="succeeded", result={"domain": {**BOOKING, "expires_at": "2029-09-01T00:00:00Z"}}))
    api.post(f"{path}/transfer_out").respond(json={
        "object": "transfer_code", "auth_code": "Xy7#pQ2!", "unlocked_at": "2026-11-02T09:00:00Z",
        "expires_at": "2026-11-07T09:00:00Z"})
    delete = api.delete(path).respond(204)

    domain = nc.Domain.from_id(DOMAIN_ID)
    assert domain.update(auto_renew=False) is domain and domain.auto_renew is False
    assert body(patch.calls.last.request) == {"auto_renew": False}
    domain.update(registrant=ANA)
    assert body(patch.calls.last.request) == {"registrant": ANA_WIRE}
    renewal = domain.renew(years=2, max_price_usd=30)
    assert body(renew.calls.last.request) == {"years": 2, "max_price_usd": 30}
    assert isinstance(renewal, nc.DomainPurchase) and renewal.wait().expires_at.year == 2029
    domain.renew(max_price_usd=15)  # the TLD's minimum term
    assert body(renew.calls.last.request) == {"max_price_usd": 15}

    code = domain.transfer_out()
    assert (code.auth_code, code.unlocked_at.day, code.expires_at.day) == ("Xy7#pQ2!", 2, 7)
    assert "Xy7" not in repr(code)
    domain.delete()
    assert delete.call_count == 1


def test_renewing_past_the_window_is_not_available(api, client):
    api.post(f"/v1/domains/{DOMAIN_ID}/renew").respond(status_code=409, json={"error": {
        "type": "not_available", "message": "acmebooking.com could be renewed until 2027-09-26."}})
    with pytest.raises(nc.NotAvailable):
        nc.Domain.from_id(DOMAIN_ID).renew(max_price_usd=15)


def test_transfer_out_inside_the_lock(api, client):
    api.post(f"/v1/domains/{DOMAIN_ID}/transfer_out").respond(status_code=409, json={"error": {
        "type": "not_available", "message": "acmebooking.com can't move until 2026-10-31."}})
    with pytest.raises(nc.NotAvailable):
        nc.Domain.from_id(DOMAIN_ID).transfer_out()


def test_inbox_on_a_domain(api, client):
    create = api.post("/v1/inboxes").respond(json={
        "object": "inbox", "id": "inb_9", "address": "help@acmebooking.com", "agent_id": None, "user_id": None,
        "created_at": "2026-09-25T10:00:00Z"})
    inbox = nc.Inbox.create(local_part="help", domain=nc.Domain.from_name("acmebooking.com"))
    assert body(create.calls.last.request) == {"local_part": "help", "domain": "acmebooking.com"}
    assert inbox.address == "help@acmebooking.com"

    api.get(f"/v1/domains/{DOMAIN_ID}").respond(json=BOOKING)
    nc.Inbox.create(local_part="help", domain=nc.Domain.from_id(DOMAIN_ID))  # a lazy domain loads for its name
    assert body(create.calls.last.request)["domain"] == "acmebooking.com"
    nc.Inbox.create(domain="mail.acme.test")  # on a connected domain, a subdomain of it
    assert body(create.calls.last.request) == {"domain": "mail.acme.test"}
    with pytest.raises(TypeError):
        nc.Inbox.create(domain=42)

    api.post("/v1/inboxes").respond(status_code=409, json={"error": {
        "type": "conflict", "message": "acme.test's mail stays where it is: put the inbox on a subdomain of it."}})
    with pytest.raises(nc.Conflict):
        nc.Inbox.create(local_part="help", domain="acme.test")


def test_an_inbox_reads_its_threads_and_a_thread_whole(api, client):
    thread = {"object": "inbox_thread", "id": "thr_1", "inbox_id": "inb_9", "conversation": "inbox:inb_9:thr_1",
              "subject": "Order 1841", "correspondent": "ada@customer.example", "message_count": 2,
              "last_direction": "outbound", "snippet": "On it.", "last_at": "2026-10-14T09:00:00Z"}
    page = api.get("/v1/inboxes/inb_9/threads").respond(json=listing(thread, next_cursor="41"))
    inbox = nc.Inbox.from_id("inb_9")
    listed = inbox.threads(limit=1)
    assert page.calls.last.request.url.params["limit"] == "1" and listed.next_cursor == "41"
    [first] = listed.data
    assert (first.subject, first.message_count, first.last_direction, first.messages) == (
        "Order 1841", 2, "outbound", [])
    assert first.last_at == datetime(2026, 10, 14, 9, tzinfo=timezone.utc)

    api.get("/v1/inboxes/inb_9/threads/thr_1").respond(json={**thread, "messages": [
        {"object": "inbox_message", "id": "thr_1", "inbox_id": "inb_9", "direction": "inbound",
         "from": "ada@customer.example", "to": "help@acmebooking.com", "subject": "Order 1841", "text": "Where is it?"},
        {"object": "inbox_message", "id": "m_2", "inbox_id": "inb_9", "direction": "outbound",
         "from": "help@acmebooking.com", "to": "ada@customer.example", "subject": "Re: Order 1841", "text": "On it."},
    ]})
    whole = inbox.thread("thr_1")
    assert [(m.direction, m.sender, m.text) for m in whole.messages] == [
        ("inbound", "ada@customer.example", "Where is it?"), ("outbound", "help@acmebooking.com", "On it.")]


def test_an_inbox_on_its_domain_sends_new_mail_and_follows_up_on_a_thread(api, client):
    sent = {"object": "inbox_message", "id": "m_3", "inbox_id": "inb_9", "direction": "outbound",
            "from": "hello@acmebooking.com", "to": "orders@millbrook.test", "subject": "Saturday delivery",
            "text": "Can you deliver?", "status": "sending", "delivery_status": None, "delivery_error": None}
    route = api.post("/v1/inboxes/inb_9/messages").respond(201, json=sent)
    inbox = nc.Inbox.from_id("inb_9")
    message = inbox.send("Can you deliver?", to="orders@millbrook.test", subject="Saturday delivery",
                         idempotency_key="ask-1")
    assert body(route.calls.last.request) == {
        "to": "orders@millbrook.test", "subject": "Saturday delivery", "text": "Can you deliver?"}
    assert route.calls.last.request.headers["Idempotency-Key"] == "ask-1"
    assert (message.direction, message.status, message.delivery_status, message.to) == (
        "outbound", "sending", None, "orders@millbrook.test")

    thread = nc.InboxThread(id="thr_1", conversation=None, subject="Saturday delivery", correspondent=None,
                            message_count=2, last_direction="inbound", snippet=None, last_at=None, messages=[], raw={})
    inbox.send("7am works?", thread=thread)
    assert body(route.calls.last.request) == {"text": "7am works?", "thread_id": "thr_1"}


# --- transfer a domain in ------------------------------------------------------

MOVED = {**ACME, "id": "dom_2", "source": "transferred", "status": "active", "noclick_dns": False,
         "expires_at": "2027-11-02T00:00:00Z", "auto_renew": True, "transfer_locked_until": "2026-12-31T00:00:00Z"}


def test_transfer_quote_says_whether_it_can_move(api, client):
    route = api.get("/v1/domains/transfer_quote").respond(json={
        "object": "transfer_quote", "name": "acme.test", "eligible": True, "reason": None,
        "price_usd": 11.25, "renewal_usd": 12.5, "years": 1, "locked_until": None})
    quote = nc.Domain.transfer_quote("acme.test", user="acme")
    assert route.calls.last.request.url.params["name"] == "acme.test"
    assert route.calls.last.request.headers["NoClick-User"] == "acme"
    assert isinstance(quote, nc.TransferQuote) and str(quote) == "acme.test"
    assert (quote.eligible, quote.reason, quote.price_usd, quote.renewal_usd, quote.years, quote.locked_until) == (
        True, None, 11.25, 12.5, 1, None)

    api.get("/v1/domains/transfer_quote").respond(json={
        "object": "transfer_quote", "name": "fresh.test", "eligible": False, "price_usd": 11.25, "renewal_usd": 12.5,
        "years": 1, "reason": "fresh.test was registered on 2026-09-01; the registry's transfer lock holds it.",
        "locked_until": "2026-10-31T00:00:00Z"})
    locked = nc.Domain.transfer_quote("fresh.test")
    assert (locked.eligible, locked.locked_until.day) == (False, 31) and "transfer lock" in locked.reason


def test_transfer_in_is_charged_and_waits_for_the_registry(api, client):
    start = api.post("/v1/domains/transfer_in").respond(json=operation(
        op_id="op_t", kind="domain.transfer_in", status="running", domain_id="dom_2", price_usd=11.25))
    api.get("/v1/domains/dom_2").respond(json={**ACME, "status": "transferring_in"})
    api.get("/v1/operations/op_t/wait").respond(json=operation(
        op_id="op_t", kind="domain.transfer_in", status="succeeded", result={"domain": MOVED}))
    quote = nc.TransferQuote._from({"name": "acme.test", "eligible": True, "price_usd": 11.25})
    transfer = nc.Domain.transfer_in(quote, auth_code="Xy7#pQ2!", max_price_usd=15)  # the account's default registrant
    assert body(start.calls.last.request) == {"name": "acme.test", "auth_code": "Xy7#pQ2!", "max_price_usd": 15}
    assert "NoClick-User" not in start.calls.last.request.headers
    assert isinstance(transfer, nc.DomainTransfer) and isinstance(transfer, nc.DomainPurchase)
    assert (transfer.status, transfer.price_usd, transfer.domain.status) == ("running", 11.25, "transferring_in")
    domain = transfer.wait()
    assert isinstance(domain, nc.Domain)
    assert (domain.source, domain.status, domain.noclick_dns, domain.transfer_locked_until.month) == (
        "transferred", "active", False, 12)

    # Resumed elsewhere, it still knows its outcome's type.
    api.get("/v1/operations/op_t").respond(json=operation(op_id="op_t", kind="domain.transfer_in", status="running"))
    assert nc.DomainTransfer.from_id("op_t").status == "running"
    assert nc.Operation.from_id("op_t").wait().source == "transferred"


def test_a_connected_domain_transfers_in_its_own_scope(api, client):
    read = api.get("/v1/domains/dom_2").respond(json=ACME)
    start = api.post("/v1/domains/transfer_in").respond(json=operation(
        op_id="op_c", kind="domain.transfer_in", status="awaiting_human", domain_id="dom_2", price_usd=11.25))
    acme = nc.Domain.from_id("dom_2")
    nc.Domain.transfer_in(acme, auth_code="Xy7#pQ2!", max_price_usd=15)  # user_42's: their registrant profile
    assert "registrant" not in body(start.calls.last.request) and start.call_count == 1
    with nc.as_user("someone_else"):
        held = nc.Domain.transfer_in(acme, auth_code="Xy7#pQ2!", max_price_usd=15, registrant=ANA)
    request = start.calls.last.request
    assert body(request)["name"] == "acme.test"  # the lazy domain loads for its name
    assert request.headers["NoClick-User"] == USER_ID  # the domain's own user, not the ambient one
    assert held.status == "awaiting_human"  # your policy holds it, like a purchase
    assert held.domain.status == "pending_dns"
    assert read.calls.last.request.headers["NoClick-User"] == USER_ID  # the transfer keeps acting for its user

    api.get("/v1/domains/dom_9").respond(json={**ACME, "id": "dom_9", "name": "acme.dev", "user_id": None})
    nc.Domain.transfer_in(nc.Domain.from_id("dom_9"), auth_code="Xy7#pQ2!", max_price_usd=15)
    assert "NoClick-User" not in start.calls.last.request.headers  # an account domain: the account
    with pytest.raises(TypeError, match="own scope"):
        nc.Domain.transfer_in(acme, auth_code="Xy7#pQ2!", max_price_usd=15, registrant=ANA, user="user_7")


def test_a_users_transfer_is_registered_to_them(api, client):
    start = api.post("/v1/domains/transfer_in").respond(json=operation(
        op_id="op_u", kind="domain.transfer_in", status="running", domain_id=DOMAIN_ID, price_usd=14))
    with nc.as_user("user_42"):
        nc.Domain.transfer_in("anasilva.dev", auth_code="Kq9!mT4z", max_price_usd=20)  # their registrant profile
        assert "registrant" not in body(start.calls.last.request)
        nc.Domain.transfer_in("anasilva.dev", auth_code="Kq9!mT4z", max_price_usd=20, registrant=ANA)
    assert start.calls.last.request.headers["NoClick-User"] == "user_42"
    assert body(start.calls.last.request)["registrant"]["email"] == "ana@example.com"


def test_transfer_in_refusals(api, client):
    api.post("/v1/domains/transfer_in").respond(status_code=409, json={"error": {
        "type": "not_available", "message": "fresh.test can't move until 2026-10-31: the registry's transfer lock."}})
    with pytest.raises(nc.NotAvailable) as err:
        nc.Domain.transfer_in("fresh.test", auth_code="Xy7#pQ2!", max_price_usd=15)
    assert "transfer lock" in err.value.message

    api.post("/v1/domains/transfer_in").respond(status_code=402, json={"error": {
        "type": "price_exceeded", "message": "Moving book.app costs $2,400.00, more than max_price_usd.", "price_usd": 2400}})
    with pytest.raises(nc.PriceExceeded):
        nc.Domain.transfer_in("book.app", auth_code="Xy7#pQ2!", max_price_usd=15)

    # The registry refuses the code: the transfer fails, and nothing is charged.
    api.post("/v1/domains/transfer_in").respond(json=operation(
        op_id="op_x", kind="domain.transfer_in", status="running", domain_id="dom_2", price_usd=11.25))
    api.get("/v1/operations/op_x/wait").respond(json=operation(
        op_id="op_x", kind="domain.transfer_in", status="failed", error={
            "type": "invalid_request", "message": "The registry refused the auth code; nothing was charged.",
            "field": "auth_code"}))
    with pytest.raises(nc.InvalidRequest) as refused:
        nc.Domain.transfer_in("acme.test", auth_code="wrong", max_price_usd=15).wait()
    assert refused.value.field == "auth_code" and refused.value.operation_id == "op_x"


def test_use_noclick_dns_copies_what_it_can_read(api, client):
    move = api.post("/v1/domains/dom_2/use_noclick_dns").respond(json={
        "domain": {**MOVED, "noclick_dns": True},
        "copied": [
            {"type": "MX", "name": "@", "value": "10 mx.mail.example", "status": "verified"},
            {"type": "TXT", "name": "@", "value": "v=spf1 include:mail.example -all", "status": "verified"},
        ]})
    domain = nc.Domain.from_id("dom_2")
    copied = domain.use_noclick_dns()
    assert move.call_count == 1
    assert [(r.type, r.value) for r in copied] == [("MX", "10 mx.mail.example"), ("TXT", "v=spf1 include:mail.example -all")]
    assert domain.noclick_dns is True and domain.source == "transferred"

    api.post("/v1/domains/dom_3/use_noclick_dns").respond(status_code=409, json={"error": {
        "type": "not_available", "message": "acme.dev is registered elsewhere: transfer it in first."}})
    with pytest.raises(nc.NotAvailable):
        nc.Domain.from_id("dom_3").use_noclick_dns()
