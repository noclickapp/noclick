"""Poll-trigger schedule registration validity gate.

A cron schedule must only be registered for a trigger config that can run:
`registration_config_error` blocks registration (and converges any existing
schedules to none, via the register chokepoint's empty-set prune) while the
config in context is missing required fields. Complements the tick-side gate
in test_webhook.py::TestScheduleTickConfigGate — together they pin the
2026-08-04 fix for red error runs during trigger setup.
"""

import uuid
import pytest
from unittest.mock import AsyncMock, patch


COMPLETE_CTX = {
    "operation": "on_form_response",
    "form_id": "form-abc",
    "schedule": {"interval": "1", "frequency": "minutes"},
}
INCOMPLETE_CTX = {
    "operation": "on_form_response",
    "schedule": {"interval": "1", "frequency": "minutes"},
}


class TestRegistrationConfigError:
    """The pure gate: judge a trigger config (context shape) for registration."""

    def _forms_cls(self):
        from nodes.google_forms_node import GoogleFormsNode
        return GoogleFormsNode

    def test_incomplete_config_blocks(self):
        from nodes.core.poll_trigger import registration_config_error
        err = registration_config_error(self._forms_cls(), INCOMPLETE_CTX)
        assert err and "form_id" in err

    def test_complete_config_passes(self):
        from nodes.core.poll_trigger import registration_config_error
        assert registration_config_error(self._forms_cls(), COMPLETE_CTX) is None

    def test_reference_value_passes(self):
        # {{ref}} resolves at runtime — valid pending resolution.
        from nodes.core.poll_trigger import registration_config_error
        ctx = {**INCOMPLETE_CTX, "form_id": "{{other.output.id}}"}
        assert registration_config_error(self._forms_cls(), ctx) is None

    def test_no_operation_cannot_be_judged(self):
        # Contexts without an operation (FE schedule-update path) register as
        # before — the gate must never tear down a schedule it can't judge.
        from nodes.core.poll_trigger import registration_config_error
        ctx = {k: v for k, v in COMPLETE_CTX.items() if k != "operation"}
        assert registration_config_error(self._forms_cls(), ctx) is None


@pytest.mark.asyncio
class TestFamilyLoaderDelegation:
    """load_field_value (from CronScheduleTriggerMixin) mints the webhook row
    and delegates registration to WebhookManager.reconcile_node, seeding
    desired state from the panel context via nodes_override. Convergence
    behavior itself is pinned in test_schedule_registration_convergence.py."""

    async def _load(self, context, reconcile_result):
        from nodes.google_forms_node import GoogleFormsNode
        from utils.webhook_manager import WebhookManager

        webhook = {
            "webhook_id": "wh-1", "webhook_url": "https://wh-1.hooks.example.test",
            "relay_connected": True, "is_production": True,
        }
        rec = AsyncMock(return_value=reconcile_result)
        with patch.object(WebhookManager, "get_or_create_webhook",
                          AsyncMock(return_value=webhook)), \
             patch.object(WebhookManager, "reconcile_node", rec):
            result = await GoogleFormsNode.load_field_value(
                "webhook_url", "user-1", uuid.uuid4(), "n1", pool=None,
                context=context,
            )
        return result["values"], rec

    async def test_context_seeds_reconcile_override(self):
        values, rec = await self._load(
            COMPLETE_CTX,
            {"state": "registered", "values": {
                "schedule_id": "s1", "next_run": "2026-08-05T00:01:00Z",
                "trigger_registered": True, "trigger_error": None,
            }},
        )
        override = rec.await_args.kwargs["nodes_override"][0]
        assert override["id"] == "n1"
        assert override["type"] == "automation-google-forms"
        assert override["config"]["form_id"] == COMPLETE_CTX["form_id"]
        assert values["trigger_registered"] is True
        assert values["schedule_id"] == "s1"
        assert values["webhook_url"] == "https://wh-1.hooks.example.test"

    async def test_teardown_values_pass_through_including_clears(self):
        values, _ = await self._load(
            INCOMPLETE_CTX,
            {"state": "deregistered", "values": {
                "schedule_id": None, "next_run": None,
                "trigger_registered": False,
                "trigger_error": "Schedule not registered: form_id is required",
            }},
        )
        assert values["trigger_registered"] is False
        assert "form_id" in values["trigger_error"]
        # Meaningful None clears survive the None-filter.
        assert values["schedule_id"] is None
        assert values["next_run"] is None

    async def test_live_fast_path_returns_webhook_basics(self):
        values, _ = await self._load(COMPLETE_CTX, {"state": "live"})
        assert values["webhook_id"] == "wh-1"
        assert "trigger_registered" not in values  # existing mirrors kept

    async def test_credential_ids_folded_into_override_config(self):
        from nodes.google_forms_node import GoogleFormsNode
        from utils.webhook_manager import WebhookManager

        rec = AsyncMock(return_value={"state": "live"})
        with patch.object(WebhookManager, "get_or_create_webhook",
                          AsyncMock(return_value={"webhook_id": "wh-1",
                                                  "webhook_url": "u"})), \
             patch.object(WebhookManager, "reconcile_node", rec):
            await GoogleFormsNode.load_field_value(
                "webhook_url", "user-1", uuid.uuid4(), "n1", pool=None,
                context=dict(COMPLETE_CTX),
                credential_ids={"google_forms_oauth": "cred-9"},
            )
        override = rec.await_args.kwargs["nodes_override"][0]
        # The arm hook (poll baseline) resolves its credential from config.
        assert override["config"]["credentialIds"] == {"google_forms_oauth": "cred-9"}


