// @vitest-environment jsdom
// Settings → Usage's charges, read a page at a time: "Show N more" appends the next page and the table stays there,
// with or without a filter; a re-read of the page brings new charges in on top of a paged table without losing its
// place; a changed filter starts again from its own first page. The backend here pages like usage:charges does, newest
// first by a (created_at, id) cursor, narrowed to the groups chargeQuery picked.
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeAll, beforeEach, expect, it, vi } from 'vitest';

const { socketCall } = vi.hoisted(() => ({ socketCall: vi.fn() }));
vi.mock('~/lib/socketCall', () => ({ socketCall }));

import { UsagePage } from '~/components/usage/page/UsagePage';
import { money } from '~/components/usage/page/derive';
import type { ChargeRow, ChargesPage, UsagePageData } from '~/components/usage/page/types';

const ME = 'u-1';
const WF = 'wf-1';
const SONNET = 'openrouter/anthropic/claude-sonnet-4.6';
const EXA = 'exa/search_api';

/** `n` charges, newest first, 20 minutes apart from `top`, each a cent more than the last so its amount names it. */
function charges(n: number, top = Date.parse('2026-10-15T23:00:00Z'), from = 1): ChargeRow[] {
    return Array.from({ length: n }, (_, i) => {
        const subtype = i % 7 < 2 ? EXA : SONNET;
        const at = new Date(top - i * 20 * 60_000).toISOString();
        return {
            id: `c-${String(from + i).padStart(3, '0')}`,
            created_at: at,
            user_id: ME,
            organization_id: null,
            usage_type: subtype === SONNET ? 'ai_usage' : 'api_usage',
            usage_subtype: subtype,
            quantity: 1000,
            unit_type: subtype === SONNET ? 'tokens' : 'requests',
            total_cost: (from + i) / 100,
            user_resource: false,
            metadata: { workflow_id: WF, node_id: 'agent-1' },
            k: `${subtype}|${at.slice(0, 10)}`,
        };
    });
}

/** The page's groups, summed from its charges as usage:page groups them. */
function pageData(rows: ChargeRow[]): UsagePageData {
    const groups = new Map<string, UsagePageData['groups'][number]>();
    for (const r of rows) {
        const g = groups.get(r.k) as (UsagePageData['groups'][number] & { n: number; total_cost: number }) | undefined;
        if (g) {
            g.n += 1;
            g.total_cost += r.total_cost;
            continue;
        }
        groups.set(r.k, {
            current: true,
            day: r.created_at.slice(0, 10),
            created_at: r.created_at,
            k: r.k,
            user_id: ME,
            usage_type: r.usage_type,
            usage_subtype: r.usage_subtype,
            unit_type: r.unit_type,
            user_resource: false,
            n: 1,
            quantity: r.quantity,
            total_cost: r.total_cost,
            prompt_tokens: 0,
            completion_tokens: 0,
            workflow_id: WF,
            node_id: 'agent-1',
        } as unknown as UsagePageData['groups'][number]);
    }
    return {
        now: '2026-10-16T15:20:00Z',
        account: { id: ME },
        period: { window_start: '2026-10-01T00:00:00Z', window_end: '2026-11-01T00:00:00Z', previous_start: '2026-09-01T00:00:00Z' },
        billing: null,
        groups: [...groups.values()],
        directory: { workflows: { [WF]: { name: 'Inbox triage' } }, agents: { [`${WF}:agent-1`]: { name: 'Support agent' } }, people: { [ME]: { name: 'Ada' } } },
        charges: page(rows, {}),
    };
}

/** usage:charges over `rows` (newest first): the groups asked for, after the cursor, `limit` at a time. */
function page(rows: ChargeRow[], { keys, cursor, limit = 50 }: { keys?: string[]; cursor?: string; limit?: number }): ChargesPage {
    const kept = rows.filter((r) => !keys || keys.includes(r.k));
    const from = cursor ? kept.findIndex((r) => `${r.created_at}|${r.id}` === cursor) + 1 : 0;
    const out = kept.slice(from, from + limit);
    const last = out[out.length - 1];
    return { rows: out, runs: {}, next: from + limit < kept.length && last ? `${last.created_at}|${last.id}` : null };
}

let rows: ChargeRow[];

beforeAll(() => {
    globalThis.ResizeObserver ??= class {
        observe() {}
        unobserve() {}
        disconnect() {}
    } as unknown as typeof ResizeObserver;
    window.matchMedia ??= ((query: string) => ({ matches: false, media: query, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {}, onchange: null, dispatchEvent: () => false })) as unknown as typeof window.matchMedia;
    Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true });
});

beforeEach(() => {
    rows = charges(85);
    socketCall.mockImplementation((event: string, payload: Record<string, unknown>) =>
        Promise.resolve(event === 'usage:page' ? pageData(rows) : page(rows, payload as { keys?: string[]; cursor?: string; limit?: number }))
    );
});

afterEach(() => {
    cleanup();
    socketCall.mockReset();
});

const table = () => screen.getByRole('table', { name: 'Charges' });
/** Each charge line's amount, top to bottom: which charges the table shows, in its order. */
const shown = () =>
    within(table())
        .queryAllByRole('row')
        .filter((r) => r.tabIndex === 0)
        .map((r) => {
            const cells = within(r).getAllByRole('cell');
            return cells[cells.length - 1].textContent;
        });
