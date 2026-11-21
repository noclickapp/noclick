// @vitest-environment happy-dom
// Settings acting as one of the account's keys, as this app serves it: every scene of its lab (lab/scenes.ts) opened as
// the owner and as a key over the lab's world, which answers a key as the API does (the account without its owner's
// fields; a cap a key may only lower). None of those scenes asks for what only the account's signed-in owner may do
// (screens/console/ownerOnly.ts), and nothing is refused: a key is never offered raising or removing the cap, nor
// linking a phone. Nothing else is reached: no call but the page's client's. No call sends or reads a secret: no key,
// token, signing secret or credential in what it sends or what comes back. What every scene calls is kept in
// settingsCalls.txt (`npx vitest run -u` writes it again), which NoClick's own tests call on its real API as a key and
// hold to the table.
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MotionGlobalConfig } from 'framer-motion';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest';
import { isOwnerOnly } from '@/screens/console/ownerOnly';
import { SceneView } from './lab/SettingsLab';
import { SCENES, sceneSearch, type SettingsScene } from './lab/scenes';
import type { ActsAs, Observe } from './lab/world';

beforeAll(() => {
    // The page's motion lands where it ends: an animation cut off by a scene's unmount would cancel in the DOM.
    MotionGlobalConfig.skipAnimations = true;
    vi.stubGlobal('fetch', async (input: RequestInfo | URL) => {
        throw new Error(`The page reached ${input instanceof Request ? input.url : String(input)} outside its client.`);
    });
});
afterAll(() => vi.unstubAllGlobals());

/** How long no new call must appear before a scene's calls are taken as all it makes. */
const QUIET_MS = 1000;

interface Call {
    method: string;
    path: string;
    /** Its answer's status once it came; null while it hasn't (a read that never answers, as one scene's). */
    status: number | null;
    /** What it sent, and what came back once it came. */
    body: unknown;
    answer: unknown;
}

/** Names a secret goes by in what the API sends or takes: a key as it's made, a token, a signing secret, a password, a
 *  credential's values (an object named `data`, where a list's `data` is its items). */
const SECRET = /^(raw_key|api_key|private_key|token|access_token|refresh_token|secret|signing_secret|password|credential|credentials)$/;

/** Every field named like a secret anywhere in `value`, by its path. */
function secrets(value: unknown, at = ''): string[] {
    if (Array.isArray(value)) return value.flatMap((item, i) => secrets(item, `${at}[${i}]`));
    if (!value || typeof value !== 'object') return [];
    return Object.entries(value).flatMap(([name, inner]) => {
        const blob = name === 'data' && !!inner && typeof inner === 'object' && !Array.isArray(inner);
        return [...(SECRET.test(name) || blob ? [`${at}.${name}`] : []), ...secrets(inner, `${at}.${name}`)];
    });
}

/** Opens `scene` as `actsAs` and waits until it has called everything it calls: no call it hasn't made before for a
 *  while, after the first came back. */
async function open(scene: SettingsScene, actsAs: ActsAs): Promise<Call[]> {
    const calls: Call[] = [];
    let waiting = 0;
    const observe: Observe = ({ method, url, body }, answered) => {
        const call: Call = { method, path: url.pathname, status: null, body, answer: null };
        calls.push(call);
        waiting += 1;
        void answered
            .then(async (response) => {
                call.status = response.status;
                call.answer = await response.clone().json().catch(() => null);
            })
            .finally(() => (waiting -= 1));
    };
    const router = createMemoryRouter([{ path: '*', element: <SceneView scene={scene} actsAs={actsAs} observe={observe} /> }], {
        initialEntries: [`/settings-lab${sceneSearch(scene)}`],
    });
    render(<RouterProvider router={router} />);
    let seen = -1;
    let quietSince = 0;
    await waitFor(
        () => {
            const distinct = new Set(calls.map((c) => `${c.method} ${c.path}`)).size;
            if (calls.length <= waiting || distinct !== seen) quietSince = Date.now();
            seen = distinct;
            expect(Date.now() - quietSince).toBeGreaterThanOrEqual(QUIET_MS);
        },
        { timeout: 15_000, interval: 50 }
    );
    cleanup();
    return calls;
}

/** `scene` drawn as `actsAs`, left open. */
function show(id: string, actsAs: ActsAs) {
    const scene = SCENES.find((s) => s.id === id)!;
    const router = createMemoryRouter([{ path: '*', element: <SceneView scene={scene} actsAs={actsAs} /> }], { initialEntries: [`/settings-lab${sceneSearch(scene)}`] });
    render(<RouterProvider router={router} />);
}

