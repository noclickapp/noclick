"""Regression tests for the AI builder persisting its OWN graph mutations to
public.workflows at each turn boundary.

Root cause fixed: the agentic builder never wrote its graph to the DB — it left
persistence to the frontend, which does not save on an ``<ask/>`` pause. A
headless run that paused for input therefore left public.workflows at its
pre-edit state, so the resumed run rehydrated an *empty* graph and every node
lookup failed ("node 'X' not found"), and the brain re-built from scratch.

These pin:
  * GraphState.to_workflow_data() emits the persisted-blob shape and round-trips
    through from_dict() (the resumed run must see what the brain built).
  * _persist_builder_graph writes that blob via the repo, and skips safely when
    there's nothing to target / nothing built.
  * list_workflows searches by id when the query IS a workflow id (Bug B: the
    builder's recovery path passes a bare id and used to find nothing).
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from coder.workflow.graph_state import GraphState, NodeState, EdgeState
from repositories.workflow import WorkflowRepo


def _sample_graph() -> GraphState:
    """A small graph shaped like the incident: a trigger + agent + a
    bottom-handle tool-provider edge, with a credential and an operation."""
    g = GraphState()
    g.nodes['gmail_trigger'] = NodeState(
        id='gmail_trigger', type='automation-gmail', label='Gmail Trigger',
        goal='poll inbox', operation='poll_for_new_emails',
        config={'credentialIds': {'automation-gmail': 'cred-1'}},
        position={'x': 10, 'y': 20},
    )
    g.nodes['agent'] = NodeState(
        id='agent', type='agent', label='Support Agent', goal='reply',
        operation='default', config={'model': 'openrouter/x'},
        position={'x': 300, 'y': 20},
    )
    g.edges['e1'] = EdgeState(id='e1', source_id='gmail_trigger', target_id='agent')
    g.edges['e2'] = EdgeState(
        id='e2', source_id='gdocs', target_id='agent', target_handle='bottom',
    )
    return g


def test_to_workflow_data_roundtrips_through_from_dict():
    """The persisted blob must reload into an equivalent GraphState — otherwise
    the resumed run sees a different graph than the brain built."""
    g = _sample_graph()
    blob = g.to_workflow_data()

    # DB-blob shape: edges keyed source/target (NOT sourceId), metadata flattened
    # into config — the shape the canvas + execution engine + from_dict expect.
    assert blob['edges'][0]['source'] == 'gmail_trigger'
    assert blob['edges'][0]['target'] == 'agent'
    assert 'sourceId' not in blob['edges'][0]
    node = blob['nodes'][0]
    assert node['config']['operation'] == 'poll_for_new_emails'
    assert node['config']['label'] == 'Gmail Trigger'
    assert node['position'] == {'x': 10, 'y': 20}

    g2 = GraphState.from_dict(blob)
    assert set(g2.nodes) == {'gmail_trigger', 'agent'}
    n = g2.get_node('gmail_trigger')
    assert n.operation == 'poll_for_new_emails'
    assert n.label == 'Gmail Trigger'
    assert n.config['credentialIds'] == {'automation-gmail': 'cred-1'}
    assert n.position == {'x': 10, 'y': 20}
    # metadata must not double-live in config after reload
    assert 'operation' not in n.config and 'label' not in n.config
    # tool-provider edge handle survives (provider_dataflow_conflict depends on it)
    assert ('gdocs', 'agent') in g2.edge_set
    be = next(e for e in g2.edges.values() if (e.source_id, e.target_id) == ('gdocs', 'agent'))
    assert be.target_handle == 'bottom'


def test_to_workflow_data_defaults_missing_position():
    """A node without a stamped position serializes with a concrete position so
    the canvas never reads `.x` off undefined (the FE crash class)."""
    g = GraphState()
    g.nodes['n'] = NodeState(id='n', type='agent', label='A', goal='')
    blob = g.to_workflow_data()
    assert blob['nodes'][0]['position'] == {'x': 0, 'y': 0}


def _handler_with_captured_save(monkeypatch):
    from wss.handlers.workflow_builder_handler import WorkflowBuilderHandler

    handler = WorkflowBuilderHandler(MagicMock())
    conn = MagicMock()
    # The persist path pre-reads the stored blob to carry credentialIds
    # forward; default to "no existing row" unless a test overrides it.
    conn.fetchrow = AsyncMock(return_value=None)
    pool = MagicMock(acquire=MagicMock(return_value=MagicMock(
        __aenter__=AsyncMock(return_value=conn), __aexit__=AsyncMock(return_value=False),
    )))
    handler.get_pool = AsyncMock(return_value=pool)
    save = AsyncMock(return_value={'id': 'wf'})
    repo = MagicMock(update_workflow_dynamic=save)
    monkeypatch.setattr(
        'wss.handlers.workflow_builder_handler.WorkflowRepo', lambda _pool: repo,
    )
    return handler, save


@pytest.mark.asyncio
async def test_persist_builder_graph_writes_serialized_graph(monkeypatch):
    """The heart of the fix: a paused/finished builder turn writes its full graph
    to public.workflows so the resumed run reads it back."""
    handler, save = _handler_with_captured_save(monkeypatch)
    wf_id = str(uuid.uuid4())
    request = SimpleNamespace(user_context={'workflow_id': wf_id})
    builder = SimpleNamespace(graph_state=_sample_graph())

    await handler._persist_builder_graph(request, builder, 'owner-1')

    assert save.await_count == 1
    args, kwargs = save.await_args
    assert args[1] == uuid.UUID(wf_id)
    assert kwargs['workflow_data'] == builder.graph_state.to_workflow_data()
    assert {n['id'] for n in kwargs['workflow_data']['nodes']} == {'gmail_trigger', 'agent'}


@pytest.mark.asyncio
async def test_persist_builder_graph_skips_without_workflow_or_when_empty(monkeypatch):
    """Never write when there's no workflow to target or nothing was built — an
    empty write would clobber an existing workflow's graph."""
    handler, save = _handler_with_captured_save(monkeypatch)

    # No workflow_id (start-without-workflow flow before one is opened).
    await handler._persist_builder_graph(
        SimpleNamespace(user_context={}),
        SimpleNamespace(graph_state=_sample_graph()), 'owner-1',
    )
    assert save.await_count == 0

    # Empty graph (a pure <list_workflows>/<open_workflow> turn).
    await handler._persist_builder_graph(
        SimpleNamespace(user_context={'workflow_id': str(uuid.uuid4())}),
        SimpleNamespace(graph_state=GraphState()), 'owner-1',
    )
    assert save.await_count == 0


