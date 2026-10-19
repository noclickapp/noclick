// @vitest-environment jsdom
// A chat that keeps a copy of its thread paints it at once and lets the persisted history replace it: the copy never
// doubles a message, never outlives a thread the server no longer holds, and a failed read is a failure, not an empty
// thread. The coordinator's chat builds on that, so an ongoing conversation never opens on the empty start.
import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useAgentChat, type AgentChatMessage, type AgentChatTransport, type ResumeResponse } from '~/hooks/useAgentChat';
import { getAgentChatSession, resetAgentChatSessions, seedAgentChatSession } from '~/lib/agentChatSessionStore';
import { installMockSocket, type MockSocket } from '../integration/helpers/mockSocket';

const cache = vi.hoisted(() => ({
    read: vi.fn<(userId: string) => Promise<{ conversationId: string; messages: AgentChatMessage[] } | null>>(),
    write: vi.fn(),
}));
vi.mock('~/lib/coordinatorThreadCache', () => ({ readCachedThread: cache.read, writeCachedThread: cache.write }));

let signedIn = 'user-0';
vi.mock('react-router', async (importOriginal) => ({
    ...(await importOriginal<typeof import('react-router')>()),
    useRouteLoaderData: () => ({ user: { id: signedIn } }),
}));

const { useCoordinatorChat } = await import('~/hooks/useCoordinatorChat');

const said = (text: string, isUser = false): AgentChatMessage => ({ isUser, text, isComplete: true });
const event = (text: string, isUser = false) => ({ action: 'message', source: isUser ? 'user' : 'agent', args: { content: text }, message: text });
const texts = (messages: readonly AgentChatMessage[]) => messages.map((m) => m.text);

function deferredTransport() {
    let settle!: { resolve: (r: ResumeResponse) => void; reject: (e: Error) => void };
    const transport: AgentChatTransport = {
        onEvent: () => () => {},
        resume: () => new Promise<ResumeResponse>((resolve, reject) => (settle = { resolve, reject })),
    };
    return { transport, settle: () => settle };
}

beforeEach(() => {
    resetAgentChatSessions();
});
afterEach(() => {
    cleanup();
});

describe('a chat painted from its copy', () => {
    it('shows the copy at once and adopts the persisted history when it lands', async () => {
        seedAgentChatSession('c1', [said('old question', true), said('old answer')]);
        const { transport, settle } = deferredTransport();
        const { result } = renderHook(() => useAgentChat('c1', transport));
        expect(texts(result.current.messages)).toEqual(['old question', 'old answer']);

        await act(async () => settle().resolve({ messages: [event('old question', true), event('old answer'), event('from a text', true), event('a reply')] }));
        expect(texts(result.current.messages)).toEqual(['old question', 'old answer', 'from a text', 'a reply']);
        expect(getAgentChatSession('c1').cached).toBe(0);
        expect(getAgentChatSession('c1').resumedOnce).toBe(true);
    });

    it('drops the copy when the server holds no thread', async () => {
        seedAgentChatSession('c1', [said('old question', true), said('old answer')]);
        const { transport, settle } = deferredTransport();
        const { result } = renderHook(() => useAgentChat('c1', transport));

        await act(async () => settle().resolve({ messages: [] }));
        expect(result.current.messages).toEqual([]);
    });

    it('keeps a message sent while the copy shows exactly once, after the history', async () => {
        seedAgentChatSession('c1', [said('old question', true), said('old answer')]);
        const { transport, settle } = deferredTransport();
        const { result } = renderHook(() => useAgentChat('c1', transport));

        act(() => result.current.addUserMessage('new question'));
        await act(async () => settle().resolve({ messages: [event('old question', true), event('old answer')] }));
        expect(texts(result.current.messages)).toEqual(['old question', 'old answer', 'new question']);
    });

    it('keeps the copy and records the failure when the history read fails', async () => {
        seedAgentChatSession('c1', [said('old question', true), said('old answer')]);
        const { transport, settle } = deferredTransport();
        const { result } = renderHook(() => useAgentChat('c1', transport));

        await act(async () => settle().reject(new Error('Could not load the conversation')));
        expect(texts(result.current.messages)).toEqual(['old question', 'old answer']);
        expect(getAgentChatSession('c1').resumeError).toBe('Could not load the conversation');
        expect(getAgentChatSession('c1').resumedOnce).toBe(false);
    });

    it('never seeds over a session that already holds the thread', () => {
        getAgentChatSession('c1').resumedOnce = true;
        seedAgentChatSession('c1', [said('stale')]);
        expect(getAgentChatSession('c1').messages).toEqual([]);

        getAgentChatSession('c2').messages = [said('live')];
        seedAgentChatSession('c2', [said('stale')]);
        expect(texts(getAgentChatSession('c2').messages)).toEqual(['live']);
    });
});

