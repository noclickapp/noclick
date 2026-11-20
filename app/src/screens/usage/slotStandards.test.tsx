// @vitest-environment happy-dom
// What the Usage page shows in its slots with no host: the balance as read, with funds added on NoClick; a charge's
// run as the charges read describes it, with its automation on NoClick; and nothing of the plan, alerts, prices or
// someone to ask, which are the deployment's.
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { standing } from '@/slots';
import { ConsoleContext, type ConsoleContextValue } from '@/screens/console/hooks/useConsole';
import { deriveView, toSnapshot } from './derive';
import { ALERT, BALANCE, CHARGE_ASK, CHARGE_PRICE, CHARGE_RUN, PLAN_LINE } from './slots';
import type { ChargeRun, PlanState, UsageBilling, UsagePageData } from './types';

vi.hoisted(() => {
    process.env.TZ = 'UTC';
});

afterEach(cleanup);

const PLAN: PlanState = {
    billing_model: 'free_member',
    tier: 'member',
    window_start: '2026-10-01T00:00:00Z',
    window_end: '2026-11-01T00:00:00Z',
    previous_start: '2026-09-01T00:00:00Z',
    included_usd: 10,
    included_used_usd: 0,
    daily_usd: null,
    daily_used_usd: null,
    fee_rate: 0.05,
    topup_usd: 0,
    topup_used_usd: 0,
    plan_price_usd: 25,
    renews_at: '2026-11-01T00:00:00Z',
};

function viewWith(balance: UsageBilling['balance']) {
    const data: UsagePageData = {
        now: '2026-10-16T15:20:00Z',
        account: { id: 'u-1' },
        period: { window_start: PLAN.window_start, window_end: PLAN.window_end, previous_start: PLAN.previous_start },
        billing: { plan: PLAN, balance, funds: { usd: 0, fee: 0, count: 0 }, autoTopUp: null, recurring: [], domains: [] },
        groups: [],
        directory: { workflows: {}, agents: {}, people: {} },
        charges: { rows: [], runs: {}, next: null },
    };
    return deriveView(toSnapshot(data));
}

describe('the balance', () => {
    const Balance = standing(BALANCE)!;

    it('shows what was read and links to adding funds on NoClick', () => {
        render(<Balance view={viewWith({ usd: 12.5, has: true })} />);
        expect(screen.getByText('Balance')).toBeTruthy();
        expect(screen.getByText('$12.50')).toBeTruthy();
        expect(screen.getByRole('link', { name: 'Add funds on NoClick' }).getAttribute('href')).toBe('https://noclick.com/dashboard?action=topup');
        expect(screen.queryByRole('button')).toBeNull();
    });

    it('reads as owed below zero, and links to the site of the console it is drawn in', () => {
        const site = { site: 'https://staging.example' } as ConsoleContextValue;
        render(
            <ConsoleContext.Provider value={site}>
                <Balance view={viewWith({ usd: -3, has: true })} />
            </ConsoleContext.Provider>,
        );
        expect(screen.getByText('Owed')).toBeTruthy();
        expect(screen.getByText('$3.00')).toBeTruthy();
        expect(screen.getByText('Repaid from the next funds you add')).toBeTruthy();
        expect(screen.getByRole('link', { name: 'Add funds on NoClick' }).getAttribute('href')).toBe('https://staging.example/dashboard?action=topup');
    });

    it('says when no funds were ever added', () => {
        render(<Balance view={viewWith({ usd: 0, has: false })} />);
        expect(screen.getByText('$0')).toBeTruthy();
        expect(screen.getByText('No funds yet')).toBeTruthy();
    });
});

describe('a charge’s run', () => {
    const Run = standing(CHARGE_RUN);
    const RUN: ChargeRun = {
        id: 'abcdef12-3456-7890-abcd-ef1234567890',
        workflow: { id: 'wf-1', name: 'Inbox triage' },
        status: 'completed',
        startedAt: '2026-10-15T09:00:00Z',
        durationMs: 75_000,
        trigger: 'schedule',
        nodesExecuted: 4,
    };

    it('says what the read knows of it and opens its automation on NoClick', () => {
        const onClose = vi.fn();
        render(<Run run={RUN} onClose={onClose} />);
        const dialog = screen.getByRole('dialog');
        expect(dialog.textContent).toContain('Inbox triage');
        expect(dialog.textContent).toContain('Run abcdef12');
        expect(dialog.textContent).toContain('Thu, Oct 15, 9:00 AM UTC');
        expect(dialog.textContent).toContain('1m 15s');
        expect(dialog.textContent).toContain('schedule');
        expect(screen.getByRole('link', { name: 'Open on NoClick' }).getAttribute('href')).toBe('https://noclick.com/dashboard?workflow=wf-1');
        // The footer's Close, beside the dialog's own ✕.
        fireEvent.click(screen.getAllByRole('button', { name: 'Close' }).at(-1)!);
        expect(onClose).toHaveBeenCalled();
    });

    it('shows the error a failed run ended with', () => {
        render(<Run run={{ ...RUN, status: 'error', error: 'The sheet was not found.' }} onClose={() => undefined} />);
        expect(screen.getByRole('dialog').textContent).toContain('The sheet was not found.');
    });
});

describe('the deployment’s own parts', () => {
    it('stand empty: no plan line, alert, price or someone to ask', () => {
        expect(standing(PLAN_LINE)).toBeNull();
        expect(standing(ALERT)).toBeNull();
        expect(standing(CHARGE_PRICE)).toBeNull();
        expect(standing(CHARGE_ASK)).toBeNull();
    });
});
