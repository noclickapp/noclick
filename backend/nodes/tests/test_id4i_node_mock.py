"""Exercise ID4i's real request builder and poll state with fixture-only HTTP."""
import base64
import hashlib
import hmac
import json
from copy import deepcopy
from unittest.mock import AsyncMock

import httpx
import pytest
from nodes import id4i_node as api

AUTH = {"credential_type": "id4i_api_key", "api_key": "e94b0006-d1d9-11e7-8941-cec278b6b50a",
        "api_secret": "synthetic-signing-secret", "organization_id": "de.acme"}
GUID = "3THvgrWxqgTFC4"
ROOT = "/api/v1"
PAGE = {"elements": [], "offset": 0, "limit": 100, "total": 0}


@pytest.fixture
def transport(monkeypatch):
    calls, replies = [], []
    native = httpx.AsyncClient
    def handle(request):
        calls.append(request)
        assert request.url.host == "backend.id4i.de"
        code, data = replies.pop(0)
        return httpx.Response(code, json=data) if data is not None else httpx.Response(code)
    monkeypatch.setattr(api.httpx, "AsyncClient", lambda **kw: native(**kw, transport=httpx.MockTransport(handle)))
    return calls, replies


def node(operation, **fields):
    config = {"config": {"operation": operation, **fields}, "credentials": deepcopy(AUTH)}
    return api.ID4iNode("fixture", "automation-id4i", config, config=api.ID4iNode.parse_config(config))


