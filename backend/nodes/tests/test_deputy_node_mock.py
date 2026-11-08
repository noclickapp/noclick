"""Deputy HTTP contract checks through the discovered native node factory."""
from copy import deepcopy
import json
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import deputy_node as deputy
from nodes.core.run_op import run_node_operation
from utils import ssrf

AUTH = {"credential_type": "deputy_permanent_token", "workplace_url": "https://fixture.au.deputy.com", "permanent_token": "fixture-deputy-not-live-token"}
USER = "00000000-0000-4000-8000-000000000001"


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    seen, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))

    async def send(request):
        seen.append(request)
        assert request.url.host == "fixture.au.deputy.com"
        assert request.headers["Authorization"] == "Bearer " + AUTH["permanent_token"]
        assert AUTH["permanent_token"] not in str(request.url)
        code, payload, *headers = replies.pop(0)
        if isinstance(payload, Exception):
            raise payload
        if isinstance(payload, bytes):
            return httpx.Response(code, content=payload, headers=headers[0] if headers else {"Content-Type": "application/json"})
        return httpx.Response(code, json=payload, headers=headers[0] if headers else {})

    native = ssrf.guarded_async_client
    monkeypatch.setattr(deputy, "guarded_async_client", lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)))
    return seen, replies


async def run(operation, arguments=None):
    return await run_node_operation(node_type="automation-deputy", operation=operation,
        arguments=arguments or {}, credential_data=deepcopy(AUTH), user_id=USER)


