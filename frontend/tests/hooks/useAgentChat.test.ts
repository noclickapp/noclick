// @vitest-environment jsdom
//
// Tests for the AgentChatBlock's live message store.
//
// Coverage goals — the things that recently broke:
//   1. User sends a message → it shows up in the transcript immediately.
//   2. Backend streams chat:message events → text accumulates into ONE agent
//      bubble (not one bubble per chunk).
//   3. `finished: true` closes the bubble; the next chat:message starts a new
//      one.
//   4. Conversation isolation: a chat:message for conversation A never lands
//      in conversation B's transcript.
//   5. Parametric coverage across the agent model spectrum (gpt-4o-mini,
//      claude-code, openclaw, hermes, …) — same wire shape, different
//      ids, with one frontend contract across the available runtimes.

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { renderHook, act, cleanup } from '@testing-library/react';
import {
    applyChatMessageEvent,
    persistedEventsToChatMessages,
    useAgentChat,
    type AgentChatMessage,
} from '~/hooks/useAgentChat';
import {
    agentChatSessionStore,
    getAgentChatSession,
    resetAgentChatSessions,
} from '~/lib/agentChatSessionStore';
import {
    installMockSocket,
    MockSocket,
} from '../integration/helpers/mockSocket';

let socket: MockSocket;
let teardown: (() => void) | null = null;

beforeEach(() => {
    // Session state is a MODULE-LEVEL store (survives unmounts by design) —
    // isolate tests from each other explicitly.
    resetAgentChatSessions();
    const installed = installMockSocket();
    socket = installed.socket;
    teardown = installed.teardown;
    // Stub the resume call so the hook's effect resolves without hanging the test.
    socket.replyTo('conversation:resume', () => ({
        session_id: '',
        messages: [],
        workflow_id: null,
    }));
});

afterEach(() => {
    // Unmount every rendered hook BEFORE tearing the socket down: with session
    // state in a shared module store, a leaked listener from a previous test's
    // still-mounted hook would now WRITE into the next test's session (with
    // component state it only warned about dead setState).
    cleanup();
    teardown?.();
    teardown = null;
});

const MODEL_VARIANTS = [
    'openrouter/openai/gpt-4o-mini',
    'openrouter/anthropic/claude-3.5-sonnet',
    'codex',
    'claude-code',
    'opencode',
    'openclaw',
    'hermes',
] as const;

function emitChat(
    conversationId: string,
    payload: {
        message?: string;
        finished?: boolean;
        content?: unknown;
        status?: string;
        role?: string;
        agentic_steps?: Array<{ id: string; text: string; status: string }>;
    }
) {
    socket.serverEmit('chat:message', {
        conversation_id: conversationId,
        ...payload,
    });
}

function emitAgentState(
    conversationId: string,
    state: string,
    reason?: string
) {
    socket.serverEmit('agent:state', {
        conversation_id: conversationId,
        state,
        ...(reason ? { reason } : {}),
    });
}

