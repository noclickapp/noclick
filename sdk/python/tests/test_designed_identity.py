"""Cards (designed, not built yet), browsers and browser profiles, against the mocked API."""

import httpx
import pytest

import noclick as nc
from platform_helpers import USER_ID, body, listing, operation

CARD = {
    "object": "card", "id": "card_1", "name": "Office supplies", "last4": "4242", "brand": "visa",
    "exp_month": 9, "exp_year": 2029, "status": "active", "limit_usd": 1500, "interval": "month",
    "spent_usd": 412.3, "resets_at": "2026-10-01T00:00:00Z", "merchants": ["office_supplies"],
    "require_approval_above_usd": 200, "agent_id": "agt_2", "user_id": USER_ID,
    "created_at": "2026-09-01T10:00:00Z",
}
CHARGE = {"object": "card_transaction", "id": "tx_1", "card_id": "card_1", "amount_usd": 86.4,
          "merchant": "Staples", "merchant_category": "office_supplies", "status": "approved",
          "decline_reason": None, "approval_id": None, "at": "2026-09-25T10:00:00Z"}
HELD = {**CHARGE, "id": "tx_2", "amount_usd": 640.0, "merchant": "Herman Miller", "status": "pending_approval",
        "approval_id": "op_appr"}


# --- cards ------------------------------------------------------------------------

def test_create_sends_the_limits_and_resolves_the_agent(api, client):
    api.get("/v1/agents").respond(json=listing({"object": "agent", "id": "agt_2", "name": "concierge", "user_id": "acme"}))
    create = api.post("/v1/cards").respond(json=CARD)
    with nc.as_user("acme"):
        card = nc.Card.create(
            "Office supplies", limit_usd=1500, merchants=["office_supplies"],
            agent=nc.Agent.from_name("concierge"), require_approval_above_usd=200,
        )
    assert body(create.calls.last.request) == {
        "name": "Office supplies", "limit_usd": 1500, "interval": "month", "merchants": ["office_supplies"],
        "agent_id": "agt_2", "require_approval_above_usd": 200}
    assert create.calls.last.request.headers["NoClick-User"] == "acme"
    assert (card.last4, card.brand, card.spent_usd, card.resets_at.month) == ("4242", "visa", 412.3, 10)
    assert repr(card) == "Card(id='card_1', name='Office supplies', last4='4242', status='active')"

    nc.Card.create("Software", limit_usd=200, interval="transaction", merchants="software")
    assert body(create.calls.last.request) == {
        "name": "Software", "limit_usd": 200, "interval": "transaction", "merchants": ["software"]}


def test_from_name_finds_an_open_card_and_converges_the_definition(api, client):
    closed = {**CARD, "id": "card_0", "status": "closed", "limit_usd": 10}
    lookup = api.get("/v1/cards").respond(json=listing(closed, CARD))
    patch = api.patch("/v1/cards/card_1").respond(json={**CARD, "limit_usd": 2000})
    card = nc.Card.from_name("Office supplies", create_if_missing=True, limit_usd=2000,
                             merchants=["office_supplies"], require_approval_above_usd=200, user="acme")
    assert lookup.call_count == 0  # lazy
    assert card.limit_usd == 2000
    assert lookup.calls.last.request.url.params["name"] == "Office supplies"
    assert body(patch.calls.last.request) == {"limit_usd": 2000}  # only what differs; the closed card is skipped
    assert card.id == "card_1"


def test_an_explicit_none_in_card_from_name_clears_the_field(api, client):
    held = {**CARD, "agent_id": "agt_1", "require_approval_above_usd": 200}
    api.get("/v1/cards").respond(json=listing(held))
    patch = api.patch("/v1/cards/card_1").mock(side_effect=lambda request: httpx.Response(200, json={
        **held, **body(request)}))
    card = nc.Card.from_name("Office supplies", create_if_missing=True, limit_usd=held["limit_usd"],
                             merchants=held["merchants"], agent=None, require_approval_above_usd=None)
    assert card.agent_id is None
    assert body(patch.calls.last.request) == {"agent_id": None, "require_approval_above_usd": None}


