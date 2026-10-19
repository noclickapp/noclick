// @vitest-environment jsdom
// Settings → Usage where nobody is billed: one read of the page, its loading, failed and empty states, what each thing
// cost by service and inside one, and the charges read a page at a time, narrowed to what the drill picked.
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router';
import { afterEach, beforeAll, beforeEach, expect, it, vi } from 'vitest';

const { socketCall } = vi.hoisted(() => ({ socketCall: vi.fn() }));
vi.mock('~/lib/socketCall', () => ({ socketCall }));

import { UsagePage } from '~/components/usage/page/UsagePage';
import type { ChargeRow, UsagePageData } from '~/components/usage/page/types';

const NOW = '2026-10-16T15:20:00Z';
const ME = 'u-1';
const WF = 'wf-1';

function group(day: string, subtype: string, usd: number, extra: Record<string, unknown> = {}) {
    const usageType = subtype.startsWith('openrouter/') ? 'ai_usage' : 'api_usage';
    return {
        current: true,
        day,
        created_at: `${day}T09:00:00Z`,
        k: `${subtype}|${extra.workflow_id ?? ''}|${extra.node_id ?? ''}`,
        user_id: ME,
        usage_type: usageType,
        usage_subtype: subtype,
        unit_type: usageType === 'ai_usage' ? 'tokens' : 'requests',
        user_resource: false,
        n: 2,
        quantity: usageType === 'ai_usage' ? 20000 : 2,
        total_cost: usd,
        prompt_tokens: 0,
        completion_tokens: 0,
        ...extra,
    } as unknown as UsagePageData['groups'][number];
}

function charge(id: string, at: string, subtype: string, usd: number, k: string): ChargeRow {
    return { id, created_at: at, user_id: ME, organization_id: null, usage_type: subtype.startsWith('openrouter/') ? 'ai_usage' : 'api_usage', usage_subtype: subtype, quantity: 1000, unit_type: 'tokens', total_cost: usd, user_resource: false, metadata: { workflow_id: WF }, k };
}

function pageData(groups: UsagePageData['groups'], rows: ChargeRow[] = []): UsagePageData {
    return {
        now: NOW,
        account: { id: ME },
        period: { window_start: '2026-10-01T00:00:00Z', window_end: '2026-11-01T00:00:00Z', previous_start: '2026-09-01T00:00:00Z' },
        billing: null,
        groups,
        directory: { workflows: { [WF]: { name: 'Inbox triage' } }, agents: { [`${WF}:agent-1`]: { name: 'Support agent' } }, people: { [ME]: { name: 'Ada' } } },
        charges: { rows, runs: {}, next: null },
    };
}

const SONNET = 'openrouter/anthropic/claude-sonnet-4.6';
const MINI = 'openrouter/openai/gpt-4o-mini';
const BUSY = pageData(
    [
        group('2026-10-14', SONNET, 3.0, { workflow_id: WF, node_id: 'agent-1' }),
        group('2026-10-15', SONNET, 2.0, { workflow_id: WF, node_id: 'agent-1' }),
        group('2026-10-15', MINI, 1.0, { workflow_id: WF, node_id: 'agent-1' }),
        group('2026-10-15', 'exa/search_api', 0.5, { workflow_id: WF, node_id: 'agent-1' }),
    ],
    [charge('c-1', '2026-10-15T12:00:00Z', SONNET, 2.0, `${SONNET}|${WF}|agent-1`), charge('c-2', '2026-10-15T11:00:00Z', 'exa/search_api', 0.5, `exa/search_api|${WF}|agent-1`)]
);

let answer: (event: string, payload: Record<string, unknown>) => Promise<unknown>;

beforeAll(() => {
    globalThis.ResizeObserver ??= class {
        observe() {}
        unobserve() {}
        disconnect() {}
    } as unknown as typeof ResizeObserver;
    window.matchMedia ??= ((query: string) => ({ matches: false, media: query, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {}, onchange: null, dispatchEvent: () => false })) as unknown as typeof window.matchMedia;
});

beforeEach(() => {
    socketCall.mockImplementation((event: string, payload: Record<string, unknown>) => answer(event, payload));
});

afterEach(() => {
    cleanup();
    socketCall.mockReset();
});

const open = () =>
    render(
        <MemoryRouter initialEntries={['/dashboard?tab=settings&section=usage']}>
            <UsagePage />
        </MemoryRouter>
    );

it('shows a skeleton while the page reads, then the page', async () => {
    let resolve!: (v: unknown) => void;
    answer = () => new Promise((r) => (resolve = r));
    open();
    expect(screen.getByLabelText('Loading usage')).toBeTruthy();
    await act(async () => resolve(BUSY));
    expect(await screen.findByLabelText('Where it goes')).toBeTruthy();
    expect(socketCall).toHaveBeenCalledWith('usage:page');
});

it('says when the page failed and reads it again on Try again', async () => {
    answer = () => Promise.reject(new Error('backend down'));
    open();
    expect(await screen.findByText('Usage didn’t load.')).toBeTruthy();
    answer = () => Promise.resolve(BUSY);
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByLabelText('Where it goes')).toBeTruthy();
});

it('reads as a new account’s page before anything is spent', async () => {
    answer = () => Promise.resolve(pageData([]));
    open();
    expect(await screen.findByText(/nothing spent yet/)).toBeTruthy();
    expect(screen.getByText('What each thing cost, as it was used.')).toBeTruthy();
    expect(screen.getByText('No charges yet this period.')).toBeTruthy();
    // Nobody is billed here: no balance, no paid-by column, nothing scheduled.
    expect(screen.queryByText('Balance')).toBeNull();
    expect(screen.queryByText('Paid by')).toBeNull();
    expect(screen.queryByText('Coming up')).toBeNull();
});

