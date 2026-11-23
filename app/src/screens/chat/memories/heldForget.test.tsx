// @vitest-environment happy-dom
// Forgetting a memory in the chat's memory panel, from a copy of the app on the key NoClick gave it: forgetting can't be
// undone, so NoClick holds it for the account's owner. The panel shows no error for it; a toast says it went to the
// owner and where, and the list is read again once it's done.
import { act, cleanup, render, renderHook, screen, waitFor } from '@testing-library/react';
import { ApprovalRequired, DEFAULT_BASE_URL, NoClick } from 'noclick';
import { Toaster } from 'sonner';
import { afterEach, describe, expect, it } from 'vitest';
import { ClientProvider } from '@/sdk/client';
import { createWorkLive, WorkLiveContext } from '@/sdk/live';
import { useMemories, type MemoryEntry, type MemoryTransport } from './useMemories';

afterEach(cleanup);

const ENTRY: MemoryEntry = {
    id: 'ana-prefers-email',
    name: 'ana-prefers-email',
    description: 'How Ana likes to be reached',
    memory_type: 'user',
    origin_conversation_id: null,
    version: 2,
    created_at: '2026-11-20T10:00:00Z',
    updated_at: '2026-11-20T10:00:00Z',
    content: 'Email, not texts.',
};

describe('forgetting a memory held for the owner', () => {
    it('says it went to the owner, never an error, and reads the list again once it’s done', async () => {
        let held = 'awaiting_human';
        let release = () => undefined as void;
        const waited = new Promise<void>((done) => (release = done));
        const fetch: typeof window.fetch = async (input) => {
            const path = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url).pathname;
            if (path.endsWith('/wait')) await waited;
            const body = { object: 'operation', id: 'op_held', kind: 'gate.held_call', status: held, ...(held === 'succeeded' ? { result: { status: 204, response: null } } : {}) };
            return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } });
        };
        const client = new NoClick({ apiKey: 'a-fixture-holds-no-key', baseUrl: DEFAULT_BASE_URL, maxRetries: 0, fetch });
        let lists = 0;
        const transport: MemoryTransport = {
            list: async () => {
                lists += 1;
                return { memories: [ENTRY], has_more: false };
            },
            get: async () => ENTRY,
            save: async () => ENTRY,
            forget: async () => {
                throw new ApprovalRequired('It waits for the account’s owner.', {
                    details: { approval_id: 'apr_1', operation_id: 'op_held', sent_to: ['whatsapp'], status: 'awaiting_approval' },
                });
            },
        };
        const live = createWorkLive();
        const { result } = renderHook(() => useMemories(transport), {
            wrapper: ({ children }) => (
                <ClientProvider client={client}>
                    <WorkLiveContext.Provider value={live}>{children}</WorkLiveContext.Provider>
                </ClientProvider>
            ),
        });
        render(<Toaster />);
        await waitFor(() => expect(result.current.memories).toHaveLength(1));
        const before = lists;

        await act(async () => result.current.forget(ENTRY));
        expect(result.current.error).toBeNull();
        expect(await screen.findByText('Forget ana-prefers-email: waiting for approval')).toBeTruthy();
        expect(screen.getByText('Sent to the account’s owner to approve, on WhatsApp. It goes ahead once they approve it.')).toBeTruthy();

        held = 'succeeded';
        act(() => live.deliver('platform:resource', { kind: 'approval', id: 'apr_1', status: 'approved' }));
        release();
        expect(await screen.findByText('Forget ana-prefers-email: done')).toBeTruthy();
        await waitFor(() => expect(lists).toBeGreaterThan(before));
    });
});