const amounts = (list: ChargeRow[]) => list.map((r) => money(r.total_cost));
const charging = () => socketCall.mock.calls.filter(([e]) => e === 'usage:charges').map(([, p]) => p as { keys?: string[]; cursor?: string });
/** Lets every read and effect the last step started run out. */
const settle = () => act(() => new Promise((r) => setTimeout(r, 30)));

const open = async () => {
    render(
        <MemoryRouter initialEntries={['/dashboard?tab=settings&section=usage']}>
            <UsagePage />
        </MemoryRouter>
    );
    await waitFor(() => expect(shown()).toHaveLength(50));
};

it('shows the next page under the first, and stays on it', async () => {
    await open();
    expect(screen.getByText('Showing 50 of 85 charges')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Show 35 more' }));
    await waitFor(() => expect(shown()).toHaveLength(85));
    await settle();
    // Every charge once, newest first: nothing skipped or repeated across the two pages, and page one not read again.
    expect(shown()).toEqual(amounts(rows));
    expect(charging()).toEqual([expect.objectContaining({ cursor: `${rows[49].created_at}|${rows[49].id}` })]);
    expect(screen.queryByRole('button', { name: /more$/ })).toBeNull();
});

it('pages a filtered table the same way', async () => {
    await open();
    fireEvent.change(screen.getByRole('searchbox', { name: 'Search charges' }), { target: { value: 'sonnet' } });
    const sonnet = rows.filter((r) => r.usage_subtype === SONNET);
    await waitFor(() => expect(screen.getByText(`Showing 50 of ${sonnet.length} charges`)).toBeTruthy());
    expect(shown()).toEqual(amounts(sonnet.slice(0, 50)));
    fireEvent.click(screen.getByRole('button', { name: `Show ${sonnet.length - 50} more` }));
    await waitFor(() => expect(shown()).toHaveLength(sonnet.length));
    await settle();
    expect(shown()).toEqual(amounts(sonnet));
    const reads = charging();
    expect(reads.map((p) => p.cursor ?? null)).toEqual([null, `${sonnet[49].created_at}|${sonnet[49].id}`]);
    expect(new Set(reads.map((p) => JSON.stringify(p.keys)))).toEqual(new Set([JSON.stringify([`${SONNET}|2026-10-15`, `${SONNET}|2026-10-14`])]));
});

it('brings new charges in on top of a paged table, keeping its place', async () => {
    await open();
    fireEvent.click(screen.getByRole('button', { name: 'Show 35 more' }));
    await waitFor(() => expect(shown()).toHaveLength(85));

    // The page reads again with nothing new: the table stays as it is.
    await act(async () => void window.dispatchEvent(new Event('focus')));
    await settle();
    expect(shown()).toEqual(amounts(rows));

    // Two charges land and the page reads again: they join the top, and the 85 below stay, each once.
    rows = [...charges(2, Date.parse('2026-10-16T01:00:00Z'), 90), ...rows];
    await act(async () => void window.dispatchEvent(new Event('focus')));
    await waitFor(() => expect(shown()).toHaveLength(87));
    await settle();
    expect(shown()).toEqual(amounts(rows));
    expect(screen.getByRole('heading', { name: /^Charges/ }).textContent).toMatch(/^Charges\s*87 ·/);
    expect(screen.queryByRole('button', { name: /more$/ })).toBeNull();

    // More land than a first page holds: it no longer reaches what's shown, so the table starts again from it.
    rows = [...charges(60, Date.parse('2026-10-16T14:00:00Z'), 100), ...rows];
    await act(async () => void window.dispatchEvent(new Event('focus')));
    await waitFor(() => expect(shown()).toEqual(amounts(rows.slice(0, 50))));
    expect(screen.getByText('Showing 50 of 147 charges')).toBeTruthy();
});

it('starts a changed filter from its own first page', async () => {
    await open();
    fireEvent.click(screen.getByRole('button', { name: 'Show 35 more' }));
    await waitFor(() => expect(shown()).toHaveLength(85));
    const search = screen.getByRole('searchbox', { name: 'Search charges' });

    fireEvent.change(search, { target: { value: 'sonnet' } });
    const sonnet = rows.filter((r) => r.usage_subtype === SONNET);
    await waitFor(() => expect(shown()).toEqual(amounts(sonnet.slice(0, 50))));

    fireEvent.change(search, { target: { value: '' } });
    await waitFor(() => expect(shown()).toEqual(amounts(rows.slice(0, 50))));
    expect(screen.getByText('Showing 50 of 85 charges')).toBeTruthy();
});

it('says when the next page didn’t load, and keeps what it shows', async () => {
    await open();
    socketCall.mockImplementation((event: string) => (event === 'usage:page' ? Promise.resolve(pageData(rows)) : Promise.reject(new Error('backend down'))));
    fireEvent.click(screen.getByRole('button', { name: 'Show 35 more' }));
    expect(await screen.findByText(/The next charges didn’t load\./)).toBeTruthy();
    expect(shown()).toEqual(amounts(rows.slice(0, 50)));
    expect(screen.getByRole('button', { name: 'Show 35 more' })).toBeTruthy();
});