describe('persistedEventsToChatMessages — restore transcript from legacy event stream', () => {
    // The conversation:resume handler may return the legacy event stream shape
    // (action/source/args/message) for pre-Phase-9 rows, NOT chat-style
    // {role, message, content}.
    // This mapper has to extract only the visible chat turns and unwrap the
    // `__NOCLICK_SEQUENCE__:[...]` payload that user messages are stored as.
    // Regression guard: representative legacy event shapes.

    it('drops internal-machinery events (system, recall, think, environment observations)', () => {
        const events = [
            {
                action: 'system',
                source: 'agent',
                message: 'You are a helpful assistant.',
            },
            { action: 'recall', source: 'user', args: { query: 'something' } },
            {
                action: 'think',
                source: 'agent',
                args: { thought: 'pondering' },
            },
            { action: undefined, source: 'environment' },
            {
                action: undefined,
                source: 'agent',
                message: 'Your thought has been logged.',
            },
        ];
        expect(persistedEventsToChatMessages(events)).toEqual([]);
    });

    it('keeps only message:user and message:agent events as transcript bubbles', () => {
        const events = [
            { action: 'system', source: 'agent', message: 'sys' },
            {
                action: 'message',
                source: 'user',
                args: { content: 'hi' },
                message: 'hi',
            },
            { action: 'think', source: 'agent', args: { thought: 'hmm' } },
            {
                action: 'message',
                source: 'agent',
                args: { content: 'hello back' },
                message: 'hello back',
            },
        ];
        const result = persistedEventsToChatMessages(events);
        expect(result).toEqual([
            { isUser: true, text: 'hi', isComplete: true, content: undefined },
            {
                isUser: false,
                text: 'hello back',
                isComplete: true,
                content: undefined,
            },
        ]);
    });

    it('unwraps __NOCLICK_SEQUENCE__ user payloads into plain text', () => {
        const events = [
            {
                action: 'message',
                source: 'user',
                args: {
                    content:
                        '__NOCLICK_SEQUENCE__:[{"type":"text","text":"hey buddy","image_url":null,"metadata":null}]',
                },
                message:
                    '__NOCLICK_SEQUENCE__:[{"type":"text","text":"hey buddy","image_url":null,"metadata":null}]',
            },
        ];
        const [m] = persistedEventsToChatMessages(events);
        expect(m.isUser).toBe(true);
        expect(m.text).toBe('hey buddy');
        expect(m.content).toEqual([{ type: 'text', text: 'hey buddy' }]);
    });

    it('preserves image content from __NOCLICK_SEQUENCE__ payloads', () => {
        const seq = [
            {
                type: 'text',
                text: 'look at this',
                image_url: null,
                metadata: null,
            },
            {
                type: 'image_url',
                text: null,
                image_url: { url: 'https://x/y.png' },
                metadata: null,
            },
        ];
        const events = [
            {
                action: 'message',
                source: 'user',
                args: {
                    content: `__NOCLICK_SEQUENCE__:${JSON.stringify(seq)}`,
                },
            },
        ];
        const [m] = persistedEventsToChatMessages(events);
        expect(m.text).toBe('look at this');
        expect(m.content).toEqual([
            { type: 'text', text: 'look at this' },
            { type: 'image_url', image_url: { url: 'https://x/y.png' } },
        ]);
    });

    it('falls back to the raw string if __NOCLICK_SEQUENCE__ is malformed', () => {
        const events = [
            {
                action: 'message',
                source: 'user',
                args: { content: '__NOCLICK_SEQUENCE__:not-json' },
            },
        ];
        const [m] = persistedEventsToChatMessages(events);
        expect(m.text).toBe('__NOCLICK_SEQUENCE__:not-json');
    });

    it('drops empty events (no content and no message)', () => {
        const events = [
            { action: 'message', source: 'user', args: { content: '' } },
            { action: 'message', source: 'agent', args: { content: '' } },
        ];
        expect(persistedEventsToChatMessages(events)).toEqual([]);
    });

    it('extracts agent_state_changed:error as an inline error bubble', () => {
        const events = [
            {
                action: 'message',
                source: 'user',
                args: { content: 'do the thing' },
            },
            {
                observation: 'agent_state_changed',
                source: 'environment',
                args: {
                    agent_state: 'error',
                    reason: 'NotFoundError: provider 404',
                },
            },
        ];
        const result = persistedEventsToChatMessages(events);
        expect(result).toHaveLength(2);
        expect(result[0]).toMatchObject({ isUser: true, text: 'do the thing' });
        expect(result[1]).toMatchObject({
            isUser: false,
            error: 'NotFoundError: provider 404',
            isComplete: true,
        });
    });

    it('skips non-error agent_state_changed transitions', () => {
        const events = [
            {
                observation: 'agent_state_changed',
                args: { agent_state: 'running' },
            },
            {
                observation: 'agent_state_changed',
                args: { agent_state: 'awaiting_user_input' },
            },
            {
                observation: 'agent_state_changed',
                args: { agent_state: 'stopped' },
            },
        ];
        expect(persistedEventsToChatMessages(events)).toEqual([]);
    });

    it('skips agent_state_changed:error with no reason', () => {
        const events = [
            {
                observation: 'agent_state_changed',
                args: { agent_state: 'error', reason: '' },
            },
        ];
        expect(persistedEventsToChatMessages(events)).toEqual([]);
    });

    it('extracts action:error (the CLI runner shape) as an inline error bubble', () => {
        const events = [
            { action: 'message', source: 'user', args: { content: 'go' } },
            {
                action: 'error',
                source: 'agent',
                args: { reason: 'Codex execution failed: token refresh' },
                message: 'Codex execution failed: token refresh',
            },
        ];
        const result = persistedEventsToChatMessages(events);
        expect(result).toHaveLength(2);
        expect(result[1]).toMatchObject({
            isUser: false,
            error: 'Codex execution failed: token refresh',
            isComplete: true,
        });
    });

    it('full conversation round-trip for a multi-event fixture', () => {
        // Synthetic stream covering the persisted-event shapes.
        const events = [
            {
                id: 0,
                action: 'system',
                source: 'agent',
                message: 'You are a helpful assistant.',
            },
            {
                id: 1,
                action: 'message',
                source: 'user',
                args: {
                    content:
                        '__NOCLICK_SEQUENCE__:[{"type":"text","text":"hey buddy","image_url":null,"metadata":null}]',
                },
            },
            { id: 2, action: 'recall', source: 'user', args: { query: '...' } },
            { id: 3, source: 'environment' },
            {
                id: 4,
                action: 'think',
                source: 'agent',
                args: { thought: '...' },
            },
            {
                id: 5,
                source: 'agent',
                message: 'Your thought has been logged.',
            },
            {
                id: 6,
                action: 'message',
                source: 'agent',
                args: {
                    content: 'Hey there! 👋 What can I help you with today?',
                },
                message: 'Hey there! 👋 What can I help you with today?',
            },
            {
                id: 7,
                action: 'message',
                source: 'user',
                args: {
                    content:
                        '__NOCLICK_SEQUENCE__:[{"type":"text","text":"whats up","image_url":null,"metadata":null}]',
                },
            },
            {
                id: 8,
                action: 'message',
                source: 'agent',
                args: { content: 'Not much! Just here and ready to help.' },
            },
        ];
        const result = persistedEventsToChatMessages(events);
        expect(result.map((m) => ({ user: m.isUser, text: m.text }))).toEqual([
            { user: true, text: 'hey buddy' },
            {
                user: false,
                text: 'Hey there! 👋 What can I help you with today?',
            },
            { user: true, text: 'whats up' },
            { user: false, text: 'Not much! Just here and ready to help.' },
        ]);
    });

    it('handles undefined / non-array gracefully', () => {
        expect(persistedEventsToChatMessages(undefined)).toEqual([]);
        expect(
            persistedEventsToChatMessages(null as unknown as undefined)
        ).toEqual([]);
    });

    it("restores an assistant turn's tool timeline as completed step rows (legacy shape)", () => {
        // CLI turns persist a compacted tool timeline with the assistant event;
        // reload must rebuild the bubble's steps (they only streamed live before).
        const events = [
            {
                action: 'message',
                source: 'user',
                args: { content: 'file a bug' },
            },
            {
                action: 'message',
                source: 'agent',
                args: { content: 'Filed LIN-482.' },
                message: 'Filed LIN-482.',
                tool_calls: [
                    {
                        tool_name: 'linear__create_issue',
                        arguments_preview: '{"title": "Bug"}',
                        result_status: 'success',
                        result_preview: '{"issue_id": "LIN-482"}',
                        duration_ms: 2000,
                        created_at: '2026-07-17T06:00:02+00:00',
                    },
                ],
            },
        ];
        const [, agent] = persistedEventsToChatMessages(events);
        expect(agent.steps).toHaveLength(1);
        expect(agent.steps![0]).toMatchObject({
            // Wire-format title so the renderer's humanizer/expander apply.
            title: 'Calling linear__create_issue({"title": "Bug"})',
            detail: '{"issue_id": "LIN-482"}',
            status: 'completed',
            kind: 'tool',
        });
        // Real timing restored: endedAt from created_at, startedAt backed off by duration.
        expect(agent.steps![0].endedAt! - agent.steps![0].startedAt).toBe(2000);
    });

    it('restores tool timelines on the post-Phase-9 {role} shape and skips malformed rows', () => {
        const events = [
            {
                role: 'assistant',
                message: 'ok',
                tool_calls: [
                    {
                        tool_name: 'slack__send_message',
                        arguments_preview: '{}',
                    },
                    { no_name: true },
                    'garbage',
                ],
            },
        ];
        const [agent] = persistedEventsToChatMessages(events as never);
        expect(agent.steps).toHaveLength(1);
        expect(agent.steps![0].title).toBe('Calling slack__send_message({})');
    });

    it('leaves steps undefined when no tool timeline was persisted', () => {
        const [agent] = persistedEventsToChatMessages([
            { role: 'assistant', message: 'plain' },
        ]);
        expect(agent.steps).toBeUndefined();
    });

    it('restores an assistant turn with generated images (image gen fast-path)', () => {
        // image / kling handlers persist {role:'assistant', message, image_urls}
        // via agent_node._persist_interface_chat_event. The mapper must surface
        // those URLs as image_url content items so reload shows the image.
        const events = [
            { role: 'user', message: 'a red bicycle' },
            {
                role: 'assistant',
                message: 'Here is your image.',
                image_urls: ['https://r2/a.png'],
            },
        ];
        const result = persistedEventsToChatMessages(events);
        expect(result).toEqual([
            {
                isUser: true,
                text: 'a red bicycle',
                isComplete: true,
                content: undefined,
            },
            {
                isUser: false,
                text: 'Here is your image.',
                isComplete: true,
                content: [
                    {
                        type: 'image_url',
                        image_url: { url: 'https://r2/a.png' },
                    },
                ],
            },
        ]);
    });

    it('restores an image-only assistant turn (no text) instead of dropping it', () => {
        // DALL-E returns no text — the assistant turn is images-only. The
        // empty-message guard must NOT drop it when image_urls are present.
        const events = [
            {
                role: 'assistant',
                message: '',
                image_urls: ['https://r2/x.png', 'https://r2/y.png'],
            },
        ];
        const result = persistedEventsToChatMessages(events);
        expect(result).toEqual([
            {
                isUser: false,
                text: '',
                isComplete: true,
                content: [
                    {
                        type: 'image_url',
                        image_url: { url: 'https://r2/x.png' },
                    },
                    {
                        type: 'image_url',
                        image_url: { url: 'https://r2/y.png' },
                    },
                ],
            },
        ]);
    });

    it('restores a plain assistant turn (no image_urls) with undefined content', () => {
        const events = [{ role: 'assistant', message: 'just text' }];
        expect(persistedEventsToChatMessages(events)).toEqual([
            {
                isUser: false,
                text: 'just text',
                isComplete: true,
                content: undefined,
            },
        ]);
    });

    it('restores an assistant turn with a generated video (video/kling fast-path)', () => {
        const events = [
            {
                role: 'assistant',
                message: 'Generated 1 video(s)',
                video_urls: ['https://r2/v.mp4'],
            },
        ];
        expect(persistedEventsToChatMessages(events)).toEqual([
            {
                isUser: false,
                text: 'Generated 1 video(s)',
                isComplete: true,
                content: [{ type: 'video_url', video_url: 'https://r2/v.mp4' }],
            },
        ]);
    });

    it('restores an assistant turn carrying both images and videos in order', () => {
        const events = [
            {
                role: 'assistant',
                message: 'media',
                image_urls: ['https://r2/a.png'],
                video_urls: ['https://r2/v.mp4'],
            },
        ];
        const [m] = persistedEventsToChatMessages(events);
        expect(m.content).toEqual([
            { type: 'image_url', image_url: { url: 'https://r2/a.png' } },
            { type: 'video_url', video_url: 'https://r2/v.mp4' },
        ]);
    });
});

