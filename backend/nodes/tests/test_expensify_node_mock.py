"""
Mock tests for the Expensify Integration Server API node.

Exercises every operation with mocked HTTP responses (no live API calls):
- Exports: export reports, download file, reconciliation export
- Create: report, expenses, policy, expense rules
- Get: policy details, policy list, domain card list
- Update: policy, report status, expense rules, tag approvers,
  advanced employee updater, employees (deprecated)
- Error handling: API errors, Expensify job errors, missing credentials
- Dynamic options: policy (workspace) dropdown
"""

import json

import pytest
from unittest.mock import Mock, patch

from nodes.expensify_node import (
    ExpensifyNode,
    ExpensifyNodeConfig,
    ExpensifyPartnerCredential,
    ExpensifyExportReportsConfig,
    ExpensifyDownloadFileConfig,
    ExpensifyReconciliationConfig,
    ExpensifyCreateReportConfig,
    ExpensifyCreateExpensesConfig,
    ExpensifyCreatePolicyConfig,
    ExpensifyCreateExpenseRulesConfig,
    ExpensifyGetPolicyConfig,
    ExpensifyGetPolicyListConfig,
    ExpensifyGetDomainCardListConfig,
    ExpensifyUpdatePolicyConfig,
    ExpensifyUpdateReportStatusConfig,
    ExpensifyUpdateExpenseRulesConfig,
    ExpensifyUpdateTagApproversConfig,
    ExpensifyAdvancedEmployeeUpdaterConfig,
    ExpensifyOnNewReportConfig,
)


@pytest.fixture
def partner_credentials():
    return ExpensifyPartnerCredential(
        partner_user_id="partner_id_123", partner_user_secret="secret_456"
    )


def create_expensify_node(config):
    return ExpensifyNode(
        node_id="test-expensify-node",
        node_type="automation-expensify",
        node_data={},
        config=config,
        sio=Mock(),
        sid="test-sid",
        workflow_id="test-workflow",
        user_id="test-user",
    )


def create_mock_response(status_code=200, json_data=None, text=""):
    mock_response = Mock()
    mock_response.status_code = status_code
    mock_response.text = text
    if json_data is not None:
        mock_response.json = lambda: json_data
    else:
        def _raise():
            raise ValueError("no json")
        mock_response.json = _raise
    return mock_response


def create_mock_client(status_code=200, json_data=None, text=""):
    """Mock httpx.AsyncClient whose .post() returns the mock response and which
    works as an async context manager."""
    mock_response = create_mock_response(status_code, json_data, text)
    mock_client = Mock()

    async def async_post(*args, **kwargs):
        return mock_response

    mock_client.post = async_post

    async def aenter(self):
        return mock_client

    async def aexit(self, *args):
        return None

    mock_client.__aenter__ = aenter
    mock_client.__aexit__ = aexit
    return mock_client


# ============================================================================
# Exports
# ============================================================================


