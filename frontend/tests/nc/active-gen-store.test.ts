// Unit test for the activeGenStore — the FE's source of truth for
// in-flight builder runs.
//
// The store has one job: consume the per-event wire contract (active_gen:*
// frames) and project the user's active runs into a Valtio proxy that
// hooks can read. This test drives synthetic events through the same
// onSocketEvent dispatch path the real socket-receiver uses, and asserts
// the projected state at each step.
//
// Why this matters: every restoration bug we fixed in this PR landed
// because the FE store had multiple writers and ambiguous state
// transitions. The new store has ONE writer (the socket listener) and
// FIVE event types, each with a deterministic projection. If this test
// passes, the store's contract is sound — bugs from here on are
// integration concerns, not state-machine concerns.
//
// Run: mcp__nc__nc_run_test({ file: "tests/nc/active-gen-store.test.ts" })

import { nc } from '~/lib/nc';
import { socketReceiver } from '~/lib/socket-receiver';
import {
    activeGenStore,
    activeGensForWorkflow,
    takeCommittedPatch,
} from '~/lib/activeGenStore';

// Drive the same dispatch path the receiver uses for real frames.
function dispatch(event: string, data: any) {
    (socketReceiver as any).handleEvent(event, [data]);
}

function reset() {
    activeGenStore.gens = {};
    activeGenStore.byWorkflow = {};
    activeGenStore.lastCommitted = {};
}

export default async function () {
    const out: Record<string, unknown> = {};
    reset();

    // ── started → register a gen ─────────────────────────────────────────
    dispatch('active_gen:started', {
        gen_id: 'g1',
        workflow_id: 'w1',
        conversation_id: 'c1',
        prompt: 'build slack bot',
        started_at: 100,
    });
    nc.assert.equal(Object.keys(activeGenStore.gens).length, 1, 'started adds one gen');
    nc.assert.equal(activeGenStore.byWorkflow['w1']?.length, 1, 'started indexes by workflow');
    nc.assert.equal(activeGensForWorkflow('w1')[0]?.gen_id, 'g1', 'lookup by workflow returns g1');

    // ── text_chunk → append to text ─────────────────────────────────────
    dispatch('active_gen:text_chunk', { gen_id: 'g1', delta: 'Hello ' });
    dispatch('active_gen:text_chunk', { gen_id: 'g1', delta: 'world' });
    nc.assert.equal(activeGenStore.gens['g1'].text, 'Hello world', 'text deltas concatenate in order');

    // ── status → update render-only field ────────────────────────────────
    dispatch('active_gen:status', { gen_id: 'g1', status: 'Modifying workflow' });
    nc.assert.equal(activeGenStore.gens['g1'].status, 'Modifying workflow', 'status field updated');

    // ── edit_step → append, dedupe consecutive ──────────────────────────
    dispatch('active_gen:edit_step', { gen_id: 'g1', step: 'Modifying workflow' });
    dispatch('active_gen:edit_step', { gen_id: 'g1', step: 'Modifying workflow' }); // dedupe
    dispatch('active_gen:edit_step', { gen_id: 'g1', step: 'Thinking' });
    nc.assert.deepEqual(
        activeGenStore.gens['g1'].edit_steps,
        ['Modifying workflow', 'Thinking'],
        'consecutive duplicate steps deduped',
    );

    // ── graph_event → append to events ──────────────────────────────────
    dispatch('active_gen:graph_event', {
        gen_id: 'g1',
        event: { type: 'node_added', nodeType: 'automation-slack', nodeLabel: 'Slack' },
    });
    nc.assert.equal(activeGenStore.gens['g1'].events.length, 1, 'graph_event appended');
    nc.assert.equal(
        (activeGenStore.gens['g1'].events[0] as any).type, 'node_added',
        'graph_event payload preserved',
    );

    // ── multi-gen on same workflow (multi-agent future) ─────────────────
    dispatch('active_gen:started', {
        gen_id: 'g2',
        workflow_id: 'w1',
        conversation_id: 'c1',
        prompt: 'parallel agent',
        started_at: 200,
    });
    nc.assert.equal(activeGensForWorkflow('w1').length, 2, 'multiple gens per workflow supported');
    nc.assert.deepEqual(
        activeGensForWorkflow('w1').map(g => g.gen_id),
        ['g1', 'g2'],
        'gens ordered by started_at',
    );

    // ── delta for unknown gen → silently dropped ────────────────────────
    dispatch('active_gen:text_chunk', { gen_id: 'unknown', delta: 'oops' });
    // Nothing to assert beyond "no crash, no spurious gen registered"
    nc.assert.equal(activeGenStore.gens['unknown'], undefined, 'unknown gen not auto-created');

    // ── terminal → drop gen, stash committed patch ──────────────────────
    const committedShape = [
        { role: 'user', message: 'build slack bot' },
        { role: 'assistant', message: '', edit_segments: [{ type: 'text', text: 'done' }] },
    ];
    dispatch('active_gen:terminal', {
        gen_id: 'g1',
        outcome: 'complete',
        committed_conversation_id: 'c1',
        committed_messages: committedShape,
    });
    nc.assert.equal(activeGenStore.gens['g1'], undefined, 'terminal evicts gen');
    nc.assert.equal(activeGensForWorkflow('w1').length, 1, 'workflow index reflects eviction');
    nc.assert.equal(activeGensForWorkflow('w1')[0]?.gen_id, 'g2', 'remaining gen still indexed');

    const patch = takeCommittedPatch('c1');
    nc.assert.equal(patch?.length, 2, 'committed patch retrievable');
    nc.assert.equal(takeCommittedPatch('c1'), null, 'patch is read-once');

    // ── snapshot replaces the local store wholesale ─────────────────────
    dispatch('active_gen:snapshot', {
        gens: [
            {
                gen_id: 'g99',
                workflow_id: 'w99',
                conversation_id: 'c99',
                prompt: 'from relay',
                started_at: 1000,
                text: 'snapshot text',
                events: [],
                edit_steps: ['from-do'],
                status: 'streaming',
            },
        ],
    });
    nc.assert.equal(Object.keys(activeGenStore.gens).length, 1, 'snapshot replaces existing gens');
    nc.assert.equal(activeGenStore.gens['g99']?.text, 'snapshot text', 'snapshot data preserved');
    nc.assert.equal(activeGensForWorkflow('w1').length, 0, 'snapshot clears stale workflow index');
    nc.assert.equal(activeGensForWorkflow('w99')[0]?.gen_id, 'g99', 'snapshot rebuilds index');

    // Cleanup so the test doesn't leave the live UI staring at synthetic state.
    reset();
    out.allChecksPassed = true;
    return out;
}
