// The signed-in owner's first screen: which NoClick account the app acts in, its plan, what it has left to spend and
// what it spent this month. Read in the browser through useClient(), so it goes through the app's own server.
import { APIConnectionError, NoClickError } from 'noclick';
import { useEffect, useState } from 'react';
import { useClient } from '@/sdk/client';
import { BUTTON_PRIMARY, BUTTON_SECONDARY } from '@/ui/buttons';
import { PAGE_TITLE } from '@/ui/titles';
import { readAccountStatus, type AccountStatus } from './status';

type Reading = { state: 'loading' } | { state: 'ready'; status: AccountStatus } | { state: 'failed'; error: unknown };

export function AccountScreen() {
    const client = useClient();
    const [reading, setReading] = useState<Reading>({ state: 'loading' });
    const [attempt, setAttempt] = useState(0);

    useEffect(() => {
        const controller = new AbortController();
        setReading({ state: 'loading' });
        readAccountStatus(client, controller.signal).then(
            (status) => setReading({ state: 'ready', status }),
            (error: unknown) => {
                if (!controller.signal.aborted) setReading({ state: 'failed', error });
            },
        );
        return () => controller.abort();
    }, [client, attempt]);

    return (
        <main className="mx-auto flex min-h-screen w-full max-w-xl flex-col gap-10 px-6 py-16">
            {reading.state === 'loading' && (
                <p role="status" className="text-[14px] text-muted-foreground">
                    Reading your NoClick account…
                </p>
            )}
            {reading.state === 'failed' && <Failure error={reading.error} retry={() => setAttempt((n) => n + 1)} />}
            {reading.state === 'ready' && <Account status={reading.status} />}
            <div className="flex flex-wrap items-center gap-3">
                {/* What the account owns and what it costs, then where it's worked on: its agents, users, logs and usage. */}
                <a className={BUTTON_PRIMARY} href="/resources">
                    Resources
                </a>
                <a className={BUTTON_SECONDARY} href="/developers">
                    Developer console
                </a>
                <form method="post" action="/logout">
                    <button type="submit" className={BUTTON_SECONDARY}>
                        Sign out
                    </button>
                </form>
            </div>
        </main>
    );
}

function Account({ status }: { status: AccountStatus }) {
    const { account, actingFor, plan, balance, month } = status;
    const title = account.name ?? account.email ?? 'Your NoClick account';
    return (
        <section className="flex flex-col gap-8">
            <div className="flex flex-col gap-1">
                <h1 className={PAGE_TITLE}>{title}</h1>
                {account.name && account.email && <p className="text-[14px] text-muted-foreground">{account.email}</p>}
            </div>
            <dl className="flex flex-col divide-y divide-border dark:divide-foreground/[0.08]">
                {actingFor && <Row label="Acting for" value={actingFor.name ?? actingFor.email ?? 'one of the account’s users'} />}
                {plan && <Row label="Plan" value={plan.name.charAt(0).toUpperCase() + plan.name.slice(1)} />}
                <Row
                    label="Left to spend"
                    value={balance.unlimited ? 'Unlimited' : balance.remainingUsd === null ? 'Can’t be read right now' : dollars(balance.remainingUsd)}
                />
                {month.spentUsd !== null && (
                    <Row label="Spent this month" value={month.periodStart ? `${dollars(month.spentUsd)} since ${day(month.periodStart)}` : dollars(month.spentUsd)} />
                )}
            </dl>
        </section>
    );
}

function Row({ label, value }: { label: string; value: string }) {
    return (
        <div className="flex items-baseline justify-between gap-6 py-3.5 text-[14px]">
            <dt className="text-muted-foreground">{label}</dt>
            <dd className="text-right font-medium tabular-nums text-foreground">{value}</dd>
        </div>
    );
}

function Failure({ error, retry }: { error: unknown; retry: () => void }) {
    const signedOut = error instanceof NoClickError && error.details.reason === 'signed_out';
    let message = 'Something went wrong while reading your account.';
    let nextStep: string | null = null;
    if (error instanceof APIConnectionError) {
        // The SDK's own words name NoClick's API; here it is the app's server that couldn't be reached.
        message = 'This page couldn’t reach the app’s server.';
        nextStep = 'Check your connection, then try again.';
    } else if (error instanceof NoClickError) {
        message = error.message;
        nextStep = error.nextStep;
    }
    return (
        <section role="alert" className="flex flex-col gap-4">
            <h1 className={PAGE_TITLE}>Couldn’t read your account</h1>
            <div className="flex flex-col gap-1 text-[14px]">
                <p className="text-foreground">{message}</p>
                {nextStep && <p className="text-muted-foreground">{nextStep}</p>}
            </div>
            <p>
                {signedOut ? (
                    <a className={BUTTON_PRIMARY} href="/login">
                        Sign in again
                    </a>
                ) : (
                    <button type="button" onClick={retry} className={BUTTON_SECONDARY}>
                        Try again
                    </button>
                )}
            </p>
        </section>
    );
}

const dollars = (usd: number) => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(usd);
const day = (iso: string) => {
    const date = new Date(iso);
    return Number.isNaN(date.getTime()) ? iso : new Intl.DateTimeFormat('en-US', { month: 'long', day: 'numeric', timeZone: 'UTC' }).format(date);
};