@pytest.mark.asyncio
class TestBespokeSpecGates:
    """Bespoke family members' specs enforce their own required fields."""

    async def test_gcs_missing_bucket_blocks(self):
        from nodes.google_cloud_storage_node import GoogleCloudStorageNode

        spec = await GoogleCloudStorageNode.cron_schedule_spec(
            {"operation": "on_new_object"}, "on_new_object",
        )
        assert spec is not None and spec.expressions == []
        assert "bucket" in spec.config_error

    async def test_gcs_bucket_present_registers(self):
        from nodes.google_cloud_storage_node import GoogleCloudStorageNode

        spec = await GoogleCloudStorageNode.cron_schedule_spec(
            {"operation": "on_new_object", "bucket": "my-bucket"}, "on_new_object",
        )
        assert spec is not None and len(spec.expressions) == 1
        assert spec.config_error is None
        assert spec.source == "gcs_trigger"

    async def test_action_operation_is_not_a_schedule_op(self):
        from nodes.google_cloud_storage_node import GoogleCloudStorageNode

        spec = await GoogleCloudStorageNode.cron_schedule_spec(
            {"operation": "list_objects"}, "list_objects",
        )
        assert spec is None


@pytest.mark.asyncio
class TestArmHookDelegation:
    """The poll mixin's arm hook (run by the reconciler post-registration)
    drives the arm-time baseline with the node's config."""

    async def test_arm_hook_calls_establish_baseline(self):
        from nodes.google_forms_node import GoogleFormsNode

        with patch.object(GoogleFormsNode, "_establish_poll_baseline",
                          AsyncMock()) as est:
            await GoogleFormsNode.arm_schedule_trigger(
                user_id="u1", workflow_id="wf-1", node_id="n1",
                config={**COMPLETE_CTX, "credentialIds": {"google_forms_oauth": "c1"}},
                pool=None,
            )
        kwargs = est.await_args.kwargs
        assert kwargs["credential_ids"] == {"google_forms_oauth": "c1"}
        assert kwargs["context"]["form_id"] == COMPLETE_CTX["form_id"]


# ============================================================================
# Arm-time baseline + poll scope
# ============================================================================


