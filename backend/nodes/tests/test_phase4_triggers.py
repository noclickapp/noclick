"""Phase 4 poll-trigger tests — Google Sheets, Notion, Google Forms.

These triggers have no push API: a Cloudflare cron fires on a schedule, POSTs
the node's webhook, and execute() polls the provider. Tests cover the shared
ScheduledPollTriggerMixin (schedule provisioning, teardown, first-poll baseline
dedup) and each node's poll logic.

Run: pytest nodes/tests/test_phase4_triggers.py -v
"""

import uuid

import pytest
from unittest.mock import AsyncMock, patch

from nodes.google_sheets_node import GoogleSheetsNode, GoogleSheetsOnNewRowConfig
from nodes.notion_node import NotionNode, NotionOnDatabaseItemConfig
from nodes.google_forms_node import GoogleFormsNode, GoogleFormsOnResponseConfig
from nodes.core.poll_trigger import ScheduledPollTriggerMixin


class _FakeCred:
    def model_dump(self):
        return {"access_token": "tok", "expires_at": "2099-01-01T00:00:00+00:00"}






def _make_node(node_cls, node_id="n1"):
    node = node_cls(
        node_id=node_id,
        node_type="automation-test",
        node_data={"credential_id": "cid"},
        config=None,
        workflow_id="wf-1",
        user_id="user-1",
    )
    return node


# ---------------------------------------------------------------------------
# Shared mixin — schema, payload semantics
# ---------------------------------------------------------------------------


class TestPollTriggerFramework:
    def test_all_three_use_the_poll_mixin(self):
        for cls in (GoogleSheetsNode, NotionNode, GoogleFormsNode):
            assert issubclass(cls, ScheduledPollTriggerMixin)

    def test_trigger_ops_in_schema(self):
        cases = [
            (GoogleSheetsNode, "GoogleSheetsOnNewRowConfig", "on_new_row"),
            (NotionNode, "NotionOnDatabaseItemConfig", "on_database_item"),
            (GoogleFormsNode, "GoogleFormsOnResponseConfig", "on_form_response"),
        ]
        for node_cls, def_name, op in cases:
            schema = node_cls.get_config_schema()
            props = schema["$defs"][def_name]["properties"]
            assert props["operation"]["const"] == op
            assert props["operation"]["x-is-trigger"] is True
            # The shared schedule field is inherited from PollTriggerConfigBase.
            assert "schedule" in props

    def test_resolve_trigger_payload_is_none(self):
        # The cron POST is a wake-up signal — execute() must run.
        for cls in (GoogleSheetsNode, NotionNode, GoogleFormsNode):
            assert cls.resolve_trigger_payload({"x": 1}, {}) is None


# ---------------------------------------------------------------------------
# Mixin — schedule provisioning / teardown
# ---------------------------------------------------------------------------


