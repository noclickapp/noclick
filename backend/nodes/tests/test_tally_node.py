"""Tally REST contract tests with an in-process HTTP transport."""

import json
import base64
import hashlib
import hmac
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
from httpx import AsyncClient as OriginalAsyncClient

from nodes.tally_node import (
    API_BASE,
    API_VERSION,
    CreateWebhookConfig,
    CreateFormConfig,
    UpdateFormConfig,
    CreateWorkspaceConfig,
    UpdateWorkspaceConfig,
    CreateFolderConfig,
    UpdateFolderConfig,
    CreateOrganizationInvitesConfig,
    UpdateWebhookConfig,
    DeleteSubmissionConfig,
    GetFormMetricsConfig,
    ListFormsConfig,
    RetryWebhookEventConfig,
    TallyApiKeyCredential,
    TallyNode,
    TallyNodeConfig,
    _ENDPOINTS,
    _request_details,
    NewFormSubmissionConfig,
)


def documented_event():
    return json.loads((Path(__file__).parent / "fixtures/tally/form_response.json").read_text())["body"]


@pytest.mark.asyncio
async def test_submission_trigger_lifecycle(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        assert request.headers["authorization"] == "Bearer test-secret"
        assert request.headers["tally-version"] == API_VERSION
        if request.method == "POST":
            body = json.loads(request.content)
            assert body["formId"] == documented_event()["data"]["formId"]
            assert body["eventTypes"] == ["FORM_RESPONSE"]
            assert body["url"] == "https://example.com/webhook"
            assert len(body["signingSecret"]) >= 32
            return httpx.Response(201, json={"id": "webhook-1"})
        assert request.method == "DELETE"
        assert request.url.path == "/webhooks/webhook-1"
        return httpx.Response(204)

    mock_http(monkeypatch, handler)
    config = NewFormSubmissionConfig(form_id=documented_event()["data"]["formId"])
    credential = {"api_key": "test-secret"}
    state = await TallyNode._register_external_webhook(
        webhook_url="https://example.com/webhook", credential=credential,
        config=config.model_dump(), node_id="test")
    assert state["signing_secret"] == json.loads(requests[0].content)["signingSecret"]
    config = config.model_copy(update=state)
    assert NewFormSubmissionConfig.model_validate(config.model_dump()).external_webhook_id == "webhook-1"
    await TallyNode._unregister_external_webhook(credential=credential, config=config.model_dump(), node_id="test")
    assert len(requests) == 2
    assert TallyNode.registration_fingerprint_fields(config.model_dump()) == {"form_id": config.form_id}
    assert (await make_node(config).execute({}))["status"] == "no_event"


def test_documented_submission_signature_and_agent_message():
    event = documented_event()
    body = json.dumps(event, ensure_ascii=False).encode()
    secret = "YOUR_SIGNING_SECRET"
    signature = base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()
    config = {"operation": "on_form_submission", "form_id": event["data"]["formId"], "signing_secret": secret}
    assert TallyNode.verify_webhook_signature(body, {"Tally-Signature": signature}, config)
    assert not TallyNode.verify_webhook_signature(body + b" ", {"tally-signature": signature}, config)
    assert not TallyNode.verify_webhook_signature(body, {}, config)
    assert not TallyNode.verify_webhook_signature(body, {"tally-signature": signature}, {})
    assert not TallyNode.verify_webhook_signature(body, {"tally-signature": "bad"}, config)
    assert TallyNode.filter_trigger_payload(event, config)
    assert not TallyNode.filter_trigger_payload(event, {**config, "form_id": "another-form"})
    assert not TallyNode.filter_trigger_payload({**event, "eventType": "other"}, config)
    turn = TallyNode.resolve_agent_event(TallyNode.resolve_trigger_payload(event, config))
    for text in ("alice@example.com", "Webhook payload", "Hello world", "In progress", "Swimming", "Skiing", "get_submission", "2wgx4n", "VwbNEw"):
        assert text in turn["text"]
    assert turn["conversation_key"] == event["data"]["submissionId"]
    assert TallyNode.resolve_agent_event({"status": "no_event", "data": {}}) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status, body", [(403, {"message": "Forbidden"}), (201, {})])
async def test_trigger_registration_failures(monkeypatch, status, body):
    mock_http(monkeypatch, lambda _: httpx.Response(status, json=body))
    with pytest.raises(ValueError):
        await TallyNode._register_external_webhook(
            webhook_url="https://example.com/webhook", credential={"api_key": "test-secret"},
            config={"form_id": "VwbNEw"}, node_id="test")


def make_node(operation, *, credential=True):
    return TallyNode(
        node_id="tally-test",
        node_type="automation-tally",
        node_data={},
        config=TallyNodeConfig(
            config=operation,
            credentials=TallyApiKeyCredential(api_key="test-secret")
            if credential
            else None,
        ),
        sio=Mock(),
        sid="test-sid",
        workflow_id="test-workflow",
        user_id="test-user",
    )


def mock_http(monkeypatch, handler):
    monkeypatch.setattr(
        "nodes.tally_node.httpx.AsyncClient",
        lambda **kwargs: OriginalAsyncClient(
            transport=httpx.MockTransport(handler), **kwargs
        ),
    )


@pytest.mark.asyncio
async def test_list_forms_sends_bearer_version_and_repeated_workspace_ids(monkeypatch):
    def handler(request):
        assert request.method == "GET"
        assert str(request.url).startswith(f"{API_BASE}/forms?")
        assert request.headers["authorization"] == "Bearer test-secret"
        assert request.headers["tally-version"] == API_VERSION
        assert request.url.params.get_list("workspaceIds") == ["ws-one", "ws-two"]
        assert request.url.params["page"] == "2"
        assert request.url.params["limit"] == "25"
        return httpx.Response(200, json={"forms": [{"id": "f1"}], "hasMore": False})

    mock_http(monkeypatch, handler)
    node = make_node(
        ListFormsConfig(page=2, limit=25, workspace_ids_json='["ws-one","ws-two"]')
    )
    result = await node.execute({})
    assert result == {
        "status": "success",
        "operation": "list_forms",
        "data": {"forms": [{"id": "f1"}], "hasMore": False},
    }


@pytest.mark.asyncio
async def test_webhook_creation_sends_body_json_without_mutation(monkeypatch):
    body = {
        "formId": "form-1",
        "url": "https://example.com/hook",
        "eventTypes": ["FORM_RESPONSE"],
    }

    def handler(request):
        assert request.method == "POST"
        assert request.url.path == "/webhooks"
        assert json.loads(request.content) == body
        return httpx.Response(201, json={"id": "webhook-1", **body})

    mock_http(monkeypatch, handler)
    result = await make_node(CreateWebhookConfig(body_json=json.dumps(body))).execute(
        {}
    )
    assert result["data"]["id"] == "webhook-1"


@pytest.mark.asyncio
async def test_delete_submission_encodes_path_and_handles_no_content(monkeypatch):
    def handler(request):
        assert request.method == "DELETE"
        assert request.url.raw_path == b"/forms/form%2Fone/submissions/sub%20two"
        return httpx.Response(204)

    mock_http(monkeypatch, handler)
    result = await make_node(
        DeleteSubmissionConfig(form_id="form/one", submission_id="sub two")
    ).execute({})
    assert result["data"] == {"deleted": True, "accepted": False}


@pytest.mark.asyncio
async def test_retry_webhook_event_handles_204_as_accepted(monkeypatch):
    def handler(request):
        assert request.method == "POST"
        assert request.url.path == "/webhooks/w1/events/e1"
        return httpx.Response(204)

    mock_http(monkeypatch, handler)
    result = await make_node(
        RetryWebhookEventConfig(webhook_id="w1", event_id="e1")
    ).execute({})
    assert result["data"] == {"deleted": False, "accepted": True}


@pytest.mark.asyncio
async def test_vendor_error_and_invalid_response_are_clear(monkeypatch):
    mock_http(
        monkeypatch,
        lambda _: httpx.Response(403, json={"message": "Invalid API key"}),
    )
    with pytest.raises(ValueError, match="Tally API error 403: Invalid API key"):
        await make_node(ListFormsConfig()).execute({})

    mock_http(monkeypatch, lambda _: httpx.Response(200, text="not json"))
    with pytest.raises(ValueError, match="Tally returned invalid JSON"):
        await make_node(ListFormsConfig()).execute({})


@pytest.mark.asyncio
async def test_missing_credential_stops_before_http(monkeypatch):
    mock_http(monkeypatch, lambda _: pytest.fail("HTTP should not be requested"))
    with pytest.raises(ValueError, match="Connect Tally"):
        await make_node(ListFormsConfig(), credential=False).execute({})


def test_request_validation_and_fixed_catalogue():
    assert len(_ENDPOINTS) == 38
    assert TallyNode.connection_evidence.operation == "list_forms"
    assert TallyNode.connection_evidence.identity_operation == "get_current_user"
    with pytest.raises(
        ValueError, match="workspaceIds must be a JSON array of strings"
    ):
        _request_details(ListFormsConfig(workspace_ids_json='["ws", 3]'))
    with pytest.raises(ValueError, match="Request Body JSON must be a JSON object"):
        _request_details(CreateWebhookConfig(body_json='["wrong"]'))
    with pytest.raises(ValueError, match="Request Body JSON must be valid JSON"):
        _request_details(CreateWebhookConfig(body_json="{bad"))
    with pytest.raises(ValueError):
        GetFormMetricsConfig(form_id="f1", period="invalid")


@pytest.mark.parametrize(
    "config, expected",
    [
        (CreateWorkspaceConfig(name="Research"), {"name": "Research"}),
        (UpdateWorkspaceConfig(workspace_id="w1", name="Research"), {"name": "Research"}),
        (CreateFolderConfig(workspace_id="w1", name="Surveys"), {"name": "Surveys"}),
        (CreateFolderConfig(workspace_id="w1", name="Surveys", parent_id=None), {"name": "Surveys"}),
        (CreateFolderConfig(workspace_id="w1", name="Surveys", parent_id="p1"),
         {"name": "Surveys", "parentId": "p1"}),
        (UpdateFolderConfig(workspace_id="w1", id="f1", name="Surveys"), {"name": "Surveys"}),
        (CreateOrganizationInvitesConfig(organization_id="o1", workspace_ids=["w1", "w2"],
                                         emails="one@example.com;two@example.com"),
         {"workspaceIds": ["w1", "w2"], "emails": "one@example.com;two@example.com"}),
        (UpdateWebhookConfig(webhook_id="h1", url="https://example.com/hook",
                             event_types=["FORM_RESPONSE"], is_enabled=False),
         {"url": "https://example.com/hook", "eventTypes": ["FORM_RESPONSE"], "isEnabled": False}),
        (UpdateWebhookConfig(webhook_id="h1", url="https://example.com/hook",
                             event_types=["FORM_RESPONSE"], is_enabled=True,
                             signing_secret=None, http_headers=None),
         {"url": "https://example.com/hook", "eventTypes": ["FORM_RESPONSE"], "isEnabled": True,
          "signingSecret": None, "httpHeaders": None}),
        (UpdateWebhookConfig(webhook_id="h1", url="https://example.com/hook",
                             event_types=["FORM_RESPONSE"], is_enabled=True,
                             http_headers=[{"name": "X-Custom", "value": "secret"}]),
         {"url": "https://example.com/hook", "eventTypes": ["FORM_RESPONSE"], "isEnabled": True,
          "httpHeaders": [{"name": "X-Custom", "value": "secret"}]}),
    ],
)
@pytest.mark.asyncio
async def test_typed_write_bodies_reach_the_api(monkeypatch, config, expected):
    def handler(request):
        assert request.method in {"POST", "PATCH"}
        assert json.loads(request.content) == expected
        return httpx.Response(200, json={"id": "result"})

    mock_http(monkeypatch, handler)
    result = await make_node(config).execute({})
    assert result["status"] == "success"


@pytest.mark.parametrize(
    "model, fields",
    [
        (CreateWorkspaceConfig, {}),
        (UpdateWorkspaceConfig, {"workspace_id": "w1"}),
        (CreateFolderConfig, {"workspace_id": "w1"}),
        (UpdateFolderConfig, {"workspace_id": "w1", "id": "f1"}),
        (CreateOrganizationInvitesConfig, {"organization_id": "o1", "workspace_ids": ["w1"]}),
        (CreateOrganizationInvitesConfig, {"organization_id": "o1", "emails": "one@example.com"}),
        (UpdateWebhookConfig, {"webhook_id": "h1", "url": "https://example.com/hook"}),
        (UpdateWebhookConfig, {"webhook_id": "h1", "url": "https://example.com/hook",
                               "event_types": ["UNKNOWN"], "is_enabled": True}),
        (UpdateWebhookConfig, {"webhook_id": "h1", "url": "https://example.com/hook",
                               "event_types": ["FORM_RESPONSE"], "is_enabled": True,
                               "http_headers": [{"name": "X-Custom"}]}),
    ],
)
def test_typed_write_bodies_reject_missing_or_invalid_api_fields(model, fields):
    with pytest.raises(ValueError):
        model(**fields)


@pytest.mark.parametrize("operation", ["create_form", "update_form"])
@pytest.mark.asyncio
async def test_documented_form_blocks_are_forwarded_and_responses_parsed(monkeypatch, operation):
    fixture = json.loads((Path(__file__).parent / "fixtures" / "tally" / f"{operation}.json").read_text())

    def handler(request):
        assert request.method == ("POST" if operation == "create_form" else "PATCH")
        assert json.loads(request.content) == fixture["request"]
        return httpx.Response(201 if operation == "create_form" else 200, json=fixture["response"])

    mock_http(monkeypatch, handler)
    if operation == "create_form":
        config = CreateFormConfig(body_json=json.dumps(fixture["request"]))
    else:
        config = UpdateFormConfig(form_id=fixture["response"]["id"], body_json=json.dumps(fixture["request"]))
    result = await make_node(config).execute({})
    assert result["data"] == fixture["response"]