class TestExpensifyExportsMock:
    @pytest.mark.asyncio
    async def test_export_reports(self, partner_credentials):
        config = ExpensifyNodeConfig(
            config=ExpensifyExportReportsConfig(
                file_extension="csv", report_state="APPROVED", start_date="2026-01-01"
            ),
            credentials=partner_credentials,
        )
        node = create_expensify_node(config)
        mock_client = create_mock_client(200, {"responseCode": 200, "filename": "export_abc.csv"})
        with patch("nodes.expensify_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "export_reports"
        assert result["data"]["filename"] == "export_abc.csv"

    @pytest.mark.asyncio
    async def test_download_file(self, partner_credentials):
        config = ExpensifyNodeConfig(
            config=ExpensifyDownloadFileConfig(file_name="export_abc.csv"),
            credentials=partner_credentials,
        )
        node = create_expensify_node(config)
        # Download returns raw file bytes, not JSON.
        mock_client = create_mock_client(200, json_data=None, text="reportName,total\nTrip,100\n")
        with patch("nodes.expensify_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "download_file"
        assert "reportName" in result["data"]["file_contents"]

    @pytest.mark.asyncio
    async def test_reconciliation_export(self, partner_credentials):
        config = ExpensifyNodeConfig(
            config=ExpensifyReconciliationConfig(
                domain_name="acme.com", start_date="2026-01-01", end_date="2026-01-31"
            ),
            credentials=partner_credentials,
        )
        node = create_expensify_node(config)
        mock_client = create_mock_client(200, {"responseCode": 200, "filename": "recon_xyz.csv"})
        with patch("nodes.expensify_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "reconciliation_export"
        assert result["data"]["filename"] == "recon_xyz.csv"


# ============================================================================
# Create
# ============================================================================


class TestExpensifyCreateMock:
    @pytest.mark.asyncio
    async def test_create_report(self, partner_credentials):
        config = ExpensifyNodeConfig(
            config=ExpensifyCreateReportConfig(
                policy_id="POL123",
                employee_email="user@acme.com",
                report_title="January Travel",
                expenses_json='[{"created":"2026-01-01","merchant":"Cab","amount":1500,"currency":"USD"}]',
            ),
            credentials=partner_credentials,
        )
        node = create_expensify_node(config)
        mock_client = create_mock_client(200, {"responseCode": 200, "reportID": "R987"})
        with patch("nodes.expensify_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_report"
        assert result["data"]["reportID"] == "R987"

    @pytest.mark.asyncio
    async def test_create_expenses(self, partner_credentials):
        config = ExpensifyNodeConfig(
            config=ExpensifyCreateExpensesConfig(
                employee_email="user@acme.com",
                expenses_json='[{"created":"2026-01-01","merchant":"Lunch","amount":2200,"currency":"USD"}]',
            ),
            credentials=partner_credentials,
        )
        node = create_expensify_node(config)
        mock_client = create_mock_client(200, {"responseCode": 200, "transactionIDList": ["T1"]})
        with patch("nodes.expensify_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_expenses"
        assert result["data"]["transactionIDList"] == ["T1"]

    @pytest.mark.asyncio
    async def test_create_policy(self, partner_credentials):
        config = ExpensifyNodeConfig(
            config=ExpensifyCreatePolicyConfig(policy_name="New Team", policy_plan="corporate"),
            credentials=partner_credentials,
        )
        node = create_expensify_node(config)
        mock_client = create_mock_client(200, {"responseCode": 200, "policyID": "POL_NEW"})
        with patch("nodes.expensify_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_policy"
        assert result["data"]["policyID"] == "POL_NEW"

    @pytest.mark.asyncio
    async def test_create_expense_rules(self, partner_credentials):
        config = ExpensifyNodeConfig(
            config=ExpensifyCreateExpenseRulesConfig(
                policy_id="POL123",
                employee_email="user@acme.com",
                rules_json='[{"tag":"Travel","applyWhen":[{"field":"merchant","value":"Uber"}]}]',
            ),
            credentials=partner_credentials,
        )
        node = create_expensify_node(config)
        mock_client = create_mock_client(200, {"responseCode": 200, "ruleIDs": ["RULE1"]})
        with patch("nodes.expensify_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_expense_rules"


# ============================================================================
# Get
# ============================================================================


class TestExpensifyGetMock:
    @pytest.mark.asyncio
    async def test_get_policy(self, partner_credentials):
        config = ExpensifyNodeConfig(
            config=ExpensifyGetPolicyConfig(policy_id_list="POL123,POL456", fields="categories,tags"),
            credentials=partner_credentials,
        )
        node = create_expensify_node(config)
        mock_client = create_mock_client(
            200, {"responseCode": 200, "policyInfo": {"POL123": {"name": "Acme"}}}
        )
        with patch("nodes.expensify_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_policy"
        assert "POL123" in result["data"]["policyInfo"]

    @pytest.mark.asyncio
    async def test_get_policy_list(self, partner_credentials):
        config = ExpensifyNodeConfig(
            config=ExpensifyGetPolicyListConfig(admin_only="true"),
            credentials=partner_credentials,
        )
        node = create_expensify_node(config)
        mock_client = create_mock_client(
            200, {"responseCode": 200, "policyList": [{"id": "POL123", "name": "Acme"}]}
        )
        with patch("nodes.expensify_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_policy_list"
        assert result["data"]["policyList"][0]["id"] == "POL123"

    @pytest.mark.asyncio
    async def test_get_domain_card_list(self, partner_credentials):
        config = ExpensifyNodeConfig(
            config=ExpensifyGetDomainCardListConfig(domain_name="acme.com"),
            credentials=partner_credentials,
        )
        node = create_expensify_node(config)
        mock_client = create_mock_client(
            200, {"responseCode": 200, "cardList": [{"cardID": "C1", "bank": "Chase"}]}
        )
        with patch("nodes.expensify_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_domain_card_list"
        assert result["data"]["cardList"][0]["cardID"] == "C1"


# ============================================================================
# Update
# ============================================================================


class TestExpensifyUpdateMock:
    @pytest.mark.asyncio
    async def test_update_policy(self, partner_credentials):
        config = ExpensifyNodeConfig(
            config=ExpensifyUpdatePolicyConfig(
                policy_id="POL123",
                update_type="categories",
                data_json='{"action":"merge","categories":[{"name":"Travel"}]}',
            ),
            credentials=partner_credentials,
        )
        node = create_expensify_node(config)
        mock_client = create_mock_client(200, {"responseCode": 200})
        with patch("nodes.expensify_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_policy"

    @pytest.mark.asyncio
    async def test_update_report_status(self, partner_credentials):
        config = ExpensifyNodeConfig(
            config=ExpensifyUpdateReportStatusConfig(report_id_list="R1,R2"),
            credentials=partner_credentials,
        )
        node = create_expensify_node(config)
        mock_client = create_mock_client(200, {"responseCode": 200, "reportList": ["R1", "R2"]})
        with patch("nodes.expensify_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_report_status"

    @pytest.mark.asyncio
    async def test_update_expense_rules(self, partner_credentials):
        config = ExpensifyNodeConfig(
            config=ExpensifyUpdateExpenseRulesConfig(
                policy_id="POL123",
                employee_email="user@acme.com",
                rule_id="0",
                rules_json='{"tag":"Travel"}',
            ),
            credentials=partner_credentials,
        )
        node = create_expensify_node(config)
        mock_client = create_mock_client(200, {"responseCode": 200})
        with patch("nodes.expensify_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_expense_rules"

    @pytest.mark.asyncio
    async def test_update_tag_approvers(self, partner_credentials):
        config = ExpensifyNodeConfig(
            config=ExpensifyUpdateTagApproversConfig(
                policy_id="POL123",
                approvers_json='[{"tag":"Marketing","approver":"lead@acme.com"}]',
            ),
            credentials=partner_credentials,
        )
        node = create_expensify_node(config)
        mock_client = create_mock_client(200, {"responseCode": 200})
        with patch("nodes.expensify_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_tag_approvers"

    @pytest.mark.asyncio
    async def test_advanced_employee_updater(self, partner_credentials):
        config = ExpensifyNodeConfig(
            config=ExpensifyAdvancedEmployeeUpdaterConfig(
                policy_id="POL123",
                employees_json='[{"email":"user@acme.com","managerEmail":"boss@acme.com"}]',
            ),
            credentials=partner_credentials,
        )
        node = create_expensify_node(config)
        mock_client = create_mock_client(200, {"responseCode": 200})
        with patch("nodes.expensify_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "advanced_employee_updater"


# ============================================================================
# Error handling
# ============================================================================


class TestExpensifyErrorHandlingMock:
    @pytest.mark.asyncio
    async def test_http_error(self, partner_credentials):
        config = ExpensifyNodeConfig(
            config=ExpensifyGetPolicyListConfig(), credentials=partner_credentials
        )
        node = create_expensify_node(config)
        mock_client = create_mock_client(429, json_data=None, text="Too Many Requests")
        with patch("nodes.expensify_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "error"
        assert result["status_code"] == 429
        assert "Too Many" in str(result["error"])

    @pytest.mark.asyncio
    async def test_job_error_response_code(self, partner_credentials):
        """A 200 with a non-200 responseCode is an Expensify job failure."""
        config = ExpensifyNodeConfig(
            config=ExpensifyGetPolicyConfig(policy_id_list="BAD"),
            credentials=partner_credentials,
        )
        node = create_expensify_node(config)
        mock_client = create_mock_client(
            200, {"responseCode": 404, "responseMessage": "Policy not found"}
        )
        with patch("nodes.expensify_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "error"
        assert result["status_code"] == 404
        assert "not found" in str(result["error"]).lower()

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        config = ExpensifyNodeConfig(config=ExpensifyGetPolicyListConfig(), credentials=None)
        node = create_expensify_node(config)
        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})

    @pytest.mark.asyncio
    async def test_invalid_json_field(self, partner_credentials):
        config = ExpensifyNodeConfig(
            config=ExpensifyCreateExpensesConfig(
                employee_email="user@acme.com", expenses_json="not valid json"
            ),
            credentials=partner_credentials,
        )
        node = create_expensify_node(config)
        with pytest.raises(ValueError, match="not valid JSON"):
            await node.execute({})


# ============================================================================
# Dynamic options
# ============================================================================


class TestExpensifyDynamicOptionsMock:
    @pytest.mark.asyncio
    async def test_load_policy_options_canonical_signature(self):
        # Handler calls (field_name, credential_data, context, page_token, search)
        # with credential_data pre-decrypted; the old (user_id, config_data,
        # credential_ids, pool) signature raised a TypeError in the config panel.
        with patch(
            "nodes.expensify_node._expensify_request",
            return_value={
                "status": "success",
                "data": {"policyList": [{"id": "POL123", "name": "Acme Workspace"}]},
            },
        ):
            result = await ExpensifyNode.load_field_options(
                field_name="policy_id",
                credential_data={"partner_user_id": "partner_id_123", "partner_user_secret": "secret_456"},
                context={},
            )
        assert result["options"][0] == {"value": "POL123", "label": "Acme Workspace"}

    @pytest.mark.asyncio
    async def test_load_options_unknown_field_and_no_credential(self):
        assert await ExpensifyNode.load_field_options(
            field_name="some_other_field", credential_data={"partner_user_id": "x"}
        ) == {"options": []}
        assert await ExpensifyNode.load_field_options(
            field_name="policy_id", credential_data={}
        ) == {"options": []}


# ============================================================================
# Payload shape
# ============================================================================


class TestExpensifyPayloadShape:
    @pytest.mark.asyncio
    async def test_credentials_embedded_in_payload(self, partner_credentials):
        """Partner credentials must be embedded inside the requestJobDescription
        form field, not sent as HTTP headers."""
        captured = {}
        config = ExpensifyNodeConfig(
            config=ExpensifyGetPolicyListConfig(), credentials=partner_credentials
        )
        node = create_expensify_node(config)

        mock_response = create_mock_response(200, {"responseCode": 200, "policyList": []})
        mock_client = Mock()

        async def async_post(*args, **kwargs):
            captured["data"] = kwargs.get("data")
            return mock_response

        mock_client.post = async_post

        async def aenter(self):
            return mock_client

        async def aexit(self, *a):
            return None

        mock_client.__aenter__ = aenter
        mock_client.__aexit__ = aexit

        with patch("nodes.expensify_node.httpx.AsyncClient", return_value=mock_client):
            await node.execute({})

        assert "requestJobDescription" in captured["data"]
        payload = json.loads(captured["data"]["requestJobDescription"])
        assert payload["credentials"]["partnerUserID"] == "partner_id_123"
        assert payload["credentials"]["partnerUserSecret"] == "secret_456"
        assert payload["type"] == "get"
        assert payload["inputSettings"]["type"] == "policyList"




# ============================================================================
# Trigger (poll-based: on_new_report) — two-step export + mixin dedup
# ============================================================================


REPORTS = [
    {"reportID": "R1", "reportName": "Jan Travel", "created": "2026-01-05", "status": "SUBMITTED"},
    {"reportID": "R2", "reportName": "Feb Travel", "created": "2026-02-05", "status": "SUBMITTED"},
    {"reportID": "R3", "reportName": "Mar Travel", "created": "2026-03-05", "status": "SUBMITTED"},
]


def create_two_step_client(reports, gen_response=None):
    """Mock httpx client for the poll trigger's two POSTs: the `file` job returns
    a generated filename; the `download` job returns the report JSON as raw text.
    Captures each request body for assertions."""
    calls = {"bodies": []}
    gen = gen_response if gen_response is not None else {"responseCode": 200, "filename": "poll_export.json"}
    file_resp = create_mock_response(200, json_data=gen)
    dl_resp = create_mock_response(200, json_data=None, text=json.dumps(reports))
    mock_client = Mock()

    async def async_post(*args, **kwargs):
        body = json.loads(kwargs.get("data", {}).get("requestJobDescription", "{}"))
        calls["bodies"].append(body)
        return dl_resp if body.get("type") == "download" else file_resp

    mock_client.post = async_post
    mock_client.__aenter__ = lambda self: _ident(mock_client)
    mock_client.__aexit__ = lambda self, *a: _none()
    return mock_client, calls


async def _ident(v):
    return v


async def _none():
    return None


async def _run_trigger(node, mock_client, state_store):
    """Execute the poll trigger with httpx + node state (mixin dedup) mocked."""

    async def fake_load_state(self):
        return dict(state_store)

    async def fake_save_state(self, state, **_):
        state_store.clear()
        state_store.update(state)

    with patch("nodes.expensify_node.httpx.AsyncClient", return_value=mock_client), patch.object(
        ExpensifyNode, "_load_node_state", fake_load_state
    ), patch.object(ExpensifyNode, "_save_node_state", fake_save_state):
        return await node.execute({})


class TestExpensifyResolveTriggerPayload:
    def test_poll_returns_none_wakeup(self):
        """The poll mixin returns None for the cron wake-up so execute() polls."""
        assert (
            ExpensifyNode.resolve_trigger_payload(
                {"x": 1}, {"operation": "on_new_report"}
            )
            is None
        )

    def test_base_passthrough_for_normal_op(self):
        from nodes.core.base import WorkflowNode

        payload = {"x": 1}
        assert WorkflowNode.resolve_trigger_payload(payload, {"operation": "get_policy_list"}) is payload


class TestExpensifyOnNewReportMock:
    @pytest.mark.asyncio
    async def test_poll_baselines_then_emits_new_and_dedupes(self, partner_credentials):
        node = create_expensify_node(
            ExpensifyNodeConfig(config=ExpensifyOnNewReportConfig(report_state="SUBMITTED"),
                                credentials=partner_credentials)
        )
        state: dict = {}

        # Poll 1: two existing reports -> baseline, emit nothing.
        client, _ = create_two_step_client(REPORTS[:2])
        r = await _run_trigger(node, client, state)
        assert r["status"] == "success" and r["operation"] == "on_new_report"
        assert r["new_count"] == 0 and r["items"] == []

        # Poll 2: a third report appears -> only R3 is emitted.
        client, _ = create_two_step_client(REPORTS)
        r = await _run_trigger(node, client, state)
        assert r["new_count"] == 1
        assert [x["reportID"] for x in r["items"]] == ["R3"]

        # Poll 3: same reports -> nothing new.
        client, _ = create_two_step_client(REPORTS)
        r = await _run_trigger(node, client, state)
        assert r["new_count"] == 0

    @pytest.mark.asyncio
    async def test_poll_runs_two_step_generate_then_download(self, partner_credentials):
        node = create_expensify_node(
            ExpensifyNodeConfig(config=ExpensifyOnNewReportConfig(report_state="APPROVED"),
                                credentials=partner_credentials)
        )
        client, calls = create_two_step_client(REPORTS)
        await _run_trigger(node, client, {"seen_ids": ["baseline"]})
        # Exactly two calls: a file/combinedReportData export, then a download.
        assert len(calls["bodies"]) == 2
        gen, dl = calls["bodies"]
        assert gen["type"] == "file"
        assert gen["inputSettings"]["type"] == "combinedReportData"
        assert gen["inputSettings"]["filters"]["reportState"] == "APPROVED"
        assert dl["type"] == "download"
        assert dl["fileName"] == "poll_export.json"

    @pytest.mark.asyncio
    async def test_poll_errors_when_no_filename_returned(self, partner_credentials):
        node = create_expensify_node(
            ExpensifyNodeConfig(config=ExpensifyOnNewReportConfig(),
                                credentials=partner_credentials)
        )
        # file job succeeds but returns no filename -> surfaced as an error, no download.
        client, calls = create_two_step_client(REPORTS, gen_response={"responseCode": 200})
        r = await _run_trigger(node, client, {"seen_ids": ["baseline"]})
        assert r["status"] == "error"
        assert "file name" in r["error"].lower()
        assert len(calls["bodies"]) == 1  # never reached the download step


# ============================================================================
# Required-field fixes (live-discovered): onReceive, startDate default, fields
# ============================================================================


class TestExpensifyRequiredFields:
    """Expensify rejects (410) a `file` export without onReceive.immediateResponse
    or a date filter, and get/policy without `fields`. These pin the fixes."""

    async def _capture_payload(self, config, partner_credentials):
        captured = {}
        node = create_expensify_node(
            ExpensifyNodeConfig(config=config, credentials=partner_credentials)
        )
        resp = create_mock_response(200, json_data={"responseCode": 200})
        client = Mock()

        async def async_post(*args, **kwargs):
            captured["body"] = json.loads(kwargs["data"]["requestJobDescription"])
            return resp

        client.post = async_post
        client.__aenter__ = lambda self: _ident(client)
        client.__aexit__ = lambda self, *a: _none()
        with patch("nodes.expensify_node.httpx.AsyncClient", return_value=client):
            await node.execute({})
        return captured["body"]

    @pytest.mark.asyncio
    async def test_export_requires_onreceive_and_startdate(self, partner_credentials):
        body = await self._capture_payload(
            ExpensifyExportReportsConfig(file_extension="csv"), partner_credentials
        )
        assert body["onReceive"]["immediateResponse"] == ["returnRandomFileName"]
        # No date given -> defaults to all-time so the export isn't rejected.
        assert body["inputSettings"]["filters"]["startDate"] == "2000-01-01"

    @pytest.mark.asyncio
    async def test_export_keeps_user_startdate(self, partner_credentials):
        body = await self._capture_payload(
            ExpensifyExportReportsConfig(file_extension="csv", start_date="2026-01-01"),
            partner_credentials,
        )
        assert body["inputSettings"]["filters"]["startDate"] == "2026-01-01"

    @pytest.mark.asyncio
    async def test_get_policy_always_sends_fields(self, partner_credentials):
        body = await self._capture_payload(
            ExpensifyGetPolicyConfig(policy_id_list="POL1"), partner_credentials
        )
        assert body["inputSettings"]["fields"] == [
            "categories", "reportFields", "tags", "tax", "employees",
        ]

    @pytest.mark.asyncio
    async def test_download_respects_file_system(self, partner_credentials):
        body = await self._capture_payload(
            ExpensifyDownloadFileConfig(file_name="f.csv", file_system="reconciliation"),
            partner_credentials,
        )
        assert body["fileSystem"] == "reconciliation"

    @pytest.mark.asyncio
    async def test_create_report_expenses_are_sibling_of_report(self, partner_credentials):
        body = await self._capture_payload(
            ExpensifyCreateReportConfig(
                policy_id="POL1", employee_email="u@acme.com", report_title="T",
                expenses_json='[{"merchant":"Cab","created":"2026-01-01","amount":100,"currency":"USD"}]',
            ),
            partner_credentials,
        )
        # expenses is a sibling of `report` in inputSettings, not nested inside it.
        assert "expenses" in body["inputSettings"]
        assert "expenses" not in body["inputSettings"]["report"]

    @pytest.mark.asyncio
    async def test_update_report_status_nests_filters(self, partner_credentials):
        body = await self._capture_payload(
            ExpensifyUpdateReportStatusConfig(report_id_list="R1,R2"), partner_credentials
        )
        assert body["inputSettings"]["status"] == "REIMBURSED"
        assert body["inputSettings"]["filters"]["reportIDList"] == "R1,R2"

    @pytest.mark.asyncio
    async def test_expense_rules_use_actions_object(self, partner_credentials):
        create = await self._capture_payload(
            ExpensifyCreateExpenseRulesConfig(policy_id="P", employee_email="u@a.com", rules_json='{"tag":"Travel"}'),
            partner_credentials,
        )
        assert create["inputSettings"]["actions"] == {"tag": "Travel"}
        update = await self._capture_payload(
            ExpensifyUpdateExpenseRulesConfig(policy_id="P", employee_email="u@a.com", rule_id="7", rules_json='{"tag":"X"}'),
            partner_credentials,
        )
        assert update["inputSettings"]["ruleID"] == 7
        assert update["inputSettings"]["actions"] == {"tag": "X"}

    @pytest.mark.asyncio
    async def test_domain_card_list_uses_domain_param(self, partner_credentials):
        body = await self._capture_payload(
            ExpensifyGetDomainCardListConfig(domain_name="acme.com"), partner_credentials
        )
        assert body["inputSettings"]["domain"] == "acme.com"

    @pytest.mark.asyncio
    async def test_employee_updater_sends_records_in_data_field(self, partner_credentials):
        # Records go in the separate `data` form field, not requestJobDescription.
        captured = {}
        node = create_expensify_node(ExpensifyNodeConfig(
            config=ExpensifyAdvancedEmployeeUpdaterConfig(
                policy_id="P", employees_json='[{"employeeEmail":"e@a.com","managerEmail":"m@a.com","employeeID":"1","policyID":"P"}]'),
            credentials=partner_credentials))
        resp = create_mock_response(200, json_data={"responseCode": 200})
        client = Mock()

        async def async_post(*a, **kw):
            captured["form"] = kw.get("data")
            return resp

        client.post = async_post
        client.__aenter__ = lambda self: _ident(client)
        client.__aexit__ = lambda self, *a: _none()
        with patch("nodes.expensify_node.httpx.AsyncClient", return_value=client):
            await node.execute({})
        assert "data" in captured["form"]
        assert json.loads(captured["form"]["data"])[0]["employeeEmail"] == "e@a.com"
        job = json.loads(captured["form"]["requestJobDescription"])
        assert job["dataSource"] == "request"
        assert "employees" not in job["inputSettings"]
