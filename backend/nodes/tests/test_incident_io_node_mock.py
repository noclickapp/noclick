"""
Mock tests for the incident.io REST API node.

Exercises every operation with mocked HTTP responses (no live API calls):
- Incidents: list, get, create, edit; list incident updates
- Actions & follow-ups: list/get actions, list/get follow-ups
- Alerts: list, get, resolve, create alert event
- Configuration: severities, incident roles, custom fields
- Users: list, get
- On-call: schedules, schedule entries, schedule override, escalations
- Catalog: types, entries (list/create/update)
- Status pages: list/create
- Workflows: list
- Trigger: on_webhook_event passthrough
- Error handling: API errors, missing credentials
- Dynamic options: severity / schedule / catalog-type dropdowns
"""

import base64
import hashlib
import hmac
import json
from pathlib import Path

import httpx
import time

import pytest
from unittest.mock import AsyncMock, Mock, patch

from nodes.incident_io_node import (
    IncidentIoNode,
    IncidentIoNodeConfig,
    IncidentIoApiKeyCredential,
    IncidentIoListIncidentsConfig,
    IncidentIoGetIncidentConfig,
    IncidentIoCreateIncidentConfig,
    IncidentIoEditIncidentConfig,
    IncidentIoListIncidentUpdatesConfig,
    IncidentIoListActionsConfig,
    IncidentIoGetActionConfig,
    IncidentIoListFollowUpsConfig,
    IncidentIoGetFollowUpConfig,
    IncidentIoListAlertsConfig,
    IncidentIoGetAlertConfig,
    IncidentIoResolveAlertConfig,
    IncidentIoCreateAlertEventConfig,
    IncidentIoListSeveritiesConfig,
    IncidentIoListIncidentRolesConfig,
    IncidentIoListCustomFieldsConfig,
    IncidentIoListUsersConfig,
    IncidentIoGetUserConfig,
    IncidentIoListSchedulesConfig,
    IncidentIoListScheduleEntriesConfig,
    IncidentIoCreateScheduleOverrideConfig,
    IncidentIoListEscalationsConfig,
    IncidentIoCreateEscalationConfig,
    IncidentIoListCatalogTypesConfig,
    IncidentIoListCatalogEntriesConfig,
    IncidentIoCreateCatalogEntryConfig,
    IncidentIoUpdateCatalogEntryConfig,
    IncidentIoListStatusPageIncidentsConfig,
    IncidentIoCreateStatusPageIncidentConfig,
    IncidentIoListWorkflowsConfig,
    IncidentIoReceiveWebhookConfig,
    _incident_io_request,
)


@pytest.fixture
def api_key_credentials():
    return IncidentIoApiKeyCredential(api_key="inc_test_key_12345")


def create_node(config):
    return IncidentIoNode(
        node_id="test-incident-io-node",
        node_type="automation-incident-io",
        node_data={},
        config=config,
        sio=Mock(),
        sid="test-sid",
        workflow_id="test-workflow",
        user_id="test-user",
    )


def create_mock_response(status_code=200, json_data=None):
    mock_response = Mock()
    mock_response.status_code = status_code
    mock_response.text = ""
    mock_response.json = lambda: (json_data if json_data is not None else {})
    return mock_response


def create_mock_client(status_code=200, json_data=None):
    """Mock httpx.AsyncClient whose .request() returns the mock response and
    which works as an async context manager."""
    mock_response = create_mock_response(status_code, json_data)
    mock_client = Mock()

    async def async_request(*args, **kwargs):
        return mock_response

    mock_client.request = async_request

    async def aenter(self):
        return mock_client

    async def aexit(self, *args):
        return None

    mock_client.__aenter__ = aenter
    mock_client.__aexit__ = aexit
    return mock_client


