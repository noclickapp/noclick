"""Native Workvivo contract regressions retain the real public guarded client.

Only DNS and HTTP transport are synthetic. Fixtures exercise exact tenant paging,
multipart full-state drafts, privacy projections and uncertain one-shot mutations.
"""
from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError
from nodes import workvivo_node as s
from utils import ssrf

CREDS = {"credential_type": s.FAMILY, "api_base": "https://api.us2.workvivo.com/v1",
    "workvivo_id": "1000001", "api_key": "fixture.workvivo.key"}
BASE = CREDS["api_base"]
SPACE = {"id": 15, "name": "Owned space", "visibility": "private"}
DRAFT = {"id": 31, "title": "Owned draft", "subtitle": "Preserved subtitle", "space_id": 15,
    "html_content": "<p>Old body</p>", "is_draft": True, "is_standalone": True,
    "is_sidebar_enabled": False, "featured_image": None, "language_variants": [],
    "external_id": None, "audience": {"is_global": False, "spaces": [{"id": 15}], "teams": []}}


@pytest.fixture
def ensure_native_db_pool():
    yield


def envelope(data, meta=None):
    return {"status": "success", "data": data, "meta": meta or {}}


def collection(rows, size=25, skip=0, next_url=None):
    return envelope(rows, {"pagination": {"take": size, "skip": skip, "next_page": next_url}})


@contextmanager
def transport(monkeypatch, replies):
    calls = []
    def answer(request):
        calls.append(request)
        assert request.url.host == "api.us2.workvivo.com"
        assert request.headers["authorization"] == "Bearer fixture.workvivo.key"
        assert request.headers["workvivo-id"] == "1000001"
        result = replies.pop(0)
        if isinstance(result, Exception):
            raise result
        return result
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["8.8.8.8"]))
    factory = ssrf.guarded_async_client
    monkeypatch.setattr(s, "guarded_async_client", lambda **kwargs: factory(**kwargs, transport=httpx.MockTransport(answer)))
    yield calls


def node(operation, **arguments):
    data = {"config": {"operation": operation, **arguments}, "credentials": CREDS}
    return s.WorkvivoNode("fixture", "automation-workvivo", data,
        config=s.WorkvivoNode.parse_config(data))


@pytest.mark.asyncio
async def test_short_page_follows_exact_link_and_keeps_tenant_filters(monkeypatch):
    href = BASE + "/spaces?take=25&skip=25&visibility=private"
    with transport(monkeypatch, [httpx.Response(200, json=collection([SPACE], next_url=href)),
        httpx.Response(200, json=collection([], skip=25))]) as calls:
        first = await node("list_spaces", visibility="private").execute({})
        assert first["next_page_url"] == href and first["snapshot_verified"] is False
        second = await node("list_spaces", visibility="private", next_page_url=href).execute({})
        assert second["items"] == [] and str(calls[1].url) == href


@pytest.mark.asyncio
@pytest.mark.parametrize("href", [
    "https://api.workvivo.com/v1/spaces?take=25&skip=25",
    BASE + "/users?take=25&skip=25", BASE + "/spaces?take=1000&skip=25",
    BASE + "/spaces?take=25&take=25&skip=25", BASE + "/spaces?take=25&skip=25&key=private",
    BASE + "/spaces?take=25&skip=-1", BASE + "/spaces?take=25&skip=25#fragment",
])
async def test_foreign_or_unbounded_continuation_precedes_http(monkeypatch, href):
    with transport(monkeypatch, []) as calls:
        assert (await node("list_spaces", next_page_url=href).execute({}))["status"] == "error"
        assert not calls


@pytest.mark.asyncio
async def test_scope_bound_page_picker_and_no_invented_page_get(monkeypatch):
    with transport(monkeypatch, [httpx.Response(200, json=collection([DRAFT])),
        httpx.Response(200, json=collection([DRAFT], size=100))]) as calls:
        options = await s.WorkvivoNode.load_field_options("page_id", CREDS, {"page_scope": "space", "space_id": "15"})
        assert options["options"] == [{"value": "31", "label": "Owned draft"}]
        result = await node("find_page", page_scope="space", space_id="15", page_id="31").execute({})
        assert result["record"]["id"] == "31"
        assert all(request.url.path == "/v1/pages" and request.method == "GET" for request in calls)


