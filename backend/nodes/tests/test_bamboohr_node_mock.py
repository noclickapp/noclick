"""
Mock tests for the BambooHR node.

Exercises every operation with mocked HTTP responses (no live API calls):
- Auth: API-key HTTP Basic (base64 "key:x") vs OAuth Bearer, subdomain base URL,
  and the mandatory Accept: application/json header
- Employees, tables, time off (with the PUT add-request quirk + note format),
  time tracking, datasets/reports, files, metadata, webhooks
- The on_field_change push trigger: registration body + private-key capture, and
  a simulated signed delivery end-to-end (HMAC verify accepts genuine, rejects
  tampered body / wrong key, and translates the payload into the trigger event)
- Dynamic dropdowns (employee / time-off type) and error handling
"""

import base64
import json
import hashlib
import hmac
import pytest
from unittest.mock import Mock, patch, AsyncMock

from nodes.bamboohr_node import (
    BambooHRNode,
    BambooHRNodeConfig,
    BambooHRApiKeyCredential,
    BambooHROAuthCredential,
    BambooGetEmployeeConfig,
    BambooGetDirectoryConfig,
    BambooAddEmployeeConfig,
    BambooUpdateEmployeeConfig,
    BambooGetChangedEmployeesConfig,
    BambooGetEmployeePhotoConfig,
    BambooGetTableRowsConfig,
    BambooAddTableRowConfig,
    BambooUpdateTableRowConfig,
    BambooDeleteTableRowConfig,
    BambooListTimeOffRequestsConfig,
    BambooAddTimeOffRequestConfig,
    BambooChangeRequestStatusConfig,
    BambooWhosOutConfig,
    BambooListTimeOffTypesConfig,
    BambooClockInConfig,
    BambooListDatasetsConfig,
    BambooGetReportConfig,
    BambooCustomReportConfig,
    BambooListEmployeeFilesConfig,
    BambooUploadEmployeeFileConfig,
    BambooListFieldsConfig,
    BambooListWebhooksConfig,
    BambooCreateWebhookConfig,
    BambooListMonitorFieldsConfig,
    BambooOnFieldChangeConfig,
)


@pytest.fixture
def api_key_credentials():
    return BambooHRApiKeyCredential(subdomain="acme", api_key="SECRETKEY")


@pytest.fixture
def oauth_credentials():
    return BambooHROAuthCredential(
        subdomain="acme",
        access_token="oauth-access-token",
        refresh_token="oauth-refresh-token",
        expires_at="2099-12-31T23:59:59Z",
        name="Test User",
        email="test@example.com",
    )


def create_node(config):
    return BambooHRNode(
        node_id="test-bamboohr-node",
        node_type="automation-bamboohr",
        node_data={},
        config=config,
        sio=Mock(),
        sid="test-sid",
        workflow_id="test-workflow",
        user_id="test-user",
    )


def create_mock_client(status_code=200, json_data=None, headers=None, content=b"{}"):
    mock_response = Mock()
    mock_response.status_code = status_code
    mock_response.text = ""
    mock_response.content = content
    mock_response.headers = headers if headers is not None else {"content-type": "application/json"}
    mock_response.json = lambda: (json_data if json_data is not None else {})

    mock_client = Mock()
    mock_client.calls = []

    async def async_request(*args, **kwargs):
        mock_client.calls.append(kwargs)
        return mock_response

    mock_client.request = async_request

    async def aenter(self):
        return mock_client

    async def aexit(self, *a):
        return None

    mock_client.__aenter__ = aenter
    mock_client.__aexit__ = aexit
    return mock_client


def last(mock_client):
    return mock_client.calls[-1]


async def _run(config, credentials, mock_client):
    node = create_node(BambooHRNodeConfig(config=config, credentials=credentials))
    with patch("nodes.bamboohr_node.httpx.AsyncClient", return_value=mock_client):
        return await node.execute({})


# ============================================================================
# Authentication
# ============================================================================


