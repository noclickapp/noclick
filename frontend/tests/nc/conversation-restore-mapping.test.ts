// Unit tests for the persisted-message → frontend Message mapper.
//
// Pinning the mapping in isolation matters because two restore paths use it
// (useSidebarConversation auto-restore + ChatHistory dropdown click) and
// historically each one drifted: editSteps was added to the dropdown path
// but missed on auto-restore; cancelled→wasInterrupted lived only in the
// dropdown path; agenticSteps casing diverged between the two; etc. With
// the mapping centralized in conversationRestoreMapping.ts these bugs can
// only happen in one place — and these tests catch any future drift.
//
// Run with: mcp__nc__nc_run_test({ file: "tests/nc/conversation-restore-mapping.test.ts" })

import { nc } from '~/lib/nc';
import {
    mapPersistedMessage,
    mapPersistedMessages,
    type PersistedMessage,
} from '~/hooks/conversationRestoreMapping';

export default async function () {
    const out: Record<string, unknown> = {};

    // ── User message round-trip ────────────────────────────────────────────
    const user: PersistedMessage = { role: 'user', message: 'hi there' };
    const userMapped = mapPersistedMessage(user);
    nc.assert.equal(userMapped.text, 'hi there', 'user.text');
    nc.assert.equal(userMapped.isUser, true, 'user.isUser');
    nc.assert.equal(userMapped.isComplete, true, 'user.isComplete');
    nc.assert.equal(userMapped.wasInterrupted, undefined, 'user has no wasInterrupted');
    out.userMapped = userMapped;

    // ── Completed assistant ────────────────────────────────────────────────
    const completed: PersistedMessage = {
        role: 'assistant',
        message: '',
        edit_segments: [
            { type: 'text', text: 'Done!' },
            { type: 'events', events: [
                { id: 'node-added-1', type: 'node_added', nodeType: 'automation-slack', nodeLabel: 'Slack', status: 'completed', timestamp: 100 },
            ] },
        ],
        edit_steps: ['Modifying workflow', 'Thinking'],
    };
    const completedMapped = mapPersistedMessage(completed);
    nc.assert.equal(completedMapped.isUser, false, 'completed.isUser');
    nc.assert.equal(completedMapped.isComplete, true, 'completed.isComplete');
    nc.assert.equal(completedMapped.wasInterrupted, undefined, 'completed: no wasInterrupted');
    nc.assert.equal(completedMapped.editSteps?.length, 2, 'completed.editSteps');
    nc.assert.equal(completedMapped.editSegments?.length, 2, 'completed.editSegments');
    nc.assert.equal(
        (completedMapped.editSegments?.[1] as any).events[0].nodeType,
        'automation-slack',
        'completed: nodeType survives',
    );

    // ── Cancelled — wasInterrupted set ─────────────────────────────────────
    const cancelled: PersistedMessage = {
        role: 'assistant', message: '', cancelled: true,
        edit_segments: [{ type: 'text', text: 'partial' }],
    };
    nc.assert.equal(
        mapPersistedMessage(cancelled).wasInterrupted, true,
        'cancelled.wasInterrupted',
    );

    // ── Paused on <ask/> — must NOT set wasInterrupted, BUT pendingAsk set ──
    const paused: PersistedMessage = {
        role: 'assistant', message: '', edit_segments: [],
        pending_ask: { ask_id: 'a1', title: null, inputs: [{ id: 'x', type: 'credential' }] },
    };
    const pausedMapped = mapPersistedMessage(paused);
    nc.assert.equal(
        pausedMapped.wasInterrupted, undefined,
        'paused must NOT set wasInterrupted (the run is awaiting input, not aborted)',
    );
    nc.assert.equal(
        pausedMapped.pendingAsk?.ask_id, 'a1',
        'paused: pendingAsk surfaced for BuilderInputBridge',
    );

    // ── agenticSteps: snake_case AND camelCase both supported ──────────────
    const snakeAgentic = mapPersistedMessage({
        role: 'assistant',
        agentic_steps: [{ id: 's1', text: 'looking', status: 'completed' } as any],
    });
    nc.assert.equal(snakeAgentic.agenticSteps?.length, 1, 'snake_case agentic_steps');
    const camelAgentic = mapPersistedMessage({
        role: 'assistant',
        agenticSteps: [{ id: 's2', text: 'thinking', status: 'completed' } as any],
    });
    nc.assert.equal(camelAgentic.agenticSteps?.length, 1, 'camelCase agenticSteps');

    // ── Empty message defaults to '' (not undefined) ───────────────────────
    nc.assert.equal(mapPersistedMessage({ role: 'assistant' }).text, '', 'missing message → ""');

    // ── Bulk mapper handles undefined / empty arrays ───────────────────────
    nc.assert.equal(mapPersistedMessages(undefined).length, 0, 'undefined input → []');
    nc.assert.equal(mapPersistedMessages([]).length, 0, 'empty input → []');
    nc.assert.equal(mapPersistedMessages([user, completed]).length, 2, 'bulk mapper count');

    // ── Multi-turn round-trip preserves order ──────────────────────────────
    const multi = mapPersistedMessages([
        { role: 'user', message: 'first' },
        { role: 'assistant', message: '', edit_segments: [{ type: 'text', text: 'a' }] },
        { role: 'user', message: 'second' },
        {
            role: 'assistant', message: '',
            edit_segments: [{ type: 'text', text: 'b' }],
            pending_ask: { ask_id: 'a2', title: null, inputs: [] },
        },
    ]);
    nc.assert.equal(multi.length, 4, 'multi-turn count');
    nc.assert.equal(multi[0].text, 'first', 'multi[0]');
    nc.assert.equal(multi[3].wasInterrupted, undefined, 'multi[3] paused: no wasInterrupted');
    nc.assert.equal(multi[3].pendingAsk?.ask_id, 'a2', 'multi[3] pendingAsk');

    out.allChecksPassed = true;
    return out;
}
