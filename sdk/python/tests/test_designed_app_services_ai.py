from datetime import datetime, timezone

import pytest

import noclick as nc
from platform_helpers import USER_ID, body, listing, operation

PROJECT = {
    "object": "project", "id": "prj_1", "name": "booking", "url": "https://booking.noclick.site", "repo_id": "repo_1",
    "framework": "remix", "production_branch": "main", "domain_names": ["acmebooking.com"], "user_id": USER_ID,
    "created_at": "2026-09-01T00:00:00Z",
}
PENDING_EMAIL = {
    "object": "project_email", "status": "pending_dns", "from_address": "noreply@acme.test", "from_name": "Acme",
    "domain": "acme.test", "daily_limit": 200, "sent_today": 0, "paused_reason": None,
    "records": [
        {"type": "TXT", "name": "@", "value": "v=spf1 include:mail.noclick.site ~all", "status": "pending", "purpose": "SPF"},
        {"type": "CNAME", "name": "nc1._domainkey", "value": "nc1.dkim.noclick.site", "status": "verified", "purpose": "DKIM"},
    ],
}
SENT = {
    "object": "sent_email", "id": "em_1", "to": ["ana@example.com"], "subject": "Your booking", "status": "delivered",
    "opened": True, "bounced": False, "error": None, "at": "2026-09-26T09:00:00Z",
}
TEST_PAYMENTS = {
    "object": "project_payments", "mode": "test", "claim_step": "claim", "next_step": "Send the owner claim_url.",
    "claim_url": "https://api.example.com/api/public/payments/claim/c_1", "test_expires_at": "2026-12-01T09:00:00Z",
    "dashboard_url": None, "secrets": ["PAYMENTS_SECRET_KEY", "PAYMENTS_PUBLISHABLE_KEY", "PAYMENTS_WEBHOOK_SECRET"],
    "processor": "stripe", "country": "US", "webhook_url": "https://booking.noclick.site/api/payments/webhook",
}
SIGN_IN = {
    "object": "project_sign_in", "status": "active", "providers": ["email", "google"], "users_table": "users",
    "tables": ["users", "auth_sessions", "auth_accounts", "auth_verifications", "auth_rate_limits"],
    "database": "DB", "library": "better-auth", "version": "1.7.7", "update_available": None,
    "commit": "9f1c2ab", "branch": None, "edited_files": [],
    "callback_urls": {"google": "https://booking.noclick.site/api/auth/callback/google"}, "missing_secrets": [],
    "secrets": ["AUTH_SECRET", "AUTH_URL", "AUTH_PROXY_SECRET"], "error": None,
}


# --- email ---------------------------------------------------------------------

def test_email_enable_on_a_domain_acts_for_the_projects_user(api, client):
    route = api.post("/v1/projects/prj_1/email").respond(json=PENDING_EMAIL)
    app = nc.Project.from_id("prj_1", user=USER_ID)
    setup = app.email.enable(domain=nc.Domain.from_name("acme.test"), from_name="Acme")
    assert body(route.calls.last.request) == {"domain": "acme.test", "from_name": "Acme"}
    assert route.calls.last.request.headers["NoClick-User"] == USER_ID
    assert (setup.status, setup.from_address, setup.domain, setup.daily_limit) == ("pending_dns", "noreply@acme.test", "acme.test", 200)
    assert not setup.can_send
    spf, dkim = setup.records
    assert isinstance(spf, nc.DnsRecord) and (spf.type, spf.name, spf.status, spf.purpose) == ("TXT", "@", "pending", "SPF")
    assert dkim.value == "nc1.dkim.noclick.site"

    app.email.enable()
    assert body(route.calls.last.request) == {}  # the default sender
    with pytest.raises(TypeError):
        app.email.enable(domain=42)