describe('applyChatMessageEvent reducer', () => {
    it('opens a new agent bubble on the first event', () => {
        const next = applyChatMessageEvent([], {
            message: 'Hello',
            finished: false,
        });
        expect(next).toEqual([
            {
                isUser: false,
                text: 'Hello',
                isComplete: false,
                content: undefined,
            },
        ]);
    });

    it('accumulates streamed chunks into the in-flight agent bubble', () => {
        let state: AgentChatMessage[] = [];
        state = applyChatMessageEvent(state, {
            message: 'Hel',
            finished: false,
        });
        state = applyChatMessageEvent(state, {
            message: 'lo, ',
            finished: false,
        });
        state = applyChatMessageEvent(state, {
            message: 'world.',
            finished: true,
        });
        expect(state).toHaveLength(1);
        expect(state[0]).toMatchObject({
            isUser: false,
            text: 'Hello, world.',
            isComplete: true,
        });
    });

    it('starts a fresh agent bubble after the previous one finished', () => {
        let state: AgentChatMessage[] = [];
        state = applyChatMessageEvent(state, {
            message: 'First turn',
            finished: true,
        });
        state = applyChatMessageEvent(state, {
            message: 'Second turn ',
            finished: false,
        });
        state = applyChatMessageEvent(state, {
            message: 'continues.',
            finished: true,
        });
        expect(state).toHaveLength(2);
        expect(state[0].text).toBe('First turn');
        expect(state[1].text).toBe('Second turn continues.');
        expect(state.every((m) => m.isComplete)).toBe(true);
    });

    it('does NOT merge into a preceding user message', () => {
        let state: AgentChatMessage[] = [
            { isUser: true, text: 'hi', isComplete: true },
        ];
        state = applyChatMessageEvent(state, {
            message: 'Hello back',
            finished: true,
        });
        expect(state).toHaveLength(2);
        expect(state[0].isUser).toBe(true);
        expect(state[1].isUser).toBe(false);
        expect(state[1].text).toBe('Hello back');
    });

    it('captures status on the in-flight agent bubble (and folds it into the timeline)', () => {
        let state: AgentChatMessage[] = [];
        state = applyChatMessageEvent(state, {
            status: 'Starting sandbox…',
            finished: false,
        });
        expect(state).toHaveLength(1);
        expect(state[0]).toMatchObject({
            isUser: false,
            text: '',
            isComplete: false,
            status: 'Starting sandbox…',
        });
        expect(state[0].steps).toHaveLength(1);
        expect(state[0].steps![0]).toMatchObject({
            title: 'Starting sandbox…',
            kind: 'status',
            status: 'in_progress',
        });
    });

    it('updates status as new in-flight chunks arrive', () => {
        let state: AgentChatMessage[] = [];
        state = applyChatMessageEvent(state, {
            status: 'Starting sandbox (noclick-codex)…',
            finished: false,
        });
        state = applyChatMessageEvent(state, {
            status: 'Sandbox ready, running agent…',
            finished: false,
        });
        expect(state).toHaveLength(1);
        expect(state[0].status).toBe('Sandbox ready, running agent…');
        expect(state[0].text).toBe('');
    });

    it('clears status once the agent starts streaming actual text', () => {
        let state: AgentChatMessage[] = [];
        state = applyChatMessageEvent(state, {
            status: 'Starting sandbox…',
            finished: false,
        });
        expect(state[0].status).toBe('Starting sandbox…');
        state = applyChatMessageEvent(state, {
            message: 'Hello',
            finished: false,
        });
        expect(state[0].text).toBe('Hello');
        expect(state[0].status).toBeUndefined();
    });

    it('clears status once finished:true lands', () => {
        let state: AgentChatMessage[] = [];
        state = applyChatMessageEvent(state, {
            status: 'Starting sandbox…',
            finished: false,
        });
        state = applyChatMessageEvent(state, {
            message: 'Done.',
            finished: true,
        });
        expect(state[0].status).toBeUndefined();
        expect(state[0].isComplete).toBe(true);
    });

    it('replaces content when a chunk carries a fresh content[] array', () => {
        const content = [
            { type: 'image_url', image_url: { url: 'https://x/y.png' } },
        ] as const;
        let state: AgentChatMessage[] = [];
        state = applyChatMessageEvent(state, {
            message: 'Look:',
            finished: false,
        });
        state = applyChatMessageEvent(state, {
            message: ' done.',
            finished: true,
            content: content as unknown as never,
        });
        expect(state[0].content).toEqual(content);
        expect(state[0].text).toBe('Look: done.');
    });
});

describe('applyChatMessageEvent — activity timeline (steps)', () => {
    // Tool calls stream as ChatMessageEvent.agentic_steps (SDK agents emit them
    // from the run loop; CLI-harness calls arrive through the local turn-scoped
    // MCP endpoint). The reducer folds them — plus status milestones — into an
    // id-keyed per-bubble timeline the transcript renders live.
    const toolStart = {
        id: 'call-1',
        text: 'Calling linear__create_issue({"title":"Bug"})',
        status: 'in_progress',
    };
    const toolDone = {
        id: 'call-1',
        text: '{"success": true, "issue_id": "LIN-1"}',
        status: 'completed',
    };

    it('creates a tool step from an agentic_steps in_progress frame', () => {
        const state = applyChatMessageEvent([], {
            agentic_steps: [toolStart] as never,
        });
        expect(state).toHaveLength(1);
        expect(state[0].steps).toHaveLength(1);
        expect(state[0].steps![0]).toMatchObject({
            id: 'call-1',
            title: 'Calling linear__create_issue({"title":"Bug"})',
            kind: 'tool',
            status: 'in_progress',
        });
    });

    it('completes a tool step in place — title kept, result stashed as detail', () => {
        let state = applyChatMessageEvent([], {
            agentic_steps: [toolStart] as never,
        });
        state = applyChatMessageEvent(state, {
            agentic_steps: [toolDone] as never,
        });
        expect(state[0].steps).toHaveLength(1);
        expect(state[0].steps![0]).toMatchObject({
            id: 'call-1',
            title: 'Calling linear__create_issue({"title":"Bug"})',
            detail: '{"success": true, "issue_id": "LIN-1"}',
            status: 'completed',
        });
    });

    it('drops a late in_progress re-emit for an already-completed step (relay reorder)', () => {
        let state = applyChatMessageEvent([], {
            agentic_steps: [toolStart] as never,
        });
        state = applyChatMessageEvent(state, {
            agentic_steps: [toolDone] as never,
        });
        state = applyChatMessageEvent(state, {
            agentic_steps: [toolStart] as never,
        });
        expect(state[0].steps).toHaveLength(1);
        expect(state[0].steps![0].status).toBe('completed');
    });

    it('a completion frame whose start was missed lands with a generic title, result as detail', () => {
        // The completed frame's text is the RESULT preview — rendering it as the
        // row label showed a raw JSON blob (start frame lost to a relay hiccup).
        const state = applyChatMessageEvent([], {
            agentic_steps: [toolDone] as never,
        });
        expect(state[0].steps![0]).toMatchObject({
            id: 'call-1',
            status: 'completed',
            title: 'Tool call',
            detail: '{"success": true, "issue_id": "LIN-1"}',
        });
    });

    it("does NOT fold a terminal frame's status sentinel into the timeline", () => {
        // A CLI terminal frame is {status:"completed", finished:true, message};
        // folding its status appended a spurious checkmarked row
        // literally labeled "completed" on every CLI turn.
        let state = applyChatMessageEvent([], { status: 'Agent is working…' });
        state = applyChatMessageEvent(state, {
            agentic_steps: [toolStart] as never,
        });
        state = applyChatMessageEvent(state, {
            message: 'All done.',
            status: 'completed',
            finished: true,
        });
        const titles = state[0].steps!.map((s) => s.title);
        expect(titles).toEqual([
            'Agent is working…',
            'Calling linear__create_issue({"title":"Bug"})',
        ]);
        expect(state[0].steps!.every((s) => s.status === 'completed')).toBe(
            true
        );
    });

    it('re-activates a recurring status instead of duplicating it (Thinking → Retrying → Thinking)', () => {
        let state = applyChatMessageEvent([], { status: 'Thinking' });
        state = applyChatMessageEvent(state, { status: 'Retrying' });
        state = applyChatMessageEvent(state, { status: 'Thinking' });
        const statusRows = state[0].steps!.filter((s) => s.kind === 'status');
        expect(statusRows.map((r) => [r.title, r.status])).toEqual([
            ['Thinking', 'in_progress'],
            ['Retrying', 'completed'],
        ]);
    });

    it('a text-only delta on a settled timeline returns the SAME steps array (no realloc)', () => {
        let state = applyChatMessageEvent([], {
            agentic_steps: [toolStart] as never,
        });
        state = applyChatMessageEvent(state, {
            agentic_steps: [toolDone] as never,
        });
        const settled = state[0].steps;
        state = applyChatMessageEvent(state, { message: 'streaming ' });
        state = applyChatMessageEvent(state, { message: 'tokens' });
        expect(state[0].steps).toBe(settled);
    });

    it('folds a late completion frame for a known id into the already-closed bubble (no ghost)', () => {
        // A delayed completed-step frame can land after the terminal frame. It
        // must update the
        // closed bubble's row, not spawn a ghost bubble.
        let state = applyChatMessageEvent([], {
            agentic_steps: [toolStart] as never,
        });
        state = applyChatMessageEvent(state, {
            message: 'Created it.',
            finished: true,
        });
        expect(state).toHaveLength(1);
        state = applyChatMessageEvent(state, {
            agentic_steps: [toolDone] as never,
        });
        expect(state).toHaveLength(1);
        expect(state[0].isComplete).toBe(true);
        expect(state[0].steps![0]).toMatchObject({
            id: 'call-1',
            detail: '{"success": true, "issue_id": "LIN-1"}',
        });
    });

    it('a steps frame with an UNKNOWN id after a closed bubble still opens a new bubble (new turn)', () => {
        let state = applyChatMessageEvent([], {
            message: 'First answer.',
            finished: true,
        });
        state = applyChatMessageEvent(state, {
            agentic_steps: [
                {
                    id: 'call-9',
                    text: 'Calling slack__send_message({})',
                    status: 'in_progress',
                },
            ] as never,
        });
        expect(state).toHaveLength(2);
        expect(state[1].isComplete).toBe(false);
        expect(state[1].steps![0].id).toBe('call-9');
    });

    it('a new status milestone completes the previous one', () => {
        let state = applyChatMessageEvent([], { status: 'Starting sandbox…' });
        state = applyChatMessageEvent(state, {
            status: 'Sandbox ready, starting agent…',
        });
        const steps = state[0].steps!;
        expect(steps.map((s) => [s.title, s.status])).toEqual([
            ['Starting sandbox…', 'completed'],
            ['Sandbox ready, starting agent…', 'in_progress'],
        ]);
    });

    it('dedupes repeated identical statuses (reasoning models re-emit "Thinking" per delta)', () => {
        let state = applyChatMessageEvent([], { status: 'Thinking' });
        state = applyChatMessageEvent(state, { status: 'Thinking' });
        state = applyChatMessageEvent(state, { status: 'Thinking' });
        expect(state[0].steps).toHaveLength(1);
    });

    it('text streaming resolves status rows but leaves running tool rows alone', () => {
        let state = applyChatMessageEvent([], { status: 'Agent is working…' });
        state = applyChatMessageEvent(state, {
            agentic_steps: [toolStart] as never,
        });
        state = applyChatMessageEvent(state, { message: 'Working on it — ' });
        const steps = state[0].steps!;
        expect(steps.find((s) => s.kind === 'status')!.status).toBe(
            'completed'
        );
        expect(steps.find((s) => s.kind === 'tool')!.status).toBe(
            'in_progress'
        );
    });

    it('a tool call starting resolves running status milestones (no double spinner)', () => {
        let state = applyChatMessageEvent([], { status: 'Agent is working…' });
        state = applyChatMessageEvent(state, {
            agentic_steps: [toolStart] as never,
        });
        const steps = state[0].steps!;
        expect(steps.find((s) => s.kind === 'status')!.status).toBe(
            'completed'
        );
        expect(steps.find((s) => s.kind === 'tool')!.status).toBe(
            'in_progress'
        );
    });

    it('finished:true resolves every running step', () => {
        let state = applyChatMessageEvent([], {
            agentic_steps: [toolStart] as never,
        });
        state = applyChatMessageEvent(state, {
            message: 'Done.',
            finished: true,
        });
        expect(state[0].steps!.every((s) => s.status === 'completed')).toBe(
            true
        );
        expect(state[0].isComplete).toBe(true);
    });

    it('steps interleave with streamed text on the SAME bubble', () => {
        let state = applyChatMessageEvent([], { message: 'Let me check. ' });
        state = applyChatMessageEvent(state, {
            agentic_steps: [toolStart] as never,
        });
        state = applyChatMessageEvent(state, {
            agentic_steps: [toolDone] as never,
        });
        state = applyChatMessageEvent(state, {
            message: 'Created LIN-1.',
            finished: true,
        });
        expect(state).toHaveLength(1);
        expect(state[0].text).toBe('Let me check. Created LIN-1.');
        expect(state[0].steps).toHaveLength(1);
    });
});

