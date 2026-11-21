// @vitest-environment happy-dom
// What an agent is saved with names its account by the ref the platform resolves: a named connection by its name, an
// account connected in the app by `credential:<id>`, never one rule for the other. An account connected from Work,
// where no host fills the connect slots, is a named connection the standard makes (its connect page on NoClick), so an
// agent given it with `credential:` in front of its id pointed at no account (an app's tools refused, a model's account
// never picked); and an app event heard through an account connected in the app goes by its `credential:` ref, never
// its name.
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { Agent, Connection } from 'noclick';
import { Toaster } from 'sonner';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { fill } from '@/slots';
import { CONNECTION_MARK } from '@/ui/slots';
import { WorkProviders } from './agents/fixtures/providers';
import { fakeWork, id } from './agents/fixtures/workAgents';
import { AgentConversation } from './conversation/AgentConversation';
import { AGENT_ID, fakeWorkAgent, settingsFor } from './conversation/fixtures/workAgent';
import { APPS } from './slots';
import { ToolsPanel } from './tools/ToolsPanel';
import { TriggersTab } from './triggers/TriggersTab';

type Json = Record<string, unknown>;

// The one app this test offers an agent: Linear, whose account it connects.
fill(APPS, { useToolApps: () => [{ value: 'automation-linear', label: 'Linear', acceptedCredentialTypes: ['linear_oauth'] }], serviceOf: () => undefined });
// The AI company an Anthropic account is with, as a host that knows it names it.
fill(CONNECTION_MARK, { ...CONNECTION_MARK.standard, aiCompany: (type) => (type.startsWith('agent_anthropic') || type === 'agent_claude_code_oauth' ? 'Claude' : undefined) });

beforeEach(() => {
    // Nothing real is called: the reads beside the views find nothing, and the connect page's tab opens nowhere.
    vi.stubGlobal('fetch', async () => new Response(null, { status: 404 }));
    vi.spyOn(window, 'open').mockImplementation(() => null);
});
afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
});

/** The connection a ref names in the account's own scope, by the platform's rule for an agent's tools, its model
 *  connection and an app event's trigger: `credential:<id>` names only an account connected in the app, by its id,
 *  never a named connection by its own id or its credential's (the API refuses that, naming the connection it meant);
 *  any other ref names a connection by its name. A tool's operation follows the first dot. */
function namedOnThePlatform(ref: string, connections: readonly Json[]): Json | undefined {
    const name = ref.split('.')[0];
    if (name.startsWith('credential:')) return connections.find((c) => c.origin === 'app' && c.id === name);
    return connections.find((c) => c.origin !== 'app' && c.name === name);
}

/** The agent's PATCHes, as sent. */
const patches = (fake: ReturnType<typeof fakeWorkAgent>) => fake.requests.filter((r) => r.method === 'PATCH' && r.path === `/v1/agents/${AGENT_ID}`).map((r) => r.body as Json);
const made = (fake: ReturnType<typeof fakeWorkAgent>) => fake.requests.filter((r) => r.method === 'POST' && r.path === '/v1/connections').map((r) => r.body as Json);

it('gives an agent the app whose account it connects by the connection’s name, the ref its tools resolve', async () => {
    const fake = fakeWorkAgent({ agent: { tools: [] }, connections: [] });
    const agent = await Agent.get(AGENT_ID, { client: fake.client });
    render(
        <WorkProviders client={fake.client}>
            <ToolsPanel agent={agent} name="Wirefern" conversation="main" onClose={() => undefined} />
            <Toaster />
        </WorkProviders>
    );
    fireEvent.click(await screen.findByRole('button', { name: 'Add an app or tool' }));
    fireEvent.click(await waitFor(() => screen.getByTestId('tool-offers').querySelector<HTMLElement>('[data-offer="automation-linear"]')!));
    const dialog = await screen.findByRole('dialog', { name: 'Connect Linear' });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Connect on NoClick' }));

    // The standard makes a named connection of Linear's, waiting for its account at its connect page.
    await waitFor(() => expect(made(fake)).toHaveLength(1));
    expect(made(fake)[0]).toMatchObject({ integration: 'linear', credential_type: 'linear_oauth' });
    expect(patches(fake)).toEqual([]);
    const connection = fake.connectAccount('rowan@wirefern.test');

    await waitFor(() => expect(patches(fake)).toHaveLength(1));
    const [ref] = patches(fake)[0].tools as string[];
    expect(patches(fake)[0].tools).toEqual([connection.name]);
    expect(namedOnThePlatform(ref, fake.connections)).toBe(connection);
    expect(await screen.findByText('Linear added')).toBeTruthy();
});

