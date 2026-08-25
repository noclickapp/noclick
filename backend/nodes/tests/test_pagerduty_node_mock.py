"""
Mock tests for the PagerDuty REST API node.

Exercises every operation with mocked HTTP responses (no live API calls):
- Incidents: list, get, create, update, manage (bulk), snooze, merge
- Incident details: notes (list/create), status update, alerts, log entries, responders
- Services: list, get, create, update
- Schedules / on-call: list schedules, get schedule, list on-calls
- Escalation policies: list, create
- Users / teams: list users, get user, create user, current user, list teams
- Maintenance windows: list, create
- Events API v2: send alert event
- Webhook subscriptions: list, create
- Reference: list priorities
- Trigger: on_incident_event passthrough, webhook registration/deregistration,
  signature verification
- Error handling: API errors, missing credentials
- Dynamic options: service dropdown
"""

import hashlib
import hmac

import pytest
from unittest.mock import Mock, patch

from nodes.pagerduty_node import (
    PagerDutyNode,
    PagerDutyNodeConfig,
    PagerDutyApiKeyCredential,
    PagerDutyListIncidentsConfig,
    PagerDutyGetIncidentConfig,
    PagerDutyCreateIncidentConfig,
    PagerDutyUpdateIncidentConfig,
    PagerDutyManageIncidentsConfig,
    PagerDutySnoozeIncidentConfig,
    PagerDutyMergeIncidentsConfig,
    PagerDutyListNotesConfig,
    PagerDutyCreateNoteConfig,
    PagerDutyCreateStatusUpdateConfig,
    PagerDutyListAlertsConfig,
    PagerDutyListLogEntriesConfig,
    PagerDutyAddRespondersConfig,
    PagerDutyListServicesConfig,
    PagerDutyGetServiceConfig,
    PagerDutyCreateServiceConfig,
    PagerDutyUpdateServiceConfig,
    PagerDutyListSchedulesConfig,
    PagerDutyGetScheduleConfig,
    PagerDutyListOnCallsConfig,
    PagerDutyListEscalationPoliciesConfig,
    PagerDutyCreateEscalationPolicyConfig,
    PagerDutyListUsersConfig,
    PagerDutyGetUserConfig,
    PagerDutyCreateUserConfig,
    PagerDutyGetCurrentUserConfig,
    PagerDutyListTeamsConfig,
    PagerDutyListMaintenanceWindowsConfig,
    PagerDutyCreateMaintenanceWindowConfig,
    PagerDutySendEventConfig,
    PagerDutyListWebhookSubscriptionsConfig,
    PagerDutyCreateWebhookSubscriptionConfig,
    PagerDutyListPrioritiesConfig,
    PagerDutyIncidentTriggerConfig,
)


@pytest.fixture
def api_key_credentials():
    return PagerDutyApiKeyCredential(api_key="pd_test_key_12345", from_email="ops@example.com")


