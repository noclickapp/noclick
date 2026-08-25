// Integration tests for useSidebarConversation.
//
// The hook resolves the sidebar's active conversation_id from one of
// three sources per workflow change:
//   1. activeGenStore (any gen for the workflow wins instantly)
//   2. BE `conversation:get_latest_for_workflow` lookup
//   3. fresh uuid (when neither has anything)
//
// These tests drive workflow switches synthetically and assert the
// resolved conversation_id at each step. The MockSocket lets us
// control what the BE returns for the lookup; the activeGenStore is
// poked directly via `active_gen:started` frames so we can simulate
// in-flight gens that arrive before/during/after a workflow becomes
// active.
//
// The bug we keep hitting manually — "switching back to workflow A
// doesn't restore A's conversation" — should reproduce here as a
// failing test if our resolver has a real race.

import { afterEach, describe, expect, test } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { installMockSocket, MockSocket } from './helpers/mockSocket';
import { useSidebarConversation } from '~/hooks/useSidebarConversation';
import { activeGenStore } from '~/lib/activeGenStore';

const SCRATCH_KEY = 'noclick:chat:scratchConversationId';
const MAP_KEY = 'noclick:chat:convByWorkflow';

let teardown: (() => void) | null = null;

function resetStores() {
    Object.keys(activeGenStore.gens).forEach(k => delete activeGenStore.gens[k]);
    Object.keys(activeGenStore.byWorkflow).forEach(k => delete activeGenStore.byWorkflow[k]);
    Object.keys(activeGenStore.byConversation).forEach(k => delete activeGenStore.byConversation[k]);
    Object.keys(activeGenStore.lastCommitted).forEach(k => delete activeGenStore.lastCommitted[k]);
    try {
        window.sessionStorage.removeItem(SCRATCH_KEY);
        window.sessionStorage.removeItem(MAP_KEY);
    } catch { /* no-op */ }
}

function setup(): MockSocket {
    resetStores();
    const installed = installMockSocket();
    teardown = installed.teardown;
    return installed.socket;
}

afterEach(() => {
    teardown?.();
    teardown = null;
    resetStores();
});

/** Make the BE return a per-workflow map of conversation_ids. Any
 *  workflow not in the map returns conversation_id: null. */
function mockBELookups(socket: MockSocket, byWorkflow: Record<string, string>) {
    socket.replyTo('conversation:get_latest_for_workflow', (req: unknown) => {
        const wfId = (req as { workflow_id: string }).workflow_id;
        const conv = byWorkflow[wfId];
        return {
            workflow_id: wfId,
            conversation_id: conv ?? null,
            has_user_messages: !!conv,
            has_pending_ask: false,
            active_generation_id: null,
        };
    });
}

function renderSidebar(initialWfId: string | null) {
    return renderHook(
        ({ wfId }: { wfId: string | null }) => useSidebarConversation(wfId),
        { initialProps: { wfId: initialWfId } },
    );
}