def test_email_through_a_project_by_name_loads_it_first(api, client):
    lookup = api.get("/v1/projects").respond(json=listing(PROJECT))
    status = api.get("/v1/projects/prj_1/email").respond(json={**PENDING_EMAIL, "status": "active", "records": []})
    setup = nc.Project.from_name("booking").email.status()
    assert lookup.calls.last.request.url.params["name"] == "booking"
    assert status.calls.last.request.headers["NoClick-User"] == USER_ID  # the project's own user
    assert setup.status == "active" and setup.can_send and setup.records == []
    assert repr(nc.Project.from_id("prj_1").email) == "ProjectEmail(project='prj_1')"


def test_email_off_until_enabled():
    setup = nc.EmailSetup._from({"object": "project_email", "status": "off"})
    assert (setup.status, setup.from_address, setup.records, setup.broadcast_status) == ("off", None, [], "off")


def test_email_pending_until_its_sending_is_set_up_says_why_once_that_failed():
    setup = nc.EmailSetup._from({**PENDING_EMAIL, "status": "pending", "pending_reason": "NoClick keeps trying."})
    assert (setup.status, setup.pending_reason, setup.can_send) == ("pending", "NoClick keeps trying.", False)
    assert nc.EmailSetup._from(PENDING_EMAIL).pending_reason is None


def test_broadcasts_have_a_status_and_address_of_their_own():
    setup = nc.EmailSetup._from({
        **PENDING_EMAIL, "status": "active", "broadcast_status": "pending_dns",
        "broadcast_from_address": "noreply@news.acme.test", "broadcast_sent_today": 0, "broadcast_paused_reason": None,
    })
    assert (setup.broadcast_status, setup.broadcast_from_address, setup.broadcast_sent_today) == (
        "pending_dns", "noreply@news.acme.test", 0)


def test_a_sign_in_code_goes_on_its_own_lane(api, client):
    route = api.post("/v1/projects/prj_1/email/codes").respond(json={**SENT, "status": "sent", "kind": "code",
                                                                      "subject": "Your booking sign-in code"})
    sent = nc.Project.from_id("prj_1").email.send_code("ana@example.com", "482913", expires_in_s=300)
    assert body(route.calls.last.request) == {"to": "ana@example.com", "code": "482913", "purpose": "sign_in",
                                              "expires_in_s": 300}
    assert route.calls.last.request.headers["Idempotency-Key"].startswith("nc_")
    assert (sent.kind, sent.status) == ("code", "sent") and nc.SentEmail._from(SENT).kind == "message"


def test_send_one_message_idempotently(api, client):
    route = api.post("/v1/projects/prj_1/email/send").respond(json={**SENT, "status": "queued", "opened": None})
    app = nc.Project.from_id("prj_1")
    sent = app.email.send(
        to="ana@example.com", subject="Your booking", text="See you Friday.", html="<p>See you Friday.</p>",
        reply_to="desk@acmebooking.com", idempotency_key="booking-1042",
    )
    request = route.calls.last.request
    assert body(request) == {
        "to": ["ana@example.com"], "subject": "Your booking", "text": "See you Friday.",
        "html": "<p>See you Friday.</p>", "reply_to": "desk@acmebooking.com",
    }
    assert request.headers["Idempotency-Key"] == "booking-1042"
    assert (sent.id, sent.status, sent.opened, sent.bounced, sent.to) == ("em_1", "queued", None, False, ["ana@example.com"])

    app.email.send(["ana@example.com", "desk@acmebooking.com"], "Booking moved", text="Now Saturday.")
    assert body(route.calls.last.request)["to"] == ["ana@example.com", "desk@acmebooking.com"]
    assert route.calls.last.request.headers["Idempotency-Key"].startswith("nc_")
    with pytest.raises(TypeError):
        app.email.send(to="ana@example.com", subject="Empty")
    assert route.call_count == 2