def create_pagerduty_node(config):
    return PagerDutyNode(
        node_id="test-pagerduty-node",
        node_type="automation-pagerduty",
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
    mock_response.content = b"{}" if json_data is not None else b""
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


async def _run(node, status_code, json_data):
    mock_client = create_mock_client(status_code, json_data)
    with patch("nodes.pagerduty_node.httpx.AsyncClient", return_value=mock_client):
        return await node.execute({})


# ============================================================================
# Incidents
# ============================================================================


class TestPagerDutyIncidentsMock:
    @pytest.mark.asyncio
    async def test_list_incidents(self, api_key_credentials):
        node = create_pagerduty_node(
            PagerDutyNodeConfig(
                config=PagerDutyListIncidentsConfig(statuses="triggered", limit="10"),
                credentials=api_key_credentials,
            )
        )
        result = await _run(node, 200, {"incidents": [{"id": "PINC1"}, {"id": "PINC2"}]})
        assert result["status"] == "success"
        assert result["action"] == "list_incidents"
        assert len(result["data"]["incidents"]) == 2

    @pytest.mark.asyncio
    async def test_get_incident(self, api_key_credentials):
        node = create_pagerduty_node(
            PagerDutyNodeConfig(
                config=PagerDutyGetIncidentConfig(incident_id="PINC1"),
                credentials=api_key_credentials,
            )
        )
        result = await _run(node, 200, {"incident": {"id": "PINC1", "title": "DB down"}})
        assert result["status"] == "success"
        assert result["action"] == "get_incident"
        assert result["data"]["incident"]["id"] == "PINC1"

    @pytest.mark.asyncio
    async def test_create_incident(self, api_key_credentials):
        node = create_pagerduty_node(
            PagerDutyNodeConfig(
                config=PagerDutyCreateIncidentConfig(
                    title="API latency", service_id="PSVC1", urgency="high"
                ),
                credentials=api_key_credentials,
            )
        )
        result = await _run(node, 201, {"incident": {"id": "PINC9", "title": "API latency"}})
        assert result["status"] == "success"
        assert result["action"] == "create_incident"
        assert result["data"]["incident"]["id"] == "PINC9"

    @pytest.mark.asyncio
    async def test_update_incident(self, api_key_credentials):
        node = create_pagerduty_node(
            PagerDutyNodeConfig(
                config=PagerDutyUpdateIncidentConfig(incident_id="PINC1", status="resolved"),
                credentials=api_key_credentials,
            )
        )
        result = await _run(node, 200, {"incident": {"id": "PINC1", "status": "resolved"}})
        assert result["status"] == "success"
        assert result["action"] == "update_incident"
        assert result["data"]["incident"]["status"] == "resolved"

    @pytest.mark.asyncio
    async def test_manage_incidents(self, api_key_credentials):
        node = create_pagerduty_node(
            PagerDutyNodeConfig(
                config=PagerDutyManageIncidentsConfig(
                    incident_ids="PINC1, PINC2", status="acknowledged"
                ),
                credentials=api_key_credentials,
            )
        )
        result = await _run(node, 200, {"incidents": [{"id": "PINC1"}, {"id": "PINC2"}]})
        assert result["status"] == "success"
        assert result["action"] == "manage_incidents"
        assert len(result["data"]["incidents"]) == 2

    @pytest.mark.asyncio
    async def test_snooze_incident(self, api_key_credentials):
        node = create_pagerduty_node(
            PagerDutyNodeConfig(
                config=PagerDutySnoozeIncidentConfig(incident_id="PINC1", duration="3600"),
                credentials=api_key_credentials,
            )
        )
        result = await _run(node, 200, {"incident": {"id": "PINC1"}})
        assert result["status"] == "success"
        assert result["action"] == "snooze_incident"

    @pytest.mark.asyncio
    async def test_merge_incidents(self, api_key_credentials):
        node = create_pagerduty_node(
            PagerDutyNodeConfig(
                config=PagerDutyMergeIncidentsConfig(
                    incident_id="PINC1", source_incident_ids="PINC2,PINC3"
                ),
                credentials=api_key_credentials,
            )
        )
        result = await _run(node, 200, {"incident": {"id": "PINC1"}})
        assert result["status"] == "success"
        assert result["action"] == "merge_incidents"


# ============================================================================
# Incident details
# ============================================================================


class TestPagerDutyIncidentDetailsMock:
    @pytest.mark.asyncio
    async def test_list_notes(self, api_key_credentials):
        node = create_pagerduty_node(
            PagerDutyNodeConfig(
                config=PagerDutyListNotesConfig(incident_id="PINC1"),
                credentials=api_key_credentials,
            )
        )
        result = await _run(node, 200, {"notes": [{"id": "PNOTE1", "content": "Investigating"}]})
        assert result["status"] == "success"
        assert result["action"] == "list_notes"
        assert result["data"]["notes"][0]["id"] == "PNOTE1"

    @pytest.mark.asyncio
    async def test_create_note(self, api_key_credentials):
        node = create_pagerduty_node(
            PagerDutyNodeConfig(
                config=PagerDutyCreateNoteConfig(incident_id="PINC1", content="On it"),
                credentials=api_key_credentials,
            )
        )
        result = await _run(node, 201, {"note": {"id": "PNOTE9", "content": "On it"}})
        assert result["status"] == "success"
        assert result["action"] == "create_note"
        assert result["data"]["note"]["id"] == "PNOTE9"

    @pytest.mark.asyncio
    async def test_create_status_update(self, api_key_credentials):
        node = create_pagerduty_node(
            PagerDutyNodeConfig(
                config=PagerDutyCreateStatusUpdateConfig(
                    incident_id="PINC1", message="Mitigation deployed"
                ),
                credentials=api_key_credentials,
            )
        )
        result = await _run(node, 201, {"status_update": {"id": "PSU1"}})
        assert result["status"] == "success"
        assert result["action"] == "create_status_update"

    @pytest.mark.asyncio
    async def test_list_alerts(self, api_key_credentials):
        node = create_pagerduty_node(
            PagerDutyNodeConfig(
                config=PagerDutyListAlertsConfig(incident_id="PINC1"),
                credentials=api_key_credentials,
            )
        )
        result = await _run(node, 200, {"alerts": [{"id": "PALERT1"}]})
        assert result["status"] == "success"
        assert result["action"] == "list_alerts"
        assert result["data"]["alerts"][0]["id"] == "PALERT1"

    @pytest.mark.asyncio
    async def test_list_log_entries(self, api_key_credentials):
        node = create_pagerduty_node(
            PagerDutyNodeConfig(
                config=PagerDutyListLogEntriesConfig(incident_id="PINC1"),
                credentials=api_key_credentials,
            )
        )
        result = await _run(node, 200, {"log_entries": [{"id": "PLOG1"}]})
        assert result["status"] == "success"
        assert result["action"] == "list_log_entries"

    @pytest.mark.asyncio
    async def test_add_responders(self, api_key_credentials):
        node = create_pagerduty_node(
            PagerDutyNodeConfig(
                config=PagerDutyAddRespondersConfig(
                    incident_id="PINC1", user_ids="PUSER1", message="Need help"
                ),
                credentials=api_key_credentials,
            )
        )
        result = await _run(node, 200, {"responder_request": {"incident": {"id": "PINC1"}}})
        assert result["status"] == "success"
        assert result["action"] == "add_responders"


# ============================================================================
# Services
# ============================================================================


class TestPagerDutyServicesMock:
    @pytest.mark.asyncio
    async def test_list_services(self, api_key_credentials):
        node = create_pagerduty_node(
            PagerDutyNodeConfig(
                config=PagerDutyListServicesConfig(query="payments"),
                credentials=api_key_credentials,
            )
        )
        result = await _run(node, 200, {"services": [{"id": "PSVC1", "name": "Payments"}]})
        assert result["status"] == "success"
        assert result["action"] == "list_services"
        assert result["data"]["services"][0]["id"] == "PSVC1"

    @pytest.mark.asyncio
    async def test_get_service(self, api_key_credentials):
        node = create_pagerduty_node(
            PagerDutyNodeConfig(
                config=PagerDutyGetServiceConfig(service_id="PSVC1"),
                credentials=api_key_credentials,
            )
        )
        result = await _run(node, 200, {"service": {"id": "PSVC1", "name": "Payments"}})
        assert result["status"] == "success"
        assert result["action"] == "get_service"
        assert result["data"]["service"]["id"] == "PSVC1"

    @pytest.mark.asyncio
    async def test_create_service(self, api_key_credentials):
        node = create_pagerduty_node(
            PagerDutyNodeConfig(
                config=PagerDutyCreateServiceConfig(
                    name="Checkout", escalation_policy_id="PEP1"
                ),
                credentials=api_key_credentials,
            )
        )
        result = await _run(node, 201, {"service": {"id": "PSVC9", "name": "Checkout"}})
        assert result["status"] == "success"
        assert result["action"] == "create_service"
        assert result["data"]["service"]["id"] == "PSVC9"

    @pytest.mark.asyncio
    async def test_update_service(self, api_key_credentials):
        node = create_pagerduty_node(
            PagerDutyNodeConfig(
                config=PagerDutyUpdateServiceConfig(service_id="PSVC1", name="Payments v2"),
                credentials=api_key_credentials,
            )
        )
        result = await _run(node, 200, {"service": {"id": "PSVC1", "name": "Payments v2"}})
        assert result["status"] == "success"
        assert result["action"] == "update_service"
        assert result["data"]["service"]["name"] == "Payments v2"


# ============================================================================
# Schedules / on-call
# ============================================================================


class TestPagerDutySchedulesMock:
    @pytest.mark.asyncio
    async def test_list_schedules(self, api_key_credentials):
        node = create_pagerduty_node(
            PagerDutyNodeConfig(
                config=PagerDutyListSchedulesConfig(query="primary"),
                credentials=api_key_credentials,
            )
        )
        result = await _run(node, 200, {"schedules": [{"id": "PSCH1", "name": "Primary"}]})
        assert result["status"] == "success"
        assert result["action"] == "list_schedules"
        assert result["data"]["schedules"][0]["id"] == "PSCH1"

    @pytest.mark.asyncio
    async def test_get_schedule(self, api_key_credentials):
        node = create_pagerduty_node(
            PagerDutyNodeConfig(
                config=PagerDutyGetScheduleConfig(schedule_id="PSCH1"),
                credentials=api_key_credentials,
            )
        )
        result = await _run(node, 200, {"schedule": {"id": "PSCH1", "name": "Primary"}})
        assert result["status"] == "success"
        assert result["action"] == "get_schedule"
        assert result["data"]["schedule"]["id"] == "PSCH1"

    @pytest.mark.asyncio
    async def test_list_oncalls(self, api_key_credentials):
        node = create_pagerduty_node(
            PagerDutyNodeConfig(
                config=PagerDutyListOnCallsConfig(schedule_ids="PSCH1"),
                credentials=api_key_credentials,
            )
        )
        result = await _run(node, 200, {"oncalls": [{"user": {"id": "PUSER1"}}]})
        assert result["status"] == "success"
        assert result["action"] == "list_oncalls"
        assert result["data"]["oncalls"][0]["user"]["id"] == "PUSER1"


# ============================================================================
# Escalation policies
# ============================================================================


class TestPagerDutyEscalationPoliciesMock:
    @pytest.mark.asyncio
    async def test_list_escalation_policies(self, api_key_credentials):
        node = create_pagerduty_node(
            PagerDutyNodeConfig(
                config=PagerDutyListEscalationPoliciesConfig(),
                credentials=api_key_credentials,
            )
        )
        result = await _run(node, 200, {"escalation_policies": [{"id": "PEP1"}]})
        assert result["status"] == "success"
        assert result["action"] == "list_escalation_policies"
        assert result["data"]["escalation_policies"][0]["id"] == "PEP1"

    @pytest.mark.asyncio
    async def test_create_escalation_policy(self, api_key_credentials):
        node = create_pagerduty_node(
            PagerDutyNodeConfig(
                config=PagerDutyCreateEscalationPolicyConfig(
                    name="Default", escalation_target_id="PUSER1"
                ),
                credentials=api_key_credentials,
            )
        )
        result = await _run(node, 201, {"escalation_policy": {"id": "PEP9", "name": "Default"}})
        assert result["status"] == "success"
        assert result["action"] == "create_escalation_policy"
        assert result["data"]["escalation_policy"]["id"] == "PEP9"


# ============================================================================
# Users / teams
# ============================================================================


class TestPagerDutyUsersMock:
    @pytest.mark.asyncio
    async def test_list_users(self, api_key_credentials):
        node = create_pagerduty_node(
            PagerDutyNodeConfig(
                config=PagerDutyListUsersConfig(query="ada"),
                credentials=api_key_credentials,
            )
        )
        result = await _run(node, 200, {"users": [{"id": "PUSER1", "name": "Ada"}]})
        assert result["status"] == "success"
        assert result["action"] == "list_users"
        assert result["data"]["users"][0]["id"] == "PUSER1"

    @pytest.mark.asyncio
    async def test_get_user(self, api_key_credentials):
        node = create_pagerduty_node(
            PagerDutyNodeConfig(
                config=PagerDutyGetUserConfig(user_id="PUSER1"),
                credentials=api_key_credentials,
            )
        )
        result = await _run(node, 200, {"user": {"id": "PUSER1", "name": "Ada"}})
        assert result["status"] == "success"
        assert result["action"] == "get_user"
        assert result["data"]["user"]["id"] == "PUSER1"

    @pytest.mark.asyncio
    async def test_create_user(self, api_key_credentials):
        node = create_pagerduty_node(
            PagerDutyNodeConfig(
                config=PagerDutyCreateUserConfig(name="Grace", email="grace@example.com"),
                credentials=api_key_credentials,
            )
        )
        result = await _run(node, 201, {"user": {"id": "PUSER9", "name": "Grace"}})
        assert result["status"] == "success"
        assert result["action"] == "create_user"
        assert result["data"]["user"]["id"] == "PUSER9"

    @pytest.mark.asyncio
    async def test_get_current_user(self, api_key_credentials):
        node = create_pagerduty_node(
            PagerDutyNodeConfig(
                config=PagerDutyGetCurrentUserConfig(),
                credentials=api_key_credentials,
            )
        )
        result = await _run(node, 200, {"user": {"id": "PME", "name": "Me"}})
        assert result["status"] == "success"
        assert result["action"] == "get_current_user"
        assert result["data"]["user"]["id"] == "PME"

    @pytest.mark.asyncio
    async def test_list_teams(self, api_key_credentials):
        node = create_pagerduty_node(
            PagerDutyNodeConfig(
                config=PagerDutyListTeamsConfig(),
                credentials=api_key_credentials,
            )
        )
        result = await _run(node, 200, {"teams": [{"id": "PTEAM1"}]})
        assert result["status"] == "success"
        assert result["action"] == "list_teams"
        assert result["data"]["teams"][0]["id"] == "PTEAM1"


# ============================================================================
# Maintenance windows
# ============================================================================


class TestPagerDutyMaintenanceWindowsMock:
    @pytest.mark.asyncio
    async def test_list_maintenance_windows(self, api_key_credentials):
        node = create_pagerduty_node(
            PagerDutyNodeConfig(
                config=PagerDutyListMaintenanceWindowsConfig(filter="future"),
                credentials=api_key_credentials,
            )
        )
        result = await _run(node, 200, {"maintenance_windows": [{"id": "PMW1"}]})
        assert result["status"] == "success"
        assert result["action"] == "list_maintenance_windows"

    @pytest.mark.asyncio
    async def test_create_maintenance_window(self, api_key_credentials):
        node = create_pagerduty_node(
            PagerDutyNodeConfig(
                config=PagerDutyCreateMaintenanceWindowConfig(
                    service_ids="PSVC1",
                    start_time="2026-07-01T00:00:00Z",
                    end_time="2026-07-01T01:00:00Z",
                ),
                credentials=api_key_credentials,
            )
        )
        result = await _run(node, 201, {"maintenance_window": {"id": "PMW9"}})
        assert result["status"] == "success"
        assert result["action"] == "create_maintenance_window"
        assert result["data"]["maintenance_window"]["id"] == "PMW9"


# ============================================================================
# Events API v2
# ============================================================================


class TestPagerDutyEventsMock:
    @pytest.mark.asyncio
    async def test_send_event(self, api_key_credentials):
        node = create_pagerduty_node(
            PagerDutyNodeConfig(
                config=PagerDutySendEventConfig(
                    routing_key="R0UT1NGK3Y00000000000000000000000",
                    event_action="trigger",
                    summary="Disk full",
                    source="db01",
                    severity="critical",
                ),
                credentials=api_key_credentials,
            )
        )
        result = await _run(
            node, 202, {"status": "success", "dedup_key": "abc123", "message": "Event processed"}
        )
        assert result["status"] == "success"
        assert result["action"] == "send_event"
        assert result["data"]["dedup_key"] == "abc123"


# ============================================================================
# Webhook subscriptions (REST operations, not the trigger)
# ============================================================================


class TestPagerDutyWebhookSubscriptionsMock:
    @pytest.mark.asyncio
    async def test_list_webhook_subscriptions(self, api_key_credentials):
        node = create_pagerduty_node(
            PagerDutyNodeConfig(
                config=PagerDutyListWebhookSubscriptionsConfig(),
                credentials=api_key_credentials,
            )
        )
        result = await _run(node, 200, {"webhook_subscriptions": [{"id": "PWH1"}]})
        assert result["status"] == "success"
        assert result["action"] == "list_webhook_subscriptions"

    @pytest.mark.asyncio
    async def test_create_webhook_subscription(self, api_key_credentials):
        node = create_pagerduty_node(
            PagerDutyNodeConfig(
                config=PagerDutyCreateWebhookSubscriptionConfig(
                    delivery_url="https://abc.hooks.example.test",
                    events="incident.triggered,incident.resolved",
                ),
                credentials=api_key_credentials,
            )
        )
        result = await _run(node, 201, {"webhook_subscription": {"id": "PWH9"}})
        assert result["status"] == "success"
        assert result["action"] == "create_webhook_subscription"
        assert result["data"]["webhook_subscription"]["id"] == "PWH9"


# ============================================================================
# Reference
# ============================================================================


class TestPagerDutyReferenceMock:
    @pytest.mark.asyncio
    async def test_list_priorities(self, api_key_credentials):
        node = create_pagerduty_node(
            PagerDutyNodeConfig(
                config=PagerDutyListPrioritiesConfig(),
                credentials=api_key_credentials,
            )
        )
        result = await _run(node, 200, {"priorities": [{"id": "PPRI1", "name": "P1"}]})
        assert result["status"] == "success"
        assert result["action"] == "list_priorities"
        assert result["data"]["priorities"][0]["id"] == "PPRI1"


# ============================================================================
# Trigger
# ============================================================================


class TestPagerDutyTriggerMock:
    @pytest.mark.asyncio
    async def test_on_incident_event_passthrough(self):
        """The trigger passes the inbound webhook payload through as output."""
        config = PagerDutyNodeConfig(
            config=PagerDutyIncidentTriggerConfig(webhook_url="https://abc.hooks.example.test"),
            credentials=None,
        )
        node = create_pagerduty_node(config)
        payload = {"event": {"event_type": "incident.triggered", "data": {"id": "PINC1"}}}
        result = await node.execute(payload)
        assert result["status"] == "success"
        assert result["action"] == "on_incident_event"
        assert result["data"]["event"]["event_type"] == "incident.triggered"
        assert result["data"]["webhook_url"] == "https://abc.hooks.example.test"

    @pytest.mark.asyncio
    async def test_register_external_webhook(self):
        with patch(
            "nodes.pagerduty_node._pagerduty_request",
            return_value={
                "status": "success",
                "data": {
                    "webhook_subscription": {
                        "id": "PWH99",
                        "delivery_method": {"secret": "whsec_abc"},
                    }
                },
            },
        ) as mock_req:
            extra = await PagerDutyNode._register_external_webhook(
                webhook_url="https://abc.hooks.example.test",
                credential={"api_key": "pd_test"},
                config={},
                node_id="node-1",
            )
        assert mock_req.called
        assert extra["external_webhook_id"] == "PWH99"
        assert extra["signing_secret"] == "whsec_abc"

    @pytest.mark.asyncio
    async def test_unregister_external_webhook(self):
        with patch(
            "nodes.pagerduty_node._pagerduty_request",
            return_value={"status": "success", "data": {}},
        ) as mock_req:
            await PagerDutyNode._unregister_external_webhook(
                credential={"api_key": "pd_test"},
                config={"external_webhook_id": "PWH99"},
                node_id="node-1",
            )
        assert mock_req.called

    def test_verify_webhook_signature(self):
        secret = "whsec_topsecret"
        body = b'{"event":{"event_type":"incident.triggered"}}'
        digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        good_sig = f"v1={digest}"
        assert PagerDutyNode.verify_webhook_signature(
            body, {"x-pagerduty-signature": good_sig}, {"signing_secret": secret}
        )
        # multiple comma-separated candidate signatures, one valid
        assert PagerDutyNode.verify_webhook_signature(
            body,
            {"x-pagerduty-signature": f"v1=deadbeef,{good_sig}"},
            {"signing_secret": secret},
        )
        assert not PagerDutyNode.verify_webhook_signature(
            body, {"x-pagerduty-signature": "v1=deadbeef"}, {"signing_secret": secret}
        )
        # no secret stored yet -> accept (trigger not armed)
        assert PagerDutyNode.verify_webhook_signature(body, {}, {})


# ============================================================================
# Error handling
# ============================================================================


class TestPagerDutyErrorHandlingMock:
    @pytest.mark.asyncio
    async def test_api_error(self, api_key_credentials):
        node = create_pagerduty_node(
            PagerDutyNodeConfig(
                config=PagerDutyGetIncidentConfig(incident_id="missing"),
                credentials=api_key_credentials,
            )
        )
        result = await _run(
            node, 404, {"error": {"message": "Not Found", "code": 2100, "errors": []}}
        )
        assert result["status"] == "error"
        assert result["status_code"] == 404
        assert "not found" in str(result["error"]).lower()

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        config = PagerDutyNodeConfig(config=PagerDutyGetCurrentUserConfig(), credentials=None)
        node = create_pagerduty_node(config)
        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})


