// Unit tests for the pure helpers backing the AgentChatBlock + handleAgentChatSend.
//
// What these prove:
//   1. The conversation_id derivation matches what backend/nodes/agent_node.py
//      builds in `effective_conversation_id` — frontend subscription and
//      backend emit must agree, otherwise messages disappear into the void.
//   2. The one-shot run-override always carries a non-empty conversation_key.
//      handlers/llm.py:73 gates persistence on this; if it's ever absent the
//      chat memory silently turns off and the agent forgets the prior turn.
//   3. The persistent config patch is minimal — only diffs from current — so
//      a no-op send doesn't churn YJS sync.
//
// Tests are parameterized across the full agent model spectrum (LLMs +
// CLI agents like claude-code, openclaw, hermes, …). Adding a new
// model variant means just appending to MODEL_VARIANTS — the suite then
// asserts the helpers do the right thing for it. Backend runtime execution for
// CLI agents lives outside this file (those need an
// integration harness), but request-shape correctness is locked in here.

import { describe, it, expect } from 'vitest';
import {
    buildCarryOverContext,
    splitCarryOverContext,
    withCarriedContext,
    DEFAULT_AGENT_MODEL,
    DEFAULT_INTERFACE_CONV_KEY,
    deriveAgentChatConversationId,
    buildAgentChatRunOverride,
    buildAgentChatConfigPatch,
    isCliAgentModel,
    harnessOf,
    harnessLabel,
    resolveRunModel,
    credentialProviderFor,
    LEGACY_LLM_MODEL,
    LEGACY_CLI_MODEL,
} from '~/lib/agentChat';

/** The full spectrum of agent model IDs the frontend chat surface targets.
 *  Adding new CLI agents here ensures the request-shape coverage extends to
 *  them automatically. Each row carries a tag for the kind of model so
 *  assertions can be tightened later for CLI-only behavior. */
const MODEL_VARIANTS: ReadonlyArray<{
    id: string;
    kind: 'llm' | 'cli' | 'image' | 'video';
}> = [
    // Regular text LLMs (LiteLLM-style routing).
    { id: 'openrouter/openai/gpt-4o-mini', kind: 'llm' },
    { id: 'openrouter/anthropic/claude-3.5-sonnet', kind: 'llm' },
    { id: 'openrouter/google/gemini-2.0-flash', kind: 'llm' },
    // CLI agents.
    { id: 'codex', kind: 'cli' },
    { id: 'claude-code', kind: 'cli' },
    { id: 'opencode', kind: 'cli' },
    { id: 'openclaw', kind: 'cli' },
    { id: 'hermes', kind: 'cli' },
    // Modality-specific models.
    { id: 'openrouter/openai/dall-e-3', kind: 'image' },
    { id: 'openrouter/google/veo-2', kind: 'video' },
];

describe('deriveAgentChatConversationId', () => {
    const WF = 'wf-123';
    const NODE = 'node-abc';

    it('uses the workflow+node+key scheme matching agent_node.py:826', () => {
        expect(deriveAgentChatConversationId(WF, NODE, 'mykey')).toBe(
            `ck:${WF}:${NODE}:mykey`
        );
    });

    it('falls back to the interface default key when conversation_key is empty', () => {
        expect(deriveAgentChatConversationId(WF, NODE, undefined)).toBe(
            `ck:${WF}:${NODE}:${DEFAULT_INTERFACE_CONV_KEY}`
        );
        expect(deriveAgentChatConversationId(WF, NODE, null)).toBe(
            `ck:${WF}:${NODE}:${DEFAULT_INTERFACE_CONV_KEY}`
        );
        expect(deriveAgentChatConversationId(WF, NODE, '')).toBe(
            `ck:${WF}:${NODE}:${DEFAULT_INTERFACE_CONV_KEY}`
        );
        expect(deriveAgentChatConversationId(WF, NODE, '   ')).toBe(
            `ck:${WF}:${NODE}:${DEFAULT_INTERFACE_CONV_KEY}`
        );
    });

    it('degrades to the node id when no workflow id is available', () => {
        // Matches agent_node.py:849 fallback: `chat_routing_id = effective_conversation_id or self.node_id`.
        expect(deriveAgentChatConversationId(undefined, NODE, 'anything')).toBe(
            NODE
        );
        expect(deriveAgentChatConversationId(null, NODE, undefined)).toBe(NODE);
    });

    it('keeps custom conversation_keys intact (used by templated refs like {{telegram.chat_id}})', () => {
        expect(deriveAgentChatConversationId(WF, NODE, 'tg-9876')).toBe(
            `ck:${WF}:${NODE}:tg-9876`
        );
    });

    it('produces stable ids across calls — first send and reload subscribe to the same thread', () => {
        const first = deriveAgentChatConversationId(WF, NODE, undefined);
        const second = deriveAgentChatConversationId(WF, NODE, undefined);
        expect(first).toBe(second);
    });
});

