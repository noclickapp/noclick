"""UNRUN actual native factory/HTTP/CRUD/envelope/continuation regressions."""
import json
from types import SimpleNamespace

import httpx
import pytest

from nodes import bloomerang_node as bm
from nodes.core.registry import NodeFactory
from nodes.core.run_op import run_node_operation

KEY = "synthetic-bloomerang-key-not-live"
CREDENTIAL = {"credential_type": bm.TYPE, "api_key": KEY}


@pytest.fixture
def ensure_native_db_pool():
    yield


def database(**extra):
    return {"Id": "fixture-database", "Name": "Fixture Organization", "Flavor": "Demo", "AccountingIntegration": "omit", **extra}


def user(**extra):
    return {"Id": 7, "Name": "Fixture User", "IsActive": True, "PermissionLevel": "Admin", "Email": "omit@example.invalid", **extra}


def constituent(**extra):
    return {"Id": 42, "AccountNumber": 9000, "Type": "Individual", "FullName": "Jane Doe", "FirstName": "Jane", "LastName": "Doe", "PrimaryEmail": {"Value": "omit@example.invalid"}, "GivingSummary": {"Amount": "omit"}, **extra}


def note(**extra):
    return {"Id": 43, "AccountId": 42, "Date": "2026-10-06", "Note": "Owned plain note", "AttachmentIds": [5], **extra}


def household(**extra):
    return {"Id": 44, "Type": "Household", **{k: "Fixture Household" for k in ("FullName", "SortName", "InformalName", "FormalName", "EnvelopeName", "RecognitionName")}, "HeadId": 45, "MemberIds": [45], **extra}


def page(rows, *, start=0, total=None, **extra):
    total = len(rows) if total is None else total
    return {"Total": total, "TotalFiltered": total, "Start": start, "ResultCount": len(rows), "Results": rows, **extra}


def binding():
    return [(200, database()), (200, user())]


@pytest.fixture
def http(monkeypatch):
    state = SimpleNamespace(replies=[], requests=[], clients=[])
    native = httpx.AsyncClient

    async def send(request):
        state.requests.append(request)
        assert request.url.host == "api.bloomerang.co" and request.url.path.startswith("/v2/")
        assert request.headers["X-API-KEY"] == KEY and "authorization" not in request.headers
        code, payload = state.replies.pop(0)
        return httpx.Response(code, json=payload) if isinstance(payload, (dict, list)) else httpx.Response(code, content=payload)

    def client(**kwargs):
        assert kwargs["verify"] is True and kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        state.clients.append(kwargs)
        return native(**kwargs, transport=httpx.MockTransport(send))

    monkeypatch.setattr(bm, "httpx", SimpleNamespace(AsyncClient=client, Timeout=httpx.Timeout, HTTPError=httpx.HTTPError))
    return state


async def run(operation, **arguments):
    return await run_node_operation(node_type="automation-bloomerang", operation=operation, arguments=arguments, user_id="fixture-user", credential_data=CREDENTIAL)


@pytest.mark.parametrize("tag", [None, "bloomerang_public_key", "slack_bot_token", "", 42, [], {}])
def test_actual_factory_refuses_original_foreign_or_null_tags(http, tag):
    with pytest.raises(ValueError):
        NodeFactory.create_node(node_id="fixture", node_type="automation-bloomerang", node_data={"config": {"operation": "check_connection"}, "credentials": {**CREDENTIAL, "credential_type": tag}}, user_id="fixture-user")
    assert http.requests == []


def test_tagless_external_blob_fails_but_actual_concrete_form_shapes_private_key(http):
    with pytest.raises(ValueError):
        bm.credential({"api_key": KEY})
    model = bm.BloomerangPrivateApiKeyCredential.model_validate({"api_key": KEY})
    assert model.model_dump(mode="json", exclude_unset=True) == CREDENTIAL
    assert KEY not in repr(model)


@pytest.mark.parametrize("key", ["", "bad value", "bad\r\nvalue", "é", "bad\x7fvalue"])
def test_invalid_header_fails_before_transport(http, key):
    with pytest.raises(ValueError):
        bm.credential({**CREDENTIAL, "api_key": key})
    assert http.requests == []


@pytest.mark.asyncio
async def test_actual_factory_current_identity_has_no_contact_or_financial_leak(http):
    http.replies = binding()
    result = await run("check_connection")
    assert result["identity_verified"] is True and result["data"][0]["Id"] == "7"
    assert [r.url.path for r in http.requests] == ["/v2/database", "/v2/user/current"]
    assert "Email" not in result["data"][0] and KEY not in str(result)
    http.replies = binding() + [(200, page([]))]
    assert (await run("list_constituents"))["data"] == []


