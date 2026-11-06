"""Exercise native AccuLynx transport, paging and CRM operation contracts.

The factory and guarded HTTP client remain real; only DNS and HTTP responses are
synthetic. These fixtures make no claim about an AccuLynx tenant or live writes.
"""
import json
from copy import deepcopy
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from pydantic import ValidationError

from nodes import acculynx_node as s
from nodes.core.registry import NodeFactory
from utils import ssrf

COMPANY = "00000000-0000-4000-8000-000000000001"
CONTACT = "00000000-0000-4000-8000-000000000002"
JOB = "00000000-0000-4000-8000-000000000003"
TYPE = "00000000-0000-4000-8000-000000000004"
SOURCE = "00000000-0000-4000-8000-000000000005"
KEY = {"credential_type": s.FAMILY, "api_key": "fixture.synthetic.key", "company_id": COMPANY}


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def wire(monkeypatch):
    state = {"calls": [], "reply": lambda _: httpx.Response(200, json={"id": CONTACT, "firstName": "Owned", "lastName": "Contact"}), "company": COMPANY,
             "resolve_host_addresses": ssrf._resolve_host_addresses}
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["8.8.8.8"]))
    def answer(request):
        state["calls"].append(request)
        assert request.url.host == "api.acculynx.com"
        assert request.headers["authorization"] == "Bearer " + KEY["api_key"]
        if request.url.path == "/api/v2/company-settings":
            return httpx.Response(200, json={"companyId": state["company"], "name": "Owned Roofing", "privateEmail": "hidden@example.test"})
        return state["reply"](request)
    actual = ssrf.guarded_async_client
    monkeypatch.setattr(s, "guarded_async_client", lambda **kwargs: actual(**kwargs, transport=httpx.MockTransport(answer)))
    return state


def node(operation, credential=None, **fields):
    return NodeFactory.create_node(node_id="fixture-node", node_type="automation-acculynx",
        node_data={"config": {"operation": operation, **fields}, "credentials": deepcopy(credential or KEY)})


def test_parse_config_accepts_base_hook_keyword():
    config = s.AccuLynxNode.parse_config(config_data={"config": {"operation": "get_company_settings"}, "credentials": deepcopy(KEY)})
    assert config.config.operation == "get_company_settings"
    assert config.credentials.company_id == COMPANY


def collection(items, start=0, size=25, count=None):
    return {"items": items, "count": len(items) + start if count is None else count, "pageSize": size, "pageStartIndex": start}


@pytest.mark.asyncio
async def test_actual_factory_company_binding_and_no_fake_user_identity(wire):
    result = await node("get_company_settings").execute({})
    assert result == {"status": "success", "companies": [{"companyId": COMPANY, "name": "Owned Roofing"}]}
    assert len(wire["calls"]) == 1
    wire["company"] = SOURCE
    result = await node("get_contact", contact_id=CONTACT).execute({})
    assert result["status"] == "error" and result["status_code"] == 200
    assert len(wire["calls"]) == 2


@pytest.mark.asyncio
async def test_contact_record_index_paging_and_projection_never_follows_link(wire):
    row = {"id": CONTACT, "firstName": "Owned", "lastName": "Contact", "_link": "https://outside.invalid/private", "emailAddresses": [{"address": "hidden@example.test"}], "billingAddress": {"street1": "private"}}
    wire["reply"] = lambda _: httpx.Response(200, json=collection([row], start=25, count=80))
    result = await node("list_contacts", start_index=25).execute({})
    assert dict(wire["calls"][-1].url.params) == {"pageSize": "25", "pageStartIndex": "25"}
    assert result["next_start_index"] == 26 and result["continuation_verified"] is True and result["snapshot_verified"] is False
    assert result["items"] == [{"id": CONTACT, "firstName": "Owned", "lastName": "Contact"}]
    assert len(wire["calls"]) == 2


