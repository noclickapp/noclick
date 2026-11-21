// @vitest-environment happy-dom
// A space's Resources name each of the account's connections by the ref the platform resolves: a named connection by
// its name, an account connected in the NoClick app by `credential:<id>`. Named by its name, an app account shared
// with a space, given to one from home or deleted from home named no connection, or, where a named connection had its
// name, that other account: the one shared or deleted for good.
import { cleanup, fireEvent, render, renderHook, screen, waitFor, within } from '@testing-library/react';
import { Connection } from 'noclick';
import { Toaster } from 'sonner';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { WorkProviders } from '../../agents/fixtures/providers';
import { fakeWork, SPACE_ID } from '../../agents/fixtures/workAgents';
import { HOME_SPACE } from '../../place';
import { deletePath } from './actions';
import { useSpaceShare } from './data';
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

it('names each of home’s connections by its own ref, so deleting one deletes that account', async () => {
    const fake = world();
    const { result } = renderHook(() => useSpaceShare(HOME_SPACE), { wrapper: ({ children }) => <WorkProviders client={fake.client}>{children}</WorkProviders> });
    await waitFor(() => expect(result.current.of('connections').some((t) => t.ref === APP_KEY.id)).toBe(true));
    const connections = await listed(fake);
    const things = result.current.of('connections');
    // One row each, the app's key and the named connection of its name apart.
    expect(new Set(things.map((t) => t.key)).size).toBe(things.length);
    for (const t of things) expect(namedOnThePlatform(t.ref, connections)).toBeTruthy();
    const app = things.find((t) => t.ref === APP_KEY.id)!;
    expect(namedOnThePlatform(app.ref, connections)).toMatchObject({ origin: 'app', account: APP_KEY.account });
    expect(deletePath(app)).toBe(`/v1/connections/${encodeURIComponent(APP_KEY.id)}`);
    const named = things.find((t) => t.ref === APP_KEY.name)!;
    expect(namedOnThePlatform(named.ref, connections)).toMatchObject({ account: NAMED_KEY_ACCOUNT });
});

it('shares an account connected in the app with a space by its `credential:` ref, never the named one of its name', async () => {
    const fake = world();
    function Adding() {
        const share = useSpaceShare(SPACE_ID);
        return <AddDialog kind="connections" spaceId={SPACE_ID} share={share} connections={new Map()} now="2026-11-22T00:00:00.000Z" onAt={() => undefined} open={() => undefined} ask={() => undefined} rename={async () => undefined} onClose={() => undefined} />;
    }
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
