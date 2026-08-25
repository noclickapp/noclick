"""Unit + integration tests for cross-workflow error routing.

Covers the WorkflowSettingsDialog.error_handler_workflow_id contract enforced
in WorkflowExecutionHandler:
- the sync gate (_maybe_dispatch_error_handler) skips when there's no target,
  when target == source, and when the failing run is itself an error_handler
  run (one-hop recursion stop);
- the async dispatcher (_dispatch_error_handler_workflow) finds the target's
  on-error node, injects _error_inputs with the SOURCE workflow's identifiers,
  and calls handle_execute with start_node_id pointed at the on-error node and
  trigger_source='error_handler';
- no on-error node in the target is a silent no-op (handler is responsible
  for surfacing this — the source run already completed).
"""

import asyncio
import json
import uuid
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace

from wss.handlers.workflow_execution_handler import WorkflowExecutionHandler
from wss.receiver.client_events import WorkflowUpdateRequest
from wss.sender import send_event
from tests.utils.base_handler_test import BaseHandlerTest
from tests.fixtures.real_db_fixture import real_database  # noqa: F401


def _make_request(workflow_id: str, trigger_source: str = "manual"):
    # Lightweight stand-in: the methods we exercise read only these attrs.
    return SimpleNamespace(workflow_id=workflow_id, trigger_source=trigger_source)


class TestMaybeDispatchGate:
    """Sync gate around the fire-and-forget spawn — the cheap rejections."""

    def setup_method(self):
        self.handler = WorkflowExecutionHandler(sio=None)
        self.source = str(uuid.uuid4())
        self.target = str(uuid.uuid4())
        self.user = str(uuid.uuid4())

    def _kwargs(self):
        return dict(
            execution_id="exec-1",
            user_id=self.user,
            error_msg="boom",
            nodes_executed=3,
            duration=1.5,
        )

    def test_no_target_set_does_not_spawn(self):
        with patch("wss.handlers.workflow_execution_handler.spawn") as spawn:
            self.handler._maybe_dispatch_error_handler(
                _make_request(self.source), **self._kwargs(), workflow_settings={},
            )
            assert spawn.call_count == 0

    def test_empty_string_target_does_not_spawn(self):
        with patch("wss.handlers.workflow_execution_handler.spawn") as spawn:
            self.handler._maybe_dispatch_error_handler(
                _make_request(self.source),
                **self._kwargs(),
                workflow_settings={"error_handler_workflow_id": "   "},
            )
            assert spawn.call_count == 0

    def test_self_target_does_not_spawn(self):
        # The frontend filters self out of the picker but the backend is the
        # last line of defense — a malformed direct settings write must not
        # cause a workflow to infinite-loop into itself.
        with patch("wss.handlers.workflow_execution_handler.spawn") as spawn:
            self.handler._maybe_dispatch_error_handler(
                _make_request(self.source),
                **self._kwargs(),
                workflow_settings={"error_handler_workflow_id": self.source},
            )
            assert spawn.call_count == 0

    def test_error_handler_trigger_source_does_not_spawn(self):
        # One-hop only: if THIS run was itself an error_handler dispatch, a
        # second failure must not cascade — even to a different workflow.
        with patch("wss.handlers.workflow_execution_handler.spawn") as spawn:
            self.handler._maybe_dispatch_error_handler(
                _make_request(self.source, trigger_source="error_handler"),
                **self._kwargs(),
                workflow_settings={"error_handler_workflow_id": self.target},
            )
            assert spawn.call_count == 0

    def test_no_user_id_does_not_spawn(self):
        with patch("wss.handlers.workflow_execution_handler.spawn") as spawn:
            kwargs = self._kwargs()
            kwargs["user_id"] = None
            self.handler._maybe_dispatch_error_handler(
                _make_request(self.source),
                **kwargs,
                workflow_settings={"error_handler_workflow_id": self.target},
            )
            assert spawn.call_count == 0

    def test_valid_target_spawns(self):
        # Stub the dispatcher so the gate doesn't build a coroutine that goes
        # unawaited under the mocked spawn (RuntimeWarning noise).
        with patch("wss.handlers.workflow_execution_handler.spawn") as spawn, \
             patch.object(self.handler, "_dispatch_error_handler_workflow",
                          AsyncMock(return_value=None)) as dispatcher:
            self.handler._maybe_dispatch_error_handler(
                _make_request(self.source),
                **self._kwargs(),
                workflow_settings={"error_handler_workflow_id": self.target},
            )
            assert spawn.call_count == 1
            assert dispatcher.call_count == 1
            kwargs = dispatcher.call_args.kwargs
            assert kwargs["target_workflow_id"] == self.target
            assert kwargs["source_workflow_id"] == self.source
            assert kwargs["user_id"] == self.user


