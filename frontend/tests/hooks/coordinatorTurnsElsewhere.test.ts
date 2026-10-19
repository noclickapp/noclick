// @vitest-environment jsdom
// A turn that comes in on another app (a text, a call, an email) shows up in the open coordinator chat without a
// reload: the backend announces it (agent:state running) once the incoming message is saved and mirrors its end
// once the reply is saved, and the chat reads the turn back from the transcript at both points.
import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, expect, it } from 'vitest';
import { useAgentChat } from '~/hooks/useAgentChat';
import { resetAgentChatSessions } from '~/lib/agentChatSessionStore';
import { installMockSocket, type MockSocket } from '../integration/helpers/mockSocket';

let socket: MockSocket;
let teardown: () => void;
const cid = 'coordinator:test-elsewhere';
const earlier = [
    { role: 'user', message: 'Remind me at 6', timestamp: '2026-10-06T09:00:00Z' },
    { role: 'assistant', message: 'Set for 6pm.', timestamp: '2026-10-06T09:00:05Z' },
];
const texted = { role: 'user', message: 'Hey', channel: 'whatsapp_text', wamid: 'wamid.1', timestamp: '2026-10-06T12:38:00Z' };
const replied = { role: 'assistant', message: 'Hey! What can I do?', channel: 'whatsapp_text', timestamp: '2026-10-06T12:38:04Z' };
let saved: unknown[];

beforeEach(() => {
    resetAgentChatSessions();
    ({ socket, teardown } = installMockSocket());
    saved = [...earlier];
    socket.replyTo('conversation:resume', () => ({ messages: saved }));
});
afterEach(() => {
    cleanup();
    teardown();
});

it('follows a turn from WhatsApp from the message that started it to the saved reply', async () => {
    const { result } = renderHook(() => useAgentChat(cid, undefined, false, true));
    await act(async () => {});
    expect(result.current.messages.map((m) => m.text)).toEqual(['Remind me at 6', 'Set for 6pm.']);

    saved = [...earlier, texted];
    await act(async () => socket.serverEmit('agent:state', { state: 'running', conversation_id: cid }));
    expect(result.current.isStreaming).toBe(true);
    expect(result.current.messages.at(-1)).toMatchObject({ isUser: true, text: 'Hey', channel: 'whatsapp_text' });

    // Its steps are mirrored live; its end comes once the reply is saved.
    act(() =>
        socket.serverEmit('chat:message', {
            conversation_id: cid,
            agentic_steps: [{ id: 'c1', text: 'Calling list_runs({})', status: 'in_progress' }],
        })
    );
    expect(result.current.messages.at(-1)?.steps?.[0]?.id).toBe('c1');
    saved = [...earlier, texted, replied];
    await act(async () => socket.serverEmit('chat:message', { conversation_id: cid, finished: true }));
    expect(result.current.isStreaming).toBe(false);
    expect(result.current.messages.map((m) => [m.text, m.channel])).toEqual([
        ['Remind me at 6', undefined],
        ['Set for 6pm.', undefined],
        ['Hey', 'whatsapp_text'],
        ['Hey! What can I do?', 'whatsapp_text'],
    ]);
});

it('leaves a chat that does not take turns from other apps as it was', async () => {
    const { result } = renderHook(() => useAgentChat(cid));
    await act(async () => {});
    saved = [...earlier, texted];
    await act(async () => socket.serverEmit('agent:state', { state: 'running', conversation_id: cid }));
    expect(result.current.isStreaming).toBe(false);
    expect(result.current.messages).toHaveLength(2);
});

it('does not take over a turn this chat sent itself', async () => {
    const { result } = renderHook(() => useAgentChat(cid, undefined, false, true));
    await act(async () => {});
    act(() => result.current.addUserMessage('What failed today?'));
    saved = [...earlier, { role: 'user', message: 'What failed today?' }];
    await act(async () => socket.serverEmit('agent:state', { state: 'running', conversation_id: cid }));
    expect(result.current.messages.at(-1)).toMatchObject({ isUser: true, text: 'What failed today?' });
    expect(result.current.messages).toHaveLength(3);
});
