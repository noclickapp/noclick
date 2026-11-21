// @vitest-environment happy-dom
// Connections acting as one of the account's keys, as this app serves it: every scene of the lab (lab/scenes.ts)
// opened over fixtures that refuse what only the account's signed-in owner may do (screens/console/ownerOnly.ts) exactly
// as the API refuses a key, and none of those scenes asks for one. What every scene calls, as the owner and as a key, is
// kept in connectionsCalls.txt (`npx vitest run -u` writes it again), which NoClick's own tests call on its real API as
// a key and hold to the table. And what the page does with an account here: it connects one at NoClick's connect page in
// a new tab, never sending a secret, and sends a key to NoClick's own pages for what only the owner does.
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { isOwnerOnly, ownerOnlyWhy } from '@/screens/console/ownerOnly';
import { SceneView } from './lab/ConnectionsLab';
import { SCENES, sceneSearch, type ConnectionsScene } from './lab/scenes';

afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
});

const asLine = ({ method, path }: { method: string; path: string }) => `${method} ${path}`;

/** How long no new call must appear before a scene's calls are taken as all it makes. */
const QUIET_MS = 1200;

interface Call {
    method: string;
    path: string;
    body: Record<string, unknown>;
}

function recorder() {
    const calls: Call[] = [];
    let waiting = 0;
    return {
        calls,
        get waiting() {
            return waiting;
        },
        observe: (method: string, path: string, answered: Promise<Response>, body: Record<string, unknown>) => {
            calls.push({ method, path, body });
            waiting += 1;
            void answered.finally(() => (waiting -= 1));
        },
    };
}

function draw(scene: ConnectionsScene, actsAs: 'owner' | 'key', observe?: ReturnType<typeof recorder>['observe']) {
    const router = createMemoryRouter([{ path: '*', element: <SceneView scene={scene} actsAs={actsAs} site="https://noclick.test" observe={observe} /> }], {
        initialEntries: [`/connections-lab${sceneSearch(scene)}`],
    });
    return render(<RouterProvider router={router} />);
}

/** Opens `scene` as `actsAs` and waits until it has called everything it calls: no call it hasn't made before for a
 *  while, after the first came back. */
async function open(scene: ConnectionsScene, actsAs: 'owner' | 'key') {
    const record = recorder();
    draw(scene, actsAs, record.observe);
    let seen = -1;
    let quietSince = 0;
    await waitFor(
        () => {
            const distinct = new Set(record.calls.map(asLine)).size;
            const answered = record.calls.length > record.waiting;
            if (!answered || distinct !== seen) quietSince = Date.now();
            seen = distinct;
            expect(Date.now() - quietSince).toBeGreaterThanOrEqual(QUIET_MS);
        },
        { timeout: 15_000, interval: 50 }
    );
    cleanup();
    return record.calls;
}

/** The catalog draws only the rows near the viewport, as a browser lays them out: a laptop's window, each row a tile
 *  tall. */
function laptopSizes() {
    const height = function (this: HTMLElement) {
        return this.hasAttribute('data-index') ? 78 : 800;
    };
    vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockImplementation(height);
    vi.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockImplementation(height);
    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockImplementation(() => 1280);
}

/** A tab a click opened, where the page sends it. */
function stubTabs() {
    const tabs: { location: { href: string }; closed: boolean; opener: unknown; close: () => void }[] = [];
    vi.stubGlobal('open', () => {
        const tab = { location: { href: 'about:blank' }, closed: false, opener: null as unknown, close: () => undefined };
        tabs.push(tab);
        return tab;
    });
    return tabs;
}

const scene = (id: string) => SCENES.find((s) => s.id === id)!;

describe('Connections acting as a key', () => {
    it('opens every scene without asking for what only the account’s owner may do', { timeout: 600_000 }, async () => {
        const called = new Set<string>();
        const refused: string[] = [];
        for (const each of SCENES) {
            for (const call of await open(each, 'owner')) called.add(asLine(call));
            for (const call of await open(each, 'key')) {
                called.add(asLine(call));
                if (isOwnerOnly(call.method, call.path)) refused.push(`${each.id}: ${asLine(call)}`);
            }
        }
        expect(refused).toEqual([]);
        await expect([...called].sort().join('\n') + '\n').toMatchFileSnapshot('./connectionsCalls.txt');
    });

    it('connects an app at NoClick’s connect page in a new tab, sending no secret, and lists it once it lands', { timeout: 30_000 }, async () => {
        laptopSizes();
        const tabs = stubTabs();
        const record = recorder();
        draw(scene('catalog'), 'key', record.observe);
        const [connect] = await screen.findAllByRole('button', { name: 'Connect Airtable' }, { timeout: 8000 });
        await act(async () => fireEvent.click(connect));
        // A named connection of the app, with nothing of the account's in it.
        await waitFor(() => expect(record.calls.filter((c) => c.method === 'POST' && c.path === '/v1/connections').map((c) => c.body)).toEqual([
            expect.objectContaining({ name: expect.stringMatching(/^airtable-/), integration: 'airtable', credential_type: 'airtable_pat' }),
        ]));
        for (const call of record.calls) {
            expect(call.body, asLine(call)).not.toHaveProperty('data');
            expect(call.path, asLine(call)).not.toMatch(/\/(token|import)$/);
        }
        // The tab opened inside the click goes to the connection's connect page on NoClick.
        await waitFor(() => expect(tabs[0]?.location.href).toMatch(/^https:\/\/noclick\.test\/connect\/airtable-/));
        // Once the account lands there, it's listed.
        fireEvent.click(screen.getByRole('tab', { name: /Connected/ }));
        await waitFor(() => expect(screen.getAllByTestId('connected-account').some((tile) => tile.textContent?.includes('Airtable'))).toBe(true), { timeout: 8000 });
    });

    it('sends a key to NoClick’s own pages to share an account or lift its approvals', { timeout: 30_000 }, async () => {
        draw(scene('account'), 'key');
        await screen.findByTestId('account-page', undefined, { timeout: 8000 });
        expect(await screen.findByText(ownerOnlyWhy('connectionSharing'))).toBeTruthy();
        const share = screen.getByRole('link', { name: /Share on NoClick/ });
        expect(share.getAttribute('href')).toBe('https://noclick.test/dashboard?tab=connections&view=connected&account=cred_github');
        expect(share.getAttribute('target')).toBe('_blank');
        const approvals = screen.getByRole('link', { name: /Choose which of its actions wait for your OK/ });
        expect(approvals.getAttribute('href')).toBe('https://noclick.test/credential/permissions/cred_github');
        expect(approvals.getAttribute('target')).toBe('_blank');
    });

    it('reconnects an account connected in the app at its own connect link, in a new tab', { timeout: 30_000 }, async () => {
        const tabs = stubTabs();
        const record = recorder();
        draw(scene('account-revoked'), 'key', record.observe);
        const reconnect = await screen.findByRole('button', { name: 'Reconnect' }, { timeout: 8000 });
        await act(async () => fireEvent.click(reconnect));
        await waitFor(() => expect(tabs[0]?.location.href).toBe('https://noclick.test/connect/reconnect-cred_slack'));
        expect(record.calls.map(asLine)).toContain('POST /v1/connections/credential:cred_slack/connect_links');
    });
});