describe('useSidebarConversation', () => {

    test('cold open of a workflow with a BE-persisted conv adopts it', async () => {
        const socket = setup();
        mockBELookups(socket, { 'wf-A': 'conv-A' });

        const { result } = renderSidebar('wf-A');

        await waitFor(() => {
            expect(result.current.conversationId).toBe('conv-A');
        });
    });

    test('cold open with no BE conv falls back to a fresh id', async () => {
        const socket = setup();
        mockBELookups(socket, {}); // BE returns null for everything

        const { result } = renderSidebar('wf-A');

        // Wait for the BE lookup to land — should be a uuid.
        await waitFor(() => {
            // Anything truthy, but NOT a literal "null"/empty value.
            expect(result.current.conversationId).toMatch(/.+/);
            // Initially conversationId was the scratch slot; after the
            // BE lookup returns null, the fallback is a fresh id —
            // assert it changed.
        });
        // No specific assertion on the exact uuid, just that resolution
        // produced something stable and non-empty.
        expect(typeof result.current.conversationId).toBe('string');
    });

    test('active gen on the workflow wins over BE lookup', async () => {
        const socket = setup();
        mockBELookups(socket, { 'wf-A': 'conv-BE' });

        // Simulate a gen for wf-A already in-flight when the user opens A.
        socket.serverEmit('active_gen:started', {
            gen_id: 'g1',
            workflow_id: 'wf-A',
            conversation_id: 'conv-Gen',
            prompt: 'test',
            started_at: 100,
        });

        const { result } = renderSidebar('wf-A');

        await waitFor(() => {
            expect(result.current.conversationId).toBe('conv-Gen');
        });
    });

    test('switching A → B → A restores each workflow', async () => {
        const socket = setup();
        mockBELookups(socket, { 'wf-A': 'conv-A', 'wf-B': 'conv-B' });

        const { result, rerender } = renderSidebar('wf-A');

        await waitFor(() => {
            expect(result.current.conversationId).toBe('conv-A');
        });

        rerender({ wfId: 'wf-B' });
        await waitFor(() => {
            expect(result.current.conversationId).toBe('conv-B');
        });

        rerender({ wfId: 'wf-A' });
        await waitFor(() => {
            expect(result.current.conversationId).toBe('conv-A');
        });

        rerender({ wfId: 'wf-B' });
        await waitFor(() => {
            expect(result.current.conversationId).toBe('conv-B');
        });

        rerender({ wfId: 'wf-A' });
        await waitFor(() => {
            expect(result.current.conversationId).toBe('conv-A');
        });
    });

    test('scratch slot persists across canvas close/reopen', async () => {
        const socket = setup();
        mockBELookups(socket, { 'wf-A': 'conv-A' });

        const { result, rerender } = renderSidebar(null);

        const scratchId = result.current.conversationId;
        expect(scratchId).toBeTruthy();

        // Open a workflow → resolves to A's BE conv.
        rerender({ wfId: 'wf-A' });
        await waitFor(() => {
            expect(result.current.conversationId).toBe('conv-A');
        });

        // Close canvas → scratch slot restored (same id as before).
        rerender({ wfId: null });
        await waitFor(() => {
            expect(result.current.conversationId).toBe(scratchId);
        });
    });

    test('headless run that targets workflow surfaces on workflow open', async () => {
        const socket = setup();
        mockBELookups(socket, { 'wf-A': 'conv-Old' });

        // User is outside any canvas; a headless gen targets wf-A.
        socket.serverEmit('active_gen:started', {
            gen_id: 'g1',
            workflow_id: 'wf-A',
            conversation_id: 'conv-Headless',
            prompt: 'edit my crm',
            started_at: 0,
        });

        const { result, rerender } = renderSidebar(null);

        // User opens wf-A. Gen-priority kicks in: adopts conv-Headless,
        // NOT the stale conv-Old from BE.
        rerender({ wfId: 'wf-A' });
        await waitFor(() => {
            expect(result.current.conversationId).toBe('conv-Headless');
        });
    });

    test('gen that appears mid-session for the active workflow is adopted', async () => {
        const socket = setup();
        mockBELookups(socket, { 'wf-A': 'conv-A' });

        const { result } = renderSidebar('wf-A');
        await waitFor(() => {
            expect(result.current.conversationId).toBe('conv-A');
        });

        // Now a fresh gen appears for wf-A with a different conv.
        socket.serverEmit('active_gen:started', {
            gen_id: 'g-mid',
            workflow_id: 'wf-A',
            conversation_id: 'conv-NewGen',
            prompt: 'new prompt',
            started_at: 200,
        });

        await waitFor(() => {
            expect(result.current.conversationId).toBe('conv-NewGen');
        });
    });

    // Exact user repro:
    //   open A → send → back → send → open B → send → back → verify
    //   scratch restored → open A → verify A restored → back → verify
    //   scratch restored → open B → verify B restored.
    test('full repro: A/scratch/B independent threads survive cross-navigation', async () => {
        const socket = setup();
        // BE state: workflow → latest persisted conv. Updated after each
        // "send" to simulate the BE saving the conversation row.
        const beConvs: Record<string, string | null> = {};
        socket.replyTo('conversation:get_latest_for_workflow', (req: unknown) => {
            const wfId = (req as { workflow_id: string }).workflow_id;
            const conv = beConvs[wfId];
            return {
                workflow_id: wfId,
                conversation_id: conv ?? null,
                has_user_messages: !!conv,
                has_pending_ask: false,
                active_generation_id: null,
            };
        });

        const { result, rerender } = renderSidebar(null);

        // 0. Outside any canvas — sidebar uses scratch slot.
        const scratchInitial = result.current.conversationId;
        expect(scratchInitial).toBeTruthy();

        // 1. Open workflow A. No history → resolves to a fresh id
        //    (BE returns null, hook falls back to freshId).
        rerender({ wfId: 'wf-A' });
        await waitFor(() => {
            expect(result.current.conversationId).not.toBe(scratchInitial);
        });
        const convA = result.current.conversationId;
        expect(convA).toBeTruthy();

        // 2. User sends on A → gen registers with (wf-A, convA), BE
        //    eventually saves the conversation row with workflow_id=wf-A.
        socket.serverEmit('active_gen:started', {
            gen_id: 'g-A',
            workflow_id: 'wf-A',
            conversation_id: convA,
            prompt: 'hello A',
            started_at: 100,
        });
        socket.serverEmit('active_gen:terminal', {
            gen_id: 'g-A',
            outcome: 'complete',
            committed_conversation_id: convA,
            committed_messages: [{ role: 'user', message: 'hello A' }],
        });
        beConvs['wf-A'] = convA;

        // 3. Go back (no workflow open) — scratch slot restored.
        rerender({ wfId: null });
        await waitFor(() => {
            expect(result.current.conversationId).toBe(scratchInitial);
        });

        // 4. User sends standalone (no workflow). Brain may decide what to
        //    do with it later; the sidebar's conv stays at the scratch slot.
        socket.serverEmit('active_gen:started', {
            gen_id: 'g-scratch',
            workflow_id: null,
            conversation_id: scratchInitial,
            prompt: 'standalone',
            started_at: 200,
        });
        // (Leave this gen running — represents in-flight headless work.)

        // 5. Open workflow B. No history → fresh id, different from
        //    scratch and convA.
        rerender({ wfId: 'wf-B' });
        await waitFor(() => {
            const c = result.current.conversationId;
            expect(c).not.toBe(scratchInitial);
            expect(c).not.toBe(convA);
        });
        const convB = result.current.conversationId;
        expect(convB).toBeTruthy();

        // 6. Send on B.
        socket.serverEmit('active_gen:started', {
            gen_id: 'g-B',
            workflow_id: 'wf-B',
            conversation_id: convB,
            prompt: 'hello B',
            started_at: 300,
        });
        socket.serverEmit('active_gen:terminal', {
            gen_id: 'g-B',
            outcome: 'complete',
            committed_conversation_id: convB,
            committed_messages: [{ role: 'user', message: 'hello B' }],
        });
        beConvs['wf-B'] = convB;

        // 7. Go back → scratch slot restored (NOT clobbered by A or B).
        rerender({ wfId: null });
        await waitFor(() => {
            expect(result.current.conversationId).toBe(scratchInitial);
        });

        // 8. Open A → convA restored.
        rerender({ wfId: 'wf-A' });
        await waitFor(() => {
            expect(result.current.conversationId).toBe(convA);
        });

        // 9. Back → scratch restored again.
        rerender({ wfId: null });
        await waitFor(() => {
            expect(result.current.conversationId).toBe(scratchInitial);
        });

        // 10. Open B → convB restored.
        rerender({ wfId: 'wf-B' });
        await waitFor(() => {
            expect(result.current.conversationId).toBe(convB);
        });
    });

    test('many cycles: A ↔ none ↔ B repeated preserves each workflow\'s thread', async () => {
        const socket = setup();
        const beConvs: Record<string, string> = { 'wf-A': 'conv-A', 'wf-B': 'conv-B' };
        socket.replyTo('conversation:get_latest_for_workflow', (req: unknown) => {
            const wfId = (req as { workflow_id: string }).workflow_id;
            const conv = beConvs[wfId];
            return {
                workflow_id: wfId,
                conversation_id: conv ?? null,
                has_user_messages: !!conv,
                has_pending_ask: false,
                active_generation_id: null,
            };
        });

        const { result, rerender } = renderSidebar(null);
        const scratchInitial = result.current.conversationId;
        expect(scratchInitial).toBeTruthy();

        // 5 full cycles: each cycle visits A, scratch, B, scratch.
        // 20 total transitions; restoration must succeed at every step.
        for (let i = 0; i < 5; i++) {
            const round = `round ${i + 1}`;

            rerender({ wfId: 'wf-A' });
            await waitFor(() => {
                expect(result.current.conversationId, `${round}: A`).toBe('conv-A');
            });

            rerender({ wfId: null });
            await waitFor(() => {
                expect(result.current.conversationId, `${round}: A→none`).toBe(scratchInitial);
            });

            rerender({ wfId: 'wf-B' });
            await waitFor(() => {
                expect(result.current.conversationId, `${round}: B`).toBe('conv-B');
            });

            rerender({ wfId: null });
            await waitFor(() => {
                expect(result.current.conversationId, `${round}: B→none`).toBe(scratchInitial);
            });
        }
    });

    test('rapid cycles: no wait between navigations — final state still correct', async () => {
        // Same workflow set, but transition WITHOUT awaiting between rerenders.
        // Stresses the cleanup-cancellation chain: prior in-flight lookups
        // must be cancelled and the final navigation's lookup must win.
        const socket = setup();
        socket.replyTo('conversation:get_latest_for_workflow', (req: unknown) => {
            const wfId = (req as { workflow_id: string }).workflow_id;
            const conv = wfId === 'wf-A' ? 'conv-A' : wfId === 'wf-B' ? 'conv-B' : null;
            return {
                workflow_id: wfId,
                conversation_id: conv,
                has_user_messages: !!conv,
                has_pending_ask: false,
                active_generation_id: null,
            };
        });

        const { result, rerender } = renderSidebar(null);
        const scratchInitial = result.current.conversationId;

        // Rapid-fire many transitions without awaiting.
        rerender({ wfId: 'wf-A' });
        rerender({ wfId: null });
        rerender({ wfId: 'wf-B' });
        rerender({ wfId: null });
        rerender({ wfId: 'wf-A' });
        rerender({ wfId: 'wf-B' });
        rerender({ wfId: 'wf-A' });
        rerender({ wfId: null });
        rerender({ wfId: 'wf-A' });

        // Final state is wf-A → must end at conv-A.
        await waitFor(() => {
            expect(result.current.conversationId).toBe('conv-A');
        });

        // Now go back to scratch and verify it's still the same scratch id.
        rerender({ wfId: null });
        await waitFor(() => {
            expect(result.current.conversationId).toBe(scratchInitial);
        });

        // And one more cycle to B should land cleanly on conv-B.
        rerender({ wfId: 'wf-B' });
        await waitFor(() => {
            expect(result.current.conversationId).toBe('conv-B');
        });
    });

    test('BE returns null for a workflow the user has chatted in — local map restores it', async () => {
        // Reproduction of the real-world failure: BE's
        // `conversation:get_latest_for_workflow` returns
        // `conversation_id: null` even after the user has sent on the
        // workflow (because `conversations.workflow_id` isn't reliably
        // populated server-side). The FE must NOT lose the conv —
        // recording the (workflow_id, conv_id) pair locally as gens
        // register lets us restore from the tab's own memory.

        const socket = setup();
        // BE never knows about any conversation for this workflow.
        socket.replyTo('conversation:get_latest_for_workflow', (req: unknown) => ({
            workflow_id: (req as { workflow_id: string }).workflow_id,
            conversation_id: null,
            has_user_messages: false,
            has_pending_ask: false,
            active_generation_id: null,
        }));

        const { result, rerender } = renderSidebar(null);
        const scratchInitial = result.current.conversationId;

        // 1. Open workflow A. BE returns null → optimistic fresh id.
        rerender({ wfId: 'wf-A' });
        await waitFor(() => {
            expect(result.current.conversationId).not.toBe(scratchInitial);
        });
        const convA = result.current.conversationId;

        // 2. Simulate user sending on A: a gen registers.
        socket.serverEmit('active_gen:started', {
            gen_id: 'g-A',
            workflow_id: 'wf-A',
            conversation_id: convA,
            prompt: 'hello A',
            started_at: 100,
        });
        // Let the gen-store subscribe callback fire so recordMapping runs
        // before the gen terminates.
        await new Promise(r => setTimeout(r, 20));

        socket.serverEmit('active_gen:terminal', {
            gen_id: 'g-A',
            outcome: 'complete',
            committed_conversation_id: convA,
            committed_messages: [{ role: 'user', message: 'hello A' }],
        });
        await new Promise(r => setTimeout(r, 20));

        // 3. Go back. Scratch restored.
        rerender({ wfId: null });
        await waitFor(() => {
            expect(result.current.conversationId).toBe(scratchInitial);
        });

        // 4. Reopen A. BE STILL returns null, but the local map records
        //    A→convA from step 2. The hook must restore convA.
        rerender({ wfId: 'wf-A' });
        await waitFor(() => {
            expect(result.current.conversationId).toBe(convA);
        });

        // 5. Multiple round-trips: A → scratch → A → scratch → A must
        //    all land on convA.
        for (let i = 0; i < 3; i++) {
            rerender({ wfId: null });
            await waitFor(() => {
                expect(result.current.conversationId).toBe(scratchInitial);
            });
            rerender({ wfId: 'wf-A' });
            await waitFor(() => {
                expect(result.current.conversationId).toBe(convA);
            });
        }
    });

    test('race: user sends BEFORE the BE lookup returns — gen conv must win', async () => {
        // The user's bug: navigate to workflow A and immediately send.
        // At the moment of send, the resolver's BE lookup is still in
        // flight and conversationId is still the previous slot's value
        // (the scratch conv). The send uses the scratch id, which then
        // becomes associated with workflow A on the BE — cross-
        // contamination. When the user later "goes back" (no workflow),
        // the sidebar shows the scratch id, which now displays the
        // message they sent on workflow A.
        //
        // The resolver must NOT clobber an in-flight conversation that
        // the user has already started using.

        const socket = setup();
        // Slow BE response: gives us time to simulate a send before the
        // lookup resolves.
        const pendingLookup: {
            resolve?: (conv: string | null) => void;
        } = {};
        socket.replyTo('conversation:get_latest_for_workflow', () => {
            return new Promise<unknown>(res => {
                pendingLookup.resolve = (conv) => res({
                    workflow_id: 'wf-A',
                    conversation_id: conv,
                    has_user_messages: !!conv,
                    has_pending_ask: false,
                    active_generation_id: null,
                });
            });
        });

        const { result, rerender } = renderSidebar(null);
        const scratchId = result.current.conversationId;

        // Navigate to A — resolver fires BE lookup but DOESN'T return yet.
        rerender({ wfId: 'wf-A' });
        // Conversation id should change off the scratch immediately,
        // so a send doesn't accidentally write to the scratch slot.
        await waitFor(() => {
            expect(result.current.conversationId).not.toBe(scratchId);
        });
        const convAtSendTime = result.current.conversationId;

        // Simulate "user sends" — a gen registers under the current conv id.
        socket.serverEmit('active_gen:started', {
            gen_id: 'g-A',
            workflow_id: 'wf-A',
            conversation_id: convAtSendTime,
            prompt: 'hello',
            started_at: 100,
        });

        // NOW the slow BE lookup returns with a different (stale) conv.
        pendingLookup.resolve?.('conv-stale');

        // Critical: the resolver must NOT override the user's active conv.
        // Give it time to attempt an override; assert the conv is still
        // the one the user sent on.
        await new Promise(r => setTimeout(r, 100));
        expect(result.current.conversationId).toBe(convAtSendTime);
    });

    test('switchToConversation writes through and persists across re-renders', async () => {
        const socket = setup();
        mockBELookups(socket, { 'wf-A': 'conv-A' });

        const { result, rerender } = renderSidebar('wf-A');
        await waitFor(() => {
            expect(result.current.conversationId).toBe('conv-A');
        });

        // User picks from history.
        result.current.switchToConversation('conv-Picked');
        await waitFor(() => {
            expect(result.current.conversationId).toBe('conv-Picked');
        });

        // Re-rendering with the same workflow should keep the pick
        // (no spurious re-resolution clobbering it).
        rerender({ wfId: 'wf-A' });
        // Note: with the current resolver, switching activeWfId to
        // the same value won't re-run the effect, so the pick survives.
        // BUT switching A → B → A *would* re-run resolution and lose it.
        // That second case is documented behavior (BE lookup is the
        // source of truth on workflow reopen).
        expect(result.current.conversationId).toBe('conv-Picked');
    });
});
