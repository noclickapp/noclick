// @vitest-environment happy-dom
// Moving an agent to another harness from its conversation's model picker, over the fake /v1 through the real SDK. The
// account it runs on there is picked for you: the one of yours that runs it with no question, a choice in the picker
// where several do, and the connect popup where none does, the move made once what it connects lands. A refusal says
// what it needs in plain words, never the platform's own text or a harness's id.
import { useState } from 'react';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { Toaster } from 'sonner';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { fill } from '@/slots';
import { clickAsDrawn } from '@/lib/clickAsDrawn';
import { WorkProviders } from '../agents/fixtures/providers';
import { useHarnessSwitch } from '../agents/harnessSwitch';
import { useAgents } from '../agents/reads';
import { useHarnesses, useModelAccounts } from '../newAgent/catalog';
import { CONNECT_MODEL } from '../slots';
import { CONNECTION_MARK } from '@/ui/slots';
import { AgentConversation } from './AgentConversation';
import { AGENT_ID, CONNECTIONS, fakeWorkAgent, settingsFor } from './fixtures/workAgent';

// The connect popup as the picker opens it (the `work.connect.model` slot): its title, and a sign-in that lands the
// account it was opened for. It opens on the Claude plan's way, the one account this test's company has.
const signIn = { landed: 'cred-1' };
fill(CONNECT_MODEL, ({ credentialType, title, onConnected }) =>
    credentialType && ['agent_anthropic', 'agent_claude_code_oauth'].includes(credentialType) ? (
        <div role="dialog" aria-label={title}>
            <h2>{title}</h2>
            <button type="button" onClick={() => onConnected(signIn.landed)}>
                Sign in with Claude
            </button>
        </div>
    ) : null
);

// The AI company an Anthropic key is with, as a host that knows it names it.
fill(CONNECTION_MARK, { ...CONNECTION_MARK.standard, aiCompany: (type) => (type === 'agent_anthropic' ? 'Claude' : undefined) });

// Nothing real is called: the reads beside the conversation (the session, the instance's capabilities) find nothing.
beforeEach(() => vi.stubGlobal('fetch', async () => new Response(null, { status: 404 })));
afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
});

/** A WhatsApp agent on NoClick's own runtime, as Rowan's was. */
const WHATSAPP = { name: 'WhatsApp', harness: 'sdk', model: 'claude-sonnet-5-5', model_connection: null };
const ON_SDK = settingsFor('main', { harness: 'sdk', model: 'claude-sonnet-5-5', model_connection: null, efforts: ['low', 'medium', 'high'], effort: 'medium', speeds: [], speed: null, permission_modes: [] });
const CLAUDE_KEY = { object: 'connection', id: 'conn-2', name: 'claude-key', integration: 'anthropic', credential_type: 'agent_anthropic', connected: true, status: 'connected' };

function show(fake: ReturnType<typeof fakeWorkAgent>) {
    render(
        <WorkProviders client={fake.client}>
            <AgentConversation agentId={AGENT_ID} conversation="main" onOpenProfile={() => undefined} onOpenMachine={() => undefined} />
            <Toaster />
        </WorkProviders>
    );
}

/** The agent's PATCHes, as sent. */
const moves = (fake: ReturnType<typeof fakeWorkAgent>) => fake.requests.filter((r) => r.method === 'PATCH' && r.path === `/v1/agents/${AGENT_ID}`).map((r) => r.body);

/** Opens the box's model picker on Claude Code's models and picks Sonnet 5.5. */
async function pickClaudeCode() {
    fireEvent.click(await screen.findByRole('button', { name: /^Model: / }));
    const rail = await screen.findByLabelText('Harnesses');
    const claude = rail.querySelector<HTMLElement>('[data-rail="claude_code"]')!;
    // Every harness can be picked from an agent's own box.
    expect(claude.getAttribute('aria-disabled')).toBeNull();
    expect(claude.getAttribute('aria-label')).toBe('Claude Code');
    fireEvent.click(claude);
    const list = await screen.findByRole('listbox', { name: 'Models' });
    fireEvent.click(await within(list).findByText('Sonnet 5.5'));
}

it('moves to Claude Code on the one account of yours that runs it, asking nothing', async () => {
    const fake = fakeWorkAgent({ agent: WHATSAPP, settings: { main: ON_SDK } });
    show(fake);
    await pickClaudeCode();

    await waitFor(() => expect(moves(fake)).toEqual([{ harness: 'claude_code', model: 'claude-sonnet-5-5', model_connection: 'anthropic-plan' }]));
    expect(screen.queryByTestId('account-choice')).toBeNull();
    expect(screen.queryByRole('dialog', { name: 'Connect Claude' })).toBeNull();
    expect(await screen.findByText('WhatsApp runs on Claude Code now')).toBeTruthy();
    expect(screen.getByText('Same conversation: its next turn picks it up on Claude Code.')).toBeTruthy();
    // The box's pill (Claude's mark) and the header follow the agent.
    await waitFor(() => expect(screen.getByRole('button', { name: /^Model: Sonnet 5\.5/ }).querySelector('svg')?.getAttribute('class')).toContain('text-[#D97757]'));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Runs on Claude Code' })).toBeTruthy());
});

