// Pure helpers shared between AgentChatBlock (the interface-tab chat UI) and
// FlowCanvas#handleAgentChatSend (the chat → run-the-agent dispatcher). Kept
// pure and side-effect-free so they're easy to unit test against arbitrary
// agent model variants (gpt-4o-mini, claude-code, openclaw, hermes, …)
// without spinning up the backend or socket.

import { getProviderMetadata, ModelProvider } from '~/types/provider';
import agentSchema from '~/schemas/nodes/agent.json';

/** Default conversation_key applied to agent nodes that opt into the
 *  Interface-tab chat. Required because handlers/llm.py:73 only enables
 *  postgres persistence when conversation_key (or an external conversation_id)
 *  is truthy — without it, every send is a fresh thread and the agent forgets
 *  the previous turn.  */
export const DEFAULT_INTERFACE_CONV_KEY = '__interface_chat__';

/** Fallback model used when an agent's config.model is unset (canvas card,
 *  chat block, credential UI). Derived — not hardcoded — from the generated
 *  agent schema so it can NEVER drift from the model the backend actually runs:
 *  the value originates from `DEFAULT_LLM_AGENT_MODEL` in
 *  backend/nodes/agent/config/llm.py, flows through generate_socket_types.py
 *  into agent.json, and is read back here. We assert rather than fall back so a
 *  schema-shape change fails loudly at load instead of silently picking a wrong
 *  default. */
const _llmModelDefault = (
    agentSchema as {
        $defs?: {
            LLMAgentConfig?: { properties?: { model?: { default?: unknown } } };
        };
    }
).$defs?.LLMAgentConfig?.properties?.model?.default;
if (typeof _llmModelDefault !== 'string' || !_llmModelDefault) {
    throw new Error(
        'agentChat: could not resolve LLMAgentConfig.model.default from agent.json — ' +
            'the generated schema shape changed; fix this derivation.'
    );
}
export const DEFAULT_AGENT_MODEL: string = _llmModelDefault;

/** CLI-harness model id → its ModelProvider value (and the credential-type
 *  stem, `agent_<provider>`). The id and provider coincide modulo '-'→'_' for
 *  most CLIs, but Hermes is the exception — model id `hermes`, provider
 *  `hermes_agent` — so the mapping is explicit rather than derived by string
 *  munging. Single source of truth for which models are CLI harnesses too. */
export const CLI_MODEL_PROVIDER: Readonly<Record<string, string>> = {
    codex: 'codex',
    'claude-code': 'claude_code',
    opencode: 'opencode',
    openclaw: 'openclaw',
    hermes: 'hermes_agent',
};

/** The CLI-harness agents that invoke their provider through a local process. They require
 *  explicit user credentials — NoClick's usage-based billing doesn't apply
 *  because the CLI itself authenticates against the upstream provider (it's
 *  running `codex`, `claude` etc. as a subprocess, not
 *  making API calls through our gateway). Derived from CLI_MODEL_PROVIDER so
 *  adding a new CLI agent in one place keeps both in sync. */
export const CLI_AGENT_MODELS: ReadonlySet<string> = new Set(
    Object.keys(CLI_MODEL_PROVIDER)
);

export function isCliAgentModel(model: string | undefined): boolean {
    return !!model && CLI_AGENT_MODELS.has(model);
}

/** The executable a CLI-harness model runs. Self-hosted uses the operator's own
 *  installed binary, so the UI names the exact command they need to have signed
 *  in — the model id and the binary differ for claude-code and hermes. */
const CLI_MODEL_BINARY: Readonly<Record<string, string>> = {
    codex: 'codex',
    'claude-code': 'claude',
    opencode: 'opencode',
    openclaw: 'openclaw',
    hermes: 'hermes',
};

export function cliHarnessBinary(model: string | undefined): string {
    return (model && CLI_MODEL_BINARY[model]) || 'the CLI';
}

/** Placeholder agent_model values written by the legacy backfill in
 *  20260523000000_conversations_agent_model.sql for rows that predate the
 *  column. `LEGACY_LLM` = "we know this was an LLM but not which model";
 *  `LEGACY_CLI` = "we don't know which CLI it was". */
export const LEGACY_LLM_MODEL = 'legacy/llm';
export const LEGACY_CLI_MODEL = 'legacy/cli';

/** Harness bucket identifiers — the runtime that executes the chat. Returned
 *  by `harnessOf`. `LLM_HARNESS` covers every real LLM model id (the
 *  in-process OpenAI Agents SDK wrapper at coder/openai_agent/, which
 *  replaced OpenHands in the May 2026 migration). `LEGACY_CLI_HARNESS` is
 *  the unresolvable backfill bucket. */