class TestDispatchErrorHandlerWorkflow:
    """Async dispatcher — payload shape, target lookup, handle_execute call."""

    def setup_method(self):
        self.handler = WorkflowExecutionHandler(sio=None)
        self.source = str(uuid.uuid4())
        self.target = str(uuid.uuid4())
        self.user = str(uuid.uuid4())
        self.on_error_id = "on-error-node-id"
        self.target_nodes = [
            {"id": "trigger-1", "type": "trigger-cron", "config": {}},
            {"id": "step-1", "type": "automation-slack", "config": {}},
            {"id": self.on_error_id, "type": "on-error", "config": {}},
            {"id": "step-2", "type": "automation-discord", "config": {}},
        ]
        self.target_edges = [
            {"id": "e1", "source": self.on_error_id, "target": "step-2"},
        ]

    def _patch_fetch(self, fetched):
        return patch.object(
            self.handler, "_fetch_workflow", AsyncMock(return_value=fetched)
        )

    @pytest.mark.asyncio
    async def test_injects_error_inputs_and_calls_handle_execute(self):
        fetched = (self.target_nodes, self.target_edges, "org-1", {}, {})
        seen_request = {}

        async def fake_handle_execute(sid, request, caller_user_id=None):
            seen_request["sid"] = sid
            seen_request["request"] = request
            seen_request["caller_user_id"] = caller_user_id
            return None

        with self._patch_fetch(fetched), \
             patch.object(self.handler, "handle_execute", side_effect=fake_handle_execute):
            await self.handler._dispatch_error_handler_workflow(
                target_workflow_id=self.target,
                source_workflow_id=self.source,
                source_execution_id="exec-src-1",
                user_id=self.user,
                error="boom",
                nodes_executed=4,
                duration=2.341,
            )

        request = seen_request["request"]
        assert request.workflow_id == self.target
        assert request.start_node_id == self.on_error_id
        assert request.trigger_source == "error_handler"
        assert seen_request["caller_user_id"] == self.user
        assert seen_request["sid"] == ""

        # On-error node carries the source run's error payload — workflow_id
        # and execution_id deliberately reference the SOURCE (that's what the
        # handler workflow needs to act on).
        on_error_payload = next(
            n["config"]["_error_inputs"]
            for n in request.nodes
            if n["id"] == self.on_error_id
        )
        assert on_error_payload == {
            "error": "boom",
            "workflow_id": self.source,
            "execution_id": "exec-src-1",
            "nodes_executed": 4,
            "duration": 2.34,
        }

        # Other nodes untouched.
        other = next(n for n in request.nodes if n["id"] == "step-1")
        assert "_error_inputs" not in other.get("config", {})

    @pytest.mark.asyncio
    async def test_no_on_error_node_is_silent_noop(self):
        nodes_without = [n for n in self.target_nodes if n["type"] != "on-error"]
        fetched = (nodes_without, [], "org-1", {}, {})
        with self._patch_fetch(fetched), \
             patch.object(self.handler, "handle_execute", new=AsyncMock()) as he:
            await self.handler._dispatch_error_handler_workflow(
                target_workflow_id=self.target,
                source_workflow_id=self.source,
                source_execution_id="exec-src-2",
                user_id=self.user,
                error="boom",
                nodes_executed=1,
                duration=0.5,
            )
            assert he.call_count == 0

    @pytest.mark.asyncio
    async def test_target_not_found_is_silent_noop(self):
        with self._patch_fetch(None), \
             patch.object(self.handler, "handle_execute", new=AsyncMock()) as he:
            await self.handler._dispatch_error_handler_workflow(
                target_workflow_id=self.target,
                source_workflow_id=self.source,
                source_execution_id="exec-src-3",
                user_id=self.user,
                error="boom",
                nodes_executed=0,
                duration=0.1,
            )
            assert he.call_count == 0

    @pytest.mark.asyncio
    async def test_handle_execute_failure_does_not_raise(self):
        # The dispatcher is fire-and-forget — a target-side crash must not
        # surface as an unhandled task exception in the source run's spawn.
        fetched = (self.target_nodes, self.target_edges, "org-1", {}, {})
        with self._patch_fetch(fetched), \
             patch.object(self.handler, "handle_execute",
                          side_effect=RuntimeError("target died")):
            await self.handler._dispatch_error_handler_workflow(
                target_workflow_id=self.target,
                source_workflow_id=self.source,
                source_execution_id="exec-src-4",
                user_id=self.user,
                error="boom",
                nodes_executed=0,
                duration=0.1,
            )
            # Reaching here without exception is the assertion.