@pytest.mark.asyncio
async def test_job_dates_assignment_max_size_and_unassigned_lead_semantics(wire):
    wire["reply"] = lambda _: httpx.Response(200, json=collection([{"id": JOB, "jobName": "Owned Lead", "currentMilestone": "Lead"}], start=25))
    result = await node("list_jobs", start_index=25, assignment="unassigned", milestones=["lead"], start_date="2026-10-01", end_date="2026-10-05", date_filter_type="ModifiedDate", sort_by="ModifiedDate", sort_order="Descending").execute({})
    params = dict(wire["calls"][-1].url.params)
    assert params["pageStartIndex"] == "25" and "recordStartIndex" not in params
    assert params["startDate"] == "2026-10-01" and params["endDate"] == "2026-10-05"
    assert params["assignment"] == "unassigned" and params["milestones"] == "lead"
    assert params["dateFilterType"] == params["sortBy"] == "ModifiedDate" and params["sortOrder"] == "Descending"
    assert result["items"][0]["currentMilestone"] == "Lead"
    for fields in ({"page_size": 26}, {"page_size": True}, {"start_date": "2026-10-05"}, {"start_date": "2026-10-05", "end_date": "2026-10-01"}, {"milestones": ["cancelled"]}):
        with pytest.raises(ValidationError):
            s.Jobs.model_validate({"operation": "list_jobs", **fields})


@pytest.mark.asyncio
async def test_unassigned_leads_and_job_pickers_use_documented_record_index(wire):
    # GET /jobs documents pageStartIndex; recordStartIndex belongs to lead sources.
    wire["reply"] = lambda _: httpx.Response(200, json=collection([{"id": JOB, "jobName": "Owned Lead"}], start=25))
    result = await node("list_unassigned_leads", start_index=25).execute({})
    assert result["status"] == "success"
    assert dict(wire["calls"][-1].url.params) == {
        "pageSize": "25", "pageStartIndex": "25", "assignment": "unassigned", "milestones": "lead"}
    for field, assignment in (("job_id", "assigned"), ("lead_id", "unassigned")):
        result = await s.AccuLynxNode.load_field_options(field, KEY, page_token="25")
        assert result["options"] == [{"value": JOB, "label": "Owned Lead"}]
        params = dict(wire["calls"][-1].url.params)
        assert params["pageStartIndex"] == "25" and "recordStartIndex" not in params
        assert params["assignment"] == assignment


@pytest.mark.asyncio
@pytest.mark.parametrize("delta", [{"count": "1"}, {"count": True}, {"pageSize": 26}, {"pageStartIndex": 1}, {"items": []}, {"items": [{"id": CONTACT}, {"id": CONTACT}]}])
async def test_malformed_paging_cannot_look_exhausted(wire, delta):
    wire["reply"] = lambda _: httpx.Response(200, json={**collection([{"id": CONTACT}], count=2), **delta})
    result = await node("list_contacts").execute({})
    assert result["status"] == "error" and result["status_code"] == 200 and result["uncertain_outcome"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [b'{"id":"00000000-0000-4000-8000-000000000002","metadata":NaN}', b'{"id":"00000000-0000-4000-8000-000000000002","metadata":1e309}', b'{"id":"00000000-0000-4000-8000-000000000002","id":"00000000-0000-4000-8000-000000000003"}'])
async def test_strict_json_is_interoperable_and_finite(wire, payload):
    wire["reply"] = lambda _: httpx.Response(200, content=payload, headers={"content-type": "application/json"})
    result = await node("get_contact", contact_id=CONTACT).execute({})
    assert result["status"] == "error" and result["status_code"] == 200 and len(wire["calls"]) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("marker", [{"error": "secret"}, {"success": False}, {"executed": False}, {"pending": True}, {"rejected": True}, {"halt": True}, {"status": 400}, {"status_code": 403}])
async def test_top_level_problem_and_admission_envelopes_are_not_records(wire, marker):
    wire["reply"] = lambda _: httpx.Response(200, json={"id": CONTACT, **marker})
    result = await node("get_contact", contact_id=CONTACT).execute({})
    assert result["status"] == "error" and "secret" not in str(result)