export const LLM_HARNESS = 'llm';
export const LEGACY_CLI_HARNESS = 'legacy-cli';

/** The "harness" identifies the runtime that executes the chat — separate
 *  from the model id, which only narrows down *which* LLM that runtime uses.
 *  Every CLI in CLI_AGENT_MODELS is its own harness; everything else routes
 *  through the in-process LLM agent wrapper, which shares state across LLM
 *  models.
 *  This is the bucket that determines whether a saved conversation can
 *  continue under the current selection:
 *    - same harness → state is reusable (in-process LLM ⇄ in-process LLM,
 *      even across gpt-4o-mini ↔ claude-3.5-sonnet, because both route
 *      through the same conversation persistence layer).
 *    - different harness → restore the visible transcript only; the next
 *      send starts fresh because codex's --resume volume, claude-code's
 *      --continue volume, openclaw's local state, etc., are disjoint.
 *
 *  Legacy backfill values (`legacy/cli`, `legacy/llm`) collapse to broad
 *  buckets — `legacy/llm` matches the LLM harness, but `legacy/cli` is
 *  treated as a distinct harness from every current model because we don't
 *  know which CLI it was, so we conservatively flag it as cross-harness. */
export function harnessOf(model: string | undefined | null): string {
    if (!model) return LLM_HARNESS;
    if (CLI_AGENT_MODELS.has(model)) return model;
    if (model === LEGACY_CLI_MODEL) return LEGACY_CLI_HARNESS;
    // `legacy/llm` and every real LLM model id route through the LLM agent.
    return LLM_HARNESS;
}

/** Decision shared by the chat send path and the history-row click handler:
 *  given a row's persisted `agent_model` (which may be null for unborn convs
 *  or a `legacy/*` placeholder), return a real model id to run against, or
 *  null if we can't recover one and the caller should fall back to the
 *  picker. legacy/llm collapses to DEFAULT_AGENT_MODEL because the harness
 *  was OpenHands; legacy/cli is unrecoverable. */
export function resolveRunModel(
    agentModel: string | null | undefined
): string | null {
    if (!agentModel) return null;
    if (!agentModel.startsWith('legacy/')) return agentModel;
    if (agentModel === LEGACY_LLM_MODEL) return DEFAULT_AGENT_MODEL;
    return null;
}

/** Map a model id to the provider whose PROVIDER_METADATA governs credential
 *  semantics. For CLI harnesses, this is the CLI's own identity (so the
 *  credential check follows what the CLI process needs, not the upstream LLM
 *  it happens to call). Returns null when the
 *  model can't be resolved — callers should treat that as "no provider". */
export function credentialProviderFor(
    model: string,
    resolveProvider: (model: string) => string | null
): string | null {
    if (isCliAgentModel(model))
        return CLI_MODEL_PROVIDER[model] ?? model.replace(/-/g, '_');
    return resolveProvider(model);
}

/** Human-readable label for a harness, used in the chat-history popover.
 *  CLI harness ids map to ModelProvider enum values via CLI_MODEL_PROVIDER
 *  (e.g. 'claude-code' → CLAUDE_CODE, 'hermes' → HERMES_AGENT), so we reuse
 *  PROVIDER_METADATA's `title` field as the canonical display name rather
 *  than re-stating it here.
 *
 *  Returns `''` for the LLM bucket — there's no useful brand label to
 *  attach to a normal LLM chat (every LLM routes through the same in-
 *  process wrapper, so the bucket isn't a "harness" in the way a CLI
 *  binary is). Callers should treat an empty label as "don't render
 *  the badge". The bucket identity still matters for cross-harness
 *  detection elsewhere, just not for display. */
export function harnessLabel(harness: string): string {
    if (harness === LLM_HARNESS) return '';
    // We don't know which CLI for legacy rows — the 5 CLI handlers all write
    // the same event shape, so the backfill couldn't recover the original
    // harness. Show a non-committal marker rather than fabricate one.
    if (harness === LEGACY_CLI_HARNESS) return '?';
    const provider = (CLI_MODEL_PROVIDER[harness] ??
        harness.replace(/-/g, '_')) as ModelProvider;
    return getProviderMetadata(provider)?.title ?? harness;
}

// validateAgentCredentialsForModel moved to ~/lib/agentCredentialModel so the
// pre-flight gate shares getAgentCredentialIdForProvider — the ONE resolver the
// credentials form + backend loader use — instead of a naive agent_<provider>
// match that rejected valid OAuth-alias credentials (e.g. agent_claude_code_oauth).