async def _run(config_obj, status_code, json_data, credentials):
    config = IncidentIoNodeConfig(config=config_obj, credentials=credentials)
    node = create_node(config)
    mock_client = create_mock_client(status_code, json_data)
    with patch("nodes.incident_io_node.httpx.AsyncClient", return_value=mock_client):
        return await node.execute({})


# ============================================================================
# Incidents
# ============================================================================


class TestIncidentIoIncidentsMock:
    @pytest.mark.asyncio
    async def test_list_incidents(self, api_key_credentials):
        result = await _run(
            IncidentIoListIncidentsConfig(status="open_id", page_size="10"),
            200,
            {"incidents": [{"id": "01ABC"}, {"id": "01DEF"}]},
            api_key_credentials,
        )
        assert result["status"] == "success"
        assert result["action"] == "list_incidents"
        assert len(result["data"]["incidents"]) == 2

    @pytest.mark.asyncio
    async def test_get_incident(self, api_key_credentials):
        result = await _run(
            IncidentIoGetIncidentConfig(incident_id="01ABC"),
            200,
            {"incident": {"id": "01ABC", "name": "DB down"}},
            api_key_credentials,
        )
        assert result["status"] == "success"
        assert result["action"] == "get_incident"
        assert result["data"]["incident"]["id"] == "01ABC"

    @pytest.mark.asyncio
    async def test_create_incident(self, api_key_credentials):
        result = await _run(
            IncidentIoCreateIncidentConfig(name="API outage", severity_id="sev_1"),
            200,
            {"incident": {"id": "01NEW", "name": "API outage"}},
            api_key_credentials,
        )
        assert result["status"] == "success"
        assert result["action"] == "create_incident"
        assert result["data"]["incident"]["id"] == "01NEW"

    @pytest.mark.asyncio
    async def test_list_incident_updates(self, api_key_credentials):
        result = await _run(
            IncidentIoListIncidentUpdatesConfig(incident_id="01ABC"),
            200,
            {"incident_updates": [{"id": "upd_1"}]},
            api_key_credentials,
        )
        assert result["status"] == "success"
        assert result["action"] == "list_incident_updates"


# ============================================================================
# Actions & follow-ups
# ============================================================================


class TestIncidentIoActionsMock:
    @pytest.mark.asyncio
    async def test_list_actions(self, api_key_credentials):
        result = await _run(
            IncidentIoListActionsConfig(incident_id="01ABC"),
            200,
            {"actions": [{"id": "act_1"}]},
            api_key_credentials,
        )
        assert result["status"] == "success"
        assert result["action"] == "list_actions"

    @pytest.mark.asyncio
    async def test_get_action(self, api_key_credentials):
        result = await _run(
            IncidentIoGetActionConfig(action_id="act_1"),
            200,
            {"action": {"id": "act_1"}},
            api_key_credentials,
        )
        assert result["status"] == "success"
        assert result["action"] == "get_action"

    @pytest.mark.asyncio
    async def test_list_follow_ups(self, api_key_credentials):
        result = await _run(
            IncidentIoListFollowUpsConfig(),
            200,
            {"follow_ups": [{"id": "fu_1"}]},
            api_key_credentials,
        )
        assert result["status"] == "success"
        assert result["action"] == "list_follow_ups"

    @pytest.mark.asyncio
    async def test_get_follow_up(self, api_key_credentials):
        result = await _run(
            IncidentIoGetFollowUpConfig(follow_up_id="fu_1"),
            200,
            {"follow_up": {"id": "fu_1"}},
            api_key_credentials,
        )
        assert result["status"] == "success"
        assert result["action"] == "get_follow_up"


# ============================================================================
# Alerts
# ============================================================================