describe('useAgentChat — live ingest', () => {
    it('addUserMessage appends a user bubble and flips isStreaming on', async () => {
        const { result } = renderHook(() => useAgentChat('conv-1'));
        expect(result.current.messages).toEqual([]);
        act(() => {
            result.current.addUserMessage('hello');
        });
        expect(result.current.messages).toEqual([
            {
                isUser: true,
                text: 'hello',
                isComplete: true,
                content: undefined,
            },
        ]);
        expect(result.current.isStreaming).toBe(true);
    });

    it('streams chat:message events for the active conversation into one bubble', async () => {
        const { result } = renderHook(() => useAgentChat('conv-1'));
        act(() => {
            result.current.addUserMessage('say hi');
        });
        act(() => {
            emitChat('conv-1', { message: 'Hi', finished: false });
        });
        act(() => {
            emitChat('conv-1', { message: ' there', finished: false });
        });
        act(() => {
            emitChat('conv-1', { message: '!', finished: true });
        });
        expect(
            result.current.messages.map((m) => ({
                user: m.isUser,
                text: m.text,
                done: m.isComplete,
            }))
        ).toEqual([
            { user: true, text: 'say hi', done: true },
            { user: false, text: 'Hi there!', done: true },
        ]);
        expect(result.current.isStreaming).toBe(false);
    });

    it('ignores chat:message events for a different conversation_id', async () => {
        const { result } = renderHook(() => useAgentChat('conv-1'));
        act(() => {
            emitChat('conv-2', {
                message: 'should be invisible',
                finished: true,
            });
        });
        act(() => {
            emitChat('', { message: 'no conv id', finished: true });
        });
        expect(result.current.messages).toEqual([]);
    });

    it.each(MODEL_VARIANTS)(
        'streams correctly for model "%s"',
        async (model) => {
            // The hook is model-agnostic — it only cares about conversation_id +
            // message text + finished flag. CLI agents (claude-code, openclaw,
            // hermes, …) emit the same ChatMessageEvent shape, so any wire-
            // shape regression here would break this case too.
            const convId = `ck:wf:node:${model}`;
            const { result } = renderHook(() => useAgentChat(convId));
            act(() => {
                result.current.addUserMessage(`prompt for ${model}`);
            });
            act(() => {
                emitChat(convId, {
                    message: `Hello from ${model}`,
                    finished: true,
                });
            });
            expect(result.current.messages).toHaveLength(2);
            expect(result.current.messages[1].text).toBe(`Hello from ${model}`);
            expect(result.current.messages[1].isComplete).toBe(true);
        }
    );

    it('keeps subscriber filtering correct when conversation_id changes', async () => {
        const { result, rerender } = renderHook(
            ({ id }: { id: string }) => useAgentChat(id),
            { initialProps: { id: 'conv-A' } }
        );
        act(() => {
            result.current.addUserMessage('to A');
        });
        rerender({ id: 'conv-B' });
        // Switching wipes the local transcript (different conversation).
        expect(result.current.messages).toEqual([]);
        // chat:message for the OLD conversation must not land on conv-B.
        act(() => {
            emitChat('conv-A', { message: 'late reply to A', finished: true });
        });
        expect(result.current.messages).toEqual([]);
        // chat:message for the new conversation DOES land.
        act(() => {
            emitChat('conv-B', { message: 'reply to B', finished: true });
        });
        expect(result.current.messages.map((m) => m.text)).toEqual([
            'reply to B',
        ]);
    });

    it('send after switching conversations lands in the NEW conversation (stale-closure regression)', () => {
        // 2026-07-18: addUserMessage captured the first render's conversationId-
        // keyed setters — after a new-chat / thread switch it kept writing to the
        // OLD session (phantom bubble + stuck isStreaming there, nothing here).
        const { result, rerender } = renderHook(
            ({ id }: { id: string }) => useAgentChat(id),
            { initialProps: { id: 'conv-A' } }
        );
        rerender({ id: 'conv-B' });
        act(() => {
            result.current.addUserMessage('to B');
        });
        expect(result.current.messages.map((m) => m.text)).toEqual(['to B']);
        expect(result.current.isStreaming).toBe(true);
        const a = getAgentChatSession('conv-A');
        expect(a.messages).toEqual([]);
        expect(a.isStreaming).toBe(false);
    });

    it('public-page shape: null-id first render, then id — send lands and arms the reconciler', async () => {
        // The share page renders once with conversationId=null (visitor id / chat
        // key hydrate in an effect). The stale closure made every later send write
        // through the null id: no user bubble, and isStreaming never armed — so
        // the reconcile poll (the ONLY terminal-delivery path for visitors, who
        // get no live finish frames) never ran and the response only appeared
        // after a refresh.
        vi.useFakeTimers();
        try {
            let persisted: Array<{ role: string; message: string }> = [];
            socket.replyTo('conversation:resume', () => ({
                session_id: '',
                messages: persisted,
                workflow_id: null,
            }));
            const { result, rerender } = renderHook(
                ({ id }: { id: string | null }) => useAgentChat(id),
                { initialProps: { id: null as string | null } }
            );
            rerender({ id: 'conv-pub' });
            await act(async () => {
                await vi.advanceTimersByTimeAsync(0);
            });
            act(() => {
                result.current.addUserMessage('hello from a visitor');
            });
            expect(result.current.messages.map((m) => m.text)).toEqual([
                'hello from a visitor',
            ]);
            expect(result.current.isStreaming).toBe(true);

            // Turn completes server-side; no live frame reaches the visitor. The
            // armed poll adopts the persisted terminal turn.
            persisted = [
                { role: 'user', message: 'hello from a visitor' },
                { role: 'assistant', message: 'response delivered by poll' },
            ];
            await act(async () => {
                await vi.advanceTimersByTimeAsync(6000);
            });
            expect(result.current.isStreaming).toBe(false);
            expect(result.current.messages.map((m) => m.text)).toEqual([
                'hello from a visitor',
                'response delivered by poll',
            ]);
        } finally {
            vi.useRealTimers();
        }
    });

    it('surfaces a sandbox-startup status before any text arrives', () => {
        const { result } = renderHook(() => useAgentChat('conv-1'));
        act(() => {
            result.current.addUserMessage('write a haiku');
        });
        act(() => {
            emitChat('conv-1', {
                status: 'Starting sandbox (noclick-codex)…',
                finished: false,
            });
        });
        const last =
            result.current.messages[result.current.messages.length - 1];
        expect(last.isUser).toBe(false);
        expect(last.text).toBe('');
        expect(last.status).toBe('Starting sandbox (noclick-codex)…');
        expect(result.current.isStreaming).toBe(true);
    });

    it('clears the status banner once the agent starts streaming text', () => {
        const { result } = renderHook(() => useAgentChat('conv-1'));
        act(() => {
            result.current.addUserMessage('go');
        });
        act(() => {
            emitChat('conv-1', {
                status: 'Starting sandbox…',
                finished: false,
            });
        });
        expect(result.current.messages[1].status).toBe('Starting sandbox…');
        act(() => {
            emitChat('conv-1', { message: 'Sure', finished: false });
        });
        expect(result.current.messages[1].status).toBeUndefined();
        expect(result.current.messages[1].text).toBe('Sure');
    });

    it('isStreaming flips to false on the terminal chunk', async () => {
        const { result } = renderHook(() => useAgentChat('conv-1'));
        act(() => {
            result.current.addUserMessage('hi');
        });
        expect(result.current.isStreaming).toBe(true);
        act(() => {
            emitChat('conv-1', { message: 'partial', finished: false });
        });
        expect(result.current.isStreaming).toBe(true);
        act(() => {
            emitChat('conv-1', { message: '!', finished: true });
        });
        expect(result.current.isStreaming).toBe(false);
    });
});