def test_from_name_issues_a_missing_card_and_refuses_one_without_a_limit(api, client):
    api.get("/v1/cards").respond(json=listing())
    create = api.post("/v1/cards").respond(json={**CARD, "id": "card_9", "name": "Travel"})
    card = nc.Card.from_name("Travel", create_if_missing=True, limit_usd=3000, merchants=["travel"])
    assert card.id == "card_9"
    assert body(create.calls.last.request) == {
        "name": "Travel", "limit_usd": 3000, "interval": "month", "merchants": ["travel"]}
    with pytest.raises(ValueError, match="limit_usd"):
        nc.Card.from_name("Travel", create_if_missing=True)
    with pytest.raises(nc.NotFound, match="No open card is named 'Gone'"):
        nc.Card.from_name("Gone").hydrate()


def test_list_filters_and_reads_across_users(api, client):
    route = api.get("/v1/cards").respond(json=listing(CARD))
    [card] = nc.Card.list(status="frozen", agent="agt_2", user_filter=nc.ALL_USERS)
    params = route.calls.last.request.url.params
    assert (params["status"], params["agent_id"], params["user_id"]) == ("frozen", "agt_2", "all")
    assert "NoClick-User" not in route.calls.last.request.headers
    page = nc.Card.list_page(limit=1)
    assert page.data == [card] and page.next_cursor is None


def test_transactions_are_typed_and_a_held_one_waits_on_its_approval(api, client):
    api.get("/v1/cards/card_1").respond(json=CARD)
    history = api.get("/v1/cards/card_1/transactions").respond(json=listing(HELD, CHARGE))
    api.get("/v1/operations/op_appr/wait").respond(json=operation(
        op_id="op_appr", kind="human.approve", status="succeeded", result={"approved": True}))
    card = nc.Card.from_id("card_1", user=USER_ID)
    held, paid = card.transactions(limit=5)
    assert history.calls.last.request.url.params["limit"] == "5"
    assert history.calls.last.request.headers["NoClick-User"] == USER_ID
    assert (paid.merchant, paid.amount_usd, paid.status, paid.at.day) == ("Staples", 86.4, "approved", 25)
    assert (held.status, held.approval_id) == ("pending_approval", "op_appr")
    assert nc.Operation.from_id(held.approval_id).wait() is True
    card.transactions(status="declined")
    assert history.calls.last.request.url.params["status"] == "declined"


DETAILS = {"object": "card_details", "card_id": "card_1", "url": "https://noclick.com/c/rv_1",
           "expires_at": "2026-10-02T10:10:00Z", "last4": "4242", "brand": "visa", "exp_month": 9, "exp_year": 2029,
           "single_use": False, "amount_usd": None, "closes_at": None, "cardholder": "Acme Corp",
           "billing_address": {"postal_code": "94107", "country": "US"}}


def test_reveal_is_a_page_and_never_the_number(api, client):
    api.get("/v1/cards/card_1").respond(json=CARD)
    reveal = api.post("/v1/cards/card_1/reveal").respond(json=DETAILS)
    details = nc.Card.from_id("card_1").reveal()
    assert reveal.call_count == 1
    assert (details.url, details.last4, details.cardholder, details.expires_at.minute) == (
        "https://noclick.com/c/rv_1", "4242", "Acme Corp", 10)
    assert details.billing_address["postal_code"] == "94107"
    assert not hasattr(details, "number") and not hasattr(details, "cvc")
    assert "/c/rv_1" not in repr(details)  # the url shows the number to whoever opens it


