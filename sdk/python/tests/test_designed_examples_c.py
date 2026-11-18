"""Designed from the examples (users, inboxes, phone numbers, channels, apps, domains, brand,
cards), and numbers you bring (connected or ported), against the mocked API: routes, bodies,
convergence and the client's own refusals."""

import hashlib
import hmac
import time
from datetime import datetime, timezone

import httpx
import pytest

import noclick as nc
from platform_helpers import BASE, USER_ID, body, listing, operation, user_row

INBOX = {"object": "inbox", "id": "inb_1", "name": "support", "address": "help@acme.test", "agent_id": "agt_1",
         "senders": "anyone", "user_id": None, "created_at": "2026-09-25T10:00:00Z"}
NUMBER = {"object": "phone_number", "id": "pn_1", "name": "front-desk", "number": "+14155550123", "agent_id": None,
          "monthly_usd": 1.5, "record_calls": False, "user_id": None, "created_at": "2026-09-25T10:00:00Z"}
CHANNEL = {"object": "channel", "id": "ch_1", "name": "daily", "mode": "mentions", "status": "open",
           "max_agent_turns": 12, "budget_usd": None, "user_id": None, "created_at": "2026-09-25T10:00:00Z",
           "members": [{"id": "m_1", "type": "agent", "agent_id": "agt_1", "name": "writer"},
                       {"id": "m_2", "type": "agent", "agent_id": "agt_old", "name": "old"}]}
PROJECT = {"object": "project", "id": "prj_1", "name": "booking", "url": "https://booking.noclick.site",
           "repo_id": "rp_1", "user_id": None}
DOMAIN = {"object": "domain", "id": "dom_1", "name": "acmebooking.com", "source": "bought", "status": "active",
          "auto_renew": True}
CONTACT = nc.DomainContact(name="Dana Reyes", email="dana@acmebooking.test", phone="+14155550188",
                           address="1 Ferry Building", city="San Francisco", region="CA", postal_code="94111",
                           country="US")


def _cron(trigger_id, expr, message):
    return {"object": "agent_trigger", "id": trigger_id, "kind": "cron",
            "spec": {"cron": expr, "tz": "UTC", "message": message}, "status": "active",
            "next_run": "2026-10-02T09:00:00Z", "created_at": "2026-09-25T10:00:00Z"}


# --- users -----------------------------------------------------------------------

def test_user_timezone_is_sent_converged_and_cleared(api, client):
    create = api.post("/v1/users").respond(json=user_row(timezone="America/Sao_Paulo"))
    user = nc.User.create(USER_ID, timezone="America/Sao_Paulo")
    assert body(create.calls.last.request) == {"id": USER_ID, "timezone": "America/Sao_Paulo"}
    assert user.timezone == "America/Sao_Paulo"

    api.get(f"/v1/users/{USER_ID}").respond(json=user_row(email="ana@example.com", timezone="UTC"))
    patch = api.patch(f"/v1/users/{USER_ID}").respond(json=user_row(timezone="Europe/Lisbon"))
    converged = nc.User.from_id(USER_ID, create_if_missing=True, email="ana@example.com", timezone="Europe/Lisbon")
    assert converged.timezone == "Europe/Lisbon"
    assert body(patch.calls.last.request) == {"timezone": "Europe/Lisbon"}  # only what differs

    nc.User.from_id(USER_ID).update(timezone=None)
    assert body(patch.calls.last.request) == {"timezone": None}


# --- inboxes ---------------------------------------------------------------------

def test_inbox_create_sends_name_and_senders_and_refuses_an_unknown_one(api, client):
    create = api.post("/v1/inboxes").respond(json=INBOX)
    inbox = nc.Inbox.create(local_part="help", name="support", agent="agt_1", senders="users")
    assert body(create.calls.last.request) == {"name": "support", "local_part": "help", "agent_id": "agt_1",
                                               "senders": "users"}
    assert (inbox.name, inbox.senders) == ("support", "anyone")
    with pytest.raises(ValueError, match="senders"):
        nc.Inbox.create(senders="everyone")
    assert create.call_count == 1


def test_inbox_from_name_converges_agent_and_senders(api, client):
    lookup = api.get("/v1/inboxes").respond(json=listing({**INBOX, "name": "other", "id": "inb_0"}, INBOX))
    patch = api.patch("/v1/inboxes/inb_1").respond(json={**INBOX, "agent_id": None, "senders": "owner"})
    inbox = nc.Inbox.from_name("support", create_if_missing=True, local_part="help", agent=None, senders="owner")
    assert lookup.call_count == 0  # lazy
    assert inbox.agent_id is None
    assert lookup.calls.last.request.url.params["name"] == "support"
    assert body(patch.calls.last.request) == {"agent_id": None, "senders": "owner"}


def test_inbox_from_name_creates_a_missing_one_adopts_a_race_and_says_when_none(api, client):
    api.get("/v1/inboxes").respond(json=listing())
    create = api.post("/v1/inboxes").respond(json=INBOX)
    inbox = nc.Inbox.from_name("support", create_if_missing=True, local_part="help", domain="acme.test", agent="agt_1")
    assert inbox.address == "help@acme.test"
    assert body(create.calls.last.request) == {"name": "support", "local_part": "help", "domain": "acme.test",
                                               "agent_id": "agt_1"}

    create.respond(409, json={"error": {"type": "conflict", "message": "Taken.", "existing_id": "inb_1"}})
    api.get("/v1/inboxes/inb_1").respond(json=INBOX)
    assert nc.Inbox.from_name("support", create_if_missing=True).id == "inb_1"
    with pytest.raises(nc.NotFound, match="No inbox is named 'gone'"):
        nc.Inbox.from_name("gone").hydrate()


