"""
Tests for the workflow soft-delete (trash) feature.

Covers:
- cleanup_workflow_operational_resources: partial cleanup for soft-delete (cron + webhooks only)
- cleanup_expired_trashed_workflows: permanent deletion of expired trash items
- Verifies R2 storage, node state, and workflow_resources are preserved during soft-delete
- Verifies full cleanup occurs during permanent deletion
"""

import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call

from tests.mocks.mock_asyncpg import (
    MockAsyncpgPool,
    MockAsyncpgRecord,
    configure_mock_query_responses,
    clear_executed_queries,
    get_executed_queries,
)

from utils.workflow_resource_manager import (
    cleanup_workflow_operational_resources,
    cleanup_workflow_resources,
    cleanup_expired_trashed_workflows,
)


@pytest.fixture(autouse=True)
def reset_mock_state():
    clear_executed_queries()
    configure_mock_query_responses({})
    yield
    clear_executed_queries()
    configure_mock_query_responses({})


# ── cleanup_workflow_operational_resources ─────────────────────────────


@pytest.mark.asyncio
class TestCleanupWorkflowOperationalResources:
    """Tests for partial cleanup used during soft-delete (move to trash)."""

    async def test_cleans_up_cron_and_deregisters_webhooks(self):
        """Operational cleanup (soft-delete/trash) removes cron schedules and
        routes webhook teardown through the deregistration choke point
        (deregister_node_webhooks), which deactivates + PRESERVES the internal
        webhook rows so a restore reuses the same URL/UUID. The rows are only
        hard-deleted on permanent delete — so delete_webhooks_for_workflow
        must NOT be called."""
        pool = MockAsyncpgPool()
        workflow_id = str(uuid.uuid4())

        mock_delete_schedules = AsyncMock(return_value={"deleted": 2})
        mock_dereg = AsyncMock(return_value={"deregistered": 3, "failed": 0})
        mock_delete_webhooks = AsyncMock(return_value=3)

        with patch("utils.cron_scheduler_client.delete_schedules_for_workflow", mock_delete_schedules), \
             patch("utils.webhook_manager.WebhookManager.deregister_node_webhooks", mock_dereg), \
             patch("utils.webhook_manager.WebhookManager.delete_webhooks_for_workflow", mock_delete_webhooks):
            result = await cleanup_workflow_operational_resources(pool, workflow_id)

        mock_delete_schedules.assert_called_once_with(workflow_id=workflow_id)
        # on_trash=True: irreversible teardown (inbound-email reservation
        # release) is skipped so trash stays restorable.
        mock_dereg.assert_awaited_once_with(pool, workflow_id, on_trash=True)
        mock_delete_webhooks.assert_not_called()  # rows preserved for restore
        assert result["cron"] == {"deleted": 2}
        assert result["webhooks"] == {"deregistered": 3, "failed": 0, "preserved": True}

    async def test_does_not_touch_node_state_or_r2(self):
        """Operational cleanup must NOT delete node state, R2 blobs, or workflow_resources."""
        pool = MockAsyncpgPool()
        workflow_id = str(uuid.uuid4())

        mock_delete_schedules = AsyncMock(return_value={"deleted": 0})
        mock_dereg = AsyncMock(return_value={"deregistered": 0, "failed": 0})

        with patch("utils.cron_scheduler_client.delete_schedules_for_workflow", mock_delete_schedules), \
             patch("utils.webhook_manager.WebhookManager.deregister_node_webhooks", mock_dereg):
            result = await cleanup_workflow_operational_resources(pool, workflow_id)

        # Only cron and webhooks keys should exist — no node_state, workflow_resources, or node_outputs
        assert set(result.keys()) == {"cron", "webhooks"}

        # Verify no database queries were executed (node state deletion would require a query)
        queries = get_executed_queries()
        for q in queries:
            assert "workflow_node_state" not in q["query"], \
                "Operational cleanup must not delete node state"
            assert "workflow_resources" not in q["query"], \
                "Operational cleanup must not delete workflow resources"

    async def test_handles_cron_failure_gracefully(self):
        """If cron scheduler is down, operational cleanup should still succeed."""
        pool = MockAsyncpgPool()
        workflow_id = str(uuid.uuid4())

        mock_delete_schedules = AsyncMock(side_effect=Exception("Scheduler unreachable"))
        mock_dereg = AsyncMock(return_value={"deregistered": 1, "failed": 0})

        with patch("utils.cron_scheduler_client.delete_schedules_for_workflow", mock_delete_schedules), \
             patch("utils.webhook_manager.WebhookManager.deregister_node_webhooks", mock_dereg):
            result = await cleanup_workflow_operational_resources(pool, workflow_id)

        assert "error" in result["cron"]
        assert result["webhooks"] == {"deregistered": 1, "failed": 0, "preserved": True}

    async def test_handles_webhook_failure_gracefully(self):
        """If webhook deregistration fails, operational cleanup should still return results."""
        pool = MockAsyncpgPool()
        workflow_id = str(uuid.uuid4())

        mock_delete_schedules = AsyncMock(return_value={"deleted": 0})
        mock_dereg = AsyncMock(side_effect=Exception("DB error"))

        with patch("utils.cron_scheduler_client.delete_schedules_for_workflow", mock_delete_schedules), \
             patch("utils.webhook_manager.WebhookManager.deregister_node_webhooks", mock_dereg):
            result = await cleanup_workflow_operational_resources(pool, workflow_id)

        assert result["cron"] == {"deleted": 0}
        assert "error" in result["webhooks"]