def test_a_purchase_is_an_operation_that_waits_for_its_approval_and_returns_its_number(api, client):
    api.get("/v1/cards/card_1").respond(json=CARD)
    held = operation(op_id="op_buy", kind="card.purchase", status="awaiting_human")
    start = api.post("/v1/cards/card_1/purchases").respond(202, json=held)
    api.get("/v1/operations/op_buy/wait").respond(json=operation(
        op_id="op_buy", kind="card.purchase", status="succeeded",
        result={**DETAILS, "single_use": True, "amount_usd": 124.5, "closes_at": "2026-10-02T11:00:00Z"}))
    with nc.as_user(USER_ID):
        op = nc.Card.from_id("card_1").purchase(124.50, "Staples", reason="Toner")
    assert body(start.calls.last.request) == {"amount_usd": 124.5, "merchant": "Staples", "reason": "Toner"}
    assert start.calls.last.request.headers["NoClick-User"] == USER_ID
    details = op.wait()
    assert isinstance(details, nc.CardDetails) and details.amount_usd == 124.5 and details.single_use


def test_a_settled_charge_is_disputed_with_its_reason(api, client):
    api.get("/v1/cards/card_1").respond(json=CARD)
    filed = api.post("/v1/cards/card_1/transactions/tx_1/dispute").respond(201, json={
        "object": "card_dispute", "id": "dp_1", "transaction_id": "tx_1", "reason": "duplicate",
        "status": "submitted", "amount_usd": 86.4, "created_at": "2026-10-02T10:00:00Z"})
    charge = nc.CardTransaction._from({**CHARGE, "status": "settled"})
    original = nc.CardTransaction._from({**CHARGE, "id": "tx_0"})
    dispute = nc.Card.from_id("card_1").dispute(charge, reason="duplicate", explanation="Charged twice",
                                                 duplicate_of=original)
    assert body(filed.calls.last.request) == {"reason": "duplicate", "explanation": "Charged twice",
                                              "duplicate_of": "tx_0"}
    assert (dispute.id, dispute.status, dispute.amount_usd) == ("dp_1", "submitted", 86.4)


def test_program_and_merchant_categories_are_the_accounts(api, client):
    program = api.get("/v1/cards/program").respond(json={
        "object": "card_program", "status": "pending_verification", "requirements_due": ["company.tax_id"],
        "company_name": None, "country": "US", "currency": "usd",
        "onboarding_url": "https://noclick.com/dashboard/developers/cards/onboarding"})
    api.get("/v1/cards/merchant_categories").respond(json=listing(
        {"object": "merchant_category", "name": "software", "description": "Software.", "mccs": ["5734"]}))
    with nc.as_user("acme"):
        state = nc.Card.program()
        [software] = nc.Card.merchant_categories()
    assert "NoClick-User" not in program.calls.last.request.headers
    assert (state.status, state.requirements_due, state.country) == ("pending_verification", ["company.tax_id"], "US")
    assert (software.name, software.mccs) == ("software", ["5734"])
    opened = api.post("/v1/cards/program/session").respond(json={
        "object": "card_onboarding_session", "client_secret": "secret_fixture", "publishable_key": "pk_fixture",
        "account": "acct_fixture", "expires_at": None,
        "program": {"object": "card_program", "status": "not_started", "requirements_due": []}})
    with nc.as_user("acme"):
        session = nc.Card.onboarding_session()
    assert "NoClick-User" not in opened.calls.last.request.headers
    assert (session.client_secret, session.account, session.program.status) == (
        "secret_fixture", "acct_fixture", "not_started")


def test_update_clears_with_none_and_leaves_the_rest(api, client):
    api.get("/v1/cards/card_1").respond(json=CARD)
    patch = api.patch("/v1/cards/card_1").respond(json={**CARD, "merchants": None, "agent_id": None})
    card = nc.Card.from_id("card_1").update(limit_usd=2000, merchants=None, agent=None)
    assert body(patch.calls.last.request) == {"limit_usd": 2000, "merchants": None, "agent_id": None}
    assert card.merchants is None and card.agent_id is None
    card.update(merchants="software")
    assert body(patch.calls.last.request) == {"merchants": ["software"]}


