import httpx
import pytest

import noclick as nc
from platform_helpers import USER_ID, body, listing, operation, trashed

INBOX = {"object": "inbox", "id": "inb_1", "address": "signup-7k2@in.noclick.app", "agent_id": None,
         "user_id": USER_ID, "created_at": "2026-09-25T10:00:00Z"}


def _mail(message_id, subject="Your code", **extra):
    return {"object": "inbox_message", "id": message_id, "inbox_id": "inb_1", "from": "noreply@github.com",
            "subject": subject, "received_at": "2026-09-25T10:00:00Z", **extra}


# --- inbox ------------------------------------------------------------------------

def test_create_with_an_agent_list_get_delete(api, client):
    api.get("/v1/agents").respond(json=listing({"object": "agent", "id": "agt_1", "name": "concierge", "user_id": "user_42"}))
    create = api.post("/v1/inboxes").respond(json={**INBOX, "agent_id": "agt_1"})
    listed = api.get("/v1/inboxes").respond(json=listing(INBOX))
    api.get("/v1/inboxes/inb_1").respond(json=INBOX)
    delete = api.delete("/v1/inboxes/inb_1").respond(json=trashed("inbox", "inb_1", "support"))

    with nc.as_user("user_42"):
        inbox = nc.Inbox.create(local_part="signup", agent=nc.Agent.from_name("concierge"))
        [first] = nc.Inbox.list(limit=5)
    assert body(create.calls.last.request) == {"local_part": "signup", "agent_id": "agt_1"}
    assert create.calls.last.request.headers["NoClick-User"] == "user_42"
    assert (inbox.address, inbox.agent_id) == ("signup-7k2@in.noclick.app", "agt_1")
    assert listed.calls.last.request.url.params["limit"] == "5"
    assert first == nc.Inbox.get("inb_1") and repr(first).startswith("Inbox(id='inb_1'")

    nc.Inbox.create()
    assert body(create.calls.last.request) == {}
    inbox.delete()
    assert delete.call_count == 1
    assert delete.calls.last.request.headers["NoClick-User"] == USER_ID  # the inbox's own user


def test_messages_long_poll_and_full_view_on_demand(api, client):
    route = api.get("/v1/inboxes/inb_1/messages").respond(json=listing(_mail("m1"), _mail("m2", text="inline")))
    full = api.get("/v1/inboxes/inb_1/messages/m1").respond(json=_mail(
        "m1", text="Your code is 481516", html=None, attachments=[{"filename": "a.pdf", "text": "invoice"}]))
    inbox = nc.Inbox.from_id("inb_1")
    m1, m2 = inbox.messages(after="m0", wait_s=10)
    params = route.calls.last.request.url.params
    assert (params["after"], params["wait_s"]) == ("m0", "10")
    assert (m1.sender, m1.subject, m1.received_at.hour) == ("noreply@github.com", "Your code", 10)
    assert full.call_count == 0
    assert m1.text == "Your code is 481516" and str(m1) == "Your code is 481516"  # loaded on first read
    assert m1.attachments == [{"filename": "a.pdf", "text": "invoice"}] and m1.html is None
    assert full.call_count == 1
    assert m2.text == "inline" and full.call_count == 1  # the listing already had it
    inbox.messages(after=m2)
    assert route.calls.last.request.url.params["after"] == "m2"

    one = inbox.message("m1")
    assert one.text == "Your code is 481516" and one.attachments[0]["filename"] == "a.pdf"


def test_a_messages_sender_says_where_it_comes_from(api, client):
    api.get("/v1/inboxes/inb_1/messages").respond(json=listing(
        _mail("m1", from_source="header", envelope_from="0100abc@send.mail.github.com", authenticated=True),
        _mail("m2", **{"from": "mallory@attacker.example"}, from_source="envelope",
              envelope_from="mallory@attacker.example", authenticated=False)))
    aligned, forged = nc.Inbox.from_id("inb_1").messages()
    assert (aligned.sender, aligned.sender_source, aligned.envelope_sender, aligned.authenticated) == (
        "noreply@github.com", "header", "0100abc@send.mail.github.com", True)
    assert (forged.sender, forged.sender_source, forged.envelope_sender, forged.authenticated) == (
        "mallory@attacker.example", "envelope", "mallory@attacker.example", False)


