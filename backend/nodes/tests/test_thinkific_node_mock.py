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
from nodes.thinkific_node import ThinkificNode, ThinkificNodeConfig, THINKIFIC_TRIGGERS

FIXTURES = Path(__file__).parent / "fixtures" / "thinkific"
RESPONSES = json.loads((FIXTURES / "responses.json").read_text())
REQUESTS = json.loads((FIXTURES / "requests.json").read_text())
TOKEN = "thinkific-test-token"
EVENTS = json.loads((FIXTURES / "events.json").read_text())


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


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", THINKIFIC_TRIGGERS)
async def test_signed_trigger_lifecycle(monkeypatch, operation):
    import hashlib
    import hmac
    topic = THINKIFIC_TRIGGERS[operation][0]
    event = EVENTS[topic]["body"]
    secret = "documented-signing-secret"
    seen = []

    def handler(request):
        seen.append(request)
        assert request.url.host == "platform.thinkific.com"
        assert request.headers["authorization"] == "Bearer " + TOKEN
        if request.method == "POST":
            assert request.url.path == "/api/v2/webhooks"
            assert json.loads(request.content) == {
                "topic": topic, "target_url": "https://workflow.hooks.example.test/hook",
                "generate_signing_secret": True,
            }
            return httpx.Response(201, json={"id": "20200227213233625839530", "signing_secret": secret})
        assert request.method == "DELETE"
        assert request.url.path == "/api/v2/webhooks/20200227213233625839530"
        return httpx.Response(204)

    mock_transport(monkeypatch, handler)
    config = {"operation": operation}
    node = make_node(config)
    registration = await ThinkificNode._register_external_webhook(
        webhook_url="https://workflow.hooks.example.test/hook", credential={"access_token": TOKEN}, config=config, node_id="thinkific")
    config.update(registration)
    assert make_node(config).config.config.signing_secret == secret
    raw = json.dumps(event).encode()
    signature = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    headers = {"X-Thinkific-Hmac-Sha256": signature}
    assert ThinkificNode.verify_webhook_signature(raw, headers, config)
    assert not ThinkificNode.verify_webhook_signature(raw + b" ", headers, config)
    assert not ThinkificNode.verify_webhook_signature(raw, {}, config)
    assert not ThinkificNode.verify_webhook_signature(raw, headers, {})
    assert not ThinkificNode.verify_webhook_signature(raw, {"x-thinkific-hmac-sha256": "é" * 64}, config)
    for other, fixture in EVENTS.items():
        assert ThinkificNode.filter_trigger_payload(fixture["body"], config) == (other == topic)
    output = ThinkificNode.resolve_trigger_payload(event, config)
    assert output == event
    turn = ThinkificNode.resolve_agent_event(output)
    user = event["payload"] if event["resource"] == "user" else event["payload"]["user"]
    assert topic in turn["text"]
    assert user["email"] in turn["text"]
    assert str(user["id"]) in turn["text"]
    assert event["tenant_id"] in turn["conversation_key"]
    assert str(event["id"]) in turn["text"]
    if event["resource"] in {"enrollment", "lesson"}:
        assert event["payload"]["course"]["name"] in turn["text"]
    if event["resource"] == "order":
        assert event["payload"]["product_name"] in turn["text"]
        assert str(event["payload"]["amount_cents"]) in turn["text"]
    assert await node.execute(event) == event
    await ThinkificNode._unregister_external_webhook(
        credential={"access_token": TOKEN}, config=config, node_id="thinkific")
    assert len(seen) == 2


@pytest.mark.asyncio
async def test_trigger_rollout_without_signing_secret_cleans_up(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request.method)
        if request.method == "POST":
            return httpx.Response(201, json={"id": "20200227213233625839530"})
        return httpx.Response(204)

    mock_transport(monkeypatch, handler)
    with pytest.raises(ValueError, match="has not enabled webhook signing secrets"):
        await ThinkificNode._register_external_webhook(
            webhook_url="https://workflow.hooks.example.test/hook", credential={"access_token": TOKEN},
            config={"operation": "on_order_created"}, node_id="thinkific")
    assert seen == ["POST", "DELETE"]


@pytest.mark.asyncio
async def test_trigger_registration_rejection_and_deleted_cleanup(monkeypatch):
    status = 401
    mock_transport(monkeypatch, lambda request: httpx.Response(status))
    with pytest.raises(ValueError, match="HTTP 401"):
        await ThinkificNode._register_external_webhook(
            webhook_url="https://workflow.hooks.example.test/hook", credential={"access_token": TOKEN},
            config={"operation": "on_student_signup"}, node_id="thinkific")
    status = 404
    await ThinkificNode._unregister_external_webhook(
        credential={"access_token": TOKEN}, config={"external_webhook_id": "1"}, node_id="thinkific")
