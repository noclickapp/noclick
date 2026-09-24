// Group requests by connection while letting the owner decide any subset.
// Unlock requests and exact-call approvals use separate modes and explicit effects;
// the host supplies persistence, and this view submits only selected request IDs.
import { useId, useMemo, useState } from 'react';
import { Link } from 'react-router';
import {
    ArrowLeft,
    Check,
    ChevronDown,
    ChevronUp,
    KeyRound,
    X,
} from 'lucide-react';
import { HiOutlineLockClosed, HiOutlineLockOpen } from 'react-icons/hi2';
import { Button } from '~/components/ui/button';
import { Checkbox } from '~/components/ui/checkbox';
import { CredentialArguments } from './CredentialArguments';

interface RequestBase {
    id: string;
    credentialId: string;
    credentialName: string;
    account: string;
    iconUrl?: string;
    title: string;
    summary: string;
    status: 'pending' | 'approved' | 'rejected' | 'expired';
    error?: string;
}
export type UnlockRequest = RequestBase & { kind: 'unlock' };
export type CallRequest = RequestBase & {
    kind: 'call';
    arguments: Record<string, unknown>;
    toolUnlocked?: boolean;
};
export type CredentialReviewRequest = UnlockRequest | CallRequest;
export type CredentialReviewDecision =
    | 'approved'
    | 'approved_and_unlocked'
    | 'rejected';
type ReviewProps = {
    purpose: string;
    saving?: boolean;
    error?: string;
    onDecide: (
        requestIds: string[],
        decision: CredentialReviewDecision
    ) => void;
} & (
    | { mode: 'unlock'; requests: UnlockRequest[] }
    | { mode: 'calls'; requests: CallRequest[] }
);