describe('Settings acting as a key', () => {
    it('opens every scene without asking for what only the account’s owner may do', { timeout: 600_000 }, async () => {
        const called = new Set<string>();
        const refused: string[] = [];
        const secret: string[] = [];
        const seen = (scene: SettingsScene, call: Call) => {
            called.add(`${call.method} ${call.path}`);
            for (const field of [...secrets(call.body, 'sent'), ...secrets(call.answer, 'answer')]) secret.push(`${scene.id}: ${call.method} ${call.path} ${field}`);
        };
        for (const scene of SCENES) {
            for (const call of await open(scene, 'owner')) seen(scene, call);
            for (const call of await open(scene, 'key')) {
                seen(scene, call);
                if (isOwnerOnly(call.method, call.path) || call.status === 403) refused.push(`${scene.id}: ${call.method} ${call.path}`);
            }
        }
        expect(refused).toEqual([]);
        expect(secret).toEqual([]);
        await expect([...called].sort().join('\n') + '\n').toMatchFileSnapshot('./settingsCalls.txt');
    });

    it('lets a key lower the cap and sends it to NoClick to raise or remove it', { timeout: 30_000 }, async () => {
        show('billing-change-cap', 'key');
        const field = (await screen.findByLabelText('Cap each period', {}, { timeout: 10_000 })) as HTMLInputElement;
        expect(screen.queryByRole('button', { name: 'Remove cap' })).toBeNull();
        const elsewhere = screen.getByRole('link', { name: /Raise or remove it on NoClick/ });
        expect(elsewhere.getAttribute('href')).toBe('https://noclick.com/dashboard?tab=settings&section=billing');
        fireEvent.change(field, { target: { value: '80' } });
        expect(screen.getByRole('alert').textContent).toContain('The account’s owner raises it on NoClick.');
        expect((screen.getByRole('button', { name: 'Save' }) as HTMLButtonElement).disabled).toBe(true);
        fireEvent.change(field, { target: { value: '30' } });
        fireEvent.click(screen.getByRole('button', { name: 'Save' }));
        expect(await screen.findByText('$12.40 of $30 spent this period · resets November 1')).toBeTruthy();
        cleanup();
    });

    it('offers a key at the cap NoClick’s page to raise it, and the owner the raise itself', { timeout: 30_000 }, async () => {
        show('billing-cap-reached', 'key');
        const raise = await screen.findByRole('link', { name: /Raise it on NoClick/ }, { timeout: 10_000 });
        expect(raise.getAttribute('href')).toBe('https://noclick.com/dashboard?tab=settings&section=billing');
        expect(screen.queryByRole('button', { name: 'Raise cap' })).toBeNull();
        cleanup();
        show('billing-cap-reached', 'owner');
        fireEvent.click(await screen.findByRole('button', { name: 'Raise cap' }, { timeout: 10_000 }));
        expect(screen.getByRole('button', { name: 'Remove cap' })).toBeTruthy();
        cleanup();
    });

    it('lets the owner link a number by its code, and never offers a key linking one', { timeout: 30_000 }, async () => {
        show('phone-none', 'owner');
        await screen.findByText('Link a number', {}, { timeout: 10_000 });
        const field = document.querySelector<HTMLInputElement>('input[type="tel"]')!;
        await waitFor(() => expect(field.disabled).toBe(false));
        fireEvent.change(field, { target: { value: '+14155550123' } });
        fireEvent.click(screen.getByRole('button', { name: 'Send code' }));
        fireEvent.change(await screen.findByLabelText('Code'), { target: { value: '123456' } });
        fireEvent.click(screen.getByRole('button', { name: 'Verify' }));
        expect(await screen.findByText('Add another number')).toBeTruthy();
        expect(screen.getAllByRole('button', { name: 'Unlink' })).toHaveLength(1);
        cleanup();
        // A key is never offered Phone: the API links a number only for the owner or a key that names its scope.
        show('phone-none', 'key');
        expect(await screen.findAllByText('Usage', {}, { timeout: 10_000 })).toBeTruthy();
        expect(screen.queryByText('Link a number')).toBeNull();
        expect(screen.queryByRole('button', { name: /^Phone/ })).toBeNull();
        cleanup();
    });

    it('lets a key turn a dismissed popup back on', { timeout: 30_000 }, async () => {
        show('popups', 'key');
        const banner = await screen.findByRole('switch', { name: 'Collaboration invite banner' }, { timeout: 10_000 });
        await waitFor(() => expect(banner.getAttribute('aria-checked')).toBe('false'));
        fireEvent.click(banner);
        await waitFor(() => expect(screen.getByRole('switch', { name: 'Collaboration invite banner' }).getAttribute('aria-checked')).toBe('true'));
        cleanup();
    });

    it('reads the plan and the balance as a key does, with NoClick’s pages for changing them', { timeout: 30_000 }, async () => {
        show('billing', 'key');
        expect(await screen.findByText('Member', {}, { timeout: 10_000 })).toBeTruthy();
        expect(screen.getByText(/\$42\.50 left/)).toBeTruthy();
        expect(screen.getByRole('link', { name: /Add funds on NoClick/ }).getAttribute('href')).toBe('https://noclick.com/dashboard?action=topup');
        await waitFor(() => expect(screen.getByText('$12.40 of $50 spent this period · resets November 1')).toBeTruthy());
        cleanup();
    });
});
