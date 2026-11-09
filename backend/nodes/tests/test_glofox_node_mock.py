"""Native factory/transport/response/scope regressions. No live I/O."""
from types import SimpleNamespace

import httpx
import pytest

from nodes import glofox_node as gf
from nodes.core.registry import NodeFactory
from nodes.core.run_op import run_node_operation

BRANCH, MEMBER, CLASS, BOOKING = "b" * 24, "a" * 24, "c" * 24, "d" * 24
KEY, TOKEN = "synthetic-glofox-key-not-live", "synthetic-glofox-token-not-live"
CREDENTIAL = {"credential_type": gf.TYPE, "api_key": KEY, "api_token": TOKEN, "branch_id": BRANCH}


@pytest.fixture
def ensure_native_db_pool():
    yield


def branch():
    return {"_id": BRANCH, "name": "Fixture Studio", "namespace": "fixture", "address": {"city": "Fixture City", "country_code": "IE"}, "email": "omit@example.invalid", "website": "https://private.invalid/?token=" + TOKEN}


def member(**extra):
    return {"_id": MEMBER, "branch_id": BRANCH, "namespace": "fixture", "first_name": "Jane", "last_name": "Doe", "type": "member", "lead_status": "LEAD", "email": "jane@example.invalid", "access_barcode": "omit", "membership": {"payment": "omit"}, **extra}


def page(rows, *, size=50, number=1, total=None, more=False):
    return {"object": "list", "page": number, "limit": size, "total_count": len(rows) if total is None else total, "has_more": more, "data": rows}


@pytest.fixture
def http(monkeypatch):
    state = SimpleNamespace(replies=[], requests=[], clients=[])
    native = httpx.AsyncClient

    async def send(request):
        state.requests.append(request)
        assert request.url.host == "gf-api.aws.glofox.com" and request.url.path.startswith("/prod/2.")
        assert request.headers["x-api-key"] == KEY
        assert request.headers["x-glofox-api-token"] == TOKEN
        assert request.headers["x-glofox-branch-id"] == BRANCH
        status, payload = state.replies.pop(0)
        return httpx.Response(status, json=payload) if isinstance(payload, (dict, list)) else httpx.Response(status, content=payload)

    def client(**kwargs):
        assert kwargs["verify"] is True and kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        state.clients.append(kwargs)
        return native(**kwargs, transport=httpx.MockTransport(send))

    monkeypatch.setattr(gf, "httpx", SimpleNamespace(AsyncClient=client, Timeout=httpx.Timeout, HTTPError=httpx.HTTPError))
    return state


async def run(operation, **arguments):
    return await run_node_operation(node_type="automation-glofox", operation=operation, arguments=arguments, user_id="fixture-user", credential_data=CREDENTIAL)


@pytest.mark.parametrize("tag", [None, "slack_bot_token", "", 42, [], {}])
def test_actual_factory_refuses_original_foreign_malformed_or_null_tags(http, tag):
    with pytest.raises(ValueError):
        NodeFactory.create_node(node_id="fixture", node_type="automation-glofox", node_data={"config": {"operation": "check_connection"}, "credentials": {**CREDENTIAL, "credential_type": tag}}, user_id="fixture-user")
    assert http.requests == []


def test_tagless_raw_blob_refused_but_concrete_unsaved_form_shapes_the_tag(http):
    raw = {k: v for k, v in CREDENTIAL.items() if k != "credential_type"}
    with pytest.raises(ValueError):
        gf.credential(raw)
    shaped = gf.GlofoxApiKeyTokenCredential.model_validate(raw).model_dump(mode="json", exclude_unset=True)
    assert shaped == CREDENTIAL and KEY not in repr(gf.GlofoxApiKeyTokenCredential.model_validate(raw))


@pytest.mark.parametrize("key", ["", "bad\r\nvalue", "bad value", "é", "bad\x7fvalue"])
def test_invalid_header_rejected_before_transport(http, key):
    with pytest.raises(ValueError):
        gf.credential({**CREDENTIAL, "api_key": key})
    assert http.requests == []


