// @vitest-environment jsdom
// Agent task results must not finish or absorb a coordinator reply in progress.
import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import {
    persistedEventsToChatMessages,
    useAgentChat,
} from '~/hooks/useAgentChat';
import { resetAgentChatSessions } from '~/lib/agentChatSessionStore';
import {
    installMockSocket,
    type MockSocket,
} from '../integration/helpers/mockSocket';

let socket: MockSocket;
let teardown: () => void;
const cid = 'coordinator:test-notifications';
const notification = {
    conversation_id: cid,
    message: 'Researcher replied: Found it.',
    finished: true,
    notification: true,
    turn_id: 'coordinator-task:one',
};

beforeEach(() => {
    resetAgentChatSessions();
    ({ socket, teardown } = installMockSocket());
    socket.replyTo('conversation:resume', () => ({ messages: [] }));
});
afterEach(() => {
    cleanup();
    teardown();
    vi.useRealTimers();
});

it('keeps a background reply separate while coordinator text continues streaming', async () => {
    const { result } = renderHook(() => useAgentChat(cid));
    await act(async () => {});
    act(() => result.current.addUserMessage('What next?'));
    act(() =>
        socket.serverEmit('chat:message', {
            conversation_id: cid,
            message: 'Next, ',
        })
    );
    act(() => socket.serverEmit('chat:message', notification));
    expect(result.current.isStreaming).toBe(true);
    expect(result.current.lastFinishedAt).toBe(0);
    act(() =>
        socket.serverEmit('chat:message', {
            conversation_id: cid,
            message: 'review it.',
            finished: true,
        })
    );
    act(() => socket.serverEmit('chat:message', notification));
    expect(result.current.messages.map((m) => m.text)).toEqual([
        'What next?',
        'Next, review it.',
        notification.message,
    ]);
    expect(result.current.isStreaming).toBe(false);
});

it('restores background identity and deduplicates a replay after reconnect', async () => {
    socket.replyTo('conversation:resume', () => ({
        messages: [{ role: 'assistant', ...notification }],
    }));
    const { result } = renderHook(() => useAgentChat(cid));
    await act(async () => {});
    act(() => socket.serverEmit('chat:message', notification));
    expect(result.current.messages).toHaveLength(1);
    expect(result.current.messages[0]).toMatchObject({
        notification: true,
        turnId: notification.turn_id,
    });
});

it('does not let a persisted notification terminate the current user turn', async () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useAgentChat(cid));
    await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
    });
    act(() => result.current.addUserMessage('Still working?'));
    socket.replyTo('conversation:resume', () => ({
        messages: [
            { role: 'user', message: 'Still working?' },
            { role: 'assistant', ...notification },
        ],
    }));
    await act(async () => {
        await vi.advanceTimersByTimeAsync(11000);
    });
    expect(result.current.isStreaming).toBe(true);
    expect(result.current.lastFinishedAt).toBe(0);
    expect(result.current.messages.at(-1)?.text).toBe(notification.message);
});

it('maps stored agent results to ordinary visible assistant bubbles', () => {
    expect(
        persistedEventsToChatMessages([
            { role: 'assistant', ...notification },
        ])[0]
    ).toMatchObject({
        text: notification.message,
        isComplete: true,
        isUser: false,
        notification: true,
    });
});
