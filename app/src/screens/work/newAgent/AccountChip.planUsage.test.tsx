// @vitest-environment happy-dom
// A plan's tier and usage in the account pill and its menu, over the fake /v1: the pill says what's left once the plan
// is nearly used for the pick; the menu reads the used plan fresh as it opens and shows the windows that can stop the
// pick's model, the other plans one bar each, each plan's tier beside its name, and a tier that runs nothing among the
// ones not for this, in its own words. A `usage` frame reads it again; nothing polls.
import {
    cleanup,
    fireEvent,
    render,
    screen,
    waitFor,
    within,
} from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { WorkProviders } from '../agents/fixtures/providers';
import { fakeWorkAgent } from '../conversation/fixtures/workAgent';
import { createWorkLive } from '@/sdk/live';
import { AccountChip } from './AccountChip';
import { connectAsk, firstUsable, type ModelAccount } from './accounts';
import { useHarnesses, useModelAccounts } from './catalog';

type Json = Record<string, unknown>;
const MODEL = 'claude-opus-5-5';
// Tuesday 17 November 2026, 11:00 in the runner's zone.
const NOW = new Date(2026, 10, 17, 11, 0, 0);
const iso = (day: number, hour: number, minute = 0) =>
    new Date(2026, 10, day, hour, minute).toISOString();

const win = (
    kind: string,
    label: string,
    used: number,
    resets: string | null,
    models: string[] = []
): Json => ({
    kind,
    label,
    models,
    used,
    left: Math.round((1 - used) * 1000) / 1000,
    resets_at: resets,
    state: used >= 1 ? 'used_up' : used >= 0.8 ? 'near' : 'ok',
});
const FIVE_HOUR = win('five_hour', '5-hour', 0.91, iso(17, 12, 40));
const CLAUDE_WINDOWS = [
    FIVE_HOUR,
    win('weekly', 'Weekly', 0.38, iso(19, 9)),
    win('weekly_model', 'Opus weekly', 0.71, iso(19, 9), ['Opus']),
    win('weekly_model', 'Sonnet weekly', 0.12, iso(19, 9), ['Sonnet']),
];
const GPT_WEEKLY = win('weekly', 'Weekly', 0.51, iso(20, 9));

const connection = (
    id: string,
    name: string,
    credentialType: string,
    integration: string,
    extra: Json
): Json => ({
    object: 'connection',
    id,
    name,
    integration,
    credential_type: credentialType,
    status: 'connected',
    origin: 'api',
    ...extra,
});
const CONNECTIONS = (): Json[] => [
    connection('conn-1', 'claude', 'agent_claude_code_oauth', 'anthropic', {
        account: 'ana@example.com',
        plan: {
            tier: 'max_20x',
            label: 'Ultra',
            runs: ['claude_code'],
            refusal: null,
        },
        usage: {
            state: 'near',
            tightest: FIVE_HOUR,
            available_at: null,
            as_of: iso(17, 10, 58),
        },
        windows: CLAUDE_WINDOWS.map((w) => ({ ...w })),
    }),
    connection(
        'conn-free',
        'claude-free',
        'agent_claude_code_oauth',
        'anthropic',
        {
            account: 'kid@example.com',
            plan: {
                tier: 'free',
                label: 'Free',
                runs: [],
                refusal: 'Claude Free doesn’t include Claude Code.',
            },
            usage: null,
        }
    ),
    connection('conn-gpt', 'chatgpt', 'agent_codex_oauth', 'openai', {
        plan: { tier: 'plus', label: 'Plus', runs: ['codex'], refusal: null },
        usage: {
            state: 'ok',
            tightest: GPT_WEEKLY,
            available_at: null,
            as_of: iso(17, 10, 58),
        },
        windows: [GPT_WEEKLY],
    }),
];