it('runs an agent on the AI account it connects by the connection’s name, the ref its model connection resolves', async () => {
    const onSdk = settingsFor('main', { harness: 'sdk', model: 'claude-sonnet-5-5', model_connection: null, efforts: ['low', 'medium', 'high'], effort: 'medium', speeds: [], speed: null, permission_modes: [] });
    const fake = fakeWorkAgent({ agent: { name: 'WhatsApp', harness: 'sdk', model: 'claude-sonnet-5-5', model_connection: null }, settings: { main: onSdk }, connections: [] });
    render(
        <WorkProviders client={fake.client}>
            <AgentConversation agentId={AGENT_ID} conversation="main" onOpenProfile={() => undefined} onOpenMachine={() => undefined} />
            <Toaster />
        </WorkProviders>
    );
    // Claude Code on Sonnet 5.5, which no account of yours runs yet.
    fireEvent.click(await screen.findByRole('button', { name: /^Model: / }));
    fireEvent.click((await screen.findByLabelText('Harnesses')).querySelector<HTMLElement>('[data-rail="claude_code"]')!);
    fireEvent.click(await within(await screen.findByRole('listbox', { name: 'Models' })).findByText('Sonnet 5.5'));
    const dialog = await screen.findByRole('dialog', { name: 'Connect Claude' });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Connect on NoClick' }));

    await waitFor(() => expect(made(fake)).toHaveLength(1));
    expect(made(fake)[0]).toMatchObject({ integration: 'anthropic' });
    expect(patches(fake)).toEqual([]);
    const connection = fake.connectAccount('rowan@wirefern.test');

    await waitFor(() => expect(patches(fake)).toHaveLength(1));
    expect(patches(fake)[0]).toEqual({ harness: 'claude_code', model: 'claude-sonnet-5-5', model_connection: connection.name });
    expect(namedOnThePlatform(String(patches(fake)[0].model_connection), fake.connections)).toBe(connection);
    expect(await screen.findByText('WhatsApp runs on Claude Code now')).toBeTruthy();
});

it('hears an app event through an account connected in the app by its `credential:` ref, never its name', async () => {
    const fake = fakeWork();
    const agent = await Agent.get(id(1), { client: fake.client });
    render(
        <WorkProviders client={fake.client}>
            <TriggersTab agent={agent} name={agent.name} phone={false} openId={null} onOpen={() => undefined} adding={{ kind: 'event', integration: 'whatsapp', event: 'message_received' }} onAdding={() => undefined} />
            <Toaster />
        </WorkProviders>
    );
    const add = await screen.findByRole('button', { name: 'Add trigger' });
    await waitFor(() => expect((add as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(add);

    const added = () => fake.requests.filter((r) => r.method === 'POST' && r.path === `/v1/agents/${id(1)}/triggers`).map((r) => r.body as Json);
    await waitFor(() => expect(added()).toHaveLength(1));
    expect(added()[0]).toMatchObject({ kind: 'event', connection: 'credential:c-wa', event: 'message_received' });
    const listed = (await Connection.list({ client: fake.client })).map((c) => c.raw as Json);
    expect(namedOnThePlatform(String(added()[0].connection), listed)).toMatchObject({ id: 'credential:c-wa', origin: 'app' });
});