describe('useAgentChat — terminal state unwedge', () => {
    // The bug: agent hits a hard error (rate limit, exception) and never emits
    // finished:true. The chat:message stream silently dies and the UI stays
    // "Streaming…" forever. The fix: also listen to agent:state and treat
    // STOPPED / ERROR / FINISHED / REJECTED / PAUSED as run-over signals.
    it.each([
        ['stopped', undefined],
        ['STOPPED', undefined], // case-insensitive
        ['error', 'RateLimitError: openai/gpt-oss is temporarily rate-limited'],
        ['finished', undefined],
        ['rejected', 'user cancelled'],
    ])('agent:state="%s" stops the streaming indicator', (state, reason) => {
        const { result } = renderHook(() => useAgentChat('conv-1'));
        act(() => {
            result.current.addUserMessage('hi');
        });
        expect(result.current.isStreaming).toBe(true);
        act(() => {
            emitAgentState('conv-1', state, reason);
        });
        expect(result.current.isStreaming).toBe(false);
        if (
            reason &&
            (state.toLowerCase() === 'error' ||
                state.toLowerCase() === 'rejected')
        ) {
            expect(result.current.errorReason).toBe(reason);
        } else {
            expect(result.current.errorReason).toBeNull();
        }
    });

    it('closes the trailing in-flight agent bubble on terminal state', () => {
        const { result } = renderHook(() => useAgentChat('conv-1'));
        act(() => {
            result.current.addUserMessage('hi');
        });
        act(() => {
            emitChat('conv-1', { message: 'Almost…', finished: false });
        });
        // Agent crashes mid-stream — no finished:true ever comes.
        act(() => {
            emitAgentState('conv-1', 'error', 'RateLimitError');
        });
        expect(result.current.isStreaming).toBe(false);
        // The partial agent bubble gets closed; an error bubble is appended
        // after it. Last is the error; second-to-last is the closed partial.
        const msgs = result.current.messages;
        expect(msgs[msgs.length - 1]).toMatchObject({
            error: 'RateLimitError',
            isComplete: true,
        });
        expect(msgs[msgs.length - 2]).toMatchObject({
            isUser: false,
            isComplete: true,
            text: 'Almost…',
        });
    });

    it('appends an inline error message on terminal error (survives across remounts via persistence)', () => {
        const { result } = renderHook(() => useAgentChat('conv-1'));
        act(() => {
            result.current.addUserMessage('hi');
        });
        act(() => {
            emitAgentState('conv-1', 'error', 'RateLimitError');
        });
        const last =
            result.current.messages[result.current.messages.length - 1];
        expect(last.isUser).toBe(false);
        expect(last.error).toBe('RateLimitError');
        expect(last.isComplete).toBe(true);
        // errorReason banner stays set for the live render too — historical
        // restore will re-derive it from the persisted agent_state_changed event.
        expect(result.current.errorReason).toBe('RateLimitError');
    });

    it('clears a stale in-flight status on terminal state (no "Sandbox ready" lingering under the banner)', () => {
        const { result } = renderHook(() => useAgentChat('conv-1'));
        act(() => {
            result.current.addUserMessage('go');
        });
        // CLI handler emits sandbox lifecycle statuses, then dies before any text.
        act(() => {
            emitChat('conv-1', {
                status: 'Starting sandbox (noclick-codex)…',
                finished: false,
            });
        });
        act(() => {
            emitChat('conv-1', {
                status: 'Sandbox ready, running agent…',
                finished: false,
            });
        });
        expect(result.current.messages[1].status).toBe(
            'Sandbox ready, running agent…'
        );
        // Token-refresh failure — agent transitions to error without a chat:message frame.
        act(() => {
            emitAgentState(
                'conv-1',
                'error',
                'Your access token could not be refreshed'
            );
        });
        const last =
            result.current.messages[result.current.messages.length - 1];
        expect(last.isComplete).toBe(true);
        expect(last.status).toBeUndefined();
        expect(result.current.errorReason).toBe(
            'Your access token could not be refreshed'
        );
    });

    it('ignores agent:state for a different conversation', () => {
        const { result } = renderHook(() => useAgentChat('conv-1'));
        act(() => {
            result.current.addUserMessage('hi');
        });
        act(() => {
            emitAgentState('conv-2', 'error', 'should not affect conv-1');
        });
        expect(result.current.isStreaming).toBe(true);
        expect(result.current.errorReason).toBeNull();
    });

    it('does NOT stop streaming on non-terminal states (running, thinking, awaiting_user_input transitions handled separately)', () => {
        const { result } = renderHook(() => useAgentChat('conv-1'));
        act(() => {
            result.current.addUserMessage('hi');
        });
        act(() => {
            emitAgentState('conv-1', 'running');
        });
        expect(result.current.isStreaming).toBe(true);
        act(() => {
            emitAgentState('conv-1', 'thinking');
        });
        expect(result.current.isStreaming).toBe(true);
    });

    it('errorReason does not outlive the turn it described', () => {
        // Reported live: turn 1 died on a 429, turn 2 answered correctly, and the
        // 429 banner was still sitting under the correct answer.
        //
        // The clear lived in addUserMessage — so it only ran for turns the CHAT
        // started. A turn dispatched from the canvas (the Run popup) arrives as
        // frames with no addUserMessage, so nothing cleared the previous failure
        // and its banner rode along under the new answer. The transcript's own
        // guard does not help: it suppresses the banner only while the error is
        // the LAST message.
        const { result } = renderHook(() => useAgentChat('conv-1'));
        act(() => {
            result.current.addUserMessage('hi');
        });
        act(() => {
            emitAgentState('conv-1', 'error', 'rate limited');
        });
        expect(result.current.errorReason).toBe('rate limited');

        // Externally-started turn: user line and reply both arrive as frames.
        act(() => {
            emitChat('conv-1', { role: 'user', message: 'hi again' });
        });
        act(() => {
            emitChat('conv-1', { message: '2 + 2 = 4', finished: true });
        });

        expect(result.current.errorReason).toBeNull();
        // The failed turn stays visible where it belongs — as its own bubble.
        expect(
            result.current.messages.some((m) => m.error === 'rate limited')
        ).toBe(true);
    });

    it('errorReason clears on the next user send', () => {
        const { result } = renderHook(() => useAgentChat('conv-1'));
        act(() => {
            result.current.addUserMessage('hi');
        });
        act(() => {
            emitAgentState('conv-1', 'error', 'rate limited');
        });
        expect(result.current.errorReason).toBe('rate limited');
        act(() => {
            result.current.addUserMessage('retry');
        });
        expect(result.current.errorReason).toBeNull();
        expect(result.current.isStreaming).toBe(true);
    });

    it.each(MODEL_VARIANTS)(
        'terminal-state unwedge works for model "%s"',
        (model) => {
            const convId = `ck:wf:node:${model}`;
            const { result } = renderHook(() => useAgentChat(convId));
            act(() => {
                result.current.addUserMessage(`prompt for ${model}`);
            });
            expect(result.current.isStreaming).toBe(true);
            act(() => {
                emitAgentState(convId, 'error', `${model} ran out of credits`);
            });
            expect(result.current.isStreaming).toBe(false);
            expect(result.current.errorReason).toBe(
                `${model} ran out of credits`
            );
        }
    );
});