# ============================================================================
# Dynamic options
# ============================================================================


class TestPagerDutyDynamicOptionsMock:
    @staticmethod
    async def _load(field_name, data, config_data=None):
        with patch(
            "nodes.pagerduty_node._pagerduty_request",
            return_value={"status": "success", "data": data},
        ) as mock_req:
            result = await PagerDutyNode.load_field_options(
                field_name,
                {"api_key": "pd_test"},
                context=config_data or {},
            )
        return result, mock_req

    @pytest.mark.asyncio
    async def test_load_service_options(self):
        result, _ = await self._load(
            "service_id", {"services": [{"id": "PSVC1", "name": "Payments"}]}
        )
        assert result["options"][0]["value"] == "PSVC1"
        assert result["options"][0]["label"] == "Payments"

    @pytest.mark.asyncio
    async def test_load_service_ids_options(self):
        result, mock_req = await self._load(
            "service_ids", {"services": [{"id": "PSVC2", "name": "Checkout"}]}
        )
        assert mock_req.call_args.args[2] == "/services"
        assert result["options"][0] == {"label": "Checkout", "value": "PSVC2"}

    @pytest.mark.asyncio
    async def test_load_team_options(self):
        result, mock_req = await self._load(
            "team_ids", {"teams": [{"id": "PTEAM1", "name": "SRE"}]}
        )
        assert mock_req.call_args.args[2] == "/teams"
        assert result["options"][0] == {"label": "SRE", "value": "PTEAM1"}

    @pytest.mark.asyncio
    async def test_load_priority_options(self):
        result, mock_req = await self._load(
            "priority_id", {"priorities": [{"id": "PPRI1", "name": "P1"}]}
        )
        assert mock_req.call_args.args[2] == "/priorities"
        assert result["options"][0] == {"label": "P1", "value": "PPRI1"}

    @pytest.mark.asyncio
    async def test_load_escalation_policy_options(self):
        result, mock_req = await self._load(
            "escalation_policy_id",
            {"escalation_policies": [{"id": "PEP1", "name": "Default EP"}]},
        )
        assert mock_req.call_args.args[2] == "/escalation_policies"
        assert result["options"][0] == {"label": "Default EP", "value": "PEP1"}

    @pytest.mark.asyncio
    async def test_load_escalation_policy_ids_options(self):
        result, mock_req = await self._load(
            "escalation_policy_ids",
            {"escalation_policies": [{"id": "PEP2", "name": "Backup EP"}]},
        )
        assert mock_req.call_args.args[2] == "/escalation_policies"
        assert result["options"][0] == {"label": "Backup EP", "value": "PEP2"}

    @pytest.mark.asyncio
    async def test_load_schedule_options(self):
        result, mock_req = await self._load(
            "schedule_id", {"schedules": [{"id": "PSCH1", "name": "Primary"}]}
        )
        assert mock_req.call_args.args[2] == "/schedules"
        assert result["options"][0] == {"label": "Primary", "value": "PSCH1"}

    @pytest.mark.asyncio
    async def test_load_schedule_ids_options(self):
        result, mock_req = await self._load(
            "schedule_ids", {"schedules": [{"id": "PSCH2", "name": "Secondary"}]}
        )
        assert mock_req.call_args.args[2] == "/schedules"
        assert result["options"][0] == {"label": "Secondary", "value": "PSCH2"}

    @pytest.mark.asyncio
    async def test_load_user_options_uses_name(self):
        result, mock_req = await self._load(
            "user_id", {"users": [{"id": "PUSER1", "name": "Ada", "email": "ada@x.com"}]}
        )
        assert mock_req.call_args.args[2] == "/users"
        # name preferred over email for the label
        assert result["options"][0] == {"label": "Ada", "value": "PUSER1"}

    @pytest.mark.asyncio
    async def test_load_user_ids_options(self):
        result, mock_req = await self._load(
            "user_ids", {"users": [{"id": "PUSER2", "name": "Grace"}]}
        )
        assert mock_req.call_args.args[2] == "/users"
        assert result["options"][0] == {"label": "Grace", "value": "PUSER2"}

    @pytest.mark.asyncio
    async def test_load_escalation_target_defaults_to_users(self):
        result, mock_req = await self._load(
            "escalation_target_id", {"users": [{"id": "PUSER1", "name": "Ada"}]}
        )
        # no escalation_target_type in config -> defaults to users
        assert mock_req.call_args.args[2] == "/users"
        assert result["options"][0] == {"label": "Ada", "value": "PUSER1"}

    @pytest.mark.asyncio
    async def test_load_escalation_target_schedule_via_depends_on(self):
        result, mock_req = await self._load(
            "escalation_target_id",
            {"schedules": [{"id": "PSCH1", "name": "Primary"}]},
            config_data={"escalation_target_type": "schedule_reference"},
        )
        # depends_on the sibling field -> schedules endpoint
        assert mock_req.call_args.args[2] == "/schedules"
        assert result["options"][0] == {"label": "Primary", "value": "PSCH1"}

    @pytest.mark.asyncio
    async def test_load_unknown_field_returns_empty(self):
        result = await PagerDutyNode.load_field_options(
            "definitely_not_a_field", {"api_key": "pd_test"}, context={}
        )
        assert result == {"options": []}