# ── cleanup_workflow_resources (full cleanup) ──────────────────────────


@pytest.mark.asyncio
class TestCleanupWorkflowResources:
    """Tests for full cleanup used during permanent deletion."""

    async def test_cleans_up_all_resource_types(self):
        """Full cleanup should remove cron, webhooks, node state, R2 blobs, and workflow_resources."""
        pool = MockAsyncpgPool()
        workflow_id = str(uuid.uuid4())

        # Configure mock to return R2 storage refs when queried
        configure_mock_query_responses({
            "SELECT storage_ref FROM workflow_resources": [
                {"storage_ref": f"{workflow_id}/resource1.png"},
                {"storage_ref": f"{workflow_id}/resource2.csv"},
            ],
        })

        mock_delete_schedules = AsyncMock(return_value={"deleted": 1})
        mock_delete_webhooks = AsyncMock(return_value=2)
        mock_delete_r2 = MagicMock(return_value=2)
        mock_rollup = AsyncMock(return_value=None)

        with patch("utils.cron_scheduler_client.delete_schedules_for_workflow", mock_delete_schedules), \
             patch("utils.webhook_manager.WebhookManager.delete_webhooks_for_workflow", mock_delete_webhooks), \
             patch("utils.r2_cloudflare.delete_files_from_r2", mock_delete_r2), \
             patch("utils.cas.gc.rollup_workflow_totals", mock_rollup):
            result = await cleanup_workflow_resources(pool, workflow_id)

        # All resource types cleaned up
        mock_delete_schedules.assert_called_once_with(workflow_id=workflow_id)
        mock_delete_webhooks.assert_called_once_with(pool=pool, workflow_id=workflow_id)
        # CAS node outputs cascade-delete with the workflow; we only roll up totals
        mock_rollup.assert_called_once_with(pool, workflow_id)

        # R2 blobs deleted with correct storage refs
        mock_delete_r2.assert_called_once_with(
            "workflow-resources", "",
            [f"{workflow_id}/resource1.png", f"{workflow_id}/resource2.csv"]
        )

        assert result["cron"] == {"deleted": 1}
        assert result["webhooks"] == {"deleted": 2}
        assert result["node_outputs"] == {"cas_totals_rolled_up": True}

        # Verify node state and workflow_resources DB rows were deleted
        queries = get_executed_queries()
        node_state_deletes = [q for q in queries if "workflow_node_state" in q["query"] and "DELETE" in q["query"]]
        wr_deletes = [q for q in queries if "workflow_resources" in q["query"] and "DELETE" in q["query"]]
        assert len(node_state_deletes) == 1, "Should delete node state from DB"
        assert len(wr_deletes) == 1, "Should delete workflow_resources from DB"

    async def test_skips_r2_when_no_storage_refs(self):
        """If workflow has no R2 resources, skip R2 deletion but still clean up everything else."""
        pool = MockAsyncpgPool()
        workflow_id = str(uuid.uuid4())

        configure_mock_query_responses({
            "SELECT storage_ref FROM workflow_resources": [],
        })

        mock_delete_schedules = AsyncMock(return_value={"deleted": 0})
        mock_delete_webhooks = AsyncMock(return_value=0)
        mock_delete_r2 = MagicMock()
        mock_rollup = AsyncMock(return_value=None)

        with patch("utils.cron_scheduler_client.delete_schedules_for_workflow", mock_delete_schedules), \
             patch("utils.webhook_manager.WebhookManager.delete_webhooks_for_workflow", mock_delete_webhooks), \
             patch("utils.r2_cloudflare.delete_files_from_r2", mock_delete_r2), \
             patch("utils.cas.gc.rollup_workflow_totals", mock_rollup):
            result = await cleanup_workflow_resources(pool, workflow_id)

        # R2 delete should NOT be called when there are no storage refs
        mock_delete_r2.assert_not_called()

        # Other cleanups still happen
        mock_delete_schedules.assert_called_once()
        mock_delete_webhooks.assert_called_once()
        mock_rollup.assert_called_once()


