import type { Node } from '@xyflow/react';

import { getProviderMetadata, ModelProvider } from '~/types/provider';
import type { NodeUpdatePayload } from '~/lib/applyNodeUpdate';
import { isLocalEdition } from '~/lib/edition';
import { CLI_MODEL_PROVIDER, DEFAULT_AGENT_MODEL, LLM_HARNESS, harnessOf } from '~/lib/agentChat';
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

/** What each CLI harness is called on a node, keyed by its model id; the first
 *  is the one written. Mirrors backend AGENT_HARNESS_NAMES
 *  (coder/workflow/workflow_ops.py). */
export const AGENT_HARNESS_NAMES: Readonly<Record<string, readonly string[]>> =
    {
        'claude-code': ['Claude Code'],
        codex: ['Codex', 'OpenAI Codex'],
        opencode: ['OpenCode'],
        openclaw: ['OpenClaw'],
        hermes: ['Hermes', 'Hermes Agent'],
    };
// NoClick's own runtime (any model that isn't a CLI harness) is named like a
// new agent node.
const SDK_AGENT_LABEL = 'AI Agent';

// Each CLI harness's own config fields — what its schema variant adds to the
// fields every variant has (opencode → opencode_model), read from the
// generated schema like the sub-model defaults above.
function readHarnessOwnFields(): Record<string, string[]> {
    const variants = Object.values(
        (
            agentSchema as {
                $defs?: Record<
                    string,
                    { properties?: Record<string, { default?: unknown }> }
                >;
            }
        ).$defs ?? {}
    ).filter((variant) => variant.properties?.model_type);
    const shared = variants
        .map((variant) => Object.keys(variant.properties ?? {}))
        .reduce((common, keys) => common.filter((key) => keys.includes(key)));
    const out: Record<string, string[]> = {};
    for (const variant of variants) {
        const model = variant.properties?.model?.default;
        if (typeof model === 'string' && model in CLI_MODEL_PROVIDER) {
            out[model] = Object.keys(variant.properties ?? {}).filter(
                (key) => !shared.includes(key)
            );
        }
    }
    return out;
}

export const HARNESS_OWN_FIELDS: Readonly<Record<string, readonly string[]>> =
    readHarnessOwnFields();

/** A user's edit that moves an agent to another harness also clears the old
 *  harness's own fields (`null` deletes in applyNodeUpdate) and renames a node
 *  named after it ("OpenCode", "OpenCode agent"), unless the edit names the
 *  node itself. Credentials follow the provider on their own
 *  (staleCredentialKeysForProvider). Mirrors backend switch_agent_harness
 *  (coder/workflow/workflow_ops.py). */
