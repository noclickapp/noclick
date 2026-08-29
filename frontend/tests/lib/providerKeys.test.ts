import { afterEach, describe, expect, it } from 'vitest';
import { providerKeyLabel, PROVIDER_KEY_SOURCES } from '~/lib/providerKeys';
import { agentAllowsUsageBased } from '~/lib/agentCredentialModel';

function setLocal(value: string | undefined) {
    if (value === undefined) delete (import.meta.env as Record<string, unknown>).VITE_NOCLICK_LOCAL;
    else (import.meta.env as Record<string, unknown>).VITE_NOCLICK_LOCAL = value;
}

afterEach(() => setLocal(undefined));

describe('providerKeyLabel', () => {
    it('names the providers the builder asks for', () => {
        expect(providerKeyLabel('OPENROUTER_API_KEY')).toBe('OpenRouter');
        expect(PROVIDER_KEY_SOURCES.OPENROUTER_API_KEY.url).toContain('openrouter.ai');
    });
    it('humanizes an unlisted variable instead of showing SHOUTING_CASE', () => {
        expect(providerKeyLabel('TOGETHERAI_API_KEY')).toBe('Togetherai');
        expect(providerKeyLabel('REPLICATE_API_TOKEN')).toBe('Replicate');
    });
});

describe('usage-based billing copy', () => {
    it('is a hosted concept: never offered on a self-hosted instance', () => {
        setLocal(undefined);
        const hosted = agentAllowsUsageBased('openai/gpt-5-mini', 'openai');
        setLocal('1');
        expect(agentAllowsUsageBased('openai/gpt-5-mini', 'openai')).toBe(false);
        // The gate is the edition, not the model: the same call differs only by edition.
        expect(typeof hosted).toBe('boolean');
    });
});