export function CredentialRequestReview({
    mode,
    purpose,
    requests,
    saving,
    error,
    onDecide,
}: ReviewProps) {
    const prefix = useId();
    const [selected, setSelected] = useState<Set<string>>(
        () =>
            new Set(
                requests
                    .filter((item) => item.status === 'pending')
                    .map((item) => item.id)
            )
    );
    const [expanded, setExpanded] = useState<Set<string>>(new Set());
    const [dontAskAgain, setDontAskAgain] = useState(false);
    const unlock = mode === 'unlock';
    const pending = requests.filter((item) => item.status === 'pending');
    const chosen = pending.filter((item) => selected.has(item.id));
    const approvedCount = requests.filter(
        (item) => item.status === 'approved'
    ).length;
    const hasUnlockedCalls = requests.some(
        (item) => item.kind === 'call' && item.toolUnlocked
    );
    const groups = useMemo(() => {
        const byCredential = new Map<string, CredentialReviewRequest[]>();
        requests.forEach((item) => {
            const group = byCredential.get(item.credentialId) ?? [];
            group.push(item);
            byCredential.set(item.credentialId, group);
        });
        return [...byCredential.values()];
    }, [requests]);
    const select = (id: string, checked: boolean) => {
        setDontAskAgain(false);
        setSelected((previous) => {
            const next = new Set(previous);
            checked ? next.add(id) : next.delete(id);
            return next;
        });
    };
    const decide = (decision: CredentialReviewDecision) => {
        onDecide(
            chosen.map((item) => item.id),
            decision
        );
        setDontAskAgain(false);
    };
    const toggleDetails = (id: string) =>
        setExpanded((previous) => {
            const next = new Set(previous);
            next.has(id) ? next.delete(id) : next.add(id);
            return next;
        });
    const noun = unlock ? 'tool' : 'call';

    return (
        <main className="min-h-screen bg-background px-5 pb-8 pt-9 text-foreground sm:px-8 sm:pt-12">
            <div className="mx-auto max-w-3xl">
                <Link
                    to="/dashboard?tab=dashboard&focus=attention"
                    className="mb-8 flex w-fit items-center gap-2 text-sm text-muted-foreground transition-colors hover:text-foreground"
                >
                    <ArrowLeft className="h-4 w-4" /> Needs you
                </Link>
                <div className="mb-4 inline-flex items-center gap-2 text-xs font-medium text-muted-foreground">
                    {unlock ? (
                        <HiOutlineLockOpen className="h-4 w-4" />
                    ) : (
                        <HiOutlineLockClosed className="h-4 w-4" />
                    )}
                    {unlock ? 'Ongoing access' : 'Call approval'}
                </div>
                <h1 className="text-3xl font-semibold tracking-tight">
                    {unlock
                        ? 'Unlock selected tools'
                        : 'Review requested actions'}
                </h1>
                <p className="mt-3 max-w-xl text-sm leading-6 text-muted-foreground">
                    {unlock
                        ? 'Choose which tools can run without asking you in future. Everything else stays locked.'
                        : 'Approve the selected calls once, or choose to stop asking for these tools on these connections.'}
                </p>
                <div className="mb-8 mt-7 rounded-xl bg-foreground/[0.03] px-4 py-3.5">
                    <p className="text-xs text-muted-foreground">
                        Your coordinator is asking
                    </p>
                    <p className="mt-1 text-sm leading-6">{purpose}</p>
                </div>

                <div className="mb-6 flex flex-wrap items-center justify-between gap-3 text-xs text-muted-foreground">
                    <span>
                        {requests.length} {noun}
                        {requests.length === 1 ? '' : 's'} · {groups.length}{' '}
                        connections
                    </span>
                    {!!pending.length && (
                        <div className="flex items-center gap-1">
                            <button
                                type="button"
                                disabled={saving}
                                onClick={() => {
                                    setDontAskAgain(false);
                                    setSelected(
                                        new Set(pending.map((item) => item.id))
                                    );
                                }}
                                className="rounded-md px-2 py-1.5 hover:bg-foreground/[0.05] hover:text-foreground disabled:opacity-40"
                            >
                                Select all pending
                            </button>
                            <button
                                type="button"
                                disabled={saving || !chosen.length}
                                onClick={() => {
                                    setSelected(new Set());
                                    setDontAskAgain(false);
                                }}
                                className="rounded-md px-2 py-1.5 hover:bg-foreground/[0.05] hover:text-foreground disabled:opacity-40"
                            >
                                Clear
                            </button>
                        </div>
                    )}
                </div>

                {!!approvedCount && (
                    <p
                        role="status"
                        className="mb-6 flex items-center gap-2 text-sm"
                    >
                        <Check className="h-4 w-4" /> {approvedCount} {noun}
                        {approvedCount === 1 ? '' : 's'}{' '}
                        {unlock
                            ? 'unlocked'
                            : hasUnlockedCalls
                              ? 'approved'
                              : 'approved once'}
                        {pending.length
                            ? ` · ${pending.length} still pending`
                            : ' · All requests reviewed'}
                    </p>
                )}
                <div className="space-y-8">
                    {groups.map((group) => (
                        <section
                            key={group[0].credentialId}
                            aria-label={group[0].credentialName}
                        >
                            <div className="mb-3 flex items-center gap-3 px-1">
                                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-foreground/[0.04]">
                                    {group[0].iconUrl ? (
                                        <img
                                            src={group[0].iconUrl}
                                            alt=""
                                            className="h-5 w-5"
                                        />
                                    ) : (
                                        <KeyRound className="h-4 w-4 text-muted-foreground" />
                                    )}
                                </div>
                                <div className="min-w-0">
                                    <h2 className="text-sm font-medium">
                                        {group[0].credentialName}
                                    </h2>
                                    <p className="mt-0.5 truncate text-xs text-muted-foreground">
                                        {group[0].account}
                                    </p>
                                </div>
                            </div>
                            <div className="space-y-2">
                                {group.map((item) => {
                                    const available = item.status === 'pending';
                                    const checked =
                                        available && selected.has(item.id);
                                    const showDetails = expanded.has(item.id);
                                    const inputId = `${prefix}-${item.id}`;
                                    return (
                                        <div
                                            key={item.id}
                                            className={`rounded-xl transition-colors ${checked ? 'bg-foreground/[0.06] ring-1 ring-inset ring-foreground/15' : 'bg-foreground/[0.02]'} ${available ? 'hover:bg-foreground/[0.045]' : ''}`}
                                        >
                                            <div className="flex items-start gap-3 px-4 py-4">
                                                {available ? (
                                                    <Checkbox
                                                        id={inputId}
                                                        checked={checked}
                                                        disabled={saving}
                                                        onCheckedChange={(
                                                            value
                                                        ) =>
                                                            select(
                                                                item.id,
                                                                value === true
                                                            )
                                                        }
                                                        aria-label={`Select ${item.title} on ${item.credentialName}`}
                                                        className="mt-0.5 border-muted-foreground/40"
                                                    />
                                                ) : item.status ===
                                                  'approved' ? (
                                                    <Check className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
                                                ) : (
                                                    <X className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
                                                )}
                                                <div className="min-w-0 flex-1">
                                                    <label
                                                        htmlFor={
                                                            available
                                                                ? inputId
                                                                : undefined
                                                        }
                                                        className={`block ${available ? 'cursor-pointer' : ''}`}
                                                    >
                                                        <span className="block text-sm font-medium">
                                                            {item.title}
                                                        </span>
                                                        <span className="mt-1 block text-xs leading-5 text-muted-foreground">
                                                            {item.summary}
                                                        </span>
                                                    </label>
                                                    {!available && (
                                                        <p className="mt-2 inline-flex items-center gap-1.5 text-xs text-muted-foreground">
                                                            {(unlock ||
                                                                (item.kind ===
                                                                    'call' &&
                                                                    item.toolUnlocked)) &&
                                                            item.status ===
                                                                'approved' ? (
                                                                <HiOutlineLockOpen className="h-3.5 w-3.5" />
                                                            ) : (
                                                                <HiOutlineLockClosed className="h-3.5 w-3.5" />
                                                            )}
                                                            {item.status ===
                                                            'approved'
                                                                ? unlock
                                                                    ? 'Unlocked for future calls'
                                                                    : item.kind ===
                                                                            'call' &&
                                                                        item.toolUnlocked
                                                                      ? 'Approved · Tool unlocked for future calls'
                                                                      : 'Approved once · Tool stays locked'
                                                                : item.status ===
                                                                    'expired'
                                                                  ? 'Expired · Still locked'
                                                                  : 'Declined · Still locked'}
                                                        </p>
                                                    )}
                                                    {item.error && (
                                                        <p
                                                            role="alert"
                                                            className="mt-2 text-xs text-destructive"
                                                        >
                                                            {item.error}
                                                        </p>
                                                    )}
                                                </div>
                                                {item.kind === 'call' && (
                                                    <button
                                                        type="button"
                                                        onClick={() =>
                                                            toggleDetails(
                                                                item.id
                                                            )
                                                        }
                                                        aria-expanded={
                                                            showDetails
                                                        }
                                                        aria-controls={`${inputId}-details`}
                                                        aria-label={`${showDetails ? 'Hide' : 'View'} details for ${item.title} on ${item.credentialName}`}
                                                        className="inline-flex shrink-0 items-center gap-1 rounded-md px-1.5 py-1 text-xs text-muted-foreground hover:bg-foreground/[0.05] hover:text-foreground"
                                                    >
                                                        Details{' '}
                                                        {showDetails ? (
                                                            <ChevronUp className="h-3.5 w-3.5" />
                                                        ) : (
                                                            <ChevronDown className="h-3.5 w-3.5" />
                                                        )}
                                                    </button>
                                                )}
                                            </div>
                                            {item.kind === 'call' &&
                                                showDetails && (
                                                    <div
                                                        id={`${inputId}-details`}
                                                        className="mx-4 mb-4 rounded-lg bg-background/60 px-4 pb-5 pt-0.5 sm:ml-11"
                                                    >
                                                        <CredentialArguments
                                                            arguments={
                                                                item.arguments
                                                            }
                                                        />
                                                    </div>
                                                )}
                                        </div>
                                    );
                                })}
                            </div>
                        </section>
                    ))}
                </div>
                {!!pending.length ? (
                    <div className="sticky bottom-0 mt-9 bg-background/95 py-5 backdrop-blur">
                        {!unlock && (
                            <div className="mb-5 flex items-start gap-3">
                                <Checkbox
                                    id={`${prefix}-dont-ask-again`}
                                    checked={dontAskAgain}
                                    disabled={saving || !chosen.length}
                                    onCheckedChange={(value) =>
                                        setDontAskAgain(value === true)
                                    }
                                    aria-describedby={`${prefix}-unlock-scope`}
                                    className="mt-0.5 border-muted-foreground/40"
                                />
                                <div>
                                    <label
                                        htmlFor={`${prefix}-dont-ask-again`}
                                        className="cursor-pointer text-sm font-medium"
                                    >
                                        Don’t ask again for these tools
                                    </label>
                                    <p
                                        id={`${prefix}-unlock-scope`}
                                        className="mt-1 max-w-xl text-xs leading-5 text-muted-foreground"
                                    >
                                        Unlocks only the tools used by selected
                                        calls on these connections. Future calls
                                        with different details won’t need
                                        approval either.
                                    </p>
                                </div>
                            </div>
                        )}
                        <div className="flex flex-wrap items-center justify-between gap-4">
                            <div>
                                <p className="text-sm font-medium">
                                    {chosen.length} of {pending.length} pending
                                    selected
                                </p>
                                <p className="mt-1 text-xs text-muted-foreground">
                                    {unlock
                                        ? 'Unselected tools stay locked and pending.'
                                        : dontAskAgain
                                          ? 'Other tools and connections keep their current rules.'
                                          : 'Approve once to keep these tools locked.'}
                                </p>
                            </div>
                            <div className="flex items-center gap-2">
                                <Button
                                    variant="ghost"
                                    disabled={!chosen.length || saving}
                                    onClick={() => decide('rejected')}
                                >
                                    Decline selected
                                </Button>
                                <Button
                                    disabled={!chosen.length || saving}
                                    onClick={() =>
                                        decide(
                                            !unlock && dontAskAgain
                                                ? 'approved_and_unlocked'
                                                : 'approved'
                                        )
                                    }
                                >
                                    {saving
                                        ? 'Saving…'
                                        : !chosen.length
                                          ? unlock
                                              ? 'Unlock selected'
                                              : 'Approve selected once'
                                          : unlock
                                            ? `Unlock ${chosen.length || ''} ${chosen.length === 1 ? 'tool' : 'tools'}`
                                            : dontAskAgain
                                              ? `Approve ${chosen.length} ${chosen.length === 1 ? 'call' : 'calls'} & unlock tools`
                                              : `Approve ${chosen.length || ''} ${chosen.length === 1 ? 'call' : 'calls'} once`}
                                </Button>
                            </div>
                        </div>
                        {!unlock && !dontAskAgain && (
                            <p className="mt-3 text-xs leading-5 text-muted-foreground">
                                Each approval is for the exact details shown and
                                can be used once within 30 minutes.
                            </p>
                        )}
                        {error && (
                            <p
                                role="alert"
                                className="mt-3 text-sm text-destructive"
                            >
                                {error}
                            </p>
                        )}
                    </div>
                ) : (
                    <div className="mt-8 flex items-center gap-2 py-5 text-sm text-muted-foreground">
                        <Check className="h-4 w-4" /> All requests reviewed.{' '}
                        {unlock
                            ? 'Only approved tools were unlocked.'
                            : hasUnlockedCalls
                              ? 'Only the tools you chose were unlocked.'
                              : 'Your connection rules are unchanged.'}
                    </div>
                )}
            </div>
        </main>
    );
}
