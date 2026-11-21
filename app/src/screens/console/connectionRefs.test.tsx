// @vitest-environment happy-dom
// The console names an agent's connection by the ref the platform resolves: a connection made through the API by
// its name, an account connected in the NoClick app by `credential:<id>`. The account's own scope lists both, so an
// account agent's event trigger, tools and model connection saved an app account by its name, which names no
// connection (the API refuses it) or, where a connection has that name, another account. What an agent already holds
// by `credential:<id>` reads as that account, never as a connection that was deleted.
import { cleanup, configure, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { DEFAULT_BASE_URL, NoClick } from 'noclick';
import { MemoryRouter, Route, Routes, useParams } from 'react-router';
import { afterEach, expect, it, vi } from 'vitest';
import { DeveloperConsole } from './DeveloperConsole';
import { AGENTS, FIXTURE_NOW, FIXTURE_NOW_MS, FIXTURE_USER, apiError, fixtureId, ok, type FixtureReply, type FixtureRequest, type FixtureRoute } from './fixtures/core';
import { makeFixtureFetch } from './fixtures/fixtureFetch';

type Json = Record<string, unknown>;

// Each wait is on the page's own state; a full parallel run can take longer than a second to load a page's code.
configure({ asyncUtilTimeout: 10_000 });
vi.setConfig({ testTimeout: 30_000 });
afterEach(cleanup);

const BASE = '/developers';
/** An account agent on NoClick's own loop, and one on Claude Code thinking with a model provider's connection. */
const SUPPORT = AGENTS[0];
const CODER = AGENTS.find((a) => a.name === 'coder')!;
/** One of Acme's own agents, in Acme's scope. */
const ACMES = AGENTS.find((a) => a.name === 'assistant' && a.user_id === 'acme')!;

/** An account connected in the app, as `GET /v1/connections` lists it in the account's own scope. */
const inTheApp = (credential: string, fields: Json): Json => ({
    object: 'connection',
    id: `credential:${credential}`,
    origin: 'app',
    user_id: null,
    status: 'connected',
    verification: null,
    connect_link: null,
    connected_at: FIXTURE_NOW,
    created_at: FIXTURE_NOW,
    updated_at: FIXTURE_NOW,
    ...fields,
});
const APP_SLACK = inTheApp(fixtureId(6, 140), { name: 'Slack', integration: 'slack', credential_type: 'slack_oauth', account: 'ops@yourco.test' });
const APP_ANTHROPIC = inTheApp(fixtureId(6, 141), { name: 'Anthropic key', integration: 'anthropic', credential_type: 'agent_anthropic' });
const IN_THE_APP = [APP_SLACK, APP_ANTHROPIC];

/** The connection a ref names in the account's own scope, by the platform's rule for an event trigger's connection
 *  (`connect.connections_named`), an agent's tools (`resolve_refs`) and its model connection (`scope_connection`):
 *  `credential:<id>` names an account connected in the app by its id, and any other ref a named connection by its
 *  name, never an app account by its name. A tool's operation follows the first dot. */
function namedOnThePlatform(ref: string, connections: readonly Json[]): Json | undefined {
    const name = ref.split('.')[0];
    if (name.startsWith('credential:')) return connections.find((c) => c.origin === 'app' && c.id === name);
    return connections.find((c) => c.origin !== 'app' && c.name === name);
}

/** The console over the fixtures, with the account's app accounts listed beside its named connections, as the API
 *  lists them, and the requests it made. `holding` changes what an agent is read with; `lab` draws what's designed. */
function open(address: string, holding: Record<string, Json> = {}, lab = false) {
    const plain = makeFixtureFetch({ set: 'populated' });
    const asPlain = async (r: FixtureRequest): Promise<{ status: number; body: Json }> => {
        const answer = await plain(`${DEFAULT_BASE_URL}${r.path}?${r.query}`, { method: r.method, headers: r.headers, body: r.body ? JSON.stringify(r.body) : undefined });
        return { status: answer.status, body: (await answer.json()) as Json };
    };
    const held = new Map(Object.entries(holding));
    let added = 0;
    const sent: { method: string; path: string; body: Json }[] = [];
    // Every connection the account's own scope holds: the named ones the fixtures list, then the app's.
    const connections = async (): Promise<Json[]> => ((await asPlain({ method: 'GET', path: '/v1/connections', query: new URLSearchParams({ user_id: 'none' }), headers: new Headers(), params: {}, body: null, set: 'populated' })).body.data as Json[]).concat(IN_THE_APP);
    const agent = async (r: FixtureRequest): Promise<FixtureReply> => {
        const { status, body } = await asPlain({ ...r, method: 'GET', body: null });
        return status === 200 ? ok({ ...body, ...held.get(r.params.id) }) : { status, body };
    };
    const routes: FixtureRoute[] = [
        {
            method: 'GET',
            path: '/v1/connections',
            reply: async (r) => {
                const { status, body } = await asPlain(r);
                const scope = r.query.get('user_id') ?? r.headers.get('NoClick-User') ?? 'none';
                const accountScope = scope === 'none' || scope === 'all';
                return status === 200 && accountScope ? ok({ ...body, data: [...(body.data as Json[]), ...IN_THE_APP] }) : { status, body };
            },
        },
        {
            method: 'GET',
            path: '/v1/integrations/:name/events',
            reply: (r) => ok({ object: 'list', data: [{ name: `${r.params.name}_message`, description: null, filters: {}, shape: null, sample: null }], next_cursor: null }),
        },
        { method: 'GET', path: '/v1/agents/:id', reply: agent },
        {
            method: 'GET',
            path: '/v1/agents',
            reply: async (r) => {
                const { status, body } = await asPlain(r);
                return status === 200 ? ok({ ...body, data: (body.data as Json[]).map((a) => ({ ...a, ...held.get(String(a.id)) })) }) : { status, body };
            },
        },
        {
            method: 'PATCH',
            path: '/v1/agents/:id',
            reply: async (r) => {
                held.set(r.params.id, { ...held.get(r.params.id), ...(r.body as Json) });
                return agent(r);
            },
        },
        {
            method: 'POST',
            path: '/v1/agents/:id/triggers',
            reply: async (r) => {
                const { kind, ...spec } = r.body as Json;
                // The API's words for a ref that names no connection (`triggers.service.compile_source`).
                const through = kind === 'event' ? namedOnThePlatform(String(spec.connection), await connections()) : undefined;
                if (kind === 'event' && !through) return apiError(404, 'not_found', `The account has no connection named '${String(spec.connection)}'.`);
                // An app event says what it hears through, as `triggers.service._source` does.
                const summary = through ? { app: through.integration, integration: through.integration, icon: null, credential_type: through.credential_type, account: through.account ?? null, number: null, hears: null, groups: null, status: 'connected', problem: null, remedy: null } : null;
                return { status: 201, body: { object: 'agent_trigger', id: fixtureId(3, 190 + ++added), kind, spec, title: null, summary, status: 'active', url: null, next_run: null, last_fired_at: null, error: null, created_at: FIXTURE_NOW } };
            },
        },
    ];
    const answer = makeFixtureFetch({ set: 'populated', routes, onRequest: (r) => r.method !== 'GET' && sent.push({ method: r.method, path: r.path, body: (r.body ?? {}) as Json }) });
    const client = new NoClick({ apiKey: 'a-fixture-holds-no-key', baseUrl: DEFAULT_BASE_URL, maxRetries: 0, fetch: answer });
    function Mounted() {
        return (
            <DeveloperConsole
                section={useParams()['*']}
                client={client}
                actsAs="owner"
                basePath={BASE}
                apiUrl="https://api.noclick.com"
                site="https://noclick.com"
                home="/"
                user={FIXTURE_USER}
                now={() => FIXTURE_NOW_MS}
                onSignOut={() => undefined}
                live={null}
                lab={lab}
            />
        );
    }
    render(
        <MemoryRouter initialEntries={[`${BASE}/${address}`]}>
            <Routes>
                <Route path={`${BASE}/*`} element={<Mounted />} />
            </Routes>
        </MemoryRouter>
    );
    return { sent: (method: string, path: string) => sent.filter((s) => s.method === method && s.path === path).map((s) => s.body), connections };
}

/** A `<select>`'s option by what it shows, chosen as a person would. */
function choose(select: HTMLSelectElement, text: string) {
    const option = [...select.options].find((o) => o.text.trim().startsWith(text));
    if (!option) throw new Error(`No option "${text}" in ${[...select.options].map((o) => o.text).join(', ')}`);
    fireEvent.change(select, { target: { value: option.value } });
}

/** A dialog's select by its label; throws while the field is something else (a text box until its options load). */
function fieldSelect(dialog: HTMLElement, label: string): HTMLSelectElement {
    const field = within(dialog).getByLabelText(label);
    if (!(field instanceof HTMLSelectElement)) throw new Error(`${label} is no select yet`);
    return field;
}

it('hears an app event through an account connected in the app by its `credential:` ref, and a named one by its name', async () => {
    const console_ = open(`agents/${SUPPORT.id}`);
    const triggers = `/v1/agents/${SUPPORT.id}/triggers`;
    for (const [shown, connection] of [
        ['Slack', APP_SLACK],
        ['gmail', null],
    ] as const) {
        fireEvent.click(await screen.findByRole('button', { name: 'Add trigger' }));
        const dialog = await screen.findByRole('dialog', { name: 'Add a trigger' });
        fireEvent.click(within(dialog).getByRole('button', { name: 'App event' }));
        const select = fieldSelect(dialog, 'Connection');
        await waitFor(() => expect(select.options.length).toBeGreaterThan(1));
        choose(select, shown);
        // Its app's events are read once it's picked.
        choose(await waitFor(() => fieldSelect(dialog, 'Event')), `${connection ? 'slack' : 'gmail'}_message`);
        fireEvent.click(within(dialog).getByRole('button', { name: 'Add trigger' }));
        await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Add a trigger' })).toBeNull());
    }
    const [app, named] = console_.sent('POST', triggers);
    expect(app).toMatchObject({ kind: 'event', connection: APP_SLACK.id, event: 'slack_message' });
    expect(namedOnThePlatform(String(app.connection), await console_.connections())).toBe(APP_SLACK);
    expect(named).toMatchObject({ kind: 'event', connection: 'gmail', event: 'gmail_message' });
    expect(namedOnThePlatform(String(named.connection), await console_.connections())).toMatchObject({ name: 'gmail', user_id: null });
    // Each reads as what it hears through: the app account as its account, never its id.
    const listed = screen.getByRole('list', { name: 'Triggers' });
    expect(within(listed).getByText(/ops@yourco\.test sends slack_message/)).toBeTruthy();
    expect(within(listed).getByText(/gmail sends gmail_message/)).toBeTruthy();
    expect(listed.textContent).not.toContain(APP_SLACK.id);
});

it('gives an agent an account connected in the app by its `credential:` ref, and lists that tool as the account', async () => {
    const console_ = open(`agents/${SUPPORT.id}`);
    fireEvent.click(await screen.findByRole('button', { name: 'Edit tools' }));
    const dialog = await screen.findByRole('dialog', { name: `${SUPPORT.name}'s tools` });
    const row = await within(dialog).findByText('Slack', { selector: 'span' });
    fireEvent.click(row.closest('label')!.querySelector('input')!);
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save tools' }));

    await waitFor(() => expect(console_.sent('PATCH', `/v1/agents/${SUPPORT.id}`)).toHaveLength(1));
    const tools = console_.sent('PATCH', `/v1/agents/${SUPPORT.id}`)[0].tools as string[];
    expect(tools).toEqual([...SUPPORT.tools, APP_SLACK.id]);
    expect(namedOnThePlatform(tools.at(-1)!, await console_.connections())).toBe(APP_SLACK);
    // Its tools now hold it, read as the account, never as a connection that was deleted.
    await waitFor(() => expect(screen.queryByRole('dialog', { name: `${SUPPORT.name}'s tools` })).toBeNull());
    const listed = screen.getByRole('list', { name: 'Tools' });
    await waitFor(() => expect(within(listed).getAllByText('Slack').length).toBeGreaterThan(0));
    expect(listed.textContent).not.toContain('No connection named');
    expect(listed.textContent).not.toContain(APP_SLACK.id);
});

it('runs an agent on a key connected in the app by its `credential:` ref, reads it as that key, and keeps it on a move', async () => {
    const console_ = open(`agents/${CODER.id}`);
    fireEvent.click(await screen.findByRole('button', { name: 'Edit model connection' }));
    choose(await screen.findByLabelText('Model connection'), 'Anthropic key');
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    const patched = `/v1/agents/${CODER.id}`;
    await waitFor(() => expect(console_.sent('PATCH', patched)).toHaveLength(1));
    expect(console_.sent('PATCH', patched)[0]).toEqual({ model_connection: APP_ANTHROPIC.id });
    expect(namedOnThePlatform(APP_ANTHROPIC.id as string, await console_.connections())).toBe(APP_ANTHROPIC);
    // It reads as the key it runs on.
    const about = screen.getByRole('region', { name: 'About' });
    await waitFor(() => expect(within(about).getByText('Anthropic key')).toBeTruthy());
    expect(about.textContent).not.toContain('no connection with this name');

    // OpenCode runs on an Anthropic key too, so the move keeps it.
    fireEvent.click(within(about).getByRole('button', { name: 'Edit where it runs' }));
    fireEvent.change(within(about).getByLabelText('Runs on'), { target: { value: 'opencode' } });
    expect((within(about).getByLabelText('Model connection') as HTMLSelectElement).value).toBe(APP_ANTHROPIC.id);
    fireEvent.click(within(about).getByRole('button', { name: 'Save' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Move to OpenCode' }));
    await waitFor(() => expect(console_.sent('PATCH', patched)).toHaveLength(2));
    expect(console_.sent('PATCH', patched)[1]).toEqual({ harness: 'opencode' });
});

it('reads a model connection an agent already holds by `credential:` as that key', async () => {
    open(`agents/${CODER.id}`, { [CODER.id]: { model_connection: APP_ANTHROPIC.id } });
    const about = await screen.findByRole('region', { name: 'About' });
    await waitFor(() => expect(within(about).getByText('Anthropic key')).toBeTruthy());
    expect(about.textContent).not.toContain('no connection with this name');
});

it('judges the operations of an account connected in the app that an agent holds when a policy draft changes', async () => {
    const console_ = open('settings/policy', { [SUPPORT.id]: { tools: [...SUPPORT.tools, APP_SLACK.id] } });
    const add = await screen.findByRole('textbox', { name: 'Add to Require approval' });
    fireEvent.change(add, { target: { value: 'slack.*' } });
    fireEvent.keyDown(add, { key: 'Enter' });

    // What the draft changes is read for every tool the account's agents reach: Slack's, through the app's account.
    await waitFor(() => expect(console_.sent('POST', '/v1/policy/evaluate').some((b) => (b.tools as string[]).includes('slack.send_message_to_channel'))).toBe(true));
    const judged = console_.sent('POST', '/v1/policy/evaluate').find((b) => (b.tools as string[]).includes('slack.send_message_to_channel'))!;
    expect(judged.tools).toEqual(expect.arrayContaining(['slack.send_message_to_channel', 'slack.list_channels']));
});

it('never offers a user’s agent an account connected in the app to share, which only the account’s own agents can hold', async () => {
    open(`agents/${ACMES.id}`, {}, true);
    fireEvent.click(await screen.findByRole('button', { name: 'Edit tools' }));
    const dialog = await screen.findByRole('dialog', { name: `${ACMES.name}'s tools` });
    fireEvent.click(within(dialog).getByRole('button', { name: "Share one of another user's connections, or your account's" }));
    // The account's own connections are offered (its Gmail among them), never one connected in the app.
    await within(dialog).findByText('Shared from other users or your account');
    expect(within(dialog).getAllByText('your account').length).toBeGreaterThan(0);
    expect(within(dialog).queryByText('Slack', { selector: 'span' })).toBeNull();
});