class TestExplicitOnErrorStartSkipsExtraction:
    """When start_node_id targets an on-error node, the extractor must keep it
    in executable_nodes so it actually runs. Pure logic check on the snippet
    we modified."""

    def test_explicit_start_keeps_on_error_in_executable_nodes(self):
        # Mirror the guard in handle_execute.
        executable_nodes = [
            {"id": "trig", "type": "trigger-cron"},
            {"id": "oerr", "type": "on-error"},
            {"id": "next", "type": "automation-slack"},
        ]
        on_error_nodes = [n for n in executable_nodes if n["type"] == "on-error"]
        request = SimpleNamespace(start_node_id="oerr")
        explicit_on_error_start = bool(request.start_node_id) and any(
            n["id"] == request.start_node_id for n in on_error_nodes
        )
        assert explicit_on_error_start is True

    def test_other_start_still_extracts(self):
        executable_nodes = [
            {"id": "trig", "type": "trigger-cron"},
            {"id": "oerr", "type": "on-error"},
        ]
        on_error_nodes = [n for n in executable_nodes if n["type"] == "on-error"]
        request = SimpleNamespace(start_node_id="trig")
        explicit_on_error_start = bool(request.start_node_id) and any(
            n["id"] == request.start_node_id for n in on_error_nodes
        )
        assert explicit_on_error_start is False


# ---------------------------------------------------------------------------
# Integration tests — real Postgres. Catch the round-trip bugs the unit tests
# above skip: actual workflow row shape, settings JSONB merge, _fetch_workflow
# parsing a real `workflow` blob, and the settings → DB → dispatch loop.
# ---------------------------------------------------------------------------


_TEST_USER_ID = '00000000-0000-4000-8000-000000000099'


async def _ensure_user(real_database, user_id: str):
    await real_database.execute(
        """
        INSERT INTO auth.users (id, email)
        VALUES ($1, $2)
        ON CONFLICT (id) DO NOTHING
        """,
        user_id,
        f"err-routing-{user_id[:8]}@example.com",
    )


async def _insert_workflow(
    real_database,
    *,
    workflow_id: str,
    owner_id: str,
    nodes: list,
    edges: list,
    settings: dict,
):
    await real_database.execute(
        """
        INSERT INTO workflows (id, owner_id, name, description, workflow, permissions, settings, created_at, updated_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, NOW(), NOW())
        """,
        workflow_id,
        owner_id,
        f"err-routing-wf-{workflow_id[:8]}",
        "test",
        {"nodes": nodes, "edges": edges},
        {},
        settings,
    )


