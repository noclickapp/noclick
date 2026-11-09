"""Exercise real factory, wire requests, published responses and connection evidence."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import funnelcockpit_node as native
from nodes.core.registry import NodeFactory
from nodes.core.connection_evidence import collect_evidence

FIXTURE = json.loads((Path(__file__).parent / "fixtures/funnelcockpit/contract.json").read_text())
KEY = "private-funnelcockpit-test-key"
CREDENTIAL = {"credential_type": "funnelcockpit_api_key", "api_key": KEY}


def node(config):
    return NodeFactory.create_node(node_id="funnelcockpit-test", node_type="automation-funnelcockpit",
        node_data={"config": config, "credentials": CREDENTIAL})


def transport(monkeypatch, body=None, status=200, empty=False, content_type="application/json"):
    requests = []
    def respond(request):
        requests.append(request)
        if empty:
            return httpx.Response(status, content=b"", headers={"content-type": content_type})
        return httpx.Response(status, json=body, headers={"content-type": content_type})
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.parametrize("case", FIXTURE["operations"], ids=lambda c: c["operation"])
async def test_funnelcockpit_published_contract_through_factory(monkeypatch, case):
    requests = transport(monkeypatch, case["response"], empty=case["empty_response"])
    result = await node(case["config"]).execute({})
    assert result == {"status": "success", "data": case["response"]}
    assert len(requests) == 1
    request = requests[0]
    route = case["path"]
    for field in case["path_fields"]:
        route = route.replace("{" + field + "}", case["config"][field])
    assert request.method == case["method"]
    assert request.url.scheme == "https" and request.url.host == "api.funnelcockpit.com"
    assert request.url.path == route
    assert request.headers["Authorization"] == KEY
    assert KEY not in str(result)
    if case["method"] == "POST":
        body = {k: v for k, v in case["config"].items() if k in case["body_fields"]}
        if case["operation"] == "create_or_update_email_contact":
            body["provider"] = "funnelcockpit"
        if "webinarStartDate" in body:
            body["webinarStartDate"] = "2026-05-19T15:00:00Z"
        assert json.loads(request.content) == body
    else:
        assert not request.content


async def test_funnelcockpit_filters_and_zero_page(monkeypatch):
    requests = transport(monkeypatch, [])
    result = await node({"operation": "list_email_contacts", "email": "contact@example.com", "tagId": "tag_123", "page": 0, "limit": 25}).execute({})
    assert result["data"] == []
    assert dict(requests[0].url.params) == {"email": "contact@example.com", "tagId": "tag_123", "page": "0", "limit": "25"}


async def test_funnelcockpit_crm_group_array_and_member_enrollment_status(monkeypatch):
    requests = transport(monkeypatch, {"success": True, "contactId": "contact_123"})
    await node({"operation": "create_or_update_crm_contact", "crmId": "crm_123", "email": "contact@example.com", "crmTagIds": ["crm_tag_123"]}).execute({})
    assert json.loads(requests[0].content)["crmTagIds"] == ["crm_tag_123"]
    body = {"email": "contact@example.com", "created": 1, "updated": 0, "skipped": 0, "enrollmentQueued": 0, "enrollmentFailed": 1}
    transport(monkeypatch, body)
    case = next(c for c in FIXTURE["operations"] if c["operation"] == "create_or_update_members_area_member")
    assert (await node(case["config"]).execute({}))["data"] == body


@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
async def test_funnelcockpit_provider_rejection_redacts_key(monkeypatch, status):
    requests = transport(monkeypatch, {"message": "Rejected " + KEY}, status=status)
    output = await node({"operation": "get_current_user"}).execute({})
    assert output["status"] == "error" and output["status_code"] == status
    assert KEY not in str(output) and len(requests) == 1


@pytest.mark.parametrize("body", [{"error": "Denied"}, {"success": False}, {"name": "Jane"}, [], "not an account"])
async def test_funnelcockpit_invalid_identity_is_not_success(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError):
        await node({"operation": "get_current_user"}).execute({})


async def test_funnelcockpit_empty_legacy_webinars_and_html_are_not_success(monkeypatch):
    transport(monkeypatch, empty=True)
    with pytest.raises(ValueError):
        await node({"operation": "list_webinars"}).execute({})
    transport(monkeypatch, {"name": "Jane", "email": "jane@example.com"}, content_type="text/html")
    with pytest.raises(ValueError):
        await node({"operation": "get_current_user"}).execute({})


async def test_funnelcockpit_actual_connection_evidence(monkeypatch):
    requests = transport(monkeypatch, {"name": "Jane Doe", "email": "jane@example.com"})
    result = await collect_evidence(node_type="automation-funnelcockpit", user_id="test", pool=None, credential_data=CREDENTIAL)
    assert result.reachable is True and result.account_label == "Jane Doe"
    assert len(requests) == 1 and requests[0].url.path == "/me"
    transport(monkeypatch, {"message": "Private API key is invalid"}, status=403)
    result = await collect_evidence(node_type="automation-funnelcockpit", user_id="test", pool=None, credential_data=CREDENTIAL)
    assert result.reachable is False and "Private API key is invalid" in result.error
    transport(monkeypatch, {"message": "Server error"}, status=500)
    result = await collect_evidence(node_type="automation-funnelcockpit", user_id="test", pool=None, credential_data=CREDENTIAL)
    assert result.reachable is None


@pytest.mark.parametrize("config", [
    {"operation": "list_forms", "page": -1},
    {"operation": "list_forms", "limit": 0},
    {"operation": "list_forms", "limit": True},
    {"operation": "list_form_submissions", "formId": "f", "pageSize": 26},
    {"operation": "list_survey_results", "surveyId": "s", "pageSize": 101},
    {"operation": "list_crm_contacts", "crmId": "../other"},
    {"operation": "list_crm_contacts"},
    {"operation": "subscribe_email_contact", "email": "bad", "tagId": "tag_123"},
    {"operation": "create_or_update_members_area_member", "membersAreaId": "m", "email": "a@b.com", "firstName": "Jane"},
    {"operation": "create_webinar_viewer", "webinarId": "w", "email": "a@b.com", "webinarStartDate": "2026-05-19"},
    {"operation": "create_or_update_email_contact", "provider": "klicktipp", "email": "a@b.com"},
    {"operation": "create_or_update_crm_contact", "crmId": "crm_123", "email": "a@b.com", "avatarUrl": "bad"},
    {"operation": "create_or_update_crm_contact", "crmId": "crm_123", "email": "a@b.com", "crmTagIds": [""]},
    {"operation": "list_forms", "url": "https://example.com"},
])
def test_funnelcockpit_invalid_config_is_rejected(config):
    with pytest.raises(ValueError):
        native.FunnelCockpitNode.parse_config({"config": config, "credentials": CREDENTIAL})


def test_funnelcockpit_manual_credential_defaults_and_redaction():
    credential = native.FunnelCockpitAPIKeyCredential(api_key=KEY)
    assert credential.credential_type == "funnelcockpit_api_key"
    assert KEY not in repr(credential)
    assert native._redact({"quote": KEY + '\"'}, KEY) == {"quote": '[redacted]\"'}
    for token in ["Bearer token", "https://example.com", "key\nheader"]:
        with pytest.raises(ValidationError):
            native.FunnelCockpitAPIKeyCredential(api_key=token)