class TestPollScope:
    """poll_scope hashes ONLY the operation's declared config fields (parsed
    model view). Canvas/builder metadata and infra must never shift it — the
    2026-08-04 rebuild: goal/label/operationReason churn from the builder's
    finishing writes re-baselined every poll and swallowed a real submission."""

    def _forms(self):
        from nodes.google_forms_node import GoogleFormsNode
        return GoogleFormsNode

    BASE = {
        "operation": "on_form_response",
        "form_id": "form-A",
        "schedule": {"interval": "1", "frequency": "minutes"},
        "webhook_id": "w1",
        "is_active": True,
        "credentialIds": {"google_forms_oauth": "c1"},
    }

    def test_builder_metadata_and_infra_do_not_shift_scope(self):
        from nodes.core.poll_trigger import poll_scope
        churned = {
            **self.BASE,
            "goal": "Trigger on every new form submission",
            "label": "Google Form Submission",
            "operationReason": "It polls the form for new responses.",
            "userFields": ["form_id"],
            "form_id__label": "Contact Us",
            "schedule": {"interval": "30", "frequency": "minutes"},
            "webhook_id": "w2",
            "next_run": "2027-01-01T00:00:00Z",
            "credentialIds": {"google_forms_oauth": "c2"},
            "_triggerPayload": {"x": 1},
        }
        assert poll_scope(self._forms(), self.BASE) == poll_scope(self._forms(), churned)

    def test_watched_resource_shifts_scope(self):
        from nodes.core.poll_trigger import poll_scope
        assert poll_scope(self._forms(), self.BASE) != poll_scope(
            self._forms(), {**self.BASE, "form_id": "form-B"}
        )

    def test_unparseable_config_is_unjudgeable(self):
        from nodes.core.poll_trigger import poll_scope
        assert poll_scope(self._forms(), {"operation": "on_form_response"}) is None
        assert poll_scope(self._forms(), None) is None


class _FakeOpConfig:
    pass  # placeholder so older references fail loudly if reintroduced


from pydantic import BaseModel as _BM
from nodes.core.poll_trigger import PollTriggerConfigBase as _PTB


class _ScopedOpConfig(_PTB):
    operation: str = "on_thing"
    resource_id: str = "A"


class _ConfigWrapper:
    def __init__(self, op_config):
        self.config = op_config


class _FakeScopedPoll:
    """Mixin harness with in-memory state and a parsed op-config (the view
    _filter_unseen hashes), mirroring _update_node_state write-or-skip
    semantics."""

    def __init__(self, resource_id, state=None):
        self.workflow_id = "wf"
        self.node_id = "n"
        self._config = _ConfigWrapper(_ScopedOpConfig(resource_id=resource_id))
        self._state = dict(state or {})

    async def _update_node_state(self, mutator, *, max_retries=4, skip_result=None):
        new_state, result = mutator(dict(self._state))
        if new_state is not None:
            self._state = dict(new_state)
        return result

    async def filter(self, items):
        from nodes.core.poll_trigger import ScheduledPollTriggerMixin
        return await ScheduledPollTriggerMixin._filter_unseen(
            self, items, lambda x: x["id"]
        )


def _scope_of(resource_id):
    from nodes.core.poll_trigger import _scope_of_op_config
    return _scope_of_op_config(_ScopedOpConfig(resource_id=resource_id))


@pytest.mark.asyncio
class TestScopeAwareFilterUnseen:

    async def test_first_poll_baselines_and_stamps_scope(self):
        p = _FakeScopedPoll("A")
        assert await p.filter([{"id": "1"}]) == []
        assert p._state == {"seen_ids": ["1"], "scope": _scope_of("A")}

    async def test_legacy_state_without_scope_is_adopted(self):
        # Pre-scoping state keeps deduping; scope stamps on the next write.
        p = _FakeScopedPoll("A", state={"seen_ids": ["1"]})
        fresh = await p.filter([{"id": "1"}, {"id": "2"}])
        assert [i["id"] for i in fresh] == ["2"]
        assert p._state["scope"] == _scope_of("A")

    async def test_scope_change_rebaselines_instead_of_blasting(self):
        # Trigger repointed at resource B: its full history must NOT fire.
        p = _FakeScopedPoll("B", state={"seen_ids": ["a1"], "scope": _scope_of("A")})
        assert await p.filter([{"id": "b1"}, {"id": "b2"}]) == []
        assert p._state == {"seen_ids": ["b1", "b2"], "scope": _scope_of("B")}
        # ...and an item arriving after the rebaseline fires normally.
        fresh = await p.filter([{"id": "b1"}, {"id": "b2"}, {"id": "b3"}])
        assert [i["id"] for i in fresh] == ["b3"]

    async def test_unjudgeable_scope_never_rebaselines(self):
        # No parsed config and no parseable node_data → scope None → dedup
        # runs normally against the stored baseline (never a mismatch).
        p = _FakeScopedPoll("A", state={"seen_ids": ["1"], "scope": _scope_of("A")})
        p._config = None
        p.node_data = {"config": None}
        fresh = await p.filter([{"id": "1"}, {"id": "2"}])
        assert [i["id"] for i in fresh] == ["2"]
        assert p._state["scope"] == _scope_of("A")  # stored scope preserved

    async def test_baseline_only_never_consumes_unseen(self):
        # Headless arm-poll racing a live baseline: unseen items must survive
        # for the next REAL poll — nothing runs downstream of the arm-poll.
        state = {"seen_ids": ["1"], "scope": _scope_of("A")}
        p = _FakeScopedPoll("A", state=state)
        p._poll_baseline_only = True
        assert await p.filter([{"id": "1"}, {"id": "2"}]) == []
        assert p._state == state  # untouched — "2" is still unseen
        # The next normal poll emits it.
        q = _FakeScopedPoll("A", state=p._state)
        fresh = await q.filter([{"id": "1"}, {"id": "2"}])
        assert [i["id"] for i in fresh] == ["2"]

    async def test_baseline_only_writes_when_no_state(self):
        p = _FakeScopedPoll("A")
        p._poll_baseline_only = True
        assert await p.filter([{"id": "1"}]) == []
        assert p._state["seen_ids"] == ["1"]