describe('buildAgentChatRunOverride', () => {
    it('overrides only message/model/conversation_key and preserves the rest of the config', () => {
        const out = buildAgentChatRunOverride({
            currentConfig: {
                system_prompt: 'You are helpful.',
                temperature: 0.5,
                foo: 'bar',
            },
            message: 'hi',
            model: 'openrouter/openai/gpt-4o-mini',
        });
        expect(out).toEqual({
            system_prompt: 'You are helpful.',
            temperature: 0.5,
            foo: 'bar',
            message: 'hi',
            model: 'openrouter/openai/gpt-4o-mini',
            conversation_key: DEFAULT_INTERFACE_CONV_KEY,
        });
    });

    it('respects an explicit conversationKey when the user has set their own', () => {
        const out = buildAgentChatRunOverride({
            currentConfig: {},
            message: 'hi',
            model: 'gpt-4o-mini',
            conversationKey: 'tg-9876',
        });
        expect(out.conversation_key).toBe('tg-9876');
    });

    it('falls back to the default key when the explicit one is blank/whitespace', () => {
        const out = buildAgentChatRunOverride({
            currentConfig: {},
            message: 'hi',
            model: 'gpt-4o-mini',
            conversationKey: '   ',
        });
        expect(out.conversation_key).toBe(DEFAULT_INTERFACE_CONV_KEY);
    });

    it('maps attachments to snake_case message_attachments the backend normalizer reads', () => {
        const out = buildAgentChatRunOverride({
            currentConfig: {},
            message: 'what is in this?',
            model: 'gpt-4o-mini',
            attachments: [
                {
                    resourceId: 'res-1',
                    url: 'https://assets.example.test/u/wf/res-1/shot.png',
                    name: 'shot.png',
                    mimeType: 'image/png',
                    sizeBytes: 1234,
                },
            ],
        });
        expect(out.message_attachments).toEqual([
            {
                resource_id: 'res-1',
                url: 'https://assets.example.test/u/wf/res-1/shot.png',
                name: 'shot.png',
                mime_type: 'image/png',
                size_bytes: 1234,
            },
        ]);
        expect(out.message).toBe('what is in this?');
    });

    it('carries a lone-space message on attachment-only sends — config.message requires min_length 1', () => {
        const out = buildAgentChatRunOverride({
            currentConfig: {},
            message: '',
            model: 'gpt-4o-mini',
            attachments: [
                {
                    resourceId: 'res-1',
                    url: 'https://assets.example.test/u/wf/res-1/doc.pdf',
                    name: 'doc.pdf',
                    mimeType: 'application/pdf',
                    sizeBytes: 99,
                },
            ],
        });
        expect(out.message).toBe(' ');
    });

    it('omits message_attachments entirely when nothing is attached', () => {
        const out = buildAgentChatRunOverride({
            currentConfig: {},
            message: 'hi',
            model: 'gpt-4o-mini',
            attachments: [],
        });
        expect('message_attachments' in out).toBe(false);
        expect(out.message).toBe('hi');
    });

    it.each(MODEL_VARIANTS)(
        'builds a persistence-ready payload for $kind model "$id"',
        ({ id }) => {
            const out = buildAgentChatRunOverride({
                currentConfig: { system_prompt: 'test' },
                message: 'hello',
                model: id,
            });
            // Each variant — including CLI agents like claude-code, openclaw,
            // hermes — must carry the user's message, the chosen model, and
            // a non-empty conversation_key so the backend enables persistence.
            expect(out.message).toBe('hello');
            expect(out.model).toBe(id);
            expect(typeof out.conversation_key).toBe('string');
            expect(String(out.conversation_key).length).toBeGreaterThan(0);
            // Preserved fields stay intact.
            expect(out.system_prompt).toBe('test');
        }
    );

    it('does not leak the user message into the persisted message field — only into the one-shot override', () => {
        // The caller (FlowCanvas) feeds the override INTO the WorkflowExecuteRequest
        // and does NOT setNodes() the message. This helper just builds the override
        // — it must not require or assume the message gets saved back. The way we
        // assert that here: the input `currentConfig.message` (if any) is replaced.
        const out = buildAgentChatRunOverride({
            currentConfig: { message: 'previous message' },
            message: 'new message',
            model: 'm',
        });
        expect(out.message).toBe('new message');
    });
});

