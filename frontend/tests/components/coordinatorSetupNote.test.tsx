// @vitest-environment jsdom
// A workflow picked on an /agents page or /mcp is finished in the chat: NoClick's note carries a `setup` reference,
// live (the frame the backend's emit_notification sends) and from the saved thread alike, and the transcript draws
// the card the platform registered under it, never folding it into a run of background notes.
import { act, cleanup, render, renderHook, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it } from 'vitest';
import { CoordinatorTranscript } from '~/components/coordinator/CoordinatorTranscript';
import { registerSetupCard } from '~/components/coordinator/toolCards';
import { updatesOf } from '~/components/coordinator/updates';
import { persistedEventsToChatMessages, useAgentChat, type AgentChatMessage } from '~/hooks/useAgentChat';
import { resetAgentChatSessions } from '~/lib/agentChatSessionStore';
import { installMockSocket, type MockSocket } from '../integration/helpers/mockSocket';

const cid = 'coordinator:test-setup';
const setup = { kind: 'mcp' as const, workflow_id: '7b0c3c1e-4e2a-4f7e-9a51-0d6f3b2a1c11', client: 'opencode' };
// Exactly what emit_notification sends (model_dump, exclude_none).
const frame = { conversation_id: cid, message: 'Let’s finish setting up Slack for OpenCode.', finished: true, notification: true, turn_id: `setup:${setup.workflow_id}`, setup };

let socket: MockSocket;
let teardown: () => void;

beforeEach(() => {
    resetAgentChatSessions();
    ({ socket, teardown } = installMockSocket());
    socket.replyTo('conversation:resume', () => ({ messages: [] }));
});
afterEach(() => {
    cleanup();
    teardown();
});

it('carries the setup reference live and from the saved thread', async () => {
    const { result } = renderHook(() => useAgentChat(cid));
    await act(async () => {});
    act(() => socket.serverEmit('chat:message', frame));
    act(() => socket.serverEmit('chat:message', frame)); // a redelivery is the same note
    expect(result.current.messages).toHaveLength(1);
    expect(result.current.messages[0].setup).toEqual(setup);
    expect(result.current.isStreaming).toBe(false);

    const [restored] = persistedEventsToChatMessages([
        { role: 'assistant', message: frame.message, turn_id: frame.turn_id, notification: true, setup, timestamp: '2026-10-07T00:00:00Z' },
    ]);
    expect(restored.setup).toEqual(setup);
});

it('never folds a setup note into the background notes around it', () => {
    const note = (text: string): AgentChatMessage => ({ isUser: false, text, isComplete: true, notification: true });
    const messages = [note('A run failed.'), { ...note(frame.message), setup }, note('Another run failed.')];
    expect(updatesOf(messages).has(1)).toBe(false);
});

it('folds a setup card once a newer one is about the same automation, saying what replaced it', async () => {
    registerSetupCard(({ setup: s, newer }) => <p>{`${s.workflow_id} for ${s.client}: ${newer ? `folded, now ${newer.setup?.client}` : 'open'}`}</p>);
    const other = { kind: 'mcp' as const, workflow_id: 'wf-other', client: 'cursor' };
    const note = (s: typeof setup): AgentChatMessage => ({ isUser: false, text: 'Set up.', isComplete: true, notification: true, setup: s });
    const messages: AgentChatMessage[] = [
        note(setup),
        note(other),
        { isUser: true, text: 'Can I connect this to Codex instead?', isComplete: true },
        note({ ...setup, client: 'codex' }),
        { isUser: false, text: 'Switched it to Codex, the command is in the card above.', isComplete: true },
    ];
    render(<CoordinatorTranscript messages={messages} isStreaming={false} errorReason={null} />);
    expect(await screen.findByText(`${setup.workflow_id} for opencode: folded, now codex`)).toBeTruthy();
    expect(screen.getByText(`${setup.workflow_id} for codex: open`)).toBeTruthy();
    expect(screen.getByText('wf-other for cursor: open')).toBeTruthy();
});

it('draws the registered card under a setup note', async () => {
    registerSetupCard(({ setup: s }) => <p>Setting up {s.workflow_id}</p>);
    const messages: AgentChatMessage[] = [{ isUser: false, text: frame.message, isComplete: true, notification: true, setup }];
    render(<CoordinatorTranscript messages={messages} isStreaming={false} errorReason={null} />);
    expect(await screen.findByText(`Setting up ${setup.workflow_id}`)).toBeTruthy();
    expect(screen.getByText(frame.message)).toBeTruthy();
});