export function withAgentHarnessSwitch(
    node: Node | undefined,
    update: NodeUpdatePayload
): NodeUpdatePayload {
    const nextModel = readTrimmedString(update.config?.model);
    if (node?.type !== 'agent' || !nextModel) return update;
    const data = (node.data ?? {}) as Record<string, unknown>;
    const config = getAgentConfigRecord(data);
    const from = harnessOf(getAgentSelectedModel(undefined, config));
    const to = harnessOf(nextModel);
    if (from === to) return update;

    const kept = HARNESS_OWN_FIELDS[to] ?? [];
    const cleared = (HARNESS_OWN_FIELDS[from] ?? []).filter(
        (key) => key in config && !kept.includes(key)
    );
    const label = (readTrimmedString(data.label) ?? '').toLowerCase();
    const named = (AGENT_HARNESS_NAMES[from] ?? []).some(
        (name) =>
            label === name.toLowerCase() ||
            label === `${name.toLowerCase()} agent`
    );
    return {
        ...update,
        config: {
            ...update.config,
            ...Object.fromEntries(cleared.map((key) => [key, null])),
        },
        ...(named && update.label === undefined
            ? { label: AGENT_HARNESS_NAMES[to]?.[0] ?? SDK_AGENT_LABEL }
            : {}),
    };
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

/** The provider an agent credential type is for (`agent_claude_code_oauth` → claude_code); null for any other type. */
export function agentCredentialProvider(credentialType: string | undefined): ModelProvider | null {
    return credentialType?.startsWith('agent_') ? (credentialType.slice('agent_'.length).replace(/_oauth$/, '') as ModelProvider) : null;
}

// Subscription-OAuth credential type that stands in for a provider's
// `agent_<provider>` key. When the user signs in with ChatGPT Plus / Claude
// Pro-Max / GitHub Copilot / SuperGrok instead of pasting an API key, the
// credential is stored under the OAuth-specific type — so every surface that
// asks "is this provider credentialed?" has to accept it too.
//
// The wrapper entries (OPENAI / XAI) exist because the CLI wrappers can reach
// those providers over the same OAuth clients:
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
// ANTHROPIC has none: a Claude plan runs only in Claude Code, so anthropic/*
// on any other harness takes an API key (claudePlanRefusal says so).
//
// Mirrors backend AGENT_OAUTH_CREDENTIAL_TYPES (nodes/agent/config/providers.py).
const AGENT_OAUTH_ALIAS: Partial<Record<ModelProvider, string>> = {
    [ModelProvider.CODEX]: 'agent_codex_oauth',
    [ModelProvider.OPENAI]: 'agent_codex_oauth',
    [ModelProvider.CLAUDE_CODE]: 'agent_claude_code_oauth',
    [ModelProvider.XAI]: 'agent_xai_oauth',
    [ModelProvider.GITHUB_COPILOT]: 'agent_github_copilot_oauth',
};

const CLAUDE_PLAN_CREDENTIAL_TYPE = 'agent_claude_code_oauth';
// Mirrors backend CLAUDE_PLAN_REFUSAL (nodes/agent/config/providers.py).
export const CLAUDE_PLAN_REFUSAL =
    'A Claude plan runs only in Claude Code. Use an Anthropic API key, or switch the agent to Claude Code.';

// A vendor's CLI harness and its models read the same API key
// (ANTHROPIC_API_KEY, OPENAI_API_KEY), so a key saved under either type serves
// both. Mirrors backend AGENT_VENDOR_KEY_ALIASES (nodes/agent/config/providers.py).
const AGENT_VENDOR_KEY_ALIAS: Partial<Record<ModelProvider, string>> = {
    [ModelProvider.CLAUDE_CODE]: 'agent_anthropic',
    [ModelProvider.ANTHROPIC]: 'agent_claude_code',
    [ModelProvider.CODEX]: 'agent_openai',
    [ModelProvider.OPENAI]: 'agent_codex',
};

/** The other vendor type an API key for `provider` may be saved under. */
export function agentVendorKeyAlias(
    provider: ModelProvider | null
): string | undefined {
    return provider ? AGENT_VENDOR_KEY_ALIAS[provider] : undefined;
}

/** What each subscription sign-in is called: the plan it uses, and whom you sign in with. */
export const AGENT_SIGN_IN_NAMES: Readonly<Record<string, { subscription: string; signInWith: string }>> = {
    agent_claude_code_oauth: { subscription: 'Claude', signInWith: 'Claude' },
    agent_codex_oauth: { subscription: 'ChatGPT', signInWith: 'ChatGPT' },
    agent_github_copilot_oauth: { subscription: 'Copilot', signInWith: 'GitHub' },
    agent_xai_oauth: { subscription: 'SuperGrok', signInWith: 'xAI' },
};

/** Every credential_type that satisfies `provider` for an agent: the direct
 *  `agent_<provider>` key, its vendor key alias and its OAuth alias
 *  (agent_codex_oauth etc.). The listing-side twin of
 *  getAgentCredentialIdForProvider — used to match a user's saved credentials
 *  against a harness, not a node's attachment. */
export function acceptedAgentCredentialTypes(
    provider: ModelProvider | null
): string[] {
    if (!provider) return [];
    return [
        getAgentCredentialType(provider),
        AGENT_VENDOR_KEY_ALIAS[provider],
        AGENT_OAUTH_ALIAS[provider],
    ].filter((type): type is string => !!type);
}

export function getAgentCredentialIdForProvider(
    credentialIds: Record<string, string>,
    provider: ModelProvider | null
): string | undefined {
    for (const type of acceptedAgentCredentialTypes(provider)) {
        const id = credentialIds[type]?.trim();
        if (id) return credentialIds[type];
    }
    return undefined;
}

/** CLAUDE_PLAN_REFUSAL when a Claude plan is attached to an anthropic/* model
 *  (any harness but Claude Code) and nothing attached runs it, else null.
 *  Mirrors backend claude_plan_refusal (nodes/agent/config/providers.py). */
export function claudePlanRefusal(
    credentialIds: Record<string, string>,
    provider: ModelProvider | null
): string | null {
    return provider === ModelProvider.ANTHROPIC &&
        credentialIds[CLAUDE_PLAN_CREDENTIAL_TYPE]?.trim() &&
        !getAgentCredentialIdForProvider(credentialIds, provider)
        ? CLAUDE_PLAN_REFUSAL
        : null;
}

/** The linked `agent_*` credential keys that are NOT valid for `provider` — callers
 *  delete these when the model's provider changes so the backend never forwards a
 *  wrong-provider token. "Valid" is getAgentCredentialIdForProvider (direct key +
 *  OAuth aliases), so a valid OAuth credential (e.g. agent_claude_code_oauth for
 *  claude_code) is never treated as stale. A naive `agent_<provider>` match wrongly
 *  deleted those, resetting the agent's credential to none on mount. A refused
 *  Claude plan stays linked so the node can say why (claudePlanRefusal), and
 *  switching the agent to Claude Code takes it back. */
export function staleCredentialKeysForProvider(
    credentialIds: Record<string, string>,
    provider: ModelProvider | null
): string[] {
    const validId = getAgentCredentialIdForProvider(credentialIds, provider);
    const refusedPlan = claudePlanRefusal(credentialIds, provider)
        ? CLAUDE_PLAN_CREDENTIAL_TYPE
        : null;
    return Object.keys(credentialIds).filter(
        (k) =>
            isPrimaryAgentCredentialKey(k) &&
            credentialIds[k] &&
            credentialIds[k] !== validId &&
            k !== refusedPlan
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
 *  claude_code, cross-aliases like openai←agent_codex_oauth). A naive
 *  agent_<provider> match used to reject those valid credentials. Usage-based
 *  providers may run credential-less; a hard mismatch (some other agent_* set, but
 *  nothing valid for this provider) is flagged, a refused Claude plan in the
 *  backend's words. */
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
    const refusal = claudePlanRefusal(
        linked,
        effectiveProvider as ModelProvider
    );
    if (refusal) return refusal;
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
    // `retired`: hidden from the picker but still served (codex names a
    // replacement), so a saved selection keeps resolving instead of being gated.
    return (
        cliModels.codex.models.includes(modelId) ||
        Object.prototype.hasOwnProperty.call(cliModels.codex.retired ?? {}, modelId)
    );
}

// Model-id prefix → the provider whose credential it runs on, first match wins.
// OpenCode's priority providers first, then the free ones it reaches.
// OpenCode Zen + Go share the same OPENCODE_API_KEY and the same opencode.ai/auth
// dashboard, so both prefixes fold into OPENCODE and one credential serves both
// catalogs. github-copilot signs in by device code (github.com/login/device), not
// an env-var key: the form renders the Copilot sign-in, and the resulting
// agent_github_copilot_oauth credential is translated by opencode.py into
// OPENCODE_AUTH_CONTENT at sandbox-injection time.
const AGENT_MODEL_PREFIXES: ReadonlyArray<readonly [string, ModelProvider]> = [
    ['openrouter/', ModelProvider.OPENROUTER],
    ['anthropic/', ModelProvider.ANTHROPIC],
    ['openai/', ModelProvider.OPENAI],
    ['gemini/', ModelProvider.GEMINI],
    ['google/', ModelProvider.GEMINI],
    ['xai/', ModelProvider.XAI],
    ['groq/', ModelProvider.GROQ],
    ['deepseek/', ModelProvider.DEEPSEEK],
    ['mistral/', ModelProvider.MISTRAL],
    ['opencode/', ModelProvider.OPENCODE],
    ['opencode-go/', ModelProvider.OPENCODE],
    ['github-models/', ModelProvider.GITHUB_MODELS],
    ['nvidia/', ModelProvider.NVIDIA],
    ['github-copilot/', ModelProvider.GITHUB_COPILOT],
];

export function inferProviderFromPrefix(model: string): ModelProvider | null {
    return AGENT_MODEL_PREFIXES.find(([prefix]) => model.startsWith(prefix))?.[1] ?? null;
}

// CLI agent providers with a subscription sign-in, keyed the way the backend's
// instance-status reports them (harness_oauth_flows.AGENT_PROVIDER_OAUTH_TYPE).
// Which of these THIS instance can complete comes from that report.
export const AGENT_OAUTH_PROVIDER_KEY: Partial<Record<ModelProvider, string>> = {
    [ModelProvider.CODEX]: 'codex',
    [ModelProvider.CLAUDE_CODE]: 'claude_code',
    [ModelProvider.GITHUB_COPILOT]: 'github_copilot',
    [ModelProvider.XAI]: 'xai',
};

/** Providers connected only by signing in: there is no key to paste. */
export function isSignInOnlyAgentProvider(provider: ModelProvider | null): boolean {
    return provider === ModelProvider.GITHUB_COPILOT;
}

/** Every provider an agent can run on: the CLI harnesses, then the providers agent models route to, each once. */
function agentRuntimeProviders(): ModelProvider[] {
    const all = [...(Object.values(CLI_MODEL_PROVIDER) as ModelProvider[]), ...AGENT_MODEL_PREFIXES.map(([, provider]) => provider)];
    return all.filter((provider, i) => all.indexOf(provider) === i && !!getProviderMetadata(provider));
}

// Two providers are one account when they take the same key or the same sign-in:
// Claude Code runs on an Anthropic key or a Claude sign-in, OpenClaw on an OpenRouter key.
function shareAnAccount(a: ModelProvider, b: ModelProvider): boolean {
    const key = (p: ModelProvider) => (getProviderMetadata(p)?.requiredApiKeys?.[0] ?? []).join('+');
    return a !== b && ((!!key(a) && key(a) === key(b)) || (!!AGENT_OAUTH_ALIAS[a] && AGENT_OAUTH_ALIAS[a] === AGENT_OAUTH_ALIAS[b]));
}

/** The other providers whose credentials are this one's account: their keys hold the same secret. */
export function sameAccountAgentProviders(provider: ModelProvider | null): ModelProvider[] {
    return provider ? agentRuntimeProviders().filter((other) => shareAnAccount(provider, other)) : [];
}

/** A company agents run on, one entry in Connections: the providers whose keys and sign-ins it issues, its own first. */
export interface AgentCompany {
    id: string;
    title: string;
    members: ModelProvider[];
}

// Products of one company that share no key and no sign-in, so their credentials can't say they're one company.
// GitHub's is named for Copilot, its mark leading: Connections lists it beside the GitHub app.
const PRODUCT_FAMILIES: ReadonlyArray<{ id: string; title: string; members: readonly ModelProvider[] }> = [
    { id: 'github', title: 'GitHub Copilot', members: [ModelProvider.GITHUB_COPILOT, ModelProvider.GITHUB_MODELS] },
];

let companies: AgentCompany[] | null = null;

/** Every company agents can run on, each once. Providers that share an account are one company (a CLI harness and
 *  the provider whose key it takes), and so is a product family; a company is its own provider, the one that isn't a
 *  CLI harness. */
export function agentCompanies(): AgentCompany[] {
    if (companies) return companies;
    const providers = agentRuntimeProviders();
    const harnesses = new Set<string>(Object.values(CLI_MODEL_PROVIDER));
    const familyOf = (p: ModelProvider) => PRODUCT_FAMILIES.find((family) => family.members.includes(p));
    const linked = (a: ModelProvider, b: ModelProvider) => shareAnAccount(a, b) || (!!familyOf(a) && familyOf(a) === familyOf(b));
    const out: AgentCompany[] = [];
    for (const provider of providers) {
        if (out.some((company) => company.members.includes(provider))) continue;
        const group = [provider];
        for (let i = 0; i < group.length; i++) {
            for (const other of providers) if (!group.includes(other) && linked(group[i], other)) group.push(other);
        }
        const members = providers.filter((p) => group.includes(p));
        const family = familyOf(provider);
        const own = (family ? family.members.find((p) => members.includes(p)) : members.find((p) => !harnesses.has(p))) ?? members[0];
        out.push({
            id: family?.id ?? own,
            title: family?.title ?? getProviderMetadata(own)!.title,
            members: [own, ...members.filter((p) => p !== own)],
        });
    }
    companies = out;
    return out;
}