class TestBambooHRAuth:
    @pytest.mark.asyncio
    async def test_api_key_uses_basic_auth(self, api_key_credentials):
        mc = create_mock_client(200, {"employees": []})
        await _run(BambooGetDirectoryConfig(), api_key_credentials, mc)
        expected = "Basic " + base64.b64encode(b"SECRETKEY:x").decode()
        assert last(mc)["headers"]["Authorization"] == expected
        assert last(mc)["headers"]["Accept"] == "application/json"

    @pytest.mark.asyncio
    async def test_base_url_includes_subdomain(self, api_key_credentials):
        mc = create_mock_client(200, {"employees": []})
        await _run(BambooGetDirectoryConfig(), api_key_credentials, mc)
        assert last(mc)["url"] == "https://api.bamboohr.com/api/gateway.php/acme/v1/employees/directory"

    @pytest.mark.asyncio
    async def test_oauth_uses_bearer(self, oauth_credentials):
        mc = create_mock_client(200, {"employees": []})
        # OAuth path: token not expired (far-future), so no refresh call is made.
        with patch("nodes.core.oauth_refresh.ensure_fresh_oauth_token", new=AsyncMock(return_value="oauth-access-token")):
            await _run(BambooGetDirectoryConfig(), oauth_credentials, mc)
        assert last(mc)["headers"]["Authorization"] == "Bearer oauth-access-token"

    @pytest.mark.asyncio
    async def test_missing_credentials_raises(self):
        node = create_node(BambooHRNodeConfig(config=BambooGetDirectoryConfig(), credentials=None))
        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})


# ============================================================================
# Employees + tables
# ============================================================================


class TestBambooHREmployees:
    @pytest.mark.asyncio
    async def test_get_employee(self, api_key_credentials):
        mc = create_mock_client(200, {"id": "42", "jobTitle": "Engineer"})
        await _run(BambooGetEmployeeConfig(employee_id="42", fields="jobTitle,department"), api_key_credentials, mc)
        call = last(mc)
        assert call["method"] == "GET"
        assert call["url"].endswith("/employees/42")
        assert call["params"]["fields"] == "jobTitle,department"

    @pytest.mark.asyncio
    async def test_add_employee(self, api_key_credentials):
        mc = create_mock_client(201, {})
        await _run(BambooAddEmployeeConfig(first_name="Ada", last_name="Lovelace", fields_json='{"jobTitle":"Engineer"}'), api_key_credentials, mc)
        call = last(mc)
        assert call["method"] == "POST"
        assert call["url"].endswith("/employees/")
        assert call["json"] == {"firstName": "Ada", "lastName": "Lovelace", "jobTitle": "Engineer"}

    @pytest.mark.asyncio
    async def test_update_employee(self, api_key_credentials):
        mc = create_mock_client(200, {})
        await _run(BambooUpdateEmployeeConfig(employee_id="0", fields_json='{"jobTitle":"Lead"}'), api_key_credentials, mc)
        call = last(mc)
        assert call["method"] == "POST"
        assert call["url"].endswith("/employees/0")
        assert call["json"] == {"jobTitle": "Lead"}

    @pytest.mark.asyncio
    async def test_changed_employees(self, api_key_credentials):
        mc = create_mock_client(200, {})
        await _run(BambooGetChangedEmployeesConfig(since="2026-01-01T00:00:00Z", type="updated"), api_key_credentials, mc)
        call = last(mc)
        assert call["url"].endswith("/employees/changed")
        assert call["params"]["since"] == "2026-01-01T00:00:00Z"
        assert call["params"]["type"] == "updated"

    @pytest.mark.asyncio
    async def test_get_table_rows(self, api_key_credentials):
        mc = create_mock_client(200, [])
        await _run(BambooGetTableRowsConfig(employee_id="42", table_name="jobInfo"), api_key_credentials, mc)
        assert last(mc)["url"].endswith("/employees/42/tables/jobInfo")

    @pytest.mark.asyncio
    async def test_add_table_row(self, api_key_credentials):
        mc = create_mock_client(201, {})
        await _run(BambooAddTableRowConfig(employee_id="42", table_name="jobInfo", fields_json='{"date":"2026-01-01"}'), api_key_credentials, mc)
        call = last(mc)
        assert call["method"] == "POST"
        assert "/gateway.php/acme/v1/employees/42/tables/jobInfo" in call["url"]

    @pytest.mark.asyncio
    async def test_update_table_row(self, api_key_credentials):
        mc = create_mock_client(200, {})
        await _run(BambooUpdateTableRowConfig(employee_id="42", table_name="jobInfo", row_id="7", fields_json='{"x":1}'), api_key_credentials, mc)
        call = last(mc)
        assert call["method"] == "PUT"
        assert "/v1/employees/42/tables/jobInfo/7" in call["url"]

    @pytest.mark.asyncio
    async def test_delete_table_row(self, api_key_credentials):
        mc = create_mock_client(200, {}, headers={"content-type": "text/plain"}, content=b"")
        await _run(BambooDeleteTableRowConfig(employee_id="42", table_name="jobInfo", row_id="7"), api_key_credentials, mc)
        assert last(mc)["method"] == "DELETE"


