"""Every operation uses Thinkific's documented response property examples.

Source: https://developers.thinkific.com/openapi/thinkific-admin-api-v1.yaml
Required IDs without examples reuse documented ID 1. Containers follow the
Get*Response/Meta schemas. Status-only acknowledgements remain empty.
"""
import json
from pathlib import Path
from unittest.mock import Mock
import httpx
import pytest
from nodes.thinkific_node import ThinkificNode, ThinkificNodeConfig

FIXTURES = Path(__file__).parent / "fixtures" / "thinkific"
RESPONSES = json.loads((FIXTURES / "responses.json").read_text())
REQUESTS = json.loads((FIXTURES / "requests.json").read_text())
TOKEN = "thinkific-test-token"


def make_node(config):
    return ThinkificNode(
        node_id="thinkific",
        node_type="automation-thinkific",
        node_data={},
        config=ThinkificNodeConfig.model_validate(
            {
                "config": config,
                "credentials": {
                    "credential_type": "thinkific_api_token",
                    "access_token": TOKEN,
                },
            }
        ),
        sio=Mock(),
    )


def mock_transport(monkeypatch, handler):
    client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda *a, **kw: client(
            *a, **{**kw, "transport": httpx.MockTransport(handler)}
        ),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", REQUESTS)
async def test_documented_operation(monkeypatch, operation):
    case, fixture = REQUESTS[operation], RESPONSES[operation]
    seen = []

    def handler(request):
        seen.append(request)
        assert request.method == case["method"]
        assert request.url.host == "api.thinkific.com"
        assert request.url.path == "/api/public/v1" + case["path"]
        assert request.headers["authorization"] == "Bearer " + TOKEN
        assert dict(request.url.params) == {k: str(v) for k, v in case["query"].items()}
        if case["body"] is None:
            assert request.content == b""
        else:
            assert json.loads(request.content) == case["body"]
        return (
            httpx.Response(fixture["status_code"], json=fixture["body"])
            if fixture["body"] is not None
            else httpx.Response(fixture["status_code"])
        )

    mock_transport(monkeypatch, handler)
    output = await make_node({"operation": operation, **case["config"]}).execute({})
    assert len(seen) == 1
    assert output["status"] == "success", output
    assert output["status_code"] == fixture["status_code"]
    assert output["data"] == (
        fixture["body"] if fixture["body"] is not None else {"success": True}
    )
    assert output["timing_ms"]["api_request"] >= 0


@pytest.mark.asyncio
async def test_bracket_filters_and_false_values(monkeypatch):
    def handler(request):
        assert dict(request.url.params) == {
            "page": "2",
            "limit": "10",
            "query[user_id]": "1",
            "query[completed]": "false",
            "query[created_after]": "2018-01-01T01:01:00Z",
        }
        return httpx.Response(
            200, json={"items": [], "meta": {"pagination": {"current_page": 2}}}
        )

    mock_transport(monkeypatch, handler)
    output = await make_node(
        {
            "operation": "list_enrollments",
            "page": 2,
            "limit": 10,
            "user_id": 1,
            "completed": False,
            "created_after": "2018-01-01T01:01:00Z",
        }
    ).execute({})
    assert output["data"]["meta"]["pagination"]["current_page"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 422, 429, 500])
async def test_provider_rejection(monkeypatch, status):
    # https://support.thinkific.dev/hc/en-us/articles/38357676036887
    mock_transport(
        monkeypatch,
        lambda r: httpx.Response(status, json={"error": "Authentication Error"}),
    )
    output = await make_node({"operation": "list_courses"}).execute({})
    assert output["status"] == "error"
    assert output["status_code"] == status
    assert output["error"] == "Authentication Error"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [{}, {"items": "invalid"}, {"items": ["bad"]}, {"items": [{}]}, {"error": "oops"}],
)
async def test_connection_probe_rejects_unexpected_success(monkeypatch, payload):
    mock_transport(monkeypatch, lambda r: httpx.Response(200, json=payload))
    assert (await make_node({"operation": "list_courses"}).execute({}))[
        "status"
    ] == "error"


@pytest.mark.asyncio
async def test_empty_course_list_is_valid(monkeypatch):
    mock_transport(
        monkeypatch, lambda r: httpx.Response(200, json={"items": [], "meta": {}})
    )
    assert (await make_node({"operation": "list_courses"}).execute({}))[
        "status"
    ] == "success"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [201, 202])
async def test_bundle_sync_and_async_acknowledgement(monkeypatch, status):
    mock_transport(monkeypatch, lambda r: httpx.Response(status))
    output = await make_node(
        {"operation": "enroll_in_bundle", "bundle_id": 1, "user_id": 1}
    ).execute({})
    assert output["status"] == "success"
    assert output["status_code"] == status


@pytest.mark.asyncio
async def test_invalid_json(monkeypatch):
    mock_transport(
        monkeypatch, lambda r: httpx.Response(200, text="<html>Not JSON</html>")
    )
    assert (await make_node({"operation": "list_courses"}).execute({}))[
        "status"
    ] == "error"


@pytest.mark.asyncio
async def test_token_redaction(monkeypatch):
    mock_transport(
        monkeypatch, lambda r: httpx.Response(401, json={"error": "Rejected " + TOKEN})
    )
    assert TOKEN not in str(await make_node({"operation": "list_courses"}).execute({}))


@pytest.mark.asyncio
@pytest.mark.parametrize("exception", [httpx.ReadTimeout, httpx.ConnectError])
async def test_transport_failure(monkeypatch, exception):
    def handler(request):
        raise exception("unreachable", request=request)

    mock_transport(monkeypatch, handler)
    assert (await make_node({"operation": "list_courses"}).execute({}))[
        "status"
    ] == "error"
