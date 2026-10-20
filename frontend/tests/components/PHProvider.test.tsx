// @vitest-environment jsdom
// PostHog (NoClick's product analytics and session replay) starts on NoClick's own pages, and never on a human
// request's page: its visitors are a customer's users, often on the customer's own brand host.
import { cleanup, render, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';

const posthog = vi.hoisted(() => ({ init: vi.fn() }));
vi.mock('posthog-js', () => ({ default: posthog }));
vi.mock('posthog-js/react', () => ({ PostHogProvider: ({ children }: { children: unknown }) => children }));
// jsdom's localhost is skipped as dev traffic; these pages are on a real host.
vi.mock('~/lib/loopback', () => ({ isLoopbackHostname: () => false }));
vi.mock('~/lib/socket-receiver', () => ({ socketReceiver: { sendAuthUpdate: () => undefined } }));

import { PHProvider } from '~/provider';

afterEach(() => {
    cleanup();
    posthog.init.mockReset();
    delete (window as { posthog?: unknown }).posthog;
    window.history.pushState({}, '', '/');
});

const open = (path: string) => {
    window.history.pushState({}, '', path);
    render(<PHProvider>page</PHProvider>);
};

it("starts on NoClick's own pages", async () => {
    open('/pricing');
    await waitFor(() => expect(posthog.init).toHaveBeenCalledTimes(1));
});

it.each(['/h/0f1e2d3c-4b5a-4978-8a6b-5c4d3e2f1a0b', '/h/0f1e2d3c-4b5a-4978-8a6b-5c4d3e2f1a0b.data'])(
    "never starts on a human request's page (%s)",
    async (path) => {
        open(path);
        // Long enough for the dynamic imports to resolve, as they do on the page that starts it.
        await new Promise((resolve) => setTimeout(resolve, 200));
        expect(posthog.init).not.toHaveBeenCalled();
        expect((window as { posthog?: unknown }).posthog).toBeUndefined();
    },
);
