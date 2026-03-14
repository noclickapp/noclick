// Unified hook that combines OpenRouter and LiteLLM models
// Provides a single interface for accessing all available AI models

import { useCallback, useMemo } from 'react';
import { Model } from '~/types/model';
import { useOpenRouterModels } from './useOpenRouterModels';
import { useLiteLLMModels } from './useLiteLLMModels';

// Extended model interface that includes source information
export interface ModelWithSource extends Model {
    source: 'openrouter' | 'litellm';
}

export interface UseModelsResult {
    /** All models from all sources combined with source information */
    models: ModelWithSource[];
    
    /** Loading state - true if any source is still loading */
    isLoading: boolean;
    
    /** Error from any source (prioritizes OpenRouter errors) */
    error: string | null;
    
    /** Refresh all model sources */
    refreshAll: () => Promise<void>;
    
    /** Get model by ID from any source */
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
    // Get data from individual hooks
    const openRouter = useOpenRouterModels();
    const liteLLM = useLiteLLMModels();

    // Combine all models with source information
    const models = useMemo(() => {
        // Create a map of OpenRouter model IDs (without prefix) to their capabilities
        const openRouterCapabilities = new Map<string, Model['capabilities']>();
        openRouter.models.forEach(model => {
            // Remove "openrouter/" prefix to get the actual model ID
            const actualId = model.id.replace(/^openrouter\//, '');
            if (model.capabilities) {
                openRouterCapabilities.set(actualId, model.capabilities);
            }
        });

        const openRouterWithSource: ModelWithSource[] = openRouter.models.map(model => ({
            ...model,
            source: 'openrouter' as const
        }));

        // Enrich LiteLLM models with capabilities from OpenRouter if they match
        const liteLLMWithSource: ModelWithSource[] = liteLLM.models.map(model => {
            // Check if this LiteLLM model exists in OpenRouter
            const matchingCapabilities = openRouterCapabilities.get(model.id);
            return {
                ...model,
                source: 'litellm' as const,
                // Merge OpenRouter capabilities with LiteLLM's, so fields from both sources are preserved
                capabilities: matchingCapabilities
                    ? { ...model.capabilities, ...matchingCapabilities }
                    : model.capabilities,
            };
        });

        return [...openRouterWithSource, ...liteLLMWithSource];
    }, [openRouter.models, liteLLM.models]);

    // Combined loading state
    const isLoading = openRouter.isLoading || liteLLM.isLoading;

    // Prioritize OpenRouter errors, fallback to LiteLLM errors
    const error = openRouter.error || liteLLM.error;

    // Refresh all sources
    const refreshAll = useCallback(async () => {
        await Promise.all([
            openRouter.refreshModels(),
            liteLLM.refreshModels()
        ]);
    }, [openRouter.refreshModels, liteLLM.refreshModels]);

    // Get model by ID from any source
    const getModelById = useCallback((id: string): ModelWithSource | undefined => {
        return models.find(model => model.id === id);
    }, [models]);

    // Search models across all sources
    const searchModels = useCallback((query: string): ModelWithSource[] => {
        if (!query.trim()) return models;
        
        const lowerQuery = query.toLowerCase();
        return models.filter(model => 
            model.id.toLowerCase().includes(lowerQuery) ||
            (model.description && model.description.toLowerCase().includes(lowerQuery)) ||
            model.provider.toLowerCase().includes(lowerQuery)
        );
    }, [models]);

    // Get models by provider
    const getModelsByProvider = useCallback((provider: string): ModelWithSource[] => {
        return models.filter(model => model.provider === provider);
    }, [models]);

    // Get models by input modality
    const getModelsByInputModality = useCallback((modality: string): ModelWithSource[] => {
        return models.filter(model => 
            model.input_modalities.includes(modality)
        );
    }, [models]);

    // Get models by output modality
    const getModelsByOutputModality = useCallback((modality: string): ModelWithSource[] => {
        return models.filter(model => 
            model.output_modalities.includes(modality)
        );
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
        getModelsByOutputModality
    };
}