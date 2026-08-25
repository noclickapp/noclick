// Multi-turn scenario test: stream → interrupt → navigate away → back
// → send follow-up → stream → navigate away → back.
//
// What this proves end-to-end:
//   • Interrupted bubble persists across navigation (BE terminal frame
//     commits "Response interrupted" into the conversation).
//   • Follow-up prompt on the same conversation APPENDS rather than
//     replacing the prior interrupted turn.
//   • New streaming text is preserved across a second navigate-away.
//   • On return, both committed history AND in-flight gen are visible.
//
// Architectural promises being verified:
//   • activeGenStore + useConversation correctly compose persisted +
//     in-flight content across mount/unmount cycles.
//   • Gen-priority adoption preserves the prior committed turns of the
//     same conversation (doesn't wipe persisted when adopting a gen
//     whose conv matches the already-loaded persistedConvId).
//   • Optimistic gens registered on submit immediately surface the
//     user prompt without waiting for the BE round-trip.

import { afterEach, expect, test } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { ReactNode } from 'react';
import { renderChat } from './helpers/renderChat';
import { useConversation } from '~/hooks/useConversation';
import {
    activeGenStore,
    dispatchPauseAllActiveGens,
    registerOptimisticGen,
} from '~/lib/activeGenStore';
import { WorkflowProvider } from '~/components/workflow/WorkflowContext';

let cleanup: (() => void) | null = null;
afterEach(() => {
    cleanup?.();
    cleanup = null;
});

function withWorkflow(workflowId: string | null) {
    return ({ children }: { children: ReactNode }) => (
        <WorkflowProvider workflowId={workflowId ?? undefined} workflowName="Test">
            {children}
        </WorkflowProvider>
    );
}

const sleep = (ms: number) => new Promise<void>(r => setTimeout(r, ms));

function bubbleSummary(messages: { isUser?: boolean; text?: string; isComplete?: boolean; wasInterrupted?: boolean; editSegments?: { type: string; text?: string }[] }[]) {
    return messages.map(m => {
        const segText = m.editSegments
            ?.filter(s => s.type === 'text')
            .map(s => s.text ?? '')
            .join('');
        const text = m.text || segText || '';
        return {
            isUser: !!m.isUser,
            text: text.slice(0, 60),
            isComplete: m.isComplete,
            wasInterrupted: m.wasInterrupted,
        };
    });
}

