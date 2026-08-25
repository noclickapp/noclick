"""
Tests for the cron trigger node implementation.

These tests verify the CronTriggerNode configuration, schedule conversion,
field loading, and execution behavior.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import uuid

from nodes.cron_trigger_node import (
    CronTriggerNode,
    CronTriggerConfig,
    CronTriggerNodeConfig,
    schedule_to_cron,
    _resolve_whole_schedule_reference,
)


class TestScheduleToCron:
    """Test schedule to cron expression conversion."""

    def test_every_5_seconds(self):
        """Every 5 seconds should produce '*/5s * * * *' (custom external-scheduler format)"""
        assert schedule_to_cron({"frequency": "seconds", "interval": 5}) == "*/5s * * * *"

    def test_every_30_seconds(self):
        """Every 30 seconds should produce '*/30s * * * *'"""
        assert schedule_to_cron({"frequency": "seconds", "interval": 30}) == "*/30s * * * *"

    def test_every_minute(self):
        """Every minute should produce '* * * * *'"""
        assert schedule_to_cron({"frequency": "minute"}) == "* * * * *"

    def test_every_5_minutes(self):
        """Every 5 minutes should produce '*/5 * * * *'"""
        assert schedule_to_cron({"frequency": "minutes", "interval": 5}) == "*/5 * * * *"

    def test_every_15_minutes(self):
        """Every 15 minutes should produce '*/15 * * * *'"""
        assert schedule_to_cron({"frequency": "minutes", "interval": 15}) == "*/15 * * * *"

    def test_every_hour(self):
        """Every hour should produce '0 * * * *'"""
        assert schedule_to_cron({"frequency": "hour"}) == "0 * * * *"

    def test_every_2_hours(self):
        """Every 2 hours should produce '0 */2 * * *' (divides evenly into 24)"""
        assert schedule_to_cron({"frequency": "hours", "interval": 2}) == "0 */2 * * *"

    def test_every_5_hours(self):
        """Every 5 hours should use custom interval format (doesn't divide into 24)"""
        assert schedule_to_cron({"frequency": "hours", "interval": 5}) == "0 0 * * * /5h"

    def test_every_15_hours(self):
        """Every 15 hours should use custom interval format (doesn't divide into 24)"""
        assert schedule_to_cron({"frequency": "hours", "interval": 15}) == "0 0 * * * /15h"

    def test_daily_at_9am(self):
        """Every day at 9:00 AM should produce '0 9 * * *'"""
        assert schedule_to_cron({"frequency": "day", "hour": 9, "minute": 0}) == "0 9 * * *"

    def test_daily_at_2_30pm(self):
        """Every day at 2:30 PM should produce '30 14 * * *'"""
        assert schedule_to_cron({"frequency": "day", "hour": 14, "minute": 30}) == "30 14 * * *"

    def test_weekly_monday_9am(self):
        """Every Monday at 9:00 AM should produce '0 9 * * 1'"""
        assert schedule_to_cron({"frequency": "week", "dayOfWeek": 1, "hour": 9, "minute": 0}) == "0 9 * * 1"

    def test_weekly_friday_5pm(self):
        """Every Friday at 5:00 PM should produce '0 17 * * 5'"""
        assert schedule_to_cron({"frequency": "week", "dayOfWeek": 5, "hour": 17, "minute": 0}) == "0 17 * * 5"

    def test_monthly_1st_midnight(self):
        """Every 1st of the month at midnight should produce '0 0 1 * *'"""
        assert schedule_to_cron({"frequency": "month", "dayOfMonth": 1, "hour": 0, "minute": 0}) == "0 0 1 * *"

    def test_monthly_15th_noon(self):
        """Every 15th of the month at noon should produce '0 12 15 * *'"""
        assert schedule_to_cron({"frequency": "month", "dayOfMonth": 15, "hour": 12, "minute": 0}) == "0 12 15 * *"

    def test_every_2_weeks_monday_9am(self):
        """Every 2 weeks on Monday at 9:00 AM should produce '0 9 * * 1 /2w'"""
        assert schedule_to_cron({"frequency": "weeks", "interval": 2, "dayOfWeek": 1, "hour": 9, "minute": 0}) == "0 9 * * 1 /2w"

    def test_every_3_weeks_friday_5pm(self):
        """Every 3 weeks on Friday at 5:00 PM should produce '0 17 * * 5 /3w'"""
        assert schedule_to_cron({"frequency": "weeks", "interval": 3, "dayOfWeek": 5, "hour": 17, "minute": 0}) == "0 17 * * 5 /3w"

    def test_biweekly_default_values(self):
        """Biweekly with defaults should use Monday at 9:00 AM"""
        assert schedule_to_cron({"frequency": "weeks", "interval": 2}) == "0 9 * * 1 /2w"

    def test_default_schedule(self):
        """Empty or invalid schedule should default to hourly."""
        assert schedule_to_cron({}) == "0 * * * *"
        assert schedule_to_cron({"frequency": "invalid"}) == "0 * * * *"


class TestCronTriggerConfig:
    """Test CronTriggerConfig Pydantic model."""

    def test_default_values(self):
        """Should have sensible defaults."""
        config = CronTriggerConfig()
        # Schedules has a default value for better UX
        assert config.schedules is not None
        assert len(config.schedules) == 1
        assert config.schedules[0].frequency == "hours"
        assert config.schedules[0].interval is None
        assert config.timezone == "UTC"
        assert config.webhook_id is None
        assert config.webhook_url is None
        assert config.schedule_ids is None
        assert config.is_active is True

    def test_full_config(self):
        """Should accept all fields."""
        config = CronTriggerConfig(
            schedules=[{"frequency": "day", "hour": 9, "minute": 0}],
            timezone="UTC",
            webhook_id="wh_123",
            webhook_url="https://example.com/wh_123",
            schedule_ids=["sched_456"],
            next_run="2025-01-15T00:00:00Z",
            is_active=True
        )
        assert config.webhook_id == "wh_123"
        assert config.schedule_ids == ["sched_456"]
        assert config.schedules[0].frequency == "day"

    def test_backward_compat_single_schedule(self):
        """Should migrate old single schedule to schedules array."""
        config = CronTriggerConfig(
            schedule={"frequency": "week", "dayOfWeek": 1},
            schedule_id="sched_old",
        )
        assert len(config.schedules) == 1
        assert config.schedules[0].frequency == "week"
        assert config.schedule_ids == ["sched_old"]


class TestCronTriggerNodeConfig:
    """Test the full node config model."""

    def test_config_with_nested_config(self):
        """Should properly nest the config."""
        node_config = CronTriggerNodeConfig(
            config=CronTriggerConfig(schedules=[{"frequency": "week", "dayOfWeek": 1}])
        )
        assert node_config.config.schedules[0].frequency == "week"

    def test_config_schema_generation(self):
        """Should generate valid JSON schema."""
        schema = CronTriggerNodeConfig.model_json_schema()
        assert 'properties' in schema


class TestCronTriggerNodeLoadFieldValue:
    """The loader (inherited from CronScheduleTriggerMixin) mints the webhook
    row and converges through WebhookManager.reconcile_node. These tests drive
    it END TO END with the real register chokepoint (create/delete mocked), so
    the deterministic-id idempotency invariants stay pinned at this level."""

    @staticmethod
    async def _drive(workflow_id, context, *, pool=None, create=None,
                     scheduler_enabled=True, node_id='node_789'):
        """Run load_field_value with the reconcile fakes; returns
        (result, create_mock, delete_mock)."""
        from unittest.mock import AsyncMock, MagicMock, patch
        from utils.webhook_manager import WebhookManager

        webhook = {'webhook_id': 'wh_test123',
                   'webhook_url': 'https://wh_test123.hooks.example.test',
                   'relay_connected': True, 'is_production': True}

        if pool is None:
            conn = AsyncMock()
            conn.fetchrow = AsyncMock(return_value=None)
            conn.execute = AsyncMock(return_value='UPDATE 1')
            pool = MagicMock()
            pool.acquire = MagicMock(return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=conn),
                __aexit__=AsyncMock(return_value=False),
            ))

        async def load_owner_nodes(p, wf_uuid, include_nodes=True):
            return 'owner-1', []

        create_mock = AsyncMock(side_effect=create) if create else AsyncMock(
            return_value={'id': 'sched_test456', 'next_run': '2025-01-15T10:00:00Z'}
        )
        delete_mock = AsyncMock()

        with patch('utils.webhook_manager._load_workflow_owner_and_nodes', load_owner_nodes), \
             patch.object(WebhookManager, 'get_or_create_webhook',
                          AsyncMock(return_value=webhook)), \
             patch.object(WebhookManager, 'persist_registration_state', AsyncMock()), \
             patch.object(WebhookManager, 'deactivate_webhook', AsyncMock()), \
             patch.object(WebhookManager, 'merge_node_config_patch', AsyncMock()), \
             patch('utils.cron_scheduler_client.create_schedule', create_mock), \
             patch('utils.cron_scheduler_client.delete_schedules_for_nodes', delete_mock), \
             patch('utils.cron_scheduler_client.is_cron_scheduler_enabled',
                   return_value=scheduler_enabled), \
             patch('utils.async_helpers.spawn',
                   side_effect=lambda coro, name=None: coro.close()), \
             patch('utils.redis_client.get_shared_redis', lambda: None):
            result = await CronTriggerNode.load_field_value(
                field_name='webhook_url', user_id='user_123',
                workflow_id=workflow_id, node_id=node_id, pool=pool,
                context=context,
            )
        return result, create_mock, delete_mock

    @pytest.mark.asyncio
    async def test_load_webhook_url_creates_webhook_and_schedule(self):
        """Should create both webhook and schedule when loading webhook_url."""
        workflow_id = uuid.uuid4()
        result, mock_create, mock_delete = await self._drive(
            workflow_id, {'schedule': {'frequency': 'minutes', 'interval': 5}}
        )

        # Verify old schedules were pruned (keep the desired set)
        mock_delete.assert_called_once()

        # Verify schedule was created with correct cron expression
        mock_create.assert_called_once()
        call_args = mock_create.call_args
        assert call_args.kwargs['cron_expression'] == '*/5 * * * *'
        assert call_args.kwargs['webhook_url'] == 'https://wh_test123.hooks.example.test'

        # Idempotent registration: create uses a DETERMINISTIC id, and the
        # prune keeps exactly that id — so concurrent/repeated loads upsert
        # one row instead of creating duplicates (the 3x-schedules bug).
        from utils.cron_scheduler_client import deterministic_schedule_id
        expected_id = deterministic_schedule_id(str(workflow_id), 'node_789', 0)
        assert call_args.kwargs['schedule_id'] == expected_id
        assert mock_delete.call_args.kwargs['keep_ids'] == [expected_id]

        # Verify result contains all values
        assert result['values']['webhook_id'] == 'wh_test123'
        assert result['values']['webhook_url'] == 'https://wh_test123.hooks.example.test'
        assert result['values']['next_run'] == '2025-01-15T10:00:00Z'
        # Must NOT echo schedules/timezone back: the FE owns them and merges
        # this loader's values over local config, so echoing the schedule the
        # request was built from reverts the user's in-flight edits to a stale
        # value (the cron schedule "keeps reverting" regression).
        assert 'schedules' not in result['values']
        assert 'timezone' not in result['values']

    @pytest.mark.asyncio
    async def test_load_webhook_url_registration_is_idempotent(self):
        """Repeated loads must reuse the SAME deterministic schedule id, so
        concurrent/duplicate registrations upsert one row instead of creating
        duplicates (the 3x-schedules bug)."""
        from utils.cron_scheduler_client import deterministic_schedule_id

        workflow_id = uuid.uuid4()
        captured_ids = []

        async def fake_create(**kwargs):
            captured_ids.append(kwargs['schedule_id'])
            return {'id': kwargs['schedule_id'], 'next_run': '2025-01-15T10:00:00Z'}

        ctx = {'schedule': {'frequency': 'minutes', 'interval': 5}}
        r1, _, _ = await self._drive(workflow_id, ctx, create=fake_create)
        r2, _, _ = await self._drive(workflow_id, ctx, create=fake_create)

        expected_id = deterministic_schedule_id(str(workflow_id), 'node_789', 0)
        # Both registrations sent the same id → the worker upserts one row.
        assert captured_ids == [expected_id, expected_id]
        assert r1['values']['schedule_ids'] == [expected_id]
        assert r2['values']['schedule_ids'] == [expected_id]

    @pytest.mark.asyncio
    async def test_load_webhook_url_uses_default_schedule_without_context(self):
        """Should use default hourly schedule when context not provided."""
        workflow_id = uuid.uuid4()
        result, mock_create, _ = await self._drive(workflow_id, None)

        # Should use default hourly cron (hours with interval 1)
        call_args = mock_create.call_args
        assert call_args.kwargs['cron_expression'] == '0 */1 * * *'

        # Even on the fallback path the loader must not echo `schedules` back
        # (the FE owns that field — echoing it reverts in-flight edits).
        assert 'schedules' not in result['values']

    @pytest.mark.asyncio
    async def test_load_webhook_url_handles_scheduler_disabled(self):
        """Should still return webhook data — and register NOTHING — when the
        scheduler is disabled (local dev). Crucially the reconciler must not
        tear anything down either: disabled = cannot judge."""
        workflow_id = uuid.uuid4()
        result, mock_create, mock_delete = await self._drive(
            workflow_id, {}, scheduler_enabled=False
        )

        # Should still have webhook data
        assert result['values']['webhook_id'] == 'wh_test123'
        assert result['values']['webhook_url'] == 'https://wh_test123.hooks.example.test'
        # But no registration side effects and no registration mirrors.
        mock_create.assert_not_called()
        mock_delete.assert_not_called()
        assert 'schedule_ids' not in result['values']
        assert 'trigger_registered' not in result['values']

    @pytest.mark.asyncio
    async def test_load_other_field_returns_none(self):
        """Should return None for non-webhook_url fields."""
        mock_pool = MagicMock()
        workflow_id = uuid.uuid4()

        result = await CronTriggerNode.load_field_value(
            field_name='some_other_field',
            user_id='user_123',
            workflow_id=workflow_id,
            node_id='node_789',
            pool=mock_pool,
            context={}
        )

        assert result == {'value': None}