@pytest.mark.parametrize("row", [user(Id=True), user(IsActive=False), user(Name=None), {"Results": [user()]}])
@pytest.mark.asyncio
async def test_invalid_direct_identity_never_uses_list_first_row(http, row):
    http.replies = [(200, database()), (200, row)]
    with pytest.raises(ValueError):
        await run("check_connection")


@pytest.mark.parametrize("status,payload", [(202, user()), (204, b""), (302, b"redirect"), (200, b"not json"), (200, {"Errors": ["do not expose " + KEY]})])
@pytest.mark.asyncio
async def test_read_status_and_error_body_do_not_become_identity(http, status, payload):
    http.replies = [(status, payload)]
    result = await run("check_connection")
    assert result["status"] == "error" and result["http_status"] == status and KEY not in str(result)
    assert len(http.requests) == 1


@pytest.mark.parametrize("changes", [{"ResultCount": True}, {"ResultCount": 2}, {"Start": 1}, {"TotalFiltered": 2, "Total": 1}, {"Results": {}}, {"Results": [], "ResultCount": 0, "TotalFiltered": 1, "Total": 1}])
@pytest.mark.asyncio
async def test_actual_lists_reject_contradictory_envelopes(http, changes):
    http.replies = binding() + [(200, page([constituent()], **changes))]
    with pytest.raises(ValueError):
        await run("list_constituents")


@pytest.mark.asyncio
async def test_api_id_not_account_number_and_offset_not_page_number(http):
    http.replies = binding() + [(200, page([constituent()], total=2))]
    result = await run("list_constituents", page_size=1)
    assert result["data"][0]["Id"] == "42" and "AccountNumber" not in result["data"][0]
    continuation = result["next_page_token"]
    http.replies = binding() + [(200, page([constituent(Id=46)], start=1, total=2))]
    assert (await run("list_constituents", page_size=1, page_token=continuation))["next_page_token"] is None
    assert http.requests[-1].url.params["skip"] == "1" and http.requests[-1].url.params["take"] == "1"
    http.replies = binding()
    with pytest.raises(ValueError):
        await run("list_constituents", page_size=1, constituent_type="Individual", page_token=continuation)


@pytest.mark.asyncio
async def test_note_parent_mismatch_is_refused_and_no_write_follows(http):
    http.replies = binding() + [(200, constituent()), (200, note(AccountId=99))]
    with pytest.raises(ValueError):
        await run("delete_note", constituent_id="42", note_id="43", expected_note="Owned plain note")
    assert all(r.method == "GET" for r in http.requests)


@pytest.mark.asyncio
async def test_actual_note_create_exact_body_and_readback(http):
    http.replies = binding() + [(200, constituent())] + binding() + [(200, note()), (200, note())] + binding()
    result = await run("create_note", constituent_id="42", note_date="2026-10-06", note="Owned plain note")
    assert result["readback_verified"] is True and result["data"]["Id"] == "43"
    request = next(r for r in http.requests if r.method == "POST")
    assert json.loads(request.content) == {"AccountId": 42, "Date": "2026-10-06", "Note": "Owned plain note"}
    assert "AttachmentIds" not in result["data"]


@pytest.mark.parametrize("status,payload", [(202, note()), (200, {"Id": True}), (200, {"success": True}), (200, note(AccountId=99)), (200, b"malformed")])
@pytest.mark.asyncio
async def test_unverified_created_id_or_async_write_is_unknown(http, status, payload):
    http.replies = binding() + [(200, constituent())] + binding() + [(status, payload)]
    result = await run("create_note", constituent_id="42", note_date="2026-10-06", note="Owned plain note")
    assert result["status"] == "unknown" and result["success"] is False and "data" not in result
    assert len([r for r in http.requests if r.method == "POST"]) == 1


@pytest.mark.asyncio
async def test_readback_error_after_acknowledged_write_remains_unknown(http):
    http.replies = binding() + [(200, constituent())] + binding() + [(200, note()), (200, {"Errors": ["rejected readback"]})]
    assert (await run("create_note", constituent_id="42", note_date="2026-10-06", note="Owned plain note"))["status"] == "unknown"


@pytest.mark.asyncio
async def test_household_create_returns_new_head_cleanup_id_without_existing_id_body(http):
    http.replies = binding() + binding() + [(200, household()), (200, household()), (200, constituent(Id=45, HouseholdId=44))] + binding()
    result = await run("create_household", full_name="Fixture Household", head_first_name="Jane", head_last_name="Doe")
    assert result["created_head_id"] == "45" and result["data"]["MemberIds"] == ["45"]
    body = json.loads(next(r for r in http.requests if r.method == "POST").content)
    assert body["Head"] == {"Type": "Individual", "FirstName": "Jane", "LastName": "Doe"} and "Id" not in body["Head"]
    assert len(body) == 7


