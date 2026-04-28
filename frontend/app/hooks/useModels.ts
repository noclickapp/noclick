// Hook for fetching the unified model catalog from /api/models.
// Single source of truth: backend serves OpenRouter + LiteLLM + static
// stragglers in one list, this hook caches it (10-min TTL) and exposes the
// same surface the rest of the app already consumed.

import { useState, useEffect, useCallback } from 'react';
import { Model } from '~/types/model';
import { ModelProvider } from '~/types/provider';

// Backwards-compatible alias — every Model now carries a `source` field
// served straight from the backend, so we no longer need to compose it.
export type ModelWithSource = Model & { source: 'openrouter' | 'litellm' | 'static' };

interface ApiModelsResponse {
    models: ModelWithSource[];
    count: number;
}

interface CachedData {
    models: ModelWithSource[];
    timestamp: number;
}

const CACHE_KEY = 'model-catalog';
const CACHE_TTL = 10 * 60 * 1000; // 10 minutes — matches backend cache TTL.

function backendUrl(): string {
    return import.meta.env.VITE_API_URL || '';
}

function isModelProvider(value: string): value is ModelProvider {
    return Object.values(ModelProvider).includes(value as ModelProvider);
}

function coerceProvider(raw: string): ModelProvider {
    // Backend already normalizes most LiteLLM provider sub-strings; the
    // remaining stragglers fall through to OPENROUTER as a safe default
    // (the consumer treats unknown providers as "other"). Coercion stays
    // here rather than at the API boundary so future enum additions don't
    // require a backend deploy.
    return isModelProvider(raw) ? raw : ModelProvider.OPENROUTER;
}

function normalizeModel(raw: ModelWithSource): ModelWithSource {
    return {
        ...raw,
        provider: coerceProvider(raw.provider as unknown as string),
    };
}

export interface UseModelsResult {
    /** All models from all sources combined with source information */
    models: ModelWithSource[];

    /** Loading state */
    isLoading: boolean;

    /** Error from the fetch, or null */
    error: string | null;

    /** Refresh (force fetch from API) */
    refreshAll: () => Promise<void>;

    /** Get model by ID */
    getModelById: (id: string) => ModelWithSource | undefined;

    /** Search models across all sources */
    searchModels: (query: string) => ModelWithSource[];

    /** Get models by provider */
    getModelsByProvider: (provider: string) => ModelWithSource[];

    /** Get models by input modality */
    getModelsByInputModality: (modality: string) => ModelWithSource[];

    /** Get models by output modality */
    getModelsByOutputModality: (modality: string) => ModelWithSource[];
}

export function useModels(): UseModelsResult {
    const [models, setModels] = useState<ModelWithSource[]>([]);
    const [isLoading, setIsLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const isCacheValid = useCallback((cachedData: CachedData): boolean => {
        return (Date.now() - cachedData.timestamp) < CACHE_TTL;
    }, []);

    const loadModels = useCallback(async (force: boolean = false) => {
        try {
            if (!force) {
                const cached = localStorage.getItem(CACHE_KEY);
                if (cached) {
                    const cachedData: CachedData = JSON.parse(cached);
                    if (isCacheValid(cachedData)) {
                        setModels(cachedData.models);
                        setIsLoading(false);
                        return;
                    }
                }
            }

            setIsLoading(true);
            setError(null);

            const response = await fetch(`${backendUrl()}/api/models`);
            if (!response.ok) {
                throw new Error(`Failed to fetch models: ${response.status} ${response.statusText}`);
            }
            const data: ApiModelsResponse = await response.json();
            const fetched = (data.models || []).map(normalizeModel);

            const cacheData: CachedData = { models: fetched, timestamp: Date.now() };
            try {
                localStorage.setItem(CACHE_KEY, JSON.stringify(cacheData));
            } catch (cacheErr) {
                // QuotaExceededError or similar — non-fatal, the in-memory
                // copy still works for this session.
                console.warn('Failed to cache model catalog:', cacheErr);
            }

            setModels(fetched);
            setError(null);
        } catch (err) {
            const errorMessage = err instanceof Error ? err.message : 'Unknown error occurred';
            setError(errorMessage);
            console.error('Failed to load model catalog:', err);

            // Stale-cache fallback so the UI doesn't go blank during a
            // transient network failure.
            const cached = localStorage.getItem(CACHE_KEY);
            if (cached) {
                try {
                    const cachedData: CachedData = JSON.parse(cached);
                    setModels(cachedData.models);
                } catch {
                    setModels([]);
                }
            } else {
                setModels([]);
            }
        } finally {
            setIsLoading(false);
        }
    }, [isCacheValid]);

    const refreshAll = useCallback(async () => {
        localStorage.removeItem(CACHE_KEY);
        await loadModels(true);
    }, [loadModels]);

    useEffect(() => {
        loadModels();
    }, [loadModels]);

    const getModelById = useCallback((id: string): ModelWithSource | undefined => {
        return models.find(m => m.id === id);
    }, [models]);

    const searchModels = useCallback((query: string): ModelWithSource[] => {
        if (!query.trim()) return models;
        const lowerQuery = query.toLowerCase();
        return models.filter(m =>
            m.id.toLowerCase().includes(lowerQuery) ||
            (m.description && m.description.toLowerCase().includes(lowerQuery)) ||
            m.provider.toLowerCase().includes(lowerQuery)
        );
    }, [models]);

    const getModelsByProvider = useCallback((provider: string): ModelWithSource[] => {
        return models.filter(m => m.provider === provider);
    }, [models]);

    const getModelsByInputModality = useCallback((modality: string): ModelWithSource[] => {
        return models.filter(m => m.input_modalities.includes(modality));
    }, [models]);

    const getModelsByOutputModality = useCallback((modality: string): ModelWithSource[] => {
        return models.filter(m => m.output_modalities.includes(modality));
    }, [models]);

    return {
        models,
        isLoading,
        error,
        refreshAll,
        getModelById,
        searchModels,
        getModelsByProvider,
        getModelsByInputModality,
        getModelsByOutputModality,
    };
}