class TestScheduleProvisioning:
    """The sheets loader (family CronScheduleTriggerMixin) converges through
    WebhookManager.reconcile_node; drive it end-to-end with the real register
    chokepoint (create/delete mocked). Full convergence matrix lives in
    tests/test_schedule_registration_convergence.py."""

    @staticmethod
    async def _load(context, create_result):
        from unittest.mock import MagicMock
        from utils.webhook_manager import WebhookManager

        webhook_data = {
            "webhook_id": "wh-1",
            "webhook_url": "https://wh.hooks.example.test/wh-1",
            "relay_connected": True,
            "is_production": True,
        }
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

        create_mock = AsyncMock(return_value=create_result)
        with patch(
            "utils.webhook_manager.WebhookManager.get_or_create_webhook",
            new=AsyncMock(return_value=webhook_data),
        ), patch(
            "utils.webhook_manager._load_workflow_owner_and_nodes", load_owner_nodes,
        ), patch.object(
            WebhookManager, "persist_registration_state", AsyncMock(),
        ), patch.object(
            WebhookManager, "merge_node_config_patch", AsyncMock(),
        ), patch(
            "utils.cron_scheduler_client.is_cron_scheduler_enabled",
            return_value=True,
        ), patch(
            "utils.cron_scheduler_client.create_schedule", create_mock,
        ), patch(
            "utils.cron_scheduler_client.delete_schedules_for_nodes", new=AsyncMock()
        ), patch(
            "utils.async_helpers.spawn",
            side_effect=lambda coro, name=None: coro.close(),
        ), patch(
            "utils.redis_client.get_shared_redis", lambda: None,
        ):
            result = await GoogleSheetsNode.load_field_value(
                field_name="webhook_url",
                user_id="user-1",
                workflow_id=uuid.uuid4(),
                node_id="n1",
                pool=pool,
                context=context,
                credential_ids={"google_sheets_oauth": "cid"},
            )
        return result, create_mock

    async def test_load_field_value_creates_schedule(self):
        result, mock_create = await self._load(
            {
                "operation": "on_new_row",
                "spreadsheet_id": "sheet-1",
                "schedule": {"frequency": "minutes", "interval": 5},
            },
            {"id": "sched-1", "next_run": "2026-05-18T12:00:00Z"},
        )
        values = result["values"]
        assert values["webhook_url"] == "https://wh.hooks.example.test/wh-1"
        assert values["schedule_id"] == "sched-1"
        assert values["trigger_registered"] is True
        assert values["interval_ms"] == 5 * 60 * 1000
        mock_create.assert_awaited_once()

    async def test_load_field_value_reregisters_idempotently(self):
        # Re-registration no longer calls update_schedule — it's an idempotent
        # deterministic-id upsert via create_schedule. A stale schedule_id in
        # context is ignored; the node always converges to its deterministic
        # schedule (so concurrent/repeated loads can't create duplicates).
        result, mock_create = await self._load(
            {
                "operation": "on_new_row",
                "spreadsheet_id": "sheet-1",
                "schedule": {"frequency": "hours", "interval": 1},
                "schedule_id": "existing-sched",
            },
            {"id": "sched-det", "next_run": "later"},
        )
        assert result["values"]["schedule_id"] == "sched-det"
        assert result["values"]["trigger_registered"] is True
        mock_create.assert_awaited_once()

    async def test_cleanup_deletes_schedule_only(self):
        """cleanup_external_webhook is provider-side teardown only — the
        webhooks row is owned by WebhookManager.deregister_node_webhooks."""
        with patch(
            "utils.cron_scheduler_client.delete_schedules_for_nodes",
            new=AsyncMock(),
        ) as mock_del_sched, patch(
            "utils.webhook_manager.WebhookManager.delete_webhook", new=AsyncMock()
        ) as mock_del_wh:
            await GoogleSheetsNode.cleanup_external_webhook(
                object(), "wf-1", "n1", {}, None
            )
        mock_del_sched.assert_awaited_once()
        mock_del_wh.assert_not_awaited()


# ---------------------------------------------------------------------------
# Mixin — _filter_unseen dedup
# ---------------------------------------------------------------------------


class TestFilterUnseen:
    async def test_first_poll_baselines_and_emits_nothing(self):
        node = _make_node(GoogleSheetsNode)
        node._load_node_state = AsyncMock(return_value={})  # no seen_ids key
        node._save_node_state = AsyncMock()

        items = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
        fresh = await node._filter_unseen(items, lambda i: i["id"])

        assert fresh == []  # baseline run emits nothing
        saved = node._save_node_state.await_args.args[0]
        assert set(saved["seen_ids"]) == {"a", "b", "c"}

    async def test_subsequent_poll_emits_only_new(self):
        node = _make_node(GoogleSheetsNode)
        node._load_node_state = AsyncMock(return_value={"seen_ids": ["a", "b"]})
        node._save_node_state = AsyncMock()

        items = [{"id": "a"}, {"id": "b"}, {"id": "c"}, {"id": "d"}]
        fresh = await node._filter_unseen(items, lambda i: i["id"])

        assert [i["id"] for i in fresh] == ["c", "d"]
        saved = node._save_node_state.await_args.args[0]
        assert set(saved["seen_ids"]) == {"a", "b", "c", "d"}

    async def test_no_new_items_does_not_write_state(self):
        node = _make_node(GoogleSheetsNode)
        node._load_node_state = AsyncMock(return_value={"seen_ids": ["a", "b"]})
        node._save_node_state = AsyncMock()

        fresh = await node._filter_unseen(
            [{"id": "a"}, {"id": "b"}], lambda i: i["id"]
        )
        assert fresh == []
        node._save_node_state.assert_not_awaited()

    async def test_items_without_id_are_skipped(self):
        node = _make_node(GoogleSheetsNode)
        node._load_node_state = AsyncMock(return_value={"seen_ids": []})
        node._save_node_state = AsyncMock()

        fresh = await node._filter_unseen(
            [{"id": None}, {"id": "x"}], lambda i: i["id"]
        )
        assert [i["id"] for i in fresh] == ["x"]