describe('useAgentChat — live steps ingest', () => {
    it('accumulates tool steps from chat:message frames into the in-flight bubble', () => {
        const { result } = renderHook(() => useAgentChat('conv-1'));
        act(() => {
            result.current.addUserMessage('create an issue');
        });
        act(() => {
            emitChat('conv-1', {
                agentic_steps: [
                    {
                        id: 's1',
                        text: 'Calling linear__create_issue({})',
                        status: 'in_progress',
                    },
                ],
            });
        });
        act(() => {
            emitChat('conv-1', {
                agentic_steps: [
                    { id: 's1', text: '{"success":true}', status: 'completed' },
                ],
            });
        });
        act(() => {
            emitChat('conv-1', { message: 'Created it.', finished: true });
        });
        const agentMsg = result.current.messages[1];
        expect(agentMsg.text).toBe('Created it.');
        expect(agentMsg.steps).toHaveLength(1);
        expect(agentMsg.steps![0]).toMatchObject({
            id: 's1',
            status: 'completed',
            detail: '{"success":true}',
        });
    });

    it('terminal agent:state resolves running steps so nothing pulses forever', () => {
        const { result } = renderHook(() => useAgentChat('conv-1'));
        act(() => {
            result.current.addUserMessage('go');
        });
        act(() => {
            emitChat('conv-1', {
                agentic_steps: [
                    {
                        id: 's1',
                        text: 'Calling slack__send_message({})',
                        status: 'in_progress',
                    },
                ],
            });
        });
        act(() => {
            emitAgentState('conv-1', 'error', 'provider 500');
        });
        const msgs = result.current.messages;
        const bubble = msgs.find((m) => !m.isUser && m.steps?.length);
        expect(bubble!.steps!.every((s) => s.status === 'completed')).toBe(
            true
        );
    });
});

describe('useAgentChat — presence-driven reconciliation (externallyBusy)', () => {
    // A tab that never saw the send (reload mid-turn, run started from a
    // trigger / share page / another tab) has isStreaming=false, so the old
    // reconciler never armed and a lost relay frame left the transcript stale
    // until remount. The presence beat (externallyBusy) arms the same poll; the
    // rendered-tail signature guard stops it from re-adopting an old turn.
    it('adopts a newly persisted terminal turn without a local send', async () => {
        vi.useFakeTimers();
        try {
            let persisted: Array<{ role: string; message: string }> = [
                { role: 'user', message: 'hi from another tab' },
            ];
            socket.replyTo('conversation:resume', () => ({
                session_id: '',
                messages: persisted,
                workflow_id: null,
            }));
            const { result } = renderHook(() =>
                useAgentChat('conv-1', undefined, true)
            );
            // Cold fetch paints the running turn's user message.
            await act(async () => {
                await vi.advanceTimersByTimeAsync(0);
            });
            expect(result.current.messages.map((m) => m.text)).toEqual([
                'hi from another tab',
            ]);

            // First poll (6s): still no assistant tail → keeps waiting.
            await act(async () => {
                await vi.advanceTimersByTimeAsync(6000);
            });
            expect(result.current.messages).toHaveLength(1);

            // Turn completes server-side; the live frame is lost. Next poll adopts.
            persisted = [
                { role: 'user', message: 'hi from another tab' },
                { role: 'assistant', message: 'all done' },
            ];
            await act(async () => {
                await vi.advanceTimersByTimeAsync(5000);
            });
            expect(result.current.messages.map((m) => m.text)).toEqual([
                'hi from another tab',
                'all done',
            ]);
        } finally {
            vi.useRealTimers();
        }
    });

    it('adopts a repeated byte-identical answer (count-based guard, not presence)', async () => {
        // Regression: turn 2 answers 'Done.' exactly like turn 1; its terminal
        // frame is lost. A presence-based signature guard matched turn 1's
        // rendered bubble and never adopted — chat pinned on streaming forever.
        // Counting copies (persisted 2 vs rendered 1) disambiguates.
        vi.useFakeTimers();
        try {
            let persisted: Array<{ role: string; message: string }> = [
                { role: 'user', message: 'do it' },
                { role: 'assistant', message: 'Done.' },
            ];
            socket.replyTo('conversation:resume', () => ({
                session_id: '',
                messages: persisted,
                workflow_id: null,
            }));
            const { result } = renderHook(() => useAgentChat('conv-1'));
            await act(async () => {
                await vi.advanceTimersByTimeAsync(0);
            });
            expect(result.current.messages.map((m) => m.text)).toEqual([
                'do it',
                'Done.',
            ]);

            // Turn 2: local send arms the reconciler; the live terminal frame is lost.
            act(() => {
                result.current.addUserMessage('do it again');
            });
            persisted = [
                { role: 'user', message: 'do it' },
                { role: 'assistant', message: 'Done.' },
                { role: 'user', message: 'do it again' },
                { role: 'assistant', message: 'Done.' },
            ];
            await act(async () => {
                await vi.advanceTimersByTimeAsync(6000);
            });
            expect(result.current.isStreaming).toBe(false);
            expect(result.current.messages.map((m) => m.text)).toEqual([
                'do it',
                'Done.',
                'do it again',
                'Done.',
            ]);
        } finally {
            vi.useRealTimers();
        }
    });

    it('does not re-adopt an already-rendered terminal tail (old turn)', async () => {
        vi.useFakeTimers();
        try {
            const persisted = [
                { role: 'user', message: 'old prompt' },
                { role: 'assistant', message: 'old answer' },
            ];
            socket.replyTo('conversation:resume', () => ({
                session_id: '',
                messages: persisted,
                workflow_id: null,
            }));
            const { result } = renderHook(() =>
                useAgentChat('conv-1', undefined, true)
            );
            await act(async () => {
                await vi.advanceTimersByTimeAsync(0);
            });
            expect(result.current.messages).toHaveLength(2);

            // Live frames for the CURRENTLY running turn arrive; a poll of the (not
            // yet advanced) persisted snapshot must NOT wipe the in-flight bubble.
            act(() => {
                emitChat('conv-1', { status: 'Agent is working…' });
            });
            await act(async () => {
                await vi.advanceTimersByTimeAsync(11000);
            });
            const msgs = result.current.messages;
            expect(msgs).toHaveLength(3);
            expect(msgs[2].status).toBe('Agent is working…');
        } finally {
            vi.useRealTimers();
        }
    });
});