@pytest.mark.asyncio
async def test_missing_parent_and_foreign_membership_refuse(monkeypatch):
    with transport(monkeypatch, [httpx.Response(200, json=collection([{**DRAFT, "space_id": 99}]))]) as calls:
        with pytest.raises(ValueError):
            await s.WorkvivoNode.load_field_options("page_id", CREDS)
        with pytest.raises(s.WorkvivoError):
            await s.WorkvivoNode.load_field_options("page_id", CREDS, {"page_scope": "space", "space_id": "15"})
        assert len(calls) == 1


@pytest.mark.asyncio
async def test_draft_update_uses_multipart_full_put_preserves_optional_state(monkeypatch):
    changed = {**DRAFT, "title": "Changed"}
    with transport(monkeypatch, [httpx.Response(200, json=collection([DRAFT], size=100)),
        httpx.Response(200, json=envelope(changed))]) as calls:
        result = await node("update_draft_page", page_scope="space", space_id="15", page_id="31",
            title="Changed", confirm_draft_change=True).execute({})
        assert [request.method for request in calls] == ["GET", "PUT"]
        assert calls[1].url.path == "/v1/pages/31"
        assert calls[1].headers["content-type"].startswith("multipart/form-data; boundary=")
        body = calls[1].content.decode()
        for name, value in {"title": "Changed", "subtitle": "Preserved subtitle", "html_content": "<p>Old body</p>",
                "is_draft": "1", "is_standalone": "1", "is_sidebar_enabled": "0", "space_id": "15"}.items():
            assert 'name="' + name + '"\r\n\r\n' + value + '\r\n' in body
        assert "filename=" not in body
        assert result["readback_verified"] is False and result["notification_behavior_verified"] is False
        assert result["preflight_atomic"] is False and "html_content" not in result["record"]


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    {"is_draft": False}, {"external_id": 7001}, {"featured_image": {"url": "private"}},
    {"language_variants": [{"html_content": "private"}]}, {"is_standalone": "1"},
    {"parent_id": 11}, {"hide_title_and_subtitle": True},
    {"audience": {"is_global": False, "spaces": [{"id": 99}], "teams": []}},
])
async def test_unsupported_or_published_page_refuses_before_mutation(monkeypatch, change):
    with transport(monkeypatch, [httpx.Response(200, json=collection([{**DRAFT, **change}], size=100))]) as calls:
        result = await node("delete_draft_page", page_scope="space", space_id="15", page_id="31", confirm_draft_change=True).execute({})
        assert result["status"] == "error" and result["uncertain_outcome"] is False
        assert [request.method for request in calls] == ["GET"]


@pytest.mark.asyncio
async def test_scan_cap_does_not_invent_not_found_or_send_a_write(monkeypatch):
    href = BASE + "/pages?skip=100&take=100&space_id=15"
    with transport(monkeypatch, [httpx.Response(200, json=collection([{**DRAFT, "id": 32}], size=100, next_url=href))]) as calls:
        result = await node("update_draft_page", page_scope="space", space_id="15", page_id="31",
            title="Changed", max_scan_pages=1, confirm_draft_change=True).execute({})
        assert "scan limit" in result["error"].lower() and not result["uncertain_outcome"] and len(calls) == 1


@pytest.mark.asyncio
async def test_create_and_delete_acknowledgements_are_not_separate_readback(monkeypatch):
    created_row = {**DRAFT, "subtitle": "", "html_content": "<p>Draft</p>", "is_standalone": False}
    with transport(monkeypatch, [httpx.Response(200, json=envelope(SPACE)), httpx.Response(201, json=envelope(created_row)),
        httpx.Response(200, json=collection([DRAFT], size=100)),
        httpx.Response(200, json=envelope({"id": 31, "external_id": None}))]) as calls:
        created = await node("create_draft_page", page_scope="space", space_id="15", title="Owned draft",
            html_content="<p>Draft</p>", confirm_draft_change=True).execute({})
        deleted = await node("delete_draft_page", page_scope="space", space_id="15", page_id="31", confirm_draft_change=True).execute({})
        assert created["status"] == deleted["status"] == "success"
        assert created["readback_verified"] is deleted["readback_verified"] is False
        assert [request.method for request in calls] == ["GET", "POST", "GET", "DELETE"]
        assert calls[0].url.path == "/v1/spaces/15" and not calls[3].content


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", [httpx.Response(429), httpx.Response(503),
    httpx.Response(201, json={"status": "success", "data": {"id": 31}, "meta": {}}),
    httpx.ReadTimeout("synthetic interruption")])