describe('buildAgentChatConfigPatch', () => {
    it('returns null when nothing needs to change (no churn)', () => {
        const patch = buildAgentChatConfigPatch({
            currentModel: 'gpt-4o-mini',
            currentConversationKey: 'existing-key',
            selectedModel: 'gpt-4o-mini',
        });
        expect(patch).toBeNull();
    });

    it('writes the model only when it actually changed', () => {
        const patch = buildAgentChatConfigPatch({
            currentModel: 'gpt-4o-mini',
            currentConversationKey: 'existing-key',
            selectedModel: 'claude-code',
        });
        expect(patch).toEqual({ model: 'claude-code' });
    });

    it('writes a default conversation_key when the node has none yet', () => {
        const patch = buildAgentChatConfigPatch({
            currentModel: 'gpt-4o-mini',
            currentConversationKey: undefined,
            selectedModel: 'gpt-4o-mini',
        });
        expect(patch).toEqual({ conversation_key: DEFAULT_INTERFACE_CONV_KEY });
    });

    it('writes both model and conversation_key when both differ from current', () => {
        const patch = buildAgentChatConfigPatch({
            currentModel: 'gpt-4o-mini',
            currentConversationKey: '',
            selectedModel: 'openclaw',
        });
        expect(patch).toEqual({
            model: 'openclaw',
            conversation_key: DEFAULT_INTERFACE_CONV_KEY,
        });
    });

    it('leaves a user-set conversation_key alone', () => {
        const patch = buildAgentChatConfigPatch({
            currentModel: 'gpt-4o-mini',
            currentConversationKey: 'tg-9876',
            selectedModel: 'gpt-4o-mini',
        });
        // No model change AND a user-set key already → nothing to do.
        expect(patch).toBeNull();
    });
});

describe('persistence id parity between block and dispatcher', () => {
    // Regression guard: AgentChatBlock subscribes to useConversation(id) and
    // FlowCanvas#handleAgentChatSend dispatches a run whose backend agent emits
    // events tagged with id. If those derivations ever drift apart the chat
    // appears to "not persist" — events flow into a different conversation_id
    // than what the UI is listening on.
    it.each(MODEL_VARIANTS)(
        'subscription id == backend emit id for $kind model "$id"',
        ({ id }) => {
            const WF = 'wf-1';
            const NODE = 'node-1';
            const cfg: Record<string, unknown> = { model: id }; // No conversation_key set yet.

            // What the block subscribes to.
            const subId = deriveAgentChatConversationId(
                WF,
                NODE,
                cfg.conversation_key as string | undefined
            );

            // What the dispatcher sends (the override the backend sees on run).
            const override = buildAgentChatRunOverride({
                currentConfig: cfg,
                message: 'hello',
                model: id,
                conversationKey: cfg.conversation_key as string | undefined,
            });

            // What the backend's `effective_conversation_id` computation produces
            // given that override (see agent_node.py:826).
            const backendId = `ck:${WF}:${NODE}:${override.conversation_key}`;

            expect(subId).toBe(backendId);
        }
    );
});