@pytest.mark.asyncio
class TestErrorRoutingRealDatabase(BaseHandlerTest):
    """Real-DB tests for the cross-workflow error routing pipeline."""

    def get_session_data(self, sid: str):
        return {
            'sid': sid,
            'user_id': _TEST_USER_ID,
            'email': 'err-routing@example.com',
        }

    async def test_dispatch_loads_target_from_real_db_and_injects_payload(
        self, real_database, sid
    ):
        """The dispatcher's only DB call is _fetch_workflow on the TARGET. This
        test plants a real row with the production JSONB shape, then asserts
        the dispatcher (a) parses it, (b) finds the on-error node, (c) injects
        _error_inputs with the SOURCE workflow's identifiers, and (d) calls
        handle_execute with start_node_id pointed at the on-error node."""
        await _ensure_user(real_database, _TEST_USER_ID)
        source_id = str(uuid.uuid4())
        target_id = str(uuid.uuid4())
        on_error_node_id = "real-db-on-error"

        target_nodes = [
            {"id": "real-db-trig", "type": "trigger-cron", "config": {}},
            {"id": on_error_node_id, "type": "on-error", "config": {}},
            {"id": "real-db-after", "type": "automation-slack",
             "config": {"message": "alert"}},
        ]
        target_edges = [
            {"id": "e1", "source": on_error_node_id, "target": "real-db-after"},
        ]
        await _insert_workflow(
            real_database,
            workflow_id=target_id,
            owner_id=_TEST_USER_ID,
            nodes=target_nodes,
            edges=target_edges,
            settings={},
        )

        handler = WorkflowExecutionHandler(sio=None)
        await handler.setup_user("")

        captured = {}

        async def fake_handle_execute(sid, request, caller_user_id=None):
            captured['request'] = request
            captured['caller_user_id'] = caller_user_id
            return None

        with patch.object(handler, 'handle_execute', side_effect=fake_handle_execute):
            await handler._dispatch_error_handler_workflow(
                target_workflow_id=target_id,
                source_workflow_id=source_id,
                source_execution_id="exec-src-integration",
                user_id=_TEST_USER_ID,
                error="explode",
                nodes_executed=7,
                duration=4.521,
            )

        request = captured['request']
        assert request.workflow_id == target_id
        assert request.start_node_id == on_error_node_id
        assert request.trigger_source == 'error_handler'
        assert captured['caller_user_id'] == _TEST_USER_ID

        on_error_payload = next(
            n['config']['_error_inputs']
            for n in request.nodes
            if n['id'] == on_error_node_id
        )
        assert on_error_payload == {
            'error': 'explode',
            'workflow_id': source_id,
            'execution_id': 'exec-src-integration',
            'nodes_executed': 7,
            'duration': 4.52,
        }

    async def test_dispatch_silent_noop_when_target_has_no_on_error_node(
        self, real_database, sid
    ):
        """A target without an on-error node is a config mistake — the source
        run shouldn't crash on it. handle_execute must not be called."""
        await _ensure_user(real_database, _TEST_USER_ID)
        source_id = str(uuid.uuid4())
        target_id = str(uuid.uuid4())
        await _insert_workflow(
            real_database,
            workflow_id=target_id,
            owner_id=_TEST_USER_ID,
            nodes=[{"id": "trig", "type": "trigger-cron", "config": {}}],
            edges=[],
            settings={},
        )

        handler = WorkflowExecutionHandler(sio=None)
        await handler.setup_user("")

        with patch.object(handler, 'handle_execute',
                          new=AsyncMock()) as he:
            await handler._dispatch_error_handler_workflow(
                target_workflow_id=target_id,
                source_workflow_id=source_id,
                source_execution_id="exec-src-1",
                user_id=_TEST_USER_ID,
                error="x",
                nodes_executed=0,
                duration=0.1,
            )
            assert he.call_count == 0

    async def test_dispatch_silent_noop_when_user_has_no_access(
        self, real_database, sid
    ):
        """check_resource_access gates _fetch_workflow. A user who doesn't own
        / share / collaborate on the target workflow can't trigger it as their
        error handler — the settings write should have prevented this, but the
        dispatcher is the last line of defense and must no-op cleanly."""
        await _ensure_user(real_database, _TEST_USER_ID)
        other_user = str(uuid.uuid4())
        await _ensure_user(real_database, other_user)
        source_id = str(uuid.uuid4())
        target_id = str(uuid.uuid4())
        await _insert_workflow(
            real_database,
            workflow_id=target_id,
            owner_id=other_user,
            nodes=[
                {"id": "oe", "type": "on-error", "config": {}},
            ],
            edges=[],
            settings={},
        )

        handler = WorkflowExecutionHandler(sio=None)
        await handler.setup_user("")

        with patch.object(handler, 'handle_execute',
                          new=AsyncMock()) as he:
            await handler._dispatch_error_handler_workflow(
                target_workflow_id=target_id,
                source_workflow_id=source_id,
                source_execution_id="exec-src-2",
                user_id=_TEST_USER_ID,
                error="x",
                nodes_executed=0,
                duration=0.1,
            )
            assert he.call_count == 0