def test_reply_answers_the_sender(api, client):
    api.get("/v1/inboxes/inb_1/messages").respond(json=listing(_mail("m1", text="hi")))
    reply = api.post("/v1/inboxes/inb_1/messages/m1/reply").respond(json={
        "object": "inbox_reply", "id": "r1", "status": "sent", "delivery_status": "delivered"})
    [message] = nc.Inbox.from_id("inb_1", user=USER_ID).messages()
    sent = message.reply("Thanks!")
    assert body(reply.calls.last.request) == {"text": "Thanks!"}
    assert (sent.id, sent.status, sent.delivery_status) == ("r1", "sent", "delivered")
    assert reply.calls.last.request.headers["NoClick-User"] == USER_ID


def test_stream_yields_as_mail_arrives(api, client):
    polls = api.get("/v1/inboxes/inb_1/messages").mock(side_effect=[
        httpx.Response(200, json=listing(_mail("m1"))),
        httpx.Response(200, json=listing()),
        httpx.Response(200, json=listing(_mail("m2"))),
    ])
    stream = nc.Inbox.from_id("inb_1").stream(wait_s=5)
    assert [next(stream).id, next(stream).id] == ["m1", "m2"]
    stream.close()
    assert [c.request.url.params.get("after") for c in polls.calls] == [None, "m1", "m1"]


async def test_stream_aio(api, client):
    api.get("/v1/inboxes/inb_1/messages").respond(json=listing(_mail("m3")))
    async for message in nc.Inbox.from_id("inb_1").stream.aio(after="m2"):
        assert message.id == "m3"
        break


def test_wait_for_returns_the_matching_message(api, client):
    start = api.post("/v1/inboxes/inb_1/wait_for").respond(json=operation(op_id="op_w", kind="inbox.wait_for",
                                                                           status="running"))
    api.get("/v1/operations/op_w/wait").respond(json=operation(
        op_id="op_w", kind="inbox.wait_for", status="succeeded", result={"message": _mail("m9", text="Code: 1234")}))
    reply = api.post("/v1/inboxes/inb_1/messages/m9/reply").respond(json={"id": "r2"})
    op = nc.Inbox.from_id("inb_1").wait_for(sender="noreply@github.com", subject_contains="code", timeout_s=300)
    assert body(start.calls.last.request) == {
        "sender": "noreply@github.com", "subject_contains": "code", "timeout_s": 300}
    assert isinstance(op, nc.Operation)
    message = op.wait()
    assert isinstance(message, nc.InboxMessage) and message.text == "Code: 1234"
    message.reply("got it")
    assert reply.call_count == 1


def test_wait_for_is_typed_whatever_the_kind_is_called(api, client):
    api.post("/v1/inboxes/inb_1/wait_for").respond(json=operation(op_id="op_w", kind="inbox.message",
                                                                   status="running"))
    api.get("/v1/operations/op_w/wait").respond(json=operation(
        op_id="op_w", kind="inbox.message", status="succeeded", result={"message": {"id": "m9", "text": "x"}}))
    reply = api.post("/v1/inboxes/inb_1/messages/m9/reply").respond(json={"id": "r2"})
    message = nc.Inbox.from_id("inb_1").wait_for(sender="a@b.c").wait()
    assert message.text == "x"
    message.reply("ok")  # the inbox it came from is remembered
    assert reply.call_count == 1


def test_wait_for_expiring_raises_expired(api, client):
    api.post("/v1/inboxes/inb_1/wait_for").respond(json=operation(op_id="op_w", kind="inbox.wait_for",
                                                                   status="running"))
    api.get("/v1/operations/op_w/wait").respond(json=operation(
        op_id="op_w", kind="inbox.wait_for", status="expired",
        error={"type": "expired", "message": "No matching message arrived in 300s."}))
    with pytest.raises(nc.Expired, match="No matching message"):
        nc.Inbox.from_id("inb_1").wait_for(subject_contains="code").wait()


def test_from_id_operation_decodes_an_inbox_wait(api, client):
    api.get("/v1/operations/op_w/wait").respond(json=operation(
        op_id="op_w", kind="inbox.wait_for", status="succeeded", result={"message": _mail("m9", text="y")}))
    assert nc.Operation.from_id("op_w").wait().text == "y"


