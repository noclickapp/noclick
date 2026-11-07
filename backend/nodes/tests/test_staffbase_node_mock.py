"""Actual native factory with fixture-only HTTP and public DNS results."""
import json
from copy import deepcopy

import httpx
import pytest
from unittest.mock import AsyncMock

from nodes import staffbase_node as db
from nodes.core.run_op import run_node_operation
from utils import ssrf

NODE = "automation-staffbase"
BASE = "https://fixture.staffbase.com/api"
TOKEN = "Zml4dHVyZTpzeW50aGV0aWMtbm90LWxpdmU="
AUTH = {"credential_type": db.TYPE, "api_base_url": BASE, "api_token": TOKEN}
USER = "00000000-0000-4000-8000-000000000001"


@pytest.fixture
def ensure_native_db_pool():
    yield


def resource(kind="user", identifier=None, *, parent=None):
    identifier = identifier or {"user": "u1", "group": "g1", "channel": "c1", "post": "n1", "page": "p1"}[kind]
    if kind == "user":
        return {"id": identifier, "status": "pending", "role": "reader", "email": "fixture@example.test", "createdAt": "2026-10-06T00:00:00Z", "profile": {"firstName": "Fixture", "lastName": "User"}, "secret": "must-not-escape", "config": {"locale": "en_US", "activationURL": "https://secret.example.test"}}
    if kind == "group":
        return {"id": identifier, "type": "internal", "config": {"localization": {"en_US": {"name": "Fixture Group", "description": "Before"}, "de_DE": {"name": "Gruppe", "description": "Unchanged"}}, "image": "https://secret.example.test"}, "adminIds": ["private-admin"]}
    if kind == "channel":
        return {"id": identifier, "config": {"localization": {"en_US": {"title": "Fixture Channel"}}}}
    contents = {"en_US": {"title": "Fixture Content", "content": "<p>Before</p>"}, "de_DE": {"title": "Inhalt", "content": "<p>Unchanged</p>"}}
    return {"id": identifier, "contents": contents, **({"channelID": parent or "c1", "planned": None, "published": None} if kind == "post" else {"spaceId": parent or "s1", "branchId": "b1", "publishedAt": None, "admins": {"tokenIds": ["must-not-escape"]}})}