def test_freeze_unfreeze_and_close(api, client):
    api.get("/v1/cards/card_1").respond(json=CARD)
    freeze = api.post("/v1/cards/card_1/freeze").respond(json={**CARD, "status": "frozen"})
    unfreeze = api.post("/v1/cards/card_1/unfreeze").respond(json=CARD)
    close = api.post("/v1/cards/card_1/close").respond(json={**CARD, "status": "closed"})
    card = nc.Card.from_id("card_1")
    assert card.freeze().status == "frozen" and freeze.call_count == 1
    assert card.unfreeze().status == "active" and unfreeze.call_count == 1
    assert card.close().status == "closed" and close.call_count == 1


def test_funding_is_the_companys_balance_and_its_bank_details(api, client):
    route = api.get("/v1/cards/funding").respond(json={
        "object": "card_funding", "balance_usd": 2480.0, "pending_usd": 640.0, "available_usd": 1840.0,
        "top_up_url": "https://noclick.com/dashboard/developers/cards/funding",
        "bank_transfer": {"bank_name": "TEST BANK", "routing_number": "110000000", "account_number": "000123",
                          "networks": ["ach", "wire"]}})
    with nc.as_user("acme"):
        funding = nc.Card.funding()
    assert "NoClick-User" not in route.calls.last.request.headers  # the account's, whoever asks
    assert (funding.balance_usd, funding.pending_usd, funding.available_usd) == (2480.0, 640.0, 1840.0)
    assert funding.top_up_url.endswith("/cards/funding")
    assert (funding.bank_transfer.routing_number, funding.bank_transfer.networks) == ("110000000", ["ach", "wire"])


def test_cards_not_enabled_is_not_available(api, client):
    api.post("/v1/cards").respond(409, json={"error": {
        "type": "not_available", "message": "Cards aren't enabled for this account."}})
    with pytest.raises(nc.NotAvailable):
        nc.Card.create("Software", limit_usd=200)


# --- browser profiles -------------------------------------------------------------

PROFILE = {"object": "browser_profile", "id": "bp_1", "name": "ana-work", "user_id": USER_ID,
           "sites": [{"domain": "portal.example.com", "signed_in_at": "2026-09-20T10:00:00Z",
                      "signed_in_by": "ana@example.com", "last_used_at": "2026-09-25T10:00:00Z"}],
           "last_used_at": "2026-09-25T10:00:00Z", "created_at": "2026-09-20T09:00:00Z"}
LOGIN = {"object": "browser_login", "url": "https://noclick.com/b/login_1", "expires_at": "2026-09-26T10:00:00Z",
         "domain": "portal.example.com", "delivery": {"delivered_via": ["email"], "undelivered": []},
         "operation": operation(op_id="op_login", kind="browser.login", status="awaiting_human")}


def test_profile_from_name_creates_on_first_use(api, client):
    lookup = api.get("/v1/browser_profiles").respond(json=listing())
    create = api.post("/v1/browser_profiles").respond(json=PROFILE)
    profile = nc.BrowserProfile.from_name("ana-work", create_if_missing=True, user="user_42")
    assert lookup.call_count == 0
    [site] = profile.sites
    assert lookup.calls.last.request.url.params["name"] == "ana-work"
    assert lookup.calls.last.request.headers["NoClick-User"] == "user_42"
    assert body(create.calls.last.request) == {"name": "ana-work"}
    assert (site.domain, site.signed_in_at.day, site.last_used_at.day) == ("portal.example.com", 20, 25)
    assert site.signed_in_by == "ana@example.com"   # who is asked again when the sign-in expires
    with pytest.raises(nc.NotFound, match="No browser profile is named 'other'"):
        nc.BrowserProfile.from_name("other").hydrate()