# ============================================================================
# Time off
# ============================================================================


class TestBambooHRTimeOff:
    @pytest.mark.asyncio
    async def test_list_requests(self, api_key_credentials):
        mc = create_mock_client(200, [])
        await _run(BambooListTimeOffRequestsConfig(start="2026-01-01", end="2026-01-31", status="approved"), api_key_credentials, mc)
        call = last(mc)
        assert call["url"].endswith("/time_off/requests/")
        assert call["params"]["start"] == "2026-01-01"
        assert call["params"]["status"] == "approved"

    @pytest.mark.asyncio
    async def test_add_request_uses_put(self, api_key_credentials):
        mc = create_mock_client(201, {})
        await _run(BambooAddTimeOffRequestConfig(employee_id="42", start="2026-02-01", end="2026-02-03", time_off_type_id="8", amount="24", status="requested", notes="vacay"), api_key_credentials, mc)
        call = last(mc)
        assert call["method"] == "PUT"  # BambooHR quirk: add-request is a PUT
        assert call["url"].endswith("/employees/42/time_off/request/")
        assert call["json"]["timeOffTypeId"] == "8"
        assert call["json"]["notes"] == [{"from": "employee", "note": "vacay"}]

    @pytest.mark.asyncio
    async def test_change_status(self, api_key_credentials):
        mc = create_mock_client(200, {})
        await _run(BambooChangeRequestStatusConfig(request_id="99", status="approved", note="ok"), api_key_credentials, mc)
        call = last(mc)
        assert call["method"] == "PUT"
        assert call["url"].endswith("/time_off/requests/99/status/")
        assert call["json"] == {"status": "approved", "note": "ok"}

    @pytest.mark.asyncio
    async def test_whos_out(self, api_key_credentials):
        mc = create_mock_client(200, [])
        await _run(BambooWhosOutConfig(start="2026-01-01", end="2026-01-31"), api_key_credentials, mc)
        assert last(mc)["url"].endswith("/time_off/whos_out/")

    @pytest.mark.asyncio
    async def test_list_types(self, api_key_credentials):
        mc = create_mock_client(200, {"timeOffTypes": []})
        await _run(BambooListTimeOffTypesConfig(), api_key_credentials, mc)
        assert last(mc)["url"].endswith("/meta/time_off/types/")


# ============================================================================
# Time tracking, reports, files, meta, webhook management
# ============================================================================