describe('formatAgentError', () => {
    it('digs the human message out of a codex structured error (nested JSON envelope)', async () => {
        const { formatAgentError } = await import('~/hooks/useAgentChat');
        const codex = {
            message:
                '{"type":"error","status":400,"error":{"type":"invalid_request_error","message":"The \'gpt-5.3-codex\' model is not supported when using Codex with a ChatGPT account."}}',
            codexErrorInfo: 'other',
            additionalDetails: null,
        };
        expect(formatAgentError(codex)).toBe(
            "The 'gpt-5.3-codex' model is not supported when using Codex with a ChatGPT account."
        );
    });

    it('passes plain strings through and tolerates prose starting with a brace', async () => {
        const { formatAgentError } = await import('~/hooks/useAgentChat');
        expect(formatAgentError('rate limited')).toBe('rate limited');
        expect(formatAgentError('{oops not json')).toBe('{oops not json');
    });

    it('never renders [object Object] for arbitrary objects', async () => {
        const { formatAgentError } = await import('~/hooks/useAgentChat');
        expect(formatAgentError({ foo: 1 })).toBe('{"foo":1}');
        expect(formatAgentError(null)).toBe('');
    });

    it('digs the provider message out of a litellm blob with JSON embedded mid-string', async () => {
        // Representative overflow case: exception-class prefix + JSON tail
        // whose useful text sits at error.metadata.raw, not error.message.
        const { formatAgentError } = await import('~/hooks/useAgentChat');
        const blob =
            'litellm.RateLimitError: RateLimitError: OpenrouterException - ' +
            '{"error":{"message":"Provider returned error","code":429,"metadata":' +
            '{"raw":"tencent/hy3:free is temporarily rate-limited upstream. Please retry shortly.",' +
            '"provider_name":"Novita","is_byok":false}},"user_id":"user_example_000000000000000000000000"}';
        expect(formatAgentError(blob)).toBe(
            'tencent/hy3:free is temporarily rate-limited upstream. Please retry shortly.'
        );
    });

    it('junk metadata objects do not shadow a real message on a sibling key', async () => {
        const { formatAgentError } = await import('~/hooks/useAgentChat');
        expect(
            formatAgentError({
                message: 'the real reason',
                metadata: { provider_name: 'Novita', is_byok: false },
            })
        ).toBe('the real reason');
    });

    it('mid-string braces that are not JSON leave the message untouched', async () => {
        const { formatAgentError } = await import('~/hooks/useAgentChat');
        expect(formatAgentError('config error near {placeholder} token')).toBe(
            'config error near {placeholder} token'
        );
    });

    it('backend-authored prose with a "Provider message: {json}" appendix survives verbatim', async () => {
        // Backend-classified errors can include an explanation ending in the raw
        // provider JSON. The mid-string digger used
        // to parse that appendix and REPLACE the whole explanation with the
        // five-word provider error it exists to explain (2026-07-18).
        const { formatAgentError } = await import('~/hooks/useAgentChat');
        const rewritten =
            "OpenRouter's upstream model provider failed while serving this request — " +
            'a server-side outage on their end, not a problem with your setup, key, or ' +
            'credits. These are usually transient: retry, or switch models if it keeps ' +
            'happening. Free (:free) model variants fail this way far more often than ' +
            'paid ones.\n\nProvider message: ' +
            '{"code":500,"message":"Internal Server Error","metadata":{"error_type":"server"}}';
        expect(formatAgentError(rewritten)).toBe(rewritten);
    });

    it('single-sentence prose before an embedded JSON blob also survives', async () => {
        const { formatAgentError } = await import('~/hooks/useAgentChat');
        const prose =
            'The provider rejected this request and returned the following payload ' +
            '{"error":{"message":"Bad Request"}}';
        expect(formatAgentError(prose)).toBe(prose);
    });

    it('falls back to the RAW string when embedded JSON holds no human-readable text', async () => {
        // Extraction must never eat the error: parseable-but-prose-less JSON
        // (only codes/flags) keeps the full original message.
        const { formatAgentError } = await import('~/hooks/useAgentChat');
        const blob = 'ProviderException - {"code":429,"is_byok":false}';
        expect(formatAgentError(blob)).toBe(blob);
    });
});

describe('session persistence across unmount (tab switches)', () => {
    // The chat surface unmounts on Interface ↔ Workflow tab switches; session
    // state lives in agentChatSessionStore so a remount restores the in-flight
    // transcript — including the status/step timeline — instantly (2026-07-18:
    // component-local state erased the progress lines on every switch).
    it('remounting mid-stream restores transcript, timeline, and streaming state', () => {
        const first = renderHook(() => useAgentChat('conv-persist'));
        act(() => {
            first.result.current.addUserMessage('go');
        });
        act(() => {
            emitChat('conv-persist', {
                status: 'Starting sandbox…',
                finished: false,
            });
        });
        act(() => {
            emitChat('conv-persist', { message: 'thinking', finished: false });
        });
        first.unmount(); // Interface → Workflow tab

        const second = renderHook(() => useAgentChat('conv-persist'));
        expect(second.result.current.isStreaming).toBe(true);
        expect(second.result.current.messages.map((m) => m.text)).toEqual([
            'go',
            'thinking',
        ]);
        // The status timeline survived the remount.
        expect(second.result.current.messages[1].steps?.length).toBeGreaterThan(
            0
        );

        // Live frames keep landing in the restored session.
        act(() => {
            emitChat('conv-persist', { message: ' more', finished: true });
        });
        expect(second.result.current.messages[1].text).toBe('thinking more');
        expect(second.result.current.isStreaming).toBe(false);
    });

    it('an idle remount does not wipe the transcript while refreshing', () => {
        const first = renderHook(() => useAgentChat('conv-idle'));
        act(() => {
            first.result.current.addUserMessage('hey');
        });
        act(() => {
            emitChat('conv-idle', { message: 'done', finished: true });
        });
        first.unmount();

        const second = renderHook(() => useAgentChat('conv-idle'));
        // Instant restore — no empty flash while the background resume runs.
        expect(second.result.current.messages.map((m) => m.text)).toEqual([
            'hey',
            'done',
        ]);
        expect(second.result.current.isStreaming).toBe(false);
    });
});

describe('prompt_builder approval card (builder_prompt frames)', () => {
    const proposal = {
        prompt: 'add a slack node',
        node_id: 'agent_1',
        proposal_id: 'p-1',
    };

    it('appends a completed card message when the transcript is idle', () => {
        const state = applyChatMessageEvent([], { builder_prompt: proposal });
        expect(state).toHaveLength(1);
        expect(state[0].builderPrompt).toEqual(proposal);
        expect(state[0].isComplete).toBe(true);
        expect(state[0].isUser).toBe(false);
        expect(state[0].text).toBe('');
    });

    it('sinks the card BELOW the in-flight bubble — streaming continues above it', () => {
        // Mid-turn: status frame opened an in-flight bubble, then the tool emits
        // the card (which must land at the BOTTOM so it isn't missed after a long
        // response), then text streams — the text must land in the bubble ABOVE.
        let state = applyChatMessageEvent([], { status: 'Agent is working…' });
        state = applyChatMessageEvent(state, { builder_prompt: proposal });
        expect(state).toHaveLength(2);
        expect(state[0].isComplete).toBe(false);
        expect(state[1].builderPrompt).toEqual(proposal);
        state = applyChatMessageEvent(state, {
            message: 'On it — ',
            finished: false,
        });
        state = applyChatMessageEvent(state, {
            message: 'awaiting your approval.',
            finished: true,
        });
        expect(state).toHaveLength(2);
        expect(state[0].text).toBe('On it — awaiting your approval.');
        expect(state[0].isComplete).toBe(true);
        expect(state[1].builderPrompt).toEqual(proposal); // card stays last
    });

    it('dedupes event relay redeliveries by proposal_id', () => {
        let state = applyChatMessageEvent([], { builder_prompt: proposal });
        const again = applyChatMessageEvent(state, {
            builder_prompt: { ...proposal },
        });
        expect(again).toBe(state);
        // A DIFFERENT proposal is a new card.
        state = applyChatMessageEvent(state, {
            builder_prompt: { ...proposal, proposal_id: 'p-2' },
        });
        expect(state).toHaveLength(2);
    });

    it('restores the card from the PERSISTED transcript (adoption must not wipe it)', () => {
        // The reconcile poll replaces the transcript wholesale with the persisted
        // events — the card only survives because prompt_builder persists it as a
        // {builder_prompt} event (2026-07-18: the live-only card vanished the
        // moment the turn finished).
        const restored = persistedEventsToChatMessages([
            { role: 'user', message: 'Can you add support for telegram?' },
            { builder_prompt: proposal },
            { role: 'assistant', message: "I've submitted a request." },
        ]);
        // The card is persisted mid-turn (before the reply) but renders BELOW it.
        expect(restored).toHaveLength(3);
        expect(restored[1].text).toBe("I've submitted a request.");
        expect(restored[2].builderPrompt).toEqual(proposal);
        expect(restored[2].isComplete).toBe(true);
        // A late live frame for the same proposal dedupes against the adopted copy.
        const afterLiveFrame = applyChatMessageEvent(restored, {
            builder_prompt: { ...proposal },
        });
        expect(afterLiveFrame).toBe(restored);
    });

    it('restores the card DECIDED when a builder_decision event follows (cross-device verdict)', () => {
        // The approve/dismiss verdict persists as its own conversation event
        // (agent:builder_decision) — the card must come back decided on any
        // device, not just where localStorage remembered it, and the verdict
        // marker itself must not render as a bubble (2026-07-19).
        const restored = persistedEventsToChatMessages([
            { role: 'user', message: 'add telegram' },
            { builder_prompt: proposal },
            { role: 'assistant', message: 'Proposed.' },
            {
                builder_decision: {
                    proposal_id: proposal.proposal_id,
                    decision: 'approved',
                },
            } as never,
        ]);
        expect(restored).toHaveLength(3); // decision event is a marker, not a bubble
        expect(restored[2].builderPrompt?.decision).toBe('approved');

        // Undecided proposals stay pristine (no decision key injected).
        const undecided = persistedEventsToChatMessages([
            { builder_prompt: proposal },
        ]);
        expect(undecided[0].builderPrompt).toEqual(proposal);
    });
});

