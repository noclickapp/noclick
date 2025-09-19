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
}