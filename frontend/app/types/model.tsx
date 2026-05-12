// Unified model type for all AI models across different providers
// Provides a consistent interface for OpenRouter, built-in, and future model sources

import { ModelProvider, ProviderMetadata, getProviderMetadata, getProviderColors, PROVIDER_METADATA } from './provider';

// Re-export provider types and utilities for backwards compatibility
export { ModelProvider, getProviderMetadata, getProviderColors, PROVIDER_METADATA };
export type { ProviderMetadata };

export interface Model {
    /** Unique identifier for the model */
    id: string;

    /** Provider name (e.g., 'openrouter', 'openai', 'anthropic', 'google') */
    provider: ModelProvider;

    /** Human-readable description of the model's capabilities */
    description?: string;

    /** Input modalities supported by the model */
    input_modalities: string[];

    /** Output modalities supported by the model */
    output_modalities: string[];

    /** Unix epoch (seconds) when the model was first published. Only set by
     *  the OpenRouter source; LiteLLM / static entries omit it. Used by the
     *  node picker to weight recency when matching free-form model queries. */
    created?: number;

    /** Capability flags for UI display */
    capabilities?: {
        /** Model can analyze images (has "image" in input_modalities) */
        imageAnalysis?: boolean;

        /** Model can generate images (has "image" in output_modalities) */
        imageGeneration?: boolean;

        /** Model supports reasoning/thinking (has "include_reasoning" in supported_parameters) */
        reasoning?: boolean;

        /** Model supports tool/function calling (has "tools" in supported_parameters) */
        tools?: boolean;

        /** Model can generate videos (has "video" in output_modalities or matches known video gen model patterns) */
        videoGeneration?: boolean;
    };
}