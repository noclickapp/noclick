// @vitest-environment jsdom

/**
 * Tests for useAgentCredentialsRequired — the hook behind the agent config
 * panel's amber "Complete required fields" banner and FlowHelperView's
 * "credentials needed" state.
 *
 * Regression (reported 2026-07-25): opencode and hermes never complained about
 * a missing credential. The hook read `allowUsageBased` off the provider of the
 * RESOLVED sub-model — a wrapper's default sub-model is a plain `openrouter/…`
 * id, and openrouter is usage-based on the in-process LLM path — so the platform
 * looked willing to fund a harness that has no platform-key path at all. Every
 * such agent then died at run time on the backend's OPENROUTER_API_KEY gate with
 * no prior warning. The rule now comes from agentAllowsUsageBased, which judges
 * the top-level harness identity.
 */
import { describe, it, expect, vi } from 'vitest';
import { renderHook } from '@testing-library/react';

import { ModelProvider } from '~/types/provider';
import { WRAPPER_SUBMODEL_DEFAULT_BY_MODEL } from '~/lib/agentCredentialModel';

// Catalog miss for every id — the wrapper sub-models are models.dev-sourced and
// genuinely absent from the catalog, so the hook's inferProviderFromPrefix
// fallback is the path that actually runs in production.
vi.mock('~/hooks/useModels', () => ({
    useModels: () => ({ getModelById: () => undefined }),
}));

const { useAgentCredentialsRequired } = await import('~/hooks/useAgentCredentialsRequired');

const check = (
    model: string | undefined,
    config: Record<string, unknown> = {},
    credentialIds: Record<string, string> = {},
) =>
    renderHook(() => useAgentCredentialsRequired(model, credentialIds, config))
        .result.current;

describe('useAgentCredentialsRequired — CLI harnesses are always BYOK', () => {
    it('requires a credential for hermes on its default sub-model (the reported gap)', () => {
        const r = check('hermes', {});
        expect(r.provider).toBe(ModelProvider.OPENROUTER);
        expect(r.allowUsageBased).toBe(false);
        expect(r.credentialsRequired).toBe(true);
    });

    it('requires a credential for opencode on a usage-based sub-model', () => {
        // Picking anthropic/openai/openrouter inside opencode used to silently
        // inherit that provider's usage-based exemption.
        for (const sub of [
            'anthropic/claude-sonnet-4-5',
            'openai/gpt-5.4-mini',
            'openrouter/google/gemma-3-27b-it:free',
        ]) {
            const r = check('opencode', { opencode_model: sub });
            expect(r.allowUsageBased, sub).toBe(false);
            expect(r.credentialsRequired, sub).toBe(true);
        }
    });

    it('requires a credential for every wrapper harness on its schema default', () => {
        for (const harness of Object.keys(WRAPPER_SUBMODEL_DEFAULT_BY_MODEL)) {
            expect(check(harness, {}).credentialsRequired, harness).toBe(true);
        }
    });

    it('clears once the sub-model provider credential is linked', () => {
        expect(
            check('hermes', {}, { agent_openrouter: 'c1' }).credentialsRequired,
        ).toBe(false);
        expect(
            check(
                'opencode',
                { opencode_model: 'anthropic/claude-sonnet-4-5' },
                { agent_anthropic: 'c1' },
            ).credentialsRequired,
        ).toBe(false);
    });

    it('accepts a subscription-OAuth credential as satisfying the requirement', () => {
        // agent_claude_code_oauth aliases ANTHROPIC inside a wrapper (opencode
        // re-enables Anthropic OAuth via a vendored plugin).
        expect(
            check(
                'opencode',
                { opencode_model: 'anthropic/claude-sonnet-4-5' },
                { agent_claude_code_oauth: 'c1' },
            ).credentialsRequired,
        ).toBe(false);
    });

    it('still requires credentials for codex / claude-code (unchanged)', () => {
        expect(check('codex', {}).credentialsRequired).toBe(true);
        expect(check('claude-code', {}).credentialsRequired).toBe(true);
    });

    it('reads the harness off model_type when config.model is unset', () => {
        // Wrapper configs persisted before the model field was seeded carry only
        // the discriminator; the harness exemption must still apply.
        expect(
            check(undefined, { model_type: 'hermes_agent' }).credentialsRequired,
        ).toBe(true);
    });
});

describe('useAgentCredentialsRequired — in-process LLM path keeps usage-based billing', () => {
    it('exempts a bare openrouter model with no credential', () => {
        const r = check('openrouter/google/gemma-3-27b-it:free', {});
        expect(r.allowUsageBased).toBe(true);
        expect(r.credentialsRequired).toBe(false);
    });

    it('requires a credential for a non-usage-based provider', () => {
        expect(check('groq/llama-3.3-70b', {}).credentialsRequired).toBe(true);
    });

    it('requires a credential when the provider cannot be resolved at all', () => {
        const r = check('some-unprefixed-mystery-model', {});
        expect(r.provider).toBeNull();
        expect(r.credentialsRequired).toBe(true);
    });
});