// validateAgentCredentialsForModel moved to ~/lib/agentCredentialModel (delegates to
// the canonical getAgentCredentialIdForProvider resolver); its tests live in
// app/lib/agentCredentialModel.test.ts.

describe('isCliAgentModel', () => {
    // CLI agents authenticate against the upstream provider inside the isolated CLI runner, so NoClick's usage-based billing doesn't apply to them — the
    // caller in AgentChatBlock uses this to short-circuit the usage-based
    // branch of the credentials pre-flight.
    it.each(['codex', 'claude-code', 'opencode', 'openclaw', 'hermes'])(
        'recognises CLI harness "%s"',
        (model) => {
            expect(isCliAgentModel(model)).toBe(true);
        }
    );

    it.each([
        'openrouter/openai/gpt-4o-mini',
        'openrouter/anthropic/claude-3.5-sonnet',
        'openai/gpt-4',
        'azure/gpt-4',
        undefined,
        '',
    ])('does NOT match regular LLM id "%s"', (model) => {
        expect(isCliAgentModel(model)).toBe(false);
    });
});

describe('harnessOf', () => {
    // The harness bucket determines whether a saved conversation can continue
    // under the current model — switching models WITHIN OpenHands is safe
    // (shared PostgresStore event stream), but crossing into a CLI harness or
    // between two CLI harnesses isn't (each CLI keeps disjoint runtime state).
    it.each(['codex', 'claude-code', 'opencode', 'openclaw', 'hermes'])(
        'maps CLI model "%s" to its own harness',
        (model) => {
            expect(harnessOf(model)).toBe(model);
        }
    );

    it.each([
        'openrouter/openai/gpt-4o-mini',
        'openrouter/anthropic/claude-3.5-sonnet',
        'openai/gpt-4',
        'azure/gpt-4',
        'gemini/gemini-2.0-flash',
        'legacy/llm',
    ])('maps LLM model "%s" to the llm bucket', (model) => {
        expect(harnessOf(model)).toBe('llm');
    });

    it('maps the legacy CLI backfill placeholder to legacy-cli', () => {
        expect(harnessOf('legacy/cli')).toBe('legacy-cli');
    });

    it('defaults null/undefined/empty to the llm bucket', () => {
        expect(harnessOf(null)).toBe('llm');
        expect(harnessOf(undefined)).toBe('llm');
        expect(harnessOf('')).toBe('llm');
    });
});

describe('harnessLabel', () => {
    // CLI harness labels are sourced from PROVIDER_METADATA so the popover
    // shows the same brand name the credentials form does — no hardcoded
    // restating of 'Claude Code' / 'OpenAI Codex' / etc. that could drift.
    it('reads CLI harness labels from PROVIDER_METADATA', () => {
        expect(harnessLabel('codex')).toBe('OpenAI Codex');
        expect(harnessLabel('claude-code')).toBe('Claude Code');
        expect(harnessLabel('opencode')).toBe('OpenCode');
        expect(harnessLabel('openclaw')).toBe('OpenClaw');
        expect(harnessLabel('hermes')).toBe('Hermes Agent');
    });

    it('returns empty string for the LLM bucket (no badge in chat history)', () => {
        // Every LLM chat shares the same in-process wrapper; the bucket
        // identity matters for cross-harness comparisons (state isn't
        // portable between CLI and LLM) but there's no useful brand label.
        // AgentChatHistory.tsx gates the badge render on a non-empty label
        // so LLM rows don't get a styled badge with empty text.
        expect(harnessLabel('llm')).toBe('');
    });

    it('returns "?" for the unresolvable legacy-CLI bucket', () => {
        // Legacy CLI rows: the original handler can't be recovered, so the
        // label is non-committal rather than fabricating a name.
        expect(harnessLabel('legacy-cli')).toBe('?');
    });
});