it('asks in the picker which account it runs on where several of yours do', async () => {
    const fake = fakeWorkAgent({ agent: WHATSAPP, settings: { main: ON_SDK }, connections: [...CONNECTIONS, CLAUDE_KEY] });
    show(fake);
    await pickClaudeCode();

    const choice = await screen.findByTestId('account-choice');
    expect(choice.getAttribute('aria-label')).toBe('Run Claude Code on');
    const options = within(choice).getAllByRole('button').filter((b) => b.getAttribute('aria-label') !== 'Back to the models');
    expect(options.map((b) => b.textContent)).toEqual(['Claude planSigned in', 'Claude keyKey saved']);
    expect(moves(fake)).toEqual([]);
    fireEvent.click(options[1]);
    await waitFor(() => expect(moves(fake)).toEqual([{ harness: 'claude_code', model: 'claude-sonnet-5-5', model_connection: 'claude-key' }]));
    expect(await screen.findByText('WhatsApp runs on Claude Code now')).toBeTruthy();
});

it('opens the connect step where none of yours runs it, and moves once the account lands', async () => {
    const fake = fakeWorkAgent({ agent: WHATSAPP, settings: { main: ON_SDK }, connections: [] });
    show(fake);
    await pickClaudeCode();

    const dialog = await screen.findByRole('dialog', { name: 'Connect Claude' });
    expect(moves(fake)).toEqual([]);
    // The sign-in lands: the app saves it as a credential the account's connections list.
    fake.connections.push({ object: 'connection', id: 'credential:cred-1', name: 'Claude', origin: 'app', integration: 'anthropic', credential_type: 'agent_claude_code_oauth', connected: true, status: 'connected' });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Sign in with Claude' }));
    await waitFor(() => expect(moves(fake)).toEqual([{ harness: 'claude_code', model: 'claude-sonnet-5-5', model_connection: 'credential:cred-1' }]));
    expect(await screen.findByText('WhatsApp runs on Claude Code now')).toBeTruthy();
});

it('says why a move was refused in plain words, never the platform’s text or a harness’s id', async () => {
    const raw = { type: 'invalid_request', message: "claude_code needs a model connection, the connection holding its model's key.", field: 'model_connection', next_step: 'POST /v1/connections {name, integration, use_for: {agent, harness: "claude_code"}}' };
    const fake = fakeWorkAgent({
        agent: WHATSAPP,
        settings: { main: ON_SDK },
        refuseUpdate: (body) => (body.harness ? new Response(JSON.stringify({ error: raw }), { status: 400, headers: { 'Content-Type': 'application/json' } }) : undefined),
    });
    show(fake);
    await pickClaudeCode();

    const title = await screen.findByText('WhatsApp stays on NoClick’s own agent');
    const toast = title.closest('[data-sonner-toast]') as HTMLElement;
    expect(toast.textContent).toContain('Your Claude plan can’t run that model on Claude Code. Pick another model, or connect a Claude plan or a Claude key.');
    expect(toast.textContent).not.toMatch(/claude_code|model connection|POST \/v1/);
    // It stays where it was.
    await waitFor(() => expect(screen.getByRole('button', { name: 'Runs on NoClick’s own agent' })).toBeTruthy());
});

it('keeps the choice of account a move asks for as the agent is read, the picker open', async () => {
    // The box's picker can be open before the agent is read (its settings come first). A harness picked the moment the
    // agent arrives, before that render's effects ran, still asks which account runs it: the hook put the choice down
    // in an effect, which took it back unless the page happened to run its effects at once.
    const fake = fakeWorkAgent({ agent: WHATSAPP, settings: { main: ON_SDK }, connections: [...CONNECTIONS, CLAUDE_KEY] });
    let arrive = () => undefined as void;
    function Picker() {
        const agents = useAgents();
        const harnesses = useHarnesses();
        const { accounts } = useModelAccounts();
        const [read, setRead] = useState(false);
        arrive = () => setRead(true);
        const agent = read ? (agents.data?.find((a) => a.id === AGENT_ID) ?? null) : null;
        const moves = useHarnessSwitch(agent);
        return (
            <>
                {agents.data && harnesses.data && accounts && <p>Accounts read</p>}
                {agent && (
                    <button type="button" onClick={() => moves.start({ harness: 'claude_code' })}>
                        Claude Code
                    </button>
                )}
                {moves.choosing && <p data-testid="choosing">{moves.choosing.accounts.map((a) => a.id).join(', ')}</p>}
            </>
        );
    }
    render(
        <WorkProviders client={fake.client}>
            <Picker />
        </WorkProviders>
    );
    await screen.findByText('Accounts read', undefined, { timeout: 5000 });
    const click = clickAsDrawn(() => screen.queryByRole('button', { name: 'Claude Code' }));
    arrive();
    await waitFor(() => expect(click.clicked()).toBe(true), { timeout: 5000 });
    expect((await screen.findByTestId('choosing')).textContent).toBe('anthropic-plan, claude-key');
    expect(moves(fake)).toEqual([]);
});