class TestIncidentIoAlertsMock:
    @pytest.mark.asyncio
    async def test_list_alerts(self, api_key_credentials):
        result = await _run(
            IncidentIoListAlertsConfig(),
            200,
            {"alerts": [{"id": "alrt_1"}]},
            api_key_credentials,
        )
        assert result["status"] == "success"
        assert result["action"] == "list_alerts"

    @pytest.mark.asyncio
    async def test_get_alert(self, api_key_credentials):
        result = await _run(
            IncidentIoGetAlertConfig(alert_id="alrt_1"),
            200,
            {"alert": {"id": "alrt_1"}},
            api_key_credentials,
        )
        assert result["status"] == "success"
        assert result["action"] == "get_alert"

    @pytest.mark.asyncio
    async def test_resolve_alert(self, api_key_credentials):
        result = await _run(
            IncidentIoResolveAlertConfig(alert_id="alrt_1"),
            200,
            {"alert": {"id": "alrt_1", "status": "resolved"}},
            api_key_credentials,
        )
        assert result["status"] == "success"
        assert result["action"] == "resolve_alert"

    @pytest.mark.asyncio
    async def test_create_alert_event(self, api_key_credentials):
        result = await _run(
            IncidentIoCreateAlertEventConfig(
                alert_source_config_id="src_1", title="Disk full", status="firing"
            ),
            202,
            {"message": "accepted", "deduplication_key": "dk_1"},
            api_key_credentials,
        )
        assert result["status"] == "success"
        assert result["action"] == "create_alert_event"


# ============================================================================
# Configuration
# ============================================================================


class TestIncidentIoConfigurationMock:
    @pytest.mark.asyncio
    async def test_list_severities(self, api_key_credentials):
        result = await _run(
            IncidentIoListSeveritiesConfig(),
            200,
            {"severities": [{"id": "sev_1", "name": "Critical"}]},
            api_key_credentials,
        )
        assert result["status"] == "success"
        assert result["action"] == "list_severities"

    @pytest.mark.asyncio
    async def test_list_incident_roles(self, api_key_credentials):
        result = await _run(
            IncidentIoListIncidentRolesConfig(),
            200,
            {"incident_roles": [{"id": "role_1", "name": "Lead"}]},
            api_key_credentials,
        )
        assert result["status"] == "success"
        assert result["action"] == "list_incident_roles"

    @pytest.mark.asyncio
    async def test_list_custom_fields(self, api_key_credentials):
        result = await _run(
            IncidentIoListCustomFieldsConfig(),
            200,
            {"custom_fields": [{"id": "cf_1", "name": "Affected Team"}]},
            api_key_credentials,
        )
        assert result["status"] == "success"
        assert result["action"] == "list_custom_fields"


# ============================================================================
# Users
# ============================================================================


class TestIncidentIoUsersMock:
    @pytest.mark.asyncio
    async def test_list_users(self, api_key_credentials):
        result = await _run(
            IncidentIoListUsersConfig(),
            200,
            {"users": [{"id": "usr_1", "name": "Ada"}]},
            api_key_credentials,
        )
        assert result["status"] == "success"
        assert result["action"] == "list_users"

    @pytest.mark.asyncio
    async def test_get_user(self, api_key_credentials):
        result = await _run(
            IncidentIoGetUserConfig(user_id="usr_1"),
            200,
            {"user": {"id": "usr_1", "name": "Ada"}},
            api_key_credentials,
        )
        assert result["status"] == "success"
        assert result["action"] == "get_user"
        assert result["data"]["user"]["id"] == "usr_1"


# ============================================================================
# On-call
# ============================================================================


