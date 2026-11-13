/**
 * Onboarding completion state (seen_once flags), fetched
 * once at the Dashboard level and shared via context. Backed by the
 * user_onboarding_completion table for cross-device persistence, mirrored to
 * localStorage for synchronous flash-free reads on page load. Consumed by
 * useSeenOnce (coachmarks and announcements). The Get Started checklist UI this once powered was removed
 * 2026-08 — the canvas corner it occupied now hosts the Crisp chat widget.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { sendEventAsync } from '~/lib/socket-sender';
import {
    OnboardingCompletionGetRequest,
    OnboardingCompletionUpdateRequest,
} from '~/types/socket-events.generated';

// localStorage key for caching onboarding completion state
const ONBOARDING_CACHE_KEY = 'noclick:onboarding_completion';

export interface OnboardingCompletionData {
    // Generic per-user "show this once" flags (coachmarks, announcements),
    // keyed by a SeenOnceKey. Missing key reads as false. See useSeenOnce.
    seen_once?: Partial<Record<string, boolean>>;
}

const defaultCompletionData: OnboardingCompletionData = {};

function cacheToLocalStorage(data: OnboardingCompletionData): void {
    if (typeof window === 'undefined') return;
    try {
        localStorage.setItem(ONBOARDING_CACHE_KEY, JSON.stringify(data));
    } catch {
        // Ignore storage errors (quota exceeded, etc.)
    }
}

function getInitialCompletionData(): OnboardingCompletionData {
    if (typeof window === 'undefined') return defaultCompletionData;
    try {
        const cached = localStorage.getItem(ONBOARDING_CACHE_KEY);
        if (cached) {
            return JSON.parse(cached);
        }
    } catch {
        // Ignore parse errors
    }
    return defaultCompletionData;
}

interface OnboardingContextValue {
    completionData: OnboardingCompletionData;
    setCompletionData: React.Dispatch<React.SetStateAction<OnboardingCompletionData>>;
    isLoading: boolean;
    hasLoaded: boolean;
    updateBackend: (updates: Partial<OnboardingCompletionData>) => Promise<void>;
}

const OnboardingContext = createContext<OnboardingContextValue | null>(null);

/**
 * Provider that fetches onboarding completion data once and shares it via context.
 * Mount at the Dashboard level so all consumers share a single fetch.
 */
export function OnboardingProvider({ children }: { children: ReactNode }) {
    const [completionData, setCompletionData] = useState<OnboardingCompletionData>(getInitialCompletionData);
    const [isLoading, setIsLoading] = useState(true);
    const [hasLoaded, setHasLoaded] = useState(false);

    // Fetch completion data from backend once on mount.
    // Relies on sendEventAsync's default 30s timeout. localStorage cache provides instant UI while this resolves.
    useEffect(() => {
        const fetchCompletionData = async () => {
            try {
                const response = await sendEventAsync(
                    OnboardingCompletionGetRequest.create({ request_id: crypto.randomUUID() }),
                ) as { completion?: OnboardingCompletionData; error?: string };

                if (response.completion) {
                    setCompletionData(response.completion);
                } else {
                    // No data from backend (new user) - reset to defaults and clear stale cache
                    setCompletionData(defaultCompletionData);
                    localStorage.removeItem(ONBOARDING_CACHE_KEY);
                }
            } catch (error) {
                console.error('[OnboardingProvider] Failed to fetch completion data:', error);
                // On error, keep existing state from localStorage cache: resetting
                // to defaults would re-show every coachmark already seen.
            } finally {
                setIsLoading(false);
                setHasLoaded(true);
            }
        };

        fetchCompletionData();
    }, []);

    // Cache completion data to localStorage whenever it changes (after backend load)
    useEffect(() => {
        if (hasLoaded) {
            cacheToLocalStorage(completionData);
        }
    }, [completionData, hasLoaded]);

    // Helper to update backend (fire-and-forget with optimistic local update)
    const updateBackend = useCallback(async (updates: Partial<OnboardingCompletionData>) => {
        try {
            await sendEventAsync(
                OnboardingCompletionUpdateRequest.create({
                    request_id: crypto.randomUUID(),
                    data: updates,
                }),
            );
        } catch (error) {
            console.error('[OnboardingProvider] Failed to update completion data:', error);
        }
    }, []);

    const value = useMemo<OnboardingContextValue>(() => ({
        completionData,
        setCompletionData,
        isLoading,
        hasLoaded,
        updateBackend,
    }), [completionData, isLoading, hasLoaded, updateBackend]);

    return (
        <OnboardingContext.Provider value={value}>
            {children}
        </OnboardingContext.Provider>
    );
}

export function useOnboardingContext(): OnboardingContextValue {
    const ctx = useContext(OnboardingContext);
    if (!ctx) {
        throw new Error('useOnboardingContext must be used within an OnboardingProvider');
    }
    return ctx;
}
