// Share the safely initialized analytics client without eager SDK imports.
// Reactive flag consumers subscribe here so login token URLs can be excluded
// before dashboard components load either analytics SDK module.
import { createContext, useContext, useEffect, useState } from 'react';
import type { PostHog } from 'posthog-js';

// Shared lightweight context: importing dashboard/flag consumers must not load
// the SDK before PHProvider has checked the callback URL.
export const AnalyticsClient = createContext<PostHog | undefined>(undefined);
export const useAnalyticsClient = () => useContext(AnalyticsClient);

export function useAnalyticsFeatureFlagEnabled(flag: string): boolean | undefined {
    const client = useAnalyticsClient();
    const [enabled, setEnabled] = useState<boolean | undefined>();
    useEffect(() => {
        setEnabled(client?.isFeatureEnabled(flag));
        return client?.onFeatureFlags(() => setEnabled(client.isFeatureEnabled(flag)));
    }, [client, flag]);
    return client ? enabled : undefined;
}

export function useAnalyticsActiveFeatureFlags(): string[] | undefined {
    const client = useAnalyticsClient();
    const [flags, setFlags] = useState<string[] | undefined>();
    useEffect(() => {
        setFlags(client?.featureFlags.getFlags());
        return client?.onFeatureFlags((active) => setFlags(active));
    }, [client]);
    return client ? flags : undefined;
}
