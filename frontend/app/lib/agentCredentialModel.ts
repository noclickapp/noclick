import { getProviderMetadata, ModelProvider } from '~/types/provider';
import { isLocalEdition } from '~/lib/edition';
import { DEFAULT_AGENT_MODEL, LLM_HARNESS, harnessOf } from '~/lib/agentChat';
import agentSchema from '~/schemas/nodes/agent.json';

export type AgentConfigRecord = Record<string, unknown> | null | undefined;

/** Credential type holding environment variables exposed to an agent process. */
export const AGENT_ENV_CREDENTIAL_TYPE = 'agent_env';

/** Whether an `agent_*` credentialIds key authenticates the agent ITSELF.
 *
 *  `agent_env` rides the same map (so the pre-delete impact scan and
 *  workflow_authorized_credentials can see it) but is a SECONDARY credential —
 *  process env vars, not auth. Every "switch model / swap credential" path purges
 *  `agent_*` keys to enforce one-provider-credential-at-a-time; without this
 *  predicate those purges would silently delete the user's env bundle, and the
 *  mismatch validator would report "the linked credential is for env".
 *  Mirrors backend utils.credentials._NON_PRIMARY_CREDENTIAL_TYPES. */
export function isPrimaryAgentCredentialKey(key: string): boolean {
    return key.startsWith('agent_') && key !== AGENT_ENV_CREDENTIAL_TYPE;
}

const WRAPPER_MODEL_BY_TYPE = {
    hermes_agent: 'hermes',
    openclaw: 'openclaw',
} as const;

// Wrapper agents that expose a sub-model field on their node config. When the
// sub-model is set, credential UI and backend cred-resolution both follow it
// to the underlying provider (e.g. hermes picking `openrouter/...` →
// OPENROUTER credential, opencode picking `anthropic/...` → ANTHROPIC
// credential). When the sub-model is unset, the wrapper name itself is used
// as the effective model so the form falls back to the wrapper's own
// provider metadata.
//
// `opencode` is here because the OpenCode CLI fans out to multiple upstream
// providers depending on the sub-model the user picks (opencode/* via Zen,
// anthropic/* via Anthropic, openai/* via OpenAI, etc.). Without this entry
// the form would always show OpenCode's `requiredApiKeys` regardless of the
// sub-model — including for users whose actual upstream is Anthropic.
const WRAPPER_SUBMODEL_FIELD_BY_MODEL = {
    hermes: 'hermes_agent_model',
    openclaw: 'openclaw_model',
    opencode: 'opencode_model',
} as const;

// Default sub-model per wrapper harness, read straight from the generated agent
// schema so it can NEVER drift from the backend Pydantic default (same
// derivation contract as DEFAULT_AGENT_MODEL in agentChat.ts). Each field's
// default lives under its own $defs variant (OpenClawConfig, OpenCodeConfig,
// HermesAgentConfig), so we scan every variant for the field. Assert loudly on
// a schema-shape change rather than silently seeding a wrong/empty model.
function readWrapperSubmodelDefaults(): Record<string, string> {
    const defs =
        (
            agentSchema as {
                $defs?: Record<
                    string,
                    { properties?: Record<string, { default?: unknown }> }
                >;
            }
        ).$defs ?? {};
    const out: Record<string, string> = {};
    for (const [harness, field] of Object.entries(
        WRAPPER_SUBMODEL_FIELD_BY_MODEL
    )) {
        let resolved: unknown;
        for (const variant of Object.values(defs)) {
            const def = variant?.properties?.[field]?.default;
            if (def !== undefined) {
                resolved = def;
                break;
            }
        }
        if (typeof resolved !== 'string' || !resolved) {
            throw new Error(
                `agentCredentialModel: could not resolve ${field}.default from ` +
                    'agent.json $defs — the generated schema shape changed; fix this derivation.'
            );
        }
        out[harness] = resolved;
    }
    return out;
}

export const WRAPPER_SUBMODEL_DEFAULT_BY_MODEL: Readonly<
    Record<string, string>
> = readWrapperSubmodelDefaults();