def test_inbox_list_by_agent_and_messages_since_a_time(api, client):
    listed = api.get("/v1/inboxes").respond(json=listing(INBOX))
    [inbox] = nc.Inbox.list(agent="agt_1")
    assert listed.calls.last.request.url.params["agent_id"] == "agt_1"

    message = {"id": "msg_1", "inbox_id": "inb_1", "from": "ana@example.com", "subject": "Hi",
               "received_at": "2026-09-30T08:00:00Z", "conversation": "inbox:inb_1:thr_9",
               "agent_operation_id": "op_turn", "agent_error": None}
    messages = api.get("/v1/inboxes/inb_1/messages").respond(json=listing(message))
    midnight = datetime(2026, 9, 30, tzinfo=timezone.utc)
    [mail] = inbox.messages(since=midnight)
    assert messages.calls.last.request.url.params["since"] == "2026-09-30T00:00:00+00:00"
    assert (mail.conversation, mail.agent_error) == ("inbox:inb_1:thr_9", None)
    assert mail.agent_operation.id == "op_turn"
    with pytest.raises(ValueError, match="timezone-aware"):
        inbox.messages(since=datetime(2026, 9, 30))


def test_a_message_that_woke_no_one_says_why(api, client):
    api.get("/v1/inboxes/inb_1/messages").respond(json=listing(
        {"id": "msg_2", "inbox_id": "inb_1", "from": "spam@example.com", "subject": "Deal"}))
    full = api.get("/v1/inboxes/inb_1/messages/msg_2").respond(json={
        "id": "msg_2", "inbox_id": "inb_1", "from": "spam@example.com", "text": "Buy",
        "agent_operation_id": None, "agent_error": "The sender isn't one of your users."})
    [mail] = nc.Inbox.from_id("inb_1").messages()
    assert mail.agent_error == "The sender isn't one of your users."  # loads the full view
    assert mail.agent_operation is None
    assert full.call_count == 1


def test_wait_for_since_and_update_on_an_inbox_reached_by_name(api, client):
    api.get("/v1/inboxes").respond(json=listing(INBOX))
    wait = api.post("/v1/inboxes/inb_1/wait_for").respond(json=operation(op_id="op_w", kind="inbox.wait_for",
                                                                         status="running"))
    patch = api.patch("/v1/inboxes/inb_1").respond(json={**INBOX, "senders": "users"})
    inbox = nc.Inbox.from_name("support")
    started = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)
    inbox.wait_for(sender="noreply@github.com", since=started)
    assert body(wait.calls.last.request) == {"sender": "noreply@github.com", "since": "2026-09-30T12:00:00+00:00"}
    assert inbox.update(senders="users").senders == "users"
    assert body(patch.calls.last.request) == {"senders": "users"}


# --- phone numbers ---------------------------------------------------------------

def test_phone_from_name_buys_once_and_converges_recording(api, client):
    api.get("/v1/phone_numbers").respond(json=listing())
    buy = api.post("/v1/phone_numbers").respond(json=NUMBER)
    number = nc.PhoneNumber.from_name("front-desk", create_if_missing=True, area_code=415, max_monthly_usd=5)
    assert number.number == "+14155550123"
    assert body(buy.calls.last.request) == {"name": "front-desk", "area_code": "415", "max_monthly_usd": 5}
    with pytest.raises(ValueError, match="max_monthly_usd"):
        nc.PhoneNumber.from_name("front-desk", create_if_missing=True)

    api.get("/v1/phone_numbers").respond(json=listing(NUMBER))
    patch = api.patch("/v1/phone_numbers/pn_1").respond(json={**NUMBER, "record_calls": True})
    number = nc.PhoneNumber.from_name("front-desk", create_if_missing=True, max_monthly_usd=5, record_calls=True)
    assert number.record_calls is True
    assert body(patch.calls.last.request) == {"record_calls": True}
    assert buy.call_count == 1

    bought = api.post("/v1/phone_numbers").respond(json=NUMBER)
    nc.PhoneNumber.buy("+14155550123", max_monthly_usd=5, name="front-desk")
    assert body(bought.calls.last.request) == {"number": "+14155550123", "max_monthly_usd": 5, "name": "front-desk"}


def test_answer_with_transfer_texts_and_callers(api, client):
    answer = api.post("/v1/phone_numbers/pn_1/answer").respond(json={**NUMBER, "agent_id": "agt_1"})
    number = nc.PhoneNumber.from_id("pn_1")
    number.answer_with("agt_1", transfer_to=nc.Human(email="dana@example.com", phone="+14155550142"), texts=True,
                       callers="users")
    assert body(answer.calls.last.request) == {"agent_id": "agt_1", "transfer_to": "+14155550142", "texts": True,
                                               "callers": "users"}
    number.answer_with("agt_1", transfer_to="+14155550199")
    assert body(answer.calls.last.request) == {"agent_id": "agt_1", "transfer_to": "+14155550199"}
    number.answer_with("agt_1", callers="owner")   # only the number's own user gets through
    assert body(answer.calls.last.request) == {"agent_id": "agt_1", "callers": "owner"}
    with pytest.raises(ValueError, match="callers"):
        number.answer_with("agt_1", callers="friends")
    with pytest.raises(ValueError, match="with a phone"):
        number.answer_with("agt_1", transfer_to=nc.Human(email="dana@example.com"))
    assert answer.call_count == 3


