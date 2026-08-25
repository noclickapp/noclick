// Hook for managing saved outputs (mock data) for workflow nodes.
// Allows users to save, list, and select previously saved output data for testing.

import { useState, useEffect, useCallback, useRef } from 'react';
import { sendEventAsync } from '~/lib/socket-sender';
import type { SavedOutputInfo } from '~/types/socket-events.generated';
import { isPlanLimitError } from '~/lib/planLimitErrors';

interface UseSavedOutputsOptions {
    nodeType: string;
    autoFetch?: boolean; // Auto-fetch on mount (default: true)
}

interface UseSavedOutputsReturn {
    savedOutputs: SavedOutputInfo[];
    isLoading: boolean;
    error: string | null;
    planLimitError: string | null;
    clearPlanLimitError: () => void;
    fetch: () => Promise<void>;
    create: (name: string, output: unknown, visibility?: 'user' | 'organization' | 'public') => Promise<SavedOutputInfo | null>;
    update: (id: string, name?: string, visibility?: 'user' | 'organization' | 'public') => Promise<boolean>;
    remove: (id: string) => Promise<boolean>;
}

export function useSavedOutputs({ nodeType, autoFetch = true }: UseSavedOutputsOptions): UseSavedOutputsReturn {
    const [savedOutputs, setSavedOutputs] = useState<SavedOutputInfo[]>([]);
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [planLimitError, setPlanLimitError] = useState<string | null>(null);
    const clearPlanLimitError = useCallback(() => setPlanLimitError(null), []);
    const hasFetchedRef = useRef(false);

    // Fetch saved outputs for the node type
    const fetch = useCallback(async () => {
        if (!nodeType) return;

        setIsLoading(true);
        setError(null);

        try {
            const response = await sendEventAsync({
                event_name: 'saved_output:list',
                request_id: `saved-output-list-${Date.now()}`,
                node_type: nodeType,
            });

            if (response?.saved_outputs) {
                setSavedOutputs(response.saved_outputs);
            }
        } catch (err) {
            const errorMsg = err instanceof Error ? err.message : 'Failed to fetch saved outputs';
            console.error('[useSavedOutputs] Fetch error:', errorMsg);
            setError(errorMsg);
        } finally {
            setIsLoading(false);
        }
    }, [nodeType]);

    // Auto-fetch on mount if enabled
    useEffect(() => {
        if (autoFetch && nodeType && !hasFetchedRef.current) {
            hasFetchedRef.current = true;
            fetch();
        }
    }, [autoFetch, nodeType, fetch]);

    // Reset when node type changes
    useEffect(() => {
        hasFetchedRef.current = false;
        setSavedOutputs([]);
        setError(null);
    }, [nodeType]);

    // Create a new saved output
    const create = useCallback(async (
        name: string,
        output: unknown,
        visibility: 'user' | 'organization' | 'public' = 'user'
    ): Promise<SavedOutputInfo | null> => {
        if (!nodeType) return null;

        try {
            const response = await sendEventAsync({
                event_name: 'saved_output:create',
                request_id: `saved-output-create-${Date.now()}`,
                node_type: nodeType,
                name,
                output: output as Record<string, unknown>,
                visibility,
            });

            if (response?.success && response.saved_output) {
                // Add to local state
                setSavedOutputs(prev => [response.saved_output!, ...prev]);
                return response.saved_output;
            } else {
                const errMsg = response?.error || response?.message || 'Failed to create saved output';
                if (isPlanLimitError(errMsg)) {
                    setPlanLimitError(errMsg);
                } else {
                    setError(errMsg);
                }
            }
            return null;
        } catch (err) {
            const errorMsg = err instanceof Error ? err.message : 'Failed to create saved output';
            console.error('[useSavedOutputs] Create error:', errorMsg);
            if (isPlanLimitError(errorMsg)) {
                setPlanLimitError(errorMsg);
            } else {
                setError(errorMsg);
            }
            return null;
        }
    }, [nodeType]);

    // Update a saved output
    const update = useCallback(async (
        id: string,
        name?: string,
        visibility?: 'user' | 'organization' | 'public'
    ): Promise<boolean> => {
        try {
            const response = await sendEventAsync({
                event_name: 'saved_output:update',
                request_id: `saved-output-update-${Date.now()}`,
                saved_output_id: id,
                name,
                visibility,
            });

            if (response?.success && response.saved_output) {
                // Update in local state
                setSavedOutputs(prev =>
                    prev.map(so => so.id === id ? response.saved_output! : so)
                );
                return true;
            } else if (!response?.success && response?.message) {
                setError(response.message);
            }
            return false;
        } catch (err) {
            const errorMsg = err instanceof Error ? err.message : 'Failed to update saved output';
            console.error('[useSavedOutputs] Update error:', errorMsg);
            setError(errorMsg);
            return false;
        }
    }, []);

    // Delete a saved output
    const remove = useCallback(async (id: string): Promise<boolean> => {
        try {
            const response = await sendEventAsync({
                event_name: 'saved_output:delete',
                request_id: `saved-output-delete-${Date.now()}`,
                saved_output_id: id,
            });

            if (response?.success) {
                // Remove from local state
                setSavedOutputs(prev => prev.filter(so => so.id !== id));
                return true;
            } else if (!response?.success && response?.message) {
                setError(response.message);
            }
            return false;
        } catch (err) {
            const errorMsg = err instanceof Error ? err.message : 'Failed to delete saved output';
            console.error('[useSavedOutputs] Delete error:', errorMsg);
            setError(errorMsg);
            return false;
        }
    }, []);

    return {
        savedOutputs,
        isLoading,
        error,
        planLimitError,
        clearPlanLimitError,
        fetch,
        create,
        update,
        remove,
    };
}