# --- phone numbers ----------------------------------------------------------------

NUMBER = {"object": "phone_number", "id": "pn_1", "number": "+14155550123", "agent_id": None,
          "monthly_usd": 1.5, "user_id": None, "created_at": "2026-09-25T10:00:00Z"}
TRANSCRIPT = [{"role": "assistant", "text": "Hi, calling to confirm Friday.", "at": 1.2},
              {"role": "user", "text": "Yes, see you then.", "at": 4.0}]
CALL = {"object": "phone_call", "id": "call_1", "phone_number_id": "pn_1", "direction": "outbound",
        "to": "+14155550100", "from": "+14155550123", "status": "completed", "goal": "Confirm Friday.",
        "agent_id": "agt_1", "call_sid": "CA1", "seconds": 42.0, "error": None, "transcript": TRANSCRIPT,
        "created_at": "2026-09-25T10:00:00Z", "ended_at": "2026-09-25T10:00:42Z"}
# What the call operation settles with at hang-up.
CALL_RESULT = {"object": "phone_call", "id": "call_1", "status": "completed", "to": "+14155550100",
               "call_sid": "CA1", "seconds": 42.0, "cost_usd": 0.21, "transcript": TRANSCRIPT}


AVAILABLE = {"number": "+14155550123", "country": "US", "type": "local", "monthly_usd": 1.5, "upfront_usd": 1.25,
             "locality": "San Francisco", "region": "CA", "capabilities": ["voice", "SMS"],
             "requirements": {"needs": "none", "items": []}, "texting": "registration"}


def test_search_buy_list_release(api, client):
    search = api.get("/v1/phone_numbers/available").respond(json=listing(AVAILABLE))
    buy = api.post("/v1/phone_numbers").respond(json=NUMBER)
    api.get("/v1/phone_numbers").respond(json=listing(NUMBER))
    release = api.delete("/v1/phone_numbers/pn_1").respond(json={"object": "phone_number", "id": "pn_1",
                                                                   "deleted": True})

    [pick] = nc.PhoneNumber.available(area_code=415, contains="555", limit=1)
    params = search.calls.last.request.url.params
    assert (params["area_code"], params["contains"], params["limit"]) == ("415", "555", "1")
    assert (str(pick), pick.locality, pick.monthly_usd, pick.upfront_usd) == ("+14155550123", "San Francisco", 1.5, 1.25)
    assert (pick.country, pick.type, pick.texting, pick.requirements["needs"]) == ("US", "local", "registration", "none")

    # The pick's own one-time price is the ceiling for it, unless the call names another.
    number = nc.PhoneNumber.buy(pick, max_monthly_usd=5)
    assert body(buy.calls.last.request) == {"number": "+14155550123", "country": "US", "type": "local",
                                            "max_monthly_usd": 5, "max_upfront_usd": 1.25}
    assert (number.number, str(number), number.monthly_usd) == ("+14155550123", "+14155550123", 1.5)
    nc.PhoneNumber.buy("+14155550999", max_monthly_usd=2)
    assert body(buy.calls.last.request)["number"] == "+14155550999"

    assert nc.PhoneNumber.list() == [number]
    number.release()
    assert release.call_count == 1 and number.released and number.number == "+14155550123"