def test_calls_both_ways_filtered_with_recordings(api, client):
    inbound = {"object": "phone_call", "id": "call_9", "direction": "inbound", "from": "+14155550100",
               "to": "+14155550123", "status": "completed", "transcript": [], "user_id": "user_42",
               "recording_url": "https://files.noclick.test/rec/call_9?sig=x"}
    history = api.get("/v1/phone_numbers/pn_1/calls").respond(json=listing(inbound))
    since = datetime(2026, 9, 23, tzinfo=timezone.utc)
    [call] = nc.PhoneNumber.from_id("pn_1").calls(direction="inbound", since=since, limit=50)
    params = history.calls.last.request.url.params
    assert (params["direction"], params["since"], params["limit"]) == ("inbound", "2026-09-23T00:00:00+00:00", "50")
    assert (call.direction, call.user_id, call.recording_url) == (
        "inbound", "user_42", "https://files.noclick.test/rec/call_9?sig=x")
    with pytest.raises(ValueError, match="direction"):
        nc.PhoneNumber.from_id("pn_1").calls(direction="sideways")


# --- numbers you bring --------------------------------------------------------------

PROVIDER = {"object": "connection", "id": "conn_7", "name": "phone-provider", "integration": "twilio",
            "credential_type": "twilio_account", "status": "connected", "user_id": None}
CONNECTED = {**NUMBER, "id": "pn_2", "source": "connected", "connection": "phone-provider", "monthly_usd": None}
PORTED = {**NUMBER, "id": "pn_3", "number": "+14155550188", "source": "ported", "monthly_usd": 1.5}


def test_connectable_lists_the_provider_accounts_numbers(api, client):
    api.get("/v1/connections/phone-provider").respond(json=PROVIDER)
    route = api.get("/v1/phone_numbers/connectable").respond(json=listing(
        {"number": "+14155550123", "label": "Front desk", "routed_elsewhere": True},
        {"number": "+14155550124", "label": "(415) 555-0124", "routed_elsewhere": False,
         "phone_number_id": "pn_2", "agent_id": "agt_1"},
    ))
    taken, free = nc.PhoneNumber.connectable(nc.Connection.from_name("phone-provider"))
    assert route.calls.last.request.url.params["connection"] == "conn_7"
    assert isinstance(taken, nc.ConnectableNumber) and str(taken) == "+14155550123"
    assert (taken.label, taken.routed_elsewhere, free.routed_elsewhere) == ("Front desk", True, False)
    assert (taken.phone_number_id, taken.agent_id) == (None, None)
    assert (free.phone_number_id, free.agent_id) == ("pn_2", "agt_1")  # already connected: one number, one agent
    nc.PhoneNumber.connectable("phone-provider", user="user_42")  # a name, in the user's own connections
    assert route.calls.last.request.url.params["connection"] == "phone-provider"
    assert route.calls.last.request.headers["NoClick-User"] == "user_42"
    with pytest.raises(TypeError, match="Connection or its name"):
        nc.PhoneNumber.connectable(42)


def test_connect_a_number_you_keep(api, client):
    connect = api.post("/v1/phone_numbers/connect").respond(json=CONNECTED)
    pick = nc.ConnectableNumber._from({"number": "+14155550123", "routed_elsewhere": True})
    with nc.as_user("user_42"):
        number = nc.PhoneNumber.connect(pick, connection="phone-provider", name="front-desk")
    request = connect.calls.last.request
    assert body(request) == {"number": "+14155550123", "connection": "phone-provider", "name": "front-desk"}
    assert request.headers["NoClick-User"] == "user_42"
    assert (number.source, number.connection, number.monthly_usd) == ("connected", "phone-provider", None)

    api.post("/v1/phone_numbers/connect").respond(status_code=409, json={"error": {
        "type": "conflict", "message": "+14155550123 is answered by the receptionist agent.", "existing_id": "pn_2"}})
    with pytest.raises(nc.Conflict) as err:
        nc.PhoneNumber.connect("+14155550123", connection="phone-provider")
    assert err.value.existing_id == "pn_2"  # one number, one agent


def test_from_name_connects_once(api, client):
    api.get("/v1/phone_numbers").respond(json=listing())
    api.get("/v1/connections/phone-provider").respond(json=PROVIDER)
    connect = api.post("/v1/phone_numbers/connect").respond(json={**CONNECTED, "record_calls": True})
    number = nc.PhoneNumber.from_name(
        "front-desk", create_if_missing=True, connect="+14155550123",
        connection=nc.Connection.from_name("phone-provider"), record_calls=True,
    )
    assert number.source == "connected"
    assert body(connect.calls.last.request) == {
        "name": "front-desk", "number": "+14155550123", "record_calls": True, "connection": "conn_7"}

    api.get("/v1/phone_numbers").respond(json=listing(CONNECTED))
    assert nc.PhoneNumber.from_name("front-desk", create_if_missing=True, connect="+14155550123",
                                    connection="phone-provider").id == "pn_2"
    assert connect.call_count == 1
    with pytest.raises(ValueError, match="needs connection="):
        nc.PhoneNumber.from_name("front-desk", create_if_missing=True, connect="+14155550123")
    with pytest.raises(ValueError, match="not both"):
        nc.PhoneNumber.from_name("front-desk", create_if_missing=True, connect="+14155550123",
                                 connection="phone-provider", max_monthly_usd=5)