def test_login_sends_a_live_browser_link_and_waits_for_the_sign_in(api, client):
    api.get("/v1/browser_profiles").respond(json=listing(PROFILE))
    start = api.post("/v1/browser_profiles/bp_1/login").respond(json=LOGIN)
    api.get("/v1/operations/op_login/wait").respond(json=operation(
        op_id="op_login", kind="browser.login", status="succeeded",
        result={"site": {"domain": "portal.example.com", "signed_in_at": "2026-09-26T09:00:00Z"}}))
    profile = nc.BrowserProfile.from_name("ana-work", user="user_42")
    login = profile.login("https://portal.example.com", reason="to download your invoices")
    assert body(start.calls.last.request) == {"url": "https://portal.example.com", "reason": "to download your invoices"}
    assert start.calls.last.request.headers["NoClick-User"] == USER_ID  # the profile's own user
    assert isinstance(login, nc.Operation) and login.kind == "browser.login" and login.status == "awaiting_human"
    assert (str(login), login.domain, login.delivered_via) == ("https://noclick.com/b/login_1", "portal.example.com", ["email"])
    site = login.wait()
    assert isinstance(site, nc.SiteLogin) and site.domain == "portal.example.com" and site.last_used_at is None
    assert site.signed_in_by is None

    profile.login("https://vendor.example.com", human=nc.Human(email="ops@acme.test"))
    assert body(start.calls.last.request) == {"url": "https://vendor.example.com", "human": {"email": "ops@acme.test"}}
    with pytest.raises(TypeError, match="noclick.Human"):
        profile.login("https://vendor.example.com", human="ops@acme.test")


def test_login_operations_are_pinned_to_their_kind(api, client):
    route = api.get("/v1/operations").respond(json=listing())
    nc.BrowserLogin.list(status="awaiting_human")
    assert route.calls.last.request.url.params["kind"] == "browser.login"
    with pytest.raises(TypeError, match="browser.login"):
        nc.BrowserLogin.list(kind="agent.message")


def test_forget_and_delete_act_by_id(api, client):
    get = api.get("/v1/browser_profiles/bp_1").respond(json=PROFILE)
    forget = api.delete("/v1/browser_profiles/bp_1/sites/portal.example.com").respond(204)
    delete = api.delete("/v1/browser_profiles/bp_1").respond(204)
    profile = nc.BrowserProfile.get("bp_1")
    profile.forget("portal.example.com")
    assert forget.call_count == 1 and profile.sites == []
    nc.BrowserProfile.from_id("bp_1").delete()
    assert delete.call_count == 1 and get.call_count == 1  # an id needs no read first


# --- browsers ---------------------------------------------------------------------

BROWSER = {"object": "browser", "id": "br_1", "status": "running", "profile_id": "bp_1", "agent_id": None,
           "live_url": "https://noclick.com/live/br_1", "url": "about:blank", "title": "", "timeout_s": 900,
           "cost_usd": 0.0, "user_id": USER_ID, "created_at": "2026-09-26T10:00:00Z",
           "expires_at": "2026-09-26T10:15:00Z", "closed_at": None}
ACT = {"done": True, "summary": "Downloaded 3 invoices from September.", "url": "https://portal.example.com/invoices",
       "steps": [{"action": "click", "detail": "September", "url": "https://portal.example.com/invoices"}],
       "downloads": [{"name": "INV-0912.pdf", "size_bytes": 48213, "url": "https://files.example.com/d/1"}],
       "cost_usd": 0.18}


