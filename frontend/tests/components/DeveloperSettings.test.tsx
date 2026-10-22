// @vitest-environment jsdom
// Settings → Developer makes keys itself only where no developer console is registered (the open edition); with
// one, it opens the console and lists only the older keys that still work.
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn(async () => ({ workflows: [] })) }));
vi.mock('~/lib/apiAuth', () => ({ backendAuthHeaders: async () => ({}), backendAccountHeaders: async () => ({}) }));

import { DeveloperSettings } from '~/components/settings/DeveloperSettings';
import { registerDeveloperConsole } from '~/lib/developerConsole';

const key = (name: string, revoked = false) => ({
    id: name, name, key_prefix: 'nk_live_abcd', workflow_id: null, permissions: ['read'],
    created_at: '2026-10-01T00:00:00Z', last_used_at: null, expires_at: null, revoked_at: revoked ? '2026-10-02T00:00:00Z' : null,
});

let keys: ReturnType<typeof key>[] = [];

function renderSection() {
    return render(
        <MemoryRouter>
            <DeveloperSettings />
        </MemoryRouter>
    );
}

describe('Settings → Developer', () => {
    beforeEach(() => {
        keys = [];
        vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(keys), { status: 200 })));
    });
    afterEach(() => {
        cleanup();
        vi.unstubAllGlobals();
    });

    // Runs first: the console is registered once per module, as a deployment's bootstrap does.
    it('makes keys itself where no console is registered', async () => {
        renderSection();
        expect(screen.getByLabelText('Key name')).toBeTruthy();
        expect(screen.queryByRole('link', { name: /Open console/ })).toBeNull();
    });

    it('opens the console where one is registered, without a way to make keys here', async () => {
        registerDeveloperConsole('/dashboard/developers');
        renderSection();
        expect(screen.getByRole('link', { name: /Open console/ }).getAttribute('href')).toBe('/dashboard/developers');
        expect(screen.queryByLabelText('Key name')).toBeNull();
        await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalled());
        expect(screen.queryByText('Older keys')).toBeNull();
    });

    it('lists the older keys that still work, and none that were revoked or made by publishing', async () => {
        keys = [key('Dashboard app'), key('Old script', true), key('Published: Shop')];
        renderSection();
        expect(await screen.findByText('Older keys')).toBeTruthy();
        expect(screen.getByRole('button', { name: 'Revoke Dashboard app' })).toBeTruthy();
        expect(screen.queryByText('Old script')).toBeNull();
        expect(screen.queryByText('Published: Shop')).toBeNull();
    });
});