class TestBambooHRMisc:
    @pytest.mark.asyncio
    async def test_binary_response_returns_binary_output(self, api_key_credentials):
        """Photo/file/PDF bodies come back as a BinaryOutput marker (resolved to a
        file reference by the executor) — never base64 encoded into the output."""
        from nodes.core.binary_output import BinaryOutput
        mc = create_mock_client(200, None, headers={"content-type": "image/jpeg"}, content=b"\xff\xd8\xff jpeg bytes")
        res = await _run(BambooGetEmployeePhotoConfig(employee_id="42", size="small"), api_key_credentials, mc)
        assert res["status"] == "success"
        out = res["data"]["file"]
        assert isinstance(out, BinaryOutput)
        assert out.data == b"\xff\xd8\xff jpeg bytes"
        assert out.content_type == "image/jpeg"
        assert out.filename.endswith(".jpg")

    @pytest.mark.asyncio
    async def test_clock_in(self, api_key_credentials):
        mc = create_mock_client(200, {})
        await _run(BambooClockInConfig(employee_id="42", fields_json='{"note":"start"}'), api_key_credentials, mc)
        call = last(mc)
        assert call["method"] == "POST"
        assert call["url"].endswith("/timesheet/clock_in")
        assert call["json"] == {"employeeId": "42", "note": "start"}

    @pytest.mark.asyncio
    async def test_list_datasets(self, api_key_credentials):
        mc = create_mock_client(200, {"datasets": []})
        await _run(BambooListDatasetsConfig(), api_key_credentials, mc)
        assert last(mc)["url"].endswith("/datasets")

    @pytest.mark.asyncio
    async def test_get_report(self, api_key_credentials):
        mc = create_mock_client(200, {})
        await _run(BambooGetReportConfig(report_id="12", report_format="JSON"), api_key_credentials, mc)
        call = last(mc)
        assert call["url"].endswith("/reports/12")
        assert call["params"]["format"] == "JSON"

    @pytest.mark.asyncio
    async def test_custom_report(self, api_key_credentials):
        mc = create_mock_client(200, {})
        await _run(BambooCustomReportConfig(fields="firstName,lastName,jobTitle", title="Roster"), api_key_credentials, mc)
        call = last(mc)
        assert call["method"] == "POST"
        assert call["url"].endswith("/reports/custom")
        assert call["json"]["fields"] == ["firstName", "lastName", "jobTitle"]
        assert call["params"]["format"] == "JSON"

    @pytest.mark.asyncio
    async def test_list_employee_files(self, api_key_credentials):
        mc = create_mock_client(200, {})
        await _run(BambooListEmployeeFilesConfig(employee_id="42"), api_key_credentials, mc)
        assert last(mc)["url"].endswith("/employees/42/files/view/")

    @pytest.mark.asyncio
    async def test_upload_employee_file_multipart(self, api_key_credentials):
        mc = create_mock_client(201, {})
        content_b64 = base64.b64encode(b"hello").decode()
        await _run(BambooUploadEmployeeFileConfig(employee_id="42", file_name="a.txt", category_id="3", content_base64=content_b64, share="yes"), api_key_credentials, mc)
        call = last(mc)
        assert call["method"] == "POST"
        assert call["files"]["file"][0] == "a.txt"
        assert call["files"]["file"][1] == b"hello"
        assert call["data"]["category"] == "3"

    @pytest.mark.asyncio
    async def test_upload_file_bad_base64(self, api_key_credentials):
        mc = create_mock_client(201, {})
        res = await _run(BambooUploadEmployeeFileConfig(employee_id="42", file_name="a.txt", category_id="3", content_base64="!!notb64!!", share="yes"), api_key_credentials, mc)
        assert res["status"] == "error"
        assert res["status_code"] == 400

    @pytest.mark.asyncio
    async def test_list_fields(self, api_key_credentials):
        mc = create_mock_client(200, [])
        await _run(BambooListFieldsConfig(), api_key_credentials, mc)
        assert last(mc)["url"].endswith("/meta/fields/")

    @pytest.mark.asyncio
    async def test_list_webhooks(self, api_key_credentials):
        mc = create_mock_client(200, {})
        await _run(BambooListWebhooksConfig(), api_key_credentials, mc)
        assert last(mc)["url"].endswith("/webhooks/")

    @pytest.mark.asyncio
    async def test_create_webhook(self, api_key_credentials):
        mc = create_mock_client(201, {"id": 5})
        await _run(BambooCreateWebhookConfig(definition_json='{"name":"w","monitorFields":["jobTitle"],"url":"https://x","format":"json"}'), api_key_credentials, mc)
        call = last(mc)
        assert call["method"] == "POST"
        assert call["json"]["monitorFields"] == ["jobTitle"]

    @pytest.mark.asyncio
    async def test_list_monitor_fields(self, api_key_credentials):
        mc = create_mock_client(200, {})
        await _run(BambooListMonitorFieldsConfig(), api_key_credentials, mc)
        assert last(mc)["url"].endswith("/webhooks/monitor_fields/")