@pytest.mark.asyncio
async def test_persist_builder_graph_swallows_db_errors(monkeypatch):
    """Persistence is best-effort: a DB failure is logged, not raised, so it
    can't abort the turn's conversation finalization (the resume anchor)."""
    handler, save = _handler_with_captured_save(monkeypatch)
    save.side_effect = RuntimeError("db down")
    # Must not raise.
    await handler._persist_builder_graph(
        SimpleNamespace(user_context={'workflow_id': str(uuid.uuid4())}),
        SimpleNamespace(graph_state=_sample_graph()), 'owner-1',
    )


@pytest.mark.asyncio
async def test_list_workflows_builder_matches_by_id(monkeypatch):
    """Bug B: a query that IS a workflow id must add an id clause + bind the
    parsed UUID, so the builder's recovery `<list_workflows query="<id>">`
    finds the workflow even when its name doesn't match."""
    repo = WorkflowRepo(MagicMock())
    fake_conn = MagicMock(fetch=AsyncMock(return_value=[]))
    wf_id = uuid.uuid4()

    await repo.list_workflows_builder(
        fake_conn, user_id=uuid.uuid4(), organization_id=None,
        query=str(wf_id), limit=10,
    )
    sql = fake_conn.fetch.await_args.args[0]
    params = list(fake_conn.fetch.await_args.args[1:])
    assert 'w.id = $' in sql
    assert wf_id in params

    # A non-UUID query keeps the name/description-only search (no id clause).
    fake_conn.fetch.reset_mock()
    await repo.list_workflows_builder(
        fake_conn, user_id=uuid.uuid4(), organization_id=None,
        query='my cool workflow', limit=10,
    )
    assert 'w.id = $' not in fake_conn.fetch.await_args.args[0]


