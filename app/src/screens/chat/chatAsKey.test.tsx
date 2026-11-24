// @vitest-environment happy-dom
// The chat acting as one of the account's keys, as this app serves it: every scene of the lab (lab/scenes.ts) opened
// over fixtures that refuse what only the account's signed-in owner may do (screens/console/ownerOnly.ts) exactly as
// the API refuses a key, and none of those scenes asks for one. What every scene calls, as the owner and as a key, is
// kept in chatCalls.txt (`npx vitest run -u` writes it again), which NoClick's own tests call on its real API as a key
// and hold to the table.
import { cleanup, render, waitFor } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { isOwnerOnly } from '@/screens/console/ownerOnly';
import { SceneView } from './lab/ChatLab';
import { SCENES, sceneSearch, type ChatScene } from './lab/scenes';
import { CLOCK } from './lab/threads';

afterEach(cleanup);

const asLine = ({ method, path }: { method: string; path: string }) => `${method} ${path}`;

/** How long no new call must appear before a scene's calls are taken as all it makes. */
const QUIET_MS = 1200;

function recorder() {
    const calls: { method: string; path: string }[] = [];
    let waiting = 0;
    return {
        calls,
        get waiting() {
            return waiting;
        },
        observe: (method: string, path: string, answered: Promise<Response>) => {
            calls.push({ method, path });
            waiting += 1;
            void answered.finally(() => (waiting -= 1));
        },
    };
}

/** Opens `scene` as `actsAs` and waits until its views have called everything they call: no call it hasn't made before
 *  for a while, after the first came back. */
async function open(scene: ChatScene, actsAs: 'owner' | 'key') {
    const record = recorder();
    const router = createMemoryRouter([{ path: '*', element: <SceneView scene={scene} actsAs={actsAs} site="https://noclick.test" observe={record.observe} /> }], {
        initialEntries: [`/chat-lab${sceneSearch(scene)}`],
    });
    render(<RouterProvider router={router} />);
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
        { interval: 50 }
    );
    cleanup();
    return record.calls;
}

describe('the chat acting as a key', () => {
    it('opens every scene without asking for what only the account’s owner may do', { timeout: 600_000 }, async () => {
        const called = new Set<string>();
        const refused: string[] = [];
        for (const scene of SCENES) {
            for (const call of await open(scene, 'owner')) called.add(asLine(call));
            for (const call of await open(scene, 'key')) {
                called.add(asLine(call));
                if (isOwnerOnly(call.method, call.path)) refused.push(`${scene.id}: ${asLine(call)}`);
            }
        }
        expect(refused).toEqual([]);
        await expect([...called].sort().join('\n') + '\n').toMatchFileSnapshot('./chatCalls.txt');
    });

    it('opens a held purchase’s page on NoClick rather than approving it here', async () => {
        // At the lab's moment, while the purchase still waits.
        vi.useFakeTimers({ toFake: ['Date'] });
        vi.setSystemTime(new Date(CLOCK));
        const scene = SCENES.find((s) => s.id === 'approval-purchase')!;
        const router = createMemoryRouter([{ path: '*', element: <SceneView scene={scene} actsAs="key" site="https://noclick.test" /> }], {
            initialEntries: [`/chat-lab${sceneSearch(scene)}`],
        });
        render(<RouterProvider router={router} />);
        const review = await waitFor(() => {
            const link = document.querySelector<HTMLAnchorElement>('[data-testid="platform-approval-open"]');
            expect(link?.textContent).toContain('Review on NoClick');
            return link!;
        });
        expect(review.getAttribute('href')).toMatch(/^https:\/\/noclick\.test\/approve\//);
        expect([...document.querySelectorAll('button')].some((b) => b.textContent?.trim() === 'Approve')).toBe(false);
        cleanup();
        vi.useRealTimers();
    });
});