CASES = [
    ("get_organization", {}, "GET", "/organizations/de.acme", None, {"name": "ACME Inc.", "namespace": "de.acme"}),
    ("get_guid", {"id4n": GUID}, "GET", f"/guids/{GUID}", None, {"id4n": GUID}),
    ("create_guids", {"count": 2}, "POST", "/guids", {"organizationId": "de.acme", "count": 2, "length": 40}, {"id4ns": [GUID]}),
    ("update_guid", {"id4n": GUID, "physical_state": "ATTACHED"}, "PATCH", f"/guids/{GUID}", {"physicalState": "ATTACHED"}, {}),
    ("list_collections", {}, "GET", "/organizations/de.acme/collections", None, PAGE),
    ("get_collection", {"id4n": GUID}, "GET", f"/collections/{GUID}", None, {"id4n": GUID}),
    ("create_collection", {"collection_type": "LABELLED_COLLECTION", "label": "Products"}, "POST", "/collections", {"organizationId": "de.acme", "type": "LABELLED_COLLECTION", "length": 40, "label": "Products"}, {"id4n": GUID}),
    ("update_collection", {"id4n": GUID, "label": "Products"}, "PATCH", f"/collections/{GUID}", {"label": "Products"}, {}),
    ("delete_collection", {"id4n": GUID}, "DELETE", f"/collections/{GUID}", None, None),
    ("list_collection_elements", {"id4n": GUID}, "GET", f"/collections/{GUID}/elements", None, PAGE),
    ("add_collection_elements", {"id4n": GUID, "id4ns": [GUID]}, "POST", f"/collections/{GUID}/elements", {"id4ns": [GUID]}, None),
    ("remove_collection_elements", {"id4n": GUID, "id4ns": [GUID]}, "DELETE", f"/collections/{GUID}/elements", {"id4ns": [GUID]}, None),
    ("get_properties", {"id4n": GUID}, "GET", f"/id4ns/{GUID}/properties", None, {"de.acme.order": "1234"}),
    ("patch_properties", {"id4n": GUID, "properties": {"de.acme.order": "1234"}}, "PATCH", f"/id4ns/{GUID}/properties", {"de.acme.order": "1234"}, None),
    ("delete_properties", {"id4n": GUID, "properties": ["de.acme.order"]}, "DELETE", f"/id4ns/{GUID}/properties", ["de.acme.order"], None),
    ("search_guids", {"alias": "1234", "alias_type": "article"}, "GET", "/search/guids", None, PAGE),
    ("get_aliases", {"id4n": GUID}, "GET", f"/id4ns/{GUID}/alias", None, {"article": "1234"}),
    ("add_alias", {"id4n": GUID, "alias_type": "article", "alias": "1234"}, "POST", f"/id4ns/{GUID}/alias/article", {"alias": "1234"}, None),
    ("remove_alias", {"id4n": GUID, "alias_type": "article"}, "DELETE", f"/id4ns/{GUID}/alias/article", None, None),
    ("list_history", {"id4n": GUID}, "GET", f"/history/{GUID}", None, PAGE),
    ("add_history", {"id4n": GUID, "history_type": "DISPATCHED", "visibility": {"public": False}}, "POST", f"/history/{GUID}", {"organizationId": "de.acme", "type": "DISPATCHED", "visibility": {"public": False}}, None),
    ("get_history_item", {"id4n": GUID, "sequence_id": 9784}, "GET", f"/history/{GUID}/de.acme/9784", None, {"type": "DISPATCHED"}),
    ("list_changes", {}, "GET", "/changelog/organization/de.acme/", None, PAGE),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,fields,method,path,body,response", CASES)
async def test_native_request_contract(transport, operation, fields, method, path, body, response):
    calls, replies = transport
    replies.append((200, deepcopy(response)))
    result = await node(operation, **fields).execute({})
    assert result["status"] == "success" and len(calls) == 1
    request = calls[0]
    assert request.method == method and request.url.path == ROOT + path
    assert (json.loads(request.content) if request.content else None) == body
    assert AUTH["api_key"] not in str(request.url) and AUTH["api_secret"] not in str(request.url)
    if operation == "get_guid":
        assert request.url.params["organizationId"] == "de.acme"
    if operation == "list_changes":
        assert request.url.params["messageMimeType"] == "text/plain"


def test_documented_hs512_header_claims_and_raw_utf8_secret(monkeypatch):
    monkeypatch.setattr(api.time, "time", lambda: 1517232722)
    header, claims, signature = api._authorization(api.ID4iCredential(**AUTH))[7:].split(".")
    decode = lambda value: base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    assert json.loads(decode(header)) == {"alg": "HS512", "typ": "API"}
    assert json.loads(decode(claims)) == {"sub": AUTH["api_key"], "iat": 1517232722, "exp": 1517232842}
    assert decode(signature) == hmac.new(AUTH["api_secret"].encode(), f"{header}.{claims}".encode(), hashlib.sha512).digest()


@pytest.mark.asyncio
async def test_rejection_redacts_secret_and_jwt_without_retry(transport):
    calls, replies = transport
    token = api._authorization(api.ID4iCredential(**AUTH))
    replies.append((403, {"message": AUTH["api_secret"] + " " + token}))
    with pytest.raises(ValueError) as error:
        await node("get_organization").execute({})
    assert "403" in str(error.value) and AUTH["api_secret"] not in str(error.value)
    assert token[7:] not in str(error.value) and len(calls) == 1


@pytest.mark.parametrize("bad", ["..", "a/b", "a%2fb", "https://foreign.test", "id\n"])
def test_path_injection_refused(bad):
    with pytest.raises(ValueError):
        node("get_guid", id4n=bad)


@pytest.mark.asyncio
async def test_property_namespace_and_other_credential_refused(transport):
    with pytest.raises(ValueError, match="namespace"):
        await node("patch_properties", id4n=GUID, properties={"org.other": "x"}).execute({})
    with pytest.raises(ValueError):
        api.ID4iNode.parse_config({"config": {"operation": "get_organization"}, "credentials": {**AUTH, "credential_type": "other_api_key"}})
    assert not transport[0]


@pytest.mark.asyncio
async def test_offset_uses_actual_count_and_fails_on_empty_nonterminal_page(transport):
    _, replies = transport
    replies.append((200, {"elements": [{"id4n": GUID}], "offset": 4, "limit": 2, "total": 6}))
    assert (await node("list_collections", offset=4, limit=2).execute({}))["next_offset"] == 5
    replies.append((200, {"elements": [], "offset": 5, "limit": 2, "total": 6}))
    with pytest.raises(ValueError, match="advance"):
        await node("list_collections", offset=5, limit=2).execute({})


@pytest.mark.asyncio
async def test_accepted_read_is_not_a_poll_baseline(transport, monkeypatch):
    _, replies = transport
    instance = node("on_new_change")
    state = AsyncMock()
    monkeypatch.setattr(instance, "_filter_unseen", state)
    replies.append((202, None))
    with pytest.raises(ValueError, match="not returned"):
        await instance.execute({})
    state.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("history", [False, True])
async def test_poll_baselines_then_emits_once_with_human_event(transport, monkeypatch, history):
    # Values are the examples on the provider's ChangeLogEntry / HistoryItem schemas.
    operation = "on_new_history" if history else "on_new_change"
    instance = node(operation, **({"id4n": GUID} if history else {}))
    state = {}
    async def update(mutator, **kwargs):
        new, result = mutator(state)
        if new is not None:
            state.clear(); state.update(new)
        return result
    monkeypatch.setattr(instance, "_update_node_state", update)
    row = ({"organizationId": "org.acme", "type": "DISPATCHED", "timestamp": 1517232722, "sequenceId": 9784}
           if history else {"id": "e100123", "timestamp": 1517232722, "message": "User {{&user}} has changed the title of {{&object}}"})
    def page(rows):
        return (200, {**PAGE, "elements": deepcopy(rows), "total": len(rows)})
    calls, replies = transport
    replies.append(page([row]))
    assert (await instance.execute({}))["new_item_count"] == 0
    second = {**row, **({"sequenceId": 9785} if history else {"id": "e100124"})}
    replies.append(page([row, second]))
    result = await instance.execute({})
    assert result["new_item_count"] == 1
    assert "ID4i" in api.ID4iNode.resolve_agent_event(result)["text"]
    replies.append(page([row, second]))
    assert (await instance.execute({}))["new_item_count"] == 0
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_poll_later_page_error_never_consumes_items(transport, monkeypatch):
    instance = node("on_new_change", from_date="2018-01-01T00:00:00Z")
    store = AsyncMock(); monkeypatch.setattr(instance, "_filter_unseen", store)
    calls, replies = transport
    replies.extend([(200, {"elements": [{"id": "e100123"}], "offset": 0, "limit": 100, "total": 2}), (500, {"message": "Unavailable"})])
    with pytest.raises(ValueError):
        await instance.execute({})
    assert calls[1].url.params["offset"] == "1"
    assert calls[0].url.params["fromDate"] == "2018-01-01T00:00:00Z"
    store.assert_not_called()


@pytest.mark.asyncio
async def test_provider_authored_changelog_preserves_nullable_total_and_context(transport):
    from pathlib import Path
    payload = json.loads((Path(__file__).parent / "fixtures/id4i/changelog.json").read_text())
    transport[1].append((200, payload))
    result = await node("list_changes").execute({})
    assert result["data"] == payload and result["next_offset"] is None
    assert result["data"]["elements"][0]["messageProperties"]["newActiveState"] is True


@pytest.mark.asyncio
async def test_foreign_page_offset_refused_before_state_write(transport, monkeypatch):
    instance = node("on_new_change")
    state = AsyncMock(); monkeypatch.setattr(instance, "_filter_unseen", state)
    transport[1].append((200, {"elements": [{"id": "e4"}], "offset": 5, "limit": 100, "total": 6}))
    with pytest.raises(ValueError, match="offset"):
        await instance.execute({})
    state.assert_not_called()