def test_disconnect_hands_it_back_and_release_refuses_a_connected_number(api, client):
    disconnect = api.post("/v1/phone_numbers/pn_2/disconnect").respond(json=CONNECTED)
    number = nc.PhoneNumber.from_id("pn_2")
    number.disconnect()
    assert disconnect.call_count == 1 and number.released

    api.delete("/v1/phone_numbers/pn_2").respond(status_code=409, json={"error": {
        "type": "conflict", "message": "+14155550123 is your provider's number: disconnect it instead."}})
    with pytest.raises(nc.Conflict):
        nc.PhoneNumber.from_id("pn_2").release()


FERRY = {"street": "1 Ferry Building", "city": "San Francisco", "region": "CA", "postal_code": "94111"}


def test_port_in_waits_for_the_signature_then_the_carrier(api, client):
    start = api.post("/v1/phone_numbers/port_in").respond(json=operation(
        op_id="op_port", kind="phone.port_in", status="awaiting_human", number="+14155550188",
        sign_url="https://noclick.com/sign/loa_1", port_at=None, monthly_usd=1.5))
    port = nc.PhoneNumber.port_in(
        "+14155550188", account_holder="dana@harbordental.test", account_name="Harbor Dental LLC",
        service_address=FERRY, account_number="8812-4410-09", pin="4410",
        bill=b"%PDF-1.7", max_monthly_usd=5, name="front-desk",
        requested_at=datetime(2026, 10, 12, 9, tzinfo=timezone.utc),
    )
    assert body(start.calls.last.request) == {
        "numbers": ["+14155550188"], "max_monthly_usd": 5, "name": "front-desk",
        "account_holder": "dana@harbordental.test", "account_name": "Harbor Dental LLC",
        "service_address": FERRY, "account_number": "8812-4410-09",
        "pin": "4410", "bill": "JVBERi0xLjc=", "requested_at": "2026-10-12T09:00:00+00:00",
    }
    assert isinstance(port, nc.PortRequest) and isinstance(port, nc.Operation)
    assert (port.status, port.sign_url, port.number, port.monthly_usd) == (
        "awaiting_human", "https://noclick.com/sign/loa_1", "+14155550188", 1.5)

    api.get("/v1/operations/op_port").respond(json=operation(
        op_id="op_port", kind="phone.port_in", status="running", step="scheduled", number="+14155550188",
        sign_url="https://noclick.com/sign/loa_1", port_at="2026-10-14T13:00:00Z"))
    scheduled = nc.PortRequest.from_id("op_port").hydrate()
    assert (scheduled.step, scheduled.port_at.day, scheduled.sign_url) == ("scheduled", 14, None)
    api.get("/v1/operations/op_port/wait").respond(json=operation(
        op_id="op_port", kind="phone.port_in", status="succeeded", result={"phone_numbers": [PORTED]}))
    [number] = port.wait()
    assert isinstance(number, nc.PhoneNumber) and (number.source, number.number) == ("ported", "+14155550188")


def test_port_in_takes_several_numbers_on_one_letter_and_a_human_signer(api, client):
    start = api.post("/v1/phone_numbers/port_in").respond(json=operation(
        op_id="op_p2", kind="phone.port_in", status="awaiting_human", number="+14155550188",
        numbers=[{"number": "+14155550188", "status": "draft", "port_at": None},
                 {"number": "+14155550189", "status": "draft", "port_at": None}]))
    port = nc.PhoneNumber.port_in(
        ["+14155550188", "+14155550189"], account_holder=nc.Human(email="dana@harbordental.test", phone="+14155550142"),
        account_name="Harbor Dental LLC", service_address=FERRY, account_number="8812-4410-09",
        billing_number="+14155550100", remaining_numbers=["+14155550100"], max_monthly_usd=5,
    )
    sent = body(start.calls.last.request)
    assert sent["numbers"] == ["+14155550188", "+14155550189"] and sent["billing_number"] == "+14155550100"
    assert sent["remaining_numbers"] == ["+14155550100"]  # a partial port: the main number stays
    assert sent["account_holder"] == "dana@harbordental.test"  # the person signs; only their email goes
    assert [n["number"] for n in port.numbers] == ["+14155550188", "+14155550189"]
    with pytest.raises(ValueError, match="with an email"):
        nc.PhoneNumber.port_in("+14155550188", account_holder=nc.Human(phone="+14155550142"), account_name="x",
                               service_address=FERRY, account_number="1", max_monthly_usd=5)
    with pytest.raises(TypeError, match="account_holder"):
        nc.PhoneNumber.port_in("+14155550188", account_holder=42, account_name="x", service_address=FERRY,
                               account_number="1", max_monthly_usd=5)