# ── cleanup_expired_trashed_workflows ──────────────────────────────────


@pytest.mark.asyncio
class TestCleanupExpiredTrashedWorkflows:
    """Tests for the scheduled job that permanently deletes expired trash."""

    async def test_deletes_expired_workflows(self):
        """Should find expired workflows, clean up resources, and delete from DB."""
        wf1_id = uuid.uuid4()
        wf2_id = uuid.uuid4()

        pool = AsyncMock()
        pool.fetch = AsyncMock(return_value=[
            MockAsyncpgRecord({"id": wf1_id}),
            MockAsyncpgRecord({"id": wf2_id}),
        ])
        pool.execute = AsyncMock(return_value="DELETE 1")

        mock_cleanup = AsyncMock(return_value={})

        with patch("utils.workflow_resource_manager.cleanup_workflow_resources", mock_cleanup):
            result = await cleanup_expired_trashed_workflows(pool)

        assert result == {"deleted": 2, "total_found": 2}

        # Verify the SELECT query uses the correct retention period
        fetch_call = pool.fetch.call_args
        assert "deleted_at" in fetch_call[0][0]
        assert fetch_call[0][1] == 30  # default retention_days

        # Full cleanup called for each workflow
        assert mock_cleanup.call_count == 2
        mock_cleanup.assert_any_call(pool=pool, workflow_id=str(wf1_id))
        mock_cleanup.assert_any_call(pool=pool, workflow_id=str(wf2_id))

        # Each workflow deleted from DB
        assert pool.execute.call_count == 2
        delete_calls = [c for c in pool.execute.call_args_list if "DELETE FROM workflows" in c.args[0]]
        assert {c.args[1] for c in delete_calls} == {wf1_id, wf2_id}
        assert all("NOT EXISTS" in c.args[0] for c in delete_calls)
        assert "NOT EXISTS" in fetch_call[0][0]

    async def test_no_expired_workflows(self):
        """Should handle empty trash gracefully."""
        pool = AsyncMock()
        pool.fetch = AsyncMock(return_value=[])

        mock_cleanup = AsyncMock()

        with patch("utils.workflow_resource_manager.cleanup_workflow_resources", mock_cleanup):
            result = await cleanup_expired_trashed_workflows(pool)

        assert result == {"deleted": 0, "total_found": 0}
        mock_cleanup.assert_not_called()
        pool.execute.assert_not_called()

    async def test_delete_is_deferred_if_execution_becomes_active(self):
        workflow_id = uuid.uuid4()
        pool = AsyncMock()
        pool.fetch = AsyncMock(return_value=[MockAsyncpgRecord({"id": workflow_id})])
        pool.execute = AsyncMock(return_value="DELETE 0")
        mock_cleanup = AsyncMock(return_value={})

        with patch("utils.workflow_resource_manager.cleanup_workflow_resources", mock_cleanup):
            result = await cleanup_expired_trashed_workflows(pool)

        assert result == {"deleted": 0, "total_found": 1}
        mock_cleanup.assert_awaited_once()

    async def test_custom_retention_days(self):
        """Should respect custom retention_days parameter."""
        pool = AsyncMock()
        pool.fetch = AsyncMock(return_value=[])

        with patch("utils.workflow_resource_manager.cleanup_workflow_resources"):
            await cleanup_expired_trashed_workflows(pool, retention_days=7)

        fetch_call = pool.fetch.call_args
        assert fetch_call[0][1] == 7

    async def test_continues_on_individual_failure(self):
        """If one workflow fails to clean up, others should still be processed."""
        wf1_id = uuid.uuid4()
        wf2_id = uuid.uuid4()
        wf3_id = uuid.uuid4()

        pool = AsyncMock()
        pool.fetch = AsyncMock(return_value=[
            MockAsyncpgRecord({"id": wf1_id}),
            MockAsyncpgRecord({"id": wf2_id}),
            MockAsyncpgRecord({"id": wf3_id}),
        ])
        pool.execute = AsyncMock(return_value="DELETE 1")

        # Second workflow fails during cleanup
        mock_cleanup = AsyncMock(side_effect=[
            {},                                     # wf1 succeeds
            Exception("R2 timeout"),                # wf2 fails
            {},                                     # wf3 succeeds
        ])

        with patch("utils.workflow_resource_manager.cleanup_workflow_resources", mock_cleanup):
            result = await cleanup_expired_trashed_workflows(pool)

        # 2 succeeded, 1 failed — but all 3 were found
        assert result == {"deleted": 2, "total_found": 3}

        # DB delete should only happen for successful cleanups (wf1, wf3)
        assert pool.execute.call_count == 2
        delete_ids = [c[0][1] for c in pool.execute.call_args_list]
        assert wf1_id in delete_ids
        assert wf3_id in delete_ids
        assert wf2_id not in delete_ids


