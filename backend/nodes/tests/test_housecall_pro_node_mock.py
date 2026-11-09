"""Exercise Housecall Pro's actual factory and HTTP request path without an account.

Published response fixtures pin provider examples; independent cases cover all
25 routes, request bodies, paging, manual credential shaping and failures.
"""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import housecall_pro_node as native
from nodes.core.registry import NodeFactory
from nodes.core.credential_connect import shape_credential

TOKEN = "synthetic-housecall-pro-key-42"
AUTH = {"credential_type": "housecall_pro_api_key", "api_key": TOKEN}
FIXTURE = json.loads((Path(__file__).parent / "fixtures/housecall-pro/published-examples.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credential=None):
    return NodeFactory.create_node(node_id="housecall-pro-fixture", node_type="automation-housecall-pro",
        node_data={"config": config, "credentials": AUTH if credential is None else credential})


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    def send(request):
        requests.append(request)
        return replies.pop(0)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(send), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests, replies


def page(key):
    return {"page": 1, "page_size": 10, "total_pages": 1, "total_items": 1, key: [{"id": "record-1", "name": "Example"}]}


CASES = [
    ("get_company", {}, "GET", "/company", 200, {"id": "company-1", "name": "Example Services"}),
    ("list_customers", {}, "GET", "/customers", 200, page("customers")),
    ("get_customer", {"customer_id": "cust-1"}, "GET", "/customers/cust-1", 200, {"id": "cust-1"}),
    ("create_customer", {"first_name": "Ada", "notifications_enabled": False}, "POST", "/customers", 201, {"id": "cust-1", "first_name": "Ada"}),
    ("update_customer", {"customer_id": "cust-1", "first_name": "Ada", "notifications_enabled": False}, "PUT", "/customers/cust-1", 200, {"id": "cust-1", "first_name": "Ada"}),
    ("create_customer_address", {"customer_id": "cust-1", "street": "123 Main St", "city": "San Diego", "state": "CA", "zip": "92101", "country": "US"}, "POST", "/customers/cust-1/addresses", 200, {"id": "addr-1"}),
    ("list_employees", {}, "GET", "/employees", 200, page("employees")),
    ("list_jobs", {"customer_id": "cust-1"}, "GET", "/jobs", 200, page("jobs")),
    ("get_job", {"job_id": "job-1"}, "GET", "/jobs/job-1", 200, {"id": "job-1"}),
    ("create_job", {"customer_id": "cust-1", "address_id": "addr-1", "notes": "Repair", "assigned_employee_ids": ["employee-1"]}, "POST", "/jobs", 201, {"id": "job-1"}),
    ("list_job_line_items", {"job_id": "job-1"}, "GET", "/jobs/job-1/line_items", 200, {"url": "/jobs/job-1/line_items", "data": [{"id": "line-1", "name": "Repair"}]}),
    ("create_job_line_item", {"job_id": "job-1", "name": "Repair", "unit_price": 15000, "quantity": 1.25}, "POST", "/jobs/job-1/line_items", 201, {"id": "line-1", "unit_price": 15000, "quantity": 1.25}),
    ("list_job_appointments", {"job_id": "job-1"}, "GET", "/jobs/job-1/appointments", 200, {"appointments": [{"id": "appointment-1"}]}),
    ("create_job_appointment", {"job_id": "job-1", "start_time": "2026-11-10T10:00:00Z", "end_time": "2026-11-10T11:00:00Z", "dispatched_employees_ids": ["employee-1"]}, "POST", "/jobs/job-1/appointments", 201, {"id": "appointment-1"}),
    ("add_job_note", {"job_id": "job-1", "content": "Gate code 123"}, "POST", "/jobs/job-1/notes", 201, {"id": "note-1", "content": "Gate code 123"}),
    ("delete_job_note", {"job_id": "job-1", "note_id": "note-1"}, "DELETE", "/jobs/job-1/notes/note-1", 200, None),
    ("add_job_tag", {"job_id": "job-1", "tag_id": "tag-1"}, "POST", "/jobs/job-1/tags", 201, {"tags": [{"id": "tag-1", "name": "Urgent"}]}),
    ("remove_job_tag", {"job_id": "job-1", "tag_id": "tag-1"}, "DELETE", "/jobs/job-1/tags/tag-1", 200, {"tags": []}),
    ("list_estimates", {}, "GET", "/estimates", 200, page("estimates")),
    ("create_estimate", {"customer_id": "cust-1", "address_id": "addr-1", "options": [{"name": "Repair", "line_items": [{"name": "Labor", "unit_price": 15000}]}]}, "POST", "/estimates", 200, {"id": "estimate-1"}),
    ("list_leads", {"status": "open"}, "GET", "/leads", 200, page("leads")),
    ("get_lead", {"lead_id": "lead-1"}, "GET", "/leads/lead-1", 200, {"id": "lead-1"}),
    ("create_lead", {"customer_id": "cust-1", "note": "Requested quote", "tags": ["New"]}, "POST", "/leads", 201, {"id": "lead-1"}),
    ("list_tags", {}, "GET", "/tags", 200, page("tags")),
    ("list_lead_sources", {"q": "Referral"}, "GET", "/lead_sources", 200, page("lead_sources")),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,args,method,path,status,body", CASES, ids=[c[0] for c in CASES])
async def test_all_operations_use_one_documented_request(transport, operation, args, method, path, status, body):
    requests, replies = transport
    replies.append(httpx.Response(status, json=body) if body is not None else httpx.Response(status))
    result = await node({"operation": operation, **args}).execute({})
    assert result["status"] == "success", result
    assert len(requests) == 1 and not replies
    request = requests[0]
    assert request.method == method and request.url.path == path
    assert request.url.host == "api.housecallpro.com"
    assert request.headers["Authorization"] == "Token " + TOKEN
    assert TOKEN not in str(request.url)
    if method in {"POST", "PUT"}:
        sent = json.loads(request.content)
        # Every supplied field except path IDs must be sent, preserving false values and nested structures.
        for key, value in args.items():
            if "{" + key + "}" in native.OPERATIONS[operation][1]: continue
            if key == "options":
                assert sent[key][0]["line_items"][0]["unit_price"] == 15000
            else: assert sent[key] == value
        assert "operation" not in sent and "job_id" not in sent
        assert result["acknowledged"] is True
    if method == "DELETE": assert not request.content


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,path", [("list_customers", "/customers"), ("list_tags", "/tags"), ("remove_job_tag", "/jobs/{job_id}/tags/{tag_id}")])
async def test_provider_published_examples_are_parsed(transport, operation, path):
    transport[1].append(httpx.Response(200, json=FIXTURE["responses"][path]))
    result = await node({"operation": operation, **({"job_id": "job-1", "tag_id": "tag-1"} if operation == "remove_job_tag" else {})}).execute({})
    assert result["status"] == "success" and result["items"]


@pytest.mark.asyncio
async def test_paging_and_search_keep_provider_query_and_next_page(transport):
    body = page("customers"); body.update(page=2, total_pages=3)
    transport[1].append(httpx.Response(200, json=body))
    result = await node({"operation": "list_customers", "q": "Ada + Co", "page": 2, "page_size": 1}).execute({})
    assert result["next_page"] == 3 and result["has_more"] is True
    assert dict(transport[0][0].url.params) == {"page": "2", "page_size": "1", "sort_direction": "desc", "q": "Ada + Co", "sort_by": "created_at"}
    body.update(page=3, total_pages=3, customers=[])
    transport[1].append(httpx.Response(200, json=body))
    result = await node({"operation": "list_customers", "page": 3}).execute({})
    assert result["next_page"] is None and result["has_more"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body", [(401, {"message": "Invalid key"}), (403, {"message": "Read only key"}), (429, {"message": "Rate limited"}), (500, {"message": "Unavailable"}), (200, {"error": "Refused"}), (200, {"customers": None})])
async def test_failures_do_not_report_success(transport, status, body):
    transport[1].append(httpx.Response(status, json=body))
    result = await node({"operation": "list_customers"}).execute({})
    assert result["status"] == "error" and "data" not in result and len(transport[0]) == 1


@pytest.mark.asyncio
async def test_redirect_html_transport_failure_and_secret_redaction(transport, monkeypatch):
    transport[1].append(httpx.Response(302, headers={"Location": "https://other.test"}))
    assert (await node({"operation": "get_company"}).execute({}))["status"] == "error"
    transport[1].append(httpx.Response(200, text="login", headers={"content-type": "text/html"}))
    assert (await node({"operation": "get_company"}).execute({}))["status"] == "error"
    transport[1].append(httpx.Response(401, json={"message": "Invalid " + TOKEN}))
    assert TOKEN not in json.dumps(await node({"operation": "get_company"}).execute({}))
    monkeypatch.setattr(httpx.AsyncClient, "request", AsyncMock(side_effect=httpx.ConnectError("unavailable")))
    assert (await node({"operation": "get_company"}).execute({}))["status"] == "error"


@pytest.mark.parametrize("bad", ["../other", "a/b", "a?b", "a%2fb", "https://other.test", "x\n"])
def test_invalid_path_ids_fail_before_http(bad):
    with pytest.raises(ValueError): node({"operation": "get_job", "job_id": bad})


@pytest.mark.parametrize("bad", ["foreign_api_key", None, "", [], {}])
def test_foreign_credential_tag_is_not_reconciled(bad):
    with pytest.raises(ValueError): node({"operation": "get_company"}, {**AUTH, "credential_type": bad})


def test_manual_connect_defaults_and_credential_fields():
    shaped, errors, resolved = shape_credential("housecall_pro_api_key", {"api_key": "  " + TOKEN + "  "})
    assert errors == {} and shaped == {"api_key": TOKEN}
    assert native.HousecallProAPIKeyCredential.model_validate(shaped).model_dump() == AUTH
    assert native.HousecallProAPIKeyCredential.model_fields["credential_type"].default == "housecall_pro_api_key"
    for bad in ("Token abc", "https://example.test/key", "<token>"):
        with pytest.raises(ValueError): native.HousecallProAPIKeyCredential(api_key=bad)


def test_required_fields_and_closed_body_shapes():
    for config in [
        {"operation": "create_job", "customer_id": "cust-1"},
        {"operation": "create_job_appointment", "job_id": "job-1", "start_time": "bad"},
        {"operation": "create_customer_address", "customer_id": "cust-1", "street": "Main"},
        {"operation": "update_customer", "customer_id": "cust-1"},
        {"operation": "create_job_line_item", "job_id": "job-1", "name": "Labor", "quantity": 1.001},
        {"operation": "get_company", "api_url": "https://other.test"},
    ]:
        with pytest.raises(ValueError): node(config)