// Config patch to apply whenever a wrapper harness (openclaw/opencode/hermes) is
// selected or a node is created with one. The wrapper's real model lives in a
// sub-model field; when that field is empty, downstream UI + credential
// resolution fall back to the bare wrapper id — which mislabels the credential
// ("OpenClaw API Key") and shows "Select…". Seeding the schema default keeps the
// PERSISTED config carrying a concrete provider-prefixed model. No-op for
// non-wrapper models and when the sub-model is already set.
export function seedWrapperSubmodel(
    modelId: string | undefined,
    config?: AgentConfigRecord
): Record<string, string> {
    const harness = readTrimmedString(modelId);
    if (!harness) return {};
    const field =
        WRAPPER_SUBMODEL_FIELD_BY_MODEL[
            harness as keyof typeof WRAPPER_SUBMODEL_FIELD_BY_MODEL
        ];
    if (!field) return {};
    const existing = readTrimmedString(getAgentConfigRecord(config)?.[field]);
    if (existing) return {};
    return { [field]: WRAPPER_SUBMODEL_DEFAULT_BY_MODEL[harness] };
}

function readTrimmedString(value: unknown): string | undefined {
    if (typeof value !== 'string') return undefined;
    const trimmed = value.trim();
    return trimmed === '' ? undefined : trimmed;
}

export function getAgentConfigRecord(
    nodeData: AgentConfigRecord
): Record<string, unknown> {
    const nested = nodeData?.config;
    return nested && typeof nested === 'object' && !Array.isArray(nested)
        ? (nested as Record<string, unknown>)
        : (nodeData ?? {});
}

export function getAgentCredentialType(provider: ModelProvider): string {
    return `agent_${provider}`;
}

// Subscription-OAuth credential type that stands in for a provider's
// `agent_<provider>` key. When the user signs in with ChatGPT Plus / Claude
// Pro-Max / GitHub Copilot / SuperGrok instead of pasting an API key, the
// credential is stored under the OAuth-specific type — so every surface that
// asks "is this provider credentialed?" has to accept it too.
//
// The OpenCode wrapper entries (OPENAI / XAI / ANTHROPIC) exist because
// opencode-ai can reach those providers over the same OAuth clients:
//
// OPENAI ← agent_codex_oauth: opencode-ai's CodexAuthPlugin uses the same
// OAuth CLIENT_ID as OpenAI's codex CLI. Eligible models are limited to the
// daily-refreshed Codex CLI list — AgentCredentialsForm hides Codex OAuth from
// the OPENAI dropdown when the selected sub-model isn't in that list (see
// isChatGptPlusSupported). The lookup below stays model-agnostic so a
// previously-saved OAuth selection still resolves; the runtime guard in
// opencode.py catches any stale combination with an actionable error.
//
// XAI ← agent_xai_oauth: opencode-ai's xAI plugin uses the same Grok-CLI
// client. Tokens are interchangeable for all xai/* models.
//
// ANTHROPIC ← agent_claude_code_oauth: opencode-ai dropped its bundled
// Anthropic OAuth provider in v1.3.0, but NoClick re-enables it via a vendored
// community plugin bundled with the hosted OpenCode runtime (see backend/nodes/agent/
// handlers/opencode_plugins/anthropic_oauth.mjs). The plugin's fetch
// interceptor reads the OAuth credential out of auth.json and rewrites
// api.anthropic.com requests to use Bearer auth + the anthropic-beta flags.
//
// Mirrors backend AGENT_OAUTH_CREDENTIAL_TYPES (nodes/agent/config/providers.py).
const AGENT_OAUTH_ALIAS: Partial<Record<ModelProvider, string>> = {
    [ModelProvider.CODEX]: 'agent_codex_oauth',
    [ModelProvider.OPENAI]: 'agent_codex_oauth',
    [ModelProvider.CLAUDE_CODE]: 'agent_claude_code_oauth',
    [ModelProvider.ANTHROPIC]: 'agent_claude_code_oauth',
    [ModelProvider.XAI]: 'agent_xai_oauth',
    [ModelProvider.GITHUB_COPILOT]: 'agent_github_copilot_oauth',
};

/** Every credential_type that satisfies `provider` for an agent: the direct
 *  `agent_<provider>` key plus its OAuth alias (agent_codex_oauth etc.).
 *  The listing-side twin of getAgentCredentialIdForProvider — used to match
 *  a user's saved credentials against a harness, not a node's attachment. */
