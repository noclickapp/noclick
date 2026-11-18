// Card issuing: where the company's application stands (the Cards panel and the
// funding page show it until it's active) and the page that applies for it,
// `/resources/cards/onboarding`. The card issuer's own form there is a slot
// (slots.ts): it opens a session only the account's signed-in owner can, so a
// console acting as a key links to where the application is finished. The lab
// shows a placeholder and never loads the issuer's form.
import type { ReactNode } from 'react';
import { Link } from 'react-router';
import { HAIRLINE, SURFACE } from '@/ui/primitives';
import { cn } from '@/ui/utils';
import { Card, type CardProgram, type CardProgramStatus } from 'noclick';
import { useSlot } from '@/slots';
import type { StatusLook } from '@/screens/console/lib/status';
import { useConsole, useConsoleHref } from '@/screens/console/hooks/useConsole';
import { useV1, type V1State } from '@/sdk/useV1';
import { consoleButtonClass } from '../../ui/Button';
import { ErrorPanel } from '../../ui/ErrorPanel';
import { PageSection } from '../../ui/PageHeader';
import { StatusPill } from '../../ui/StatusPill';
import { useOwnerOnly } from '../../ownerOnly';
import { CARD_ISSUER_FORM } from '../../slots';
import { IssuerLink } from '../../slotStandards';
import { errorText, Field } from './shared';

/** The Cards kind's addresses (Resources routes the sub-pages; the API's links point at them). */
export const CARD_PAGES = { list: 'resources/cards', onboarding: 'resources/cards/onboarding', funding: 'resources/cards/funding' } as const;

const PROGRAM: Record<CardProgramStatus, { look: StatusLook; line: string; action: string | null }> = {
    not_started: {
        look: { label: 'Not applied', glyph: 'hollow', tone: 'muted' },
        line: 'Your company applies once before it can issue cards.',
        action: 'Apply for card issuing',
    },
    pending_verification: {
        look: { label: 'Being verified', glyph: 'waiting', tone: 'ink' },
        line: "The card issuer is checking your company's details; cards can be issued once it has.",
        action: 'Continue your application',
    },
    restricted: {
        look: { label: 'Needs more details', glyph: 'waiting', tone: 'ink' },
        line: 'The card issuer needs more from your company before its cards can be issued or pay again.',
        action: 'Continue your application',
    },
    rejected: {
        look: { label: 'Rejected', glyph: 'cross', tone: 'failure' },
        line: "The card issuer declined your company's application, so it can't issue cards. Contact NoClick support to understand why.",
        action: null,
    },
    active: {
        look: { label: 'Active', glyph: 'filled', tone: 'ink' },
        line: 'Your company can issue cards.',
        action: null,
    },
};

export function useCardProgram(): V1State<CardProgram> {
    const { client } = useConsole();
    return useV1('cards/program', () => Card.program({ client }));
}

/** A read that failed, in a banner's place: the API's words and Retry. */
export function RetryLine({ label, children, onRetry }: { label: string; children: ReactNode; onRetry: () => void }) {
    return (
        <section aria-label={label} className={cn(SURFACE, 'mb-3 flex flex-wrap items-center gap-2 px-4 py-3 text-[13px] text-muted-foreground')}>
            {children}
            <button type="button" onClick={onRetry} className="font-medium text-foreground underline-offset-2 hover:underline">
                Retry
            </button>
        </section>
    );
}