# ============================================================================
# Error handling + non-JSON responses
# ============================================================================


class TestBambooHRErrors:
    @pytest.mark.asyncio
    async def test_api_error_surfaced(self, api_key_credentials):
        mc = create_mock_client(404, {"message": "Employee not found"})
        res = await _run(BambooGetEmployeeConfig(employee_id="999", fields="jobTitle"), api_key_credentials, mc)
        assert res["status"] == "error"
        assert res["status_code"] == 404
        assert "not found" in res["error"].lower()

    @pytest.mark.asyncio
    async def test_bad_json_field(self, api_key_credentials):
        mc = create_mock_client(200, {})
        node = create_node(BambooHRNodeConfig(config=BambooUpdateEmployeeConfig(employee_id="0", fields_json="not-json"), credentials=api_key_credentials))
        with patch("nodes.bamboohr_node.httpx.AsyncClient", return_value=mc):
            with pytest.raises(ValueError, match="must be valid JSON"):
                await node.execute({})


# ============================================================================
# Dynamic dropdowns
# ============================================================================


class TestBambooHRDropdowns:
    @pytest.mark.asyncio
    async def test_employee_dropdown(self, api_key_credentials):
        mc = create_mock_client(200, {"employees": [{"id": 1, "displayName": "Ada Lovelace"}]})
        with patch("nodes.bamboohr_node.httpx.AsyncClient", return_value=mc):
            res = await BambooHRNode.load_field_options("employee_id", api_key_credentials.model_dump())
        values = [o["value"] for o in res["options"]]
        assert "0" in values and "1" in values  # includes "Me" + directory
        assert any(o["label"] == "Ada Lovelace" for o in res["options"])

    @pytest.mark.asyncio
    async def test_time_off_type_dropdown(self, api_key_credentials):
        mc = create_mock_client(200, {"timeOffTypes": [{"id": 8, "name": "Vacation"}]})
        with patch("nodes.bamboohr_node.httpx.AsyncClient", return_value=mc):
            res = await BambooHRNode.load_field_options("time_off_type_id", api_key_credentials.model_dump())
        assert res["options"] == [{"value": "8", "label": "Vacation"}]

    @pytest.mark.asyncio
    async def test_webhook_dropdown(self, api_key_credentials):
        mc = create_mock_client(200, {"webhooks": [{"id": 42, "name": "Job change hook"}]})
        with patch("nodes.bamboohr_node.httpx.AsyncClient", return_value=mc):
            res = await BambooHRNode.load_field_options("webhook_id", api_key_credentials.model_dump())
        assert res["options"] == [{"value": "42", "label": "Job change hook"}]

    @pytest.mark.asyncio
    async def test_category_dropdown(self, api_key_credentials):
        mc = create_mock_client(200, {"categories": [{"id": 3, "name": "Contracts"}]})
        with patch("nodes.bamboohr_node.httpx.AsyncClient", return_value=mc):
            res = await BambooHRNode.load_field_options("category_id", api_key_credentials.model_dump())
        assert res["options"] == [{"value": "3", "label": "Contracts"}]

    @pytest.mark.asyncio
    async def test_dropdown_no_credential(self):
        res = await BambooHRNode.load_field_options("employee_id", {})
        assert res == {"options": []}


# ============================================================================
# Push trigger (on_field_change)
# ============================================================================