class TestCronTriggerNodeExecution:
    """Test the execute method."""

    @pytest.mark.asyncio
    async def test_execute_outputs_trigger_metadata(self):
        """Should output cron trigger metadata."""
        node = CronTriggerNode(
            node_id='cron_node_1',
            node_type='trigger-cron',
            node_data={},
            config=None,
            sio=None,
            sid=None,
            workflow_id='wf_123'
        )

        # Mock emit
        node.emit = AsyncMock()

        inputs = {
            'schedule_id': 'sched_123',
            'workflow_id': 'wf_456',
            'triggered_at': '2025-01-15T10:00:00Z',
            'custom_data': 'value',
            '_webhook': {'id': 'wh_789'}
        }

        result = await node.execute(inputs)

        # Verify output structure
        assert result['type'] == 'cron-trigger'
        assert result['status'] == 'triggered'
        assert 'timestamp' in result
        assert result['schedule_id'] == 'sched_123'
        assert result['triggered_at'] == '2025-01-15T10:00:00Z'
        assert result['webhook_id'] == 'wh_789'
        # Payload should exclude metadata fields
        assert 'custom_data' in result['payload']
        assert '_webhook' not in result['payload']
        assert '_cron' not in result['payload']

        # Verify emit was called
        node.emit.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_handles_minimal_inputs(self):
        """Should handle execution with minimal inputs."""
        node = CronTriggerNode(
            node_id='cron_node_1',
            node_type='trigger-cron',
            node_data={},
            config=None,
            sio=None,
            sid=None,
            workflow_id='wf_123'
        )

        node.emit = AsyncMock()

        result = await node.execute({})

        assert result['type'] == 'cron-trigger'
        assert result['status'] == 'triggered'
        assert result['payload'] == {}


