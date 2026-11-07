"""Benchmark Email 2026 API request contracts (not a live account test)."""

import json
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
from pydantic import ValidationError

from nodes import benchmark_email_node as benchmark


STRUCTURE = "64a1b2c3d4e5f6a7b8c9d0e1"
LIST = "66f1a6e4698f1bca60425001"
CONTACT = "66f1a6e4698f1bca60424901"


def credential(**changes):
    return benchmark.BenchmarkEmailCredential(
        api_key="bme_secret", api_base_url="https://api-us-1.benchmarkemail.io", **changes
    )


def node(operation):
    return benchmark.BenchmarkEmailNode(
        node_id="test", node_type="automation-benchmark-email", node_data={},
        config=benchmark.BenchmarkEmailNodeConfig(config=operation, credentials=credential()),
        sio=Mock(), sid="sid", workflow_id="workflow", user_id="user",
    )


def fake_api(monkeypatch, handler):
    real_client = httpx.AsyncClient

    def client(*args, **kwargs):
        return real_client(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(benchmark.httpx, "AsyncClient", client)


def check_auth(request):
    assert request.headers["X-API-Key"] == "bme_secret"
    assert request.url.host == "api-us-1.benchmarkemail.io"


def test_credential_base_url_rejects_ssrf_targets():
    for value in (
        "http://api-us-1.benchmarkemail.io", "https://api-us-1.benchmarkemail.io.evil.org",
        "https://api-us-1.benchmarkemail.io:8443", "https://api-us-1.benchmarkemail.io/path",
        "https://user@api-us-1.benchmarkemail.io", "https://localhost",
    ):
        with pytest.raises(ValidationError):
            benchmark.BenchmarkEmailCredential(api_key="x", api_base_url=value)


@pytest.mark.asyncio
async def test_create_contact_uses_field_ids_and_list_objects(monkeypatch):
    def handler(request):
        check_auth(request)
        assert request.method == "POST" and request.url.path == "/api/contact"
        assert json.loads(request.content) == {
            "key": "ada@example.com", "contactStructureId": STRUCTURE,
            "fields": [{"_id": CONTACT, "value": "Ada"}], "lists": [{"_id": LIST}],
        }
        return httpx.Response(200, json={"_id": CONTACT})

    fake_api(monkeypatch, handler)
    result = await node(benchmark.CreateContact(
        contact_structure_id=STRUCTURE, email="ada@example.com",
        fields_json=json.dumps([{"_id": CONTACT, "value": "Ada"}]), list_ids=LIST,
    )).execute({})
    assert result["status"] == "success" and result["data"]["_id"] == CONTACT


@pytest.mark.asyncio
async def test_search_contacts_uses_nonempty_projection_and_email_filter(monkeypatch):
    def handler(request):
        check_auth(request)
        body = json.loads(request.content)
        assert request.url.path == "/api/contact/search"
        assert body["source"] == ["_id", "key", "fields", "lists", "contactStatus", "createdAt"]
        assert body["contactSpecification"]["filters"][0]["criterias"][0] == {
            "columnToFilter": "KEY", "operator": "EQ", "values": ["ada@example.com"]
        }
        return httpx.Response(200, json={"contacts": [], "totalRecords": 0})

    fake_api(monkeypatch, handler)
    result = await node(benchmark.SearchContacts(contact_structure_id=STRUCTURE,
                                                  email="ada@example.com")).execute({})
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_update_contact_preserves_omitted_fields_and_current_version(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request.method)
        check_auth(request)
        assert request.url.path == f"/api/contact/{CONTACT}"
        if request.method == "GET":
            return httpx.Response(200, json={
                "key": "old@example.com", "contactStructureId": STRUCTURE,
                "fields": [{"_id": STRUCTURE, "value": "Existing"}],
                "lists": [{"_id": LIST}], "tags": [], "status": {"primary": "Active"},
                "__v": 7, "accountId": "readonly",
            })
        body = json.loads(request.content)
        assert body == {
            "key": "new@example.com", "contactStructureId": STRUCTURE,
            "fields": [{"_id": STRUCTURE, "value": "Existing"}],
            "lists": [{"_id": LIST}], "tags": [], "status": {"primary": "Active"}, "__v": 7,
        }
        return httpx.Response(200, json={"__v": 8})

    fake_api(monkeypatch, handler)
    result = await node(benchmark.UpdateContact(contact_id=CONTACT,
                                                 email="new@example.com")).execute({})
    assert result["status"] == "success" and calls == ["GET", "PUT"]


@pytest.mark.asyncio
async def test_unsubscribe_sends_compliance_status(monkeypatch):
    def handler(request):
        assert request.method == "PATCH"
        assert json.loads(request.content) == {"status": {
            "primary": "Inactive", "secondary": "Unsubscribe"}}
        return httpx.Response(200, json={"status": {"primary": "Inactive"}})

    fake_api(monkeypatch, handler)
    assert (await node(benchmark.UnsubscribeContact(contact_id=CONTACT)).execute({}))["status"] == "success"


@pytest.mark.asyncio
async def test_rename_list_fetches_version_and_delete_accepts_204(monkeypatch):
    def handler(request):
        check_auth(request)
        assert request.url.path.endswith(f"/lists/{LIST}")
        if request.method == "GET":
            return httpx.Response(200, json={"name": "Old", "__v": 3})
        if request.method == "PATCH":
            assert json.loads(request.content) == {"name": "New", "__v": 3}
            return httpx.Response(200, json={"name": "New", "__v": 4})
        assert request.method == "DELETE"
        return httpx.Response(204)

    fake_api(monkeypatch, handler)
    assert (await node(benchmark.RenameList(contact_structure_id=STRUCTURE,
                                            list_id=LIST, name="New")).execute({}))["status"] == "success"
    deleted = await node(benchmark.DeleteList(contact_structure_id=STRUCTURE,
                                              list_id=LIST)).execute({})
    assert deleted["data"] == {"success": True}


@pytest.mark.asyncio
async def test_campaign_draft_lists_are_plain_id_strings(monkeypatch):
    def handler(request):
        check_auth(request)
        body = json.loads(request.content)
        assert request.url.path == "/api/email/campaign"
        assert body == {"name": "Newsletter", "lists": [LIST],
                        "contactStructureId": STRUCTURE, "replyToAddresses": ["reply@example.com"]}
        return httpx.Response(200, json={"_id": CONTACT, "status": "draft"})

    fake_api(monkeypatch, handler)
    result = await node(benchmark.CreateCampaign(
        name="Newsletter", list_ids=LIST, contact_structure_id=STRUCTURE,
        reply_to_addresses="reply@example.com",
    )).execute({})
    assert result["data"]["status"] == "draft"


@pytest.mark.asyncio
async def test_update_campaign_fetches_version_and_can_assign_recipients(monkeypatch):
    def handler(request):
        check_auth(request)
        assert request.url.path == f"/api/email/campaign/{CONTACT}"
        if request.method == "GET":
            return httpx.Response(200, json={"__v": 5, "status": "draft"})
        assert request.method == "PATCH"
        assert json.loads(request.content) == {"subject": "New subject", "lists": [LIST], "__v": 5}
        return httpx.Response(200, json={"__v": 6, "status": "draft"})

    fake_api(monkeypatch, handler)
    result = await node(benchmark.UpdateCampaign(
        campaign_id=CONTACT, subject="New subject", list_ids=LIST,
    )).execute({})
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_duplicate_campaign_requires_and_sends_new_name(monkeypatch):
    def handler(request):
        check_auth(request)
        assert request.method == "POST" and request.url.path == f"/api/email/campaign/{CONTACT}/duplicate"
        assert json.loads(request.content) == {"name": "Follow-up"}
        return httpx.Response(200, json={"name": "Follow-up", "status": "draft"})

    fake_api(monkeypatch, handler)
    result = await node(benchmark.DuplicateCampaign(
        campaign_id=CONTACT, name="Follow-up",
    )).execute({})
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_connection_evidence_picker_calls_real_account_endpoint(monkeypatch):
    def handler(request):
        check_auth(request)
        assert request.method == "GET" and request.url.path == "/api/contact-structure"
        return httpx.Response(200, json=[{"_id": STRUCTURE, "label": "Default Contacts"}])

    fake_api(monkeypatch, handler)
    options = await benchmark.BenchmarkEmailNode.load_field_options(
        "contact_structure_id", credential().model_dump())
    assert options == {"options": [{"value": STRUCTURE, "label": "Default Contacts"}]}


@pytest.mark.asyncio
async def test_list_picker_reads_paginated_records_shape(monkeypatch):
    list_id = "507f1f77bcf86cd799439012"

    def handler(request):
        check_auth(request)
        assert request.method == "GET"
        assert request.url.path == f"/api/contact-structure/{STRUCTURE}/lists/all"
        return httpx.Response(200, json={"records": [{"_id": list_id, "name": "QA List"}]})

    fake_api(monkeypatch, handler)
    options = await benchmark.BenchmarkEmailNode.load_field_options(
        "list_id", credential().model_dump(), context={"config": {"contact_structure_id": STRUCTURE}})
    assert options == {"options": [{"value": list_id, "label": "QA List"}]}


@pytest.mark.asyncio
async def test_api_error_is_structured_and_never_exposes_api_key(monkeypatch):
    fake_api(monkeypatch, lambda request: httpx.Response(403, json={
        "name": "ForbiddenError", "message": "Missing contacts:write scope"}))
    result = await node(benchmark.CreateList(contact_structure_id=STRUCTURE,
                                              name="New")).execute({})
    assert result["status"] == "error" and result["status_code"] == 403
    assert "contacts:write" in result["error"]
    assert "bme_secret" not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("model,path", [
    (benchmark.DashboardReport, "/api/reports/dashboard"),
    (benchmark.EmailOverallReport, "/api/reports/email/overall"),
])
async def test_summary_reports_send_required_period_and_optional_timezone(monkeypatch, model, path):
    # Source: https://developers.benchmarkemail.io/scenarios/view-reports.md
    responses = json.loads((Path(__file__).parent / "fixtures" / "benchmark-email" / "report_responses.json").read_text())
    requests = []

    def handler(request):
        check_auth(request)
        assert request.method == "GET" and request.url.path == path
        requests.append(dict(request.url.params))
        return httpx.Response(200, json=responses[model().operation])

    fake_api(monkeypatch, handler)
    assert (await node(model()).execute({}))["status"] == "success"
    assert (await node(model(past_days=7, timezone="America/New_York")).execute({}))["status"] == "success"
    assert requests == [{"pastDays": "30"}, {"pastDays": "7", "timezone": "America/New_York"}]


@pytest.mark.parametrize("model", [benchmark.DashboardReport, benchmark.EmailOverallReport])
@pytest.mark.parametrize("past_days", [0, 91])
def test_summary_reports_reject_period_outside_provider_limits(model, past_days):
    with pytest.raises(ValidationError):
        model(past_days=past_days)


@pytest.mark.asyncio
async def test_list_templates_sends_required_documented_language(monkeypatch):
    # Source: https://developers.benchmarkemail.io/scenarios/manage-campaigns.md
    response = json.loads((Path(__file__).parent / "fixtures" / "benchmark-email" / "template_list_response.json").read_text())

    def handler(request):
        check_auth(request)
        assert request.method == "GET" and request.url.path == "/api/email/template"
        assert dict(request.url.params) == {"lang": "en"}
        return httpx.Response(200, json=response)

    fake_api(monkeypatch, handler)
    result = await node(benchmark.ListTemplates(language="en")).execute({})
    assert result["status"] == "success" and result["data"] == response


def test_list_templates_rejects_empty_language():
    with pytest.raises(ValidationError):
        benchmark.ListTemplates(language="")