describe('resolveRunModel', () => {
    // Decision is shared by submit() and handleSwitchToConversation() — both
    // must pick the same model for a given row so picker-vs-conv stays in sync.
    it('returns null for unborn conversations', () => {
        expect(resolveRunModel(null)).toBeNull();
        expect(resolveRunModel(undefined)).toBeNull();
    });

    it('returns the agent_model as-is for real model ids', () => {
        expect(resolveRunModel('codex')).toBe('codex');
        expect(resolveRunModel('claude-code')).toBe('claude-code');
        expect(resolveRunModel('openrouter/openai/gpt-4o-mini')).toBe(
            'openrouter/openai/gpt-4o-mini'
        );
    });

    it('collapses legacy/llm to the default agent model so the harness aligns', () => {
        expect(resolveRunModel(LEGACY_LLM_MODEL)).toBe(DEFAULT_AGENT_MODEL);
    });

    it('returns null for legacy/cli — caller must fall back to the picker', () => {
        expect(resolveRunModel(LEGACY_CLI_MODEL)).toBeNull();
    });
});

describe('credentialProviderFor', () => {
    // CLI harnesses authenticate directly, not through the NoClick gateway, so
    // the credential check follows the CLI's OWN provider
    // (PROVIDER_METADATA[OPENCLAW]) rather than the submodel's upstream LLM.
    const lookup = (m: string) => (m.includes('/') ? m.split('/')[0] : null);

    it('maps CLI ids to their own ModelProvider snake-case identity', () => {
        expect(credentialProviderFor('claude-code', lookup)).toBe(
            'claude_code'
        );
        expect(credentialProviderFor('hermes', lookup)).toBe('hermes_agent');
        expect(credentialProviderFor('codex', lookup)).toBe('codex');
    });

    it('defers to the resolver for LLM models', () => {
        expect(
            credentialProviderFor('openrouter/openai/gpt-4o-mini', lookup)
        ).toBe('openrouter');
        expect(credentialProviderFor('azure/gpt-4', lookup)).toBe('azure');
    });
});

// ── Carrying a thread across a model change ─────────────────────────────────
// A conversation is bound to the model it started with, so changing an agent's
// model starts a fresh one. Dropping the thread silently loses everything said
// so far; making the user choose between "keep the thread" and "use the model I
// picked" is a choice they shouldn't have to make. The transcript rides along
// as context instead.
describe('buildCarryOverContext', () => {
    const msg = (isUser: boolean, text: string, error?: string) => ({
        isUser,
        text,
        error,
    });

    it('is empty when there is nothing worth carrying', () => {
        expect(buildCarryOverContext([])).toBe('');
        expect(buildCarryOverContext([msg(true, '   ')])).toBe('');
    });

    it('round-trips both sides in order', () => {
        const block = buildCarryOverContext([
            msg(true, 'hi'),
            msg(false, 'hello'),
        ]);
        expect(splitCarryOverContext(block).carried).toEqual([
            { isUser: true, text: 'hi' },
            { isUser: false, text: 'hello' },
        ]);
    });

    it('survives a message containing newlines', () => {
        // The reason this is JSON and not "User: …" lines: a line-based format
        // cannot tell a new turn from a second line of the same one.
        const multi = 'line one\nline two\nUser: not a turn';
        const block = buildCarryOverContext([msg(true, multi)]);
        expect(splitCarryOverContext(block).carried).toEqual([
            { isUser: true, text: multi },
        ]);
    });

    it('frames the block as history, not as an instruction', () => {
        // Without this the new model reads the transcript as the turn it must
        // answer and replies to the OLD message.
        expect(buildCarryOverContext([msg(true, 'hi')])).toContain(
            'History, not a new instruction'
        );
    });

    it('drops error bubbles, which neither party said', () => {
        const block = buildCarryOverContext([
            msg(true, 'hi'),
            msg(false, '', 'Agent stopped: no credential'),
        ]);
        const { carried } = splitCarryOverContext(block);
        expect(carried).toEqual([{ isUser: true, text: 'hi' }]);
    });

    it('trims from the START, keeping the most recent turns', () => {
        const block = buildCarryOverContext(
            [msg(true, 'x'.repeat(40)), msg(false, 'recent')],
            40
        );
        expect(splitCarryOverContext(block).carried).toEqual([
            { isUser: false, text: 'recent' },
        ]);
    });

    it('never exceeds the budget it was given', () => {
        const many = Array.from({ length: 50 }, (_, i) =>
            msg(i % 2 === 0, `turn ${i} `.repeat(20))
        );
        const { carried } = splitCarryOverContext(
            buildCarryOverContext(many, 500)
        );
        const body = carried.reduce((n, t) => n + t.text.length, 0);
        expect(body).toBeLessThanOrEqual(500);
    });

    it('trims the newest turn in rather than carrying nothing', () => {
        // The headline case: switch models right after a long answer. A reply
        // longer than the whole budget used to empty the carry entirely —
        // exactly when the user most needs the previous turn to follow it up.
        // Its tail survives (a long reply's conclusion lives at the end).
        const long = `${'preamble '.repeat(30)}the conclusion is 42`;
        const { carried } = splitCarryOverContext(
            buildCarryOverContext([msg(true, 'question'), msg(false, long)], 80)
        );
        expect(carried).toHaveLength(1);
        expect(carried[0].isUser).toBe(false);
        expect(carried[0].text.startsWith('… ')).toBe(true);
        expect(carried[0].text).toContain('the conclusion is 42');
        expect(carried[0].text.length).toBeLessThanOrEqual(82);
    });
});