@pytest.mark.asyncio
class TestErrorHandlerSettingPersists(BaseHandlerTest):
    """The frontend writes `settings.error_handler_workflow_id` via the
    workflow:update socket event. The settings column is a free JSONB merge,
    so this nominally works — but the contract bug (frontend renames the key,
    backend filters it out, Pydantic rejects it) only surfaces with a full
    round-trip."""

    def get_session_data(self, sid: str):
        return {
            'sid': sid,
            'user_id': _TEST_USER_ID,
            'email': 'err-routing@example.com',
        }

    async def test_error_handler_workflow_id_round_trips_through_workflow_update(
        self, real_database, frontend_sio, sid
    ):
        await _ensure_user(real_database, _TEST_USER_ID)
        workflow_id = str(uuid.uuid4())
        target_id = str(uuid.uuid4())
        await _insert_workflow(
            real_database,
            workflow_id=workflow_id,
            owner_id=_TEST_USER_ID,
            nodes=[],
            edges=[],
            settings={"min_required_credits": 5},
        )

        update = WorkflowUpdateRequest(
            event_name="workflow:update",
            request_id="set-err-handler",
            workflow_id=workflow_id,
            settings={
                "error_handler_workflow_id": target_id,
                "min_required_balance": None,
            },
        )
        await send_event(frontend_sio, sid, update)
        await asyncio.sleep(0.2)

        row = await real_database.fetchrow(
            "SELECT settings FROM workflows WHERE id = $1", workflow_id
        )
        assert row is not None
        settings = row['settings']
        if isinstance(settings, str):
            settings = json.loads(settings)
        # Merge semantics: new key landed, prior key preserved, explicit-null
        # legacy key wiped (matches what the dialog sends on every save).
        assert settings.get('error_handler_workflow_id') == target_id
        assert settings.get('min_required_credits') == 5
        assert 'min_required_balance' not in settings or settings.get('min_required_balance') is None

    async def test_clearing_error_handler_writes_null(
        self, real_database, frontend_sio, sid
    ):
        """Dialog sends `error_handler_workflow_id: null` to clear. The JSONB
        merge writes the null (it doesn't delete the key), which the dispatcher
        reads as 'no target' and skips — both behaviors must hold."""
        await _ensure_user(real_database, _TEST_USER_ID)
        workflow_id = str(uuid.uuid4())
        prior_target = str(uuid.uuid4())
        await _insert_workflow(
            real_database,
            workflow_id=workflow_id,
            owner_id=_TEST_USER_ID,
            nodes=[],
            edges=[],
            settings={"error_handler_workflow_id": prior_target},
        )

        update = WorkflowUpdateRequest(
            event_name="workflow:update",
            request_id="clear-err-handler",
            workflow_id=workflow_id,
            settings={"error_handler_workflow_id": None},
        )
        await send_event(frontend_sio, sid, update)
        await asyncio.sleep(0.2)

        row = await real_database.fetchrow(
            "SELECT settings FROM workflows WHERE id = $1", workflow_id
        )
        assert row is not None
        settings = row['settings']
        if isinstance(settings, str):
            settings = json.loads(settings)
        assert settings.get('error_handler_workflow_id') is None

        # And the dispatcher's gate treats null as no-target.
        handler = WorkflowExecutionHandler(sio=None)
        with patch("wss.handlers.workflow_execution_handler.spawn") as spawn:
            handler._maybe_dispatch_error_handler(
                SimpleNamespace(workflow_id=workflow_id, trigger_source='cron'),
                execution_id='ex',
                user_id=_TEST_USER_ID,
                error_msg='boom',
                nodes_executed=0,
                duration=0.0,
                workflow_settings=settings,
            )
            assert spawn.call_count == 0