def test_numbers_abroad_filters_coverage_places_and_an_address(api, client):
    search = api.get("/v1/phone_numbers/available").respond(json=listing({
        **AVAILABLE, "number": "+31612345678", "country": "NL", "type": "mobile", "monthly_usd": 2.5,
        "upfront_usd": 2.5, "texting": "unavailable",
        "requirements": {"needs": "address", "items": [{"kind": "address", "name": "Address anywhere",
                                                        "description": ""}]}}))
    api.get("/v1/phone_numbers/coverage").respond(json=listing(
        {"object": "phone_number_coverage", "country": "NL", "types": ["mobile"], "texting_types": [],
         "documents_types": []},
        {"object": "phone_number_coverage", "country": "IN", "types": ["local", "mobile"], "texting_types": [],
         "documents_types": ["local"], "steps_types": ["mobile"]}))
    places = api.get("/v1/phone_numbers/places").respond(json=listing(
        {"object": "phone_number_place", "kind": "locality", "value": "Amsterdam", "region": ""}))
    buy = api.post("/v1/phone_numbers").respond(json=NUMBER)

    covered, documents = nc.PhoneNumber.coverage()
    assert (covered.country, covered.types, covered.texting_types, covered.documents_types) == ("NL", ["mobile"], [], [])
    # India's local numbers are bought with documents; its mobile ones ask a step that can't be taken here.
    assert (documents.country, documents.documents_types, documents.steps_types) == ("IN", ["local"], ["mobile"])
    assert covered.steps_types == []
    [place] = nc.PhoneNumber.places("NL", type="mobile")
    assert (place.kind, place.value) == ("locality", "Amsterdam")
    assert dict(places.calls.last.request.url.params) == {"country": "NL", "type": "mobile"}
    [pick] = nc.PhoneNumber.available(country="NL", type="mobile", locality="Amsterdam", region="NH",
                                      starts_with="6", ends_with="78", features="voice_sms")
    params = search.calls.last.request.url.params
    assert [params[k] for k in ("country", "type", "locality", "region", "starts_with", "ends_with", "features")] == [
        "NL", "mobile", "Amsterdam", "NH", "6", "78", "voice_sms"]
    assert pick.requirements["needs"] == "address"
    nc.PhoneNumber.buy(pick, max_monthly_usd=3, max_upfront_usd=3, address=nc.NumberHolder(
        name="Dana Ruiz", street="Keizersgracht 1", city="Amsterdam", postal_code="1015 CJ", country="NL",
        phone="+31612345670"))
    assert body(buy.calls.last.request) == {
        "number": "+31612345678", "country": "NL", "type": "mobile", "max_monthly_usd": 3, "max_upfront_usd": 3,
        "address": {"name": "Dana Ruiz", "street": "Keizersgracht 1", "city": "Amsterdam", "postal_code": "1015 CJ",
                    "country": "NL", "phone": "+31612345670"}}


def test_a_holder_profile_is_filed_once_and_a_purchase_files_it(api, client):
    holder = {"name": "Dana Ruiz", "street": "Keizersgracht 1", "city": "Amsterdam", "postal_code": "1015 CJ",
              "country": "NL", "phone": "+31612345670"}
    profile = {"object": "phone_number_holder", "user_id": "user_42", "holder": holder,
               "requirements": {"req_type": "Passport"}, "accepted_at": "2026-11-20T09:30:00+00:00",
               "updated_at": "2026-11-20T09:31:00+00:00"}
    put = api.put("/v1/phone_numbers/holder").respond(json=profile)
    get = api.get("/v1/phone_numbers/holder").respond(json=profile)
    delete = api.delete("/v1/phone_numbers/holder").respond(204)
    buy = api.post("/v1/phone_numbers").respond(json=NUMBER)
    filed = nc.PhoneNumber.set_holder_profile(nc.NumberHolder(**holder), requirements={"req_type": "Passport"},
                                              accepted_at="2026-11-20T09:30:00Z", user="user_42")
    assert body(put.calls.last.request) == {"holder": holder, "requirements": {"req_type": "Passport"},
                                            "accepted_at": "2026-11-20T09:30:00Z"}
    assert put.calls.last.request.headers["NoClick-User"] == "user_42"
    assert (filed.holder.name, filed.requirements, filed.user_id) == ("Dana Ruiz", {"req_type": "Passport"}, "user_42")
    assert nc.PhoneNumber.holder_profile(user="user_42").accepted_at.year == 2026
    assert get.calls.last.request.headers["NoClick-User"] == "user_42"
    with pytest.raises(TypeError, match="accepted_at"):
        nc.PhoneNumber.set_holder_profile(nc.NumberHolder(**holder))
    nc.PhoneNumber.buy("+31612345678", country="NL", type="mobile", max_monthly_usd=3, holder_on_file=True)
    assert body(buy.calls.last.request) == {"number": "+31612345678", "country": "NL", "type": "mobile",
                                            "max_monthly_usd": 3, "holder_on_file": True}
    assert nc.PhoneNumber.set_holder_profile(None) is None and delete.call_count == 1


IDENTITY_TYPE = {"id": "req_type", "kind": "textual", "name": "Identity Document Type", "description": "",
                 "example": "Passport", "values": ["Identity card", "Driving license", "Passport", "Other"]}