// ── Carried context never renders as the user's message ─────────────────────
// Reported live: after a model change the whole previous transcript appeared
// INSIDE the user's own bubble as a dump. The live bubble was clean — the
// prefix only rides the copy sent to the backend — but the persisted copy is
// what the transcript is rebuilt from, so it came back on the next read.
describe('persistedEventsToChatMessages — carried context', () => {
    it('puts the carried thread back as real turns, not inside the message', async () => {
        const { buildCarryOverContext } = await import('~/lib/agentChat');
        const block = buildCarryOverContext([
            { isUser: true, text: "hi what's 2+2" },
            { isUser: false, text: '4' },
        ]);
        const out = persistedEventsToChatMessages([
            { role: 'user', message: `${block}\n\nrepeat pls` },
        ] as never);

        expect(
            out.map((m) => ({ u: m.isUser, t: m.text, c: !!m.carriedOver }))
        ).toEqual([
            { u: true, t: "hi what's 2+2", c: true },
            { u: false, t: '4', c: true },
            { u: true, t: 'repeat pls', c: false },
        ]);
    });

    it('leaves a message with no carried block alone', () => {
        const out = persistedEventsToChatMessages([
            { role: 'user', message: 'just a question' },
        ] as never);
        expect(out).toHaveLength(1);
        expect(out[0].text).toBe('just a question');
        expect(out[0].carriedOver).toBeUndefined();
    });
});

// ── The conversation's model must not be "unknown" ──────────────────────────
// Reported live: a thread took consecutive turns through different harnesses,
// so the agent answered "this is our first
// interaction" to a question about the conversation directly above it.
//
// The mint guard asks what model the thread is running. Its nominal source is
// the conversations list — which is only refetched when the History popover
// opens, so a thread minted in this session is absent from it. Unknown then
// read as "same as the picker", and no fresh thread was minted. The session
// store carries what was actually dispatched so the next send can tell.
describe('agentChatSessionStore — lastSentModel', () => {
    it('starts null and survives across reads of the same conversation', () => {
        const s = getAgentChatSession('conv-model-1');
        expect(s.lastSentModel).toBeNull();
        s.lastSentModel = 'opencode';
        expect(getAgentChatSession('conv-model-1').lastSentModel).toBe(
            'opencode'
        );
    });

    it('is per conversation, so a fresh thread does not inherit the old one', () => {
        getAgentChatSession('conv-model-a').lastSentModel =
            'openrouter/openai/gpt-4o';
        expect(getAgentChatSession('conv-model-b').lastSentModel).toBeNull();
    });
});

// ── getAgentChatSession hands out a REACTIVE session ────────────────────────
// Reported live: after a model change the chat showed a step timeline and no
// sign of the message just sent, until the reply landed. The message WAS in the
// store against the right conversation — the component simply never re-rendered.
//
// `x ??= y` evaluates to y, the RAW object, not the proxy valtio installs on
// assignment. So the FIRST touch of a conversation handed back an unproxied
// session and every mutation through it was invisible. Existing sessions
// returned the proxy, which is why this only ever bit a brand-new conversation
// — exactly the case a model switch creates.
describe('getAgentChatSession', () => {
    it('NOTIFIES subscribers on the first write to a conversation', async () => {
        // The data lands either way — an unproxied session is still assigned INTO
        // the store, so reading it back looks correct. What was lost is the
        // notification, so that is what this asserts: the component subscribes,
        // and a write it never hears about renders nothing.
        const { subscribe } = await import('valtio');
        const id = `conv-proxy-${Math.random()}`;
        let notified = 0;
        const unsubscribe = subscribe(agentChatSessionStore, () => {
            notified++;
        });
        try {
            // HOLD the handle from the first touch and write through it — what the
            // seeding path does. Calling the getter twice would hide the bug: the
            // second call finds the session and returns the proxy.
            const session = getAgentChatSession(id);
            await Promise.resolve();
            const afterCreate = notified;
            session.messages = [
                { isUser: true, text: 'hello', isComplete: true },
            ];
            await Promise.resolve();
            expect(notified).toBeGreaterThan(afterCreate);
            expect(agentChatSessionStore.sessions[id].messages[0].text).toBe(
                'hello'
            );
        } finally {
            unsubscribe();
        }
    });

    it('keeps returning the same session on later touches', () => {
        const id = `conv-proxy-stable-${Math.random()}`;
        getAgentChatSession(id).isStreaming = true;
        getAgentChatSession(id).lastSentModel = 'opencode';
        const s = agentChatSessionStore.sessions[id];
        expect(s.isStreaming).toBe(true);
        expect(s.lastSentModel).toBe('opencode');
    });
});

// User-attached files (chat composer attachments): the persist path writes
// user turns with top-level image_urls (attached images) and attachments
// (non-image files) — the restore mapper must put them back on the bubble.
describe('persistedEventsToChatMessages — user-turn attachments', () => {
    it('restores attached images on a user turn as image_url content items', () => {
        const events = [
            {
                role: 'user',
                message: 'what is in this screenshot?',
                image_urls: ['https://assets.example.test/u/wf/r1/shot.png'],
            },
            { role: 'assistant', message: 'A cat.' },
        ];
        const [user, agent] = persistedEventsToChatMessages(events);
        expect(user).toMatchObject({
            isUser: true,
            text: 'what is in this screenshot?',
            content: [
                {
                    type: 'image_url',
                    image_url: {
                        url: 'https://assets.example.test/u/wf/r1/shot.png',
                    },
                },
            ],
        });
        expect(agent.isUser).toBe(false);
    });

    it('restores non-image files as attachment chips with a name fallback from the URL', () => {
        const events = [
            {
                role: 'user',
                message: '',
                attachments: [
                    {
                        name: 'report.pdf',
                        url: 'https://assets.example.test/u/wf/r2/report.pdf',
                        mime_type: 'application/pdf',
                    },
                    { url: 'https://assets.example.test/u/wf/r3/data.csv' },
                ],
            },
        ];
        const [user] = persistedEventsToChatMessages(events);
        expect(user.attachments).toEqual([
            {
                name: 'report.pdf',
                url: 'https://assets.example.test/u/wf/r2/report.pdf',
                mimeType: 'application/pdf',
            },
            {
                name: 'data.csv',
                url: 'https://assets.example.test/u/wf/r3/data.csv',
                mimeType: undefined,
            },
        ]);
    });

    it('keeps an attachment-only user turn (no text) as a bubble instead of dropping it', () => {
        const events = [
            {
                role: 'user',
                message: '',
                image_urls: ['https://assets.example.test/u/wf/r4/pic.jpg'],
            },
        ];
        const result = persistedEventsToChatMessages(events);
        expect(result).toHaveLength(1);
        expect(result[0].isUser).toBe(true);
        expect(result[0].content).toHaveLength(1);
    });

    it('still restores assistant generated media exactly as before', () => {
        const events = [
            {
                role: 'assistant',
                message: 'here you go',
                image_urls: ['https://assets.example.test/u/wf/r5/gen.png'],
            },
        ];
        const [agent] = persistedEventsToChatMessages(events);
        expect(agent.content).toEqual([
            {
                type: 'image_url',
                image_url: { url: 'https://assets.example.test/u/wf/r5/gen.png' },
            },
        ]);
        expect(agent.attachments).toBeUndefined();
    });
});