def test_texting_registration_is_created_corrected_verified_and_deleted(api, client):
    view = {"object": "texting_registration", "id": "tr_1", "status": "pending", "brand_name": "Harbor Dental",
            "setup_usd": 32.5, "monthly_usd": 2.5, "fields": []}
    made = api.post("/v1/texting_registrations").respond(status_code=201, json=view)
    registration = nc.TextingRegistration.create(
        legal_name="Harbor Dental LLC", brand_name="Harbor Dental", entity_type="private_company",
        tax_id="12-3456789", industry="healthcare", website="https://harbordental.test", address=FERRY,
        contact={"name": "Dana Ruiz", "email": "dana@harbordental.test", "phone": "+14155550142"},
        privacy_url="https://harbordental.test/privacy", terms_url="https://harbordental.test/terms",
        max_setup_usd=40, max_monthly_usd=5,
    )
    sent = body(made.calls.last.request)
    assert (sent["entity_type"], sent["tax_id"], sent["address"]) == ("private_company", "12-3456789", FERRY)
    assert "stock" not in sent and (registration.status, registration.setup_usd) == ("pending", 32.5)
    api.get("/v1/texting_registrations/tr_1").respond(json={**view, "status": "rejected", "fields": ["tax_id"]})
    refused = nc.TextingRegistration.get("tr_1")
    assert (refused.status, refused.fields) == ("rejected", ["tax_id"])
    corrected = api.patch("/v1/texting_registrations/tr_1").respond(json={**view, "status": "pending"})
    assert refused.update(tax_id="98-7654321").status == "pending"
    assert body(corrected.calls.last.request) == {"tax_id": "98-7654321"}
    verified = api.post("/v1/texting_registrations/tr_1/verify").respond(json={**view, "status": "in_review"})
    assert refused.verify("482913").status == "in_review" and body(verified.calls.last.request) == {"code": "482913"}
    gone = api.delete("/v1/texting_registrations/tr_1").respond(json={"id": "tr_1", "deleted": True})
    refused.delete()
    assert gone.call_count == 1


def test_a_number_texts_lists_its_texts_and_opens_a_transfer_out(api, client):
    answer = api.post("/v1/phone_numbers/pn_1/answer").respond(json={"id": "pn_1", "texts": True})
    number = nc.PhoneNumber.from_id("pn_1").answer_with("ag_1", texts=True)
    assert body(answer.calls.last.request) == {"agent_id": "ag_1", "texts": True} and number.texts is True
    api.get("/v1/phone_numbers/pn_1/texts").respond(json=listing(
        {"object": "phone_text", "id": "tx_1", "direction": "inbound", "from": "+14155550100", "to": "+14155550123",
         "text": "STOP", "keyword": "stop", "status": "received", "segments": 1, "cost_usd": 0.005}))
    [text] = number.text_messages(direction="inbound")
    assert (text.from_number, text.keyword, str(text)) == ("+14155550100", "stop", "STOP")
    api.post("/v1/phone_numbers/pn_1/transfer_out").respond(json={
        "object": "transfer_out", "phone_number_id": "pn_1", "number": "+14155550123", "account_name": "NoClick Inc",
        "account_number": "4155550123", "billing_number": "+14155550123", "pin": "73019284",
        "service_address": "548 Market St, San Francisco, CA 94104", "expires_at": "2026-11-01T00:00:00Z"})
    details = number.transfer_out()
    assert (details.pin, details.account_number, details.billing_number, details.expires_at.month) == (
        "73019284", "4155550123", "+14155550123", 11)
    assert "73019284" not in repr(details)


def test_a_rejected_port_retries_with_corrections_and_a_live_one_cancels(api, client):
    api.get("/v1/operations/op_port/wait").respond(json=operation(
        op_id="op_port", kind="phone.port_in", status="failed", error={
            "type": "invalid_request", "message": "The account number doesn't match the carrier's records.",
            "field": "account_number"}))
    port = nc.PortRequest.from_id("op_port")
    with pytest.raises(nc.InvalidRequest) as err:
        port.wait()
    assert err.value.field == "account_number"
    retry = api.post("/v1/phone_numbers/port_in/op_port/retry").respond(json=operation(
        op_id="op_port2", kind="phone.port_in", status="running", step="submitted", number="+14155550188"))
    again = port.retry(account_number="8812-4410-07")
    assert body(retry.calls.last.request) == {"account_number": "8812-4410-07"}  # the rest is kept
    port.retry(remaining_numbers=[])
    assert body(retry.calls.last.request) == {"remaining_numbers": []}  # every number on the account moves
    assert isinstance(again, nc.PortRequest) and (again.id, again.step) == ("op_port2", "submitted")

    cancel = api.post("/v1/operations/op_port2/cancel").respond(json=operation(
        op_id="op_port2", kind="phone.port_in", status="canceled"))
    assert again.cancel().status == "canceled" and cancel.call_count == 1


def test_port_requests_list_typed_and_pinned_to_their_kind(api, client):
    rows = (
        operation(op_id="op_a", kind="phone.port_in", status="awaiting_human", number="+14155550188",
                  sign_url="https://noclick.com/sign/loa_1"),
        operation(op_id="op_b", kind="phone.port_in", status="running", step="scheduled", number="+14155550199",
                  port_at="2026-10-14T13:00:00Z"),
    )
    listed = api.get("/v1/operations").respond(json=listing(*rows))
    waiting, scheduled = nc.PortRequest.list(status="live", user_filter=nc.ALL_USERS)
    params = listed.calls.last.request.url.params
    assert (params["kind"], params["status"], params["user_id"]) == ("phone.port_in", "live", "all")
    assert isinstance(waiting, nc.PortRequest) and waiting.sign_url == "https://noclick.com/sign/loa_1"
    assert (scheduled.step, scheduled.port_at.day, scheduled.sign_url) == ("scheduled", 14, None)
    api.get("/v1/operations").respond(json=listing(*rows, next_cursor="c2"))
    page = nc.PortRequest.list_page(limit=2)
    assert [p.id for p in page.data] == ["op_a", "op_b"] and page.next_cursor == "c2"
    assert isinstance(page.data[0], nc.PortRequest)
    with pytest.raises(TypeError, match="reads only phone.port_in"):
        nc.PortRequest.list(kind="phone.call")


