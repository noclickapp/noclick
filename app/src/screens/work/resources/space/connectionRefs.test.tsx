// @vitest-environment happy-dom
// A space's Resources name each of the account's connections by the ref the platform resolves: a named connection by
// its name, an account connected in the NoClick app by `credential:<id>`. Named by its name, an app account shared
// with a space named no connection, or, where a named connection had its name, that other account: the one shared for
// good. A space's link names what it shares by its id, so a named connection shared already was still offered (by its
// name) and adding it again was refused.
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { Connection, Workspace } from 'noclick';
import { Toaster } from 'sonner';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { WorkProviders } from '../../agents/fixtures/providers';
import { fakeWork, SPACE_ID } from '../../agents/fixtures/workAgents';
import { share, useSpaceShare } from './data';
import { AddDialog } from './dialogs';

type Json = Record<string, unknown>;

beforeEach(() => {
    // Nothing real is called: the reads beside the views find nothing.
    vi.stubGlobal('fetch', async () => new Response(null, { status: 404 }));
});
afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
});

/** A key saved in the app under the name a named connection of the account already has ('anthropic'). */
const APP_KEY = { id: 'credential:c-key', name: 'anthropic', account: 'Key ending 55aa' };
const NAMED_KEY_ACCOUNT = 'Key ending 4f2a';

function world() {
    const fake = fakeWork({ keys: 'several' });
    fake.addAppAccount('c-key', APP_KEY.name, 'anthropic', 'agent_anthropic', APP_KEY.account);
    return fake;
}

/** The connection a ref names, by the platform's rule for one shared with a space or deleted
 *  (`connect.service._visible`): `credential:<id>` names an account connected in the app by its id, any other ref a
 *  named connection by its name or id, never an app account by its name. */
function namedOnThePlatform(ref: string, connections: readonly Json[]): Json | undefined {
    if (ref.startsWith('credential:')) return connections.find((c) => c.origin === 'app' && c.id === ref);
    return connections.find((c) => c.origin !== 'app' && (c.name === ref || c.id === ref));
}

/** The account's connections as the API lists them. */
const listed = async (fake: ReturnType<typeof world>) => (await Connection.list({ client: fake.client })).map((c) => c.raw as Json);

/** The space's "Add from the account" for connections, with how many of its connections are shared with it. */
function Adding() {
    const share = useSpaceShare(SPACE_ID);
    return (
        <>
            <span data-testid="shared-here">{share.of('connections').filter((t) => t.link).length}</span>
            <AddDialog kind="connections" spaceId={SPACE_ID} share={share} connections={new Map()} now="2026-11-22T00:00:00.000Z" onAt={() => undefined} open={() => undefined} ask={() => undefined} rename={async () => undefined} onClose={() => undefined} />
        </>
    );
}

it('shares an account connected in the app with a space by its `credential:` ref, never the named one of its name', async () => {
    const fake = world();
    render(
        <WorkProviders client={fake.client}>
            <Adding />
            <Toaster />
        </WorkProviders>
    );
    const dialog = await screen.findByTestId('add-from-account');
    fireEvent.click((await within(dialog).findByText(`anthropic · ${APP_KEY.account}`)).closest('button')!);
    fireEvent.click(within(dialog).getByRole('button', { name: 'Add to this space' }));

    const shared = () => fake.requests.filter((r) => r.method === 'POST' && r.path === `/v1/workspaces/${SPACE_ID}/resources`).map((r) => r.body as Json);
    await waitFor(() => expect(shared()).toHaveLength(1));
    expect(shared()[0]).toMatchObject({ kind: 'connection', ref: APP_KEY.id });
    expect(namedOnThePlatform(String(shared()[0].ref), await listed(fake))).toMatchObject({ origin: 'app', account: APP_KEY.account });
});

it('never offers a named connection already shared with the space, whose link names it by its id', async () => {
    const fake = world();
    // Shared by its name before: the platform's link keeps the connection's id (`workspaces.resources.share`).
    await share(fake.client, SPACE_ID, 'connection', APP_KEY.name);
    render(
        <WorkProviders client={fake.client}>
            <Adding />
            <Toaster />
        </WorkProviders>
    );
    await waitFor(() => expect(screen.getByTestId('shared-here').textContent).toBe('1'));
    const dialog = await screen.findByTestId('add-from-account');
    // The app's key of that name is another account, still to add.
    await within(dialog).findByText(`anthropic · ${APP_KEY.account}`);
    expect(within(dialog).queryByText(`anthropic · ${NAMED_KEY_ACCOUNT}`)).toBeNull();

    // Everything still offered is added, none refused as shared already.
    const offered = within(dialog).getAllByRole('button', { pressed: false });
    expect(offered).toHaveLength((await listed(fake)).length - 1);
    for (const row of offered) fireEvent.click(row);
    fireEvent.click(within(dialog).getByRole('button', { name: 'Add to this space' }));
    expect(await screen.findByText(`${offered.length} added to this space`)).toBeTruthy();
    expect(screen.queryByText(/^Couldn’t add/)).toBeNull();
    const links = (await Workspace.fromId(SPACE_ID, { client: fake.client, user: null }).resources()).map((r) => String(r.raw.ref));
    expect([...links].sort()).toEqual((await listed(fake)).map((c) => String(c.id)).sort());
});