# ============================================================================
# Full coverage: parametrized mock tests for all expanded operations
# ============================================================================
from nodes.pagerduty_node import (
    PagerDutyAddStatusUpdateSubscribersConfig,
    PagerDutyAddTeamMemberConfig,
    PagerDutyAssociateServiceDependenciesConfig,
    PagerDutyAssociateTeamEscalationPolicyConfig,
    PagerDutyAssociateTriggerServiceConfig,
    PagerDutyChangeTagsConfig,
    PagerDutyCreateAddonConfig,
    PagerDutyCreateAutomationActionConfig,
    PagerDutyCreateBusinessServiceConfig,
    PagerDutyCreateBusinessServiceSubscribersConfig,
    PagerDutyCreateContactMethodConfig,
    PagerDutyCreateCustomFieldConfig,
    PagerDutyCreateEventOrchestrationConfig,
    PagerDutyCreateExtensionConfig,
    PagerDutyCreateFieldOptionConfig,
    PagerDutyCreateIncidentWorkflowConfig,
    PagerDutyCreateIncidentWorkflowTriggerConfig,
    PagerDutyCreateNotificationRuleConfig,
    PagerDutyCreateOrchestrationIntegrationConfig,
    PagerDutyCreateOverrideConfig,
    PagerDutyCreateResponsePlayConfig,
    PagerDutyCreateRulesetConfig,
    PagerDutyCreateRulesetRuleConfig,
    PagerDutyCreateRunnerConfig,
    PagerDutyCreateScheduleConfig,
    PagerDutyCreateServiceEventRuleConfig,
    PagerDutyCreateServiceIntegrationConfig,
    PagerDutyCreateStatusPagePostConfig,
    PagerDutyCreateStatusPagePostUpdateConfig,
    PagerDutyCreateStatusPageSubscriptionConfig,
    PagerDutyCreateTagConfig,
    PagerDutyCreateTeamConfig,
    PagerDutyCreateTemplateConfig,
    PagerDutyDeleteAddonConfig,
    PagerDutyDeleteAutomationActionConfig,
    PagerDutyDeleteBusinessServiceConfig,
    PagerDutyDeleteContactMethodConfig,
    PagerDutyDeleteCustomFieldConfig,
    PagerDutyDeleteEscalationPolicyConfig,
    PagerDutyDeleteEventOrchestrationConfig,
    PagerDutyDeleteExtensionConfig,
    PagerDutyDeleteFieldOptionConfig,
    PagerDutyDeleteIncidentWorkflowConfig,
    PagerDutyDeleteIncidentWorkflowTriggerConfig,
    PagerDutyDeleteMaintenanceWindowConfig,
    PagerDutyDeleteNotificationRuleConfig,
    PagerDutyDeleteOrchestrationIntegrationConfig,
    PagerDutyDeleteOverrideConfig,
    PagerDutyDeletePriorityThresholdsConfig,
    PagerDutyDeleteResponsePlayConfig,
    PagerDutyDeleteRulesetConfig,
    PagerDutyDeleteRulesetRuleConfig,
    PagerDutyDeleteRunnerConfig,
    PagerDutyDeleteScheduleConfig,
    PagerDutyDeleteServiceConfig,
    PagerDutyDeleteServiceEventRuleConfig,
    PagerDutyDeleteStatusPagePostConfig,
    PagerDutyDeleteStatusPagePostUpdateConfig,
    PagerDutyDeleteStatusPageSubscriptionConfig,
    PagerDutyDeleteTagConfig,
    PagerDutyDeleteTeamConfig,
    PagerDutyDeleteTemplateConfig,
    PagerDutyDeleteUserConfig,
    PagerDutyDeleteWebhookSubscriptionConfig,
    PagerDutyDisableWebhookSubscriptionConfig,
    PagerDutyDisassociateServiceDependenciesConfig,
    PagerDutyDisassociateTriggerServiceConfig,
    PagerDutyEnableExtensionConfig,
    PagerDutyEnableWebhookSubscriptionConfig,
    PagerDutyGetAddonConfig,
    PagerDutyGetAlertConfig,
    PagerDutyGetAutomationActionConfig,
    PagerDutyGetBusinessServiceConfig,
    PagerDutyGetBusinessServiceDependenciesConfig,
    PagerDutyGetContactMethodConfig,
    PagerDutyGetCustomFieldConfig,
    PagerDutyGetEscalationPolicyConfig,
    PagerDutyGetEventOrchestrationConfig,
    PagerDutyGetExtensionConfig,
    PagerDutyGetExtensionSchemaConfig,
    PagerDutyGetFieldOptionConfig,
    PagerDutyGetIncidentCustomFieldsConfig,
    PagerDutyGetIncidentWorkflowConfig,
    PagerDutyGetIncidentWorkflowTriggerConfig,
    PagerDutyGetInvocationConfig,
    PagerDutyGetLogEntryConfig,
    PagerDutyGetMaintenanceWindowConfig,
    PagerDutyGetNotificationRuleConfig,
    PagerDutyGetOrchestrationGlobalConfig,
    PagerDutyGetOrchestrationIntegrationConfig,
    PagerDutyGetOrchestrationRouterConfig,
    PagerDutyGetOutlierIncidentConfig,
    PagerDutyGetPastIncidentsConfig,
    PagerDutyGetPriorityThresholdsConfig,
    PagerDutyGetRawIncidentConfig,
    PagerDutyGetRelatedIncidentsConfig,
    PagerDutyGetResponsePlayConfig,
    PagerDutyGetRulesetConfig,
    PagerDutyGetRulesetRuleConfig,
    PagerDutyGetRunnerConfig,
    PagerDutyGetServiceEventRuleConfig,
    PagerDutyGetServiceIntegrationConfig,
    PagerDutyGetServiceOrchestrationActiveConfig,
    PagerDutyGetServiceOrchestrationConfig,
    PagerDutyGetStatusDashboardBySlugConfig,
    PagerDutyGetStatusDashboardConfig,
    PagerDutyGetStatusDashboardServiceImpactsConfig,
    PagerDutyGetStatusPagePostConfig,
    PagerDutyGetStatusPagePostUpdateConfig,
    PagerDutyGetStatusPageSubscriptionConfig,
    PagerDutyGetTagConfig,
    PagerDutyGetTagsForEntityConfig,
    PagerDutyGetTeamConfig,
    PagerDutyGetTechnicalServiceDependenciesConfig,
    PagerDutyGetTemplateConfig,
    PagerDutyGetVendorConfig,
    PagerDutyGetWebhookSubscriptionConfig,
    PagerDutyIncidentMetricsByDimensionConfig,
    PagerDutyIncidentMetricsConfig,
    PagerDutyInvokeAutomationActionConfig,
    PagerDutyListAbilitiesConfig,
    PagerDutyListAddonsConfig,
    PagerDutyListAuditRecordsConfig,
    PagerDutyListAutomationActionsConfig,
    PagerDutyListBusinessServiceImpactorsConfig,
    PagerDutyListBusinessServiceImpactsConfig,
    PagerDutyListBusinessServiceSubscribersConfig,
    PagerDutyListBusinessServicesConfig,
    PagerDutyListChangeEventsConfig,
    PagerDutyListContactMethodsConfig,
    PagerDutyListCustomFieldsConfig,
    PagerDutyListEventOrchestrationsConfig,
    PagerDutyListExtensionSchemasConfig,
    PagerDutyListExtensionsConfig,
    PagerDutyListFieldOptionsConfig,
    PagerDutyListGlobalLogEntriesConfig,
    PagerDutyListIncidentWorkflowTriggersConfig,
    PagerDutyListIncidentWorkflowsConfig,
    PagerDutyListInvocationsConfig,
    PagerDutyListLicenseAllocationsConfig,
    PagerDutyListLicensesConfig,
    PagerDutyListNotificationRulesConfig,
    PagerDutyListNotificationsConfig,
    PagerDutyListOrchestrationIntegrationsConfig,
    PagerDutyListOverridesConfig,
    PagerDutyListRelatedChangeEventsConfig,
    PagerDutyListResponsePlaysConfig,
    PagerDutyListRulesetRulesConfig,
    PagerDutyListRulesetsConfig,
    PagerDutyListRunnersConfig,
    PagerDutyListServiceChangeEventsConfig,
    PagerDutyListServiceEventRulesConfig,
    PagerDutyListStatusDashboardsConfig,
    PagerDutyListStatusPagePostUpdatesConfig,
    PagerDutyListStatusPagePostsConfig,
    PagerDutyListStatusPageSubscriptionsConfig,
    PagerDutyListStatusPagesConfig,
    PagerDutyListStatusUpdateSubscribersConfig,
    PagerDutyListTagsConfig,
    PagerDutyListTeamMembersConfig,
    PagerDutyListTemplatesConfig,
    PagerDutyListUsersOnScheduleConfig,
    PagerDutyListVendorsConfig,
    PagerDutyManageAlertsConfig,
    PagerDutyPausedIncidentReportAlertsConfig,
    PagerDutyPausedIncidentReportCountsConfig,
    PagerDutyPingWebhookSubscriptionConfig,
    PagerDutyPreviewScheduleConfig,
    PagerDutyRawIncidentResponsesConfig,
    PagerDutyRawIncidentsConfig,
    PagerDutyRemoveBusinessServiceSubscribersConfig,
    PagerDutyRemoveStatusUpdateSubscriberConfig,
    PagerDutyRemoveTeamEscalationPolicyConfig,
    PagerDutyRemoveTeamMemberConfig,
    PagerDutyRenderTemplateConfig,
    PagerDutyResponderMetricsConfig,
    PagerDutyRunResponsePlayConfig,
    PagerDutySendChangeEventConfig,
    PagerDutySetPriorityThresholdConfig,
    PagerDutySetServiceOrchestrationActiveConfig,
    PagerDutyStartIncidentWorkflowConfig,
    PagerDutyTestAbilityConfig,
    PagerDutyUpdateAddonConfig,
    PagerDutyUpdateAlertConfig,
    PagerDutyUpdateAutomationActionConfig,
    PagerDutyUpdateBusinessServiceConfig,
    PagerDutyUpdateContactMethodConfig,
    PagerDutyUpdateCustomFieldConfig,
    PagerDutyUpdateEscalationPolicyConfig,
    PagerDutyUpdateEventOrchestrationConfig,
    PagerDutyUpdateExtensionConfig,
    PagerDutyUpdateFieldOptionConfig,
    PagerDutyUpdateIncidentCustomFieldsConfig,
    PagerDutyUpdateIncidentWorkflowConfig,
    PagerDutyUpdateIncidentWorkflowTriggerConfig,
    PagerDutyUpdateMaintenanceWindowConfig,
    PagerDutyUpdateNotificationRuleConfig,
    PagerDutyUpdateOrchestrationGlobalConfig,
    PagerDutyUpdateOrchestrationIntegrationConfig,
    PagerDutyUpdateOrchestrationRouterConfig,
    PagerDutyUpdateResponsePlayConfig,
    PagerDutyUpdateRulesetConfig,
    PagerDutyUpdateRulesetRuleConfig,
    PagerDutyUpdateRunnerConfig,
    PagerDutyUpdateScheduleConfig,
    PagerDutyUpdateServiceEventRuleConfig,
    PagerDutyUpdateServiceIntegrationConfig,
    PagerDutyUpdateServiceOrchestrationConfig,
    PagerDutyUpdateStatusPagePostConfig,
    PagerDutyUpdateStatusPagePostUpdateConfig,
    PagerDutyUpdateTeamConfig,
    PagerDutyUpdateTemplateConfig,
    PagerDutyUpdateUserConfig,
    PagerDutyUpdateWebhookSubscriptionConfig,
)