def test_create_with_a_profile_acts_for_its_user_and_closes_on_exit(api, client):
    api.get("/v1/browser_profiles").respond(json=listing(PROFILE))
    create = api.post("/v1/browsers").respond(json=BROWSER)
    close = api.delete("/v1/browsers/br_1").respond(json={**BROWSER, "status": "closed"})
    profile = nc.BrowserProfile.from_name("ana-work", user="user_42")
    with nc.Browser.create(profile=profile, timeout_s=900, human=nc.Human(email="ana@example.com")) as browser:
        assert browser.live_url == "https://noclick.com/live/br_1"
    assert body(create.calls.last.request) == {"profile_id": "bp_1", "timeout_s": 900, "human": {"email": "ana@example.com"}}
    assert create.calls.last.request.headers["NoClick-User"] == USER_ID
    assert close.call_count == 1 and browser.status == "closed"

    nc.Browser.create()
    assert body(create.calls.last.request) == {}


def test_create_on_a_machine_names_it_and_reads_where_it_runs(api, client):
    on_box = {**BROWSER, "profile_id": None, "place": "machine", "place_name": "build-box"}
    create = api.post("/v1/browsers").respond(json=on_box)
    browser = nc.Browser.create(machine="m_1", timeout_s=900)
    assert body(create.calls.last.request) == {"machine_id": "m_1", "timeout_s": 900}
    assert (browser.place, browser.place_name) == ("machine", "build-box")
    api.get("/v1/browsers/br_1").respond(json={**on_box, "status": "failed", "end_reason": "image_pull_failed"})
    assert browser.refresh().end_reason == "image_pull_failed" and browser.status == "failed"
    nc.Browser.create(machine=nc.Machine.from_id("m_2"))
    assert body(create.calls.last.request) == {"machine_id": "m_2"}


def test_goto_extract_screenshot_and_content(api, client):
    goto = api.post("/v1/browsers/br_1/goto").respond(json={"url": "https://portal.example.com/invoices", "title": "Invoices"})
    extract = api.post("/v1/browsers/br_1/extract").respond(json={"data": [{"number": "INV-0912", "total_usd": 120.5}]})
    shot = api.get("/v1/browsers/br_1/screenshot").respond(content=b"\x89PNG")
    content = api.get("/v1/browsers/br_1/content").respond(json={"content": "# Invoices"})
    browser = nc.Browser.from_id("br_1", user=USER_ID)
    page = browser.goto("https://portal.example.com/invoices")
    assert body(goto.calls.last.request) == {"url": "https://portal.example.com/invoices"}
    assert (page.url, page.title, browser.url, browser.title) == (
        "https://portal.example.com/invoices", "Invoices", "https://portal.example.com/invoices", "Invoices")
    schema = {"type": "array"}
    assert browser.extract("the invoice numbers and totals", schema=schema)[0]["number"] == "INV-0912"
    assert body(extract.calls.last.request) == {"query": "the invoice numbers and totals", "schema": schema}
    assert browser.screenshot(full_page=True) == b"\x89PNG"
    assert shot.calls.last.request.url.params["full_page"] == "true"
    browser.screenshot()
    assert "full_page" not in shot.calls.last.request.url.params
    assert browser.content() == "# Invoices"
    assert content.calls.last.request.url.params["format"] == "markdown"


def test_act_waits_for_the_result_or_returns_the_operation(api, client):
    act = api.post("/v1/browsers/br_1/act").mock(side_effect=[
        httpx.Response(202, json=operation(op_id="op_act", kind="browser.act", status="running")),
        httpx.Response(202, json=operation(op_id="op_act2", kind="browser.act", status="running")),
    ])
    api.get("/v1/operations/op_act/wait").respond(json=operation(
        op_id="op_act", kind="browser.act", status="succeeded", result=ACT))
    api.get("/v1/operations/op_act2/wait").respond(json=operation(
        op_id="op_act2", kind="browser.act", status="succeeded", result={"done": False, "summary": "Ran out of steps."}))
    browser = nc.Browser.from_id("br_1")
    result = browser.act("Download every invoice from September", max_steps=40)
    assert body(act.calls[0].request) == {"instruction": "Download every invoice from September", "max_steps": 40}
    assert isinstance(result, nc.ActResult) and result.done and str(result) == "Downloaded 3 invoices from September."
    assert (result.steps[0]["action"], result.downloads[0]["name"], result.cost_usd) == ("click", "INV-0912.pdf", 0.18)

    op = browser.act("Compare flights", background=True)
    assert isinstance(op, nc.Operation) and op.kind == "browser.act"
    assert body(act.calls[1].request) == {"instruction": "Compare flights"}
    later = op.wait()
    assert (later.done, later.summary, later.downloads) == (False, "Ran out of steps.", [])


