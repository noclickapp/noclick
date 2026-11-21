// @vitest-environment happy-dom
// Settings → Usage acting as one of the account's keys, as this app serves it: every scene of its lab (lab/scenes.ts)
// opened as the owner and as a key over the lab's world, which answers a key's read of the money as the API does (no
// auto top-up, no friends' credit), and none of those scenes asks for what only the account's signed-in owner may do
// (screens/console/ownerOnly.ts). Nothing else is reached: no call but the page's client's. What every scene calls is
// kept in usageCalls.txt (`npx vitest run -u` writes it again), which NoClick's own tests call on its real API as a key
// and hold to the table.
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { MotionGlobalConfig } from 'framer-motion';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest';
import { isOwnerOnly } from '@/screens/console/ownerOnly';
import { SceneView } from './lab/UsageLab';
import { SCENES, sceneSearch, type UsageScene } from './lab/scenes';
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

/** Opens `scene` as `actsAs` and waits until it has called everything it calls: no call it hasn't made before for a
 *  while, after the first came back. */
async function open(scene: UsageScene, actsAs: ActsAs): Promise<{ method: string; path: string }[]> {
    const calls: { method: string; path: string }[] = [];
    let waiting = 0;
    const observe: Observe = ({ method, url }, answered) => {
        calls.push({ method, path: url.pathname });
        waiting += 1;
        void answered.finally(() => (waiting -= 1));
    };
    const router = createMemoryRouter([{ path: '*', element: <SceneView scene={scene} actsAs={actsAs} observe={observe} /> }], {
        initialEntries: [`/usage-lab${sceneSearch(scene)}`],
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

describe('Settings → Usage acting as a key', () => {
    it('opens every scene without asking for what only the account’s owner may do', { timeout: 600_000 }, async () => {
        const called = new Set<string>();
        const refused: string[] = [];
        for (const scene of SCENES) {
            for (const call of await open(scene, 'owner')) called.add(`${call.method} ${call.path}`);
            for (const call of await open(scene, 'key')) {
                called.add(`${call.method} ${call.path}`);
                if (isOwnerOnly(call.method, call.path)) refused.push(`${scene.id}: ${call.method} ${call.path}`);
            }
        }
        expect(refused).toEqual([]);
        await expect([...called].sort().join('\n') + '\n').toMatchFileSnapshot('./usageCalls.txt');
    });

    it('shows a key the balance as read, with NoClick’s page for adding funds', { timeout: 30_000 }, async () => {
        const member = SCENES.find((s) => s.id === 'account-member')!;
        const router = createMemoryRouter([{ path: '*', element: <SceneView scene={member} actsAs="key" /> }], { initialEntries: [`/usage-lab${sceneSearch(member)}`] });
        render(<RouterProvider router={router} />);
        const add = await screen.findByRole('link', { name: /Add funds/ }, { timeout: 10_000 });
        expect(add.getAttribute('href')).toMatch(/^https:\/\//);
        await waitFor(() => expect(screen.queryByText(/auto top-up/i)).toBeNull());
        cleanup();
    });
});
