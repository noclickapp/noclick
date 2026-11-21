// @vitest-environment happy-dom
// A revoked connection NoClick itself makes (its assistant's) offers Restore on its row, which turns it back on as it
// was; a revoked client a person connected offers nothing (it connects again), and a live one offers Revoke.
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { DEFAULT_BASE_URL, NoClick } from 'noclick';
import { MemoryRouter, Route, Routes, useParams } from 'react-router';
import { afterEach, expect, it } from 'vitest';
import { DeveloperConsole } from '../../DeveloperConsole';
import { FIXTURE_NOW_MS, FIXTURE_USER } from '../../fixtures/core';
import { makeFixtureFetch } from '../../fixtures/fixtureFetch';
import { CONNECTED_APPS } from '../../fixtures/pages/a';

afterEach(cleanup);

const WAIT = { timeout: 10_000 };

function openKeys(): string[] {
    const answer = makeFixtureFetch({ set: 'populated', actsAs: 'owner' });
    const made: string[] = [];
    const client = new NoClick({
        apiKey: 'a-fixture-holds-no-key',
        baseUrl: DEFAULT_BASE_URL,
        maxRetries: 0,
        fetch: async (input, init) => {
            const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url);
            made.push(`${(init?.method ?? 'GET').toUpperCase()} ${url.pathname}`);
            return answer(input, init);
        },
    });
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
        </MemoryRouter>,
    );
    return made;
}

const assistant = CONNECTED_APPS.find((a) => a.client.id === 'noclick:coordinator')!;
const revokedClient = CONNECTED_APPS.find((a) => a.revoked_at && !a.restorable)!;

it('restores the assistant’s revoked connection from its row, as it was', async () => {
    const made = openKeys();
    const section = (await screen.findByRole('heading', { name: 'Connected apps' }, WAIT)).closest('section')!;
    // A revoked client a person connected has no actions; a live one revokes.
    await within(section).findByText(assistant.client.name, {}, WAIT);
    expect(within(section).queryByRole('button', { name: `Actions for ${revokedClient.client.name}` })).toBeNull();
    fireEvent.keyDown(within(section).getByRole('button', { name: 'Actions for Claude' }), { key: 'Enter' });
    expect((await screen.findAllByRole('menuitem')).map((item) => item.textContent)).toEqual(['Revoke']);
    fireEvent.keyDown(document.activeElement ?? document.body, { key: 'Escape' });

    fireEvent.keyDown(within(section).getByRole('button', { name: `Actions for ${assistant.client.name}` }), { key: 'Enter' });
    const [restore] = await screen.findAllByRole('menuitem');
    expect(restore.textContent).toBe('Restore');
    fireEvent.click(restore);
    const dialog = await screen.findByRole('dialog', { name: `Restore ${assistant.client.name}?` }, WAIT);
    expect(dialog.textContent).toContain('it can read, build, deploy, spend, delete, with a cap of $25.00 a month');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Restore' }));
    await waitFor(() => expect(made).toContain(`POST /v1/connected_apps/${assistant.id}/restore`), WAIT);
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull(), WAIT);
});
