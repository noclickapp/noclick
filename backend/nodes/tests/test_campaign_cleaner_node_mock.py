"""Exercise every operation against the provider's published request/response examples.

The real node factory, credential schema and guarded HTTP client run locally;
only DNS and the transport are replaced, so these tests never contact accounts.
"""
import base64
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import campaign_cleaner_node as cc
from nodes.core.binary_output import BinaryOutput
from nodes.core.registry import NODE_REGISTRY, NodeFactory
from nodes.core.connection_evidence import collect_evidence
from nodes.core.credential_connect import shape_credential
from utils import ssrf

EXAMPLES = json.loads((Path(__file__).parent / "fixtures/campaign-cleaner/contract_examples.json").read_text())
CASES = EXAMPLES["cases"]
AUTH = {"credential_type": "campaign_cleaner_api_key", "api_key": "fixture-campaign-cleaner-key"}


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    calls, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))

    async def send(request):
        calls.append(request)
        assert request.url.host == "api.campaigncleaner.com"
        assert request.headers["X-CC-API-Key"] == AUTH["api_key"]
        assert AUTH["api_key"] not in str(request.url)
        status, body, headers = replies.pop(0)
        if isinstance(body, bytes):
            return httpx.Response(status, content=body, headers=headers)
        return httpx.Response(status, json=body, headers=headers)

    native = ssrf.guarded_async_client
    monkeypatch.setattr(cc, "guarded_async_client", lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)))
    return calls, replies


def node(config, credentials=AUTH):
    return NodeFactory.create_node(node_id="campaign-cleaner-test", node_type="automation-campaign-cleaner",
        node_data={"config": config, "credentials": credentials})


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["operation"])
async def test_campaign_cleaner_contract_examples(case, transport):
    calls, replies = transport
    response = b"%PDF-1.4\nfixture" if case["content_type"] == "application/pdf" else case["response"]
    replies.append((case["status"], response, {"Content-Type": case["content_type"]}))
    result = await node(case["config"]).execute({})
    assert len(calls) == 1
    request = calls[0]
    assert request.method == case["method"]
    assert request.url.path == case["path"]
    if case["body"] is not None:
        expected = case["body"]
        if case["operation"] == "send_campaign":
            # The shared runtime config lens treats cleared optional text as unset.
            expected = {"send_campaign": {k: v for k, v in expected["send_campaign"].items() if v != ""}}
        assert json.loads(request.content) == expected
    else:
        assert not request.content
        expected = {k: str(v).lower() if isinstance(v, bool) else str(v)
            for k, v in case["config"].items() if k != "operation"}
        assert dict(request.url.params) == expected
    if isinstance(response, bytes):
        assert isinstance(result["file"], BinaryOutput)
        assert result["file"].data == response
        assert result["file"].content_type == "application/pdf"
    else:
        assert result == response


@pytest.mark.asyncio
@pytest.mark.parametrize("status,headers", [(200, {}), (200, {"X-CC-Status": "4001"}), (401, {})])
async def test_campaign_cleaner_rejected_key_is_an_error(status, headers, transport):
    _, replies = transport
    replies.append((status, {"error": "Invalid API Key."}, headers))
    result = await node({"operation": "get_campaign_list"}).execute({})
    assert result["status"] == "error"
    assert result["error"] == "Invalid API Key."


@pytest.mark.asyncio
async def test_campaign_cleaner_evidence_names_the_saved_campaign(transport):
    _, replies = transport
    sample = next(c for c in CASES if c["operation"] == "get_campaign_list")["response"]
    replies.append((200, sample, {}))
    result = await collect_evidence(node_type="automation-campaign-cleaner", credential_data=AUTH,
        user_id="00000000-0000-4000-8000-000000000001")
    assert result.reachable is True
    assert result.samples
    assert result.samples[0].label == sample["campaign_list"][0]["campaign_name"]


@pytest.mark.asyncio
async def test_campaign_cleaner_original_message_is_a_file(transport):
    _, replies = transport
    original = b"From: sender@example.com\r\nSubject: Example\r\n\r\nHello"
    replies.append((200, {"message_id": 9821, "eml_base64": base64.b64encode(original).decode()}, {}))
    result = await node({"operation": "monitor_get_message", "message_id": 9821, "include_eml": True}).execute({})
    assert "eml_base64" not in result
    assert result["file"].data == original
    assert result["file"].content_type == "message/rfc822"


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [b"<html>Sign in</html>", b"[]"])
async def test_campaign_cleaner_unexpected_response_is_not_success(body, transport):
    _, replies = transport
    replies.append((200, body, {}))
    with pytest.raises(ValueError, match="unexpected"):
        await node({"operation": "get_credits"}).execute({})


def test_campaign_cleaner_discovery_and_manual_connect():
    assert NODE_REGISTRY["automation-campaign-cleaner"] is cc.CampaignCleanerNode
    shaped, errors, resolved = shape_credential("campaign_cleaner_api_key", {"api_key": AUTH["api_key"]})
    assert not errors
    assert resolved == ("automation-campaign-cleaner", cc.CampaignCleanerAPIKey)
    assert cc.CampaignCleanerAPIKey.model_validate(shaped).credential_type == "campaign_cleaner_api_key"
    assert not cc.CampaignCleanerAPIKey.model_fields["credential_type"].is_required()


@pytest.mark.parametrize("config", [
    {"operation": "send_campaign", "campaign_name": "Test"},
    {"operation": "create_inbox_test", "test_name": "x" * 81},
    {"operation": "monitor_get_message"},
    {"operation": "monitor_get_messages", "page_size": 201},
    {"operation": "monitor_get_summary", "days": 366},
    {"operation": "monitor_save_alert", "kind": "unknown"},
    {"operation": "monitor_delete_alert", "alert_id": 0},
    {"operation": "send_campaign", "campaign_name": "Test", "campaign_html": "<p>Hi</p>", "webhook_url": "https://example.com/callback?secret=1"},
])
def test_campaign_cleaner_invalid_inputs_do_not_send(config):
    with pytest.raises(ValidationError):
        cc.CampaignCleanerFullConfig.model_validate({"config": config, "credentials": AUTH})