test('stream → interrupt → nav-away → back → follow-up → stream → nav-away → back', async () => {
    const harness = await renderChat({ initialWorkflowId: null, children: <div /> });
    cleanup = harness.cleanup;

    // ── Step 1: First gen starts streaming ─────────────────────────────────
    const conversationId = 'conv-shared';
    harness.socket.serverEmit('active_gen:started', {
        gen_id: 'g1',
        workflow_id: 'wf-1',
        conversation_id: conversationId,
        prompt: 'first prompt',
        started_at: 0,
    });
    harness.socket.serverEmit('active_gen:text_chunk', {
        gen_id: 'g1',
        delta: 'Building the workflow…',
    });

    // Mount the hook for the first time.
    const view1 = renderHook(() => useConversation('wf-1'), {
        wrapper: withWorkflow('wf-1'),
    });

    // Verify streaming bubble visible.
    expect(view1.result.current.isStreaming).toBe(true);
    let summary = bubbleSummary(view1.result.current.messages as never);
    expect(summary).toEqual([
        { isUser: true, text: 'first prompt', isComplete: true, wasInterrupted: undefined },
        { isUser: false, text: 'Building the workflow…', isComplete: false, wasInterrupted: undefined },
    ]);

    // ── Step 2: User clicks stop ───────────────────────────────────────────
    await act(async () => { dispatchPauseAllActiveGens(); });
    await waitFor(() => {
        expect(view1.result.current.isStreaming).toBe(false);
    });
    summary = bubbleSummary(view1.result.current.messages as never);
    expect(summary[1].wasInterrupted).toBe(true);
    expect(summary[1].isComplete).toBe(true);

    // BE delivers the canonical interrupted history.
    await act(async () => {
        harness.socket.serverEmit('active_gen:terminal', {
            gen_id: 'g1',
            committed_conversation_id: conversationId,
            committed_messages: [
                { role: 'user', message: 'first prompt' },
                {
                    role: 'assistant',
                    message: '',
                    edit_segments: [{ type: 'text', text: 'Building the workflow…' }],
                    // BE-side persistence uses `cancelled: true`;
                    // mapPersistedMessages translates that into the
                    // FE Message's `wasInterrupted: true` flag.
                    cancelled: true,
                },
            ],
        });
    });

    // Wait for activeGenStore eviction + lastCommitted patch adoption.
    await waitFor(() => {
        expect(activeGenStore.gens).toEqual({});
    });
    // Persisted history now reflects the interrupted turn.
    await waitFor(() => {
        const s = bubbleSummary(view1.result.current.messages as never);
        expect(s.length).toBe(2);
        expect(s[1].wasInterrupted).toBe(true);
    });

    // ── Step 3: Navigate away (unmount the hook) ───────────────────────────
    view1.unmount();
    await sleep(50);

    // ── Step 4: Navigate back (remount) ────────────────────────────────────
    // The new hook fetches latest persisted from BE — mock that response.
    // useConversation issues `conversation:get_latest_for_workflow`; we
    // have to intercept on the harness's socket emit and reply.
    const origEmit = harness.socket.emit;
    harness.socket.emit = ((name: string, data: unknown, ...rest: unknown[]) => {
        origEmit.call(harness.socket, name, data, ...rest);
        const reqId = data && typeof data === 'object'
            ? (data as { request_id?: string }).request_id
            : undefined;
        if (!reqId) return true;
        if (name === 'conversation:get_latest_for_workflow') {
            queueMicrotask(() => {
                harness.socket.serverEmit('response', {
                    request_id: reqId,
                    data: {
                        conversation_id: conversationId,
                        has_user_messages: true,
                        has_pending_ask: false,
                    },
                });
            });
        } else if (name === 'conversation:resume') {
            queueMicrotask(() => {
                harness.socket.serverEmit('response', {
                    request_id: reqId,
                    data: {
                        messages: [
                            { role: 'user', message: 'first prompt' },
                            {
                                role: 'assistant',
                                message: '',
                                edit_segments: [{ type: 'text', text: 'Building the workflow…' }],
                                cancelled: true,
                            },
                        ],
                    },
                });
            });
        }
        return true;
    }) as typeof harness.socket.emit;

    const view2 = renderHook(() => useConversation('wf-1'), {
        wrapper: withWorkflow('wf-1'),
    });

    // Wait for the BE-lookup chain to resolve into persisted.
    await waitFor(() => {
        const s = bubbleSummary(view2.result.current.messages as never);
        expect(s.length).toBe(2);
        expect(s[0].text).toBe('first prompt');
        expect(s[1].wasInterrupted).toBe(true);
    }, { timeout: 5000 });

    // ── Step 5: Send a follow-up prompt on the SAME conversation ───────────
    // The optimistic gen surfaces immediately so user sees their bubble
    // before the BE round-trip.
    act(() => {
        registerOptimisticGen({
            workflow_id: 'wf-1',
            conversation_id: conversationId,
            prompt: 'add slack notification',
        });
    });

    // Critical assertion: the prior interrupted bubble must REMAIN
    // visible alongside the new user prompt + streaming asst bubble.
    await waitFor(() => {
        const s = bubbleSummary(view2.result.current.messages as never);
        expect(s.length).toBe(4);  // user1, asst1-interrupted, user2, asst2-streaming
        expect(s[0]).toMatchObject({ isUser: true, text: 'first prompt' });
        expect(s[1]).toMatchObject({ isUser: false, wasInterrupted: true });
        expect(s[2]).toMatchObject({ isUser: true, text: 'add slack notification' });
        expect(s[3]).toMatchObject({ isUser: false, isComplete: false });
    });

    // ── Step 6: BE confirms gen started + streams text ─────────────────────
    // active_gen:started will evict our optimistic gen and register the
    // real one keyed on the same conversation_id.
    await act(async () => {
        harness.socket.serverEmit('active_gen:started', {
            gen_id: 'g2',
            workflow_id: 'wf-1',
            conversation_id: conversationId,
            prompt: 'add slack notification',
            started_at: 1,
        });
    });

    await act(async () => {
        harness.socket.serverEmit('active_gen:text_chunk', {
            gen_id: 'g2',
            delta: 'Adding slack node…',
        });
    });

    await waitFor(() => {
        const s = bubbleSummary(view2.result.current.messages as never);
        expect(s.length).toBe(4);
        expect(s[3].text).toContain('Adding slack node…');
    });

    // ── Step 7: Navigate away mid-stream ───────────────────────────────────
    view2.unmount();
    await sleep(50);

    // Backend keeps streaming while we're "away" — gen lives in store.
    harness.socket.serverEmit('active_gen:text_chunk', {
        gen_id: 'g2',
        delta: ' Wiring inputs.',
    });

    // ── Step 8: Navigate back, gen still running ───────────────────────────
    const view3 = renderHook(() => useConversation('wf-1'), {
        wrapper: withWorkflow('wf-1'),
    });

    // The promise: we see BOTH the prior interrupted turn AND the
    // in-flight gen2 streaming the latest text.
    await waitFor(() => {
        const s = bubbleSummary(view3.result.current.messages as never);
        expect(s.length).toBe(4);
        expect(s[0]).toMatchObject({ isUser: true, text: 'first prompt' });
        expect(s[1]).toMatchObject({ isUser: false, wasInterrupted: true });
        expect(s[2]).toMatchObject({ isUser: true, text: 'add slack notification' });
        expect(s[3].text).toContain('Wiring inputs.');
        expect(view3.result.current.isStreaming).toBe(true);
    }, { timeout: 5000 });
}, 30_000);