class TestIncidentIoOnCallMock:
    @pytest.mark.asyncio
    async def test_list_schedules(self, api_key_credentials):
        result = await _run(
            IncidentIoListSchedulesConfig(),
            200,
            {"schedules": [{"id": "sch_1", "name": "Primary"}]},
            api_key_credentials,
        )
        assert result["status"] == "success"
        assert result["action"] == "list_schedules"

    @pytest.mark.asyncio
    async def test_list_schedule_entries(self, api_key_credentials):
        result = await _run(
            IncidentIoListScheduleEntriesConfig(schedule_id="sch_1"),
            200,
            {"schedule_entries": {"entries": [{"user_id": "usr_1"}]}},
            api_key_credentials,
        )
        assert result["status"] == "success"
        assert result["action"] == "list_schedule_entries"

    @pytest.mark.asyncio
    async def test_list_escalations(self, api_key_credentials):
        result = await _run(
            IncidentIoListEscalationsConfig(),
            200,
            {"escalations": [{"id": "esc_1"}]},
            api_key_credentials,
        )
        assert result["status"] == "success"
        assert result["action"] == "list_escalations"

    @pytest.mark.asyncio
    async def test_create_escalation(self, api_key_credentials):
        result = await _run(
            IncidentIoCreateEscalationConfig(title="Page on-call", escalation_path_id="ep_1"),
            200,
            {"escalation": {"id": "esc_new"}},
            api_key_credentials,
        )
        assert result["status"] == "success"
        assert result["action"] == "create_escalation"


# ============================================================================
# Catalog
# ============================================================================


class TestIncidentIoCatalogMock:
    @pytest.mark.asyncio
    async def test_list_catalog_types(self, api_key_credentials):
        result = await _run(
            IncidentIoListCatalogTypesConfig(),
            200,
            {"catalog_types": [{"id": "ct_1", "name": "Service"}]},
            api_key_credentials,
        )
        assert result["status"] == "success"
        assert result["action"] == "list_catalog_types"

    @pytest.mark.asyncio
    async def test_list_catalog_entries(self, api_key_credentials):
        result = await _run(
            IncidentIoListCatalogEntriesConfig(catalog_type_id="ct_1"),
            200,
            {"catalog_entries": [{"id": "ce_1"}]},
            api_key_credentials,
        )
        assert result["status"] == "success"
        assert result["action"] == "list_catalog_entries"


# ============================================================================
# Status pages & workflows
# ============================================================================


class TestIncidentIoStatusPageMock:

    @pytest.mark.asyncio
    async def test_list_workflows(self, api_key_credentials):
        result = await _run(
            IncidentIoListWorkflowsConfig(),
            200,
            {"workflows": [{"id": "wf_1"}]},
            api_key_credentials,
        )
        assert result["status"] == "success"
        assert result["action"] == "list_workflows"


# ============================================================================
# Trigger
# ============================================================================