@pytest.mark.asyncio
async def test_list_workflows_mcp_matches_by_id():
    """Bug B, MCP surface: the external server's list_workflows had the same
    id-blind gap."""
    repo = WorkflowRepo(MagicMock())
    fake_conn = MagicMock(fetch=AsyncMock(return_value=[]))
    wf_id = uuid.uuid4()

    await repo.list_workflows_mcp(
        fake_conn, user_id=str(uuid.uuid4()), query=str(wf_id),
        folder_id=None, limit=10,
    )
    sql = fake_conn.fetch.await_args.args[0]
    params = list(fake_conn.fetch.await_args.args[1:])
    assert 'id = $' in sql
    assert wf_id in params


# ── Whole-blob persist must be LOSSLESS (2026-08-02) ────────────────────────
#
# _persist_builder_graph writes the WHOLE workflow blob, unconditionally and
# server-side, at every turn boundary. So any field to_workflow_data() fails to
# emit is silently REVERTED on each turn — the FE's next save re-adds it, and
# the audit trail shows the same "∅ → value" transition over and over (three
# times in one session before this was caught). Worse, the same whole-blob
# write is what propagated a credential-less canvas snapshot to the DB and
# un-attached a user's working WhatsApp credential 40s after he confirmed it
# worked.


def _fe_saved_node() -> dict:
    """A node in the exact shape the FE's buildSaveConfig persists: every
    top-level datum flattened into `config`."""
    return {
        "id": "whatsapp",
        "type": "automation-whatsapp",
        "position": {"x": 190, "y": 307},
        "config": {
            "label": "WhatsApp Messaging",
            "goal": "Provide WhatsApp messaging actions",
            "content": "WhatsApp Messaging",
            "operationReason": "Provides send/lookup actions to the agent",
            "userFields": ["to"],
            "credentialIds": {"whatsapp_qr": "e564b06a-616e-4ec5-aec9-aaeccd35ff11"},
            "agent_tool_operations": ["send_text_message"],
        },
    }


def test_persisted_blob_preserves_every_fe_saved_field():
    out = GraphState.from_dict({"nodes": [_fe_saved_node()], "edges": []}).to_workflow_data()
    before = _fe_saved_node()["config"]
    after = out["nodes"][0]["config"]
    missing = {k: before[k] for k in before if k not in after}
    assert not missing, f"whole-blob persist drops FE-saved fields: {sorted(missing)}"
    for key, value in before.items():
        assert after[key] == value, f"{key} changed on round-trip"


def test_credentials_survive_the_builder_blob_write():
    """The load-bearing one: a turn that touches nothing must not un-attach a
    credential the user connected."""
    out = GraphState.from_dict({"nodes": [_fe_saved_node()], "edges": []}).to_workflow_data()
    assert out["nodes"][0]["config"]["credentialIds"] == {
        "whatsapp_qr": "e564b06a-616e-4ec5-aec9-aaeccd35ff11"
    }


def test_repeated_round_trips_are_stable():
    """No ∅→value ping-pong: persisting an already-persisted blob is a no-op,
    so the builder and the FE stop fighting over the same node."""
    once = GraphState.from_dict({"nodes": [_fe_saved_node()], "edges": []}).to_workflow_data()
    twice = GraphState.from_dict(once).to_workflow_data()
    assert once == twice


# ── The whole-blob write must never UN-ATTACH a credential ──────────────────
#
# _persist_builder_graph writes unconditionally from a CLIENT-supplied graph.
# When that client's canvas had lost a credential, the write deleted a working
# credential from the DB (2026-08-02: connected WhatsApp, confirmed working at
# 12:53:55, un-attached by the next turn's persist at 12:54:37). The exact
# client-side path that dropped it was never pinned down — so the guard lives
# at the choke point every builder turn goes through, making the outcome
# robust to whichever mechanism empties the snapshot.

from coder.workflow.workflow_ops import preserve_existing_credentials

_CREDS = {"whatsapp_qr": "e564b06a-616e-4ec5-aec9-aaeccd35ff11"}


def test_stored_credentials_survive_a_credential_less_client_graph():
    """The incident, reduced: the DB has the credential, the incoming graph
    doesn't, and the write must NOT delete it."""
    incoming = [{"id": "whatsapp", "config": {"agent_tool_operations": ["send_text_message"]}}]
    stored = [{"id": "whatsapp", "config": {"credentialIds": dict(_CREDS)}}]
    preserve_existing_credentials(incoming, stored)
    assert incoming[0]["config"]["credentialIds"] == _CREDS