# --- channels --------------------------------------------------------------------

def test_channel_from_name_opens_with_members_and_schedules(api, client):
    api.get("/v1/channels").respond(json=listing({**CHANNEL, "status": "closed"}))
    create = api.post("/v1/channels").respond(json=CHANNEL)
    room = nc.Channel.from_name(
        "daily", create_if_missing=True, members=[nc.Agent.from_id("agt_1")], max_agent_turns=12,
        triggers=[nc.Cron("0 9 * * 1-5", message="@writer draft today's changelog")],
    )
    assert room.id == "ch_1"
    assert body(create.calls.last.request) == {
        "name": "daily", "max_agent_turns": 12, "members": [{"agent_id": "agt_1"}],
        "triggers": [{"kind": "cron", "cron": "0 9 * * 1-5", "tz": "UTC", "message": "@writer draft today's changelog"}],
    }


def test_channel_from_name_converges_settings_members_and_schedules(api, client):
    lookup = api.get("/v1/channels").respond(json=listing(CHANNEL))
    patch = api.patch("/v1/channels/ch_1").respond(json={**CHANNEL, "max_agent_turns": 20})
    removed = api.delete("/v1/channels/ch_1/members/m_2").respond(204)
    added = api.post("/v1/channels/ch_1/members").respond(json={"id": "m_3", "type": "agent", "agent_id": "agt_2"})
    api.get("/v1/channels/ch_1/triggers").respond(json=listing(_cron("tr_1", "0 8 * * *", "old"),
                                                               _cron("tr_2", "0 9 * * 1-5", "@writer go")))
    dropped = api.delete("/v1/channels/ch_1/triggers/tr_1").respond(204)
    new_trigger = api.post("/v1/channels/ch_1/triggers").respond(json=_cron("tr_3", "0 17 * * 5", "@writer wrap up"))
    reread = api.get("/v1/channels/ch_1").respond(json=CHANNEL)

    room = nc.Channel.from_name(
        "daily", create_if_missing=True, members=[nc.Agent.from_id("agt_1"), nc.Agent.from_id("agt_2")],
        max_agent_turns=20, budget_usd=None,
        triggers=[nc.Cron("0 9 * * 1-5", message="@writer go"), nc.Cron("0 17 * * 5", message="@writer wrap up")],
    )
    room.hydrate()
    assert lookup.calls.last.request.url.params["status"] == "open"
    assert body(patch.calls.last.request) == {"max_agent_turns": 20}  # budget_usd is already None
    assert (removed.call_count, body(added.calls.last.request)) == (1, {"agent_id": "agt_2"})
    assert dropped.call_count == 1
    assert body(new_trigger.calls.last.request) == {"kind": "cron", "cron": "0 17 * * 5", "tz": "UTC",
                                                    "message": "@writer wrap up"}
    assert reread.call_count == 1


def test_channel_from_name_none_puts_a_limit_back_to_its_default_and_lifts_the_budget(api, client):
    api.get("/v1/channels").respond(json=listing({**CHANNEL, "max_mention_hops": 3, "budget_usd": 5}))
    patch = api.patch("/v1/channels/ch_1").respond(json=CHANNEL)
    nc.Channel.from_name("daily", create_if_missing=True, max_agent_turns=None, max_mention_hops=None,
                         budget_usd=None).hydrate()
    assert body(patch.calls.last.request) == {"max_agent_turns": 20, "max_mention_hops": 8, "budget_usd": None}
    # Already at the defaults: nothing to change.
    api.get("/v1/channels").respond(json=listing({**CHANNEL, "max_agent_turns": 20, "max_mention_hops": 8}))
    nc.Channel.from_name("daily", create_if_missing=True, max_agent_turns=None, max_mention_hops=None).hydrate()
    assert patch.call_count == 1


def test_channel_triggers_add_list_and_remove(api, client):
    listed = api.get("/v1/channels/ch_1/triggers").respond(json=listing(_cron("tr_1", "0 9 * * 1-5", "@writer go")))
    add = api.post("/v1/channels/ch_1/triggers").respond(json=_cron("tr_2", "0 16 * * 5", "@writer wrap up"))
    delete = api.delete("/v1/channels/ch_1/triggers/tr_1").respond(204)
    room = nc.Channel.from_id("ch_1")
    [trigger] = room.triggers()
    assert (trigger.kind, trigger.spec["message"], trigger.next_run.hour) == ("cron", "@writer go", 9)
    added = room.add_trigger(nc.Cron("0 16 * * 5", message="@writer wrap up"))
    assert added.id == "tr_2" and body(add.calls.last.request)["message"] == "@writer wrap up"
    room.remove_trigger(nc.Cron("0 9 * * 1-5", message="@writer go"))
    assert delete.call_count == 1 and listed.call_count == 2
    with pytest.raises(nc.NotFound):
        room.remove_trigger(nc.Cron("0 1 * * *", message="nope"))
    with pytest.raises(ValueError, match="message"):
        room.add_trigger(nc.Cron("0 9 * * *"))
    with pytest.raises(TypeError, match="Cron"):
        room.add_trigger(nc.OnWebhook(name="orders"))