class TestIncidentIoTriggerMock:
    @pytest.mark.asyncio
    async def test_on_webhook_event_passthrough(self):
        """The trigger passes the inbound webhook payload through as output."""
        config = IncidentIoNodeConfig(
            config=IncidentIoReceiveWebhookConfig(webhook_url="https://abc.hooks.example.test"),
            credentials=None,
        )
        node = create_node(config)
        payload = {
            "event_type": "public_incident.incident_created_v2",
            "incident": {"id": "01ABC"},
        }
        result = await node.execute(payload)
        assert result["status"] == "success"
        assert result["action"] == "on_webhook_event"
        assert result["data"]["event_type"] == "public_incident.incident_created_v2"
        assert result["data"]["webhook_url"] == "https://abc.hooks.example.test"

    def test_event_type_defaults_to_all(self):
        """The trigger config defaults to firing on all events."""
        cfg = IncidentIoReceiveWebhookConfig()
        assert cfg.event_type == "*"

    def test_filter_passes_selected_event(self):
        """A delivery whose event_type matches the user's selection fires."""
        config = {
            "operation": "on_webhook_event",
            "event_type": "public_incident.incident_created_v2",
        }
        payload = {"event_type": "public_incident.incident_created_v2", "incident": {"id": "01"}}
        assert IncidentIoNode.filter_trigger_payload(payload, config) is True

    def test_filter_skips_non_selected_event(self):
        """A delivery whose event_type differs from the selection is skipped."""
        config = {
            "operation": "on_webhook_event",
            "event_type": "public_incident.incident_created_v2",
        }
        payload = {"event_type": "public_incident.incident_status_updated_v2", "incident": {"id": "01"}}
        assert IncidentIoNode.filter_trigger_payload(payload, config) is False

    def test_filter_star_passes_any_event(self):
        """The 'all events' selection ('*') fires on any inbound event type."""
        config = {"operation": "on_webhook_event", "event_type": "*"}
        for evt in (
            "public_incident.incident_created_v2",
            "public_incident.action_updated_v1",
            "private_incident.incident_updated_v2",
        ):
            assert IncidentIoNode.filter_trigger_payload({"event_type": evt}, config) is True

    def test_filter_unset_event_type_passes_any_event(self):
        """A trigger with no event_type chosen falls back to firing on all events."""
        config = {"operation": "on_webhook_event"}
        assert (
            IncidentIoNode.filter_trigger_payload(
                {"event_type": "public_incident.follow_up_created_v1"}, config
            )
            is True
        )

    def test_exposed_events_match_enum(self):
        """Every selectable event in the trigger schema is a known incident.io event."""
        from nodes.incident_io_node import INCIDENT_IO_WEBHOOK_EVENTS, INCIDENT_IO_WEBHOOK_EVENT_NAMES

        assert "*" in INCIDENT_IO_WEBHOOK_EVENTS
        assert "public_incident.incident_created_v2" in INCIDENT_IO_WEBHOOK_EVENTS
        assert len(INCIDENT_IO_WEBHOOK_EVENTS) == len(INCIDENT_IO_WEBHOOK_EVENT_NAMES)

    @pytest.mark.asyncio
    async def test_manual_trigger_run_has_no_event(self):
        node = create_node(IncidentIoNodeConfig(config=IncidentIoReceiveWebhookConfig()))
        result = await node.execute({})
        assert result["status"] == "no_event"
        assert result["data"] == {}

    def test_signed_delivery_and_replay_window(self):
        secret_bytes = b"incident-io-webhook-test-secret-32"
        secret = "whsec_" + base64.b64encode(secret_bytes).decode()
        body = b'{"event_type":"public_incident.incident_created_v2"}'
        timestamp = str(int(time.time()))
        msg_id = "msg_incident_test"

        def signed(ts, raw=body):
            digest = hmac.new(
                secret_bytes, f"{msg_id}.{ts}.".encode() + raw, hashlib.sha256
            ).digest()
            return {
                "webhook-id": msg_id,
                "webhook-timestamp": ts,
                "webhook-signature": "v1," + base64.b64encode(digest).decode(),
            }

        headers = signed(timestamp)
        assert IncidentIoNode.verify_webhook_signature(body, headers, {"signing_secret": secret})
        assert not IncidentIoNode.verify_webhook_signature(body + b" ", headers, {"signing_secret": secret})
        assert not IncidentIoNode.verify_webhook_signature(body, headers, {})
        assert not IncidentIoNode.verify_webhook_signature(body, {**headers, "webhook-signature": "v1,bad"}, {"signing_secret": secret})
        assert not IncidentIoNode.verify_webhook_signature(body, {**headers, "webhook-signature": "v1,☃"}, {"signing_secret": secret})
        assert not IncidentIoNode.verify_webhook_signature(body, {"webhook-id": msg_id}, {"signing_secret": secret})
        assert not IncidentIoNode.verify_webhook_signature(body, signed(str(int(timestamp) - 301)), {"signing_secret": secret})
        assert not IncidentIoNode.verify_webhook_signature(body, signed(str(int(timestamp) + 301)), {"signing_secret": secret})
        assert not IncidentIoNode.verify_webhook_signature(body, headers, {"signing_secret": "whsec_"})


# ============================================================================
# Error handling
# ============================================================================