def test_sign_in_with_a_website_login_and_an_act_that_may_sign_up(api, client):
    signed = api.post("/v1/browsers/br_1/sign_in").respond(
        202, json=operation(op_id="op_in", kind="browser.act", status="running"))
    api.get("/v1/operations/op_in/wait").respond(json=operation(
        op_id="op_in", kind="browser.act", status="succeeded",
        result={"done": True, "summary": "Signed in with 'acme-billing'.", "steps": [], "url": "https://acme.test/"}))
    result = nc.Browser.from_id("br_1").sign_in("acme-billing")
    assert body(signed.calls[0].request) == {"connection": "acme-billing"}
    assert isinstance(result, nc.ActResult) and result.done and result.url == "https://acme.test/"

    act = api.post("/v1/browsers/br_1/act").respond(202, json=operation(op_id="op_act", kind="browser.act",
                                                                         status="running"))
    nc.Browser.from_id("br_1").act("Make an account for ana@acme.test", sign_up=True, background=True)
    assert body(act.calls[0].request) == {"instruction": "Make an account for ana@acme.test", "sign_up": True}


def test_a_website_logins_own_address_and_the_mail_sent_there(api, client):
    api.get("/v1/connections/acme-com/mail").respond(json={
        "object": "list", "address": "login-0f3a@noclick.email", "has_more": False, "data": [{
            "object": "login_mail", "id": "lm_1", "from": "no-reply@acme.com", "subject": "Your Acme code",
            "text": "Your code is 482910.", "kind": "code", "received_at": "2026-11-28T10:00:00Z",
            "expires_at": "2026-12-05T10:00:00Z"}]})
    mail = nc.Connection.from_name("acme-com").login_mail()
    assert mail.address == "login-0f3a@noclick.email"
    [message] = mail.messages
    assert (message.sender, message.subject, message.kind) == ("no-reply@acme.com", "Your Acme code", "code")


def test_a_captcha_holds_the_step_on_a_person(api, client):
    api.post("/v1/browsers/br_1/act").respond(202, json=operation(op_id="op_act", kind="browser.act", status="running"))
    waits = api.get("/v1/operations/op_act/wait").mock(side_effect=[
        httpx.Response(200, json=operation(op_id="op_act", kind="browser.act", status="awaiting_human")),
        httpx.Response(200, json=operation(op_id="op_act", kind="browser.act", status="succeeded", result=ACT)),
    ])
    assert nc.Browser.from_id("br_1").act("Sign in and download the invoices").done
    assert waits.call_count == 2


def test_list_browsers_by_profile_and_status(api, client):
    route = api.get("/v1/browsers").respond(json=listing(BROWSER))
    [browser] = nc.Browser.list(profile=nc.BrowserProfile.from_id("bp_1"), status="live", user_filter=nc.ALL_USERS)
    params = route.calls.last.request.url.params
    assert (params["profile_id"], params["status"], params["user_id"]) == ("bp_1", "live", "all")
    assert browser == nc.Browser.from_id("br_1") and browser.expires_at.minute == 15
    assert nc.Browser.list_page(limit=5).data == [browser]


def test_the_operations_decode_by_kind_anywhere(api, client):
    api.get("/v1/operations/op_act/wait").respond(json=operation(
        op_id="op_act", kind="browser.act", status="succeeded", result=ACT))
    assert nc.Operation.from_id("op_act").wait().summary == "Downloaded 3 invoices from September."