class TestBambooHRTrigger:
    @pytest.mark.asyncio
    async def test_trigger_manual_run_passthrough(self, api_key_credentials):
        node = create_node(BambooHRNodeConfig(config=BambooOnFieldChangeConfig(monitor_fields="jobTitle", webhook_url="https://x.hooks.example.test"), credentials=api_key_credentials))
        # No HTTP: a manual run of the trigger just echoes inputs.
        res = await node.execute({"foo": "bar"})
        assert res["operation"] == "on_field_change"
        assert res["data"]["foo"] == "bar"

    @pytest.mark.asyncio
    async def test_register_webhook_builds_body_and_captures_key(self, api_key_credentials):
        mc = create_mock_client(201, {"id": 77, "privateKey": "PRIVKEY"})
        with patch("nodes.bamboohr_node.httpx.AsyncClient", return_value=mc):
            reg = await BambooHRNode._register_external_webhook(
                webhook_url="https://abc.hooks.example.test",
                credential=api_key_credentials.model_dump(),
                config={"operation": "on_field_change", "monitor_fields": "jobTitle,department"},
                node_id="n1",
            )
        call = last(mc)
        assert call["method"] == "POST"
        assert call["url"].endswith("/webhooks/")
        assert call["json"]["monitorFields"] == ["jobTitle", "department"]
        assert call["json"]["url"] == "https://abc.hooks.example.test"
        assert reg == {"external_webhook_id": "77", "signing_secret": "PRIVKEY"}

    @pytest.mark.asyncio
    async def test_decomposed_triggers_use_preset_fields(self, api_key_credentials):
        """Each decomposed trigger registers with its preset (non-permission-gated)
        field bundle; the generic on_field_change uses the user's monitor_fields."""
        from nodes.bamboohr_node import TRIGGER_MONITOR_FIELDS
        for op, fields in TRIGGER_MONITOR_FIELDS.items():
            mc = create_mock_client(201, {"id": 1, "privateKey": "K"})
            with patch("nodes.bamboohr_node.httpx.AsyncClient", return_value=mc):
                await BambooHRNode._register_external_webhook(
                    webhook_url="https://x.hooks.example.test",
                    credential=api_key_credentials.model_dump(),
                    # a decomposed trigger ignores any monitor_fields and uses its preset
                    config={"operation": op, "monitor_fields": "ignored"},
                    node_id="n",
                )
            assert last(mc)["json"]["monitorFields"] == fields, op

    def test_verify_signature_valid(self):
        secret = "PRIVKEY"
        body = b'{"employees":[{"id":1}]}'
        timestamp = "2026-01-01T00:00:00Z"
        sig = hmac.new(secret.encode(), body + timestamp.encode(), hashlib.sha256).hexdigest()
        headers = {"x-bamboohr-signature": sig, "x-bamboohr-timestamp": timestamp}
        assert BambooHRNode.verify_webhook_signature(body, headers, {"signing_secret": secret}) is True

    def test_verify_signature_invalid(self):
        headers = {"x-bamboohr-signature": "deadbeef", "x-bamboohr-timestamp": "2026-01-01T00:00:00Z"}
        assert BambooHRNode.verify_webhook_signature(b"body", headers, {"signing_secret": "PRIVKEY"}) is False

    def test_simulated_signed_delivery_end_to_end(self):
        """Simulate BambooHR's exact signed POST end-to-end: verify accepts the
        genuine delivery, rejects a tampered body and a wrong key, and the
        payload is translated into the workflow trigger event."""
        secret = "wh_priv"
        payload = {"employees": [{"id": "116", "changedFields": ["jobTitle"], "fields": {"jobTitle": "Fired"}}]}
        body = json.dumps(payload).encode()
        ts = "2026-07-14T10:00:00Z"
        sig = hmac.new(secret.encode(), body + ts.encode(), hashlib.sha256).hexdigest()
        hdr = {"X-BambooHR-Signature": sig, "X-BambooHR-Timestamp": ts}
        cfg = {"signing_secret": secret}
        assert BambooHRNode.verify_webhook_signature(body, hdr, cfg) is True
        assert BambooHRNode.verify_webhook_signature(body + b"x", hdr, cfg) is False  # tampered
        assert BambooHRNode.verify_webhook_signature(body, hdr, {"signing_secret": "evil"}) is False  # wrong key
        node = BambooHRNode(node_id="t", node_type="automation-bamboohr", node_data={}, config=None,
                            sio=Mock(), sid="s", workflow_id="w", user_id="u")
        event = node.resolve_agent_event({"data": payload})
        assert json.loads(event["text"])["employees"][0]["id"] == "116"

    def test_verify_signature_missing_headers(self):
        assert BambooHRNode.verify_webhook_signature(b"body", {}, {"signing_secret": "PRIVKEY"}) is False