class TestIncidentIoErrorHandlingMock:
    @pytest.mark.asyncio
    async def test_api_error(self, api_key_credentials):
        result = await _run(
            IncidentIoGetIncidentConfig(incident_id="missing"),
            404,
            {"type": "not_found", "status": 404, "errors": [{"message": "Incident not found"}]},
            api_key_credentials,
        )
        assert result["status"] == "error"
        assert result["status_code"] == 404
        assert result["error"] == "incident.io API returned HTTP 404"

    @pytest.mark.asyncio
    async def test_redirect_is_not_success(self):
        client = create_mock_client(302, {"type": "provider_redirect_sentinel"})
        with patch("nodes.incident_io_node.httpx.AsyncClient", return_value=client):
            result = await _incident_io_request("key", "GET", "/v2/incidents")
        assert result["status"] == "error"
        assert result["status_code"] == 302
        assert result["error"] == "incident.io API returned HTTP 302"
        assert "provider_redirect_sentinel" not in str(result)

    @pytest.mark.asyncio
    async def test_provider_error_type_is_not_reflected(self, caplog):
        client = create_mock_client(403, {"type": "secret_type_sentinel"})
        with patch("nodes.incident_io_node.httpx.AsyncClient", return_value=client):
            result = await _incident_io_request("key", "GET", "/v2/incidents")
        assert result["error"] == "incident.io API returned HTTP 403"
        assert "secret_type_sentinel" not in str(result)
        assert "secret_type_sentinel" not in caplog.text

    @pytest.mark.asyncio
    async def test_transport_exception_is_not_disclosed(self, caplog):
        client = create_mock_client()
        client.request = AsyncMock(side_effect=RuntimeError("transport_secret_sentinel"))
        with patch("nodes.incident_io_node.httpx.AsyncClient", return_value=client):
            result = await _incident_io_request("key", "GET", "/v2/incidents")
        assert result["status"] == "error"
        assert result["error"] == "incident.io request failed"
        assert "transport_secret_sentinel" not in str(result)
        assert "transport_secret_sentinel" not in caplog.text

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        config = IncidentIoNodeConfig(config=IncidentIoListSeveritiesConfig(), credentials=None)
        node = create_node(config)
        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})

    @pytest.mark.asyncio
    async def test_non_json_body_never_reaches_output_or_logs(self, caplog):
        response = create_mock_response(200)
        response.text = "<html>secret-key-material</html>"
        response.json = Mock(side_effect=ValueError("invalid JSON"))
        client = create_mock_client()

        async def request(*args, **kwargs):
            return response

        client.request = request
        with patch("nodes.incident_io_node.httpx.AsyncClient", return_value=client):
            result = await _incident_io_request("key", "GET", "/v2/incidents")
        assert result["status"] == "error"
        assert "secret-key-material" not in str(result)
        assert "secret-key-material" not in caplog.text

        response.status_code = 502
        with patch("nodes.incident_io_node.httpx.AsyncClient", return_value=client):
            result = await _incident_io_request("key", "GET", "/v2/incidents")
        assert result["status"] == "error"
        assert "secret-key-material" not in str(result)
        assert "secret-key-material" not in caplog.text


# ============================================================================
# Dynamic options
# ============================================================================