@pytest.mark.asyncio
async def test_actual_factory_connection_is_branch_evidence_not_user_identity(http):
    http.replies = [(200, branch())]
    out = await run("check_connection")
    assert out["status"] == "success" and out["identity_verified"] is False
    assert out["data"][0]["name"] == "Fixture Studio" and "email" not in out["data"][0]
    assert KEY not in str(out) and TOKEN not in str(out)
    assert str(http.requests[0].url) == gf.BASE + "/2.0/branches/" + BRANCH


@pytest.mark.asyncio
async def test_member_get_verifies_real_branch_listing_before_global_legacy_get(http):
    http.replies = [(200, branch()), (200, page([member()], size=100)), (200, {"_id": MEMBER, "first_name": "Jane", "last_name": "Doe", "lead_status": "LEAD"})]
    out = await run("get_member", member_id=MEMBER)
    assert out["status"] == "success" and out["scope_proof"] == "connected_branch_member_listing"
    assert "branch_id" not in out["data"]  # Do not invent a legacy response field.
    assert http.requests[1].url.params["active"] == "any"
    assert "home_only" not in http.requests[1].url.params


@pytest.mark.asyncio
async def test_member_partial_update_has_expected_current_names_and_exact_readback(http):
    updated = member(last_name="Updated")
    http.replies = [(200, branch()), (200, page([member()], size=100)), (200, member()), (200, updated), (200, page([updated], size=100)), (200, updated)]
    out = await run("update_member", member_id=MEMBER, expected_first_name="Jane", expected_last_name="Doe", last_name="Updated")
    assert out["status"] == "success" and out["readback_verified"] is True
    writes = [request for request in http.requests if request.method != "GET"]
    assert len(writes) == 1 and writes[0].method == "PUT"
    assert writes[0].content == b'{"last_name":"Updated"}'
    assert "membership" not in out["data"] and "access_barcode" not in out["data"]


@pytest.mark.asyncio
async def test_mismatched_expected_name_refuses_update_before_write(http):
    http.replies = [(200, branch()), (200, page([member()], size=100)), (200, member())]
    with pytest.raises(ValueError):
        await run("update_member", member_id=MEMBER, expected_first_name="Wrong", expected_last_name="Doe", last_name="Updated")
    assert all(request.method == "GET" for request in http.requests)


@pytest.mark.parametrize("payload", [page([member(branch_id="e" * 24)]), page([member()], number=True), page([], total=1, more=True), page([], total=True), page([member(), member()])])
@pytest.mark.asyncio
async def test_wrong_parent_and_malformed_paging_refuse_success(http, payload):
    http.replies = [(200, branch()), (200, payload)]
    with pytest.raises(ValueError):
        await run("list_members")


@pytest.mark.asyncio
async def test_continuation_is_bound_to_api_token_branch_and_operation(http):
    http.replies = [(200, branch()), (200, page([member()], size=1, total=2, more=True))]
    first = await run("list_members", page_size=1)
    session = gf.Session(CREDENTIAL)
    session.branch = branch()
    scope = gf._scope_key(session, gf.ListMembers(page_size=1))
    assert gf._page(session, scope, first["next_page_token"]) == 2
    session.data["api_token"] = "different-token"
    with pytest.raises(ValueError):
        gf._page(session, gf._scope_key(session, gf.ListMembers(page_size=1)), first["next_page_token"])
    with pytest.raises(ValueError):
        gf._page(session, gf._scope_key(session, gf.ListBranchBookings(page_size=1)), first["next_page_token"])


@pytest.mark.asyncio
async def test_email_search_is_exact_single_object_and_no_contact_export(http):
    http.replies = [(200, branch()), (200, member())]
    out = await run("find_member_by_email", email="jane@example.invalid")
    assert out["data"]["_id"] == MEMBER and "email" not in out["data"]
    assert http.requests[-1].url.params["filters[email]"] == "jane@example.invalid"
    http.replies = [(200, branch()), (200, {"data": [member()]})]
    with pytest.raises(ValueError):
        await run("find_member_by_email", email="jane@example.invalid")


@pytest.mark.parametrize("status", [202, 204, 302, 401, 403, 429])
@pytest.mark.asyncio
async def test_read_http_refusal_never_becomes_proof(http, status):
    http.replies = [(status, b"provider text that must not leak " + KEY.encode())]
    out = await run("check_connection")
    assert out["status"] == "error" and out["http_status"] == status and KEY not in str(out)
    assert len(http.requests) == 1


