import { useCallback } from 'react';

export function isFeatureEnabled(_key: string): boolean {
    return false;
}

export function useAnalytics() {
    const logActivity = useCallback(
        (_eventName: string, _metadata?: Record<string, unknown>) => undefined,
        []
    );
    return { logActivity };
}