def listing(kind="user", rows=None, *, following=None, total=None, limit=100, offset=0, members=False):
    rows = [resource(kind)] if rows is None else rows
    if kind in {"user", "group"}:
        out = {"entries": {"data": rows} if members else rows, "nextCursor": following, "prevCursor": None}
        if members: out["total"] = len(rows) if total is None else total
        return out
    out = {"data": rows, "limit": limit, "total": len(rows) if total is None else total}
    if kind == "post": out["offset"] = offset
    else: out["cursor"] = following
    return out


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))
    async def send(request):
        requests.append(request)
        assert request.url.host == "fixture.staffbase.com" and not request.url.userinfo
        assert request.headers["Authorization"] == "Basic " + TOKEN
        assert TOKEN not in str(request.url)
        code, payload, *extra = replies.pop(0)
        if isinstance(payload, bytes):
            return httpx.Response(code, content=payload, headers=extra[0] if extra else {"Content-Type": "application/json"})
        return httpx.Response(code, json=payload, headers=extra[0] if extra else {})
    native = ssrf.guarded_async_client
    monkeypatch.setattr(db, "guarded_async_client", lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(operation, arguments=None, auth=AUTH):
    return await run_node_operation(node_type=NODE, operation=operation, arguments=arguments or {}, credential_data=deepcopy(auth), user_id=USER)


CASES = [
    ("list_users", {}, [(200, listing())]),
    ("get_user", {"user_id": "u1"}, [(200, resource())]),
    ("create_user", {"email": "fixture@example.test"}, [(201, resource()), (200, resource())]),
    ("update_user", {"user_id": "u1", "first_name": "Changed"}, [(200, resource()), (200, {**resource(), "profile": {"firstName": "Changed", "lastName": "User"}}), (200, {**resource(), "profile": {"firstName": "Changed", "lastName": "User"}})]),
    ("delete_user", {"user_id": "u1"}, [(200, resource()), (204, b""), (404, {"message": "Not found"})]),
    ("list_groups", {}, [(200, listing("group"))]),
    ("get_group", {"group_id": "g1"}, [(200, resource("group"))]),
    ("create_group", {"name": "Fixture Group", "description": "Before"}, [(201, {**resource("group"), "config": {"localization": {"en_US": {"name": "Fixture Group", "description": "Before"}}}}), (200, {**resource("group"), "config": {"localization": {"en_US": {"name": "Fixture Group", "description": "Before"}}}})]),
    ("update_group", {"group_id": "g1", "name": "Changed"}, [(200, resource("group")), (200, {**resource("group"), "config": {"localization": {"en_US": {"name": "Changed", "description": "Before"}, "de_DE": {"name": "Gruppe", "description": "Unchanged"}}}}), (200, {**resource("group"), "config": {"localization": {"en_US": {"name": "Changed", "description": "Before"}, "de_DE": {"name": "Gruppe", "description": "Unchanged"}}}})]),
    ("delete_group", {"group_id": "g1"}, [(200, resource("group")), (204, b""), (404, {"message": "Not found"})]),
    ("list_group_members", {"group_id": "g1"}, [(200, resource("group")), (200, listing(members=True))]),
    ("list_channels", {}, [(200, listing("channel"))]),
    ("get_channel", {"channel_id": "c1"}, [(200, resource("channel"))]),
    ("list_posts", {"channel_id": "c1"}, [(200, resource("channel")), (200, listing("post"))]),
    ("get_post", {"channel_id": "c1", "post_id": "n1"}, [(200, resource("channel")), (200, resource("post"))]),
    ("create_draft_post", {"channel_id": "c1", "title": "Fixture Content", "content": "<p>Before</p>"}, [(200, resource("channel")), (201, {**resource("post"), "contents": {"en_US": resource("post")["contents"]["en_US"]}}), (200, {**resource("post"), "contents": {"en_US": resource("post")["contents"]["en_US"]}})]),
    ("update_draft_post", {"channel_id": "c1", "post_id": "n1", "title": "Fixture Content"}, [(200, resource("channel")), (200, resource("post")), (200, resource("post")), (200, resource("post"))]),
    ("delete_draft_post", {"channel_id": "c1", "post_id": "n1"}, [(200, resource("channel")), (200, resource("post")), (204, b""), (404, {"message": "Not found"})]),
    ("list_pages", {"space_id": "s1"}, [(200, listing("page"))]),
    ("get_page", {"space_id": "s1", "page_id": "p1"}, [(200, resource("page"))]),
    ("create_draft_page", {"space_id": "s1", "title": "Fixture Content", "content": "<p>Before</p>"}, [(200, {**resource("page"), "contents": {"en_US": resource("page")["contents"]["en_US"]}}), (200, {**resource("page"), "contents": {"en_US": resource("page")["contents"]["en_US"]}}), (200, listing("page")), (200, {**resource("page"), "contents": {"en_US": resource("page")["contents"]["en_US"]}})]),
    ("update_draft_page", {"space_id": "s1", "page_id": "p1", "title": "Fixture Content"}, [(200, listing("page")), (200, resource("page")), (200, resource("page")), (200, resource("page")), (200, listing("page")), (200, resource("page"))]),
    ("delete_draft_page", {"space_id": "s1", "page_id": "p1"}, [(200, listing("page")), (200, resource("page")), (204, b""), (404, {"message": "Not found"})]),
]


@pytest.mark.parametrize("operation,arguments,replies", CASES)
@pytest.mark.asyncio
async def test_all_native_operations_through_actual_factory(transport, operation, arguments, replies):
    requests, queue = transport
    queue.extend(deepcopy(replies))
    result = await run(operation, arguments)
    assert result["status"] == "success" and result["success"] is True and result["identity_verified"] is False
    assert queue == []
    wire = json.dumps(result)
    assert "must-not-escape" not in wire and "activationURL" not in wire and "private-admin" not in wire and "<p>" not in wire
    for request in requests:
        if request.method in {"POST", "PATCH", "PUT"}:
            body = json.loads(request.content)
            assert not (set(body) & {"readerIds", "adminIds", "notificationChannels", "secret", "recoveryCode"})
            if "/pages" in request.url.path:
                assert body["published"] is False and body["spaceId"] == "s1"
            if "/posts" in request.url.path:
                assert "published" not in body and "planned" not in body


@pytest.mark.asyncio
async def test_exact_current_media_and_once_encoded_basic_header(transport):
    requests, queue = transport
    queue.append((200, listing()))
    await run("list_users")
    assert requests[-1].headers["Accept"] == db.MEDIA["user_list"]
    assert requests[-1].url.params["includeProfile"] == "true"
    queue.extend([(201, resource()), (200, resource())])
    await run("create_user", {"email": "fixture@example.test"})
    creation = requests[-2]
    assert creation.headers["Accept"] == db.MEDIA["user"]
    assert creation.headers["Content-Type"] == db.MEDIA["user_create"]
    body = json.loads(creation.content)
    assert body["role"] == "reader" and body["status"] == "pending" and "sendMail" not in body
    queue.extend([(200, resource()), (200, resource()), (200, resource())])
    result = await run("update_user", {"user_id": "u1", "send_mail": True})
    assert requests[-2].headers["Content-Type"] == db.MEDIA["user_update"]
    assert json.loads(requests[-2].content) == {"sendMail": True}
    assert result["send_mail_requested"] is True and result["mail_delivery_verified"] is False


@pytest.mark.parametrize("tag", [None, "", 42, "cronofy_oauth", [], {}])
@pytest.mark.asyncio
async def test_raw_foreign_or_malformed_type_before_factory_transport(transport, tag):
    with pytest.raises((ValueError, TypeError)):
        await run("list_users", auth={**AUTH, "credential_type": tag})
    assert transport[0] == []


@pytest.mark.parametrize("bad", ["..", ".", "a/b", "a%2Fb", "https://foreign.test", "u1\n"])
@pytest.mark.asyncio
async def test_hostile_resource_ids_refused_before_http(transport, bad):
    with pytest.raises(ValueError):
        await run("get_user", {"user_id": bad})
    assert transport[0] == []


@pytest.mark.asyncio
async def test_signed_cursor_bound_to_token_tenant_search_and_parent(transport):
    requests, queue = transport
    queue.append((200, listing(rows=[resource()], following="next-opaque")))
    result = await run("list_users")
    token = result["next_page_token"]
    assert TOKEN not in token
    count = len(requests)
    for auth in [{**AUTH, "api_base_url": "https://another.staffbase.com/api"}, {**AUTH, "api_token": "YW5vdGhlcjpzeW50aGV0aWM="}]:
        with pytest.raises(ValueError):
            await run("list_users", {"page_token": token}, auth=auth)
    with pytest.raises(ValueError):
        await run("list_groups", {"page_token": token})
    assert len(requests) == count
    queue.append((200, listing(rows=[])))
    terminal = await run("list_users", {"page_token": token})
    assert terminal["next_page_token"] is None and requests[-1].url.params["cursor"] == "next-opaque"
    queue.extend([(200, resource("channel")), (200, listing("post", limit=1, total=2))])
    posts = await run("list_posts", {"channel_id": "c1", "page_size": 1})
    count = len(requests)
    with pytest.raises(ValueError):
        await run("list_posts", {"channel_id": "c2", "page_size": 1, "page_token": posts["next_page_token"]})
    assert len(requests) == count


@pytest.mark.asyncio
async def test_actual_bounded_lookup_finds_later_page_and_retains_scope(transport):
    requests, queue = transport
    queue.extend([(200, listing(rows=[resource("user", "u1")], following="later")), (200, listing(rows=[{**resource("user", "u2"), "profile": {"firstName": "Later"}}]))])
    result = await db.StaffbaseNode.load_field_options("user_id", AUTH, search="Later")
    assert [r["value"] for r in result["options"]] == ["u2"]
    assert requests[-1].url.params["cursor"] == "later"
    queue.extend([(200, resource("channel")), (200, listing("post", following=None))])
    result = await db.StaffbaseNode.load_field_options("post_id", AUTH, {"channel_id": "c1"})
    assert result["options"][0]["metadata"] == {"channelID": "c1"}


@pytest.mark.asyncio
async def test_lookup_20_request_bound_and_repeated_cursor_refusal(transport):
    requests, queue = transport
    queue.extend((200, listing(rows=[resource("user", "u" + str(i))], following="cursor" + str(i + 1))) for i in range(20))
    result = await db.StaffbaseNode.load_field_options("user_id", AUTH, search="absent")
    assert len(requests) == 20 and result["options"] == [] and result["next_page_token"]
    queue.extend([(200, listing(following="repeat")), (200, listing(rows=[resource("user", "u2")], following="repeat"))])
    with pytest.raises(ValueError):
        await db.StaffbaseNode.load_field_options("user_id", AUTH)


@pytest.mark.parametrize("kind,parent_field,operation", [("post", "channel_id", "get_post"), ("page", "space_id", "get_page")])
@pytest.mark.asyncio
async def test_parent_mismatch_cannot_emit_resource(transport, kind, parent_field, operation):
    if kind == "post": transport[1].append((200, resource("channel")))
    transport[1].append((200, resource(kind, parent="foreign")))
    with pytest.raises(ValueError):
        await run(operation, {parent_field: "c1" if kind == "post" else "s1", kind + "_id": "n1" if kind == "post" else "p1"})


@pytest.mark.parametrize("payload", [{"entries": [] , "nextCursor": ""}, {"entries": [], "nextCursor": "continuing"}, {"entries": [resource(), resource()]}])
@pytest.mark.asyncio
async def test_malformed_envelope_and_nonadvancing_cursor_fail(transport, payload):
    transport[1].append((200, payload))
    with pytest.raises(ValueError):
        await run("list_users")


@pytest.mark.parametrize("published,planned", [("2026-10-06T00:00:00Z", None), (None, "2026-10-07T00:00:00Z"), ("missing", "missing")])
@pytest.mark.asyncio
async def test_published_scheduled_and_unknown_news_refuse_before_write(transport, published, planned):
    post = resource("post")
    if published == "missing": post.pop("published")
    else: post["published"] = published
    if planned == "missing": post.pop("planned")
    else: post["planned"] = planned
    transport[1].extend([(200, resource("channel")), (200, post)])
    with pytest.raises(ValueError):
        await run("delete_draft_post", {"channel_id": "c1", "post_id": "n1"})
    assert all(r.method == "GET" for r in transport[0])


@pytest.mark.asyncio
async def test_draft_page_uses_explicit_filter_and_refuses_changed_publication(transport):
    transport[1].extend([(200, listing("page")), (200, {**resource("page"), "publishedAt": "2026-10-06T00:00:00Z"})])
    with pytest.raises(ValueError):
        await run("delete_draft_page", {"space_id": "s1", "page_id": "p1"})
    assert transport[0][0].url.params["status"] == "DRAFT" and transport[0][0].url.params["spaceIds"] == "s1"
    assert all(r.method == "GET" for r in transport[0])


@pytest.mark.asyncio
async def test_locale_update_preserves_other_locale_and_refuses_media_loss(transport):
    replies = next(r for op, _, r in CASES if op == "update_group")
    transport[1].extend(deepcopy(replies))
    await run("update_group", {"group_id": "g1", "name": "Changed"})
    patch = json.loads(transport[0][1].content)
    assert patch["config"]["localization"]["de_DE"] == {"name": "Gruppe", "description": "Unchanged"}
    post = resource("post")
    post["contents"]["en_US"]["image"] = {"original": {"url": "https://secret.example.test"}}
    transport[1].extend([(200, resource("channel")), (200, post)])
    count = len(transport[0])
    with pytest.raises(ValueError):
        await run("update_draft_post", {"channel_id": "c1", "post_id": "n1", "title": "Changed"})
    assert all(r.method == "GET" for r in transport[0][count:])


@pytest.mark.asyncio
async def test_write_ack_not_normalized_when_readback_fails_or_async(transport):
    transport[1].extend([(201, resource()), (200, {**resource(), "email": "different@example.test"})])
    result = await run("create_user", {"email": "fixture@example.test"})
    assert result["status"] == "unknown" and result["success"] is False and "written_id" not in result
    transport[1].append((202, {"id": "u2"}))
    result = await run("create_user", {"email": "fixture@example.test"})
    assert result["http_status"] == 202 and result["status"] == "unknown" and "written_id" not in result


@pytest.mark.parametrize("code,payload,headers", [(302, b"", {"Location": "https://foreign.test", "Content-Type": "text/plain"}), (200, b"login", {"Content-Type": "text/html"}), (429, {"message": "rate limited"}, {}), (200, {"error": "provider refused"}, {})])
@pytest.mark.asyncio
async def test_error_redirect_and_nonjson_do_not_pass(transport, code, payload, headers):
    transport[1].append((code, payload, headers))
    result = await run("list_users")
    assert result["success"] is False and result["identity_verified"] is False and len(transport[0]) == 1


@pytest.mark.asyncio
async def test_echoed_token_and_decoded_password_do_not_escape(transport):
    transport[1].append((401, {"message": "token " + TOKEN + " synthetic-not-live"}))
    result = await run("list_users")
    assert TOKEN not in json.dumps(result) and "synthetic-not-live" not in json.dumps(result)

@pytest.mark.parametrize("base", ["http://fixture.staffbase.com/api", "https://user:password@fixture.staffbase.com/api", "https://fixture.staffbase.com:8443/api", "https://fixture.staffbase.com/api?token=x", "https://fixture.staffbase.com/api/../users", "https://127.0.0.1/api"])
@pytest.mark.asyncio
async def test_invalid_tenant_roots_do_not_create_transport(transport, base):
    with pytest.raises((ValueError, TypeError)):
        await run("list_users", auth={**AUTH, "api_base_url": base})
    assert transport[0] == []


@pytest.mark.asyncio
async def test_oversize_response_and_incorrect_written_id_do_not_pass(transport):
    transport[1].append((200, b"x" * (2 * 1024 * 1024 + 1)))
    result = await run("list_users")
    assert result["success"] is False
    transport[1].extend([(200, resource()), (200, resource("user", "other"))])
    result = await run("update_user", {"user_id": "u1", "first_name": "Changed"})
    assert result["status"] == "unknown" and "written_id" not in result


@pytest.mark.asyncio
async def test_delete_acknowledgement_without_absence_is_unknown(transport):
    transport[1].extend([(200, resource("group")), (204, b""), (200, resource("group"))])
    result = await run("delete_group", {"group_id": "g1"})
    assert result["status"] == "unknown" and "deleted_id" not in result


@pytest.mark.asyncio
async def test_admin_user_deletion_refused_before_delete(transport):
    transport[1].append((200, {**resource(), "role": "admin"}))
    with pytest.raises(ValueError):
        await run("delete_user", {"user_id": "u1"})
    assert [r.method for r in transport[0]] == ["GET"]


@pytest.mark.asyncio
async def test_scoped_picker_tokens_do_not_cross_search_or_space(transport):
    transport[1].extend((200, listing("page", following="p-cursor-" + str(i), rows=[resource("page", "p" + str(i))])) for i in range(20))
    result = await db.StaffbaseNode.load_field_options("page_id", AUTH, {"space_id": "s1"}, search="absent")
    token = result["next_page_token"]
    count = len(transport[0])
    for parent, search in [("s2", "absent"), ("s1", "changed")]:
        with pytest.raises(ValueError):
            await db.StaffbaseNode.load_field_options("page_id", AUTH, {"space_id": parent}, search=search, page_token=token)
    assert len(transport[0]) == count


@pytest.mark.asyncio
async def test_closed_route_methods_refuse_undocumented_user_put(transport):
    with pytest.raises(ValueError):
        await db.Session(AUTH).request("PUT", "/users/u1", body={"profile": {}})
    assert transport[0] == []


@pytest.mark.parametrize("extra", [{"notificationChannels": ["push"]}, {"published": "now"}, {"api_token": "stale"}])
def test_unknown_operation_fields_are_refused(extra):
    with pytest.raises(ValueError, match="Staffbase configuration"):
        db.StaffbaseNode.parse_config({"config": {"operation": "update_draft_post", "channel_id": "c1", "post_id": "n1", "title": "Changed", **extra}, "credentials": AUTH})