export function acceptedAgentCredentialTypes(
    provider: ModelProvider | null
): string[] {
    if (!provider) return [];
    const out = [getAgentCredentialType(provider)];
    const alias = AGENT_OAUTH_ALIAS[provider];
    if (alias) out.push(alias);
    return out;
}

export function getAgentCredentialIdForProvider(
    credentialIds: Record<string, string>,
    provider: ModelProvider | null
): string | undefined {
    if (!provider) return undefined;

    const direct = credentialIds[getAgentCredentialType(provider)];
    if (direct?.trim()) return direct;

    const alias = AGENT_OAUTH_ALIAS[provider];
    return (alias && credentialIds[alias]?.trim()) || undefined;
}

/** The linked `agent_*` credential keys that are NOT valid for `provider` — callers
 *  delete these when the model's provider changes so the backend never forwards a
 *  wrong-provider token. "Valid" is getAgentCredentialIdForProvider (direct key +
 *  OAuth aliases), so a valid OAuth credential (e.g. agent_claude_code_oauth for
 *  claude_code) is never treated as stale. A naive `agent_<provider>` match wrongly
 *  deleted those, resetting the agent's credential to none on mount. */
export function staleCredentialKeysForProvider(
    credentialIds: Record<string, string>,
    provider: ModelProvider | null
): string[] {
    const validId = getAgentCredentialIdForProvider(credentialIds, provider);
    return Object.keys(credentialIds).filter(
        (k) =>
            isPrimaryAgentCredentialKey(k) &&
            credentialIds[k] &&
            credentialIds[k] !== validId
    );
}

/** Whether NoClick's usage-based billing can fund this agent with NO user
 *  credential — the ONE rule every credential surface must apply (config-panel
 *  banner, canvas badge, credentials form, chat send gate).
 *
 *  `allowUsageBased` is PROVIDER-scoped in the metadata, which is only true on
 *  the in-process LLM path (we call the provider with NoClick's key and bill the
 *  call). A CLI harness runs the vendor binary with its own environment and
 *  authenticates upstream itself — there is no NoClick-key fallback and no
 *  per-call cost capture — so its credential is mandatory however the provider
 *  normally bills. Judge that from the TOP-LEVEL selected model (`hermes`,
 *  `opencode`, …), never the resolved sub-model: a wrapper's sub-model is a
 *  plain `openrouter/…` id whose provider flag says "usage-based" and silently
 *  waved the requirement through.
 *
 *  Mirrors backend `agent_credential_requirement` (nodes/agent/config/providers.py). */
export function agentAllowsUsageBased(
    selectedModel: string | undefined,
    provider: string | null
): boolean {
    if (!provider) return false;
    if (harnessOf(selectedModel) !== LLM_HARNESS) return false;
    // Usage-based billing is the hosted service's platform key; a self-hosted
    // instance has no such thing to fall back to.
    if (isLocalEdition()) return false;
    return (
        getProviderMetadata(provider as ModelProvider)?.allowUsageBased ?? false
    );
}

/** Pre-flight credential check before dispatching a chat send — catches the common
 *  "switched models but forgot to update credentials" case. Returns null when safe
 *  to dispatch, or a user-facing message.
 *
 *  The "is a valid credential linked?" question delegates to
 *  getAgentCredentialIdForProvider — the SAME resolver the credentials form and the
 *  backend loader use — so the gate accepts everything they do: a direct
 *  agent_<provider> key AND subscription-OAuth aliases (agent_claude_code_oauth for
 *  claude_code, cross-aliases like anthropic←agent_claude_code_oauth). A naive
 *  agent_<provider> match used to reject those valid credentials. Usage-based
 *  providers may run credential-less; a hard mismatch (some other agent_* set, but
 *  nothing valid for this provider) is flagged. */
export function validateAgentCredentialsForModel(args: {
    effectiveProvider: string | null;
    /** True if the provider supports usage-based billing (cred optional). */
    usageBased: boolean;
    credentialIds: Record<string, string> | undefined;
}): string | null {
    const { effectiveProvider, usageBased, credentialIds } = args;
    if (!effectiveProvider) return null;
    const linked = credentialIds || {};
    if (
        getAgentCredentialIdForProvider(
            linked,
            effectiveProvider as ModelProvider
        )
    )
        return null;
    const otherAgentKey = Object.keys(linked).find(
        (k) => isPrimaryAgentCredentialKey(k) && linked[k]
    );
    if (otherAgentKey) {
        const have = otherAgentKey.replace(/^agent_/, '').replace(/_/g, '-');
        return `The linked credential is for ${have}, but this model routes through ${effectiveProvider}. Pick or create a ${effectiveProvider} credential in the Credentials panel.`;
    }
    if (usageBased) return null;
    return `This model needs a ${effectiveProvider} credential. Add one in the Credentials panel before sending.`;
}