@pytest.mark.asyncio
async def test_oversize_response_refused_and_nominal_200_error_not_proof(http):
    http.replies = [(200, b"x" * (2 * 1024 * 1024 + 1))]
    assert (await run("check_connection"))["status"] == "error"
    http.replies = [(200, {"success": False, "message": KEY})]
    assert (await run("check_connection"))["status"] == "error"


@pytest.mark.parametrize("body", [b"", b"Accepted", {"success": True}])
@pytest.mark.asyncio
async def test_note_200_acknowledgement_does_not_invent_created_id_or_cleanup(http, body):
    http.replies = [(200, branch()), (200, page([member()], size=100)), (200, member()), (200, body)]
    out = await run("add_note", member_id=MEMBER, description="Fixture note\nSecond line")
    assert out["status"] == "success" and out["acknowledged"] is True
    assert out["readback_verified"] is False and out["cleanup_supported"] is False and "note_id" not in out
    assert b'"type":"NOTE"' in http.requests[-1].content and b'"user_id"' in http.requests[-1].content


@pytest.mark.asyncio
async def test_note_pending_acknowledgement_is_unknown_and_never_retried(http):
    http.replies = [(200, branch()), (200, page([member()], size=100)), (200, member()), (202, b"pending")]
    out = await run("add_note", member_id=MEMBER, description="Fixture note")
    assert out["status"] == "unknown" and len([r for r in http.requests if r.method == "POST"]) == 1


@pytest.mark.asyncio
async def test_filtered_notes_keep_provider_interaction_totals_without_email_body(http):
    interaction = {"_id": BOOKING, "branch_id": BRANCH, "user_id": MEMBER, "type": "NOTE", "description": "A note", "created": 1}
    envelope = {"success": True, "meta": {"pagination": {"count": 2, "perPage": 50, "currentPage": 1}}, "data": [interaction, {**interaction, "_id": CLASS, "type": "MANUAL_EMAIL", "description": "Do not export email body"}]}
    http.replies = [(200, branch()), (200, page([member()], size=100)), (200, member()), (200, envelope)]
    out = await run("list_notes", member_id=MEMBER)
    assert len(out["data"]) == 1 and "Do not export email" not in str(out)
    assert out["pagination"]["total_scope"] == "all_interactions" and out["pagination"]["raw_count"] == 2


@pytest.mark.asyncio
async def test_branch_booking_times_remain_local_strings_and_finance_excluded(http):
    row = {"_id": BOOKING, "branch_id": BRANCH, "namespace": "fixture", "user_id": MEMBER, "status": "BOOKED", "time_start": "2026-10-06T10:00:00", "time_finish": "2026-10-06T11:00:00", "created": "2026-10-05T09:00:00Z", "paid": True, "payment_method": "omit"}
    http.replies = [(200, branch()), (200, {"success": True, "meta": {"totalCount": 1, "page": 1, "limit": 50}, "data": [row]})]
    out = await run("list_branch_bookings")
    assert out["data"][0]["time_start_local"] == row["time_start"]
    assert "paid" not in out["data"][0] and "payment_method" not in out["data"][0]


@pytest.mark.asyncio
async def test_class_type_scope_and_seconds_query_are_exact(http):
    row = {"_id": CLASS, "branch_id": BRANCH, "namespace": "fixture", "type": "event", "name": "Class", "time_start": 100, "image_url": "omit"}
    http.replies = [(200, branch()), (200, page([row]))]
    out = await run("list_classes", start_utc_seconds=100, end_utc_seconds=200)
    assert out["data"][0]["time_start"] == 100 and "image_url" not in out["data"][0]
    assert http.requests[-1].url.params["start"] == "100" and http.requests[-1].url.params["filter"] == "event"
    http.replies = [(200, branch()), (200, {**row, "type": "course"})]
    with pytest.raises(ValueError):
        await run("get_class", class_id=CLASS)


def test_redaction_covers_nested_values_and_keys():
    assert gf._redact({KEY: [TOKEN, {"x": KEY + TOKEN}]}, (KEY, TOKEN)) == {"[redacted]": ["[redacted]", {"x": "[redacted][redacted]"}]}
