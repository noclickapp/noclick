// @vitest-environment happy-dom
// A new key is shown once, alone: named for the key just made, whole (so a phone shows all of it), with Copy and a
// Copy as a .env line that holds it under the variable the SDKs read.
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useParams } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { DeveloperConsole } from '../DeveloperConsole';
import { fixtureClient } from '../fixtures/client';
import { FIXTURE_NOW_MS, FIXTURE_USER } from '../fixtures/core';
import { LAB_RAW_KEY } from '../fixtures/pages/a';

afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
});

function keysPage() {
    const client = fixtureClient({ set: 'populated' }, { maxRetries: 0 });
    function Mounted() {
        return (
            <DeveloperConsole
                section={useParams()['*']}
                client={client}
                actsAs="owner"
                basePath="/developers"
                apiUrl="https://api.noclick.com"
                site="https://noclick.com"
                home="/"
                user={FIXTURE_USER}
                now={() => FIXTURE_NOW_MS}
                onSignOut={() => undefined}
                live={null}
            />
        );
    }
    render(
        <MemoryRouter initialEntries={['/developers/keys']}>
            <Routes>
                <Route path="/developers/*" element={<Mounted />} />
            </Routes>
        </MemoryRouter>
    );
}

describe('a key made in the console', () => {
    it('is shown once, whole, with a copy of the .env line it goes in', async () => {
        const writeText = vi.fn(async () => undefined);
        vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } });
        keysPage();
        fireEvent.click(await screen.findByRole('button', { name: 'New key' }));
        fireEvent.change(await screen.findByLabelText('Name'), { target: { value: 'backend-prod' } });
        fireEvent.click(screen.getByRole('button', { name: 'Create key' }));

        expect(await screen.findByText('backend-prod is ready')).toBeTruthy();
        expect(screen.getByTestId('secret-shown-once').textContent).toBe(LAB_RAW_KEY);
        fireEvent.click(screen.getByRole('button', { name: 'Copy as a .env line' }));
        await waitFor(() => expect(writeText).toHaveBeenCalledWith(`NOCLICK_API_KEY=${LAB_RAW_KEY}`));
        fireEvent.click(screen.getByRole('button', { name: 'Copy key' }));
        await waitFor(() => expect(writeText).toHaveBeenLastCalledWith(LAB_RAW_KEY));
    }, 30_000);
});
