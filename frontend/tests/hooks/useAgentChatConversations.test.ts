// @vitest-environment jsdom
//
// Tests for the per-agent conversation history hook.
//
// Coverage goals:
//   1. Initial fetch on mount writes the list returned by the backend.
//   2. switchTo writes the conversation_key back via onSetConversationKey.
//   3. createNew mints a fresh key and writes it back; doesn't refetch
//      immediately (the new row only appears server-side after first send).
//   4. deleteOne calls the conversation:delete event, removes the row
//      locally for instant feedback, refreshes, and — if the deleted row
//      was the active thread — mints a new key so the chat moves to a
//      fresh empty thread instead of pointing at a tombstoned id.
//   5. The hook tolerates a missing workflowId (won't fetch / fail).
//   6. Cross-fetch isolation: switching to a new (workflow, node) pair
//      refetches.

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useAgentChatConversations } from '~/hooks/useAgentChatConversations';
import { DEFAULT_INTERFACE_CONV_KEY } from '~/lib/agentChat';
import { installMockSocket, MockSocket } from '../integration/helpers/mockSocket';

let socket: MockSocket;
let teardown: (() => void) | null = null;

beforeEach(() => {
  const installed = installMockSocket();
  socket = installed.socket;
  teardown = installed.teardown;
});

afterEach(() => {
  teardown?.();
  teardown = null;
});

function makeConv(key: string, overrides: Partial<{ title: string; preview: string; turn_count: number; last_activity: string }> = {}) {
  return {
    conversation_id: `ck:wf-1:node-1:${key}`,
    conversation_key: key,
    title: overrides.title ?? '',
    preview: overrides.preview ?? '',
    last_activity: overrides.last_activity ?? new Date().toISOString(),
    created_at: new Date().toISOString(),
    turn_count: overrides.turn_count ?? 0,
    agent_model: null,
  };
}

async function flushMicrotasks() {
  // Two tick boundaries: one to let sendEventAsync's response land via
  // queueMicrotask in the mock, and one for the resulting setState to commit.
  await Promise.resolve();
  await Promise.resolve();
}