class TestCronTriggerNodeRegistration:
    """Test node registration in registry."""

    def test_node_is_registered(self):
        """Should be registered in NODE_REGISTRY."""
        from nodes.core.registry import NODE_REGISTRY
        assert 'trigger-cron' in NODE_REGISTRY
        assert NODE_REGISTRY['trigger-cron'] == CronTriggerNode

    def test_config_model_available(self):
        """Should return config model."""
        model = CronTriggerNode.get_config_model()
        assert model == CronTriggerNodeConfig


class TestWholeScheduleReferenceResolution:
    """Test _resolve_whole_schedule_reference for resolving {{nodeId.values.field}} references."""

    @pytest.mark.asyncio
    async def test_resolve_single_schedule(self):
        """Should resolve a reference to a single schedule config dict."""
        workflow_id = uuid.uuid4()
        node_id = "interface-config-form-abc123"
        workflow_data = {"nodes": [
            {"id": node_id, "config": {"values": {"my_schedule": [{"frequency": "day", "hour": 10, "minute": 30}]}}}
        ]}

        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value={"workflow": workflow_data})
        mock_pool = MagicMock()
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_pool.acquire.return_value = mock_ctx

        result = await _resolve_whole_schedule_reference(
            f"{{{{{node_id}.values.my_schedule}}}}",
            workflow_id,
            mock_pool
        )

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["frequency"] == "day"
        assert result[0]["hour"] == 10

    @pytest.mark.asyncio
    async def test_resolve_multiple_schedules(self):
        """Should resolve a reference to a list of schedule configs."""
        workflow_id = uuid.uuid4()
        node_id = "interface-config-form-abc123"
        workflow_data = {"nodes": [
            {"id": node_id, "config": {"values": {"schedules": [
                {"frequency": "day", "hour": 9, "minute": 0},
                {"frequency": "week", "dayOfWeek": 1, "hour": 10, "minute": 0},
            ]}}}
        ]}

        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value={"workflow": workflow_data})
        mock_pool = MagicMock()
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_pool.acquire.return_value = mock_ctx

        result = await _resolve_whole_schedule_reference(
            f"{{{{{node_id}.values.schedules}}}}",
            workflow_id,
            mock_pool
        )

        assert isinstance(result, list)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_resolve_missing_node_returns_none(self):
        """Should return None when referenced node is not in workflow."""
        workflow_id = uuid.uuid4()
        workflow_data = {"nodes": []}

        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value={"workflow": workflow_data})
        mock_pool = MagicMock()
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_pool.acquire.return_value = mock_ctx

        result = await _resolve_whole_schedule_reference(
            "{{missing-node.values.field}}",
            workflow_id,
            mock_pool
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_resolve_invalid_reference_returns_none(self):
        """Should return None for an invalid reference format."""
        workflow_id = uuid.uuid4()
        mock_pool = AsyncMock()

        result = await _resolve_whole_schedule_reference(
            "not-a-reference",
            workflow_id,
            mock_pool
        )

        assert result is None


class TestEmptySchedules:
    """Behavior when schedules list is empty (cron disabled) and when
    schedules arrive as whole-schedule references."""

    @staticmethod
    def _ref_pool(blob_row):
        """Pool whose fetchrow serves the workflow blob for reference
        resolution and None for the reconciler's webhooks-row SELECT."""
        from unittest.mock import AsyncMock, MagicMock

        async def fetchrow(sql, *args):
            if 'FROM webhooks' in sql:
                return None
            return blob_row

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=fetchrow)
        conn.execute = AsyncMock(return_value='UPDATE 1')
        pool = MagicMock()
        pool.acquire = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=conn),
            __aexit__=AsyncMock(return_value=False),
        ))
        return pool

    @pytest.mark.asyncio
    async def test_empty_schedules_disables_cron(self):
        """Should prune all schedules and mirror cron-disabled state when
        schedules is explicitly empty."""
        workflow_id = uuid.uuid4()
        result, mock_create, mock_delete = (
            await TestCronTriggerNodeLoadFieldValue._drive(
                workflow_id, {'schedules': [], 'schedule_id': 'stale'},
            )
        )

        # Old schedules deleted, none created.
        mock_delete.assert_called_once()
        mock_create.assert_not_called()
        # Result mirrors the teardown: no schedule, not registered.
        assert result['values']['schedule_id'] is None
        assert result['values']['next_run'] is None
        assert result['values']['trigger_registered'] is False

    @pytest.mark.asyncio
    async def test_whole_schedule_reference_in_load_field_value(self):
        """Should resolve whole-schedule string references during load_field_value."""
        workflow_id = uuid.uuid4()
        ref_node_id = "interface-config-form-abc123"
        pool = self._ref_pool({
            "workflow": {"nodes": [
                {"id": ref_node_id, "config": {"values": {"my_schedule": [
                    {"frequency": "day", "hour": 14, "minute": 30}
                ]}}}
            ]}
        })

        async def fake_create(**kwargs):
            return {'id': 'sched_ref_1', 'next_run': '2025-01-15T14:30:00Z'}

        result, mock_create, _ = await TestCronTriggerNodeLoadFieldValue._drive(
            workflow_id,
            {'schedules': [f"{{{{{ref_node_id}.values.my_schedule}}}}"]},
            pool=pool, create=fake_create,
        )

        # Should have created a schedule from the resolved reference
        mock_create.assert_called_once()
        call_args = mock_create.call_args
        # day at 14:30 → cron "30 14 * * *"
        assert call_args.kwargs['cron_expression'] == '30 14 * * *'
        assert result['values']['is_active'] is True
        assert result['values']['schedule_ids'] == ['sched_ref_1']

    @pytest.mark.asyncio
    async def test_bare_string_schedule_reference_in_load_field_value(self):
        """Should resolve a bare string reference (not wrapped in a list) for
        schedules — the frontend stores a plain "{{node.values.schedule}}"
        string when set via the UI."""
        workflow_id = uuid.uuid4()
        ref_node_id = "interface-config-form-losg"
        pool = self._ref_pool({
            "workflow": {"nodes": [
                {"id": ref_node_id, "config": {"values": {"schedule": [
                    {"frequency": "week", "hour": 6, "minute": 0, "dayOfWeek": 1},
                    {"frequency": "week", "hour": 6, "minute": 0, "dayOfWeek": 4},
                ]}}}
            ]}
        })

        created = []

        async def fake_create(**kwargs):
            created.append(kwargs['cron_expression'])
            return {'id': f"sched_week_{len(created)}", 'next_run': '2025-01-20T11:00:00Z'}

        result, mock_create, _ = await TestCronTriggerNodeLoadFieldValue._drive(
            workflow_id,
            {'schedules': f"{{{{{ref_node_id}.values.schedule}}}}"},
            pool=pool, create=fake_create,
        )

        # Both entries of the referenced schedule list became cron schedules.
        assert created == ['0 6 * * 1', '0 6 * * 4']
        assert result['values']['schedule_ids'] == ['sched_week_1', 'sched_week_2']


class TestConfigWithStringEntries:
    """Test CronTriggerConfig with string entries (whole references)."""

    def test_config_accepts_string_entries(self):
        """Should accept string entries in the schedules list."""
        config = CronTriggerConfig(
            schedules=["{{node123.values.schedule}}"]
        )
        assert len(config.schedules) == 1
        assert config.schedules[0] == "{{node123.values.schedule}}"

    def test_config_accepts_mixed_entries(self):
        """Should accept a mix of ScheduleConfig objects and string references."""
        config = CronTriggerConfig(
            schedules=[
                {"frequency": "day", "hour": 9, "minute": 0},
                "{{node123.values.schedule}}"
            ]
        )
        assert len(config.schedules) == 2
        assert hasattr(config.schedules[0], 'frequency')
        assert config.schedules[1] == "{{node123.values.schedule}}"