function Chip() {
    const harnesses = useHarnesses();
    const { accounts } = useModelAccounts();
    const harness = harnesses.data?.find((h) => h.name === 'claude_code');
    if (!harness || !accounts) return null;
    const account = firstUsable(accounts, harness, [MODEL]);
    return (
        <AccountChip
            harness={harness}
            model={MODEL}
            modelLabel="Opus 5.5"
            accounts={accounts}
            account={account as ModelAccount | null}
            routes={[MODEL]}
            free={null}
            picked={false}
            ask={connectAsk(accounts, harness, MODEL, [])}
            ways={[]}
            onPick={() => undefined}
            onConnect={() => undefined}
            compact
        />
    );
}

function show() {
    const connections = CONNECTIONS();
    const fake = fakeWorkAgent({ connections });
    const live = createWorkLive();
    render(
        <WorkProviders client={fake.client} live={live}>
            <Chip />
        </WorkProviders>
    );
    const usageReads = () =>
        fake.requests.filter(
            (r) =>
                r.method === 'GET' &&
                /\/v1\/connections\/[^/]+\/usage$/.test(r.path)
        );
    const connectionLists = () =>
        fake.requests.filter(
            (r) => r.method === 'GET' && r.path === '/v1/connections'
        );
    // The fake's connections as GET /v1/connections lists them: changed in place, as a new reading changes them.
    const listed = () => fake.connections;
    return { fake, live, usageReads, connectionLists, listed };
}

beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(NOW);
    globalThis.ResizeObserver ??= class {
        observe() {}
        unobserve() {}
        disconnect() {}
    } as unknown as typeof ResizeObserver;
});
afterEach(() => {
    cleanup();
    vi.useRealTimers();
});

const pill = () => screen.findByRole('button', { name: /^Runs on:/ });