def test_incoming_credential_wins_over_stored():
    """A genuine <set_credentials> must still be able to CHANGE a credential."""
    incoming = [{"id": "n", "config": {"credentialIds": {"whatsapp_qr": "new-id"}}}]
    stored = [{"id": "n", "config": {"credentialIds": {"whatsapp_qr": "old-id"}}}]
    preserve_existing_credentials(incoming, stored)
    assert incoming[0]["config"]["credentialIds"] == {"whatsapp_qr": "new-id"}


def test_merges_per_provider_without_clobbering_siblings():
    incoming = [{"id": "n", "config": {"credentialIds": {"slack": "s1"}}}]
    stored = [{"id": "n", "config": {"credentialIds": {"whatsapp_qr": "w1"}}}]
    preserve_existing_credentials(incoming, stored)
    assert incoming[0]["config"]["credentialIds"] == {"whatsapp_qr": "w1", "slack": "s1"}


def test_untouched_when_nothing_stored_or_node_is_new():
    incoming = [{"id": "brand-new", "config": {"x": 1}}]
    preserve_existing_credentials(incoming, [{"id": "other", "config": {"credentialIds": _CREDS}}])
    assert "credentialIds" not in incoming[0]["config"]
    # Empty/garbage inputs are no-ops, never raises.
    preserve_existing_credentials([], [])
    preserve_existing_credentials([{"no_id": True}], [{"id": "n", "config": {}}])


def test_guard_composes_with_the_blob_serializer():
    """End-to-end at the persist boundary: a graph_state built from a
    credential-less client snapshot still persists the stored credential."""
    client_graph = {"nodes": [{
        "id": "whatsapp", "type": "automation-whatsapp", "position": {"x": 0, "y": 0},
        "config": {"label": "WhatsApp Messaging", "goal": "g"},
    }], "edges": []}
    blob = GraphState.from_dict(client_graph).to_workflow_data()
    assert "credentialIds" not in blob["nodes"][0]["config"]  # the bug's input

    stored = [{"id": "whatsapp", "config": {"credentialIds": dict(_CREDS)}}]
    preserve_existing_credentials(blob["nodes"], stored)
    assert blob["nodes"][0]["config"]["credentialIds"] == _CREDS


@pytest.mark.asyncio
async def test_persist_carries_stored_credentials_through_the_real_path(monkeypatch):
    """Integration at the choke point: the builder's graph has no credential,
    the DB does, and what gets WRITTEN keeps it."""
    handler, save = _handler_with_captured_save(monkeypatch)
    wf_id = str(uuid.uuid4())

    gs = GraphState()
    gs.nodes['whatsapp'] = NodeState(
        id='whatsapp', type='automation-whatsapp', label='WhatsApp Messaging',
        goal='g', operation=None, config={'agent_tool_operations': ['send_text_message']},
    )
    # The DB row still holds the credential the user connected.
    handler.get_pool.return_value.acquire.return_value.__aenter__.return_value.fetchrow = \
        AsyncMock(return_value={'workflow': {'nodes': [
            {'id': 'whatsapp', 'config': {'credentialIds': dict(_CREDS)}}
        ]}})

    await handler._persist_builder_graph(
        SimpleNamespace(user_context={'workflow_id': wf_id}),
        SimpleNamespace(graph_state=gs), 'owner-1',
    )

    assert save.await_count == 1
    written = save.await_args.kwargs['workflow_data']['nodes'][0]['config']
    assert written['credentialIds'] == _CREDS, "persist un-attached a stored credential"


@pytest.mark.asyncio
async def test_persist_still_writes_when_the_preread_fails(monkeypatch):
    """The guard is best-effort: a failed pre-read must not block persistence,
    or resume-after-ask breaks (the bug this method exists to fix)."""
    handler, save = _handler_with_captured_save(monkeypatch)
    handler.get_pool.return_value.acquire.return_value.__aenter__.return_value.fetchrow = \
        AsyncMock(side_effect=RuntimeError("db blip"))

    await handler._persist_builder_graph(
        SimpleNamespace(user_context={'workflow_id': str(uuid.uuid4())}),
        SimpleNamespace(graph_state=_sample_graph()), 'owner-1',
    )
    assert save.await_count == 1
