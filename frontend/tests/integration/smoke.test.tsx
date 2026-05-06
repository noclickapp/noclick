// Smoke test for the integration harness. If this passes, the
// MockSocket + renderChat plumbing is wired correctly and the more
// elaborate scenario tests can rely on it.
//
// What it verifies:
//  - WorkflowProvider sets currentWorkflowId so useActiveWorkflowEditorId
//    sees it (via the chat, which derives isStreaming from the store).
//  - MockSocket installs cleanly into socketReceiver.
//  - Driving an active_gen:started event reaches activeGenStore via
//    the listener installed at module-import time.

import { afterEach, expect, test } from 'vitest';
import { renderChat } from './helpers/renderChat';
import { activeGenStore } from '~/lib/activeGenStore';

let cleanup: (() => void) | null = null;
afterEach(() => {
    cleanup?.();
    cleanup = null;
});

test('mockSocket drives active_gen:started into activeGenStore', async () => {
    const harness = await renderChat({ initialWorkflowId: 'wf-1' });
    cleanup = harness.cleanup;

    expect(Object.keys(activeGenStore.gens)).toEqual([]);

    harness.socket.serverEmit('active_gen:started', {
        gen_id: 'g1',
        workflow_id: 'wf-1',
        conversation_id: 'c1',
        prompt: 'hello',
        started_at: 0,
    });

    expect(activeGenStore.gens['g1']).toMatchObject({
        gen_id: 'g1',
        workflow_id: 'wf-1',
        conversation_id: 'c1',
        prompt: 'hello',
    });
    expect(activeGenStore.byWorkflow['wf-1']).toEqual(['g1']);
});

test('mockSocket terminal frame evicts the gen', async () => {
    const harness = await renderChat({ initialWorkflowId: 'wf-1' });
    cleanup = harness.cleanup;

    harness.socket.serverEmit('active_gen:started', {
        gen_id: 'g1',
        workflow_id: 'wf-1',
        conversation_id: 'c1',
        prompt: 'hello',
        started_at: 0,
    });
    expect(Object.keys(activeGenStore.gens)).toEqual(['g1']);

    harness.socket.serverEmit('active_gen:terminal', {
        gen_id: 'g1',
        committed_conversation_id: 'c1',
        committed_messages: [
            { role: 'user', message: 'hello' },
            { role: 'assistant', message: 'done' },
        ],
    });

    expect(Object.keys(activeGenStore.gens)).toEqual([]);
    expect(activeGenStore.byWorkflow).toEqual({});
});