describe('a plan’s usage in the account pill', () => {
    it('says what’s left once the plan is nearly used for the pick, from NoClick’s last reading', async () => {
        const { usageReads } = show();
        await waitFor(async () =>
            expect((await pill()).textContent).toBe('Claude plan · 9% left')
        );
        const read = usageReads()[0];
        expect(read.query.get('model')).toBe(MODEL);
        expect(read.query.get('fresh')).toBeNull();
        // Its plans with a clear summary aren't read at all.
        expect(usageReads().map((r) => decodeURIComponent(r.path))).toEqual([
            '/v1/connections/claude/usage',
        ]);
    });

    it('opens on the windows that can stop the model, read fresh, and the other plans one bar each with their tiers', async () => {
        const { usageReads } = show();
        fireEvent.click(await pill());
        const menu = await screen.findByRole('dialog', { name: 'Runs on' });
        await waitFor(() =>
            expect(
                usageReads().some(
                    (r) =>
                        r.query.get('fresh') === 'true' &&
                        r.query.get('model') === MODEL
                )
            ).toBe(true)
        );

        const used = within(menu).getByRole('menuitemradio', { checked: true });
        expect(within(used).getByText('Ultra')).toBeTruthy();
        await waitFor(() =>
            expect(within(used).getAllByTestId('plan-window')).toHaveLength(3)
        );
        const windows = within(used)
            .getAllByTestId('plan-window')
            .map((w) => w.textContent);
        expect(windows).toEqual([
            '5-hour91% usedresets in 1 h 40 min',
            'Weekly38% usedresets Thu 9:00 AM',
            'Opus weekly71% usedresets Thu 9:00 AM',
        ]);
        // The near window reads in full ink, never red.
        const near = within(used).getAllByTestId('plan-window')[0];
        expect(near.getAttribute('data-state')).toBe('near');
        expect(near.innerHTML).not.toMatch(/red|yellow|amber/);

        // Claude Free runs nothing: it's among the ones not for this, saying so, its tier beside it.
        expect(within(menu).getAllByRole('menuitemradio')).toHaveLength(1);
        expect(
            within(menu).getByText('Claude Free doesn’t include Claude Code.')
        ).toBeTruthy();
        expect(within(menu).getByText('Free')).toBeTruthy();
        // ChatGPT's plan, not for Claude Code: its tier and the window that stops it first.
        expect(within(menu).getByText('Plus')).toBeTruthy();
        const others = within(menu)
            .getAllByTestId('plan-usage')
            .filter((u) => !used.contains(u));
        expect(others.map((u) => u.textContent)).toEqual([
            'Weekly51% usedresets Fri 9:00 AM',
        ]);
    });

    it('reads it again on its connection’s usage frame, and says used up then', async () => {
        const { live, listed, usageReads, connectionLists } = show();
        await waitFor(async () =>
            expect((await pill()).textContent).toBe('Claude plan · 9% left')
        );
        const claude = listed().find((c) => c.id === 'conn-1')!;
        const out = { ...FIVE_HOUR, used: 1, left: 0, state: 'used_up' };
        claude.windows = [out, ...CLAUDE_WINDOWS.slice(1)];
        claude.usage = {
            state: 'used_up',
            tightest: out,
            available_at: FIVE_HOUR.resets_at,
            as_of: iso(17, 11),
        };
        const before = usageReads().length;
        const listsBefore = connectionLists().length;
        // Usage has a frame of its own: the connections lists (and what reads them) don't read again on it.
        live.deliver('platform:resource', {
            kind: 'plan_usage',
            id: 'conn-1',
            status: 'used_up',
        });
        await waitFor(async () =>
            expect((await pill()).textContent).toBe('Claude plan · used up')
        );
        expect(usageReads().length).toBeGreaterThan(before);
        expect(connectionLists().length).toBe(listsBefore);
    });

    it('leaves the pill as it is below the limit', async () => {
        const connections = CONNECTIONS();
        const clear = win('five_hour', '5-hour', 0.4, iso(17, 12, 40));
        connections[0].windows = [clear];
        connections[0].usage = {
            state: 'ok',
            tightest: clear,
            available_at: null,
            as_of: iso(17, 10, 58),
        };
        const fake = fakeWorkAgent({ connections });
        render(
            <WorkProviders client={fake.client}>
                <Chip />
            </WorkProviders>
        );
        await waitFor(() =>
            expect(fake.requests.some((r) => r.path.endsWith('/usage'))).toBe(
                true
            )
        );
        expect((await pill()).textContent).toBe('Claude plan');
    });

    it('follows a plan that was clear from the start until it is used up', async () => {
        const { live, listed, usageReads } = show();
        const claude = listed().find((c) => c.id === 'conn-1')!;
        const clear = win('five_hour', '5-hour', 0.3, iso(17, 12, 40));
        claude.windows = [clear];
        claude.usage = { state: 'ok', tightest: clear, available_at: null, as_of: iso(17, 10) };
        await waitFor(() => expect(usageReads().length).toBeGreaterThan(0));
        expect((await pill()).textContent).toBe('Claude plan');
        const out = { ...clear, used: 1, left: 0, state: 'used_up' };
        claude.windows = [out];
        live.deliver('platform:resource', {
            kind: 'plan_usage',
            id: 'conn-1',
            status: 'used_up',
        });
        await waitFor(async () =>
            expect((await pill()).textContent).toBe('Claude plan · used up')
        );
    });

    it('says near even when the accounts list still has an older summary that was clear', async () => {
        // The list's summary isn't read again as the plan is used (a usage frame never re-reads it): the pill reads
        // the plan's own usage, so an older "ok" never hides that it's nearly used now.
        const connections = CONNECTIONS();
        const near = win('five_hour', '5-hour', 0.91, iso(17, 12, 40));
        connections[0].windows = [near];
        connections[0].usage = {
            state: 'ok',
            tightest: { ...near, used: 0.4, left: 0.6, state: 'ok' },
            available_at: null,
            as_of: iso(17, 9),
        };
        const fake = fakeWorkAgent({ connections });
        render(
            <WorkProviders client={fake.client}>
                <Chip />
            </WorkProviders>
        );
        await waitFor(async () =>
            expect((await pill()).textContent).toBe('Claude plan · 9% left')
        );
    });
});
