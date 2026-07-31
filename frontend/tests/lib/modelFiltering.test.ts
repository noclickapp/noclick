/**
 * Tests for filterAndSortModels' free-model surfacing in the model picker:
 * $0-priced models (OpenRouter :free routes, OpenCode Zen free tier) float
 * above paid ones — below any priority pins — only on surfaces that opt in
 * via `freeFirst` (the agent model popup; the demo chat keeps native order),
 * and every free model answers to a "free" search even when its id doesn't
 * carry the word.
 */
import { describe, it, expect } from 'vitest';

import { filterAndSortModels } from '~/lib/modelFiltering';
import type { Model } from '~/types/model';
import { ModelProvider } from '~/types/provider';

function model(id: string, free = false): Model {
    return {
        id,
        provider: ModelProvider.OPENROUTER,
        input_modalities: ['text'],
        output_modalities: ['text'],
        free,
    };
}

const MODELS = [
    model('openrouter/openai/gpt-5.5'),
    model('openrouter/meta-llama/llama-4:free', true),
    model('claude-code'),
    model('opencode/glm-4.7-free', true),
    model('openrouter/anthropic/claude-opus-4.7'),
];

const BASE_OPTS = {
    searchQuery: '',
    selectedProviders: new Set<ModelProvider>(),
    selectedFeatures: new Set<string>(),
    viewMode: 'all' as const,
    userFavorites: [],
};

describe('freeFirst banding', () => {
    it('floats free models above paid ones, below priority pins, stable within bands', () => {
        const ids = filterAndSortModels(MODELS, {
            ...BASE_OPTS,
            priorityModelIds: ['claude-code'],
            freeFirst: true,
        }).map((m) => m.id);
        expect(ids).toEqual([
            'claude-code',
            'openrouter/meta-llama/llama-4:free',
            'opencode/glm-4.7-free',
            'openrouter/openai/gpt-5.5',
            'openrouter/anthropic/claude-opus-4.7',
        ]);
    });

    it('keeps native ordering when freeFirst is not requested', () => {
        const ids = filterAndSortModels(MODELS, BASE_OPTS).map((m) => m.id);
        expect(ids).toEqual(MODELS.map((m) => m.id));
    });
});

describe('"free" search term', () => {
    it('matches every free model, including ids without the word', () => {
        const zenFree = model('opencode/glm-5-mini', true); // id carries no "free"
        const ids = filterAndSortModels([...MODELS, zenFree], {
            ...BASE_OPTS,
            searchQuery: 'free',
        }).map((m) => m.id);
        expect(ids).toContain('opencode/glm-5-mini');
        expect(ids).toContain('openrouter/meta-llama/llama-4:free');
        expect(ids).not.toContain('openrouter/openai/gpt-5.5');
    });
});
