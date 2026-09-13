// Pure helpers shared between AgentChatBlock (the interface-tab chat UI) and
// FlowCanvas#handleAgentChatSend (the chat → run-the-agent dispatcher). Kept
// pure and side-effect-free so they're easy to unit test against arbitrary
// agent model variants (gpt-4o-mini, claude-code, openclaw, hermes, …)
// without spinning up the backend or socket.

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

/** Fences a carried thread inside the message that carries it — the block the
 *  backend's session-interchange fallback writes (nodes/agent/interchange/
 *  fallback.py), and the one this client wrote itself until 2026-09-13, when
 *  a model switch minted a fresh conversation here. Those stored messages
 *  persist, and a message is what the transcript SHOWS, so the display strips
 *  the block back out — the same trick __NOCLICK_SEQUENCE__ uses for
 *  interleaved image payloads. */
const CARRY_OPEN = '<<<NOCLICK_CARRIED_CONTEXT';
const CARRY_CLOSE = 'NOCLICK_CARRIED_CONTEXT>>>';

export interface CarriedTurn {
    isUser: boolean;
    text: string;
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