def test_a_send_the_account_cant_pay_for_reads_held_and_a_time_sensitive_one_says_so(api, client):
    route = api.post("/v1/projects/prj_1/email/send").respond(json={**SENT, "status": "held", "opened": None})
    app = nc.Project.from_id("prj_1")
    assert app.email.send("ana@example.com", "New enquiry", text="Hi").status == "held"
    assert "time_sensitive" not in body(route.calls.last.request)
    app.email.send("ana@example.com", "Your sign-in link", text="https://acme.test/in", time_sensitive=True)
    assert body(route.calls.last.request)["time_sensitive"] is True


def test_messages_newest_first_filtered_and_paged(api, client):
    bounced = {**SENT, "id": "em_2", "to": "bob@example.com", "status": "bounced", "bounced": True, "opened": None,
               "error": "550 mailbox unavailable"}
    route = api.get("/v1/projects/prj_1/email/messages").respond(json=listing(SENT, bounced))
    first, second = nc.Project.from_id("prj_1").email.messages(to="ana@example.com", limit=10)
    params = route.calls.last.request.url.params
    assert (params["to"], params["limit"]) == ("ana@example.com", "10")
    assert first.at == datetime(2026, 9, 26, 9, tzinfo=timezone.utc) and first.opened is True
    assert (second.to, second.bounced, second.error) == (["bob@example.com"], True, "550 mailbox unavailable")

    nc.Project.from_id("prj_1").email.messages()
    assert route.calls.last.request.url.params["limit"] == "50"
    assert "to" not in route.calls.last.request.url.params


def test_a_previews_outbox_holds_what_it_kept_with_what_it_would_have_said(api, client):
    kept = {**SENT, "status": "captured", "opened": None, "environment": "preview", "captured": ["ana@example.com"],
            "text": "See you Friday.", "html": None}
    route = api.get("/v1/projects/prj_1/email/messages").respond(json=listing(kept))
    (message,) = nc.Project.from_id("prj_1").email.messages(environment="preview")
    assert route.calls.last.request.url.params["environment"] == "preview"
    assert (message.status, message.environment, message.captured, message.text) == (
        "captured", "preview", ["ana@example.com"], "See you Friday.")
    sent = nc.SentEmail._from(SENT)
    assert (sent.environment, sent.captured, sent.text) == ("production", [], None)
    assert nc.Broadcast._from({"id": "op_1", "sent": 1, "captured": 2, "skipped": []}).captured == 2


# --- payments ------------------------------------------------------------------

def test_payments_enable_then_status(api, client):
    enable = api.post("/v1/projects/prj_1/payments").respond(json=TEST_PAYMENTS)
    status = api.get("/v1/projects/prj_1/payments").respond(json={
        **TEST_PAYMENTS, "mode": "live", "claim_step": None, "claim_url": None, "test_expires_at": None,
        "dashboard_url": "https://payments.example/dashboard/acct_1",
    })
    app = nc.Project.from_id("prj_1", user=USER_ID)
    setup = app.payments.enable(country="US", owner_email="owner@acmebooking.com")
    assert body(enable.calls.last.request) == {"country": "US", "owner_email": "owner@acmebooking.com"}
    assert enable.calls.last.request.headers["NoClick-User"] == USER_ID
    assert (setup.mode, setup.claim_step, setup.country, setup.processor) == ("test", "claim", "US", "stripe")
    assert setup.claim_url == "https://api.example.com/api/public/payments/claim/c_1"
    assert setup.test_expires_at == datetime(2026, 12, 1, 9, tzinfo=timezone.utc)
    assert setup.secrets[0] == "PAYMENTS_SECRET_KEY" and setup.webhook_url.endswith("/api/payments/webhook")
    app.payments.enable()
    assert body(enable.calls.last.request) == {}
    live = app.payments.status()
    assert status.call_count == 1
    assert (live.mode, live.claim_url, live.dashboard_url) == ("live", None, "https://payments.example/dashboard/acct_1")
    assert nc.PaymentsSetup._from({}).mode == "off"


# --- sign-in -------------------------------------------------------------------