/** Full send-path pre-flight: resolve the (conversation-locked or selected)
 *  model to its effective provider — wrapper harnesses carry the real provider
 *  on their sub-model field — and validate the linked credentials against it.
 *  CLI harnesses are ALWAYS BYOK (see agentAllowsUsageBased): a credential-less
 *  openrouter sub-model under opencode used to sail past this gate and die on
 *  the backend's OPENROUTER_API_KEY error. */
/** Whether this chat will run under a DIFFERENT provider than the picker shows.
 *
 *  A conversation keeps the model it started with, so switching the node's model
 *  between sessions leaves the chat on the old one. Exported because two places
 *  need the same answer and must not drift: the message (which has to name the
 *  pin rather than blame the current selection) and the recovery action (a new
 *  conversation is the only thing that moves a pin — no credential edit does). */
export function conversationNeedsFreshThread(args: {
    /** The model the conversation was created with. */
    sendModel: string;
    /** The model the picker shows now. */
    selectedModel: string;
    config: AgentConfigRecord;
    resolveProvider: (model: string) => string | null;
}): boolean {
    const { sendModel, selectedModel, config, resolveProvider } = args;
    // Different harness: codex's --resume volume, claude-code's --continue
    // volume and openclaw's local state are disjoint, so the thread cannot
    // continue even when both route through the same provider.
    if (harnessOf(sendModel) !== harnessOf(selectedModel)) return true;
    // Same harness, different provider: different credential and routing.
    return (
        resolveProvider(getAgentEffectiveModel(sendModel, config)) !==
        resolveProvider(getAgentEffectiveModel(selectedModel, config))
    );
}

export function validateAgentSendCredentials(args: {
    /** The model this send will ACTUALLY run under. A chat whose picked model
     *  has moved to another provider mints a fresh conversation on send, so
     *  that is the picked model — validating the OLD one told a correctly
     *  configured agent its credential was wrong. */
    sendModel: string;
    config: AgentConfigRecord;
    credentialIds: Record<string, string> | undefined;
    /** Model-catalog provider lookup (the caller's getModelById + prefix inference). */
    resolveProvider: (model: string) => string | null;
}): string | null {
    const { sendModel, config, credentialIds, resolveProvider } = args;
    const effectiveProvider = resolveProvider(
        getAgentEffectiveModel(sendModel, config)
    );
    return validateAgentCredentialsForModel({
        effectiveProvider,
        usageBased: agentAllowsUsageBased(sendModel, effectiveProvider),
        credentialIds,
    });
}

export function getAgentSelectedModel(
    model: string | undefined,
    config?: AgentConfigRecord
): string {
    const explicitModel =
        readTrimmedString(model) ?? readTrimmedString(config?.model);
    if (explicitModel) {
        return explicitModel;
    }

    const modelType = readTrimmedString(config?.model_type)?.toLowerCase();
    if (modelType && modelType in WRAPPER_MODEL_BY_TYPE) {
        return WRAPPER_MODEL_BY_TYPE[
            modelType as keyof typeof WRAPPER_MODEL_BY_TYPE
        ];
    }

    return DEFAULT_AGENT_MODEL;
}

export function getAgentEffectiveModel(
    model: string | undefined,
    config?: AgentConfigRecord
): string {
    const selectedModel = getAgentSelectedModel(model, config);
    const subField =
        WRAPPER_SUBMODEL_FIELD_BY_MODEL[
            selectedModel as keyof typeof WRAPPER_SUBMODEL_FIELD_BY_MODEL
        ];
    if (!subField) {
        return selectedModel;
    }

    // Wrapper with an empty sub-model: resolve to the wrapper's DEFAULT
    // sub-model (a real, provider-prefixed model id) rather than the bare
    // wrapper id. The bare id isn't a real model — it mislabels the credential
    // and makes cred-resolution demand a nonexistent `agent_<wrapper>` key
    // instead of the underlying provider's. This matches the model the backend
    // runs by default (the Pydantic default the FE otherwise never sees).
    return (
        readTrimmedString(config?.[subField]) ??
        WRAPPER_SUBMODEL_DEFAULT_BY_MODEL[selectedModel]
    );
}