IDENTITY = {"id": "req_doc", "kind": "document", "name": "Identity Document", "description": "", "example": "",
            "values": []}
DOCUMENT = {"object": "phone_number_document", "id": "doc_1", "requirement_id": "req_doc",
            "requirement_name": "Identity Document", "filename": "passport.pdf",
            "uploaded_at": "2026-10-10T12:00:00Z"}
ORDER = {"object": "phone_number_order", "id": "ord_1", "number": "+390212345678", "country": "IT", "type": "local",
         "status": "in_review", "reason": None, "deadline": None, "monthly_usd": 1.0, "upfront_usd": 1.0,
         "phone_number_id": None, "requirements": {"needs": "documents", "items": [IDENTITY_TYPE, IDENTITY]},
         "created_at": "2026-10-10T12:00:00Z", "updated_at": "2026-10-10T12:00:00Z"}


def test_a_number_with_documents_is_ordered_and_becomes_the_number_once_the_carrier_completes_it(api, client,
                                                                                                tmp_path):
    import base64

    upload = api.post("/v1/phone_numbers/documents").respond(201, json=DOCUMENT)
    buy = api.post("/v1/phone_numbers").respond(202, json=ORDER)
    passport = tmp_path / "passport.pdf"
    passport.write_bytes(b"%PDF-1.4 passport")

    document = nc.PhoneNumber.upload_document(passport, requirement=IDENTITY, country="IT")
    assert body(upload.calls.last.request) == {
        "country": "IT", "type": "local", "requirement_id": "req_doc", "filename": "passport.pdf",
        "file": base64.b64encode(b"%PDF-1.4 passport").decode()}
    assert (document.id, document.requirement_name, str(document)) == ("doc_1", "Identity Document", "doc_1")
    with pytest.raises(TypeError):  # bytes need a filename
        nc.PhoneNumber.upload_document(b"%PDF", requirement="req_doc", country="IT")
    nc.PhoneNumber.upload_document(b"%PDF", requirement="req_doc", country="IT", type="mobile",
                                   filename="scan.pdf")
    assert (body(upload.calls.last.request)["type"], body(upload.calls.last.request)["filename"]) == (
        "mobile", "scan.pdf")

    holder = nc.NumberHolder(name="Giulia Rossi", street="Via Roma 1", city="Milano", postal_code="20121",
                             country="IT", phone="+393471234567")
    order = nc.PhoneNumber.buy("+390212345678", country="IT", max_monthly_usd=5, max_upfront_usd=5, address=holder,
                               requirements={"req_type": "Passport", "req_doc": document})
    sent = body(buy.calls.last.request)
    assert sent["requirements"] == {"req_type": "Passport", "req_doc": "doc_1"}
    assert isinstance(order, nc.PhoneNumberOrder)
    assert (order.id, order.status, order.number, order.phone_number_id) == ("ord_1", "in_review", "+390212345678",
                                                                              None)
    with pytest.raises(nc.Conflict):  # not the account's until it completes
        order.phone_number()

    # The carrier sends it back; corrections are resubmitted on the same order.
    api.get("/v1/phone_numbers/orders/ord_1").respond(json={
        **ORDER, "status": "rejected", "reason": "Upload the photo page.", "deadline": "2026-10-24T00:00:00Z"})
    order.refresh()
    assert (order.status, order.reason, order.deadline.year) == ("rejected", "Upload the photo page.", 2026)
    resubmit = api.post("/v1/phone_numbers/orders/ord_1/resubmit").respond(json=ORDER)
    order.resubmit(address=holder, requirements={"req_type": "Passport", "req_doc": "doc_2"})
    assert body(resubmit.calls.last.request) == {
        "address": {"name": "Giulia Rossi", "street": "Via Roma 1", "city": "Milano", "postal_code": "20121",
                    "country": "IT", "phone": "+393471234567"},
        "requirements": {"req_type": "Passport", "req_doc": "doc_2"}}
    assert order.status == "in_review"

    # Once it completes, it's the number.
    api.get("/v1/phone_numbers/orders/ord_1").respond(json={**ORDER, "status": "completed", "requirements": None,
                                                            "phone_number_id": "pn_1"})
    api.get("/v1/phone_numbers/pn_1").respond(json=NUMBER)
    completed = nc.PhoneNumberOrder.retrieve("ord_1")
    number = completed.phone_number()
    assert isinstance(number, nc.PhoneNumber) and number.id == "pn_1"