// The block travels inside the message so it remains scoped to the carried
// turn instead of mutating the stored system prompt. The DISPLAY takes it back
// out, or
// the whole transcript renders inside what the user typed (reported live).
describe('splitCarryOverContext', () => {
    it('leaves an ordinary message untouched', () => {
        expect(splitCarryOverContext('just a message')).toEqual({
            carried: [],
            text: 'just a message',
        });
    });

    it('returns the user words without the block', () => {
        const block = buildCarryOverContext([
            { isUser: true, text: 'earlier' },
        ]);
        const { carried, text } = splitCarryOverContext(
            `${block}\n\nwhat did we discuss?`
        );
        expect(text).toBe('what did we discuss?');
        expect(carried).toEqual([{ isUser: true, text: 'earlier' }]);
    });

    it('still yields the message when the block is corrupt', () => {
        // A truncated or hand-edited block must not take the user's message down
        // with it — losing the words they actually typed is the worse failure.
        const { carried, text } = splitCarryOverContext(
            '<<<NOCLICK_CARRIED_CONTEXT [{"isUser":tr NOCLICK_CARRIED_CONTEXT>>>\n\nhello'
        );
        expect(carried).toEqual([]);
        expect(text).toBe('hello');
    });
});

// The stored message is read by things that cannot strip the block: conversation
// titles and previews come from LEFT(events->0->>'message', 100) in SQL. A block
// at the front made every carried-over thread show up in History titled
// "<<<NOCLICK_CARRIED_CONTEXT …".
describe('withCarriedContext', () => {
    it('leads with the user words, so a prefix of the stored message starts correctly', () => {
        const block = buildCarryOverContext([
            { isUser: true, text: 'earlier turn' },
        ]);
        const stored = withCarriedContext(
            'what has been our convo so far?',
            block
        );
        expect(stored.startsWith('what has been our convo so far?')).toBe(true);
        expect(stored).toContain('earlier turn');
    });

    it('a 100-char prefix of it still strips clean', () => {
        // What History actually gets: LEFT(message, 100) from SQL, which cuts the
        // closing marker off. The label must still be the user's words.
        const block = buildCarryOverContext([
            { isUser: true, text: 'earlier turn' },
        ]);
        const stored = withCarriedContext(
            'what has been our convo so far?',
            block
        );
        expect(splitCarryOverContext(stored.slice(0, 100)).text).toBe(
            'what has been our convo so far?'
        );
    });

    it('is a no-op when there is nothing to carry', () => {
        expect(withCarriedContext('just asking', '')).toBe('just asking');
    });
});