/** `children` once card issuing is active; until then where the application stands and the way to it. */
export function CardProgramGate({ children }: { children: ReactNode }) {
    const program = useCardProgram();
    const href = useConsoleHref();
    if (program.error !== undefined && !program.data) {
        return (
            <RetryLine label="Card issuing" onRetry={() => void program.refresh()}>
                {errorText(program.error)}
            </RetryLine>
        );
    }
    const p = program.data;
    if (!p) return <div aria-busy className={cn(SURFACE, 'mb-3 h-[4.5rem] animate-pulse')} />;
    if (p.status === 'active') return <>{children}</>;
    const { look, line, action } = PROGRAM[p.status];
    return (
        <section aria-label="Card issuing" className={cn(SURFACE, 'mb-3 flex flex-wrap items-center gap-x-6 gap-y-3 px-4 py-3')}>
            <div className="flex min-w-0 flex-1 flex-col gap-1">
                <span className="text-[12px] text-muted-foreground">Card issuing</span>
                <StatusPill look={look} />
                <p className="m-0 text-[12px] text-muted-foreground">
                    {line}
                    {p.requirementsDue.length > 0 && ` ${p.requirementsDue.length} ${p.requirementsDue.length === 1 ? 'detail is' : 'details are'} still due.`}
                </p>
            </div>
            {action && (
                <Link to={href(CARD_PAGES.onboarding)} className={consoleButtonClass('primary')}>
                    {action}
                </Link>
            )}
        </section>
    );
}

/** `/resources/cards/onboarding`: where the application stands and, until it's decided, the issuer's form for it. */
export function CardsOnboardingPage() {
    const { lab } = useConsole();
    const href = useConsoleHref();
    const IssuerForm = useSlot(CARD_ISSUER_FORM);
    const ownerCan = useOwnerOnly();
    const program = useCardProgram();
    if (program.error !== undefined && !program.data) return <ErrorPanel error={program.error} onRetry={() => void program.refresh()} />;
    const p = program.data;
    if (!p) return <div aria-busy className="h-40 animate-pulse rounded-xl bg-foreground/[0.03]" />;
    const { look, line } = PROGRAM[p.status];
    const deciding = p.status !== 'active' && p.status !== 'rejected';
    return (
        <>
            <PageSection title="Where it stands">
                <dl className="m-0">
                    <Field label="Status">
                        <StatusPill look={look} />
                    </Field>
                    {p.companyName && <Field label="Company">{p.companyName}</Field>}
                    {p.requirementsDue.length > 0 && (
                        <Field label="Still due">
                            <span role="list" aria-label="Still due" className="flex flex-wrap gap-1">
                                {p.requirementsDue.map((due) => (
                                    <span key={due} role="listitem" className="rounded bg-foreground/[0.06] px-1.5 py-[1px] font-mono text-[12px]">
                                        {due}
                                    </span>
                                ))}
                            </span>
                        </Field>
                    )}
                </dl>
                <p className="m-0 mt-2 text-[13px] text-muted-foreground">{line}</p>
                {p.status === 'active' && (
                    <div className="mt-3 flex flex-wrap gap-2">
                        <Link to={href(CARD_PAGES.list)} className={consoleButtonClass('primary')}>
                            Go to cards
                        </Link>
                        <Link to={href(CARD_PAGES.funding)} className={consoleButtonClass('soft')}>
                            Fund your cards
                        </Link>
                    </div>
                )}
            </PageSection>
            {deciding && (
                <PageSection title="Your company's details" note="The card issuer verifies the business and the people who run it; what you enter here goes to the card issuer, not to NoClick.">
                    {lab ? <LabPlaceholder /> : ownerCan('cardIssuerForm') ? <IssuerForm program={p} /> : <IssuerLink program={p} />}
                </PageSection>
            )}
        </>
    );
}

function LabPlaceholder() {
    return (
        <div role="note" aria-label="Stripe's form (lab placeholder)" className={cn('flex min-h-[16rem] flex-col items-center justify-center gap-1.5 rounded-xl border border-dashed px-6 py-10 text-center', HAIRLINE)}>
            <span className="rounded bg-foreground/[0.06] px-1.5 py-[1px] font-mono text-[12px] uppercase tracking-wide text-muted-foreground">Lab</span>
            <p className="m-0 text-[14px] font-medium text-foreground">Stripe&apos;s onboarding form mounts here</p>
            <p className="m-0 max-w-md text-[13px] text-muted-foreground">The lab never loads Stripe: its onboarding session is a fixture, with no real account behind it.</p>
        </div>
    );
}