@pytest.mark.asyncio
async def test_contact_create_has_exact_body_and_verified_current_type(wire):
    def reply(request):
        if request.method == "GET":
            assert request.url.path == "/api/v2/contacts/contact-types"
            return httpx.Response(200, json=collection([{"id": TYPE, "name": "Customer", "isDefault": True}]))
        assert request.url.path == "/api/v2/contacts" and request.method == "POST"
        assert json.loads(request.content) == {"firstName": "Synthetic", "lastName": "Fixture", "contactTypeIds": [TYPE], "crossReference": "owned-fixture"}
        return httpx.Response(201, json={"id": CONTACT, "_link": "https://do-not-follow.invalid"})
    wire["reply"] = reply
    result = await node("create_contact", first_name="Synthetic", last_name="Fixture", contact_type_id=TYPE, cross_reference="owned-fixture", confirm_crm_change=True).execute({})
    assert result["record_id"] == CONTACT and result["status_code"] == 201 and result["readback_verified"] is False
    assert len(wire["calls"]) == 3


@pytest.mark.asyncio
async def test_contact_note_acknowledges_empty_201_without_fake_note_id(wire):
    wire["reply"] = lambda request: httpx.Response(200, json={"id": CONTACT}) if request.method == "GET" else httpx.Response(201)
    result = await node("create_contact_note", contact_id=CONTACT, note="Synthetic\nnote", confirm_crm_change=True).execute({})
    assert wire["calls"][-1].url.path == f"/api/v2/contacts/{CONTACT}/notes"
    assert json.loads(wire["calls"][-1].content) == {"note": "Synthetic\nnote"}
    assert result["status"] == "success" and result["note_id"] is None and result["contact_id"] == CONTACT
    assert result["readback_verified"] is False and len(wire["calls"]) == 3