@pytest.mark.parametrize("deleted,present", [(False, False), (True, True)])
@pytest.mark.asyncio
async def test_deletion_requires_ack_and_actual_absence(http, deleted, present):
    http.replies = binding() + [(200, constituent()), (200, note())] + binding() + [(200, {"Id": 43, "Type": "actual-provider-type", "Deleted": deleted})]
    if deleted:
        http.replies.append((200, note()) if present else (404, b""))
    result = await run("delete_note", constituent_id="42", note_id="43", expected_note="Owned plain note")
    assert result["status"] == "unknown"


@pytest.mark.asyncio
async def test_household_delete_keeps_members_and_only_deletes_household(http):
    http.replies = binding() + [(200, household())] + binding() + [(200, {"Id": 44, "Type": "actual-provider-type", "Deleted": True}), (404, b"")] + binding()
    result = await run("delete_household", household_id="44", expected_full_name="Fixture Household")
    assert result["members_preserved"] is True and result["absence_http_status"] == 404
    assert [r.url.path for r in http.requests if r.method == "DELETE"] == ["/v2/household/44"]


@pytest.mark.asyncio
async def test_database_switch_before_write_refuses_and_after_write_is_unknown(http):
    http.replies = binding() + [(200, constituent())] + [(200, database(Id="different"))]
    with pytest.raises(ValueError):
        await run("create_note", constituent_id="42", note_date="2026-10-06", note="Owned plain note")
    assert all(r.method == "GET" for r in http.requests)
    http.replies = binding() + [(200, constituent())] + binding() + [(200, note()), (200, note()), (200, database(Id="different"))]
    assert (await run("create_note", constituent_id="42", note_date="2026-10-06", note="Owned plain note"))["status"] == "unknown"


@pytest.mark.asyncio
async def test_provider_counts_are_not_fetched_row_counts(http):
    http.replies = binding() + [(200, page([constituent()], total=120, TotalFiltered=60))]
    result = await run("get_constituent_counts", constituent_type="Individual")
    assert result["data"] == {"Total": 120, "TotalFiltered": 60} and http.requests[-1].url.params["take"] == "1"


@pytest.mark.parametrize("change", ["key", "database", "user", "parent", "operation"])
def test_native_continuation_binds_actual_grant_and_parent(http, change):
    session = bm.Session(CREDENTIAL)
    session.database, session.user = bm._database(database()), bm._user(user(), active=True)
    operation = bm.ListNotes(constituent_id="42")
    token = bm._token(session, bm._scope(session, operation), 50)
    if change == "key": session.data["api_key"] = "different-key"
    if change == "database": session.database["Id"] = "different-database"
    if change == "user": session.user["Id"] = "8"
    if change == "parent": operation = bm.ListNotes(constituent_id="99")
    if change == "operation": operation = bm.ListInteractions(constituent_id="42")
    with pytest.raises(ValueError):
        bm._offset(session, bm._scope(session, operation), token)
    assert http.requests == []


@pytest.mark.asyncio
async def test_actual_search_stops_at_twenty_pages_and_keeps_continuation(http):
    http.replies = binding() + [(200, page([constituent(Id=i + 42, FullName="Other")], start=i, total=100)) for i in range(20)]
    result = await bm.BloomerangNode.load_field_options("constituent_id", CREDENTIAL, search="Missing")
    assert result["options"] == [] and result["next_page_token"]
    assert len(http.requests) == 22 and http.requests[-1].url.params["skip"] == "19"


@pytest.mark.asyncio
async def test_actual_search_rejects_repeated_ids_across_pages(http):
    http.replies = binding() + [(200, page([constituent()], total=2)), (200, page([constituent()], start=1, total=2))]
    with pytest.raises(ValueError):
        await bm.BloomerangNode.load_field_options("constituent_id", CREDENTIAL, search="Missing")


@pytest.mark.asyncio
async def test_nominal_identity_error_and_oversized_read_remain_errors(http):
    http.replies = [(200, b"x" * (2 * 1024 * 1024 + 1))]
    result = await run("check_connection")
    assert result["status"] == "error" and len(http.requests) == 1


@pytest.mark.parametrize("parent", ["../42", "042", "0", str(2**63), "42\n"])
def test_actual_child_factory_also_validates_inherited_parent_before_transport(http, parent):
    with pytest.raises(ValueError):
        NodeFactory.create_node(node_id="fixture", node_type="automation-bloomerang", node_data={"config": {"operation": "get_note", "constituent_id": parent, "note_id": "43"}, "credentials": CREDENTIAL}, user_id="fixture-user")
    assert http.requests == []