async def test_uncertain_mutation_is_never_automatically_replayed(monkeypatch, reply):
    with transport(monkeypatch, [reply]) as calls:
        result = await node("create_draft_page", title="Owned", html_content="<p>Draft</p>", confirm_draft_change=True).execute({})
        assert result["status"] == "error" and result["uncertain_outcome"] is True and len(calls) == 1
        if isinstance(reply, httpx.Response):
            assert result["status_code"] == reply.status_code


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", [
    b'{"status":"success","data":[],"meta":{},"executed":false}',
    b'{"status":"success","data":[],"meta":{},"status":"error"}',
    b'{"status":"success","data":[],"meta":{},"opaque":NaN}',
    b'{"status":"success","data":[],"meta":{},"opaque":1e309}',
])
async def test_invalid_envelopes_and_nonfinite_json_are_unverified(monkeypatch, raw):
    with transport(monkeypatch, [httpx.Response(200, content=raw, headers={"Content-Type": "application/json"})]):
        result = await node("list_users").execute({})
        assert result["status"] == "error" and result["status_code"] == 200


@pytest.mark.asyncio
async def test_metadata_privacy_and_secret_redaction(monkeypatch):
    person = {"id": 9, "name": "Owned " + CREDS["api_key"], "email": "private@fixture.invalid",
        "mobile_phone": "private", "date_of_birth": "private", "avatar_url": "https://private.invalid"}
    with transport(monkeypatch, [httpx.Response(200, json=collection([person]))]):
        result = await node("list_users").execute({})
        assert result["items"] == [{"id": "9", "name": "Owned [redacted]"}]
        assert "private" not in str(result) and CREDS["api_key"] not in str(result)


@pytest.mark.parametrize("changes", [
    {"api_base": "http://api.workvivo.com/v1"}, {"api_base": "https://api.workvivo.com.evil.invalid/v1"},
    {"api_base": "https://127.0.0.1/v1"}, {"workvivo_id": "100\n001"}, {"api_key": "私密"},
])
def test_invalid_credentials_reject_before_client_construction(changes):
    with pytest.raises(ValidationError):
        s.WorkvivoAPIKeyCredential.model_validate({**CREDS, **changes})
    assert CREDS["api_key"] not in repr(s.WorkvivoAPIKeyCredential.model_validate(CREDS))


@pytest.mark.asyncio
async def test_omitted_state_is_not_absence_proof_for_draft_mutation(monkeypatch):
    row = deepcopy(DRAFT)
    del row["external_id"]
    with transport(monkeypatch, [httpx.Response(200, json=collection([row], size=100))]) as calls:
        result = await node("delete_draft_page", page_scope="space", space_id="15", page_id="31", confirm_draft_change=True).execute({})
        assert result["status"] == "error" and not result["uncertain_outcome"]
        assert len(calls) == 1 and calls[0].method == "GET"


@pytest.mark.asyncio
async def test_streamed_response_limit_is_enforced_before_metadata_parse(monkeypatch):
    with transport(monkeypatch, [httpx.Response(200, content=b" " * (s.MAX_BYTES + 1), headers={"Content-Type": "application/json"})]) as calls:
        result = await node("list_users").execute({})
        assert result["status"] == "error" and result["status_code"] == 200 and not result["uncertain_outcome"]
        assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,fixture", [
    ("list_spaces", "spaces-list"), ("list_articles", "articles-list"),
    ("find_page", "pages-list"), ("create_draft_page", "space-detail"),
    ("update_draft_page", "pages-list"), ("delete_draft_page", "pages-list"),
])
async def test_documented_examples_cannot_authorize_inconsistent_reads_or_draft_writes(monkeypatch, operation, fixture):
    """Keep the provider's examples exact, including their documented defects.

    Placeholder collections are not JSON envelopes. Page samples report take=10
    for a take=100 request (and describe a published page in a different space
    from the draft). The space-1 detail sample cannot prove space-15 access.
    """
    root = Path(__file__).parent / "fixtures" / "workvivo"
    example = json.loads((root / (fixture + ".json")).read_text())
    arguments = json.loads((root / "documented-inputs.json").read_text())[operation]["config"]
    with transport(monkeypatch, [httpx.Response(200, json=example["body"])]) as calls:
        result = await node(operation, **arguments).execute({})
    assert result["status"] == "error" and result["uncertain_outcome"] is False
    assert len(calls) == 1 and calls[0].method == "GET"
    if fixture == "pages-list":
        assert dict(calls[0].url.params)["take"] == "100"
        assert example["body"]["meta"]["pagination"]["take"] == 10
    if fixture == "space-detail":
        assert calls[0].url.path == "/v1/spaces/15"
        assert example["body"]["data"]["id"] == 1
