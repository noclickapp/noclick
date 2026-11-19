// @vitest-environment happy-dom
// Work's Agents list over the fake /v1: the space's NoClick pinned first (in your personal space your own, named as
// your assistant everywhere; in a team space the space's own, named for it), then your agents, and never one of
// NoClick's helpers (an app's coding agent it made when its assistant handed the app a change), which the API still
// lists, marked `helper`, for the places its work shows (the chat's At work tab, beside the conversation that started it).
import { cleanup, render, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, expect, it } from 'vitest';
import { Agent } from 'noclick';
import { useOwnSpaceNoClicks } from '../intro';
import type { WorkSpace } from '../spaces';
import { AgentsList } from './AgentsList';
import { WorkProviders } from './fixtures/providers';
import { fakeWork, HELPER_ID, id, SPACE_ID, SPACE_NOCLICK_ID } from './fixtures/workAgents';
import { readAgents, SpaceNoClicksContext } from './reads';

afterEach(cleanup);

const YOURS_LINE = 'Your assistant everywhere, across all your spaces and your phone';
const space = (name: string): WorkSpace => ({ id: SPACE_ID, workspaceId: SPACE_ID, name, own: true, role: 'owner' });

/** The account's spaces' NoClicks as Work reads them for every view. */
function OwnSpaces({ spaces, children }: { spaces: WorkSpace[]; children: ReactNode }) {
    return <SpaceNoClicksContext.Provider value={useOwnSpaceNoClicks(spaces)}>{children}</SpaceNoClicksContext.Provider>;
}

function show(fake = fakeWork({ coordinator: true, helper: true }), spaceId: string | null = null, spaces: WorkSpace[] = []) {
    const list = (named: WorkSpace[]) => (
        <WorkProviders client={fake.client}>
            <OwnSpaces spaces={named}>
                <AgentsList spaceId={spaceId} selectedAgentId={null} onOpen={() => undefined} onNew={() => undefined} />
            </OwnSpaces>
        </WorkProviders>
    );
    const view = render(list(spaces));
    const rows = () => Array.from(view.container.querySelectorAll<HTMLElement>('li[data-agent]'));
    const pinned = () => rows().find((r) => r.dataset.pinned === 'true');
    return { fake, view, rows, pinned, rename: (named: WorkSpace[]) => view.rerender(list(named)) };
}

it("lists your NoClick and your agents, never one of NoClick's helpers", async () => {
    const { rows } = show();
    await waitFor(() => expect(rows().length).toBeGreaterThan(1));
    const [pinned, ...yours] = rows();
    expect(pinned.dataset.pinned).toBe('true');
    expect(pinned.textContent).toContain('Your NoClick');
    expect(yours.map((r) => r.dataset.agent).sort()).toEqual([1, 2, 3, 4, 5].map(id).sort());
    expect(rows().some((r) => r.dataset.agent === HELPER_ID || r.textContent?.includes('shop-coder'))).toBe(false);
});

it('still reads the helper, marked, where its work shows', async () => {
    const { client } = fakeWork({ coordinator: true, helper: true });
    const helper = (await readAgents(client)).find((a) => a.id === HELPER_ID);
    expect(helper?.helper).toBe(true);
    expect((await readAgents(client)).filter((a) => a.helper).map((a) => a.id)).toEqual([HELPER_ID]);
    expect((await Agent.states({ client })).data.some((s) => s.agentId === HELPER_ID)).toBe(true);
});

it('in your personal space, pins your NoClick as your assistant everywhere, across your spaces and your phone', async () => {
    const { pinned } = show(fakeWork({ coordinator: true, spaceNoClick: true }), null, [space('Launch')]);
    await waitFor(() => expect(pinned()?.textContent).toContain(YOURS_LINE));
    expect(pinned()!.querySelector('[data-name]')?.textContent).toBe('Your NoClick');
});

it("in a team space, pins the space's own NoClick, named for the space, and never yours", async () => {
    const { rows, pinned, rename } = show(fakeWork({ coordinator: true, spaceNoClick: true }), SPACE_ID, [space('Launch')]);
    await waitFor(() => expect(pinned()?.dataset.agent).toBe(SPACE_NOCLICK_ID));
    expect(pinned()!.querySelector('[data-name]')?.textContent).toBe('NoClick for Launch');
    expect(pinned()!.textContent).toContain('Changes this space when you ask; tells you what matters');
    expect(rows().filter((r) => r.dataset.agent === SPACE_NOCLICK_ID)).toHaveLength(1);
    expect(rows().some((r) => /Your NoClick|across all your spaces/.test(r.textContent ?? ''))).toBe(false);

    // Renamed, the space's NoClick goes by the new name.
    rename([space('Growth')]);
    await waitFor(() => expect(pinned()!.querySelector('[data-name]')?.textContent).toBe('NoClick for Growth'));
});
