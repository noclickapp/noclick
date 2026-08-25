"""
Mock tests for the Datadog REST API node.

Exercises every operation with mocked HTTP responses (no live API calls):
- Monitors: create, get, list, update, delete, mute, unmute, search
- Events: post, get, list, search
- Metrics: submit, query timeseries, query (legacy), list active, get metadata
- Logs: send, search, aggregate
- Dashboards: create, get, list, update, delete
- Incidents: create, list, update
- Downtimes: create, cancel
- Error handling: API errors, missing credentials
- Dynamic options: monitor + dashboard dropdowns
"""

import pytest
from unittest.mock import AsyncMock, Mock, patch

from nodes.datadog_node import (
    DatadogNode,
    DatadogNodeConfig,
    DatadogApiKeyCredential,
    DatadogCreateMonitorConfig,
    DatadogGetMonitorConfig,
    DatadogListMonitorsConfig,
    DatadogUpdateMonitorConfig,
    DatadogDeleteMonitorConfig,
    DatadogMuteMonitorConfig,
    DatadogUnmuteMonitorConfig,
    DatadogSearchMonitorsConfig,
    DatadogPostEventConfig,
    DatadogGetEventConfig,
    DatadogListEventsConfig,
    DatadogSearchEventsConfig,
    DatadogOnNewEventConfig,
    DatadogSubmitMetricsConfig,
    DatadogQueryTimeseriesConfig,
    DatadogQueryMetricsConfig,
    DatadogListMetricsConfig,
    DatadogGetMetricMetadataConfig,
    DatadogSendLogsConfig,
    DatadogSearchLogsConfig,
    DatadogAggregateLogsConfig,
    DatadogCreateDashboardConfig,
    DatadogGetDashboardConfig,
    DatadogListDashboardsConfig,
    DatadogUpdateDashboardConfig,
    DatadogDeleteDashboardConfig,
    DatadogCreateIncidentConfig,
    DatadogListIncidentsConfig,
    DatadogUpdateIncidentConfig,
    DatadogCreateDowntimeConfig,
    DatadogCancelDowntimeConfig,
)


@pytest.fixture
def credentials():
    return DatadogApiKeyCredential(
        api_key="dd_api_test_key", app_key="dd_app_test_key", site="datadoghq.com"
    )


def create_datadog_node(config):
    return DatadogNode(
        node_id="test-datadog-node",
        node_type="automation-datadog",
        node_data={},
        config=config,
        sio=Mock(),
        sid="test-sid",
        workflow_id="test-workflow",
        user_id="test-user",
    )


def create_mock_response(status_code=200, json_data=None, text="{}"):
    mock_response = Mock()
    mock_response.status_code = status_code
    mock_response.text = text
    mock_response.json = lambda: (json_data if json_data is not None else {})
    return mock_response


def _bind_state(node, prior_state=None):
    """Route the poll node's CAS state primitive through an in-memory dict.

    `on_new_event` now dedups via `_update_node_state(mutator, skip_result=...)`
    plus a top-level `_load_node_state()` to size the query window. Both are
    stubbed here to read the injected `prior_state`; the mutator's persisted
    state (if any) is captured into the returned `saved` dict — which stays
    empty when the mutator persists nothing (new_state is None).
    """
    state = dict(prior_state or {})
    saved: dict = {}

    async def fake_load():
        return dict(state)

    async def fake_update(mutator, *, max_retries=4, skip_result=None):
        new_state, result = mutator(dict(state))
        if new_state is not None:
            saved.clear()
            saved.update(new_state)
        return result

    node._load_node_state = fake_load
    node._update_node_state = fake_update
    return saved


def create_mock_client(status_code=200, json_data=None, text="{}"):
    """Mock httpx.AsyncClient whose .request() returns the mock response and
    which works as an async context manager."""
    mock_response = create_mock_response(status_code, json_data, text)
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


# ============================================================================
# Monitors
# ============================================================================