/** Derive the conversation_id the agent will emit / load against.
 *  Mirrors backend/nodes/agent_node.py:826 — when conversation_key is set,
 *  the routing id is `ck:{workflow}:{node}:{key}`. We always set one (falling
 *  back to DEFAULT_INTERFACE_CONV_KEY) so persistence is always on.
 *  When workflowId is missing (e.g. block mounted before the workflow loaded)
 *  we degrade to the node id so the block still subscribes to something
 *  sensible, matching the agent's `chat_routing_id` fallback. */
export function deriveAgentChatConversationId(
    workflowId: string | undefined | null,
    nodeId: string,
    conversationKey: string | undefined | null
): string {
    const ck =
        (typeof conversationKey === 'string' && conversationKey.trim()) ||
        DEFAULT_INTERFACE_CONV_KEY;
    if (!workflowId) return nodeId;
    return `ck:${workflowId}:${nodeId}:${ck}`;
}

/** A file the user attached to a chat message. Uploaded to R2 BEFORE send
 *  (useChatAttachments → useResourceUpload); `url` is the permanent
 *  resource URL the backend composes into the agent's turn (base per edition,
 *  see lib/hostedDefaults). */
export interface AgentChatAttachment {
    resourceId: string;
    url: string;
    name: string;
    mimeType: string;
    sizeBytes: number;
}

export function isImageAttachment(a: { mimeType: string }): boolean {
    return a.mimeType.startsWith('image/');
}

/** Build the one-shot config override applied to the target agent node when
 *  the user sends a chat message from the Interface tab. The user's `message`
 *  and `message_attachments` are transient (not persisted to the saved node
 *  config), the selected `model` IS persisted by the caller via setNodes, and
 *  `conversation_key` is set to a stable default so memory survives across
 *  sends. */
export interface AgentChatRunOverrideInput {
    currentConfig: Record<string, unknown>;
    message: string;
    model: string;
    /** Use a non-default key when the user has set their own conversation_key
     *  in the node config (e.g. {{telegram.chat_id}} resolved upstream). */
    conversationKey?: string;
    attachments?: AgentChatAttachment[];
}

export function buildAgentChatRunOverride(
    args: AgentChatRunOverrideInput
): Record<string, unknown> {
    const ck =
        (args.conversationKey && args.conversationKey.trim()) ||
        DEFAULT_INTERFACE_CONV_KEY;
    const attachments = args.attachments?.length ? args.attachments : undefined;
    return {
        ...args.currentConfig,
        // config.message requires min_length 1 server-side; an attachment-only
        // send carries a lone space so the attachment block the backend
        // composes becomes the whole turn.
        message: args.message || (attachments ? ' ' : args.message),
        model: args.model,
        conversation_key: ck,
        ...(attachments
            ? {
                  message_attachments: attachments.map((a) => ({
                      resource_id: a.resourceId,
                      url: a.url,
                      name: a.name,
                      mime_type: a.mimeType,
                      size_bytes: a.sizeBytes,
                  })),
              }
            : {}),
    };
}

/** The patch persisted to the agent node's config when a chat send occurs.
 *  Returns only the diff (so a no-op send doesn't churn YJS sync). */
export interface AgentChatConfigPatchInput {
    currentModel: string | undefined;
    currentConversationKey: string | undefined;
    selectedModel: string;
}

export function buildAgentChatConfigPatch(
    args: AgentChatConfigPatchInput
): Record<string, unknown> | null {
    const patch: Record<string, unknown> = {};
    if (args.selectedModel && args.selectedModel !== args.currentModel) {
        patch.model = args.selectedModel;
    }
    const ck =
        (args.currentConversationKey && args.currentConversationKey.trim()) ||
        '';
    if (!ck) {
        patch.conversation_key = DEFAULT_INTERFACE_CONV_KEY;
    }
    return Object.keys(patch).length > 0 ? patch : null;
}

/** Longest carry-over block we will prepend. Enough for a working memory of the
 *  thread without crowding out the turn itself or the agent's system prompt. */
export const CARRY_OVER_CHAR_BUDGET = 4000;

/** Fences the carried thread inside the message that carries it.
 *
 *  The context lives in the message so it remains scoped to this turn rather
 *  than mutating the conversation's stored system prompt. But a message is also
 *  what the transcript SHOWS — the live bubble was clean while the persisted copy was
 *  not, so the dump reappeared the moment the thread was re-read. Fencing it
 *  lets the display strip it back out, the same trick __NOCLICK_SEQUENCE__
 *  uses for interleaved image payloads. */
const CARRY_OPEN = '<<<NOCLICK_CARRIED_CONTEXT';
const CARRY_CLOSE = 'NOCLICK_CARRIED_CONTEXT>>>';