@pytest.mark.asyncio
class TestEstablishPollBaseline:
    """The arm-time runner: polls only when no valid baseline exists for the
    current scope, runs the node headlessly in baseline-only mode."""

    CTX = {"operation": "on_form_response", "form_id": "form-A"}

    async def _run(self, state_row, create_node=None):
        from nodes.google_forms_node import GoogleFormsNode

        fake_instance = AsyncMock()
        fake_instance.run = AsyncMock(return_value={})
        created = {}

        def _create(**kwargs):
            created.update(kwargs)
            return fake_instance

        with patch("utils.database_pool.get_native_pool") as gp, \
             patch("nodes.core.registry.NodeFactory.create_node",
                   side_effect=create_node or _create) as factory, \
             patch("nodes.core.run_op.resolve_operation_credential",
                   AsyncMock(return_value={"access_token": "t"})):
            gp.return_value.fetchrow = AsyncMock(return_value=state_row)
            await GoogleFormsNode._establish_poll_baseline(
                user_id="u1", workflow_id="wf-1", node_id="n1",
                context=self.CTX,
                credential_ids={"google_forms_oauth": "cred-1"},
                pool=None,
            )
        return fake_instance, factory, created

    async def test_no_state_runs_baseline_poll(self):
        instance, factory, created = await self._run(state_row=None)
        assert factory.called
        assert created["node_id"] == "n1"
        assert created["node_type"] == "automation-google-forms"
        assert created["node_data"]["credential_id"] == "cred-1"
        assert instance._poll_baseline_only is True
        instance.run.assert_awaited_once_with({})

    async def test_matching_baseline_skips_provider_call(self):
        from nodes.core.poll_trigger import poll_scope
        from nodes.google_forms_node import GoogleFormsNode
        row = {"state": {"seen_ids": ["1"], "scope": poll_scope(GoogleFormsNode, self.CTX)}}
        instance, factory, _ = await self._run(state_row=row)
        assert not factory.called

    async def test_legacy_unscoped_baseline_is_adopted_not_repolled(self):
        row = {"state": {"seen_ids": ["1"]}}
        instance, factory, _ = await self._run(state_row=row)
        assert not factory.called

    async def test_scope_mismatch_repolls(self):
        row = {"state": {"seen_ids": ["a1"], "scope": "stale-scope"}}
        instance, factory, _ = await self._run(state_row=row)
        assert factory.called

    async def test_failure_is_swallowed(self):
        from nodes.google_forms_node import GoogleFormsNode
        with patch("utils.database_pool.get_native_pool") as gp:
            gp.return_value.fetchrow = AsyncMock(side_effect=RuntimeError("db down"))
            await GoogleFormsNode._establish_poll_baseline(
                user_id="u1", workflow_id="wf-1", node_id="n1",
                context=self.CTX, credential_ids={}, pool=None,
            )  # must not raise


# TestLoaderSpawnsBaseline was superseded by the reconciler family: the arm
# spawn now happens inside WebhookManager._reconcile_schedule_node, pinned in
# test_schedule_registration_convergence.py (armed on `registered`, never on
# failed/incomplete/live).
