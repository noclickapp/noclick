// Hook for managing API keys for different AI model providers
// Stores keys in IndexedDB via cached valtio state for persistence and cloud sync

import { useCallback } from 'react';
import { ModelProvider, getProviderMetadata } from '~/types/provider';
import { useCachedValtioState } from '~/hooks/useCachedValtioState';

interface APIKeys {
    [key: string]: string; // Dynamic keys for all providers
}

export function useAPIKeys() {
    // Store API keys in cached valtio state (IndexedDB + cloud sync)
    // Using 'settings' as the valtio path for user-specific configurations
    const [keys, setKeys] = useCachedValtioState<APIKeys>(
        'settings',
        'apiKeys',
        {} // Initial value is empty object
    );
    
    // Save a key for a specific provider
    const saveKey = useCallback((provider: ModelProvider, key: string) => {
        const providerKey = String(provider); // Convert enum to string
        setKeys(prev => ({ ...prev, [providerKey]: key }));
    }, [setKeys]);
    
    // Remove a key for a specific provider
    const removeKey = useCallback((provider: ModelProvider) => {
        const providerKey = String(provider); // Convert enum to string
        setKeys(prev => {
            const updated = { ...prev };
            delete updated[providerKey];
            return updated;
        });
    }, [setKeys]);
    
    // Check if a key exists for a provider
    const hasKey = useCallback((provider: ModelProvider): boolean => {
        const providerKey = String(provider); // Convert enum to string
        return Boolean(keys[providerKey]);
    }, [keys]);
    
    // Get a key for a provider
    const getKey = useCallback((provider: ModelProvider): string | undefined => {
        const providerKey = String(provider); // Convert enum to string
        return keys[providerKey];
    }, [keys]);
    
    // Check if we have all required API keys for a ModelProvider (handles OR conditions)
    const hasRequiredKeys = useCallback((provider: ModelProvider): boolean => {
        const metadata = getProviderMetadata(provider);
        if (!metadata?.requiredApiKeys || metadata.requiredApiKeys.length === 0) {
            return true; // No API keys required
        }
        
        // Check if we have at least one complete set of API keys (OR condition)
        return metadata.requiredApiKeys.some(keySet => 
            keySet.every(keyName => {
                return Boolean(keys[keyName]);
            })
        );
    }, [keys]);
    
    // Save multiple keys at once (useful for providers with multiple required keys)
    const saveKeys = useCallback((keyValuePairs: Record<string, string>) => {
        setKeys(prev => ({ ...prev, ...keyValuePairs }));
    }, [setKeys]);
    
    // Get all relevant API keys for a provider (returns object with all keys needed)
    const getAllKeysForProvider = useCallback((provider: ModelProvider): Record<string, string> | undefined => {
        const metadata = getProviderMetadata(provider);
        const result: Record<string, string> = {};
        
        if (!metadata?.requiredApiKeys || metadata.requiredApiKeys.length === 0) {
            return undefined; // No API keys required
        }
        
        // Find the first complete set of API keys (OR condition)
        for (const keySet of metadata.requiredApiKeys) {
            const keysForSet: Record<string, string> = {};
            let hasAllKeys = true;
            
            for (const keyName of keySet) {
                if (keys[keyName]) {
                    keysForSet[keyName] = keys[keyName];
                } else {
                    hasAllKeys = false;
                    break;
                }
            }
            
            if (hasAllKeys) {
                // Found a complete set, return it
                return keysForSet;
            }
        }
        
        // No complete set found, return what we have (partial)
        for (const keySet of metadata.requiredApiKeys) {
            for (const keyName of keySet) {
                if (keys[keyName]) {
                    result[keyName] = keys[keyName];
                }
            }
        }
        
        return Object.keys(result).length > 0 ? result : undefined;
    }, [keys]);
    
    return {
        keys,
        isLoaded: true, // Always loaded since useCachedValtioState handles initialization
        saveKey,
        saveKeys,
        removeKey,
        hasKey,
        getKey,
        hasRequiredKeys,
        getAllKeysForProvider
    };
}