it('splits the spend by service, and inside one by what drove it, narrowing the charges to it', async () => {
    answer = (event, payload) => {
        if (event === 'usage:page') return Promise.resolve(BUSY);
        const keys = payload.keys as string[] | undefined;
        return Promise.resolve({ rows: BUSY.charges.rows.filter((r) => !keys || keys.includes(r.k)), runs: {}, next: null });
    };
    open();
    const where = await screen.findByLabelText('Where it goes');
    expect(within(where).getByText('AI models')).toBeTruthy();
    expect(within(where).getByText('$6.00')).toBeTruthy();
    const charges = screen.getByRole('table', { name: 'Charges' });
    expect(within(charges).getAllByRole('row').length).toBeGreaterThan(2);

    fireEvent.click(within(where).getByText('AI models'));
    await waitFor(() => expect(within(where).getByRole('navigation', { name: 'Where it goes, drilled' })).toBeTruthy());
    expect(within(where).getByText('By model, with what each used')).toBeTruthy();
    expect(within(where).getByText('Claude Sonnet 4.6')).toBeTruthy();
    // The charges now read only the groups inside AI models.
    await waitFor(() => expect(socketCall).toHaveBeenCalledWith('usage:charges', expect.objectContaining({ keys: expect.arrayContaining([`${SONNET}|${WF}|agent-1`, `${MINI}|${WF}|agent-1`]) })));
    const last = socketCall.mock.calls.filter(([e]) => e === 'usage:charges').pop()![1] as { keys: string[] };
    expect(last.keys).not.toContain(`exa/search_api|${WF}|agent-1`);
    // The days say what they're narrowed to, with the way back to everything.
    expect(screen.getByText('Show everything')).toBeTruthy();

    // One step back out, and the charges are everything again.
    fireEvent.click(within(where).getByRole('button', { name: 'Back' }));
    await waitFor(() => expect(within(where).queryByRole('navigation', { name: 'Where it goes, drilled' })).toBeNull());
});

it('drills service › model › what used it › its charges, in the URL, and backs out a level at a time', async () => {
    const chat = group('2026-10-15', SONNET, 4.0, { surface: 'coordinator', k: 'sonnet-chat' });
    const data = pageData([...BUSY.groups, chat], BUSY.charges.rows);
    answer = (event, payload) => {
        if (event === 'usage:page') return Promise.resolve(data);
        const keys = payload.keys as string[] | undefined;
        return Promise.resolve({ rows: data.charges.rows.filter((r) => !keys || keys.includes(r.k)), runs: {}, next: null });
    };
    let search = '';
    const Probe = () => {
        search = useLocation().search;
        return null;
    };
    render(
        <MemoryRouter initialEntries={['/dashboard?tab=settings&section=usage']}>
            <UsagePage />
            <Probe />
        </MemoryRouter>
    );
    const where = await screen.findByLabelText('Where it goes');
    const crumbs = () =>
        within(within(where).getByRole('navigation', { name: 'Where it goes, drilled' }))
            .getAllByRole('listitem')
            .map((li) => li.textContent);
    const lastKeys = () => (socketCall.mock.calls.filter(([e]) => e === 'usage:charges').pop()![1] as { keys: string[] }).keys;

    fireEvent.click(within(where).getByText('AI models'));
    fireEvent.click(await within(where).findByText('Claude Sonnet 4.6'));
    expect(await within(where).findByText('By what used it')).toBeTruthy();
    expect(within(where).getByText('Chat with NoClick')).toBeTruthy();
    expect(within(where).getByText('Support agent · Inbox triage')).toBeTruthy();
    expect(new URLSearchParams(search).get('in')).toBe(`service:ai,item:${encodeURIComponent(SONNET)}`);
    // The model narrows the charges to its own groups.
    await waitFor(() => expect(lastKeys()).toEqual(expect.arrayContaining(['sonnet-chat', `${SONNET}|${WF}|agent-1`])));
    expect(lastKeys()).not.toContain(`${MINI}|${WF}|agent-1`);

    fireEvent.click(within(where).getByText('Chat with NoClick'));
    await waitFor(() => expect(lastKeys()).toEqual(['sonnet-chat']));
    expect(new URLSearchParams(search).get('pick')).toBe('__chat__');
    // The picked row stays in its list, pressed; the days and the charges name the whole way down.
    await waitFor(() => expect(crumbs()).toEqual(['All services', 'AI models', 'Claude Sonnet 4.6']));
    expect(within(where).getByText('Chat with NoClick').closest('[aria-pressed]')?.getAttribute('aria-pressed')).toBe('true');
    expect(screen.getAllByText('AI models › Claude Sonnet 4.6 › Chat with NoClick').length).toBeGreaterThan(0);

    // Back: the pick, then the model, then the service.
    const back = async () => {
        // A level that's leaving fades out beside the new one: step back once it has gone.
        await waitFor(() => expect(within(where).getAllByRole('button', { name: 'Back' })).toHaveLength(1));
        fireEvent.click(within(where).getByRole('button', { name: 'Back' }));
    };
    await back();
    await waitFor(() => expect(new URLSearchParams(search).get('pick')).toBeNull());
    await waitFor(() => expect(crumbs()).toEqual(['All services', 'AI models', 'Claude Sonnet 4.6']));
    await back();
    expect(await within(where).findByText('By model, with what each used')).toBeTruthy();
    await back();
    await waitFor(() => expect(within(where).queryByRole('navigation', { name: 'Where it goes, drilled' })).toBeNull());
});