describe('useAgentChatConversations', () => {
  it('fetches the conversation list on mount', async () => {
    const convs = [makeConv('thread-a'), makeConv('thread-b')];
    socket.replyTo('conversation:list_for_agent', () => ({ conversations: convs }));
    const setKey = vi.fn();
    const { result } = renderHook(() => useAgentChatConversations('wf-1', 'node-1', DEFAULT_INTERFACE_CONV_KEY, setKey));
    expect(result.current.isLoading).toBe(true);
    await act(async () => { await flushMicrotasks(); });
    expect(result.current.conversations.map(c => c.conversation_key)).toEqual(['thread-a', 'thread-b']);
    expect(result.current.isLoading).toBe(false);
    // Last sent emit was the list request, with the right workflow_id/node_id.
    const emit = socket.expectSent('conversation:list_for_agent');
    expect(emit.data).toMatchObject({ workflow_id: 'wf-1', node_id: 'node-1' });
  });

  it('does not fetch when workflowId is missing', async () => {
    const setKey = vi.fn();
    renderHook(() => useAgentChatConversations(undefined, 'node-1', undefined, setKey));
    await act(async () => { await flushMicrotasks(); });
    expect(socket.hasSent('conversation:list_for_agent')).toBe(false);
  });

  it('switchTo writes the chosen key back', async () => {
    socket.replyTo('conversation:list_for_agent', () => ({ conversations: [] }));
    const setKey = vi.fn();
    const { result } = renderHook(() => useAgentChatConversations('wf-1', 'node-1', DEFAULT_INTERFACE_CONV_KEY, setKey));
    await act(async () => { await flushMicrotasks(); });
    act(() => { result.current.switchTo('thread-x'); });
    expect(setKey).toHaveBeenCalledWith('thread-x');
  });

  it('createNew mints a fresh key and writes it back', async () => {
    socket.replyTo('conversation:list_for_agent', () => ({ conversations: [] }));
    const setKey = vi.fn();
    const { result } = renderHook(() => useAgentChatConversations('wf-1', 'node-1', DEFAULT_INTERFACE_CONV_KEY, setKey));
    await act(async () => { await flushMicrotasks(); });
    let minted = '';
    act(() => { minted = result.current.createNew(); });
    expect(minted.startsWith(`${DEFAULT_INTERFACE_CONV_KEY}_`)).toBe(true);
    expect(setKey).toHaveBeenCalledWith(minted);
    expect(setKey).toHaveBeenCalledTimes(1);
  });

  it('deleteOne calls conversation:delete, removes the row locally, and refetches', async () => {
    const start = [makeConv('thread-a'), makeConv('thread-b')];
    let listResponse = { conversations: start };
    socket.replyTo('conversation:list_for_agent', () => listResponse);
    socket.replyTo('conversation:delete', () => ({ success: true }));
    const setKey = vi.fn();
    const { result } = renderHook(() => useAgentChatConversations('wf-1', 'node-1', 'thread-a', setKey));
    await act(async () => { await flushMicrotasks(); });
    expect(result.current.conversations).toHaveLength(2);

    // Server will now return only thread-b on next list.
    listResponse = { conversations: [makeConv('thread-b')] };

    await act(async () => {
      await result.current.deleteOne(start[0]);
      await flushMicrotasks();
    });
    expect(socket.expectSent('conversation:delete').data).toMatchObject({ conversation_id: 'ck:wf-1:node-1:thread-a' });
    expect(result.current.conversations.map(c => c.conversation_key)).toEqual(['thread-b']);
  });

  it('deleting the active thread mints a fresh key', async () => {
    const start = [makeConv('thread-a')];
    socket.replyTo('conversation:list_for_agent', () => ({ conversations: start }));
    socket.replyTo('conversation:delete', () => ({ success: true }));
    const setKey = vi.fn();
    const { result } = renderHook(() => useAgentChatConversations('wf-1', 'node-1', 'thread-a', setKey));
    await act(async () => { await flushMicrotasks(); });

    await act(async () => {
      await result.current.deleteOne(start[0]);
      await flushMicrotasks();
    });
    expect(setKey).toHaveBeenCalledTimes(1);
    const newKey = setKey.mock.calls[0][0];
    expect(newKey.startsWith(`${DEFAULT_INTERFACE_CONV_KEY}_`)).toBe(true);
  });

  it('deleting a NON-active thread leaves the active key alone', async () => {
    const start = [makeConv('thread-a'), makeConv('thread-b')];
    socket.replyTo('conversation:list_for_agent', () => ({ conversations: start }));
    socket.replyTo('conversation:delete', () => ({ success: true }));
    const setKey = vi.fn();
    const { result } = renderHook(() => useAgentChatConversations('wf-1', 'node-1', 'thread-a', setKey));
    await act(async () => { await flushMicrotasks(); });

    await act(async () => {
      await result.current.deleteOne(start[1]); // delete thread-b, but thread-a is active
      await flushMicrotasks();
    });
    expect(setKey).not.toHaveBeenCalled();
  });

  it('switching (workflow, node) pair refetches', async () => {
    let callCount = 0;
    socket.replyTo('conversation:list_for_agent', () => {
      callCount += 1;
      return { conversations: [] };
    });
    const setKey = vi.fn();
    const { rerender } = renderHook(
      ({ wf, node }: { wf: string; node: string }) =>
        useAgentChatConversations(wf, node, DEFAULT_INTERFACE_CONV_KEY, setKey),
      { initialProps: { wf: 'wf-1', node: 'node-1' } },
    );
    await act(async () => { await flushMicrotasks(); });
    expect(callCount).toBe(1);

    rerender({ wf: 'wf-2', node: 'node-1' });
    await act(async () => { await flushMicrotasks(); });
    expect(callCount).toBe(2);

    // Same pair again — should NOT refetch.
    rerender({ wf: 'wf-2', node: 'node-1' });
    await act(async () => { await flushMicrotasks(); });
    expect(callCount).toBe(2);
  });
});