# --- apps ------------------------------------------------------------------------

def test_project_current_signs_in_with_the_deployment(api, client, monkeypatch):
    monkeypatch.delenv("NOCLICK_DEPLOYMENT_TOKEN", raising=False)
    with pytest.raises(nc.Unauthenticated, match="NOCLICK_DEPLOYMENT_TOKEN"):
        nc.Project.current()

    monkeypatch.setenv("NOCLICK_DEPLOYMENT_TOKEN", "nk_dep_123")
    monkeypatch.setenv("NOCLICK_API_URL", BASE)
    current = api.get("/v1/projects/current").respond(json=PROJECT)
    binding = api.get("/v1/projects/prj_1/bindings/DB").respond(json={
        "name": "DB", "kind": "database", "resource_id": "db_1", "resource_name": "booking-db"})
    app = nc.Project.current()
    db = app.database("DB")
    assert (app.name, db.id) == ("booking", "db_1")
    assert current.calls.last.request.headers["Authorization"] == "Bearer nk_dep_123"
    assert "NoClick-User" not in binding.calls.last.request.headers
    with pytest.raises(nc.InvalidRequest, match="bound to a database, not a queue"):
        app.queue("DB")


def test_every_bound_kind_resolves_to_its_object(api, client):
    for name, kind in [("FILES", "bucket"), ("SESSIONS", "dict"), ("JOBS", "queue"), ("CRM", "connection")]:
        api.get(f"/v1/projects/prj_1/bindings/{name}").respond(json={"name": name, "kind": kind, "resource_id": f"{kind}_1"})
    app = nc.Project.from_id("prj_1")
    assert isinstance(app.bucket("FILES"), nc.Bucket)
    assert isinstance(app.dict("SESSIONS"), nc.Dict)
    assert isinstance(app.queue("JOBS"), nc.Queue)
    crm = app.connection("CRM")
    assert isinstance(crm, nc.Connection) and crm._known("id") == "connection_1"


def test_verify_request_checks_the_schedule_signature(monkeypatch):
    app = nc.Project.from_id("prj_1")
    payload = b'{"schedule": "reminders"}'
    now = int(time.time())
    signature = hmac.new(b"whsec_app", f"{now}.".encode() + payload, hashlib.sha256).hexdigest()
    headers = {"noclick-signature": f"t={now},v1={signature}"}
    monkeypatch.delenv("NOCLICK_SIGNING_SECRET", raising=False)
    with pytest.raises(nc.Unauthenticated):
        app.verify_request(payload, headers)
    monkeypatch.setenv("NOCLICK_SIGNING_SECRET", "whsec_app")
    assert app.verify_request(payload, headers) is None
    with pytest.raises(nc.WebhookSignatureError):
        app.verify_request(b"{}", headers)
    with pytest.raises(nc.WebhookSignatureError):
        app.verify_request(payload, {"NoClick-Signature": f"t={now - 900},v1={signature}"})


def test_project_settings_read_back(api, client):
    put = api.put("/v1/projects/prj_1/settings/PUBLIC_BASE_URL").respond(204)
    api.get("/v1/projects/prj_1/settings").respond(json=listing({"name": "PUBLIC_BASE_URL", "value": "https://book.acme.com"}))
    delete = api.delete("/v1/projects/prj_1/settings/PUBLIC_BASE_URL").respond(204)
    app = nc.Project.from_id("prj_1")
    app.settings.set("PUBLIC_BASE_URL", "https://book.acme.com")
    assert body(put.calls.last.request) == {"value": "https://book.acme.com"}
    assert app.settings.list() == {"PUBLIC_BASE_URL": "https://book.acme.com"}
    app.settings.delete("PUBLIC_BASE_URL")
    assert delete.call_count == 1


def test_email_broadcast_is_named_and_reads_its_outcome(api, client):
    enable = api.post("/v1/projects/prj_1/email").respond(json={"status": "active", "postal_address": "1 Ferry Bldg",
                                                                "broadcast_daily_limit": 50000})
    setup = nc.Project.from_id("prj_1").email.enable(domain="mail.ana.acmebooking.com", postal_address="1 Ferry Bldg")
    assert body(enable.calls.last.request) == {"domain": "mail.ana.acmebooking.com", "postal_address": "1 Ferry Bldg"}
    assert (setup.postal_address, setup.broadcast_daily_limit) == ("1 Ferry Bldg", 50000)

    send = api.post("/v1/projects/prj_1/email/broadcasts").respond(json=operation(
        op_id="op_b", kind="project.email.broadcast", status="running"))
    api.get("/v1/operations/op_b/wait").respond(json=operation(
        op_id="op_b", kind="project.email.broadcast", status="succeeded",
        result={"id": "bc_1", "subject": "News", "sent": 2, "skipped": [{"to": "c@x.test", "reason": "unsubscribed"}]}))
    email = nc.Project.from_id("prj_1").email
    result = email.broadcast(["a@x.test", "b@x.test", "c@x.test"], "News", html="<p>Hi</p>",
                             idempotency_key="news-2026-10").wait()
    request = send.calls.last.request
    assert body(request) == {"to": ["a@x.test", "b@x.test", "c@x.test"], "subject": "News", "html": "<p>Hi</p>"}
    assert request.headers["Idempotency-Key"] == "news-2026-10"
    assert isinstance(result, nc.Broadcast) and (result.sent, result.skipped[0]["reason"]) == (2, "unsubscribed")
    with pytest.raises(TypeError, match="list of addresses"):
        email.broadcast("a@x.test", "News", text="Hi", idempotency_key="k")
    with pytest.raises(TypeError, match="text="):
        email.broadcast(["a@x.test"], "News", idempotency_key="k")