CASES = [
    ("list_employees", {}, "GET", "/resource/Employee", None),
    ("get_employee", {"employee_id": 17}, "GET", "/resource/Employee/17", None),
    ("create_employee", {"first_name": "John", "last_name": "Doe", "company_id": 1, "mobile_phone": "0441234567", "payroll_id": "1234"}, "POST", "/supervise/employee", {"strFirstName": "John", "strLastName": "Doe", "intCompanyId": 1, "strMobilePhone": "0441234567", "strPayrollId": "1234"}),
    ("update_employee_phone", {"employee_id": 17, "phone": "0441234567"}, "POST", "/supervise/employee/17", {"Phone": "0441234567"}),
    ("list_locations", {}, "GET", "/resource/Company", None),
    ("get_location", {"company_id": 5}, "GET", "/resource/Company/5", None),
    ("list_areas", {}, "GET", "/resource/OperationalUnit", None),
    ("get_area", {"area_id": 2}, "GET", "/resource/OperationalUnit/2", None),
    ("create_area", {"company_id": 5, "name": "Front desk", "export_name": "FRONT"}, "PUT", "/supervise/department", {"intCompanyId": 5, "strOpunitName": "Front desk", "strExportName": "FRONT"}),
    ("list_rosters", {}, "GET", "/resource/Roster", None),
    ("get_roster", {"roster_id": 8}, "GET", "/resource/Roster/8", None),
    ("copy_rosters", {"from_date": "2022-01-01", "to_date": "2022-01-08", "area_ids": [2]}, "POST", "/supervise/roster/copy", {"strFromDate": "2022-01-01", "strToDate": "2022-01-08", "intOperationalUnitArray": [2], "blnRequireErrorDetails": 1}),
    ("publish_rosters", {"roster_ids": [8, 9], "mode": 1}, "POST", "/supervise/roster/publish", {"intMode": 1, "blnAllLocationsMode": 0, "intRosterArray": [8, 9]}),
    ("list_timesheets", {}, "GET", "/resource/Timesheet", None),
    ("get_timesheet", {"timesheet_id": 22}, "GET", "/resource/Timesheet/22", None),
    ("start_timesheet", {"employee_id": 17, "area_id": 2}, "POST", "/supervise/timesheet/start", {"intOpunitId": 2, "intEmployeeId": 17}),
    ("stop_timesheet", {"timesheet_id": 22, "mealbreak_minutes": 30}, "POST", "/supervise/timesheet/end", {"intTimesheetId": 22, "intMealbreakMinute": 30}),
    ("pause_timesheet", {"timesheet_id": 22, "mealbreak_minutes": 0}, "POST", "/supervise/timesheet/pause", {"intTimesheetId": 22, "intMealbreakMinute": 0}),
    ("list_leave", {}, "GET", "/resource/Leave", None),
    ("get_leave", {"leave_id": 33}, "GET", "/resource/Leave/33", None),
    ("create_leave", {"employee_id": 17, "date_start": "2022/01/01", "date_end": "2022/01/02", "status": 1, "approval_comment": "Hello this is leave", "overlapping_rosters_action": 0}, "POST", "/supervise/leave", {"Employee": 17, "DateStart": "2022/01/01", "DateEnd": "2022/01/02", "Status": 1, "ApprovalComment": "Hello this is leave", "ActionOverlappingRosters": 0}),
    ("list_tasks", {}, "GET", "/resource/Task", None),
    ("get_task", {"task_id": 44}, "GET", "/resource/Task/44", None),
    ("get_employee_unavailability", {"employee_id": 17}, "GET", "/supervise/unavail/17", None),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,arguments,method,path,body", CASES)
async def test_all_operations_issue_exactly_one_contract_request(transport, operation, arguments, method, path, body):
    seen, replies = transport
    payload = [{"Id": 1, "CompanyName": "Fixture workplace"}] if operation.startswith("list_") else {"Id": 1}
    replies.append((200, payload))
    result = await run(operation, arguments)
    assert result["success"] is True and result["data"] == payload
    assert len(seen) == 1 and not replies
    request = seen[0]
    assert request.method == method and request.url.path == "/api/v1" + path
    assert not request.url.query
    assert (json.loads(request.content) if request.content else None) == body
    if method != "GET":
        assert result["write_acknowledged"] is True and result["readback_verified"] is False


@pytest.mark.parametrize("url", ["http://fixture.au.deputy.com", "https://fixture.au.deputy.com.evil.test", "https://fixture.au.deputy.com@evil.test", "https://127.0.0.1", "https://fixture.au.deputy.com/api", "https://fixture.au.deputy.com:443", "https://developer.deputy.com", "https://fixture.au.deputy.com?secret=yes"])
def test_refuses_untrusted_workplace_urls(url):
    with pytest.raises(ValueError):
        deputy.DeputyPermanentTokenCredential.model_validate({**AUTH, "workplace_url": url})


@pytest.mark.parametrize("region", ["au", "eu", "na", "deputy"])
def test_accepts_published_tenant_regions(region):
    parsed = deputy.DeputyPermanentTokenCredential.model_validate({**AUTH, "workplace_url": f"https://WORKPLACE.{region}.deputy.com/"})
    assert parsed.workplace_url == f"https://workplace.{region}.deputy.com"


@pytest.mark.asyncio
@pytest.mark.parametrize("status,payload", [(401, {"message": "Invalid token"}), (403, {"message": "Not permitted"}), (302, b""), (200, b"<html>Sign in</html>"), (200, {"error": "Rejected"}), (200, False), (200, None), (200, {"success": False}), (200, b"{invalid")])
async def test_reads_do_not_claim_success_for_errors(transport, status, payload):
    seen, replies = transport
    replies.append((status, payload))
    result = await run("list_locations")
    assert result["success"] is False and len(seen) == 1


@pytest.mark.asyncio
async def test_provider_rejection_is_preserved_and_token_redacted(transport):
    _, replies = transport
    replies.append((403, {"message": "Token rejected: " + AUTH["permanent_token"]}))
    result = await run("list_locations")
    assert "Token rejected" in result["error"]
    assert AUTH["permanent_token"] not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("status,payload", [(500, {"message": "Unavailable"}), (200, b"{invalid")])
async def test_ambiguous_writes_are_not_retried(transport, status, payload):
    seen, replies = transport
    replies.append((status, payload))
    result = await run("start_timesheet", {"employee_id": 17, "area_id": 2})
    assert result["status"] == "unknown" and result["write_outcome"] == "unverified"
    assert result["success"] is False and len(seen) == 1


@pytest.mark.asyncio
async def test_oversized_response_fails_closed(transport):
    _, replies = transport
    replies.append((200, b" " * (4 * 1024 * 1024 + 1)))
    result = await run("list_locations")
    assert result["success"] is False


def test_leave_dates_are_valid_and_ordered():
    for start, end in [("2022/02/30", "2022/03/01"), ("2022/03/02", "2022/03/01")]:
        with pytest.raises(ValueError):
            deputy.CreateLeave(employee_id=1, date_start=start, date_end=end, status=0, approval_comment="", overlapping_rosters_action=0)


def test_connection_evidence_names_the_tenants_locations():
    evidence = deputy.DeputyNode.connection_evidence
    assert evidence.operation == "list_locations" and evidence.proves == "account"
    assert "CompanyName" in evidence.label_keys
