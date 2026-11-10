"""Provider-authored OpenAPI examples through the native node operation seam."""
import json
from pathlib import Path
from unittest.mock import AsyncMock
from urllib.parse import quote

import httpx
import pytest

from nodes import wikimedia_node as wm
from nodes.core.run_op import run_node_operation
from utils import ssrf

EXAMPLES = json.loads((Path(__file__).parent / "fixtures/wikimedia/contract_examples.json").read_text())
TOKEN = "fixture-wikimedia-access-token"
AUTH = {"credential_type": "wikimedia_access_token", "access_token": TOKEN}


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))

    async def send(request):
        requests.append(request)
        assert request.url.host == "www.wikidata.org"
        assert request.headers["Authorization"] == "Bearer " + TOKEN
        assert request.headers["User-Agent"].startswith("NoClick/")
        assert TOKEN not in str(request.url)
        status, body, headers = replies.pop(0)
        return httpx.Response(status, headers=headers, **({"content": b""} if status == 204 else {"json": body}))

    native = ssrf.guarded_async_client
    monkeypatch.setattr(wm, "guarded_async_client", lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(operation, arguments=None, auth=AUTH):
    return await run_node_operation(node_type="automation-wikimedia", operation=operation,
                                    arguments=arguments or {}, credential_data=auth,
                                    user_id="00000000-0000-4000-8000-000000000001")


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", EXAMPLES)
async def test_published_examples_match_wire_and_preserve_response(transport, operation):
    requests, replies = transport
    example = EXAMPLES[operation]
    replies.append((example["http_status"], example["response"], {"X-Authenticated-User": "Fixture editor", "ETag": '"1276705620"'}))
    result = await run(operation, example["config"])
    request = requests[0]
    assert len(requests) == 1 and not replies
    assert request.method == example["method"]
    values = {**example["config"], "item_id": example["config"].get("item_id", "Q24")}
    assert request.url.raw_path.split(b"?")[0].decode() == example["path"].format(**{key: quote(str(v), safe="") for key, v in values.items()})
    assert result["status"] == "success" and result["revision"] == '"1276705620"'
    if operation == "check_connection":
        assert result["authenticated_user"] == "Fixture editor" and "data" not in result
    else:
        assert result["data"] == example["response"]
    if operation.startswith("search_"):
        assert dict(request.url.params) == {key: str(example["config"][key]) for key in ("q", "language", "limit", "offset")}
    if operation == "get_item_statements":
        assert request.url.params["property"] == "P1628"
    if example["request_body"] is not None:
        body = json.loads(request.content)
        expected = example["request_body"]
        if operation == "create_item":
            expected = {**expected, "item": {k: expected["item"][k] for k in ("labels", "descriptions", "aliases")}, "tags": [], "bot": False}
        elif "statement" in expected:
            expected = {**expected, "statement": {"rank": "normal", "qualifiers": [], "references": [], **expected["statement"]}}
        assert body == expected
    else:
        assert not request.content


@pytest.mark.asyncio
async def test_connection_requires_authenticated_header(transport):
    transport[1].append((200, EXAMPLES["get_item"]["response"], {}))
    result = await run("check_connection")
    assert result["success"] is False and result["status"] == "unverified"
    assert "authenticated username" in result["message"]
    # The shared connect seam must treat an anonymous public read as unverified.
    from nodes.core.connection_evidence import _raise_if_error_envelope
    with pytest.raises(Exception, match="authenticated username"):
        _raise_if_error_envelope(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 404, 409, 412, 429, 500])
async def test_provider_failure_preserves_message_and_never_retries(transport, status):
    transport[1].append((status, {"code": "permission-denied", "message": "Denied for " + TOKEN}, {}))
    result = await run("get_item", {"item_id": "Q24"})
    assert result["success"] is False and result["http_status"] == status
    assert result["message"] == "Denied for [redacted]" and len(transport[0]) == 1
    from nodes.core.connection_evidence import _raise_if_error_envelope
    with pytest.raises(Exception, match=f"HTTP {status}"):
        _raise_if_error_envelope(result)


@pytest.mark.asyncio
async def test_edit_revision_and_metadata_are_sent_on_delete(transport):
    transport[1].append((204, None, {}))
    result = await run("delete_item_label", {"item_id": "Q24", "language_code": "en",
                                          "if_match": '"1276705620"', "comment": "Remove English label"})
    request = transport[0][0]
    assert result["data"] is None and request.headers["If-Match"] == '"1276705620"'
    assert json.loads(request.content) == {"comment": "Remove English label", "bot": False, "tags": []}


@pytest.mark.asyncio
@pytest.mark.parametrize("arguments", [{"item_id": "Q24/labels"}, {"item_id": "../Q24"}, {"item_id": "Q0"}])
async def test_item_path_injection_refused_before_transport(transport, arguments):
    with pytest.raises(ValueError):
        await run("get_item", arguments)
    assert not transport[0]


@pytest.mark.parametrize("url", ["http://www.wikidata.org", "https://editor:secret@www.wikidata.org", "https://www.wikidata.org:8443"])
def test_invalid_origins_refused(url):
    with pytest.raises(ValueError):
        wm.WikimediaAccessToken(access_token=TOKEN, wiki_url=url)


def test_credential_defaults_and_normalization():
    credential = wm.WikimediaAccessToken(access_token="  " + TOKEN + "\n", wiki_url="https://www.wikidata.org/wiki/Q24")
    assert credential.credential_type == "wikimedia_access_token" and credential.access_token == TOKEN
    assert credential.wiki_url == "https://www.wikidata.org"


def test_creation_does_not_offer_an_existing_revision_guard():
    assert "if_match" not in wm.CreateItem.model_fields
    with pytest.raises(ValueError):
        wm.CreateItem(labels={"en": "Jane Doe"}, if_match='"1276705620"')


@pytest.mark.parametrize("token", ["Bearer copied-token", "https://meta.wikimedia.org/token", "<token>", "abc\r\ndef", "nonascii-é"])
def test_invalid_tokens_refused(token):
    with pytest.raises(ValueError):
        wm.WikimediaAccessToken(access_token=token)


@pytest.mark.asyncio
async def test_search_explicit_next_page_is_forwarded(transport):
    transport[1].append((200, {"results": []}, {}))
    await run("search_items", {"q": "potato", "offset": 20, "limit": 20})
    assert dict(transport[0][0].url.params) == {"q": "potato", "language": "en", "offset": "20", "limit": "20"}


@pytest.mark.asyncio
async def test_redirect_is_not_followed(transport):
    transport[1].append((302, {}, {"Location": "https://foreign.example"}))
    result = await run("get_item", {"item_id": "Q24"})
    assert result["success"] is False and len(transport[0]) == 1
