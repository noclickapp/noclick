// @vitest-environment happy-dom
// A space you joined lists its agents in Agents, read through your session in it: where its agents stand, for that
// space alone. Before people could read agent states, the list said only "Couldn’t load your agents."
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { afterEach, expect, it, vi } from 'vitest';
import { WorkClientContext } from './client';
import { fakeWork, JOINED_SESSION } from './fixtures/workApi';
import { WorkLiveContext } from '@/sdk/live';
import { Work } from './Work';
import { MORE_AGENTS } from '@/screens/channels/slots';
import { fill } from '@/slots';

// No agents from Automations in the pickers here (the hosted fill would ask the app's socket).
fill(MORE_AGENTS, null);

afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
});

it("a joined space's Agents list shows its agents, read through your session for that space", async () => {
    const fake = fakeWork();
    // A joined space's session client reaches the fake through the global fetch.
    vi.stubGlobal('fetch', fake.fetch);
    const router = createMemoryRouter([{ path: '/dashboard', element: <Work user={{ email: 'rowan@example.com', display_name: 'Rowan Hale' }} /> }], {
        initialEntries: ['/dashboard?tab=work&space=ws_acme&show=agents'],
    });
    render(
        <WorkClientContext.Provider value={fake.client}>
            <WorkLiveContext.Provider value={fake.live}>
                    <RouterProvider router={router} />
            </WorkLiveContext.Provider>
        </WorkClientContext.Provider>
    );
    // In the list (the pane beside it, with no agent open, shows them too).
    await within(await screen.findByTestId('agents-list', {}, { timeout: 5000 })).findByText('Ops', {}, { timeout: 5000 });
    expect(document.body.textContent).not.toContain('Couldn’t load your agents');
    const read = fake.requests.filter((r) => r.method === 'GET' && r.path === '/v1/agents/states' && r.session);
    expect(read.length).toBeGreaterThan(0);
    await waitFor(() => expect(read.every((r) => r.session === JOINED_SESSION && r.query.get('workspace_id') === 'ws_acme')).toBe(true));
});
