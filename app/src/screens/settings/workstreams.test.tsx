// @vitest-environment happy-dom
// Settings → Workstreams over the lab's world, as the API answers it: the open ones with what each spent this month and
// the archived ones apart; archiving one moves it there and unarchiving brings it back; a rename onto another's name
// says it merges before it's sent, and once sent the merged one leaves the list; a name the API would refuse is said
// before it's sent; and a read that fails offers to try again.
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MotionGlobalConfig } from 'framer-motion';
import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { ClientProvider } from '@/sdk/client';
import { createWorkLive, WorkLiveContext } from '@/sdk/live';
import { workFixtureClient } from '@/screens/work/fixtures/client';
import { settingsClient, type Observe, type SettingsApiWorld } from './lab/world';
import { nameError, WorkstreamsSection } from './workstreams';

beforeAll(() => {
    MotionGlobalConfig.skipAnimations = true;
});
afterEach(cleanup);

const WORLD: SettingsApiWorld = { tier: 'member', balanceUsd: 42.5, capUsd: 50, spentUsd: 12.4 };

function show(world: SettingsApiWorld = WORLD, client = settingsClient(world)) {
    const live = createWorkLive();
    render(
        <ClientProvider client={client}>
            <WorkLiveContext.Provider value={live}>
                <WorkstreamsSection />
            </WorkLiveContext.Provider>
        </ClientProvider>
    );
    return live;
}

const rowOf = (name: string) => screen.getByText(name, { selector: 'div' }).closest('div.flex') as HTMLElement;

describe('Settings → Workstreams', () => {
    it('lists the open ones with what each spent this month, and the archived ones apart', async () => {
        show();
        await screen.findByText('Customer support');
        expect(within(rowOf('Customer support')).getByText('$12.40 this month')).toBeTruthy();
        expect(within(rowOf('Menu refresh')).getByText('Nothing spent this month')).toBeTruthy();
        expect(screen.getByRole('heading', { level: 3, name: 'Archived' })).toBeTruthy();
        expect(screen.getByRole('button', { name: 'Unarchive Q3 launch' })).toBeTruthy();
    });

    it('archives one and brings it back', async () => {
        show();
        fireEvent.click(await screen.findByRole('button', { name: 'Archive Menu refresh' }));
        await screen.findByRole('button', { name: 'Unarchive Menu refresh' });
        fireEvent.click(screen.getByRole('button', { name: 'Unarchive Menu refresh' }));
        await screen.findByRole('button', { name: 'Archive Menu refresh' });
    });

    it('says a rename onto another’s name merges, then the merged one leaves the list', async () => {
        show();
        fireEvent.click(await screen.findByRole('button', { name: 'Rename Menu refresh' }));
        const field = await screen.findByLabelText('New name');
        fireEvent.change(field, { target: { value: '  spring   LAUNCH ' } });
        expect(screen.getByText('Merge Menu refresh into Spring launch?')).toBeTruthy();
        fireEvent.click(screen.getByRole('button', { name: 'Merge into Spring launch' }));
        await waitFor(() => expect(screen.queryByRole('button', { name: 'Rename Menu refresh' })).toBeNull());
        expect(screen.getByRole('button', { name: 'Rename Spring launch' })).toBeTruthy();
    });

    it('renames one in place', async () => {
        show();
        fireEvent.click(await screen.findByRole('button', { name: 'Rename Customer support' }));
        fireEvent.change(await screen.findByLabelText('New name'), { target: { value: 'Support inbox' } });
        expect(screen.getByText('Rename Customer support')).toBeTruthy();
        fireEvent.click(screen.getByRole('button', { name: 'Rename' }));
        await screen.findByRole('button', { name: 'Rename Support inbox' });
    });

    it('says what the API would refuse in a name before it’s sent', () => {
        expect(nameError('')).toBe('Give it a name.');
        expect(nameError('web/site')).toBe('A name can’t have a slash in it.');
        expect(nameError('x'.repeat(61))).toBe('A name is at most 60 characters.');
        expect(nameError('Bakery site')).toBeNull();
    });

    it('reads them again when one changes elsewhere, and on nothing else of the kind', async () => {
        const reads: string[] = [];
        const observe: Observe = ({ method, url }) => void (method === 'GET' && url.pathname === '/v1/workstreams' && reads.push(url.search));
        const live = show(WORLD, settingsClient(WORLD, observe));
        await screen.findByText('Customer support');
        const before = reads.length;
        live.deliver('platform:resource', { kind: 'notifications', id: 'u_ada', status: 'active' });
        live.deliver('platform:resource', { kind: 'workstream', id: 'ws_menu', status: 'archived' });
        await waitFor(() => expect(reads.length).toBe(before + 2));
        expect(reads.slice(before).sort()).toEqual(['', '?archived=true']);
    });

    it('says when there are none yet', async () => {
        show({ ...WORLD, workstreams: 'none' });
        expect(await screen.findByText('No workstreams yet. Your agents name one as they start work.')).toBeTruthy();
    });

    it('offers to try again when the read fails', async () => {
        const failing = workFixtureClient(async () => Response.json({ error: { type: 'server_error', message: 'The workstreams didn’t load.' } }, { status: 500 }), { maxRetries: 0 });
        show(WORLD, failing);
        expect(await screen.findByText('Your workstreams didn’t load.')).toBeTruthy();
        expect(screen.getByRole('button', { name: 'Try again' })).toBeTruthy();
    });
});
