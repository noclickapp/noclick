"""Published Sertifier v3.3 examples exercised through the real node factory."""
import json
from pathlib import Path
from urllib.parse import quote
import httpx
import pytest
from pydantic import ValidationError
from nodes import sertifier_node as native
from nodes.core.registry import NodeFactory

EXAMPLES = json.loads(
    (Path(__file__).parent / "fixtures/sertifier/contract_examples.json").read_text()
)["operations"]
TOKEN = "sertifier-synthetic-secret-42"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(
        node_id="sertifier-fixture",
        node_type="automation-sertifier",
        node_data={
            "config": config,
            "credentials": {"credential_type": "sertifier_api_key", "api_key": TOKEN},
        },
    )


def transport(monkeypatch, payload, status=200):
    calls = []

    def respond(request):
        calls.append(request)
        if isinstance(payload, Exception):
            raise payload
        return httpx.Response(status, json=payload)

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        assert kwargs["timeout"] == 30.0
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,example", EXAMPLES.items())
async def test_published_examples_exact_request_and_response(
    monkeypatch, operation, example
):
    calls = transport(monkeypatch, example["response"])
    config = {"operation": operation, **(example["request"] or {})}
    path = example["path"]
    for parameter in path.split("{")[1:]:
        parameter = parameter.split("}")[0]
        field = "credential_id_or_certificate_no" if "OR" in parameter else parameter
        config[field] = "resource + space"
        path = path.replace("{" + parameter + "}", quote(config[field], safe=""))
    result = await node(config).execute({})
    assert (
        result["status"] == "success" and result["data"] == example["response"]["data"]
    )
    assert len(calls) == 1
    request = calls[0]
    assert (
        request.method == example["method"] and request.url.host == "b2b.sertifier.com"
    )
    assert request.url.raw_path.decode() == path
    assert (
        request.headers["secretKey"] == TOKEN
        and request.headers["api-version"] == "3.3"
    )
    assert not request.url.query
    if example["request"] is not None:
        assert json.loads(request.content) == example["request"]
    else:
        assert request.content == b""
    assert TOKEN not in str(result)


@pytest.mark.asyncio
async def test_search_defaults_account_evidence_and_explicit_page(monkeypatch):
    response = {
        "hasError": False,
        "data": {
            "results": [{"id": "campaign-42", "title": "Graduation 2026"}],
            "total": 53,
        },
    }
    calls = transport(monkeypatch, response)
    result = await node(
        {"operation": "search_campaigns", "start_index": 50, "length": 3}
    ).execute({})
    assert json.loads(calls[0].content) == {"startIndex": 50, "length": 3}
    assert (
        result["total"] == 53 and result["start_index"] == 50 and result["length"] == 3
    )
    assert len(calls) == 1
    transport(monkeypatch, response)
    result = await node({"operation": "search_campaigns"}).execute({})
    assert result["start_index"] == 0 and result["length"] == 50
    assert native.SertifierNode.connection_evidence.operation == "search_campaigns"


@pytest.mark.asyncio
async def test_creation_defaults_preserve_email_control_and_acknowledgments(
    monkeypatch,
):
    calls = transport(monkeypatch, EXAMPLES["add_credentials_to_campaign"]["response"])
    await node(
        {
            "operation": "add_credentials_to_campaign",
            "credentials": [
                {
                    "campaign_id": "campaign-1",
                    "name": "Graduate",
                    "dont_send_email": True,
                }
            ],
        }
    ).execute({})
    assert json.loads(calls[0].content) == {
        "credentials": [
            {
                "campaignId": "campaign-1",
                "name": "Graduate",
                "quickPublish": False,
                "dontSendEmail": True,
            }
        ]
    }
    calls = transport(monkeypatch, EXAMPLES["publish_credentials"]["response"])
    result = await node(
        {"operation": "publish_credentials", "ids": ["certificate-1"]}
    ).execute({})
    assert result["success"] and result["data"] is False and "delivered" not in result
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload,status",
    [
        ({"hasError": True, "message": "Invalid secretKey", "data": None}, 200),
        ({"hasError": True, "message": "API key rejected", "data": None}, 403),
        ({"hasError": True, "validationErrors": ["Invalid title"], "data": None}, 200),
        ({}, 200),
        ({"hasError": False}, 200),
        ({"hasError": "false", "data": []}, 200),
        ({"hasError": False, "data": {"results": "invalid"}}, 200),
        ({"hasError": False, "data": []}, 302),
    ],
)
async def test_error_envelopes_http_errors_and_malformed_pages(
    monkeypatch, payload, status
):
    calls = transport(monkeypatch, payload, status)
    with pytest.raises(ValueError):
        await node({"operation": "search_campaigns"}).execute({})
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_secrets_redacted_and_provider_rejection_preserved(monkeypatch):
    transport(
        monkeypatch, {"hasError": True, "message": "Rejected " + TOKEN, "data": None}
    )
    with pytest.raises(ValueError, match=r"Rejected \[redacted\]") as exc:
        await node({"operation": "search_campaigns"}).execute({})
    assert TOKEN not in str(exc.value)
    transport(monkeypatch, {"hasError": False, "data": {"note": TOKEN}})
    assert (
        await node({"operation": "get_credential", "credential_id": "cert-1"}).execute(
            {}
        )
    )["data"]["note"] == "[redacted]"


@pytest.mark.asyncio
async def test_timeout_has_no_retry_or_false_write_success(monkeypatch):
    calls = transport(monkeypatch, httpx.ReadTimeout("timeout"))
    with pytest.raises(ValueError, match="may have completed"):
        await node({"operation": "send_campaign", "id": "campaign-1"}).execute({})
    assert len(calls) == 1


@pytest.mark.parametrize(
    "key", ["https://example.com/key", "secret\nheader", "bad key", "<token>"]
)
def test_manual_secret_validation(key):
    with pytest.raises(ValueError):
        native.SertifierAPIKeyCredential(api_key=key)


def test_manual_credential_default_and_required_writes():
    assert (
        native.SertifierAPIKeyCredential(api_key=TOKEN).credential_type
        == "sertifier_api_key"
    )
    for config in [
        {"operation": "publish_credentials", "ids": []},
        {"operation": "add_recipients", "recipients": []},
        {"operation": "schedule_campaign", "id": "one"},
        {"operation": "get_credential"},
        {"operation": "search_campaigns", "length": 0},
        {"operation": "search_campaigns", "start_index": -1},
    ]:
        with pytest.raises(ValidationError):
            native.SertifierNodeConfig(config=config)


@pytest.mark.asyncio
async def test_explicit_null_clears_expiry_but_unset_update_fields_are_omitted(
    monkeypatch,
):
    calls = transport(monkeypatch, EXAMPLES["update_credential"]["response"])
    await node(
        {
            "operation": "update_credential",
            "credential_id": "cert-1",
            "expire_date": None,
        }
    ).execute({})
    assert json.loads(calls[0].content) == {"expireDate": None}


@pytest.mark.asyncio
async def test_dot_segment_cannot_change_resource_route(monkeypatch):
    calls = transport(monkeypatch, EXAMPLES["get_credential"]["response"])
    with pytest.raises(ValueError, match="resource ID"):
        await node({"operation": "get_credential", "credential_id": ".."}).execute({})
    assert calls == []