class TestIncidentIoDynamicOptionsMock:
    @pytest.mark.asyncio
    async def test_load_severity_options(self):
        with patch(
            "nodes.incident_io_node._incident_io_request",
            return_value={
                "status": "success",
                "data": {"severities": [{"id": "sev_1", "name": "Critical"}]},
            },
        ):
            result = await IncidentIoNode.load_field_options(
                "severity_id", credential_data={"api_key": "inc_test"}
            )
        assert result["options"][0]["value"] == "sev_1"
        assert result["options"][0]["label"] == "Critical"

    @pytest.mark.asyncio
    async def test_load_schedule_options(self):
        with patch(
            "nodes.incident_io_node._incident_io_request",
            return_value={
                "status": "success",
                "data": {"schedules": [{"id": "sch_1", "name": "Primary"}]},
            },
        ):
            result = await IncidentIoNode.load_field_options(
                "schedule_id", credential_data={"api_key": "inc_test"}
            )
        assert result["options"][0]["value"] == "sch_1"

    @pytest.mark.asyncio
    async def test_load_catalog_type_options(self):
        with patch(
            "nodes.incident_io_node._incident_io_request",
            return_value={
                "status": "success",
                "data": {"catalog_types": [{"id": "ct_1", "name": "Service"}]},
            },
        ):
            result = await IncidentIoNode.load_field_options(
                "catalog_type_id", credential_data={"api_key": "inc_test"}
            )
        assert result["options"][0]["value"] == "ct_1"

    @pytest.mark.asyncio
    async def test_load_unknown_field_returns_empty(self):
        result = await IncidentIoNode.load_field_options(
            "nonexistent_field", credential_data=None
        )
        assert result == {"options": []}

    @pytest.mark.asyncio
    async def test_options_reject_missing_key_and_provider_error(self):
        with pytest.raises(ValueError, match="Connect an incident.io API key"):
            await IncidentIoNode.load_field_options("severity_id", credential_data=None)
        with patch("nodes.incident_io_node._incident_io_request", return_value={
            "status": "error", "error": "incident.io API returned HTTP 403 (forbidden)"
        }):
            with pytest.raises(ValueError, match="HTTP 403"):
                await IncidentIoNode.load_field_options("severity_id", credential_data={"api_key": "key"})

    @pytest.mark.asyncio
    async def test_schedule_paging_and_search(self):
        async def request(api_key, method, endpoint, params=None, **kwargs):
            assert endpoint == "/v2/schedules"
            if params and params.get("after") == "next":
                return {"status": "success", "data": {"schedules": [{"id": "s2", "name": "Primary"}], "pagination_meta": {}}}
            return {"status": "success", "data": {"schedules": [{"id": "s1", "name": "Secondary"}], "pagination_meta": {"after": "next"}}}

        with patch("nodes.incident_io_node._incident_io_request", side_effect=request):
            first = await IncidentIoNode.load_field_options("schedule_id", credential_data={"api_key": "key"})
            second = await IncidentIoNode.load_field_options("schedule_id", credential_data={"api_key": "key"}, page_token="next")
            searched = await IncidentIoNode.load_field_options("schedule_id", credential_data={"api_key": "key"}, search="primary")
        assert first == {"options": [{"label": "Secondary", "value": "s1"}], "next_page_token": "next"}
        assert second["options"] == [{"label": "Primary", "value": "s2"}]
        assert searched == {"options": [{"label": "Primary", "value": "s2"}], "next_page_token": None}

    @pytest.mark.asyncio
    async def test_current_lookup_dispatcher_passes_credential_and_search(self):
        from nodes.core.run_op import run_node_lookup

        with patch("nodes.core.run_op.resolve_operation_credential", new_callable=AsyncMock, return_value={"api_key": "key"}), patch(
            "utils.credential_approval.admit_lookup", new_callable=AsyncMock, return_value=None
        ), patch.object(IncidentIoNode, "freshen_credential", new_callable=AsyncMock, return_value={"api_key": "key"}), patch(
            "nodes.incident_io_node._incident_io_request", new_callable=AsyncMock,
            return_value={"status": "success", "data": {"severities": [
                {"id": "s1", "name": "Critical"}, {"id": "s2", "name": "Low"}
            ]}}
        ):
            result = await run_node_lookup(
                node_type="automation-incident-io", field_name="severity_id",
                user_id="user-1", credential_id="cred-1", search="Critical"
            )
        assert result == {"options": [{"label": "Critical", "value": "s1"}], "next_page_token": None}