class TestDatadogMonitorsMock:
    @pytest.mark.asyncio
    async def test_create_monitor(self, credentials):
        config = DatadogNodeConfig(
            config=DatadogCreateMonitorConfig(
                name="High CPU",
                type="metric alert",
                query="avg(last_5m):avg:system.cpu.user{*} > 80",
                message="CPU is high",
                tags="env:prod",
            ),
            credentials=credentials,
        )
        node = create_datadog_node(config)
        mock_client = create_mock_client(200, {"id": 123, "name": "High CPU"})
        with patch("nodes.datadog_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_monitor"
        assert result["data"]["id"] == 123

    @pytest.mark.asyncio
    async def test_get_monitor(self, credentials):
        config = DatadogNodeConfig(
            config=DatadogGetMonitorConfig(monitor_id="123"), credentials=credentials
        )
        node = create_datadog_node(config)
        mock_client = create_mock_client(200, {"id": 123, "name": "High CPU"})
        with patch("nodes.datadog_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_monitor"
        assert result["data"]["id"] == 123

    @pytest.mark.asyncio
    async def test_list_monitors(self, credentials):
        config = DatadogNodeConfig(
            config=DatadogListMonitorsConfig(tags="env:prod", page_size="10"),
            credentials=credentials,
        )
        node = create_datadog_node(config)
        mock_client = create_mock_client(200, [{"id": 1}, {"id": 2}])
        with patch("nodes.datadog_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_monitors"
        assert len(result["data"]) == 2

    @pytest.mark.asyncio
    async def test_list_monitors_all_commas_tags_no_crash(self, credentials):
        """Tags field with only commas must not crash with TypeError on join."""
        config = DatadogNodeConfig(
            config=DatadogListMonitorsConfig(tags=",,,", page_size="10"),
            credentials=credentials,
        )
        node = create_datadog_node(config)
        mock_client = create_mock_client(200, [])
        with patch("nodes.datadog_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_update_monitor(self, credentials):
        config = DatadogNodeConfig(
            config=DatadogUpdateMonitorConfig(monitor_id="123", name="Renamed"),
            credentials=credentials,
        )
        node = create_datadog_node(config)
        mock_client = create_mock_client(200, {"id": 123, "name": "Renamed"})
        with patch("nodes.datadog_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_monitor"
        assert result["data"]["name"] == "Renamed"

    @pytest.mark.asyncio
    async def test_delete_monitor(self, credentials):
        config = DatadogNodeConfig(
            config=DatadogDeleteMonitorConfig(monitor_id="123"), credentials=credentials
        )
        node = create_datadog_node(config)
        mock_client = create_mock_client(200, {"deleted_monitor_id": 123})
        with patch("nodes.datadog_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_monitor"

    @pytest.mark.asyncio
    async def test_mute_monitor(self, credentials):
        config = DatadogNodeConfig(
            config=DatadogMuteMonitorConfig(monitor_id="123", scope="host:web1"),
            credentials=credentials,
        )
        node = create_datadog_node(config)
        mock_client = create_mock_client(200, {"id": 123, "options": {"silenced": {}}})
        with patch("nodes.datadog_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "mute_monitor"

    @pytest.mark.asyncio
    async def test_unmute_monitor(self, credentials):
        config = DatadogNodeConfig(
            config=DatadogUnmuteMonitorConfig(monitor_id="123"), credentials=credentials
        )
        node = create_datadog_node(config)
        mock_client = create_mock_client(200, {"id": 123})
        with patch("nodes.datadog_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "unmute_monitor"

    @pytest.mark.asyncio
    async def test_search_monitors(self, credentials):
        config = DatadogNodeConfig(
            config=DatadogSearchMonitorsConfig(query="type:metric"),
            credentials=credentials,
        )
        node = create_datadog_node(config)
        mock_client = create_mock_client(200, {"monitors": [{"id": 1}]})
        with patch("nodes.datadog_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "search_monitors"
        assert result["data"]["monitors"][0]["id"] == 1


# ============================================================================
# Events
# ============================================================================


class TestDatadogEventsMock:
    @pytest.mark.asyncio
    async def test_post_event(self, credentials):
        config = DatadogNodeConfig(
            config=DatadogPostEventConfig(
                title="Deploy", text="Deployed v2", tags="service:api"
            ),
            credentials=credentials,
        )
        node = create_datadog_node(config)
        mock_client = create_mock_client(
            202, {"data": {"id": "evt_1", "type": "event"}}
        )
        with patch("nodes.datadog_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "post_event"
        assert result["data"]["data"]["id"] == "evt_1"

    @pytest.mark.asyncio
    async def test_get_event(self, credentials):
        config = DatadogNodeConfig(
            config=DatadogGetEventConfig(event_id="12345"), credentials=credentials
        )
        node = create_datadog_node(config)
        captured = {}

        async def fake_request(*args, **kwargs):
            captured["url"] = args[1] if len(args) > 1 else kwargs.get("url", "")
            mock_resp = Mock()
            mock_resp.status_code = 200
            mock_resp.text = '{"event": {"id": 12345}}'
            mock_resp.json = lambda: {"event": {"id": 12345}}
            return mock_resp

        mock_client = Mock()
        mock_client.request = fake_request
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("nodes.datadog_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_event"
        # Must use v1 endpoint — v1 integer IDs are not in the v2 UUID namespace
        assert "/api/v1/events/12345" in captured["url"], (
            f"get_event must use v1 endpoint to match post_event IDs, got: {captured['url']}"
        )

    @pytest.mark.asyncio
    async def test_list_events(self, credentials):
        config = DatadogNodeConfig(
            config=DatadogListEventsConfig(filter_from="now-1h", filter_to="now"),
            credentials=credentials,
        )
        node = create_datadog_node(config)
        mock_client = create_mock_client(200, {"data": [{"id": "evt_1"}]})
        with patch("nodes.datadog_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_events"
        assert len(result["data"]["data"]) == 1

    @pytest.mark.asyncio
    async def test_search_events(self, credentials):
        config = DatadogNodeConfig(
            config=DatadogSearchEventsConfig(query="status:error"),
            credentials=credentials,
        )
        node = create_datadog_node(config)
        mock_client = create_mock_client(200, {"data": [{"id": "evt_1"}]})
        with patch("nodes.datadog_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "search_events"


# ============================================================================
# Trigger (poll-based on_new_event)
# ============================================================================


class TestDatadogTriggerMock:
    def test_resolve_trigger_payload_poll_returns_none(self):
        """The poll op returns None so execute() runs and actually polls."""
        result = DatadogNode.resolve_trigger_payload(
            {"some": "payload"}, {"operation": "on_new_event"}
        )
        assert result is None

    def test_resolve_trigger_payload_passthrough_for_normal_op(self):
        """Non-trigger ops keep the default passthrough behaviour."""
        payload = {"some": "payload"}
        result = DatadogNode.resolve_trigger_payload(
            payload, {"operation": "list_events"}
        )
        assert result == payload

    @pytest.mark.asyncio
    async def test_poll_first_run_baselines_and_emits_nothing(self, credentials):
        """First poll (no cursor) records the newest id and emits no events."""
        config = DatadogNodeConfig(
            config=DatadogOnNewEventConfig(query="status:error"),
            credentials=credentials,
        )
        node = create_datadog_node(config)
        events_payload = {
            "data": [
                {"id": "evt_3", "type": "event", "attributes": {"title": "C"}},
                {"id": "evt_2", "type": "event", "attributes": {"title": "B"}},
                {"id": "evt_1", "type": "event", "attributes": {"title": "A"}},
            ]
        }
        mock_client = create_mock_client(200, events_payload)
        saved = _bind_state(node)
        with patch("nodes.datadog_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["operation"] == "on_new_event"
        assert result["events"] == []
        assert result["new_count"] == 0
        # Baseline cursor recorded at the newest event.
        assert saved["last_seen_id"] == "evt_3"
        # No new event => downstream skipped.
        assert node.trigger_produced_no_event(result) is True

    @pytest.mark.asyncio
    async def test_poll_emits_only_new_events_after_cursor(self, credentials):
        """A subsequent poll emits only events newer than the saved cursor and
        advances the cursor, deduping already-seen events."""
        config = DatadogNodeConfig(
            config=DatadogOnNewEventConfig(query="status:error"),
            credentials=credentials,
        )
        node = create_datadog_node(config)
        # Newest-first: evt_5 and evt_4 are new; evt_3 was already seen.
        events_payload = {
            "data": [
                {"id": "evt_5", "type": "event", "attributes": {"title": "E"}},
                {"id": "evt_4", "type": "event", "attributes": {"title": "D"}},
                {"id": "evt_3", "type": "event", "attributes": {"title": "C"}},
                {"id": "evt_2", "type": "event", "attributes": {"title": "B"}},
            ]
        }
        mock_client = create_mock_client(200, events_payload)
        saved = _bind_state(node, {"last_seen_id": "evt_3"})
        with patch("nodes.datadog_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["new_count"] == 2
        emitted_ids = [e["id"] for e in result["events"]]
        assert emitted_ids == ["evt_5", "evt_4"]
        # evt_3 (the cursor) and older are NOT re-emitted.
        assert "evt_3" not in emitted_ids
        # Cursor advanced to the newest event.
        assert saved["last_seen_id"] == "evt_5"
        assert node.trigger_produced_no_event(result) is False

    @pytest.mark.asyncio
    async def test_poll_no_new_events_is_idempotent(self, credentials):
        """When the newest event equals the cursor, nothing is emitted and the
        cursor is unchanged (no re-emit of already-seen events)."""
        config = DatadogNodeConfig(
            config=DatadogOnNewEventConfig(),
            credentials=credentials,
        )
        node = create_datadog_node(config)
        events_payload = {
            "data": [
                {"id": "evt_3", "type": "event", "attributes": {"title": "C"}},
                {"id": "evt_2", "type": "event", "attributes": {"title": "B"}},
            ]
        }
        mock_client = create_mock_client(200, events_payload)
        saved = _bind_state(node, {"last_seen_id": "evt_3"})
        with patch("nodes.datadog_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["events"] == []
        assert result["new_count"] == 0
        # Cursor unchanged => mutator persists nothing (no CAS write).
        assert saved == {}
        assert node.trigger_produced_no_event(result) is True

    @pytest.mark.asyncio
    async def test_poll_api_error_passes_through(self, credentials):
        """An API error during the poll is surfaced, not swallowed."""
        config = DatadogNodeConfig(
            config=DatadogOnNewEventConfig(),
            credentials=credentials,
        )
        node = create_datadog_node(config)
        mock_client = create_mock_client(403, {"errors": ["Forbidden"]})
        _bind_state(node)
        with patch("nodes.datadog_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "error"
        assert result["status_code"] == 403

    @pytest.mark.asyncio
    async def test_load_field_value_provisions_webhook_and_schedule(self, credentials):
        """load_field_value('webhook_url') mints the webhook row and converges
        registration through WebhookManager.reconcile_node (family loader),
        returning the operational values."""
        import uuid as uuid_module
        from unittest.mock import MagicMock

        wf_id = uuid_module.uuid4()

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        conn.execute = AsyncMock(return_value="UPDATE 1")
        pool = MagicMock()
        pool.acquire = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=conn),
            __aexit__=AsyncMock(return_value=False),
        ))

        async def load_owner_nodes(p, wf_uuid, include_nodes=True):
            return "owner-1", []

        from utils.webhook_manager import WebhookManager

        with patch(
            "utils.webhook_manager.WebhookManager.get_or_create_webhook",
            new=AsyncMock(
                return_value={
                    "webhook_id": "wh_1",
                    "webhook_url": "https://hook.example/abc",
                }
            ),
        ), patch(
            "utils.webhook_manager._load_workflow_owner_and_nodes", load_owner_nodes,
        ), patch.object(
            WebhookManager, "persist_registration_state", AsyncMock(),
        ), patch.object(
            WebhookManager, "merge_node_config_patch", AsyncMock(),
        ), patch(
            "utils.cron_scheduler_client.is_cron_scheduler_enabled", return_value=True
        ), patch(
            "utils.cron_scheduler_client.create_schedule",
            new=AsyncMock(return_value={"id": "sch_1", "next_run": "2026-01-01T00:00:00Z"}),
        ), patch(
            "utils.cron_scheduler_client.delete_schedules_for_nodes",
            new=AsyncMock(return_value={"deleted": 0}),
        ), patch(
            "utils.async_helpers.spawn",
            side_effect=lambda coro, name=None: coro.close(),
        ), patch(
            "utils.redis_client.get_shared_redis", lambda: None,
        ):
            result = await DatadogNode.load_field_value(
                field_name="webhook_url",
                user_id="user-1",
                workflow_id=wf_id,
                node_id="node-1",
                pool=pool,
                context={"operation": "on_new_event",
                         "schedule": {"frequency": "minutes", "interval": 5}},
            )
        values = result["values"]
        assert values["webhook_id"] == "wh_1"
        assert values["webhook_url"] == "https://hook.example/abc"
        assert values["schedule_id"] == "sch_1"
        assert values["next_run"] == "2026-01-01T00:00:00Z"
        assert values["interval_ms"] == 5 * 60 * 1000
        assert values["is_active"] is True
        assert values["trigger_registered"] is True

    @pytest.mark.asyncio
    async def test_load_field_value_other_field_is_noop(self):
        """Only webhook_url provisions; other fields return a null value."""
        import uuid as uuid_module

        result = await DatadogNode.load_field_value(
            field_name="something_else",
            user_id="user-1",
            workflow_id=uuid_module.uuid4(),
            node_id="node-1",
            pool=Mock(),
        )
        assert result == {"value": None}


# ============================================================================
# Metrics
# ============================================================================


class TestDatadogMetricsMock:
    @pytest.mark.asyncio
    async def test_submit_metrics(self, credentials):
        config = DatadogNodeConfig(
            config=DatadogSubmitMetricsConfig(
                metric="my.app.requests", value="42", metric_type="gauge", tags="env:prod"
            ),
            credentials=credentials,
        )
        node = create_datadog_node(config)
        mock_client = create_mock_client(202, {"errors": []})
        with patch("nodes.datadog_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "submit_metrics"

    @pytest.mark.asyncio
    async def test_query_timeseries(self, credentials):
        config = DatadogNodeConfig(
            config=DatadogQueryTimeseriesConfig(
                query="avg:system.cpu.user{*}", from_ms="1700000000000", to_ms="1700003600000"
            ),
            credentials=credentials,
        )
        node = create_datadog_node(config)
        mock_client = create_mock_client(200, {"data": {"attributes": {"values": [[1.0]]}}})
        with patch("nodes.datadog_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "query_timeseries"

    @pytest.mark.asyncio
    async def test_query_metrics(self, credentials):
        config = DatadogNodeConfig(
            config=DatadogQueryMetricsConfig(
                query="system.cpu.idle{*}", from_ts="1700000000", to_ts="1700003600"
            ),
            credentials=credentials,
        )
        node = create_datadog_node(config)
        mock_client = create_mock_client(200, {"series": [{"metric": "system.cpu.idle"}]})
        with patch("nodes.datadog_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "query_metrics"
        assert result["data"]["series"][0]["metric"] == "system.cpu.idle"

    @pytest.mark.asyncio
    async def test_list_metrics(self, credentials):
        config = DatadogNodeConfig(
            config=DatadogListMetricsConfig(from_ts="1700000000"), credentials=credentials
        )
        node = create_datadog_node(config)
        mock_client = create_mock_client(200, {"metrics": ["system.cpu.idle"]})
        with patch("nodes.datadog_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_metrics"
        assert "system.cpu.idle" in result["data"]["metrics"]

    @pytest.mark.asyncio
    async def test_get_metric_metadata(self, credentials):
        config = DatadogNodeConfig(
            config=DatadogGetMetricMetadataConfig(metric_name="system.cpu.idle"),
            credentials=credentials,
        )
        node = create_datadog_node(config)
        mock_client = create_mock_client(200, {"type": "gauge", "unit": "percent"})
        with patch("nodes.datadog_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_metric_metadata"
        assert result["data"]["type"] == "gauge"


# ============================================================================
# Logs
# ============================================================================


class TestDatadogLogsMock:
    @pytest.mark.asyncio
    async def test_send_logs(self, credentials):
        config = DatadogNodeConfig(
            config=DatadogSendLogsConfig(
                message="something happened", ddsource="python", service="api", ddtags="env:prod"
            ),
            credentials=credentials,
        )
        node = create_datadog_node(config)
        mock_client = create_mock_client(202, {"status": "ok"})
        with patch("nodes.datadog_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "send_logs"

    @pytest.mark.asyncio
    async def test_search_logs(self, credentials):
        config = DatadogNodeConfig(
            config=DatadogSearchLogsConfig(query="service:api status:error"),
            credentials=credentials,
        )
        node = create_datadog_node(config)
        mock_client = create_mock_client(200, {"data": [{"id": "log_1"}]})
        with patch("nodes.datadog_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "search_logs"
        assert len(result["data"]["data"]) == 1

    @pytest.mark.asyncio
    async def test_aggregate_logs(self, credentials):
        config = DatadogNodeConfig(
            config=DatadogAggregateLogsConfig(query="service:api", group_by="status"),
            credentials=credentials,
        )
        node = create_datadog_node(config)
        mock_client = create_mock_client(200, {"data": {"buckets": [{"by": {"status": "error"}}]}})
        with patch("nodes.datadog_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "aggregate_logs"


# ============================================================================
# Dashboards
# ============================================================================


class TestDatadogDashboardsMock:
    @pytest.mark.asyncio
    async def test_create_dashboard(self, credentials):
        config = DatadogNodeConfig(
            config=DatadogCreateDashboardConfig(title="My Board", layout_type="ordered"),
            credentials=credentials,
        )
        node = create_datadog_node(config)
        mock_client = create_mock_client(200, {"id": "abc-123", "title": "My Board"})
        with patch("nodes.datadog_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_dashboard"
        assert result["data"]["id"] == "abc-123"

    @pytest.mark.asyncio
    async def test_get_dashboard(self, credentials):
        config = DatadogNodeConfig(
            config=DatadogGetDashboardConfig(dashboard_id="abc-123"), credentials=credentials
        )
        node = create_datadog_node(config)
        mock_client = create_mock_client(200, {"id": "abc-123", "title": "My Board"})
        with patch("nodes.datadog_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_dashboard"
        assert result["data"]["id"] == "abc-123"

    @pytest.mark.asyncio
    async def test_list_dashboards(self, credentials):
        config = DatadogNodeConfig(
            config=DatadogListDashboardsConfig(), credentials=credentials
        )
        node = create_datadog_node(config)
        mock_client = create_mock_client(200, {"dashboards": [{"id": "abc-123"}]})
        with patch("nodes.datadog_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_dashboards"
        assert result["data"]["dashboards"][0]["id"] == "abc-123"

    @pytest.mark.asyncio
    async def test_update_dashboard_with_explicit_widgets(self, credentials):
        """When widgets_json is provided, use it directly without fetching existing."""
        config = DatadogNodeConfig(
            config=DatadogUpdateDashboardConfig(
                dashboard_id="abc-123",
                title="Renamed Board",
                layout_type="ordered",
                widgets_json='[{"definition": {"type": "note", "content": "hi"}}]',
            ),
            credentials=credentials,
        )
        node = create_datadog_node(config)
        captured = {}

        async def fake_request(*args, **kwargs):
            captured.setdefault("calls", []).append(kwargs.get("method", args[0] if args else ""))
            captured["json"] = kwargs.get("json")
            mock_resp = Mock()
            mock_resp.status_code = 200
            mock_resp.text = '{"id": "abc-123", "title": "Renamed Board"}'
            mock_resp.json = lambda: {"id": "abc-123", "title": "Renamed Board"}
            return mock_resp

        mock_client = Mock()
        mock_client.request = fake_request
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("nodes.datadog_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_dashboard"
        # Only one HTTP call — no GET needed when widgets_json is provided
        assert len(captured.get("calls", [])) == 1
        assert captured["json"]["widgets"] == [{"definition": {"type": "note", "content": "hi"}}]

    @pytest.mark.asyncio
    async def test_update_dashboard_without_widgets_fetches_existing(self, credentials):
        """When widgets_json is blank, the node fetches existing widgets before PUT
        so it does not silently destroy all widgets on the dashboard."""
        config = DatadogNodeConfig(
            config=DatadogUpdateDashboardConfig(
                dashboard_id="abc-123", title="Renamed Board", layout_type="ordered"
                # widgets_json intentionally omitted (None)
            ),
            credentials=credentials,
        )
        node = create_datadog_node(config)
        existing_widgets = [{"definition": {"type": "timeseries"}}]
        calls = []

        async def fake_request(method, url, **kwargs):
            calls.append(method)
            mock_resp = Mock()
            mock_resp.status_code = 200
            if method == "GET":
                mock_resp.text = '{"id": "abc-123", "widgets": [...]}'
                mock_resp.json = lambda: {"id": "abc-123", "widgets": existing_widgets}
            else:
                mock_resp.text = '{"id": "abc-123", "title": "Renamed Board"}'
                mock_resp.json = lambda: {"id": "abc-123", "title": "Renamed Board"}
            return mock_resp

        mock_client = Mock()
        mock_client.request = fake_request
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("nodes.datadog_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        # Two HTTP calls: GET to fetch widgets, then PUT
        assert calls == ["GET", "PUT"], f"Expected [GET, PUT], got {calls}"

    @pytest.mark.asyncio
    async def test_delete_dashboard(self, credentials):
        config = DatadogNodeConfig(
            config=DatadogDeleteDashboardConfig(dashboard_id="abc-123"), credentials=credentials
        )
        node = create_datadog_node(config)
        mock_client = create_mock_client(200, {"deleted_dashboard_id": "abc-123"})
        with patch("nodes.datadog_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_dashboard"


# ============================================================================
# Incidents
# ============================================================================


class TestDatadogIncidentsMock:
    @pytest.mark.asyncio
    async def test_create_incident(self, credentials):
        config = DatadogNodeConfig(
            config=DatadogCreateIncidentConfig(title="Outage", customer_impacted="true"),
            credentials=credentials,
        )
        node = create_datadog_node(config)
        mock_client = create_mock_client(201, {"data": {"id": "inc_1", "type": "incidents"}})
        with patch("nodes.datadog_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_incident"
        assert result["data"]["data"]["id"] == "inc_1"

    @pytest.mark.asyncio
    async def test_list_incidents(self, credentials):
        config = DatadogNodeConfig(
            config=DatadogListIncidentsConfig(page_size="5"), credentials=credentials
        )
        node = create_datadog_node(config)
        mock_client = create_mock_client(200, {"data": [{"id": "inc_1"}]})
        with patch("nodes.datadog_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_incidents"
        assert len(result["data"]["data"]) == 1

    @pytest.mark.asyncio
    async def test_update_incident(self, credentials):
        config = DatadogNodeConfig(
            config=DatadogUpdateIncidentConfig(incident_id="inc_1", state="resolved"),
            credentials=credentials,
        )
        node = create_datadog_node(config)
        mock_client = create_mock_client(200, {"data": {"id": "inc_1"}})
        with patch("nodes.datadog_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_incident"


# ============================================================================
# Downtimes
# ============================================================================


class TestDatadogDowntimesMock:
    @pytest.mark.asyncio
    async def test_create_downtime(self, credentials):
        config = DatadogNodeConfig(
            config=DatadogCreateDowntimeConfig(scope="env:staging", message="Maintenance"),
            credentials=credentials,
        )
        node = create_datadog_node(config)
        mock_client = create_mock_client(200, {"data": {"id": "dt_1", "type": "downtime"}})
        with patch("nodes.datadog_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_downtime"
        assert result["data"]["data"]["id"] == "dt_1"

    @pytest.mark.asyncio
    async def test_cancel_downtime(self, credentials):
        config = DatadogNodeConfig(
            config=DatadogCancelDowntimeConfig(downtime_id="dt_1"), credentials=credentials
        )
        node = create_datadog_node(config)
        mock_client = create_mock_client(204, None, text="")
        with patch("nodes.datadog_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "cancel_downtime"


# ============================================================================
# Error handling
# ============================================================================


class TestDatadogErrorHandlingMock:
    @pytest.mark.asyncio
    async def test_api_error(self, credentials):
        config = DatadogNodeConfig(
            config=DatadogGetMonitorConfig(monitor_id="999"), credentials=credentials
        )
        node = create_datadog_node(config)
        mock_client = create_mock_client(404, {"errors": ["Monitor not found"]})
        with patch("nodes.datadog_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "error"
        assert result["status_code"] == 404
        assert "not found" in str(result["error"]).lower()

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        config = DatadogNodeConfig(
            config=DatadogListMonitorsConfig(), credentials=None
        )
        node = create_datadog_node(config)
        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})


# ============================================================================
# Dynamic options
# ============================================================================


class TestDatadogDynamicOptionsMock:
    @pytest.mark.asyncio
    async def test_load_monitor_options(self):
        cred = {"api_key": "dd_api", "app_key": "dd_app", "site": "datadoghq.com"}
        with patch(
            "nodes.datadog_node._datadog_request",
            return_value={
                "status": "success",
                "data": [{"id": 123, "name": "High CPU"}, {"id": 456, "name": "Low Disk"}],
            },
        ):
            result = await DatadogNode.load_field_options(
                field_name="monitor_id", credential_data=cred
            )
        assert "options" in result
        assert result["options"][0]["value"] == "123"
        assert result["options"][0]["label"] == "High CPU"

    @pytest.mark.asyncio
    async def test_load_dashboard_options(self):
        cred = {"api_key": "dd_api", "app_key": "dd_app", "site": "datadoghq.com"}
        with patch(
            "nodes.datadog_node._datadog_request",
            return_value={
                "status": "success",
                "data": {"dashboards": [{"id": "abc-123", "title": "My Board"}]},
            },
        ):
            result = await DatadogNode.load_field_options(
                field_name="dashboard_id", credential_data=cred
            )
        assert "options" in result
        assert result["options"][0]["value"] == "abc-123"
        assert result["options"][0]["label"] == "My Board"

    @pytest.mark.asyncio
    async def test_load_options_unknown_field(self):
        result = await DatadogNode.load_field_options(
            field_name="unrelated_field", credential_data={}
        )
        assert result == {"options": []}


# ============================================================================
# Bug-fix regression tests
# ============================================================================


class TestDatadogBugFixes:
    """Regression tests for confirmed bugs fixed in the review pass."""

    # --- Bug 1: _post_event body structure -----------------------------------

    @pytest.mark.asyncio
    async def test_post_event_uses_v1_flat_body(self, credentials):
        """Post event must use the v1 flat body (title/text at root), NOT v2 data.attributes nesting.
        The v2 POST endpoint requires events_write scope not available on all accounts."""
        config = DatadogNodeConfig(
            config=DatadogPostEventConfig(title="Deploy", text="v2 deployed", tags="env:prod"),
            credentials=credentials,
        )
        node = create_datadog_node(config)
        captured = {}

        async def fake_request(*args, **kwargs):
            captured["url"] = args[1] if len(args) > 1 else kwargs.get("url", "")
            captured["json"] = kwargs.get("json")
            mock_resp = Mock()
            mock_resp.status_code = 202
            mock_resp.text = '{"event": {"id": 12345}}'
            mock_resp.json = lambda: {"event": {"id": 12345}}
            return mock_resp

        mock_client = Mock()
        mock_client.request = fake_request
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("nodes.datadog_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        # Must use the v1 endpoint
        assert "/api/v1/events" in captured["url"], f"Expected v1 endpoint, got: {captured['url']}"
        body = captured["json"]
        # v1 body: flat — title and text at the root, NOT nested under data.attributes
        assert body["title"] == "Deploy"
        assert body["text"] == "v2 deployed"
        assert "data" not in body, "v1 body must not wrap in data.attributes"
        assert body.get("alert_type") == "info"
        assert body.get("priority") == "normal"

    # --- Bug 2: _create_downtime uses v1 API (v2 monitor_identifier invalid) ---

    @pytest.mark.asyncio
    async def test_create_downtime_all_monitors_uses_v1_endpoint(self, credentials):
        """Downtime creation must use v1 endpoint — v2 monitor_identifier validation
        rejects all formats on trial/standard accounts."""
        config = DatadogNodeConfig(
            config=DatadogCreateDowntimeConfig(scope="env:staging"),
            credentials=credentials,
        )
        node = create_datadog_node(config)
        captured = {}

        async def fake_request(*args, **kwargs):
            captured["url"] = args[1] if len(args) > 1 else kwargs.get("url", "")
            captured["json"] = kwargs.get("json")
            mock_resp = Mock()
            mock_resp.status_code = 200
            mock_resp.text = '{"id": 123456}'
            mock_resp.json = lambda: {"id": 123456}
            return mock_resp

        mock_client = Mock()
        mock_client.request = fake_request
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("nodes.datadog_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        assert "/api/v1/downtime" in captured["url"]
        body = captured["json"]
        # v1 scope is a list
        assert isinstance(body["scope"], list)
        assert "env:staging" in body["scope"]
        # No monitor_identifier in v1 body — all monitors when monitor_id absent
        assert "monitor_identifier" not in body

    @pytest.mark.asyncio
    async def test_create_downtime_with_monitor_id(self, credentials):
        config = DatadogNodeConfig(
            config=DatadogCreateDowntimeConfig(
                scope="host:myhost",
                monitor_id="12345",
            ),
            credentials=credentials,
        )
        node = create_datadog_node(config)
        captured = {}

        async def fake_request(*args, **kwargs):
            captured["json"] = kwargs.get("json")
            mock_resp = Mock()
            mock_resp.status_code = 200
            mock_resp.text = '{"id": 654321}'
            mock_resp.json = lambda: {"id": 654321}
            return mock_resp

        mock_client = Mock()
        mock_client.request = fake_request
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("nodes.datadog_node.httpx.AsyncClient", return_value=mock_client):
            await node.execute({})

        body = captured["json"]
        # v1 uses integer monitor_id at root level
        assert body.get("monitor_id") == 12345
        assert isinstance(body["scope"], list)

    # --- Bug 3: poll trigger cursor gap --------------------------------------

    @pytest.mark.asyncio
    async def test_poll_stores_last_seen_ts_ms_on_baseline(self, credentials):
        """First poll should persist last_seen_ts_ms alongside last_seen_id.
        Covers both numeric epoch-s timestamps and ISO 8601 strings (Events v2 format)."""
        config = DatadogNodeConfig(
            config=DatadogOnNewEventConfig(query=""),
            credentials=credentials,
        )
        node = create_datadog_node(config)
        # Events v2 returns ISO 8601 strings for timestamp
        events_payload = {
            "data": [
                {"id": "evt_3", "type": "event", "attributes": {"title": "C", "timestamp": "2023-11-14T23:46:40+00:00"}},  # epoch 1700010400
                {"id": "evt_1", "type": "event", "attributes": {"title": "A", "timestamp": "2023-11-14T21:33:20+00:00"}},  # epoch 1700001200
            ]
        }
        mock_client = create_mock_client(200, events_payload)
        saved = _bind_state(node)
        with patch("nodes.datadog_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert saved["last_seen_id"] == "evt_3"
        # last_seen_ts_ms must be stored so subsequent polls can widen the window
        assert "last_seen_ts_ms" in saved
        from datetime import datetime, timezone as tz
        expected_ms = int(datetime.fromisoformat("2023-11-14T23:46:40+00:00").timestamp() * 1000)
        assert abs(saved["last_seen_ts_ms"] - expected_ms) < 2000
        # baselined flag must be saved so next poll knows baseline already ran
        assert saved["baselined"] is True

    @pytest.mark.asyncio
    async def test_poll_baseline_empty_saves_baselined_flag(self, credentials):
        """First poll with no matching events must still save baselined:True so
        the next poll can emit events posted in between."""
        config = DatadogNodeConfig(
            config=DatadogOnNewEventConfig(query="tags:nonexistent"),
            credentials=credentials,
        )
        node = create_datadog_node(config)
        empty_payload = {"data": []}
        mock_client = create_mock_client(200, empty_payload)
        saved = _bind_state(node)
        with patch("nodes.datadog_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        assert result["new_count"] == 0
        # CRITICAL: baselined flag must be saved even when there are no events
        assert saved.get("baselined") is True
        assert "last_seen_ts_ms" in saved

    @pytest.mark.asyncio
    async def test_poll_after_empty_baseline_emits_new_events(self, credentials):
        """If poll 1 found no events (baselined=True, last_seen_id=None), poll 2
        must emit events discovered for the first time — not baseline again."""
        config = DatadogNodeConfig(
            config=DatadogOnNewEventConfig(query="tags:noclick_e2e"),
            credentials=credentials,
        )
        node = create_datadog_node(config)
        events_payload = {
            "data": [
                {"id": "evt_new", "type": "event", "attributes": {"title": "First", "timestamp": "2023-11-15T06:13:20+00:00"}},
            ]
        }
        mock_client = create_mock_client(200, events_payload)
        # Simulate state left by poll 1 (empty baseline)
        saved = _bind_state(
            node,
            {"last_seen_id": None, "last_seen_ts_ms": 1700040000000, "baselined": True},
        )
        with patch("nodes.datadog_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        # Must emit the new event, not treat this as another baseline
        assert result["new_count"] == 1
        assert result["events"][0]["id"] == "evt_new"
        assert saved.get("last_seen_id") == "evt_new"

    @pytest.mark.asyncio
    async def test_poll_cursor_gap_does_not_emit_old_events(self, credentials):
        """When last_seen_id is absent (gap > window), no events should be emitted
        — the stored timestamp widens the window so the cursor event is included."""
        config = DatadogNodeConfig(
            config=DatadogOnNewEventConfig(query=""),
            credentials=credentials,
        )
        node = create_datadog_node(config)
        # Simulate gap: last_seen_ts_ms stored, API returns events within the wider window
        # including the cursor event (evt_3 is back in range).
        events_payload = {
            "data": [
                {"id": "evt_5", "type": "event", "attributes": {"title": "E", "timestamp": "2023-11-15T02:46:40+00:00"}},
                {"id": "evt_4", "type": "event", "attributes": {"title": "D", "timestamp": "2023-11-15T01:23:20+00:00"}},
                {"id": "evt_3", "type": "event", "attributes": {"title": "C", "timestamp": "2023-11-15T00:00:00+00:00"}},
            ]
        }
        mock_client = create_mock_client(200, events_payload)
        # last_seen_ts_ms is provided so filter[from] will be set accordingly
        saved = _bind_state(
            node, {"last_seen_id": "evt_3", "last_seen_ts_ms": 1700010000 * 1000}
        )
        with patch("nodes.datadog_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        # Only events newer than the cursor are emitted
        assert result["new_count"] == 2
        emitted_ids = [e["id"] for e in result["events"]]
        assert emitted_ids == ["evt_5", "evt_4"]
        assert "evt_3" not in emitted_ids

    # --- Bug 4: isdigit() rejects float timestamps ---------------------------

    @pytest.mark.asyncio
    async def test_mute_monitor_float_timestamp_accepted(self, credentials):
        """A float POSIX timestamp (e.g. 1750000000.5) must be accepted, not silently dropped."""
        config = DatadogNodeConfig(
            config=DatadogMuteMonitorConfig(monitor_id="123", end="1750000000.5"),
            credentials=credentials,
        )
        node = create_datadog_node(config)
        captured = {}

        async def fake_request(*args, **kwargs):
            captured["json"] = kwargs.get("json")
            mock_resp = Mock()
            mock_resp.status_code = 200
            mock_resp.text = '{"id": 123}'
            mock_resp.json = lambda: {"id": 123}
            return mock_resp

        mock_client = Mock()
        mock_client.request = fake_request
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("nodes.datadog_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        # end must be present as int (truncated from float), not None
        assert captured["json"]["end"] == 1750000000

    @pytest.mark.asyncio
    async def test_submit_metrics_float_timestamp_accepted(self, credentials):
        """A float POSIX timestamp must be accepted for metric submission."""
        config = DatadogNodeConfig(
            config=DatadogSubmitMetricsConfig(metric="my.metric", value="42", timestamp="1750000000.9"),
            credentials=credentials,
        )
        node = create_datadog_node(config)
        captured = {}

        async def fake_request(*args, **kwargs):
            captured["json"] = kwargs.get("json")
            mock_resp = Mock()
            mock_resp.status_code = 202
            mock_resp.text = '{"errors": []}'
            mock_resp.json = lambda: {"errors": []}
            return mock_resp

        mock_client = Mock()
        mock_client.request = fake_request
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("nodes.datadog_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        assert captured["json"]["series"][0]["points"][0]["timestamp"] == 1750000000

    # --- Bug 5: filter_from must be ISO 8601 on subsequent polls ---------------

    @pytest.mark.asyncio
    async def test_poll_filter_from_is_iso8601_on_subsequent_poll(self, credentials):
        """When last_seen_ts_ms is stored, filter[from] must be ISO 8601.
        Sending a raw epoch-ms integer string causes the Events v2 API to reject with 400."""
        config = DatadogNodeConfig(
            config=DatadogOnNewEventConfig(query=""),
            credentials=credentials,
        )
        node = create_datadog_node(config)
        captured = {}

        async def fake_request(method, url, **kwargs):
            captured["params"] = kwargs.get("params", {})
            mock_resp = Mock()
            mock_resp.status_code = 200
            mock_resp.text = '{"data": {"data": []}}'
            mock_resp.json = lambda: {"data": {"data": []}}
            return mock_resp

        mock_client = Mock()
        mock_client.request = fake_request
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        # Simulate state from a previous poll: ts_ms is epoch ms of cursor event
        stored_ts_ms = 1700010000 * 1000  # 1.7 trillion — 13 digits, clearly ms
        _bind_state(
            node,
            {"last_seen_id": "evt_old", "last_seen_ts_ms": stored_ts_ms, "baselined": True},
        )

        with patch("nodes.datadog_node.httpx.AsyncClient", return_value=mock_client):
            await node.execute({})

        filter_from = captured["params"].get("filter[from]", "")
        # Must be ISO 8601 (contains "T" and "+"), NOT a 13-digit ms integer string
        assert "T" in filter_from, (
            f"filter[from] must be ISO 8601, got raw numeric: {filter_from!r}"
        )
        assert "+" in filter_from or "Z" in filter_from, (
            f"filter[from] must include timezone offset, got: {filter_from!r}"
        )
        # Must NOT be a bare integer string (which would fail the Events v2 API)
        assert not filter_from.isdigit(), (
            f"filter[from] must not be a raw integer epoch string, got: {filter_from!r}"
        )

    @pytest.mark.asyncio
    async def test_poll_event_ts_ms_parses_iso8601_timestamp(self, credentials):
        """_event_ts_ms must correctly parse ISO 8601 timestamp strings returned
        by the Events v2 API (float() conversion would always return None)."""
        config = DatadogNodeConfig(
            config=DatadogOnNewEventConfig(query=""),
            credentials=credentials,
        )
        node = create_datadog_node(config)
        # Events v2 returns attributes.timestamp as ISO 8601 string
        events_payload = {
            "data": [
                {
                    "id": "evt_iso",
                    "type": "event",
                    "attributes": {
                        "title": "ISO event",
                        "timestamp": "2023-11-14T21:33:20+00:00",  # epoch 1700001200
                    },
                }
            ]
        }
        mock_client = create_mock_client(200, events_payload)
        saved = _bind_state(node)
        with patch("nodes.datadog_node.httpx.AsyncClient", return_value=mock_client):
            await node.execute({})

        # last_seen_ts_ms must reflect the actual event timestamp, not wall-clock
        assert "last_seen_ts_ms" in saved
        from datetime import datetime, timezone as tz
        expected_ms = int(datetime.fromisoformat("2023-11-14T21:33:20+00:00").timestamp() * 1000)
        assert abs(saved["last_seen_ts_ms"] - expected_ms) < 2000, (
            f"ISO 8601 timestamp not parsed correctly, got: {saved['last_seen_ts_ms']}, expected ~{expected_ms}"
        )

    # --- Bug 6: int() without guard in _query_timeseries --------------------

    @pytest.mark.asyncio
    async def test_query_timeseries_invalid_ms_raises_value_error(self, credentials):
        """Non-integer from_ms/to_ms should raise a clear ValueError, not crash."""
        config = DatadogNodeConfig(
            config=DatadogQueryTimeseriesConfig(
                query="avg:system.cpu.user{*}",
                from_ms="now-1h",  # invalid — must be epoch ms
                to_ms="now",
            ),
            credentials=credentials,
        )
        node = create_datadog_node(config)
        with pytest.raises(ValueError, match="epoch millisecond"):
            await node.execute({})
