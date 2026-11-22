"""Which of the app's popups your account's owner sees (``noclick.Popups``), and the numbers linked to your account
(``noclick.AccountPhones``): both the account's, never a user's, so neither sends ``NoClick-User`` inside
``as_user``."""

import pytest

import noclick as nc
from platform_helpers import body

POPUPS = {"run_results": True, "invite_banner": False, "publish_banner": True}
PHONES = {"object": "phones", "configured": True, "max_phones": 5, "phones": [
    {"phone": "+14155550123", "verified_at": "2026-10-02T09:00:00+00:00", "source": "verify"},
    {"phone": "+447700900123", "verified_at": "2026-11-11T09:00:00+00:00", "source": "whatsapp"},
]}


def test_popups_read_whether_each_shows(api, client):
    read = api.get("/v1/popups").respond(json={"object": "popups", "popups": POPUPS})
    with nc.as_user("user_42"):  # the owner's popups: never a user's
        shown = nc.Popups.get()
    assert shown.popups == POPUPS
    assert "NoClick-User" not in read.calls.last.request.headers


def test_popups_update_sends_only_the_ones_it_names(api, client):
    patch = api.patch("/v1/popups").respond(json={"object": "popups", "popups": {**POPUPS, "invite_banner": True}})
    shown = nc.Popups.update({"invite_banner": True})
    assert body(patch.calls.last.request) == {"popups": {"invite_banner": True}}
    assert "NoClick-User" not in patch.calls.last.request.headers
    assert shown.popups["invite_banner"] is True


def test_a_popup_the_app_doesnt_have_raises_invalid_request(api, client):
    api.patch("/v1/popups").respond(400, json={"error": {"type": "invalid_request", "message": "popups.tour: no"}})
    with pytest.raises(nc.InvalidRequest):
        nc.Popups.update({"tour": False})


def test_account_phones_read_the_linked_numbers(api, client):
    read = api.get("/v1/account/phones").respond(json=PHONES)
    with nc.as_user("user_42"):
        linked = nc.AccountPhones.get()
    assert (linked.configured, linked.max_phones) == (True, 5)
    assert [(p.phone, p.source, p.verified_at.isoformat()) for p in linked.phones] == [
        ("+14155550123", "verify", "2026-10-02T09:00:00+00:00"),
        ("+447700900123", "whatsapp", "2026-11-11T09:00:00+00:00"),
    ]
    assert "NoClick-User" not in read.calls.last.request.headers


def test_linking_texts_a_code_and_verify_links_the_number(api, client):
    start = api.post("/v1/account/phones").respond(201, json={
        "object": "phone_challenge", "id": "ch_1", "phone": "+14155550123", "expires_at": "2026-11-21T12:10:00+00:00"})
    check = api.post("/v1/account/phones/verify").respond(json={
        "object": "phone", "phone": "+14155550123", "verified_at": "2026-11-21T12:01:00+00:00", "source": "verify"})
    challenge = nc.AccountPhones.link("+1 415 555 0123")
    assert body(start.calls.last.request) == {"phone": "+1 415 555 0123"}
    assert (challenge.id, challenge.phone, challenge.expires_at.isoformat()) == (
        "ch_1", "+14155550123", "2026-11-21T12:10:00+00:00")
    phone = nc.AccountPhones.verify(challenge.id, "123456")
    assert body(check.calls.last.request) == {"challenge_id": "ch_1", "code": "123456"}
    assert (phone.phone, phone.source) == ("+14155550123", "verify")


def test_a_wrong_code_raises_invalid_request_naming_why(api, client):
    api.post("/v1/account/phones/verify").respond(400, json={"error": {
        "type": "invalid_request", "message": "That code isn't right", "reason": "invalid_code"}})
    with pytest.raises(nc.InvalidRequest) as refused:
        nc.AccountPhones.verify("ch_1", "000000")
    assert refused.value.details["reason"] == "invalid_code"


def test_unlink_names_the_number_in_the_path(api, client):
    removed = api.delete("/v1/account/phones/%2B14155550123").respond(
        json={"object": "phone", "phone": "+14155550123", "unlinked": True})
    nc.AccountPhones.unlink("+14155550123")
    assert removed.call_count == 1


def test_a_key_without_the_scope_raises_permission_denied(api, client):
    api.get("/v1/account/phones").respond(403, json={"error": {
        "type": "permission_denied", "message": "This key lacks the 'account:phones' scope"}})
    with pytest.raises(nc.PermissionDenied):
        nc.AccountPhones.get()