_PD_COVERAGE_PARAMS = [
    # incidents-extended
    (PagerDutyGetAlertConfig(incident_id="PINC001", alert_id="PPGATO4"), "get_alert", {"alert": {"id": "PPGATO4", "type": "alert", "summary": "Server on fire", "status": "triggered", "incident": {"id": "PINC001", "type": "incident_reference"}}}),
    (PagerDutyUpdateAlertConfig(incident_id="PINC001", alert_id="PPGATO4", status="resolved"), "update_alert", {"alert": {"id": "PPGATO4", "type": "alert", "status": "resolved"}}),
    (PagerDutyManageAlertsConfig(incident_id="PINC001", alert_ids="PPGATO4,PPGATO5", status="resolved"), "manage_alerts", {"alerts": [{"id": "PPGATO4", "type": "alert", "status": "resolved"}, {"id": "PPGATO5", "type": "alert", "status": "resolved"}]}),
    (PagerDutyGetIncidentCustomFieldsConfig(incident_id="PINC001"), "get_incident_custom_fields", {"custom_fields": [{"id": "PXYZ123", "name": "environment", "value": "production"}]}),
    (PagerDutyUpdateIncidentCustomFieldsConfig(incident_id="PINC001", custom_fields='[{"id": "PXYZ123", "value": "staging"}]'), "update_incident_custom_fields", {"custom_fields": [{"id": "PXYZ123", "name": "environment", "value": "staging"}]}),
    (PagerDutyListRelatedChangeEventsConfig(incident_id="PINC001"), "list_related_change_events", {"change_events": [{"id": "PCHG001", "summary": "Deployed payments v2", "source": "GitHub"}]}),
    (PagerDutyGetPastIncidentsConfig(incident_id="PINC001", limit="5"), "get_past_incidents", {"past_incidents": [{"incident": {"id": "PABC999", "title": "Prior payments outage"}, "score": 190.5}]}),
    (PagerDutyGetRelatedIncidentsConfig(incident_id="PINC001"), "get_related_incidents", {"related_incidents": [{"incident": {"id": "PDEF888", "title": "Related DB outage"}, "relationships": [{"type": "machine_learning_inferred"}]}]}),
    (PagerDutyGetOutlierIncidentConfig(incident_id="PINC001"), "get_outlier_incident", {"outlier_incident": {"incident": {"id": "PINC001"}, "outlier": True, "incident_template": {"id": "PTMPL01"}}}),
    (PagerDutyListStatusUpdateSubscribersConfig(incident_id="PINC001"), "list_status_update_subscribers", {"subscribers": [{"subscriber_id": "PUSER01", "subscriber_type": "user"}]}),
    (PagerDutyAddStatusUpdateSubscribersConfig(incident_id="PINC001", subscriber_ids="PUSER01,PUSER02", subscriber_type="user"), "add_status_update_subscribers", {"subscriptions": [{"subscriber_id": "PUSER01", "subscriber_type": "user", "result": "success"}, {"subscriber_id": "PUSER02", "subscriber_type": "user", "result": "success"}]}),
    (PagerDutyRemoveStatusUpdateSubscriberConfig(incident_id="PINC001", subscriber_ids="PUSER01", subscriber_type="user"), "remove_status_update_subscriber", {"delete_count": 1}),
    (PagerDutyListGlobalLogEntriesConfig(limit="25"), "list_global_log_entries", {"log_entries": [{"id": "PLOG001", "type": "trigger_log_entry", "summary": "Triggered through the API"}]}),
    (PagerDutyGetLogEntryConfig(log_entry_id="PLOG001"), "get_log_entry", {"log_entry": {"id": "PLOG001", "type": "trigger_log_entry", "summary": "Triggered through the API"}}),
    # services-full
    (PagerDutyDeleteServiceConfig(service_id="PSVC001"), "delete_service", {"success": True}),
    (PagerDutyAssociateServiceDependenciesConfig(relationships='[{"dependent_service":{"id":"PBIZ001","type":"business_service_reference"},"supporting_service":{"id":"PTECH01","type":"technical_service_reference"}}]'), "associate_service_dependencies", {"relationships": [{"id": "PDEP001", "type": "service_dependency", "dependent_service": {"id": "PBIZ001", "type": "business_service_reference"}, "supporting_service": {"id": "PTECH01", "type": "technical_service_reference"}}]}),
    (PagerDutyDisassociateServiceDependenciesConfig(relationships='[{"dependent_service":{"id":"PBIZ001","type":"business_service_reference"},"supporting_service":{"id":"PTECH01","type":"technical_service_reference"}}]'), "disassociate_service_dependencies", {"relationships": []}),
    (PagerDutyGetTechnicalServiceDependenciesConfig(service_id="PTECH01"), "get_technical_service_dependencies", {"relationships": [{"id": "PDEP001", "type": "service_dependency", "supporting_service": {"id": "PTECH02", "type": "technical_service_reference"}, "dependent_service": {"id": "PTECH01", "type": "technical_service_reference"}}]}),
    (PagerDutyGetBusinessServiceDependenciesConfig(business_service_id="PBIZ001"), "get_business_service_dependencies", {"relationships": [{"id": "PDEP002", "type": "service_dependency", "supporting_service": {"id": "PTECH01", "type": "technical_service_reference"}, "dependent_service": {"id": "PBIZ001", "type": "business_service_reference"}}]}),
    (PagerDutyCreateServiceIntegrationConfig(service_id="PSVC001", integration_type="events_api_v2_inbound_integration", name="Datadog Alerts"), "create_service_integration", {"integration": {"id": "PINT001", "type": "events_api_v2_inbound_integration", "name": "Datadog Alerts", "integration_key": "abc123def456abc123def456abc12345"}}),
    (PagerDutyGetServiceIntegrationConfig(service_id="PSVC001", integration_id="PINT001"), "get_service_integration", {"integration": {"id": "PINT001", "type": "events_api_v2_inbound_integration", "name": "Datadog Alerts", "integration_key": "abc123def456abc123def456abc12345"}}),
    (PagerDutyUpdateServiceIntegrationConfig(service_id="PSVC001", integration_id="PINT001", integration_type="events_api_v2_inbound_integration", name="Datadog Alerts (Prod)"), "update_service_integration", {"integration": {"id": "PINT001", "type": "events_api_v2_inbound_integration", "name": "Datadog Alerts (Prod)"}}),
    (PagerDutyListServiceEventRulesConfig(service_id="PSVC001"), "list_service_event_rules", {"rules": [{"id": "PRULE01", "position": 0, "disabled": False}], "total": 1, "offset": 0, "limit": 25, "more": False}),
    (PagerDutyCreateServiceEventRuleConfig(service_id="PSVC001", conditions='{"operator":"and","subconditions":[{"operator":"contains","parameters":{"path":"payload.summary","value":"cpu"}}]}', actions='{"severity":{"value":"critical"}}', position="0", disabled="false"), "create_service_event_rule", {"rule": {"id": "PRULE01", "position": 0, "disabled": False, "conditions": {"operator": "and", "subconditions": [{"operator": "contains", "parameters": {"path": "payload.summary", "value": "cpu"}}]}, "actions": {"severity": {"value": "critical"}}}}),
    (PagerDutyGetServiceEventRuleConfig(service_id="PSVC001", rule_id="PRULE01"), "get_service_event_rule", {"rule": {"id": "PRULE01", "position": 0, "disabled": False}}),
    (PagerDutyUpdateServiceEventRuleConfig(service_id="PSVC001", rule_id="PRULE01", disabled="true"), "update_service_event_rule", {"rule": {"id": "PRULE01", "position": 0, "disabled": True}}),
    (PagerDutyDeleteServiceEventRuleConfig(service_id="PSVC001", rule_id="PRULE01"), "delete_service_event_rule", {"success": True}),
    # schedules-full
    (
        PagerDutyCreateScheduleConfig(
            schedule='{"name":"Daytime Coverage","time_zone":"America/New_York","schedule_layers":[{"start":"2026-07-01T09:00:00-04:00","rotation_virtual_start":"2026-07-01T09:00:00-04:00","rotation_turn_length_seconds":86400,"users":[{"user":{"id":"PABC123","type":"user_reference"}}]}]}'
        ),
        "create_schedule",
        {"schedule": {"id": "PSCHED1", "name": "Daytime Coverage", "type": "schedule"}},
    ),
    (
        PagerDutyUpdateScheduleConfig(
            schedule_id="PSCHED1",
            schedule='{"name":"Nights Coverage","time_zone":"America/New_York","schedule_layers":[]}',
        ),
        "update_schedule",
        {"schedule": {"id": "PSCHED1", "name": "Nights Coverage", "type": "schedule"}},
    ),
    (
        PagerDutyDeleteScheduleConfig(schedule_id="PSCHED1"),
        "delete_schedule",
        {"success": True},
    ),
    (
        PagerDutyPreviewScheduleConfig(
            schedule='{"name":"Preview","time_zone":"UTC","schedule_layers":[]}',
            since="2026-07-01T00:00:00Z",
            until="2026-07-08T00:00:00Z",
            overflow="true",
        ),
        "preview_schedule",
        {"schedule": {"final_schedule": {"name": "Final Schedule", "rendered_schedule_entries": []}}},
    ),
    (
        PagerDutyListUsersOnScheduleConfig(
            schedule_id="PSCHED1",
            since="2026-07-01T00:00:00Z",
            until="2026-07-08T00:00:00Z",
        ),
        "list_users_on_schedule",
        {"users": [{"id": "PABC123", "type": "user", "summary": "Jane Doe"}]},
    ),
    (
        PagerDutyListOverridesConfig(
            schedule_id="PSCHED1",
            since="2026-07-01T00:00:00Z",
            until="2026-07-08T00:00:00Z",
            editable="false",
        ),
        "list_overrides",
        {"overrides": [{"id": "POVR1", "start": "2026-07-04T00:00:00Z", "end": "2026-07-05T00:00:00Z"}]},
    ),
    (
        PagerDutyCreateOverrideConfig(
            schedule_id="PSCHED1",
            user_id="PABC123",
            start="2026-07-04T00:00:00Z",
            end="2026-07-05T00:00:00Z",
        ),
        "create_override",
        {"overrides": [{"status": 201, "override": {"id": "POVR1", "start": "2026-07-04T00:00:00Z", "end": "2026-07-05T00:00:00Z"}}]},
    ),
    (
        PagerDutyDeleteOverrideConfig(schedule_id="PSCHED1", override_id="POVR1"),
        "delete_override",
        {"success": True},
    ),
    (
        PagerDutyGetEscalationPolicyConfig(escalation_policy_id="PEP1234"),
        "get_escalation_policy",
        {"escalation_policy": {"id": "PEP1234", "name": "Default Policy", "type": "escalation_policy"}},
    ),
    (
        PagerDutyUpdateEscalationPolicyConfig(
            escalation_policy_id="PEP1234",
            name="Renamed Policy",
            description="Primary on-call rotation",
        ),
        "update_escalation_policy",
        {"escalation_policy": {"id": "PEP1234", "name": "Renamed Policy", "type": "escalation_policy"}},
    ),
    (
        PagerDutyDeleteEscalationPolicyConfig(escalation_policy_id="PEP1234"),
        "delete_escalation_policy",
        {"success": True},
    ),
    # users-teams-full
    (PagerDutyUpdateUserConfig(user_id="PUSER01", name="Jane Doe", role="user", time_zone="America/New_York"), "update_user", {"user": {"id": "PUSER01", "type": "user", "name": "Jane Doe", "role": "user"}}),
    (PagerDutyDeleteUserConfig(user_id="PUSER01"), "delete_user", {"success": True}),
    (PagerDutyListContactMethodsConfig(user_id="PUSER01"), "list_contact_methods", {"contact_methods": [{"id": "PCM01", "type": "email_contact_method", "label": "Work", "address": "jane@example.com"}]}),
    (PagerDutyCreateContactMethodConfig(user_id="PUSER01", type="phone_contact_method", label="Mobile", address="4155551234", country_code="1"), "create_contact_method", {"contact_method": {"id": "PCM02", "type": "phone_contact_method", "label": "Mobile", "address": "4155551234", "country_code": 1}}),
    (PagerDutyGetContactMethodConfig(user_id="PUSER01", contact_method_id="PCM01"), "get_contact_method", {"contact_method": {"id": "PCM01", "type": "email_contact_method", "label": "Work", "address": "jane@example.com"}}),
    (PagerDutyUpdateContactMethodConfig(user_id="PUSER01", contact_method_id="PCM01", type="email_contact_method", label="Home", address="jane.home@example.com"), "update_contact_method", {"contact_method": {"id": "PCM01", "type": "email_contact_method", "label": "Home", "address": "jane.home@example.com"}}),
    (PagerDutyDeleteContactMethodConfig(user_id="PUSER01", contact_method_id="PCM01"), "delete_contact_method", {"success": True}),
    (PagerDutyListNotificationRulesConfig(user_id="PUSER01"), "list_notification_rules", {"notification_rules": [{"id": "PNR01", "type": "assignment_notification_rule", "start_delay_in_minutes": 0, "urgency": "high"}]}),
    (PagerDutyCreateNotificationRuleConfig(user_id="PUSER01", contact_method_id="PCM01", contact_method_type="email_contact_method_reference", start_delay_in_minutes="0", urgency="high"), "create_notification_rule", {"notification_rule": {"id": "PNR02", "type": "assignment_notification_rule", "start_delay_in_minutes": 0, "urgency": "high", "contact_method": {"id": "PCM01", "type": "email_contact_method_reference"}}}),
    (PagerDutyGetNotificationRuleConfig(user_id="PUSER01", notification_rule_id="PNR01"), "get_notification_rule", {"notification_rule": {"id": "PNR01", "type": "assignment_notification_rule", "start_delay_in_minutes": 0, "urgency": "high"}}),
    (PagerDutyUpdateNotificationRuleConfig(user_id="PUSER01", notification_rule_id="PNR01", start_delay_in_minutes="5", urgency="low"), "update_notification_rule", {"notification_rule": {"id": "PNR01", "type": "assignment_notification_rule", "start_delay_in_minutes": 5, "urgency": "low"}}),
    (PagerDutyDeleteNotificationRuleConfig(user_id="PUSER01", notification_rule_id="PNR01"), "delete_notification_rule", {"success": True}),
    (PagerDutyGetTeamConfig(team_id="PTEAM01"), "get_team", {"team": {"id": "PTEAM01", "type": "team", "name": "Engineering"}}),
    (PagerDutyCreateTeamConfig(name="Engineering", description="The engineering team"), "create_team", {"team": {"id": "PTEAM02", "type": "team", "name": "Engineering", "description": "The engineering team"}}),
    (PagerDutyUpdateTeamConfig(team_id="PTEAM01", name="Platform", description="Platform team"), "update_team", {"team": {"id": "PTEAM01", "type": "team", "name": "Platform", "description": "Platform team"}}),
    (PagerDutyDeleteTeamConfig(team_id="PTEAM01"), "delete_team", {"success": True}),
    (PagerDutyListTeamMembersConfig(team_id="PTEAM01"), "list_team_members", {"members": [{"user": {"id": "PUSER01", "type": "user_reference"}, "role": "manager"}]}),
    (PagerDutyAddTeamMemberConfig(team_id="PTEAM01", user_id="PUSER01", role="responder"), "add_team_member", {"success": True}),
    (PagerDutyRemoveTeamMemberConfig(team_id="PTEAM01", user_id="PUSER01"), "remove_team_member", {"success": True}),
    (PagerDutyAssociateTeamEscalationPolicyConfig(team_id="PTEAM01", escalation_policy_id="PEP01"), "associate_team_escalation_policy", {"success": True}),
    (PagerDutyRemoveTeamEscalationPolicyConfig(team_id="PTEAM01", escalation_policy_id="PEP01"), "remove_team_escalation_policy", {"success": True}),
    # maintenance-webhooks-full
    (PagerDutyGetMaintenanceWindowConfig(maintenance_window_id="PMW1234"), "get_maintenance_window", {"maintenance_window": {"id": "PMW1234", "summary": "DB upgrade", "status": "ongoing"}}),
    (PagerDutyUpdateMaintenanceWindowConfig(maintenance_window_id="PMW1234", start_time="2026-07-05T00:00:00Z", end_time="2026-07-05T02:00:00Z", service_ids="PSVC1,PSVC2", description="Extended window"), "update_maintenance_window", {"maintenance_window": {"id": "PMW1234", "status": "future"}}),
    (PagerDutyDeleteMaintenanceWindowConfig(maintenance_window_id="PMW1234"), "delete_maintenance_window", {"success": True}),
    (PagerDutyGetWebhookSubscriptionConfig(webhook_subscription_id="PWH1234"), "get_webhook_subscription", {"webhook_subscription": {"id": "PWH1234", "active": True, "type": "webhook_subscription"}}),
    (PagerDutyUpdateWebhookSubscriptionConfig(webhook_subscription_id="PWH1234", delivery_url="https://example.com/hook", events="incident.triggered,incident.resolved", description="Prod incidents"), "update_webhook_subscription", {"webhook_subscription": {"id": "PWH1234", "active": True}}),
    (PagerDutyDeleteWebhookSubscriptionConfig(webhook_subscription_id="PWH1234"), "delete_webhook_subscription", {"success": True}),
    (PagerDutyEnableWebhookSubscriptionConfig(webhook_subscription_id="PWH1234"), "enable_webhook_subscription", {"webhook_subscription": {"id": "PWH1234", "active": True}}),
    (PagerDutyDisableWebhookSubscriptionConfig(webhook_subscription_id="PWH1234"), "disable_webhook_subscription", {"webhook_subscription": {"id": "PWH1234", "active": False}}),
    (PagerDutyPingWebhookSubscriptionConfig(webhook_subscription_id="PWH1234"), "ping_webhook_subscription", {"success": True}),
    (PagerDutyListExtensionsConfig(query="slack", limit="25"), "list_extensions", {"extensions": [{"id": "PEXT1", "name": "Slack Notifications", "type": "extension"}], "limit": 25, "more": False}),
    (PagerDutyCreateExtensionConfig(name="Slack Notifications", extension_schema_id="PES1234", service_ids="PSVC1,PSVC2", endpoint_url="https://hooks.example.com/x"), "create_extension", {"extension": {"id": "PEXT1", "name": "Slack Notifications"}}),
    (PagerDutyGetExtensionConfig(extension_id="PEXT1"), "get_extension", {"extension": {"id": "PEXT1", "name": "Slack Notifications"}}),
    (PagerDutyUpdateExtensionConfig(extension_id="PEXT1", name="Renamed Ext", endpoint_url="https://hooks.example.com/y", service_ids="PSVC3"), "update_extension", {"extension": {"id": "PEXT1", "name": "Renamed Ext"}}),
    (PagerDutyDeleteExtensionConfig(extension_id="PEXT1"), "delete_extension", {"success": True}),
    (PagerDutyEnableExtensionConfig(extension_id="PEXT1"), "enable_extension", {"extension": {"id": "PEXT1", "temporarily_disabled": False}}),
    (PagerDutyListExtensionSchemasConfig(limit="25"), "list_extension_schemas", {"extension_schemas": [{"id": "PES1234", "label": "Generic V2 Webhook", "type": "extension_schema"}], "limit": 25, "more": False}),
    (PagerDutyGetExtensionSchemaConfig(extension_schema_id="PES1234"), "get_extension_schema", {"extension_schema": {"id": "PES1234", "label": "Generic V2 Webhook"}}),
    # event-orchestrations
    (PagerDutyListEventOrchestrationsConfig(limit="25"), "list_event_orchestrations", {"orchestrations": [{"id": "b1b2b3", "name": "Production Orchestration"}], "limit": 25, "more": False}),
    (PagerDutyGetEventOrchestrationConfig(orchestration_id="b1b2b3"), "get_event_orchestration", {"orchestration": {"id": "b1b2b3", "name": "Production Orchestration", "routes": 2}}),
    (PagerDutyCreateEventOrchestrationConfig(name="New Orchestration", description="Routes prod alerts", team_id="PIJ90N7"), "create_event_orchestration", {"orchestration": {"id": "c9c9c9", "name": "New Orchestration", "description": "Routes prod alerts"}}),
    (PagerDutyUpdateEventOrchestrationConfig(orchestration_id="b1b2b3", name="Renamed Orchestration"), "update_event_orchestration", {"orchestration": {"id": "b1b2b3", "name": "Renamed Orchestration"}}),
    (PagerDutyDeleteEventOrchestrationConfig(orchestration_id="b1b2b3"), "delete_event_orchestration", {"success": True}),
    (PagerDutyGetOrchestrationRouterConfig(orchestration_id="b1b2b3"), "get_orchestration_router", {"orchestration_path": {"type": "router", "sets": [{"id": "start", "rules": []}], "catch_all": {"actions": {"route_to": "unrouted"}}}}),
    (PagerDutyUpdateOrchestrationRouterConfig(orchestration_id="b1b2b3", orchestration_path='{"sets": [{"id": "start", "rules": [{"label": "route DB alerts", "conditions": [{"expression": "event.source matches part \'db\'"}], "actions": {"route_to": "PXYZ123"}}]}], "catch_all": {"actions": {"route_to": "unrouted"}}}'), "update_orchestration_router", {"orchestration_path": {"type": "router", "sets": [{"id": "start", "rules": [{"id": "1", "label": "route DB alerts"}]}]}}),
    (PagerDutyGetOrchestrationGlobalConfig(orchestration_id="b1b2b3"), "get_orchestration_global", {"orchestration_path": {"type": "global", "sets": [{"id": "start", "rules": []}], "catch_all": {"actions": {}}}}),
    (PagerDutyUpdateOrchestrationGlobalConfig(orchestration_id="b1b2b3", orchestration_path='{"sets": [{"id": "start", "rules": [{"label": "suppress info", "conditions": [{"expression": "event.severity matches \'info\'"}], "actions": {"suppress": true}}]}], "catch_all": {"actions": {}}}'), "update_orchestration_global", {"orchestration_path": {"type": "global", "sets": [{"id": "start", "rules": [{"id": "r1", "label": "suppress info"}]}]}}),
    (PagerDutyGetServiceOrchestrationConfig(service_id="PXYZ123"), "get_service_orchestration", {"orchestration_path": {"type": "service", "parent": {"id": "PXYZ123", "type": "service_reference"}, "sets": [{"id": "start", "rules": []}]}}),
    (PagerDutyUpdateServiceOrchestrationConfig(service_id="PXYZ123", orchestration_path='{"sets": [{"id": "start", "rules": [{"label": "urgent", "conditions": [{"expression": "event.custom_details.type matches \'outage\'"}], "actions": {"severity": "critical"}}]}], "catch_all": {"actions": {}}}'), "update_service_orchestration", {"orchestration_path": {"type": "service", "parent": {"id": "PXYZ123", "type": "service_reference"}, "sets": [{"id": "start", "rules": [{"id": "s1", "label": "urgent"}]}]}}),
    (PagerDutyGetServiceOrchestrationActiveConfig(service_id="PXYZ123"), "get_service_orchestration_active", {"active": True}),
    (PagerDutySetServiceOrchestrationActiveConfig(service_id="PXYZ123", active="true"), "set_service_orchestration_active", {"active": True}),
    (PagerDutyListOrchestrationIntegrationsConfig(orchestration_id="b1b2b3"), "list_orchestration_integrations", {"integrations": [{"id": "9c5ff030", "label": "Datadog", "parameters": {"routing_key": "R0257B3", "type": "global"}}]}),
    (PagerDutyCreateOrchestrationIntegrationConfig(orchestration_id="b1b2b3", label="Grafana"), "create_orchestration_integration", {"integration": {"id": "1b2c3d4e", "label": "Grafana", "parameters": {"routing_key": "R0AB12C", "type": "global"}}}),
    (PagerDutyGetOrchestrationIntegrationConfig(orchestration_id="b1b2b3", integration_id="9c5ff030"), "get_orchestration_integration", {"integration": {"id": "9c5ff030", "label": "Datadog", "parameters": {"routing_key": "R0257B3", "type": "global"}}}),
    (PagerDutyUpdateOrchestrationIntegrationConfig(orchestration_id="b1b2b3", integration_id="9c5ff030", label="Datadog Prod"), "update_orchestration_integration", {"integration": {"id": "9c5ff030", "label": "Datadog Prod"}}),
    (PagerDutyDeleteOrchestrationIntegrationConfig(orchestration_id="b1b2b3", integration_id="9c5ff030"), "delete_orchestration_integration", {"success": True}),
    (PagerDutyListRulesetsConfig(limit="25"), "list_rulesets", {"rulesets": [{"id": "abc123", "name": "Default Global", "type": "ruleset", "routing_keys": ["R0257B3"]}], "limit": 25, "more": False}),
    (PagerDutyCreateRulesetConfig(name="Prod Ruleset"), "create_ruleset", {"ruleset": {"id": "def456", "name": "Prod Ruleset", "type": "ruleset", "routing_keys": ["R0XY12Z"]}}),
    (PagerDutyGetRulesetConfig(ruleset_id="abc123"), "get_ruleset", {"ruleset": {"id": "abc123", "name": "Default Global", "type": "ruleset"}}),
    (PagerDutyUpdateRulesetConfig(ruleset_id="abc123", name="Renamed Ruleset"), "update_ruleset", {"ruleset": {"id": "abc123", "name": "Renamed Ruleset"}}),
    (PagerDutyDeleteRulesetConfig(ruleset_id="abc123"), "delete_ruleset", {"success": True}),
    (PagerDutyListRulesetRulesConfig(ruleset_id="abc123"), "list_ruleset_rules", {"rules": [{"id": "9b5dcb28", "disabled": False, "conditions": {"operator": "and", "subconditions": []}, "actions": {}}]}),
    (PagerDutyCreateRulesetRuleConfig(ruleset_id="abc123", rule='{"conditions": {"operator": "and", "subconditions": [{"operator": "contains", "parameters": {"path": "payload.summary", "value": "disk"}}]}, "actions": {"route": {"value": "PXYZ123"}, "severity": {"value": "warning"}}}'), "create_ruleset_rule", {"rule": {"id": "aa11bb22", "disabled": False, "actions": {"route": {"value": "PXYZ123"}}}}),
    (PagerDutyGetRulesetRuleConfig(ruleset_id="abc123", rule_id="9b5dcb28"), "get_ruleset_rule", {"rule": {"id": "9b5dcb28", "disabled": False, "conditions": {"operator": "and", "subconditions": []}, "actions": {}}}),
    (PagerDutyUpdateRulesetRuleConfig(ruleset_id="abc123", rule_id="9b5dcb28", rule='{"disabled": true, "conditions": {"operator": "and", "subconditions": []}, "actions": {"suppress": {"value": true}}}'), "update_ruleset_rule", {"rule": {"id": "9b5dcb28", "disabled": True, "actions": {"suppress": {"value": True}}}}),
    (PagerDutyDeleteRulesetRuleConfig(ruleset_id="abc123", rule_id="9b5dcb28"), "delete_ruleset_rule", {"success": True}),
    # response-automation-workflows
    (PagerDutyListResponsePlaysConfig(query="Major Incident"), "list_response_plays", {"response_plays": [{"id": "PXYZ123", "type": "response_play", "name": "Major Incident"}]}),
    (PagerDutyGetResponsePlayConfig(response_play_id="PXYZ123"), "get_response_play", {"response_play": {"id": "PXYZ123", "type": "response_play", "name": "Major Incident"}}),
    (PagerDutyCreateResponsePlayConfig(name="Sev1 Play", description="Page leadership", additional_fields_json='{"conference_number": "+1-555-0100"}'), "create_response_play", {"response_play": {"id": "PNEW001", "type": "response_play", "name": "Sev1 Play"}}),
    (PagerDutyUpdateResponsePlayConfig(response_play_id="PXYZ123", name="Sev1 Play v2"), "update_response_play", {"response_play": {"id": "PXYZ123", "type": "response_play", "name": "Sev1 Play v2"}}),
    (PagerDutyDeleteResponsePlayConfig(response_play_id="PXYZ123"), "delete_response_play", {"success": True}),
    (PagerDutyRunResponsePlayConfig(response_play_id="PXYZ123", incident_id="PINC456"), "run_response_play", {"status": "ok"}),
    (PagerDutyListAutomationActionsConfig(query="restart", limit="25"), "list_automation_actions", {"actions": [{"id": "01ABC", "name": "Restart Service", "action_type": "process_automation"}]}),
    (PagerDutyGetAutomationActionConfig(action_id="01ABC"), "get_automation_action", {"action": {"id": "01ABC", "name": "Restart Service", "action_type": "process_automation"}}),
    (PagerDutyCreateAutomationActionConfig(name="Restart Service", action_type="process_automation", runner_id="01RUNNER", action_data_json='{"process_automation_job_id": "job-123"}', only_invocable_on_unresolved_incidents="true"), "create_automation_action", {"action": {"id": "01NEW", "name": "Restart Service", "action_type": "process_automation"}}),
    (PagerDutyUpdateAutomationActionConfig(action_id="01ABC", name="Restart Service v2", description="Updated"), "update_automation_action", {"action": {"id": "01ABC", "name": "Restart Service v2"}}),
    (PagerDutyDeleteAutomationActionConfig(action_id="01ABC"), "delete_automation_action", {"success": True}),
    (PagerDutyInvokeAutomationActionConfig(action_id="01ABC", incident_id="PINC456", inputs_json='[{"name": "region", "value": "us-east-1"}]'), "invoke_automation_action", {"invocation": {"id": "01INVOKE", "state": "created"}}),
    (PagerDutyListInvocationsConfig(action_id="01ABC"), "list_invocations", {"invocations": [{"id": "01INVOKE", "state": "completed"}]}),
    (PagerDutyGetInvocationConfig(invocation_id="01INVOKE"), "get_invocation", {"invocation": {"id": "01INVOKE", "state": "completed"}}),
    (PagerDutyListRunnersConfig(query="prod"), "list_runners", {"runners": [{"id": "01RUNNER", "name": "prod-runner", "runner_type": "runbook"}]}),
    (PagerDutyGetRunnerConfig(runner_id="01RUNNER"), "get_runner", {"runner": {"id": "01RUNNER", "name": "prod-runner", "runner_type": "runbook"}}),
    (PagerDutyCreateRunnerConfig(name="prod-runner", runner_type="runbook", runbook_base_uri="https://rundeck.example.com", runbook_api_key="secret-key", description="Prod runbook runner"), "create_runner", {"runner": {"id": "01NEWRUN", "name": "prod-runner", "runner_type": "runbook"}}),
    (PagerDutyUpdateRunnerConfig(runner_id="01RUNNER", name="prod-runner-2", additional_fields_json='{"runbook_base_uri": "https://rundeck2.example.com"}'), "update_runner", {"runner": {"id": "01RUNNER", "name": "prod-runner-2"}}),
    (PagerDutyDeleteRunnerConfig(runner_id="01RUNNER"), "delete_runner", {"success": True}),
    (PagerDutyListIncidentWorkflowsConfig(query="Escalate"), "list_incident_workflows", {"incident_workflows": [{"id": "PIW001", "type": "incident_workflow", "name": "Escalate to Eng"}]}),
    (PagerDutyGetIncidentWorkflowConfig(incident_workflow_id="PIW001"), "get_incident_workflow", {"incident_workflow": {"id": "PIW001", "type": "incident_workflow", "name": "Escalate to Eng"}}),
    (PagerDutyCreateIncidentWorkflowConfig(name="Escalate to Eng", description="Auto-escalate", steps_json='[{"name": "Notify", "action": "pagerduty.com:incident-workflows:send-status-update:1"}]'), "create_incident_workflow", {"incident_workflow": {"id": "PIWNEW", "type": "incident_workflow", "name": "Escalate to Eng"}}),
    (PagerDutyUpdateIncidentWorkflowConfig(incident_workflow_id="PIW001", name="Escalate to Eng v2"), "update_incident_workflow", {"incident_workflow": {"id": "PIW001", "type": "incident_workflow", "name": "Escalate to Eng v2"}}),
    (PagerDutyDeleteIncidentWorkflowConfig(incident_workflow_id="PIW001"), "delete_incident_workflow", {"success": True}),
    (PagerDutyStartIncidentWorkflowConfig(incident_workflow_id="PIW001", incident_id="PINC456"), "start_incident_workflow", {"incident_workflow_instance": {"id": "PIWI001", "status": "in_progress"}}),
    (PagerDutyListIncidentWorkflowTriggersConfig(workflow_name_contains="Escalate"), "list_incident_workflow_triggers", {"triggers": [{"id": "PTRIG01", "trigger_type": "manual"}]}),
    (PagerDutyGetIncidentWorkflowTriggerConfig(trigger_id="PTRIG01"), "get_incident_workflow_trigger", {"trigger": {"id": "PTRIG01", "trigger_type": "manual"}}),
    (PagerDutyCreateIncidentWorkflowTriggerConfig(incident_workflow_id="PIW001", trigger_type="conditional", condition="incident.priority matches 'P1'", subscribed_to_all_services="false", service_ids="PSVC1,PSVC2"), "create_incident_workflow_trigger", {"trigger": {"id": "PTRIGNEW", "trigger_type": "conditional"}}),
    (PagerDutyUpdateIncidentWorkflowTriggerConfig(trigger_id="PTRIG01", condition="incident.priority matches 'P2'", subscribed_to_all_services="true"), "update_incident_workflow_trigger", {"trigger": {"id": "PTRIG01", "trigger_type": "conditional"}}),
    (PagerDutyDeleteIncidentWorkflowTriggerConfig(trigger_id="PTRIG01"), "delete_incident_workflow_trigger", {"success": True}),
    (PagerDutyAssociateTriggerServiceConfig(trigger_id="PTRIG01", service_id="PSVC1"), "associate_trigger_service", {"service": {"id": "PSVC1", "type": "service_reference"}}),
    (PagerDutyDisassociateTriggerServiceConfig(trigger_id="PTRIG01", service_id="PSVC1"), "disassociate_trigger_service", {"success": True}),
    # business-status
    (PagerDutyListBusinessServicesConfig(limit="25"), "list_business_services", {"business_services": [{"id": "PBS123", "type": "business_service", "name": "Checkout"}]}),
    (PagerDutyGetBusinessServiceConfig(business_service_id="PBS123"), "get_business_service", {"business_service": {"id": "PBS123", "type": "business_service", "name": "Checkout"}}),
    (PagerDutyCreateBusinessServiceConfig(name="Checkout", description="Payments flow", point_of_contact="Ops", team_id="PTEAM1"), "create_business_service", {"business_service": {"id": "PBS123", "type": "business_service", "name": "Checkout"}}),
    (PagerDutyUpdateBusinessServiceConfig(business_service_id="PBS123", name="Checkout v2"), "update_business_service", {"business_service": {"id": "PBS123", "type": "business_service", "name": "Checkout v2"}}),
    (PagerDutyDeleteBusinessServiceConfig(business_service_id="PBS123"), "delete_business_service", {"success": True}),
    (PagerDutyListBusinessServiceSubscribersConfig(business_service_id="PBS123"), "list_business_service_subscribers", {"subscribers": [{"subscriber_id": "PUSR1", "subscriber_type": "user"}]}),
    (PagerDutyCreateBusinessServiceSubscribersConfig(business_service_id="PBS123", subscriber_ids="PUSR1,PUSR2", subscriber_type="user"), "create_business_service_subscribers", {"subscribers": [{"subscriber_id": "PUSR1", "subscriber_type": "user"}]}),
    (PagerDutyRemoveBusinessServiceSubscribersConfig(business_service_id="PBS123", subscriber_ids="PUSR1", subscriber_type="user"), "remove_business_service_subscribers", {"deleted_count": 1}),
    (PagerDutyListBusinessServiceImpactsConfig(ids="PBS123", additional_fields="business_service.priority"), "list_business_service_impacts", {"services": [{"id": "PBS123", "impacted": True}]}),
    (PagerDutyListBusinessServiceImpactorsConfig(ids="PBS123"), "list_business_service_impactors", {"services": [{"id": "PSVC1", "type": "service"}]}),
    (PagerDutyGetPriorityThresholdsConfig(), "get_priority_thresholds", {"global_threshold": {"id": "PPRI1", "order": 1}}),
    (PagerDutySetPriorityThresholdConfig(priority_id="PPRI1", order="1"), "set_priority_threshold", {"global_threshold": {"id": "PPRI1", "order": 1}}),
    (PagerDutyDeletePriorityThresholdsConfig(), "delete_priority_thresholds", {"success": True}),
    (PagerDutyListStatusDashboardsConfig(), "list_status_dashboards", {"status_dashboards": [{"id": "PDASH1", "name": "Prod"}]}),
    (PagerDutyGetStatusDashboardConfig(status_dashboard_id="PDASH1"), "get_status_dashboard", {"status_dashboard": {"id": "PDASH1", "name": "Prod"}}),
    (PagerDutyGetStatusDashboardBySlugConfig(url_slug="prod"), "get_status_dashboard_by_slug", {"status_dashboard": {"id": "PDASH1", "url_slug": "prod"}}),
    (PagerDutyGetStatusDashboardServiceImpactsConfig(status_dashboard_id="PDASH1"), "get_status_dashboard_service_impacts", {"services": [{"id": "PSVC1", "impact": "none"}]}),
    (PagerDutyListStatusPagesConfig(status_page_type="public"), "list_status_pages", {"status_pages": [{"id": "PSPAGE1", "name": "Public Status"}]}),
    (PagerDutyListStatusPagePostsConfig(status_page_id="PSPAGE1", post_type="incident"), "list_status_page_posts", {"posts": [{"id": "PPOST1"}]}),
    (PagerDutyCreateStatusPagePostConfig(status_page_id="PSPAGE1", title="Degraded checkout", post_type="incident", starts_at="2026-07-01T00:00:00Z", ends_at="2026-07-01T02:00:00Z", updates='[{"message": "Investigating"}]'), "create_status_page_post", {"post": {"id": "PPOST1", "title": "Degraded checkout"}}),
    (PagerDutyGetStatusPagePostConfig(status_page_id="PSPAGE1", post_id="PPOST1"), "get_status_page_post", {"post": {"id": "PPOST1"}}),
    (PagerDutyUpdateStatusPagePostConfig(status_page_id="PSPAGE1", post_id="PPOST1", title="Resolved checkout", post_type="incident", starts_at="2026-07-01T00:00:00Z", ends_at="2026-07-01T02:00:00Z"), "update_status_page_post", {"post": {"id": "PPOST1", "title": "Resolved checkout"}}),
    (PagerDutyDeleteStatusPagePostConfig(status_page_id="PSPAGE1", post_id="PPOST1"), "delete_status_page_post", {"success": True}),
    (PagerDutyListStatusPagePostUpdatesConfig(status_page_id="PSPAGE1", post_id="PPOST1"), "list_status_page_post_updates", {"post_updates": [{"id": "PPU1"}]}),
    (PagerDutyCreateStatusPagePostUpdateConfig(status_page_id="PSPAGE1", post_id="PPOST1", post_update='{"message": "Update", "notify_subscribers": true}'), "create_status_page_post_update", {"post_update": {"id": "PPU1"}}),
    (PagerDutyGetStatusPagePostUpdateConfig(status_page_id="PSPAGE1", post_id="PPOST1", post_update_id="PPU1"), "get_status_page_post_update", {"post_update": {"id": "PPU1"}}),
    (PagerDutyUpdateStatusPagePostUpdateConfig(status_page_id="PSPAGE1", post_id="PPOST1", post_update_id="PPU1", post_update='{"message": "Revised update"}'), "update_status_page_post_update", {"post_update": {"id": "PPU1"}}),
    (PagerDutyDeleteStatusPagePostUpdateConfig(status_page_id="PSPAGE1", post_id="PPOST1", post_update_id="PPU1"), "delete_status_page_post_update", {"success": True}),
    (PagerDutyListStatusPageSubscriptionsConfig(status_page_id="PSPAGE1", channel="email"), "list_status_page_subscriptions", {"subscriptions": [{"id": "PSUB1"}]}),
    (PagerDutyCreateStatusPageSubscriptionConfig(status_page_id="PSPAGE1", channel="email", contact="ops@example.com", subscribable_object_id="PSPAGE1", subscribable_object_type="status_page"), "create_status_page_subscription", {"subscription": {"id": "PSUB1"}}),
    (PagerDutyGetStatusPageSubscriptionConfig(status_page_id="PSPAGE1", subscription_id="PSUB1"), "get_status_page_subscription", {"subscription": {"id": "PSUB1"}}),
    (PagerDutyDeleteStatusPageSubscriptionConfig(status_page_id="PSPAGE1", subscription_id="PSUB1"), "delete_status_page_subscription", {"success": True}),
    # analytics-audit-changes
    (
        PagerDutyIncidentMetricsConfig(
            filters='{"created_at_start":"2026-06-01T00:00:00Z","created_at_end":"2026-06-30T00:00:00Z","service_ids":["PSVC123"]}',
            aggregate_unit="day",
            time_zone="Etc/UTC",
        ),
        "analytics_incident_metrics",
        {"data": [{"total_incident_count": 12, "mean_seconds_to_resolve": 3600, "mean_seconds_to_first_ack": 120}], "aggregate_unit": "day", "time_zone": "Etc/UTC"},
    ),
    (
        PagerDutyIncidentMetricsByDimensionConfig(
            dimension="services",
            aggregate_all="false",
            filters='{"created_at_start":"2026-06-01T00:00:00Z","created_at_end":"2026-06-30T00:00:00Z"}',
        ),
        "analytics_incident_metrics_by_dimension",
        {"data": [{"service_id": "PSVC123", "service_name": "Payments", "total_incident_count": 5, "mean_seconds_to_resolve": 4200}]},
    ),
    (
        PagerDutyRawIncidentsConfig(
            filters='{"created_at_start":"2026-06-01T00:00:00Z","created_at_end":"2026-06-30T00:00:00Z"}',
            order="desc",
            order_by="created_at",
            limit="50",
        ),
        "analytics_raw_incidents",
        {"data": [{"id": "PABCDEF", "incident_number": 101, "seconds_to_resolve": 3300, "urgency": "high"}], "more": False, "limit": 50, "order": "desc", "order_by": "created_at"},
    ),
    (
        PagerDutyGetRawIncidentConfig(incident_id="PABCDEF"),
        "get_raw_incident",
        {"id": "PABCDEF", "incident_number": 101, "description": "Database CPU high", "seconds_to_resolve": 3300, "urgency": "high"},
    ),
    (
        PagerDutyRawIncidentResponsesConfig(incident_id="PABCDEF"),
        "get_raw_incident_responses",
        {"responses": [{"id": "PRESP1", "responder_name": "Jane Doe", "response_status": "accepted", "time_to_respond_seconds": 45}]},
    ),
    (
        PagerDutyResponderMetricsConfig(
            group_by="teams",
            filters='{"date_range_start":"2026-06-01T00:00:00Z","date_range_end":"2026-06-30T00:00:00Z","team_ids":["PTEAM1"]}',
        ),
        "analytics_responder_metrics",
        {"data": [{"team_id": "PTEAM1", "team_name": "SRE", "total_engaged_seconds": 7200, "total_incident_count": 8}]},
    ),
    (
        PagerDutyListAuditRecordsConfig(
            since="2026-06-01T00:00:00Z",
            until="2026-06-30T00:00:00Z",
            limit="50",
            root_resource_types="services,teams",
            actions="create,update",
        ),
        "list_audit_records",
        {"response": [{"id": "REC1", "action": "create", "execution_time": "2026-06-15T10:00:00Z", "root_resource": {"type": "service_reference", "id": "PSVC123"}}], "pagination": {"limit": 50, "next_cursor": None}},
    ),
    (
        PagerDutySendChangeEventConfig(
            routing_key="R0ABCDEFGHIJKLMNOPQRSTUV12345678",
            summary="Deployed api v1.2.3 to production",
            source="deploy-pipeline",
            custom_details='{"build":"1.2.3","env":"prod"}',
        ),
        "send_change_event",
        {"status": "Change event processed", "message": "Change event processed"},
    ),
    (
        PagerDutyListChangeEventsConfig(team_ids="PTEAM1", limit="25", since="2026-06-01T00:00:00Z"),
        "list_change_events",
        {"change_events": [{"id": "CE1", "summary": "Deploy v1.2.3", "source": "deploy-pipeline", "timestamp": "2026-06-15T10:00:00Z"}], "limit": 25, "more": False},
    ),
    (
        PagerDutyListServiceChangeEventsConfig(service_id="PSVC123", limit="25"),
        "list_service_change_events",
        {"change_events": [{"id": "CE2", "summary": "Config update", "timestamp": "2026-06-16T09:00:00Z"}], "limit": 25, "more": False},
    ),
    # reference-misc
    (PagerDutyListCustomFieldsConfig(), "list_custom_fields", {"custom_fields": [{"id": "PF1", "name": "level_of_effort", "display_name": "Level of Effort", "data_type": "string", "field_type": "single_value_fixed"}]}),
    (PagerDutyCreateCustomFieldConfig(name="level_of_effort", display_name="Level of Effort", data_type="string", field_type="single_value_fixed", description="Effort estimate", enabled="true"), "create_custom_field", {"field": {"id": "PF1", "name": "level_of_effort", "display_name": "Level of Effort", "data_type": "string", "field_type": "single_value_fixed"}}),
    (PagerDutyGetCustomFieldConfig(field_id="PF1"), "get_custom_field", {"field": {"id": "PF1", "name": "level_of_effort", "display_name": "Level of Effort"}}),
    (PagerDutyUpdateCustomFieldConfig(field_id="PF1", display_name="Effort", description="Updated", enabled="false"), "update_custom_field", {"field": {"id": "PF1", "display_name": "Effort", "enabled": False}}),
    (PagerDutyDeleteCustomFieldConfig(field_id="PF1"), "delete_custom_field", {"success": True}),
    (PagerDutyListFieldOptionsConfig(field_id="PF1"), "list_field_options", {"field_options": [{"id": "FO1", "data": {"data_type": "string", "value": "Low"}}]}),
    (PagerDutyCreateFieldOptionConfig(field_id="PF1", value="Low"), "create_field_option", {"field_option": {"id": "FO1", "data": {"data_type": "string", "value": "Low"}}}),
    (PagerDutyGetFieldOptionConfig(field_id="PF1", field_option_id="FO1"), "get_field_option", {"field_option": {"id": "FO1", "data": {"data_type": "string", "value": "Low"}}}),
    (PagerDutyUpdateFieldOptionConfig(field_id="PF1", field_option_id="FO1", value="High"), "update_field_option", {"field_option": {"id": "FO1", "data": {"data_type": "string", "value": "High"}}}),
    (PagerDutyDeleteFieldOptionConfig(field_id="PF1", field_option_id="FO1"), "delete_field_option", {"success": True}),
    (PagerDutyListTemplatesConfig(template_type="status_update"), "list_templates", {"templates": [{"id": "PT1", "name": "Outage Update", "template_type": "status_update"}]}),
    (PagerDutyCreateTemplateConfig(name="Outage Update", template_type="status_update", description="Standard outage comms", templated_fields='{"subject": "Update on {{incident.title}}", "body": "We are investigating."}'), "create_template", {"template": {"id": "PT1", "name": "Outage Update", "template_type": "status_update"}}),
    (PagerDutyGetTemplateConfig(template_id="PT1"), "get_template", {"template": {"id": "PT1", "name": "Outage Update", "template_type": "status_update"}}),
    (PagerDutyUpdateTemplateConfig(template_id="PT1", name="Outage Update v2", templated_fields='{"subject": "Update", "body": "Resolved."}'), "update_template", {"template": {"id": "PT1", "name": "Outage Update v2"}}),
    (PagerDutyDeleteTemplateConfig(template_id="PT1"), "delete_template", {"success": True}),
    (PagerDutyRenderTemplateConfig(template_id="PT1", incident_id="PINC123", message="We are on it."), "render_template", {"rendered_content": {"subject": "Update on Outage", "body": "We are on it."}}),
    (PagerDutyListTagsConfig(query="prod", limit="25"), "list_tags", {"tags": [{"id": "TAG1", "type": "tag", "label": "production"}]}),
    (PagerDutyCreateTagConfig(label="production"), "create_tag", {"tag": {"id": "TAG1", "type": "tag", "label": "production"}}),
    (PagerDutyGetTagConfig(tag_id="TAG1"), "get_tag", {"tag": {"id": "TAG1", "type": "tag", "label": "production"}}),
    (PagerDutyDeleteTagConfig(tag_id="TAG1"), "delete_tag", {"success": True}),
    (PagerDutyGetTagsForEntityConfig(entity_type="users", entity_id="PUSER1"), "get_tags_for_entity", {"tags": [{"id": "TAG1", "type": "tag", "label": "production"}]}),
    (PagerDutyChangeTagsConfig(entity_type="users", entity_id="PUSER1", add_tag_ids="TAG1,TAG2", add_tag_labels="oncall", remove_tag_ids="TAG3"), "change_tags", {"success": True}),
    (PagerDutyListVendorsConfig(limit="25"), "list_vendors", {"vendors": [{"id": "PV1", "name": "Amazon CloudWatch"}]}),
    (PagerDutyGetVendorConfig(vendor_id="PV1"), "get_vendor", {"vendor": {"id": "PV1", "name": "Amazon CloudWatch"}}),
    (PagerDutyListAddonsConfig(filter="full_page_addon"), "list_addons", {"addons": [{"id": "PA1", "type": "full_page_addon", "name": "Status Page", "src": "https://status.example.com"}]}),
    (PagerDutyCreateAddonConfig(addon_type="incident_show_addon", name="Runbook", src="https://runbook.example.com", service_ids="PSVC1,PSVC2"), "create_addon", {"addon": {"id": "PA1", "type": "incident_show_addon", "name": "Runbook", "src": "https://runbook.example.com"}}),
    (PagerDutyGetAddonConfig(addon_id="PA1"), "get_addon", {"addon": {"id": "PA1", "type": "full_page_addon", "name": "Status Page", "src": "https://status.example.com"}}),
    (PagerDutyUpdateAddonConfig(addon_id="PA1", addon_type="full_page_addon", name="Status Page v2", src="https://status.example.com/v2"), "update_addon", {"addon": {"id": "PA1", "type": "full_page_addon", "name": "Status Page v2", "src": "https://status.example.com/v2"}}),
    (PagerDutyDeleteAddonConfig(addon_id="PA1"), "delete_addon", {"success": True}),
    (PagerDutyListAbilitiesConfig(), "list_abilities", {"abilities": ["sso", "teams", "advanced_reports"]}),
    (PagerDutyTestAbilityConfig(ability_id="sso"), "test_ability", {"success": True}),
    (PagerDutyListNotificationsConfig(since="2026-06-01T00:00:00Z", until="2026-06-30T23:59:59Z", filter="sms_notification", limit="25"), "list_notifications", {"notifications": [{"id": "PN1", "type": "sms_notification", "address": "+15555550123"}]}),
    (PagerDutyListLicensesConfig(), "list_licenses", {"licenses": [{"id": "PL1", "name": "Full User", "summary": "Full User"}]}),
    (PagerDutyListLicenseAllocationsConfig(limit="25"), "list_license_allocations", {"license_allocations": [{"user": {"id": "PUSER1"}, "license": {"id": "PL1"}}]}),
    (PagerDutyPausedIncidentReportAlertsConfig(since="2026-06-01T00:00:00Z", until="2026-06-30T23:59:59Z", service_id="PSVC1", suspended_by="auto_pause"), "paused_incident_report_alerts", {"paused_incident_reporting_counts": [{"total": 12}]}),
    (PagerDutyPausedIncidentReportCountsConfig(since="2026-06-01T00:00:00Z", until="2026-06-30T23:59:59Z", suspended_by="rules"), "paused_incident_report_counts", {"paused_incident_reporting_counts": [{"total": 42}]}),
]


@pytest.mark.parametrize("cfg,action,payload", _PD_COVERAGE_PARAMS)
@pytest.mark.asyncio
async def test_expanded_operation(api_key_credentials, cfg, action, payload):
    node = create_pagerduty_node(PagerDutyNodeConfig(config=cfg, credentials=api_key_credentials))
    result = await _run(node, 200, payload)
    assert result["status"] == "success", result
    assert result["action"] == action