# ---------------------------------------------------------------------------
# Per-node poll logic
# ---------------------------------------------------------------------------


class TestSheetsPoll:
    async def test_emits_new_rows_with_header_mapping(self):
        node = _make_node(GoogleSheetsNode)
        node._load_node_state = AsyncMock(return_value={"seen_ids": ["2"]})
        node._save_node_state = AsyncMock()
        config = GoogleSheetsOnNewRowConfig(spreadsheet_id="SS1")

        sheet_values = [
            ["Name", "Email"],
            ["Alice", "a@x.com"],
            ["Bob", "b@x.com"],
        ]
        with patch(
            "nodes.google_sheets_node.ensure_fresh_google_token",
            new=AsyncMock(return_value="tok"),
        ), patch(
            "nodes.google_sheets_node.sheets_read_values",
            new=AsyncMock(return_value=sheet_values),
        ):
            result = await node._trigger_on_new_row(config, _FakeCred())

        # Row 2 (Alice) was already seen; row 3 (Bob) is new.
        assert result["new_row_count"] == 1
        assert result["rows"][0]["row"] == {"Name": "Bob", "Email": "b@x.com"}
        assert result["headers"] == ["Name", "Email"]


class TestNotionPoll:


    async def test_emits_new_or_updated_pages(self):
        node = _make_node(NotionNode)
        node._load_node_state = AsyncMock(
            return_value={"seen_ids": ["p1:t1"]}
        )
        node._save_node_state = AsyncMock()
        node._make_request = AsyncMock(
            return_value={
                "status": "success",
                "data": {
                    "results": [
                        {"id": "p1", "last_edited_time": "t1"},  # unchanged
                        {"id": "p1", "last_edited_time": "t2"},  # edited
                        {"id": "p2", "last_edited_time": "t1"},  # new
                    ]
                },
            }
        )
        config = NotionOnDatabaseItemConfig(database_id="DB1")
        result = await node._trigger_on_database_item(config, _FakeCred())

        ids = {f"{p['id']}:{p['last_edited_time']}" for p in result["items"]}
        assert ids == {"p1:t2", "p2:t1"}
        assert result["new_item_count"] == 2

    async def test_error_response_raises(self):
        node = _make_node(NotionNode)
        node._make_request = AsyncMock(
            return_value={"status": "error", "error": "bad database id"}
        )
        config = NotionOnDatabaseItemConfig(database_id="DB1")
        with pytest.raises(ValueError, match="Notion database query failed"):
            await node._trigger_on_database_item(config, _FakeCred())


class TestFormsPoll:
    async def test_emits_new_responses(self):
        node = _make_node(GoogleFormsNode)
        node._load_node_state = AsyncMock(return_value={"seen_ids": ["r1"]})
        node._save_node_state = AsyncMock()
        config = GoogleFormsOnResponseConfig(form_id="F1")

        responses = [
            {"responseId": "r1", "createTime": "t1"},
            {"responseId": "r2", "createTime": "t2"},
        ]
        with patch(
            "nodes.google_forms_node.ensure_fresh_google_token",
            new=AsyncMock(return_value="tok"),
        ), patch(
            "nodes.google_forms_node.forms_list_responses",
            new=AsyncMock(return_value=responses),
        ):
            result = await node._trigger_on_form_response(config, _FakeCred())

        assert result["new_response_count"] == 1
        assert result["responses"][0]["responseId"] == "r2"