def test_sign_in_enable_is_an_operation_giving_the_setup(api, client):
    start = api.post("/v1/projects/prj_1/sign_in").respond(json=operation(kind="project.sign_in.enable", status="running"))
    done = operation(kind="project.sign_in.enable", status="succeeded", result=SIGN_IN)
    api.get("/v1/operations/op_1/wait").respond(json=done)
    api.get("/v1/operations/op_1").respond(json=done)
    app = nc.Project.from_id("prj_1", user=USER_ID)
    op = app.sign_in.enable(providers=["email", "google"], branch="add-sign-in")
    assert body(start.calls.last.request) == {"providers": ["email", "google"], "users_table": "users", "branch": "add-sign-in"}
    assert start.calls.last.request.headers["NoClick-User"] == USER_ID
    assert isinstance(op, nc.Operation) and op.kind == "project.sign_in.enable"
    setup = op.wait()
    assert isinstance(setup, nc.SignInSetup)
    assert (setup.status, setup.providers, setup.users_table, setup.commit) == ("active", ["email", "google"], "users", "9f1c2ab")
    assert setup.callback_urls == {"google": "https://booking.noclick.site/api/auth/callback/google"}
    assert (setup.library, setup.version, setup.tables[0], setup.missing_secrets) == ("better-auth", "1.7.7", "users", [])
    # Resumed anywhere, the registered reader types the result.
    assert isinstance(nc.Operation.from_id("op_1").wait(), nc.SignInSetup)

    app.sign_in.enable(["github"], users_table="members", database="USERS_DB")
    assert body(start.calls.last.request) == {"providers": ["github"], "users_table": "members", "database": "USERS_DB"}


def test_sign_in_providers_through_noclick_or_on_your_own_client(api, client):
    start = api.post("/v1/projects/prj_1/sign_in").respond(json=operation(kind="project.sign_in.enable", status="running"))
    done = operation(kind="project.sign_in.enable", status="succeeded", result={
        **SIGN_IN, "providers": ["email", "google", "microsoft"], "managed_providers": ["microsoft"]})
    api.get("/v1/operations/op_1/wait").respond(json=done)
    app = nc.Project.from_id("prj_1")
    setup = app.sign_in.enable(["email", "google", "microsoft"], own_credentials=["google"]).wait()
    assert body(start.calls.last.request) == {"providers": ["email", "google", "microsoft"],
                                              "own_credentials": ["google"], "users_table": "users"}
    assert (setup.managed_providers, setup.callback_urls) == (["microsoft"], SIGN_IN["callback_urls"])
    # An empty list moves every provider onto NoClick's.
    app.sign_in.enable(["email", "google"], own_credentials=[])
    assert body(start.calls.last.request)["own_credentials"] == []
    assert nc.SignInSetup._from(SIGN_IN).managed_providers == []


def test_sign_in_upgrade_is_an_operation_giving_the_setup(api, client):
    start = api.post("/v1/projects/prj_1/sign_in/upgrade").respond(
        json=operation(kind="project.sign_in.upgrade", status="running"))
    done = operation(kind="project.sign_in.upgrade", status="succeeded", result={**SIGN_IN, "branch": "sign-in-update"})
    api.get("/v1/operations/op_1/wait").respond(json=done)
    op = nc.Project.from_id("prj_1").sign_in.upgrade(branch="sign-in-update")
    assert body(start.calls.last.request) == {"branch": "sign-in-update"} and op.kind == "project.sign_in.upgrade"
    setup = op.wait()
    assert isinstance(setup, nc.SignInSetup) and setup.branch == "sign-in-update"


def test_sign_in_status(api, client):
    route = api.get("/v1/projects/prj_1/sign_in").respond(json={
        **SIGN_IN, "status": "active", "providers": ["email", "google"], "missing_secrets": ["GOOGLE_CLIENT_SECRET"],
    })
    setup = nc.Project.from_id("prj_1").sign_in.status()
    assert route.call_count == 1
    assert setup.missing_secrets == ["GOOGLE_CLIENT_SECRET"]
    assert nc.SignInSetup._from({"status": "off"}).providers == []
