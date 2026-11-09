"""Exercise the native factory, wire formats, business errors and token hygiene.

All network responses are synthetic. Operations fixture lists the corresponding
published v0 operation IDs; conformance independently checks the pinned OpenAPI.
"""
import json
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import ValidationError

from nodes import just_one_api_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-joa-token+42"
OPERATIONS = json.loads(
    (Path(__file__).parent / "fixtures/just-one-api/operations.json").read_text()
)


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(
        node_id="joa-test",
        node_type="automation-just-one-api",
        node_data={
            "config": config,
            "credentials": {"credential_type": "just_one_api_token", "token": TOKEN},
        },
    )


def transport(monkeypatch, body, *, status=200, headers=None):
    requests = []

    def respond(request):
        requests.append(request)
        if isinstance(body, Exception):
            raise body
        if isinstance(body, bytes):
            return httpx.Response(status, content=body, headers=headers)
        return httpx.Response(status, json=body, headers=headers)

    def client(**kwargs):
        assert kwargs == {"timeout": 120, "follow_redirects": False, "trust_env": False}
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", OPERATIONS)
async def test_each_published_route_and_wire_format(monkeypatch, operation):
    fixture = OPERATIONS[operation]
    data = {"items": [{"id": "result"}], "nextCursor": "opaque-next", "has_more": 1}
    requests = transport(
        monkeypatch, {"code": 0, "message": "", "data": data, "recordTime": None}
    )
    result = await node(fixture["config"]).execute({})
    assert result["status"] == "success" and result["data"] == data
    assert len(requests) == 1
    request = requests[0]
    assert request.method == fixture["method"]
    assert request.url.scheme == "https" and request.url.host == "api.justoneapi.com"
    assert request.url.path == fixture["path"]
    expected = {
        wire: fixture["config"][name]
        for name, wire in fixture["fields"].items()
        if fixture["config"].get(name) is not None
        and (fixture["config"][name] != "" or fixture["mode"] == "form")
    }
    if fixture["mode"] == "form":
        assert dict(request.url.params) == {}
        assert request.headers["content-type"].startswith(
            "application/x-www-form-urlencoded"
        )
        assert parse_qs(request.content.decode(), keep_blank_values=True) == {
            key: [str(value)] for key, value in {"token": TOKEN, **expected}.items()
        }
    elif fixture["mode"] == "json":
        assert dict(request.url.params) == {"token": TOKEN}
        assert json.loads(request.content) == expected
        assert request.headers["content-type"] == "application/json"
    else:
        assert dict(request.url.params) == {
            "token": TOKEN,
            **{key: str(value) for key, value in expected.items()},
        }
        assert request.content == b""
    assert TOKEN not in str(result)


@pytest.mark.asyncio
async def test_explicit_pagination_and_boolean_filters(monkeypatch):
    requests = transport(
        monkeypatch, {"code": 0, "data": {"nextCursor": "next"}, "message": None}
    )
    result = await node(
        {
            "operation": "search_1688_products",
            "keyword": "coffee + café",
            "page": 2,
            "page_size": 10,
            "new_arrival": False,
            "free_shipping": True,
            "price_start": "1.50",
            "price_end": "9.00",
        }
    ).execute({})
    assert result["status"] == "success"
    assert dict(requests[0].url.params) == {
        "token": TOKEN,
        "keyword": "coffee + café",
        "page": "2",
        "pageSize": "10",
        "sort": "default",
        "newArrival": "false",
        "freeShipping": "true",
        "priceStart": "1.50",
        "priceEnd": "9.00",
    }
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_form_continuation_is_not_moved_to_query(monkeypatch):
    requests = transport(monkeypatch, {"code": 0, "data": [], "message": ""})
    await node(
        {
            "operation": "search_wechat_articles",
            "keyword": "咖啡 & tea",
            "current_page": 2,
            "offset": 10,
            "cookies_buffer": "a+b/c==",
        }
    ).execute({})
    fields = parse_qs(requests[0].content.decode())
    assert fields["keyword"] == ["咖啡 & tea"] and fields["cookies_buffer"] == ["a+b/c=="]
    assert not requests[0].url.query


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "code,status",
    [
        (100, 401),
        (600, 403),
        (302, 429),
        (303, 429),
        (301, 200),
        (601, 200),
        (602, 200),
    ],
)
async def test_business_failure_keeps_provider_message_and_never_succeeds(
    monkeypatch, code, status
):
    transport(
        monkeypatch,
        {"code": code, "message": "Provider refused token " + TOKEN, "data": None},
    )
    result = await node({"operation": "get_weibo_hot_search"}).execute({})
    assert result["status"] == "error" and result["status_code"] == status
    assert (
        result["code"] == code
        and result["error"] == "Provider refused token [redacted]"
    )
    assert TOKEN not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body,status,headers",
    [
        ({"code": 0, "data": {}}, 401, None),
        ({"code": 0, "data": {}}, 302, {"location": "https://example.com"}),
        (b"<html>no</html>", 200, {"content-type": "text/html"}),
        (b"no-json", 200, {"content-type": "application/json"}),
        ([], 200, None),
        ({"code": True, "data": {}}, 200, None),
        ({"code": 0}, 200, None),
    ],
)
async def test_http_redirect_or_malformed_success_is_an_error(
    monkeypatch, body, status, headers
):
    requests = transport(monkeypatch, body, status=status, headers=headers)
    result = await node({"operation": "get_weibo_hot_search"}).execute({})
    assert result["status"] == "error" and len(requests) == 1


@pytest.mark.asyncio
async def test_network_error_does_not_echo_query_token_or_retry(monkeypatch):
    transport(monkeypatch, httpx.ReadTimeout("URL?token=" + TOKEN))
    result = await node({"operation": "get_weibo_hot_search"}).execute({})
    assert result["status"] == "error" and TOKEN not in str(result)


@pytest.mark.asyncio
async def test_data_null_scalar_list_and_secret_echo(monkeypatch):
    for data in [
        None,
        "caption text",
        [],
        {"title": TOKEN, "token": TOKEN, "nested": [{"access_token": TOKEN}]},
    ]:
        transport(
            monkeypatch,
            {
                "code": 0,
                "message": TOKEN,
                "data": data,
                "requestParams": {"query": {"token": TOKEN}},
            },
        )
        result = await node({"operation": "get_weibo_hot_search"}).execute({})
        assert result["status"] == "success" and TOKEN not in str(result)
        assert "requestParams" not in result


def test_manual_credential_defaults_and_invalid_pastes():
    credential = native.JustOneApiTokenCredential(token="  " + TOKEN + "\n")
    assert (
        credential.token == TOKEN and credential.credential_type == "just_one_api_token"
    )
    for token in [
        "",
        "https://dashboard.justoneapi.com",
        "<your token>",
        "Bearer abc",
        "a\nb",
    ]:
        with pytest.raises(ValidationError):
            native.JustOneApiTokenCredential(token=token)


@pytest.mark.parametrize(
    "config",
    [
        {"operation": "search_douyin_videos", "keyword": "coffee", "page": 2},
        {"operation": "search_youtube"},
        {"operation": "search_taobao_products", "keyword": "coffee", "page": 0},
        {
            "operation": "search_douyin_videos",
            "keyword": "coffee",
            "sort_type": "invented",
        },
        {"operation": "convert_1688_image", "url": "http://example.com/x.jpg"},
        {"operation": "get_weibo_hot_search", "endpoint": "https://example.com"},
    ],
)
def test_invalid_config_fails_before_network(config):
    with pytest.raises(ValidationError):
        native.JustOneApiFullConfig(config=config)