def test_buy_needs_a_price_ceiling_and_reports_price_exceeded(api, client):
    with pytest.raises(TypeError):
        nc.PhoneNumber.buy("+14155550123")  # max_monthly_usd is required
    api.post("/v1/phone_numbers").respond(402, json={"error": {
        "type": "price_exceeded", "message": "This number costs $8.00/month.", "monthly_usd": 8.0}})
    with pytest.raises(nc.PriceExceeded) as info:
        nc.PhoneNumber.buy("+14155550123", max_monthly_usd=5)
    assert info.value.monthly_usd == 8.0


def test_outside_the_phone_feature_is_not_available(api, client):
    api.get("/v1/phone_numbers/available").respond(409, json={"error": {
        "type": "not_available", "message": "Phone numbers aren't enabled for this account."}})
    with pytest.raises(nc.NotAvailable):
        nc.PhoneNumber.available()


def test_answer_with_call_and_calls(api, client):
    api.get("/v1/phone_numbers/pn_1").respond(json=NUMBER)
    answer = api.post("/v1/phone_numbers/pn_1/answer").respond(json={**NUMBER, "agent_id": "agt_1"})
    place = api.post("/v1/phone_numbers/pn_1/calls").respond(json=operation(op_id="op_c", kind="phone.call",
                                                                            status="running"))
    api.get("/v1/operations/op_c/wait").respond(json=operation(
        op_id="op_c", kind="phone.call", status="succeeded", result=CALL_RESULT))
    history = api.get("/v1/phone_numbers/pn_1/calls").respond(json=listing(CALL, {**CALL, "id": "call_2",
                                                                                  "direction": "inbound"}))

    number = nc.PhoneNumber.get("pn_1")
    assert number.answer_with(nc.Agent.from_id("agt_1")) is number
    assert body(answer.calls.last.request) == {"agent_id": "agt_1"} and number.agent_id == "agt_1"

    op = number.call("+14155550100", goal="Confirm Friday.")
    assert body(place.calls.last.request) == {"to": "+14155550100", "goal": "Confirm Friday."}
    call = op.wait()
    assert isinstance(call, nc.PhoneCall)
    assert (call.id, call.status, call.seconds, call.cost_usd) == ("call_1", "completed", 42.0, 0.21)
    assert call.transcript == TRANSCRIPT
    assert str(call) == call.text == "assistant: Hi, calling to confirm Friday.\nuser: Yes, see you then."

    number.call(to="+14155550101", goal="Ask about the order.", agent="agt_2")
    assert body(place.calls.last.request)["agent_id"] == "agt_2"
    listed = number.calls()
    assert [c.direction for c in listed] == ["outbound", "inbound"]
    assert (listed[0].from_number, listed[0].ended_at.second) == ("+14155550123", 42)
    assert history.call_count == 1


def test_an_unanswered_call_settles_not_connected(api, client):
    api.post("/v1/phone_numbers/pn_1/calls").respond(json=operation(op_id="op_c", kind="phone.call",
                                                                   status="running"))
    api.get("/v1/operations/op_c/wait").respond(json=operation(
        op_id="op_c", kind="phone.call", status="succeeded",
        result={**CALL_RESULT, "status": "not_connected", "seconds": 0.0, "transcript": []}))
    call = nc.PhoneNumber.from_id("pn_1").call("+14155550100", goal="x").wait()
    assert (call.status, call.transcript, call.text) == ("not_connected", [], "")


LIVE = {**CALL, "status": "calling", "transcript": [], "seconds": None, "ended_at": None,
        "answered_at": "2026-09-25T10:00:09Z", "ended_by": None,
        "lines": [{"turn": 1, "who": "them", "text": "Hello?"}, {"turn": 1, "who": "agent", "text": "Hi, it's Ada."}]}