@pytest.mark.asyncio
async def test_lead_create_is_unassigned_and_never_gets_unretrievable_job(wire):
    wire["reply"] = lambda request: httpx.Response(200, json={"id": CONTACT}) if request.method == "GET" else httpx.Response(201, json={"id": JOB})
    result = await node("create_unassigned_lead", contact_id=CONTACT, notes="owned fixture", confirm_crm_change=True).execute({})
    assert json.loads(wire["calls"][-1].content) == {"contact": {"id": CONTACT}, "notes": "owned fixture"}
    assert result["created_as"] == "unassigned_lead" and result["get_job_readback_supported"] is False
    assert result["record_id"] == JOB and len(wire["calls"]) == 3
    assert not any(request.url.path == f"/api/v2/jobs/{JOB}" for request in wire["calls"])


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,fields,path,body", [("update_job_priority", {"priority": "High"}, "priority", {"priority": "High"}), ("update_job_lead_source", {"lead_source_id": SOURCE}, "lead-source", {"id": SOURCE})])
async def test_job_updates_preflight_parent_and_preserve_empty_204(wire, operation, fields, path, body):
    def reply(request):
        if request.method == "PUT":
            assert request.url.path == f"/api/v2/jobs/{JOB}/{path}" and json.loads(request.content) == body
            return httpx.Response(204)
        return httpx.Response(200, json={"id": SOURCE, "name": "Owned Source"} if "lead-sources" in request.url.path else {"id": JOB, "jobName": "Owned Job"})
    wire["reply"] = reply
    result = await node(operation, job_id=JOB, confirm_crm_change=True, **fields).execute({})
    assert result["status"] == "success" and result["status_code"] == 204 and result["readback_verified"] is False
    assert sum(request.method == "PUT" for request in wire["calls"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", [httpx.Response(201, json={"id": "invalid"}), httpx.Response(201, json={"id": JOB, "success": False}), httpx.Response(429, json={"detail": KEY["api_key"]})])
async def test_mutation_failure_retains_actual_status_and_uncertainty_without_replay(wire, reply):
    wire["reply"] = lambda request: httpx.Response(200, json={"id": CONTACT}) if request.method == "GET" else reply
    result = await node("create_unassigned_lead", contact_id=CONTACT, confirm_crm_change=True).execute({})
    assert result["status"] == "error" and result["uncertain_outcome"] is True and result["status_code"] == reply.status_code
    assert KEY["api_key"] not in str(result) and len(wire["calls"]) == 3


@pytest.mark.asyncio
async def test_picker_and_native_connect_redact_secrets_and_keep_company_scope(wire):
    wire["reply"] = lambda _: httpx.Response(200, json=collection([{"id": CONTACT, "firstName": KEY["api_key"]}]))
    result = await s.AccuLynxNode.load_field_options("contact_id", KEY)
    assert result == {"options": [{"value": CONTACT, "label": "[redacted]"}], "next_page_token": None}
    assert KEY["api_key"] not in repr(s.AccuLynxAPIKeyCredential.model_validate(KEY))
    with pytest.raises(ValueError):
        await s.AccuLynxNode.load_field_options("contact_id", KEY, page_token="https://outside.invalid")


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [{"api_key": "unicode-é"}, {"api_key": "bad\nheader"}, {"company_id": "../../outside"}, {"credential_type": "oauth"}])
async def test_credential_rejects_before_client_construction(monkeypatch, change):
    transport = Mock(side_effect=AssertionError("No HTTP construction"))
    monkeypatch.setattr(s, "guarded_async_client", transport)
    with pytest.raises(ValueError):
        node("get_company_settings", credential={**KEY, **change})
    transport.assert_not_called()


@pytest.mark.asyncio
async def test_native_routes_and_typed_models_have_no_purchase_message_or_raw_escape():
    session = s.CRMSession(s.AccuLynxAPIKeyCredential.model_validate(KEY))
    for method, path in (("POST", "jobs/x/messages"), ("DELETE", "contacts/" + CONTACT), ("PUT", "contacts"), ("PUT", "jobs"), ("GET", "https://outside.invalid"), ("POST", "orders")):
        with pytest.raises(s.AccuLynxError):
            await session.request(method, path, body={})
    with pytest.raises(ValidationError):
        s.CreateLead(contact_id=CONTACT, confirm_crm_change=1)
    with pytest.raises(ValidationError):
        s.CreateLead(contact_id=CONTACT, confirm_crm_change=True, representative_id=JOB)


@pytest.mark.asyncio
async def test_current_milestone_and_history_are_closed_metadata(wire):
    def reply(request):
        if request.url.path.endswith("/milestones/current"):
            return httpx.Response(200, json={"id": TYPE, "name": "Prospect", "isCurrent": True, "_link": "https://hidden.invalid"})
        if request.url.path.endswith("/history"):
            return httpx.Response(200, json={"items": [{"action": "Lead was created.", "date": "2026-10-06T00:00:00Z", "createdBy": {"email": "hidden@example.test"}}]})
        return httpx.Response(200, json={"id": JOB, "jobName": "Owned"})
    wire["reply"] = reply
    result = await node("get_current_job_milestone", job_id=JOB).execute({})
    assert result["milestone"] == {"id": TYPE, "name": "Prospect", "isCurrent": True}
    result = await node("get_lead_history", lead_id=JOB).execute({})
    assert result["history"] == [{"action": "Lead was created.", "date": "2026-10-06T00:00:00Z"}]


@pytest.mark.asyncio
async def test_response_bound_and_missing_contact_type_stop_before_mutation(wire):
    wire["reply"] = lambda _: httpx.Response(200, content=b"x" * (2 * 1024 * 1024 + 1), headers={"content-type": "application/json"})
    result = await node("get_contact", contact_id=CONTACT).execute({})
    assert result["status"] == "error" and result["status_code"] == 200 and len(wire["calls"]) == 2
    wire["calls"].clear()
    wire["reply"] = lambda _: httpx.Response(200, json=collection([]))
    result = await node("create_contact", first_name="Synthetic", last_name="Fixture", contact_type_id=TYPE, confirm_crm_change=True).execute({})
    assert result["status"] == "error" and result["uncertain_outcome"] is False
    assert len(wire["calls"]) == 2 and all(request.method == "GET" for request in wire["calls"])
