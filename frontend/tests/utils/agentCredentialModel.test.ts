import { describe, expect, it } from 'vitest';
import { ModelProvider } from '~/types/provider';
import {
    acceptedAgentCredentialTypes,
    CLAUDE_PLAN_REFUSAL,
    claudePlanRefusal,
    getAgentConfigRecord,
    staleCredentialKeysForProvider,
    validateAgentSendCredentials,
    getAgentCredentialIdForProvider,
    getAgentEffectiveModel,
    getAgentSelectedModel,
    inferProviderFromPrefix,
    WRAPPER_SUBMODEL_DEFAULT_BY_MODEL,
} from '~/lib/agentCredentialModel';

describe('agent credential model helpers', () => {
    it('reads agent config from the credentials tab wrapper shape', () => {
        const config = getAgentConfigRecord({
            operation: undefined,
            config: {
                model: 'anthropic/claude-sonnet-4.5',
            },
        });

        expect(getAgentSelectedModel(undefined, config)).toBe(
            'anthropic/claude-sonnet-4.5'
        );
    });

    it('uses wrapper submodel fields for effective provider credentials', () => {
        const config = {
            model: 'hermes',
            hermes_agent_model: 'groq/llama-3.3-70b-versatile',
        };

        expect(getAgentEffectiveModel(config.model, config)).toBe(
            'groq/llama-3.3-70b-versatile'
        );
    });

    it('ignores stale agent credentials from a different provider', () => {
        const credentialIds = {
            agent_openrouter: 'openrouter-credential-id',
        };

        expect(
            getAgentCredentialIdForProvider(credentialIds, ModelProvider.AZURE)
        ).toBeUndefined();
    });

    it('keeps CLI OAuth credentials scoped to their active provider', () => {
        const credentialIds = {
            agent_codex_oauth: 'codex-oauth-id',
            agent_claude_code_oauth: 'claude-oauth-id',
        };

        expect(
            getAgentCredentialIdForProvider(credentialIds, ModelProvider.CODEX)
        ).toBe('codex-oauth-id');
        expect(
            getAgentCredentialIdForProvider(
                credentialIds,
                ModelProvider.CLAUDE_CODE
            )
        ).toBe('claude-oauth-id');
        expect(
            getAgentCredentialIdForProvider(
                credentialIds,
                ModelProvider.OPENROUTER
            )
        ).toBeUndefined();
    });

    it('folds a vendor API key across its CLI harness and its models', () => {
        // One Anthropic key serves claude_code and anthropic/*, one OpenAI key
        // codex and openai/*, saved under either type — the backend's
        // AGENT_VENDOR_KEY_ALIASES (providers._requirement_for).
        const cases: [Record<string, string>, ModelProvider][] = [
            [{ agent_anthropic: 'k' }, ModelProvider.CLAUDE_CODE],
            [{ agent_claude_code: 'k' }, ModelProvider.ANTHROPIC],
            [{ agent_openai: 'k' }, ModelProvider.CODEX],
            [{ agent_codex: 'k' }, ModelProvider.OPENAI],
        ];
        for (const [credentialIds, provider] of cases) {
            expect(getAgentCredentialIdForProvider(credentialIds, provider)).toBe('k');
            // Valid, so switching to that model never purges it.
            expect(staleCredentialKeysForProvider(credentialIds, provider)).toEqual([]);
        }
        // The provider's own type still wins, and vendors never cross.
        expect(
            getAgentCredentialIdForProvider(
                { agent_anthropic: 'alias', agent_claude_code: 'direct' },
                ModelProvider.CLAUDE_CODE
            )
        ).toBe('direct');
        expect(
            getAgentCredentialIdForProvider({ agent_openai: 'k' }, ModelProvider.CLAUDE_CODE)
        ).toBeUndefined();
        expect(acceptedAgentCredentialTypes(ModelProvider.CODEX)).toEqual([
            'agent_codex',
            'agent_openai',
            'agent_codex_oauth',
        ]);
        expect(acceptedAgentCredentialTypes(ModelProvider.OPENROUTER)).toEqual([
            'agent_openrouter',
        ]);
    });

    it('takes a Claude plan for Claude Code alone', () => {
        // A Claude plan runs only in Claude Code: anthropic/* on any other
        // harness takes a key, and an attached plan says why it runs nothing.
        expect(acceptedAgentCredentialTypes(ModelProvider.CLAUDE_CODE)).toContain(
            'agent_claude_code_oauth'
        );
        expect(acceptedAgentCredentialTypes(ModelProvider.ANTHROPIC)).toEqual([
            'agent_anthropic',
            'agent_claude_code',
        ]);
        const plan = { agent_claude_code_oauth: 'plan' };
        expect(getAgentCredentialIdForProvider(plan, ModelProvider.ANTHROPIC)).toBeUndefined();
        expect(claudePlanRefusal(plan, ModelProvider.ANTHROPIC)).toBe(CLAUDE_PLAN_REFUSAL);
        expect(claudePlanRefusal(plan, ModelProvider.CLAUDE_CODE)).toBeNull();
        expect(claudePlanRefusal(plan, ModelProvider.OPENROUTER)).toBeNull();
        expect(
            claudePlanRefusal({ ...plan, agent_anthropic: 'k' }, ModelProvider.ANTHROPIC)
        ).toBeNull();
    });

    describe('opencode wrapper credential routing', () => {
        // OpenCode is a multi-upstream wrapper: the user picks a sub-model
        // (opencode_model) that determines which provider's credential is
        // actually needed. The form has to follow the sub-model so users
        // reuse their existing Anthropic / OpenAI / OpenRouter credentials
        // for those sub-models, and only see OpenCode-specific fields for
        // opencode/* (Zen) sub-models.

        it('routes anthropic/* sub-models to the ANTHROPIC provider', () => {
            const config = {
                model: 'opencode',
                opencode_model: 'anthropic/claude-sonnet-4-5',
            };
            const effective = getAgentEffectiveModel(config.model, config);
            expect(effective).toBe('anthropic/claude-sonnet-4-5');
            expect(inferProviderFromPrefix(effective)).toBe(
                ModelProvider.ANTHROPIC
            );
        });

        it('keeps opencode/* sub-models on the OPENCODE provider', () => {
            const config = {
                model: 'opencode',
                opencode_model: 'opencode/mimo-v2-flash-free',
            };
            const effective = getAgentEffectiveModel(config.model, config);
            expect(effective).toBe('opencode/mimo-v2-flash-free');
            expect(inferProviderFromPrefix(effective)).toBe(
                ModelProvider.OPENCODE
            );
        });

        it('falls back to the wrapper DEFAULT sub-model when opencode_model is unset', () => {
            // An empty sub-model resolves to the wrapper's schema default (a
            // real, provider-prefixed id) rather than the bare wrapper id — the
            // bare id mislabeled the credential ("OpenCode API Key") and demanded
            // a nonexistent agent_opencode key. The default correctly infers the
            // OPENCODE provider (its own Zen key), matching what the backend runs.
            const config = { model: 'opencode' };
            const effective = getAgentEffectiveModel(config.model, config);
            expect(effective).toBe(WRAPPER_SUBMODEL_DEFAULT_BY_MODEL.opencode);
            expect(inferProviderFromPrefix(effective)).toBe(
                ModelProvider.OPENCODE
            );
        });

        it('routes openai/* and openrouter/* sub-models to their respective providers', () => {
            expect(inferProviderFromPrefix('openai/gpt-5')).toBe(
                ModelProvider.OPENAI
            );
            expect(
                inferProviderFromPrefix('openrouter/anthropic/claude-haiku-4-5')
            ).toBe(ModelProvider.OPENROUTER);
        });

        it('routes all twelve OpenCode picker prefixes to a known provider', () => {
            // Every sub-model the OpenCode picker can produce (priority +
            // free providers with operator credentials) must resolve.
            // If this regresses, the credential form shows "Provider
            // metadata not found" for one of the prefixes — which is what
            // was happening for github-models before this fix.
            expect(inferProviderFromPrefix('xai/grok-beta')).toBe(
                ModelProvider.XAI
            );
            expect(inferProviderFromPrefix('groq/llama-3.3-70b')).toBe(
                ModelProvider.GROQ
            );
            expect(inferProviderFromPrefix('deepseek/deepseek-chat')).toBe(
                ModelProvider.DEEPSEEK
            );
            expect(inferProviderFromPrefix('mistral/mistral-large')).toBe(
                ModelProvider.MISTRAL
            );
            expect(inferProviderFromPrefix('github-models/gpt-5')).toBe(
                ModelProvider.GITHUB_MODELS
            );
            expect(
                inferProviderFromPrefix('nvidia/nemotron-3-super-120b-a12b')
            ).toBe(ModelProvider.NVIDIA);
        });

        it('folds opencode-go/* into OPENCODE so the same Zen credential is reused', () => {
            // opencode and opencode-go share the same OPENCODE_API_KEY env
            // var and the same dashboard. A user who already added their
            // Zen key for opencode/* models shouldn't have to re-add it
            // for opencode-go/* models. The prefix collapse here is what
            // makes that work — both prefixes route to ModelProvider.OPENCODE,
            // and credentials are stored under `agent_opencode` either way.
            expect(inferProviderFromPrefix('opencode-go/anything')).toBe(
                ModelProvider.OPENCODE
            );
        });

        it('routes github-copilot/* to the GITHUB_COPILOT provider (OAuth-only)', () => {
            // github-copilot uses device-code OAuth (github.com/login/device);
            // models.dev ships `auth.env: []` for it. The credential form's
            // OAuth-path special-case mounts <GithubCopilotOAuth /> when
            // provider === GITHUB_COPILOT, so the field is OAuth-only — no
            // paste-API-key fallback. The provider entry still defines a
            // requiredApiKeys placeholder so non-OAuth gates downstream
            // (allNewRequiredFilled, etc.) don't trip.
            expect(inferProviderFromPrefix('github-copilot/gpt-4o')).toBe(
                ModelProvider.GITHUB_COPILOT
            );
        });
    });
});