def test_payments_setup_names_its_processor_even_while_off(api, client):
    api.get("/v1/projects/prj_1/payments").respond(json={"mode": "off", "secrets": [], "processor": "acmepay"})
    setup = nc.Project.from_id("prj_1").payments.status()
    assert (setup.mode, setup.processor) == ("off", "acmepay")


def test_resubscribe_lifts_a_broadcast_unsubscribe(api, client):
    lift = api.post("/v1/projects/prj_1/email/resubscribe").mock(side_effect=[
        httpx.Response(200, json={"address": "ana@example.com", "resubscribed": True}),
        httpx.Response(200, json={"address": "bo@example.com", "resubscribed": False}),
    ])
    email = nc.Project.from_id("prj_1").email
    assert email.resubscribe("ana@example.com") is True
    assert body(lift.calls.last.request) == {"address": "ana@example.com"}
    assert email.resubscribe("bo@example.com") is False   # wasn't unsubscribed


# --- domains ---------------------------------------------------------------------

def test_domain_from_name_buys_once_and_converges_auto_renew(api, client):
    api.get("/v1/domains").respond(json=listing())
    buy = api.post("/v1/domains").respond(json={**operation(op_id="op_d", kind="domain.buy", status="running"),
                                                "domain_id": "dom_1"})
    api.get("/v1/domains/dom_1").respond(json={**DOMAIN, "status": "registering"})
    domain = nc.Domain.from_name("acmebooking.com", create_if_missing=True, max_price_usd=15)
    assert domain.status == "registering"
    assert body(buy.calls.last.request) == {"name": "acmebooking.com", "max_price_usd": 15}  # the TLD's minimum term
    with pytest.raises(ValueError, match="max_price_usd"):
        nc.Domain.from_name("acmebooking.com", create_if_missing=True)

    api.get("/v1/domains").respond(json=listing(DOMAIN))
    patch = api.patch("/v1/domains/dom_1").respond(json={**DOMAIN, "auto_renew": False})
    nc.Domain.from_name("acmebooking.com", create_if_missing=True, max_price_usd=15, auto_renew=False).hydrate()
    assert body(patch.calls.last.request) == {"auto_renew": False}
    assert buy.call_count == 1


def test_default_registrant_and_a_wildcard_connect(api, client):
    put = api.put("/v1/domains/registrant").respond(json={"name": "Dana Reyes", "email": "dana@acmebooking.test"})
    delete = api.delete("/v1/domains/registrant").respond(204)
    api.get("/v1/domains/registrant").respond(json={})
    saved = nc.Domain.set_default_registrant(CONTACT)
    assert body(put.calls.last.request)["postal_code"] == "94111" and saved.email == "dana@acmebooking.test"
    assert nc.Domain.set_default_registrant(None) is None and delete.call_count == 1
    assert nc.Domain.default_registrant() is None

    connect = api.post("/v1/domains/connect").respond(json={**DOMAIN, "source": "connected", "wildcard": True})
    assert nc.Domain.connect("apps.acme.test", wildcard=True).wildcard is True
    assert body(connect.calls.last.request) == {"name": "apps.acme.test", "wildcard": True}
    nc.Domain.connect("acme.test")
    assert body(connect.calls.last.request) == {"name": "acme.test"}


# --- brand and cards ---------------------------------------------------------------

def test_brand_serves_from_your_domain_with_your_oauth_apps(api, client):
    api.get("/v1/secrets").respond(json=listing({"object": "secret", "id": "sec_1", "name": "google-oauth-app"}))
    put = api.put("/v1/brand").respond(json={"name": "Acme", "domain": "connect.acme.com",
                                             "oauth_apps": {"google": "sec_1"}})
    brand = nc.Brand.set(name="Acme", domain="connect.acme.com", oauth_apps={"google": "google-oauth-app"})
    assert body(put.calls.last.request) == {"name": "Acme", "domain": "connect.acme.com",
                                            "oauth_apps": {"google": "sec_1"}}
    assert (brand.domain, brand.oauth_apps) == ("connect.acme.com", {"google": "sec_1"})


def test_single_use_cards(api, client):
    card_row = {"object": "card", "id": "card_1", "name": "Marketplace", "status": "active", "limit_usd": 500,
                "interval": "month", "single_use": True}
    create = api.post("/v1/cards").respond(json=card_row)
    card = nc.Card.create("Marketplace", limit_usd=500, single_use=True)
    assert body(create.calls.last.request) == {"name": "Marketplace", "limit_usd": 500, "interval": "month",
                                               "single_use": True}
    assert card.single_use is True

    api.get("/v1/cards").respond(json=listing(card_row))
    patch = api.patch("/v1/cards/card_1").mock(side_effect=lambda request: httpx.Response(200, json={
        **card_row, **body(request)}))
    card = nc.Card.from_name("Marketplace", create_if_missing=True, limit_usd=500, single_use=False)
    assert card.single_use is False and body(patch.calls.last.request) == {"single_use": False}
    nc.Card.from_name("Marketplace", create_if_missing=True, limit_usd=500).hydrate()  # left out: never changed
    assert patch.call_count == 1
