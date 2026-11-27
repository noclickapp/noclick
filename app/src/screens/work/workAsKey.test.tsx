// @vitest-environment happy-dom
// Work acting as one of the account's keys, as this app serves it: every view of the lab (lab/scenes.ts) opened over
// fixtures that refuse what only the account's signed-in owner may do (screens/console/ownerOnly.ts) exactly as the
// API refuses a key, and none of those views asks for one. What every view calls, as the owner and as a key, is kept
// in workCalls.txt (`npx vitest run -u` writes it again), which NoClick's own tests call on its real API as a key and
// hold to the table.
import { cleanup, render, waitFor } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { afterEach, describe, expect, it } from 'vitest';
import { SETTLE_MS } from '@/screens/channels/useChannels';
import { isOwnerOnly } from '@/screens/console/ownerOnly';
import { SCENES, type LabScene } from './lab/scenes';
import { answerSessions } from './lab/sessions';
import { SceneView } from './lab/WorkLab';

afterEach(cleanup);

const asLine = ({ method, path }: { method: string; path: string }) => `${method} ${path}`;

/** How long no new call must appear before a scene's calls are taken as all it makes. */
const QUIET_MS = SETTLE_MS * 4;

/** What a scene's views called, and how many calls are still waiting on their answers. */
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
 *  on five looks in a row, after the first came back. (A view that reads again whenever it marks itself read, as the
 *  fixtures' frames make a thread do, keeps calling, but nothing new.) */
async function open(scene: LabScene, actsAs: 'owner' | 'key') {
    const record = recorder();
    const router = createMemoryRouter([{ path: '*', element: <SceneView scene={scene} actsAs={actsAs} site="https://noclick.test" prepare={answerSessions} observe={record.observe} /> }], {
        initialEntries: [`/work?${new URLSearchParams(scene.place)}`],
    });
    render(<RouterProvider router={router} />);
    // A scene that clicks through to a menu, a dialog or what else it opens has made its clicks once that's open.
    const last = scene.steps?.at(-1);
    if (last) await waitFor(() => expect(document.querySelector(scene.opens ?? ('item' in last ? '[role="dialog"]' : '[role="menu"]'))).toBeTruthy());
    // Settled once no new call has appeared for well past the channels' own wait before reading again what a change
    // named (a read, its change, and the read that change asks for come in turn).
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

describe('Work acting as a key', () => {
    it('opens every view without asking for what only the account’s owner may do', { timeout: 300_000 }, async () => {
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
        await expect([...called].sort().join('\n') + '\n').toMatchFileSnapshot('./workCalls.txt');
    });

    it('offers an agent’s sandbox all the same, and says what the API answers a key without its scope', async () => {
        const machine = SCENES.find((s) => s.id === 'machine')!;
        const router = createMemoryRouter([{ path: '*', element: <SceneView scene={machine} actsAs="key" site="https://noclick.test" prepare={answerSessions} /> }], {
            initialEntries: [`/work?${new URLSearchParams(machine.place)}`],
        });
        render(<RouterProvider router={router} />);
        await waitFor(() => expect(document.body.textContent).toContain('Couldn’t list its files: This key hasn’t the agents:terminal scope'));
        cleanup();
    });
});
