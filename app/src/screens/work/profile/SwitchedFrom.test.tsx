// @vitest-environment happy-dom
// An agent's facts while a plan's limit has it on another connection, over the fake /v1 through the real SDK: under
// its model, one line saying what it's on, until when (on the reader's clock), and the plan it goes back on; nothing
// once it's back.
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { Agent } from 'noclick';
import { WorkProviders } from '../agents/fixtures/providers';
import { AGENT_ID, fakeWorkAgent } from '../conversation/fixtures/workAgent';
import { AgentFacts } from './facts';

type Json = Record<string, unknown>;
// Tuesday 17 November 2026, 11:00 in the runner's own zone.
const NOW = new Date(2026, 10, 17, 11, 0, 0);

const CONNECTIONS: Json[] = [
    { object: 'connection', id: 'conn-work', name: 'work', integration: 'anthropic', credential_type: 'agent_claude_code_oauth', connected: true, status: 'connected', origin: 'api' },
    { object: 'connection', id: 'conn-personal', name: 'personal', integration: 'anthropic', credential_type: 'agent_claude_code_oauth', connected: true, status: 'connected', origin: 'api' },
];

beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(NOW);
    vi.stubGlobal('fetch', async () => new Response(null, { status: 404 }));
});
afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.useRealTimers();
});

async function facts(agent: Json) {
    const fake = fakeWorkAgent({ connections: CONNECTIONS, agent: { model_connection: 'personal', ...agent } });
    const read = await Agent.get(AGENT_ID, { client: fake.client });
    render(
        <WorkProviders client={fake.client}>
            <AgentFacts agent={read} conversation="main" triggers={[]} onMachine={() => undefined} onTriggers={() => undefined} />
        </WorkProviders>
    );
}

it('says what it’s on until the reset, then the plan it goes back on, under its model', async () => {
    await facts({ switched_from: { connection: 'work', name: 'work', window: 'five_hour', resets_at: new Date(2026, 10, 17, 15, 20).toISOString() } });
    const line = await screen.findByTestId('switched-from');
    await waitFor(() => expect(line.textContent).toBe('On your personal Claude plan until 3:20 PM, then back on your work Claude plan'));
    await waitFor(() => expect(line.closest('dd')?.textContent).toBe('Opus 5.5 · your Claude plan · personalOn your personal Claude plan until 3:20 PM, then back on your work Claude plan'));
});

it('says nothing of a switch once it’s back on its own', async () => {
    await facts({ switched_from: null, model_connection: 'work' });
    await waitFor(() => expect(screen.getByTestId('agent-facts').textContent).toContain('your Claude plan · work'));
    expect(screen.queryByTestId('switched-from')).toBeNull();
});