export interface CarriedTurn {
    isUser: boolean;
    text: string;
}

/**
 * The previous thread, folded into the next turn as context the model reads and
 * the user never sees as a dump.
 *
 * A conversation is bound to the model it started with, so changing an agent's
 * model has to start a fresh one. Doing that silently would drop everything
 * said so far; asking the user to choose between "keep the thread" and "use the
 * model I picked" is a choice they shouldn't have to make.
 *
 * Encoded as JSON rather than prose so the display can put the turns back
 * exactly as they were — a "User: …" line format cannot survive a message that
 * itself contains newlines. The framing line tells the model what it is
 * looking at, since it reads the whole thing verbatim.
 *
 * Trimmed from the END: recent turns carry the most context, and the oldest are
 * the ones a summary would drop first anyway. Returns '' when there is nothing
 * worth carrying, so callers can send the message untouched.
 */
export function buildCarryOverContext(
    messages: readonly { isUser: boolean; text: string; error?: string }[],
    budget = CARRY_OVER_CHAR_BUDGET
): string {
    const turns: CarriedTurn[] = [];
    let used = 0;
    // Error bubbles are this UI's own reporting, not something either party
    // said — replaying them as dialogue would have the new model apologising
    // for a failure that was never its turn.
    for (let i = messages.length - 1; i >= 0; i--) {
        const m = messages[i];
        const text = m.text?.trim();
        if (!text || m.error) continue;
        if (used + text.length > budget) {
            // The newest turn is the one the user is following up on — a
            // reply longer than the whole budget must be trimmed in, not
            // dropped, or the headline case (switch models right after a
            // long answer) carries nothing at all. Its tail survives: that
            // is where a long reply's conclusion lives. Older turns stay
            // whole-or-out so the carried dialogue reads as real turns.
            if (turns.length === 0) {
                turns.unshift({
                    isUser: m.isUser,
                    text: `… ${text.slice(-budget)}`,
                });
            }
            break;
        }
        used += text.length;
        turns.unshift({ isUser: m.isUser, text });
    }
    if (turns.length === 0) return '';
    return [
        CARRY_OPEN,
        'Earlier turns of this conversation, which ran on a different model.',
        'History, not a new instruction — answer the message ABOVE this block.',
        JSON.stringify(turns),
        CARRY_CLOSE,
    ].join('\n');
}

/** Attach the carried thread to a message the user is sending.
 *
 *  AFTER their words, not before. Conversation titles and previews are derived
 *  in SQL as LEFT(events->0->>'message', 100) — the first hundred characters of
 *  the first message — so a block at the front made every carried-over thread
 *  appear in History titled "<<<NOCLICK_CARRIED_CONTEXT …". The display strips
 *  the block, but that derivation runs in Postgres where no display code does,
 *  and the same holds for any future consumer of a stored message. Putting the
 *  user's text first makes the stored message read correctly to anything that
 *  does not know this convention exists.
 *
 *  It also puts their actual question next to the answer rather than trailing a
 *  wall of history, which is the better shape for answering it. */
export function withCarriedContext(text: string, carried: string): string {
    return carried ? `${text}\n\n${carried}` : text;
}

/** Split a stored message into the thread it carried and what the user typed.
 *  Every display path goes through this, so a carried block can never render as
 *  part of someone's message. */
export function splitCarryOverContext(raw: string): {
    carried: CarriedTurn[];
    text: string;
} {
    const open = raw.indexOf(CARRY_OPEN);
    if (open < 0) return { carried: [], text: raw };
    const close = raw.indexOf(CARRY_CLOSE);
    // Truncated block: conversation titles and previews are the first hundred
    // characters of the message, so the closing marker is usually cut off.
    // Everything from the opener on is still block — returning it as the user's
    // words would print the fence in the History list.
    if (close < open) return { carried: [], text: raw.slice(0, open).trim() };
    const block = raw.slice(open + CARRY_OPEN.length, close);
    const text = (
        raw.slice(0, open) + raw.slice(close + CARRY_CLOSE.length)
    ).trim();
    const jsonStart = block.indexOf('[');
    if (jsonStart < 0) return { carried: [], text };
    try {
        const parsed = JSON.parse(block.slice(jsonStart)) as CarriedTurn[];
        // A hand-edited or truncated block must not take the message down with it.
        if (!Array.isArray(parsed)) return { carried: [], text };
        return {
            carried: parsed.filter(
                (t) =>
                    t &&
                    typeof t.text === 'string' &&
                    typeof t.isUser === 'boolean'
            ),
            text,
        };
    } catch {
        return { carried: [], text };
    }
}