// ── The model a send will actually run under ────────────────────────────────
// A conversation is bound to the model it started with, so a picker that has
// moved to another provider means the next send MINTS a fresh conversation and
// runs the pick. The pre-flight therefore validates the picked model — it used
// to validate the conversation's, and told a correctly-configured agent "the
// linked credential is for opencode, but this model routes through openrouter".
describe('validateAgentSendCredentials', () => {
    const config = {
        model: 'opencode',
        opencode_model: 'opencode/deepseek-v4-flash-free',
        openclaw_model: 'openrouter/~openai/gpt-mini-latest',
    };
    const resolveProvider = (m: string) =>
        m.startsWith('openrouter/')
            ? 'openrouter'
            : m.startsWith('opencode/')
              ? 'opencode'
              : null;

    it('passes when the credential matches the model that will run', () => {
        expect(
            validateAgentSendCredentials({
                sendModel: 'opencode',
                config,
                credentialIds: { agent_opencode: 'c1' },
                resolveProvider,
            })
        ).toBeNull();
    });

    it('names the provider actually needed when the credential is for another', () => {
        expect(
            validateAgentSendCredentials({
                sendModel: 'openclaw',
                config,
                credentialIds: { agent_opencode: 'c1' },
                resolveProvider,
            })
        ).toContain('this model routes through openrouter');
    });

    it('asks for one when nothing is linked and the harness is BYOK', () => {
        expect(
            validateAgentSendCredentials({
                sendModel: 'opencode',
                config,
                credentialIds: {},
                resolveProvider,
            })
        ).toContain('needs a opencode credential');
    });

    it('refuses a Claude plan on an anthropic/* sub-model, saying why', () => {
        expect(
            validateAgentSendCredentials({
                sendModel: 'opencode',
                config: { model: 'opencode', opencode_model: 'anthropic/claude-sonnet-4-5' },
                credentialIds: { agent_claude_code_oauth: 'plan' },
                resolveProvider: (m) => (m.startsWith('anthropic/') ? 'anthropic' : null),
            })
        ).toBe(CLAUDE_PLAN_REFUSAL);
    });
});
