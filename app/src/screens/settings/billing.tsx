// Settings → Plan and billing as the app draws it where no host has its own (a host that bills fills the section): the
// account's plan and balance as the platform API reads them, with NoClick's pages for changing the plan and adding
// funds, and its monthly spending cap, read with GET /v1/usage/limits and set with PUT /v1/usage/limits/account. One of
// the account's keys lowers the cap or sets one where there's none; raising or removing it is the owner's, on NoClick
// (screens/console/ownerOnly.ts, `accountCap`). All of it is read again on the host's live frames (the cap set, the
// account charged, a `reset`), never on a timer.
import { useCallback, useState } from 'react';
import { ExternalLink } from 'lucide-react';
import { Usage, type AccountCap } from 'noclick';
import { useClient } from '@/sdk/client';
import { useWorkFrames } from '@/sdk/live';
import type { AccountView } from '@/sdk/owner';
import { invalidateV1, useV1 } from '@/sdk/useV1';
import { useAccount, useConsole } from '@/screens/console/hooks/useConsole';
import { addFundsUrl, billingSettingsUrl } from '@/screens/console/lib/site';
import { useOwnerOnly } from '@/screens/console/ownerOnly';
import { money, planName } from '@/screens/usage/derive';
import { BUTTON_SECONDARY } from '@/ui/buttons';
import { SettingsGroup, SettingsHeader, SettingsRow } from './parts';
import { SpendCapRow, type SpendCapControl, type SpendCapState } from './spendCap';

/** The cap's read's key in the client's cache. */
export const ACCOUNT_CAP_READ = 'settings:account_cap';

const NOT_READ = 'The spending cap didn’t load.';
const NOT_SAVED = 'Couldn’t save the cap. Try again.';

/** The cap as the account reads it: its own period where one is set, else the period the account's month is. */
function stateOf(cap: AccountCap | null, month: AccountView['month']): SpendCapState {
    const capUsd = cap?.capUsd ?? null;
    return {
        capUsd,
        spentUsd: cap?.spentUsd ?? month.spent_usd,
        periodStart: cap?.periodStart?.toISOString() ?? month.period_start,
        resetsAt: cap?.resetsAt?.toISOString() ?? month.resets_at,
        reached: capUsd !== null && cap?.reached === true,
        payer: { self: true },
    };
}

function messageOf(failure: unknown, fallback: string): string {
    return failure instanceof Error && failure.message ? failure.message : fallback;
}

/** The account's monthly spending cap, with the client and live frames the host hands it. */
export function useAccountCap(): SpendCapControl {
    const client = useClient();
    const account = useAccount();
    const read = useV1(ACCOUNT_CAP_READ, async () => (await Usage.limits({ client })).account, { client });
    const again = useCallback(() => invalidateV1(ACCOUNT_CAP_READ), []);
    useWorkFrames('platform:resource', (frame) => {
        if (frame.kind === 'spend_cap') again();
    });
    useWorkFrames('platform:usage', again);
    useWorkFrames('reset', again);
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const { data, mutate, refresh } = read;

    const save = useCallback(
        async (capUsd: number | null) => {
            setSaving(true);
            setError(null);
            try {
                mutate(await Usage.setAccountCap(capUsd, { client }));
                return true;
            } catch (failure) {
                setError(messageOf(failure, NOT_SAVED));
                return false;
            } finally {
                setSaving(false);
            }
        },
        [client, mutate]
    );

    const month = account.data?.month;
    const state = data !== undefined && month ? stateOf(data, month) : null;
    const loadError = state ? null : read.error || account.error ? NOT_READ : null;
    return { state, loadError, saving, error, setError, save, refresh };
}

/** What's left to spend: the balance as the account reads it, and the part of it that was added. */
function balanceLine(balance: AccountView['balance']): string {
    if (balance.unlimited) return 'No limit on this account.';
    if (balance.remaining_usd === null) return 'Not known right now.';
    const added = balance.funds_usd ? ` · ${money(balance.funds_usd)} of it added` : '';
    return `${money(balance.remaining_usd)} left${added}`;
}

/** NoClick's own page, where what this row shows is changed. */
function OnNoClick({ href, children }: { href: string; children: string }) {
    return (
        <a href={href} target="_blank" rel="noreferrer" className={BUTTON_SECONDARY}>
            {children}
            <ExternalLink aria-hidden className="h-3.5 w-3.5" />
        </a>
    );
}

function Loading({ label }: { label: string }) {
    return <span aria-label={label} className="inline-block h-3.5 w-40 animate-pulse rounded bg-foreground/[0.06] align-middle" />;
}

export function BillingStandard() {
    const { site } = useConsole();
    const may = useOwnerOnly();
    const account = useAccount().data;
    const cap = useAccountCap();
    // A charge moves the balance and the month.
    useWorkFrames('platform:usage', () => invalidateV1('account'));
    const billing = billingSettingsUrl(site);
    return (
        <div>
            <SettingsHeader title="Plan and billing" description="Your plan, balance and monthly spending cap." />
            <SettingsGroup note="The plan and adding funds are on NoClick.">
                <SettingsRow label="Plan" description={account ? planName(account.plan.tier) : <Loading label="Loading the plan" />} control={<OnNoClick href={billing}>Change on NoClick</OnNoClick>} />
                <SettingsRow
                    label="Balance"
                    description={account ? balanceLine(account.balance) : <Loading label="Loading the balance" />}
                    control={<OnNoClick href={addFundsUrl(site)}>Add funds on NoClick</OnNoClick>}
                />
                <SpendCapRow cap={cap} lowerOnly={may('accountCap') ? null : { raiseAt: billing }} />
            </SettingsGroup>
        </div>
    );
}
