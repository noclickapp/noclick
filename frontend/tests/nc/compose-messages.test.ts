// Pure-function test of composeMessages — the rendering projection
// from (persisted history + active gens) → Message[].
//
// All chat rendering bugs in this PR boiled down to coherence between
// these two state classes. By making the composition pure and tested,
// the entire "what does the chat show right now" question reduces to
// "what's in persisted, what's in active." Both are inspectable.

import { nc } from '~/lib/nc';
import { composeMessages } from '~/lib/composeMessages';
import type { ActiveGeneration } from '~/lib/activeGenStore';
import type { PersistedMessage } from '~/hooks/conversationRestoreMapping';

function gen(id: string, overrides: Partial<ActiveGeneration> = {}): ActiveGeneration {
    return {
        gen_id: id,
        workflow_id: 'w1',
        conversation_id: 'c1',
        prompt: `prompt for ${id}`,
        started_at: 100,
        text: '',
        events: [],
        edit_steps: [],
        status: '',
        lastEventAt: 100,
        ...overrides,
    };
}

export default async function () {
    // ── empty + empty → empty (caller substitutes the welcome bubble) ──
    nc.assert.equal(composeMessages([], []).length, 0, 'empty inputs → empty output');

    // ── persisted only → mapped through mapPersistedMessages ──────────
    const persisted: PersistedMessage[] = [
        { role: 'user', message: 'first turn' },
        { role: 'assistant', message: '', edit_segments: [{ type: 'text', text: 'done' }] },
    ];
    const persistedOnly = composeMessages(persisted, []);
    nc.assert.equal(persistedOnly.length, 2, 'persisted prefix preserved');
    nc.assert.equal(persistedOnly[0].text, 'first turn', 'persisted user mapped');
    nc.assert.equal(persistedOnly[1].isUser, false, 'persisted assistant mapped');

    // ── active gen with text only → user + in-flight assistant bubble ──
    const streaming = composeMessages([], [
        gen('g1', { prompt: 'hi', text: 'Hello world' }),
    ]);
    nc.assert.equal(streaming.length, 2, 'one gen → two bubbles');
    nc.assert.equal(streaming[0].text, 'hi', 'user bubble carries prompt');
    nc.assert.equal(streaming[0].isUser, true, 'user bubble flagged');
    nc.assert.equal(streaming[1].isUser, false, 'assistant bubble flagged');
    nc.assert.equal(streaming[1].isComplete, false, 'in-flight: isComplete=false');
    nc.assert.equal(streaming[1].editSegments?.length, 1, 'text segment created');
    nc.assert.equal(
        (streaming[1].editSegments?.[0] as any).text, 'Hello world',
        'text accumulator surfaced as text segment',
    );

    // ── active gen with events → events segment populated ─────────────
    const withEvents = composeMessages([], [
        gen('g2', {
            prompt: 'add slack',
            events: [
                { type: 'node_added', nodeType: 'automation-slack', nodeLabel: 'Slack' },
                { type: 'node_updated', nodeId: 'slack_send' },
            ],
        }),
    ]);
    const eventsSeg: any = withEvents[1].editSegments?.[0];
    nc.assert.equal(eventsSeg?.type, 'events', 'no text → first segment is events');
    nc.assert.equal(eventsSeg?.events?.length, 2, 'all graph events surfaced');

    // ── text + events → both segments, in order ───────────────────────
    const both = composeMessages([], [
        gen('g3', {
            prompt: 'mix',
            text: 'thinking...',
            events: [{ type: 'node_added', nodeType: 'automation-slack' }],
        }),
    ]);
    const segs = both[1].editSegments;
    nc.assert.equal(segs?.length, 2, 'text + events → 2 segments');
    nc.assert.equal((segs?.[0] as any).type, 'text', 'text segment first');
    nc.assert.equal((segs?.[1] as any).type, 'events', 'events segment second');

    // ── edit_steps + status surface on the in-flight bubble ───────────
    const withSteps = composeMessages([], [
        gen('g4', {
            prompt: 'reasoning',
            edit_steps: ['Modifying workflow', 'Thinking'],
            status: 'Thinking',
        }),
    ]);
    nc.assert.equal(withSteps[1].editSteps?.length, 2, 'edit_steps surfaced');
    nc.assert.equal(withSteps[1].editStatus, 'Thinking', 'status surfaced as editStatus');

    // ── persisted + active → prefix + in-flight at the tail ───────────
    const layered = composeMessages(persisted, [
        gen('g5', { prompt: 'follow-up', text: 'streaming...' }),
    ]);
    nc.assert.equal(layered.length, 4, 'persisted prefix + in-flight pair');
    nc.assert.equal(layered[0].text, 'first turn', 'persisted prefix preserved');
    nc.assert.equal(layered[2].text, 'follow-up', 'in-flight user follows persisted');
    nc.assert.equal(layered[3].isComplete, false, 'in-flight assistant at tail');

    // ── multi-agent: two concurrent gens, each gets its own pair ──────
    const multiAgent = composeMessages([], [
        gen('g6', { prompt: 'agent A', text: 'A working...' }),
        gen('g7', { prompt: 'agent B', text: 'B working...' }),
    ]);
    nc.assert.equal(multiAgent.length, 4, 'two gens → four bubbles');
    nc.assert.equal(multiAgent[0].text, 'agent A', 'first gen first');
    nc.assert.equal(multiAgent[2].text, 'agent B', 'second gen second');
    nc.assert.equal(multiAgent[1].generationId, 'g6', 'in-flight bubble tagged with gen_id');
    nc.assert.equal(multiAgent[3].generationId, 'g7', 'second in-flight bubble tagged');

    // ── resume gen (prompt='') → EXTEND trailing assistant in place ──
    // Skip All / credential submit produces this. The prior turn's
    // segments + steps must remain visible while new content streams
    // into the SAME bubble — not a separate one below.
    const resumePersisted: PersistedMessage[] = [
        { role: 'user', message: 'connect slack' },
        {
            role: 'assistant', message: '',
            edit_segments: [
                { type: 'text', text: 'starting work' },
                { type: 'events', events: [{ id: 'node-added-1', type: 'node_added', nodeType: 'automation-slack', nodeLabel: 'Slack', status: 'completed', timestamp: 100 }] },
            ],
            edit_steps: ['Modifying workflow'],
            pending_ask: { ask_id: 'a1', title: null, inputs: [] },
        },
    ];
    const resumed = composeMessages(resumePersisted, [
        gen('g_resume', {
            prompt: '',
            text: 'continuing without it',
            edit_steps: ['Thinking after skip'],
        }),
    ]);
    nc.assert.equal(resumed.length, 2, 'resume gen extends in place — same bubble count');
    nc.assert.equal(resumed[0].text, 'connect slack', 'persisted user preserved');
    nc.assert.equal(resumed[1].isUser, false, 'still only one assistant bubble');
    nc.assert.equal(resumed[1].isComplete, false, 'extended bubble flips to in-flight');
    nc.assert.equal(resumed[1].pendingAsk, undefined, 'pendingAsk cleared on resume');
    nc.assert.equal(resumed[1].editSegments?.length, 3, 'prior segments kept + new text appended');
    nc.assert.equal(
        (resumed[1].editSegments?.[0] as any).text, 'starting work',
        'first segment is prior text',
    );
    nc.assert.equal(
        (resumed[1].editSegments?.[2] as any).text, 'continuing without it',
        'last segment is resume text',
    );
    nc.assert.deepEqual(
        resumed[1].editSteps,
        ['Modifying workflow', 'Thinking after skip'],
        'edit_steps concatenated in order',
    );
    nc.assert.equal(resumed[1].generationId, 'g_resume', 'extended bubble tagged with resume gen_id');

    // ── defensive dedupe: persisted tail matches active prompt → skip user dup ──
    // (Currently the BE doesn't double-stamp, but the guard is cheap.)
    const trailingUser: PersistedMessage[] = [
        { role: 'user', message: 'duplicate prompt' },
    ];
    const deduped = composeMessages(trailingUser, [
        gen('g8', { prompt: 'duplicate prompt', text: 'no dupe' }),
    ]);
    nc.assert.equal(deduped.length, 2, 'duplicate user dropped, only assistant added');
    nc.assert.equal(deduped[0].text, 'duplicate prompt', 'persisted user kept');
    nc.assert.equal(deduped[1].isUser, false, 'in-flight assistant only');

    return { allChecksPassed: true };
}
