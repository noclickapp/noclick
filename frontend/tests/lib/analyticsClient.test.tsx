// @vitest-environment jsdom
// Check reactive flags when the safely initialized client arrives or disappears.
// This protects credential previews/debug controls after removing their eager
// SDK imports from the dashboard's callback-sensitive component tree.

import { act, renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { PostHog } from 'posthog-js';
import { AnalyticsClient, useAnalyticsActiveFeatureFlags, useAnalyticsFeatureFlagEnabled } from '~/lib/analyticsClient';
import type { ReactNode } from 'react';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

describe('lightweight reactive analytics client', () => {
    it('keeps dashboard consumers free of eager SDK imports', () => {
        for (const path of ['app/routes/dashboard.tsx', 'app/components/workflow/NodeCredentials.tsx', 'app/hooks/useDebugToolsEnabled.ts']) {
            const source = readFileSync(resolve(path), 'utf8');
            expect(source).not.toMatch(/import\s+(?!type\b)[^;]*from\s+['"]posthog-js(?:\/react)?['"]/);
        }
    });

    it('reacts to late client initialization, flag changes and private route client removal', () => {
        let enabled = false;
        let flags: string[] = [];
        const listeners = new Set<(flags: string[]) => void>();
        const unsubscribe = vi.fn();
        const client = { isFeatureEnabled: () => enabled, featureFlags: { getFlags: () => flags },
            onFeatureFlags: (listener: (flags: string[]) => void) => {
                listeners.add(listener);
                return () => { listeners.delete(listener); unsubscribe(); };
            },
        } as unknown as PostHog;
        let active: PostHog | undefined;
        const wrapper = ({ children }: { children: ReactNode }) => <AnalyticsClient.Provider value={active}>{children}</AnalyticsClient.Provider>;
        const hook = renderHook(() => ({ enabled: useAnalyticsFeatureFlagEnabled('debug'), flags: useAnalyticsActiveFeatureFlags() }), { wrapper });
        expect(hook.result.current).toEqual({ enabled: undefined, flags: undefined });
        active = client;
        hook.rerender();
        expect(hook.result.current).toEqual({ enabled: false, flags: [] });
        act(() => { enabled = true; flags = ['debug', 'preview']; listeners.forEach((listener) => listener(flags)); });
        expect(hook.result.current).toEqual({ enabled: true, flags: ['debug', 'preview'] });
        act(() => { enabled = false; flags = []; listeners.forEach((listener) => listener(flags)); });
        expect(hook.result.current).toEqual({ enabled: false, flags: [] });
        active = undefined;
        hook.rerender();
        expect(hook.result.current).toEqual({ enabled: undefined, flags: undefined });
        expect(listeners.size).toBe(0);
        expect(unsubscribe).toHaveBeenCalledTimes(2);
        hook.unmount();
    });
});