class TestIncidentIoConnectionEvidenceMock:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("name", ["User API key", "Team service key"])
    async def test_identity_probe_through_real_collector(self, name):
        from nodes.core.connection_evidence import collect_evidence

        with patch("nodes.incident_io_node._incident_io_request", new_callable=AsyncMock,
                   return_value={"status": "success", "data": {"identity": {
                       "name": name, "roles": ["viewer"], "dashboard_url": "https://app.incident.io/example",
                       "api_key": "must-not-appear"
                   }}}) as request:
            verdict = await collect_evidence(
                node_type="automation-incident-io", user_id="user-1",
                credential_data={"api_key": "typed-secret"},
            )
        assert verdict.reachable is True
        assert [sample.label for sample in verdict.samples] == [name]
        assert "must-not-appear" not in str(verdict)
        assert "typed-secret" not in str(verdict)
        assert request.await_args.args[:3] == ("typed-secret", "GET", "/v1/identity")

    @pytest.mark.asyncio
    async def test_identity_rejection_and_bad_shape_do_not_look_connected(self):
        from nodes.core.connection_evidence import collect_evidence

        with patch("nodes.incident_io_node._incident_io_request", new_callable=AsyncMock,
                   return_value={"status": "error", "error": "incident.io API returned HTTP 401 (unauthorized)"}):
            rejected = await collect_evidence(
                node_type="automation-incident-io", user_id="user-1",
                credential_data={"api_key": "typed-secret"},
            )
        assert rejected.reachable is False
        assert "typed-secret" not in str(rejected)

        with patch("nodes.incident_io_node._incident_io_request", new_callable=AsyncMock,
                   return_value={"status": "success", "data": {"identity": {"name": 123}}}):
            malformed = await collect_evidence(
                node_type="automation-incident-io", user_id="user-1",
                credential_data={"api_key": "typed-secret"},
            )
        assert malformed.reachable is None
        assert not malformed.samples


# Provider-authored examples, copied from the source URL recorded in each case.
CONTRACT_EXAMPLES = json.loads(
    (Path(__file__).parent / "fixtures" / "incident-io" / "contract_examples.json").read_text()
)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", CONTRACT_EXAMPLES)
async def test_documented_request_contract(operation, api_key_credentials):
    case = CONTRACT_EXAMPLES[operation]
    captured = []

    def respond(request):
        captured.append(request)
        return httpx.Response(case["response_status"], json=case["response"])

    original_client = httpx.AsyncClient

    def client(**kwargs):
        return original_client(**kwargs, transport=httpx.MockTransport(respond), trust_env=False)

    config = IncidentIoNodeConfig.model_validate({
        "config": case["config"], "credentials": api_key_credentials,
    })
    with patch("nodes.incident_io_node.httpx.AsyncClient", side_effect=client):
        result = await create_node(config).execute({})

    assert result["status"] == "success"
    assert result["data"] == case["response"]
    assert result["status_code"] == case["response_status"]
    assert len(captured) == 1
    request = captured[0]
    assert request.method == case["method"]
    assert request.url.path == case["path"]
    if case["body"] is not None:
        assert json.loads(request.content) == case["body"]
    else:
        assert dict(request.url.params) == {
            "status_page_id": case["config"]["status_page_id"], "page_size": "25",
        }


@pytest.mark.parametrize("config", [
    {"operation": "list_status_page_incidents"},
    {"operation": "create_status_page_incident", "status_page_id": "01FCNDV6P870EA6S7TK1DSYDG0",
     "name": "Elevated API latency", "message": "We are currently investigating reports of elevated error rates affecting our API."},
    {"operation": "create_catalog_entry", "catalog_type_id": "01FCNDV6P870EA6S7TK1DSYDG0", "name": "Primary On-call"},
    {"operation": "update_catalog_entry", "catalog_entry_id": "01FCNDV6P870EA6S7TK1DSYDG0", "name": "Primary On-call"},
])
def test_missing_required_provider_fields_are_rejected(config):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        IncidentIoNodeConfig.model_validate({"config": config})
