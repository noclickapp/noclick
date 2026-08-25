"""
Tests for the cron scheduler client.

These tests verify the HTTP client that communicates with the Cloudflare
cron scheduler Worker.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import httpx

from utils.cron_scheduler_client import (
    is_cron_scheduler_enabled,
    delete_schedules_for_nodes,
    delete_schedules_for_workflow,
    create_schedule,
    update_schedule,
    deterministic_schedule_id,
    register_node_schedules,
)


class TestIsCronSchedulerEnabled:
    """Test cron scheduler configuration check."""

    def test_enabled_when_both_vars_set(self):
        """Should return True when both URL and secret are configured."""
        with patch.dict('os.environ', {
            'CRON_SCHEDULER_URL': 'https://cron.example.com',
            'CRON_SCHEDULER_SECRET': 'secret123'
        }):
            # Need to reload the module to pick up new env vars
            from utils import cron_scheduler_client
            import importlib
            importlib.reload(cron_scheduler_client)
            assert cron_scheduler_client.is_cron_scheduler_enabled() is True

    def test_disabled_when_url_missing(self):
        """Should return False when URL is not configured."""
        with patch.dict('os.environ', {
            'CRON_SCHEDULER_URL': '',
            'CRON_SCHEDULER_SECRET': 'secret123'
        }, clear=True):
            from utils import cron_scheduler_client
            import importlib
            importlib.reload(cron_scheduler_client)
            assert cron_scheduler_client.is_cron_scheduler_enabled() is False

    def test_disabled_when_secret_missing(self):
        """Should return False when secret is not configured."""
        with patch.dict('os.environ', {
            'CRON_SCHEDULER_URL': 'https://cron.example.com',
            'CRON_SCHEDULER_SECRET': ''
        }, clear=True):
            from utils import cron_scheduler_client
            import importlib
            importlib.reload(cron_scheduler_client)
            assert cron_scheduler_client.is_cron_scheduler_enabled() is False

    def test_local_edition_derives_in_process_defaults(self):
        """A bare self-hosted backend launch keeps schedules functional."""
        with patch.dict('os.environ', {
            'NOCLICK_LOCAL': '1',
            'PORT': '8123',
        }, clear=True):
            from utils import cron_scheduler_client
            import importlib
            importlib.reload(cron_scheduler_client)
            assert cron_scheduler_client.is_cron_scheduler_enabled() is True
            assert cron_scheduler_client.CRON_SCHEDULER_URL == (
                'http://127.0.0.1:8123/local-cron'
            )
            assert cron_scheduler_client.CRON_SCHEDULER_SECRET
            assert cron_scheduler_client.CRON_SCHEDULER_SECRET == __import__('os').environ[
                'CRON_SCHEDULER_SECRET'
            ]

    def test_local_edition_replaces_blank_secret(self):
        with patch.dict('os.environ', {
            'NOCLICK_LOCAL': '1',
            'CRON_SCHEDULER_SECRET': '',
        }, clear=True):
            from utils import cron_scheduler_client
            import importlib
            importlib.reload(cron_scheduler_client)
            assert cron_scheduler_client.CRON_SCHEDULER_SECRET
            assert __import__('os').environ['CRON_SCHEDULER_SECRET']


class TestDeleteSchedulesForNodes:
    """Test bulk deletion of schedules for specific nodes."""

    @pytest.mark.asyncio
    async def test_skips_when_disabled(self):
        """Should skip deletion when cron scheduler is not configured."""
        with patch('utils.cron_scheduler_client.is_cron_scheduler_enabled', return_value=False):
            result = await delete_schedules_for_nodes(
                workflow_id='wf_123',
                node_ids=['node_1', 'node_2']
            )
            assert result == {'deleted': 0, 'skipped': True}

    @pytest.mark.asyncio
    async def test_returns_zero_for_empty_node_ids(self):
        """Should return deleted=0 when no node IDs provided."""
        with patch('utils.cron_scheduler_client.is_cron_scheduler_enabled', return_value=True):
            result = await delete_schedules_for_nodes(
                workflow_id='wf_123',
                node_ids=[]
            )
            assert result == {'deleted': 0}





class TestDeleteSchedulesForWorkflow:
    """Test deletion of all schedules for a workflow."""

    @pytest.mark.asyncio
    async def test_skips_when_disabled(self):
        """Should skip deletion when cron scheduler is not configured."""
        with patch('utils.cron_scheduler_client.is_cron_scheduler_enabled', return_value=False):
            result = await delete_schedules_for_workflow(workflow_id='wf_123')
            assert result == {'deleted': 0, 'skipped': True}



class TestCreateSchedule:
    """Test schedule creation."""

    @pytest.mark.asyncio
    async def test_skips_when_disabled(self):
        """Should skip creation when cron scheduler is not configured."""
        with patch('utils.cron_scheduler_client.is_cron_scheduler_enabled', return_value=False):
            result = await create_schedule(
                user_id='user_123',
                workflow_id='wf_456',
                node_id='node_789',
                cron_expression='0 * * * *',
                webhook_url='https://webhook.example.com/wh_123'
            )
            assert 'skipped' in result
            assert result['skipped'] is True



class TestUpdateSchedule:
    """Test schedule updates."""

    @pytest.mark.asyncio
    async def test_skips_when_disabled(self):
        """Should skip update when cron scheduler is not configured."""
        with patch('utils.cron_scheduler_client.is_cron_scheduler_enabled', return_value=False):
            result = await update_schedule(
                schedule_id='sched_123',
                cron_expression='*/5 * * * *'
            )
            assert 'skipped' in result

    @pytest.mark.asyncio
    async def test_returns_error_for_empty_update(self):
        """Should return error when no updates provided."""
        with patch('utils.cron_scheduler_client.is_cron_scheduler_enabled', return_value=True):
            result = await update_schedule(schedule_id='sched_123')
            assert result == {'error': 'No updates provided'}



def _mock_post_client(status_code, json_value):
    """Patch context yielding a mocked httpx client whose .post is captured."""
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.json.return_value = json_value
    mock_post = AsyncMock(return_value=mock_response)
    return mock_post


class TestIdempotentRegistration:
    """Idempotency primitives that prevent duplicate cron schedules."""

    def test_deterministic_schedule_id_is_stable(self):
        # Same inputs must always yield the same id, so re-registration upserts
        # the existing row instead of minting a duplicate.
        a = deterministic_schedule_id('wf_1', 'node_1', 0)
        b = deterministic_schedule_id('wf_1', 'node_1', 0)
        assert a == b

    def test_deterministic_schedule_id_varies_by_slot_node_workflow(self):
        base = deterministic_schedule_id('wf_1', 'node_1', 0)
        assert deterministic_schedule_id('wf_1', 'node_1', 1) != base
        assert deterministic_schedule_id('wf_1', 'node_2', 0) != base
        assert deterministic_schedule_id('wf_2', 'node_1', 0) != base






class TestRegisterNodeSchedules:
    """The shared registration chokepoint every trigger node routes through."""

    @pytest.mark.asyncio
    async def test_upserts_each_slot_and_prunes_to_desired_set(self):
        created = []

        async def fake_create(**kwargs):
            created.append(kwargs['schedule_id'])
            return {'id': kwargs['schedule_id'], 'next_run': '2025-01-15T10:00:00Z'}

        delete_mock = AsyncMock(return_value={'deleted': 0})
        with patch('utils.cron_scheduler_client.is_cron_scheduler_enabled', return_value=True), \
             patch('utils.cron_scheduler_client.create_schedule', side_effect=fake_create), \
             patch('utils.cron_scheduler_client.delete_schedules_for_nodes', delete_mock):
            res = await register_node_schedules(
                user_id='u', workflow_id='wf', node_id='n',
                webhook_url='https://x', cron_expressions=['* * * * *', '0 * * * *'],
            )

        expected = [
            deterministic_schedule_id('wf', 'n', 0),
            deterministic_schedule_id('wf', 'n', 1),
        ]
        # Each slot upserted under its deterministic id...
        assert created == expected
        assert res['schedule_ids'] == expected
        assert res['schedule_id'] == expected[0]
        assert res['is_active'] is True
        # ...and the prune keeps EXACTLY the desired set (everything else dropped).
        assert delete_mock.call_args.kwargs['keep_ids'] == expected

    @pytest.mark.asyncio
    async def test_is_idempotent_across_repeated_calls(self):
        async def fake_create(**kwargs):
            return {'id': kwargs['schedule_id'], 'next_run': None}

        with patch('utils.cron_scheduler_client.is_cron_scheduler_enabled', return_value=True), \
             patch('utils.cron_scheduler_client.create_schedule', side_effect=fake_create), \
             patch('utils.cron_scheduler_client.delete_schedules_for_nodes', new_callable=AsyncMock):
            r1 = await register_node_schedules(
                user_id='u', workflow_id='wf', node_id='n',
                webhook_url='https://x', cron_expressions=['* * * * *'],
            )
            r2 = await register_node_schedules(
                user_id='u', workflow_id='wf', node_id='n',
                webhook_url='https://x', cron_expressions=['* * * * *'],
            )
        # Same inputs → same id both times (worker upserts one row, no duplicate).
        assert r1['schedule_ids'] == r2['schedule_ids']

    @pytest.mark.asyncio
    async def test_noop_when_scheduler_disabled(self):
        with patch('utils.cron_scheduler_client.is_cron_scheduler_enabled', return_value=False), \
             patch('utils.cron_scheduler_client.create_schedule', new_callable=AsyncMock) as mock_create, \
             patch('utils.cron_scheduler_client.delete_schedules_for_nodes', new_callable=AsyncMock) as mock_delete:
            res = await register_node_schedules(
                user_id='u', workflow_id='wf', node_id='n',
                webhook_url='https://x', cron_expressions=['* * * * *'],
            )
        assert res == {'schedule_ids': [], 'schedule_id': None, 'next_run': None, 'is_active': False}
        mock_create.assert_not_called()
        mock_delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_noop_when_no_webhook_url(self):
        with patch('utils.cron_scheduler_client.is_cron_scheduler_enabled', return_value=True), \
             patch('utils.cron_scheduler_client.create_schedule', new_callable=AsyncMock) as mock_create:
            res = await register_node_schedules(
                user_id='u', workflow_id='wf', node_id='n',
                webhook_url='', cron_expressions=['* * * * *'],
            )
        assert res['is_active'] is False
        mock_create.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_prune_when_all_creates_fail(self):
        # Total transient failure must NOT prune — pruning then would delete the
        # node's still-live (possibly legacy-id) schedule with no replacement.
        delete_mock = AsyncMock(return_value={'deleted': 0})
        with patch('utils.cron_scheduler_client.is_cron_scheduler_enabled', return_value=True), \
             patch('utils.cron_scheduler_client.create_schedule', new=AsyncMock(return_value={'error': 'Timeout'})), \
             patch('utils.cron_scheduler_client.delete_schedules_for_nodes', delete_mock):
            res = await register_node_schedules(
                user_id='u', workflow_id='wf', node_id='n',
                webhook_url='https://x', cron_expressions=['* * * * *'],
            )
        assert res['is_active'] is False
        assert res['schedule_ids'] == []
        delete_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_cron_expressions_still_prunes_all(self):
        # Cron disabled (empty desired set) must still prune every schedule.
        delete_mock = AsyncMock(return_value={'deleted': 1})
        with patch('utils.cron_scheduler_client.is_cron_scheduler_enabled', return_value=True), \
             patch('utils.cron_scheduler_client.create_schedule', new_callable=AsyncMock) as mock_create, \
             patch('utils.cron_scheduler_client.delete_schedules_for_nodes', delete_mock):
            res = await register_node_schedules(
                user_id='u', workflow_id='wf', node_id='n',
                webhook_url='https://x', cron_expressions=[],
            )
        assert res['is_active'] is False
        mock_create.assert_not_called()
        delete_mock.assert_called_once()
        assert delete_mock.call_args.kwargs['keep_ids'] == []