def test_a_call_is_read_live_and_hung_up_by_its_id_or_its_operation(api, client):
    place = api.post("/v1/phone_numbers/pn_1/calls").respond(json=operation(
        op_id="op_c", kind="phone.call", status="running", call_id="call_1", phone_number_id="pn_1"))
    read = api.get("/v1/phone_numbers/calls/call_1").respond(json=LIVE)
    hang_up = api.post("/v1/phone_numbers/calls/call_1/hang_up").respond(json=LIVE)

    op = nc.PhoneNumber.from_id("pn_1", user=USER_ID).call("+14155550100", goal="Confirm Friday.")
    call = nc.PhoneNumber.get_call(op)
    assert (call.status, call.answered_at.second, call.ended_by) == ("calling", 9, None)
    assert [(line["who"], line["text"]) for line in call.lines] == [("them", "Hello?"), ("agent", "Hi, it's Ada.")]
    # The operation's user goes with it, as the call it placed did.
    assert read.calls.last.request.headers["NoClick-User"] == USER_ID
    assert place.calls.last.request.headers["NoClick-User"] == USER_ID

    assert nc.PhoneNumber.hang_up(op).status == "calling"  # it ends a moment later, as any end does
    assert body(hang_up.calls.last.request) is None  # nothing but the call
    nc.PhoneNumber.hang_up("call_1", user=None)
    assert "NoClick-User" not in hang_up.calls.last.request.headers
    assert hang_up.call_count == 2

    ended = {**LIVE, "status": "completed", "ended_by": "hang_up", "transcript": TRANSCRIPT}
    read.respond(json=ended)
    assert nc.PhoneNumber.get_call("call_1").ended_by == "hang_up"
    api.get("/v1/operations/op_h").respond(json=operation(op_id="op_h"))
    with pytest.raises(TypeError):  # an operation that isn't a call
        nc.PhoneNumber.get_call(nc.Operation.from_id("op_h"))


def test_hanging_up_a_call_that_ended_is_a_conflict(api, client):
    api.post("/v1/phone_numbers/calls/call_1/hang_up").respond(409, json={"error": {
        "type": "conflict", "message": "The call already ended (completed).", "call_status": "completed"}})
    with pytest.raises(nc.Conflict):
        nc.PhoneNumber.hang_up("call_1")


def test_from_id_operation_decodes_a_call(api, client):
    api.get("/v1/operations/op_c/wait").respond(json=operation(
        op_id="op_c", kind="phone.call", status="succeeded", result=CALL_RESULT))
    assert isinstance(nc.Operation.from_id("op_c").wait(), nc.PhoneCall)


# --- sandbox background exec --------------------------------------------------------

def test_background_exec_is_an_operation(api, client):
    start = api.post("/v1/sandboxes/sb_1/exec").respond(json=operation(op_id="op_x", kind="sandbox.exec",
                                                                       status="running"))
    api.get("/v1/operations/op_x/wait").respond(json=operation(
        op_id="op_x", kind="sandbox.exec", status="succeeded", result={"stdout": "built\n", "stderr": "",
                                                                       "exit_code": 0}))
    sb = nc.Sandbox.from_id("sb_1", user=USER_ID)
    op = sb.exec(["make", "all"], background=True, timeout_s=1800)
    assert isinstance(op, nc.Operation)
    assert body(start.calls.last.request) == {"command": "make all", "background": True, "timeout_s": 1800}
    assert start.calls.last.request.headers["NoClick-User"] == USER_ID
    result = op.wait()
    assert isinstance(result, nc.ExecResult) and result.ok and result.stdout == "built\n"


def test_background_exec_non_zero_exit_is_still_a_result(api, client):
    api.post("/v1/sandboxes/sb_1/exec").respond(json=operation(op_id="op_x", kind="exec", status="running"))
    api.get("/v1/operations/op_x/wait").respond(json=operation(
        op_id="op_x", kind="exec", status="succeeded", result={"stdout": "", "stderr": "fail", "exit_code": 1}))
    result = nc.Sandbox.from_id("sb_1").exec("false", background=True).wait()
    assert (result.ok, result.stderr) == (False, "fail")


async def test_background_exec_aio(api, client):
    api.post("/v1/sandboxes/sb_1/exec").respond(json=operation(op_id="op_x", kind="sandbox.exec",
                                                               status="succeeded",
                                                               result={"stdout": "ok", "exit_code": 0}))
    op = await nc.Sandbox.from_id("sb_1").exec.aio("true", background=True)
    assert (await op.wait.aio()).stdout == "ok"