describe('the coordinator chat', () => {
    let socket: MockSocket;
    let teardown: () => void;
    let user = 0;

    beforeEach(() => {
        // Each test signs in as someone new: the tab remembers the last thread it opened, per account.
        signedIn = `user-${++user}`;
        cache.read.mockReset().mockResolvedValue(null);
        cache.write.mockReset();
        ({ socket, teardown } = installMockSocket());
        socket.replyTo('coordinator:open', () => ({ conversation_id: `coordinator:${signedIn}`, reach: { phone: null, imessage: null, email: null } }));
    });
    afterEach(() => {
        cleanup();
        teardown();
    });

    const answerResume = (messages: unknown[], error?: string) =>
        act(async () => {
            const sent = socket.expectSent('conversation:resume');
            socket.serverEmit('response', { request_id: (sent.data as { request_id: string }).request_id, data: { messages }, error });
        });

    it('shows neither the start nor a thread until the history says which', async () => {
        const { result } = renderHook(() => useCoordinatorChat());
        await waitFor(() => expect(result.current.conversationId).toBe(`coordinator:${signedIn}`));
        expect(result.current.loaded).toBe(false);
        // Opening it says where this browser is: its zone replaces the one the owner's number placed.
        expect(socket.expectSent('coordinator:open').data).toMatchObject({ timezone: Intl.DateTimeFormat().resolvedOptions().timeZone });

        await answerResume([event('brief me', true), event('done')]);
        expect(result.current.loaded).toBe(true);
        expect(texts(result.current.messages)).toEqual(['brief me', 'done']);
    });

    it('paints this browser’s copy before the server answers anything', async () => {
        socket.clearReplyHandlers();
        cache.read.mockResolvedValue({ conversationId: `coordinator:${signedIn}`, messages: [said('brief me', true), said('done')] });
        const { result } = renderHook(() => useCoordinatorChat());

        await waitFor(() => expect(result.current.loaded).toBe(true));
        expect(texts(result.current.messages)).toEqual(['brief me', 'done']);
        expect(cache.read).toHaveBeenCalledWith(signedIn);
    });

    it('opens on the start at once when the copy says there is no conversation yet', async () => {
        socket.clearReplyHandlers();
        cache.read.mockResolvedValue({ conversationId: `coordinator:${signedIn}`, messages: [] });
        const { result } = renderHook(() => useCoordinatorChat());

        await waitFor(() => expect(result.current.loaded).toBe(true));
        expect(result.current.messages).toEqual([]);
    });

    it('comes back to the chat with the thread already there', async () => {
        const first = renderHook(() => useCoordinatorChat());
        await waitFor(() => expect(first.result.current.conversationId).not.toBeNull());
        await answerResume([event('brief me', true), event('done')]);
        first.unmount();

        const { result } = renderHook(() => useCoordinatorChat());
        expect(result.current.loaded).toBe(true);
        expect(texts(result.current.messages)).toEqual(['brief me', 'done']);
    });

    it('writes the settled thread back for the next visit', async () => {
        const { result } = renderHook(() => useCoordinatorChat());
        await waitFor(() => expect(result.current.conversationId).not.toBeNull());
        await answerResume([event('brief me', true), event('done')]);

        await waitFor(() => expect(cache.write).toHaveBeenCalled(), { timeout: 2000 });
        const [userId, conversationId, messages] = cache.write.mock.calls.at(-1)!;
        expect([userId, conversationId, texts(messages)]).toEqual([signedIn, `coordinator:${signedIn}`, ['brief me', 'done']]);
    });

    it('says when the history fails to load, and reads it again on retry', async () => {
        const { result } = renderHook(() => useCoordinatorChat());
        await waitFor(() => expect(result.current.conversationId).not.toBeNull());
        await answerResume([], 'Could not load the conversation');
        expect(result.current.loaded).toBe(false);
        expect(result.current.loadError).toBe('Could not load the conversation');

        socket.clearSent();
        act(() => result.current.retry());
        expect(result.current.loadError).toBeNull();
        await waitFor(() => expect(socket.hasSent('conversation:resume')).toBe(true));
        await answerResume([event('brief me', true)]);
        expect(result.current.loaded).toBe(true);
        expect(texts(result.current.messages)).toEqual(['brief me']);
    });
});