// Catalog-miss fallback for credential UI: when getModelById can't find a
// model (typical for the dynamic, models.dev-sourced sub-models like
// `opencode/mimo-v2-flash-free` or `openrouter/anthropic/claude-3.5-sonnet`),
// derive the provider from the id prefix. Order matters only for
// readability; prefixes don't overlap.
//
// All twelve prefixes the OpenCode picker can produce (the nine priority +
// three of the four free providers; github-copilot is omitted because its
// auth is device-code OAuth, not env-var — see note below) are covered
// here so wrapping a sub-model in OpenCode always resolves to a provider
// with a credential schema and dashboard URL.
//
// Returns null for ids that don't carry a recognisable provider prefix so
// callers can fall through to their own default (typically the wrapper
// provider itself).
// Daily-refreshed Codex CLI model list — also drives the Codex node's
// dropdown. Single source of truth for which openai/* sub-models are
// reachable via ChatGPT Plus OAuth in the OpenCode wrapper. The JSON
// is regenerated by .github/workflows/refresh-cli-models.yml and mirrored
// into app/schemas by scripts/generate_socket_types.py on every commit.
import cliModels from '~/schemas/cli-models.json';

/**
 * FE mirror of backend `_is_chatgpt_plus_supported` in
 * `nodes/agent/handlers/opencode.py`. Returns true iff the bare model
 * id is in the daily-refreshed Codex CLI list — opencode-ai's
 * CodexAuthPlugin only accepts that subset over ChatGPT Plus OAuth.
 *
 * Used by `AgentCredentialsForm` to exclude `agent_codex_oauth` from
 * the OPENAI provider's matching-credentials list when the user picks
 * a wrapper sub-model that opencode-ai would reject — so the OAuth
 * option never appears for an unsupported model in the first place.
 *
 * Accepts a bare model id (e.g. "gpt-5.4-mini"), not the prefixed
 * "openai/..." form. Callers should strip the provider prefix first.
 */
export function isChatGptPlusSupported(modelId: string): boolean {
    return cliModels.codex.models.includes(modelId);
}

export function inferProviderFromPrefix(model: string): ModelProvider | null {
    // ── OpenCode priority providers ────────────────────────────────────
    if (model.startsWith('openrouter/')) return ModelProvider.OPENROUTER;
    if (model.startsWith('anthropic/')) return ModelProvider.ANTHROPIC;
    if (model.startsWith('openai/')) return ModelProvider.OPENAI;
    if (model.startsWith('gemini/') || model.startsWith('google/')) {
        return ModelProvider.GEMINI;
    }
    if (model.startsWith('xai/')) return ModelProvider.XAI;
    if (model.startsWith('groq/')) return ModelProvider.GROQ;
    if (model.startsWith('deepseek/')) return ModelProvider.DEEPSEEK;
    if (model.startsWith('mistral/')) return ModelProvider.MISTRAL;
    // OpenCode Zen + Go share the same OPENCODE_API_KEY and the same
    // opencode.ai/auth dashboard — fold both prefixes into the OPENCODE
    // provider so credentials are reused across the two model catalogs.
    if (model.startsWith('opencode/') || model.startsWith('opencode-go/')) {
        return ModelProvider.OPENCODE;
    }
    // ── OpenCode free providers ────────────────────────────────────────
    if (model.startsWith('github-models/')) return ModelProvider.GITHUB_MODELS;
    if (model.startsWith('nvidia/')) return ModelProvider.NVIDIA;
    // github-copilot uses device-code OAuth (github.com/login/device)
    // rather than an env-var API key. The form's OAuth-path special-case
    // renders <GithubCopilotOAuth /> instead of a paste-key field. The
    // resulting agent_github_copilot_oauth credential is translated by
    // opencode.py into OPENCODE_AUTH_CONTENT at sandbox-injection time.
    if (model.startsWith('github-copilot/'))
        return ModelProvider.GITHUB_COPILOT;
    return null;
}
