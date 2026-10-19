// @vitest-environment jsdom
// A builder bridge link (/b/{linkId}) says what it asks: its preview in a chat (the route's meta, from a loader that
// reads the link on the server) and the page's heading name the accounts to connect or the questions to answer, the
// page reads right to the person NoClick asked and to anyone they sent it on to, and a closed link says so.
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { BuilderBridge, type BridgeInput, type BridgePayload, type BridgeTransport } from '~/components/bridge/BuilderBridge';
import { bridgeAsk } from '~/components/bridge/bridgeAsk';
import * as BridgeRoute from '~/routes/b.$linkId';

afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
});

const account = (credential_type: string, description?: string): BridgeInput => ({
    id: credential_type,
    label: 'Which account?',
    description,
    required: true,
    type: 'credential',
    credential_type,
    credential_provide_token: 'token',
    credential_fulfilled: true,
});
const question = (id: string): BridgeInput => ({ id, label: `What ${id}?`, required: true, type: 'text' });
const link = (...inputs: BridgeInput[]): BridgePayload => ({ workflow_name: 'Reviews agent', expires_at: '2026-10-15T00:00:00Z', inputs });

it('names the accounts a link asks to connect, and says why when the ask does', () => {
    expect(bridgeAsk(link(account('google_business_profile_oauth', 'So the agent can read reviews and reply.')))).toEqual({
        title: 'Connect Google Business Profile',
        heading: 'Connect your Google Business Profile',
        description: 'So the agent can read reviews and reply.',
        accountsOnly: true,
    });
    expect(bridgeAsk(link(account('google_business_profile_oauth'), account('gmail_oauth'))).title).toBe('Connect Google Business Profile and Gmail');
});

it('counts the questions otherwise, for the workflow they finish', () => {
    expect(bridgeAsk(link(question('tone'), question('hours')))).toEqual({
        title: 'Answer 2 questions for “Reviews agent”',
        heading: 'Answer 2 questions for “Reviews agent”',
        description: 'NoClick needs this to finish “Reviews agent”.',
        accountsOnly: false,
    });
    expect(bridgeAsk(link(account('gmail_oauth'), question('tone'))).heading).toBe('Connect your Gmail and answer a question');
});

it('says a closed link is no longer open', () => {
    expect(bridgeAsk(null).title).toBe('This link is no longer open');
});

it('unfurls an open link to what it asks, a closed one as closed, and an unreadable one plainly', async () => {
    const respond = (status: number, body?: unknown) => vi.stubGlobal('fetch', vi.fn(async () => new Response(body ? JSON.stringify(body) : null, { status })));
    const load = () => BridgeRoute.loader({ params: { linkId: 'abc' } } as never);
    const og = (data: Awaited<ReturnType<typeof load>>) =>
        Object.fromEntries((BridgeRoute.meta({ data } as never) as { property?: string; content?: string }[]).filter((t) => t.property).map((t) => [t.property, t.content]));

    respond(200, link(account('google_business_profile_oauth', 'So the agent can read reviews and reply.')));
    const open = await load();
    expect(og(open)['og:title']).toBe('Connect Google Business Profile');
    expect(og(open)['og:description']).toBe('So the agent can read reviews and reply.');
    expect(Object.keys(open).sort()).toEqual(['description', 'title']);

    respond(404, { detail: 'This link is invalid, answered, or expired' });
    expect((await load()).title).toBe('This link is no longer open');

    respond(502);
    expect((await load()).title).toBe('NoClick needs something from you');
    // A capability URL: never kept in a shared cache.
    expect(BridgeRoute.headers()['Cache-Control']).toBe('no-store');
});

const transport = (payload: BridgePayload, submitted = vi.fn()): BridgeTransport => ({
    apiBase: '',
    load: async () => payload,
    submit: async () => submitted(),
    reconnect: async () => {},
});

it('asks the person in their own words, whoever opened it, and confirms what happens next', async () => {
    render(<BuilderBridge transport={transport(link(account('google_business_profile_oauth')))} />);
    expect(await screen.findByRole('heading', { name: 'Connect your Google Business Profile' })).toBeTruthy();
    expect(screen.getByText('NoClick is building “Reviews agent” and needs this to finish it. You don’t need an account.')).toBeTruthy();
    expect(screen.queryByText(/Whoever sent you/)).toBeNull();
    expect(screen.queryByText(/Step 1 of 1/)).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: /Continue/ }));
    expect(await screen.findByText('Connected')).toBeTruthy();
    expect(screen.getByText(/NoClick is finishing “Reviews agent”/)).toBeTruthy();
});

it('sends answers to questions, and says a link it cannot open is closed', async () => {
    render(<BuilderBridge transport={transport(link(question('tone')))} />);
    expect(await screen.findByRole('heading', { name: 'Answer a question for “Reviews agent”' })).toBeTruthy();
    expect(screen.getByRole('button', { name: /Send answers/ })).toBeTruthy();
    cleanup();

    render(<BuilderBridge transport={{ ...transport(link()), load: async () => Promise.reject(new Error('This link is invalid, answered, or expired')) }} />);
    expect(await screen.findByRole('heading', { name: 'This link can’t be opened' })).toBeTruthy();
    expect(screen.getByText('This link is invalid, answered, or expired')).toBeTruthy();
});
