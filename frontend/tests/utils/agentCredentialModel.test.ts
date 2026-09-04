import { describe, expect, it } from 'vitest';
import { ModelProvider } from '~/types/provider';
import {
    conversationNeedsFreshThread,
    getAgentConfigRecord,
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
});

describe('conversationNeedsFreshThread', () => {
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

    it('is true when the chat runs a different provider than the picker', () => {
        expect(
            conversationNeedsFreshThread({
                sendModel: 'openclaw',
                selectedModel: 'opencode',
                config,
                resolveProvider,
            })
        ).toBe(true);
    });

    it('is false when they agree', () => {
        expect(
            conversationNeedsFreshThread({
                sendModel: 'opencode',
                selectedModel: 'opencode',
                config,
                resolveProvider,
            })
        ).toBe(false);
    });

    it('is false for a different MODEL on the same provider and harness', () => {
        // Both route through the in-process LLM agent and the same credential,
        // so the thread continues — minting here would throw away history for
        // nothing.
        expect(
            conversationNeedsFreshThread({
                sendModel: 'openrouter/anthropic/claude-3.5',
                selectedModel: 'openrouter/openai/gpt-4o',
                config,
                resolveProvider,
            })
        ).toBe(false);
    });

    it('is true across harnesses even on the same provider', () => {
        // openclaw runs its sub-model through openrouter, so the PROVIDER
        // matches — but its sandbox state is disjoint from the in-process LLM
        // agent's, so the thread cannot continue. Provider alone was the old
        // test for this and it missed exactly this case.
        expect(
            conversationNeedsFreshThread({
                sendModel: 'openrouter/~openai/gpt-mini-latest',
                selectedModel: 'openclaw',
                config,
                resolveProvider,
            })
        ).toBe(true);
    });
});