# ── Soft-delete vs permanent-delete contract ───────────────────────────


@pytest.mark.asyncio
class TestSoftDeletePreservesData:
    """
    Contract test: verify that soft-delete (operational cleanup) preserves
    all data that full cleanup (permanent delete) would remove.
    """

    async def test_operational_cleanup_is_strict_subset_of_full_cleanup(self):
        """
        The operational cleanup must only touch cron and webhooks.
        Full cleanup touches cron, webhooks, node_state, workflow_resources, and node_outputs.
        This test ensures the two don't drift apart — if full cleanup adds a new resource type,
        we want to be explicit about whether operational cleanup should also handle it.
        """
        pool = MockAsyncpgPool()
        workflow_id = str(uuid.uuid4())

        configure_mock_query_responses({
            "SELECT storage_ref FROM workflow_resources": [],
        })

        # Track which external services each function calls. Both paths
        # DEREGISTER provider webhooks via the deregister_node_webhooks choke
        # point; only the full/permanent path additionally HARD-DELETES the
        # webhook rows (and skips row management — manage_rows=False — since
        # the rows are removed wholesale right after).
        cron_calls = {"operational": 0, "full": 0}
        dereg_calls = {"operational": 0, "full": 0}
        row_delete_calls = {"operational": 0, "full": 0}
        dereg_kwargs = {"operational": None, "full": None}

        async def counting_cron(**kwargs):
            return {"deleted": 0}

        async def counting_dereg(*args, **kwargs):
            return {"deregistered": 0, "failed": 0}

        async def counting_row_delete(**kwargs):
            return 0

        # Run operational cleanup (soft-delete / trash)
        with patch("utils.cron_scheduler_client.delete_schedules_for_workflow", side_effect=counting_cron) as mock_cron, \
             patch("utils.webhook_manager.WebhookManager.deregister_node_webhooks", side_effect=counting_dereg) as mock_dereg, \
             patch("utils.webhook_manager.WebhookManager.delete_webhooks_for_workflow", side_effect=counting_row_delete) as mock_rowdel:
            op_result = await cleanup_workflow_operational_resources(pool, workflow_id)
            cron_calls["operational"] = mock_cron.call_count
            dereg_calls["operational"] = mock_dereg.call_count
            dereg_kwargs["operational"] = mock_dereg.call_args.kwargs if mock_dereg.call_args else None
            row_delete_calls["operational"] = mock_rowdel.call_count

        clear_executed_queries()

        # Run full cleanup (permanent delete)
        with patch("utils.cron_scheduler_client.delete_schedules_for_workflow", side_effect=counting_cron) as mock_cron, \
             patch("utils.webhook_manager.WebhookManager.deregister_node_webhooks", side_effect=counting_dereg) as mock_dereg, \
             patch("utils.webhook_manager.WebhookManager.delete_webhooks_for_workflow", side_effect=counting_row_delete) as mock_rowdel, \
             patch("utils.cas.gc.rollup_workflow_totals", AsyncMock(return_value=None)):
            full_result = await cleanup_workflow_resources(pool, workflow_id)
            cron_calls["full"] = mock_cron.call_count
            dereg_calls["full"] = mock_dereg.call_count
            dereg_kwargs["full"] = mock_dereg.call_args.kwargs if mock_dereg.call_args else None
            row_delete_calls["full"] = mock_rowdel.call_count

        # Both call cron + provider deregistration exactly once.
        assert cron_calls["operational"] == 1
        assert cron_calls["full"] == 1
        assert dereg_calls["operational"] == 1
        assert dereg_calls["full"] == 1

        # Soft-delete lets the choke point manage (deactivate+preserve) the
        # rows; permanent delete tears down provider-side only and hard-deletes
        # the rows itself right after.
        assert dereg_kwargs["operational"].get("manage_rows", True) is True
        assert dereg_kwargs["full"].get("manage_rows") is False

        # Only full delete hard-removes the webhook rows; soft-delete preserves
        # them so a restore reuses the same URL/UUID.
        assert row_delete_calls["operational"] == 0
        assert row_delete_calls["full"] == 1

        # Operational result should only have cron + webhooks
        assert set(op_result.keys()) == {"cron", "webhooks"}

        # Full result should have additional resource types
        assert "node_state" in full_result
        assert "workflow_resources" in full_result
        assert "node_outputs" in full_result
