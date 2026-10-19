// Finding and buying a number, the one flow every surface that sells numbers shows: the filters, the numbers for sale
// with their own prices, a buy that asks once, in place, with what's charged now, and, for a country that asks who holds
// a number or for documents, what it asks as a step of its own. A number bought with documents is in the carrier's
// review until it approves them: the numbers in review are listed above the search, and one the carrier sent back is
// corrected and resubmitted in the same step. On a confirmation link the row's button prepares the reviewed quote
// instead (``review``); the surface shows it.
import { useState, type ReactNode } from 'react';
import { Link } from 'react-router';
import { AlertCircle, ArrowLeft, ChevronRight, Clock3, FileText, Globe, Loader2 } from 'lucide-react';
import { BUTTON_PRIMARY, BUTTON_SECONDARY } from '~/components/shell/buttons';
import { countryName } from '~/components/ui/country-picker';
import { Skeleton } from '~/components/ui/skeleton';
import type { AvailableNumber, NumberFiling, NumberOrder, PhoneNumberPurchase } from '~/hooks/usePhoneNumberPurchase';
import { cn } from '~/lib/utils';
import { NumberFilters } from './NumberFilters';
import { NumberRow } from './NumberRow';
import { documentsAsked, documentsSummary, dueNow, formatNumber, holderNote, placeOf, priceText, reviewNote, textingNote } from './numberDisplay';
import { RequirementFields, filingMissing, filingToSend, useFiling } from './RequirementFields';

type Priced = Pick<AvailableNumber, 'monthly_credits' | 'upfront_credits'> & { requirements?: AvailableNumber['requirements'] };

/** What buying it charges, in a sentence a person agrees to; one the carrier reviews is charged once it approves it. */
export function chargeSentence(number: Priced): string {
    const price = priceText(number);
    const then = `then ${price.monthly} every month while you keep it. Delete it any time to release the number.`;
    if (number.requirements?.needs === 'documents') {
        const due = price.upfront ? `${dueNow(number)} (${price.upfront} to set it up and the first month)` : price.monthly;
        return `Nothing is charged until the carrier approves the documents. Then ${due} is charged, ${then}`;
    }
    const now = price.upfront ? `${dueNow(number)} is charged now (${price.upfront} to set it up and the first month)` : `${price.monthly} is charged now`;
    return `${now}, ${then}`;
}

export function PurchaseError({ error }: { error: PhoneNumberPurchase['error'] }) {
    if (!error) return null;
    return (
        <p role="alert" className="text-[13.5px] text-red-600 dark:text-red-400">
            {error.text}
            {error.kind === 'credits' && (
                <Link to="/dashboard?action=topup" className="ml-1.5 font-medium text-foreground underline underline-offset-4">
                    Top up
                </Link>
            )}
        </p>
    );
}

/** What a search's numbers ask before they're sold, said once above the list: documents, added when one is bought (or,
 *  where this surface doesn't file them, where to buy it), or a step that can't be taken here, so no Buy. */
function AskedNote({ requirements, filesDocuments }: { requirements: AvailableNumber['requirements']; filesDocuments: boolean }) {
    const asked = documentsAsked(requirements);
    const steps = requirements.needs === 'steps';
    return (
        <div className="text-[13.5px] leading-snug" data-testid={steps ? 'needs-steps' : 'needs-documents'}>
            <p className="flex items-start gap-2 text-foreground/85">
                <FileText className="mt-[1px] h-4 w-4 shrink-0 text-amber-600 dark:text-amber-400" strokeWidth={1.75} />
                <span>
                    {steps
                        ? 'Buying these numbers here isn’t available yet: their country asks for a step the carrier takes with the holder itself, such as an identity check at its own link.'
                        : filesDocuments
                          ? `These numbers need ${documentsSummary(requirements)}. You add them when you buy one, and the carrier reviews them before it’s yours.`
                          : `These numbers need ${documentsSummary(requirements)}, which aren’t filed here: buy one in the app, or through the API with its documents.`}
                </span>
            </p>
            {asked.length > 0 && (
                <details className="group mt-1.5 pl-6">
                    <summary className="inline-flex cursor-pointer list-none items-center gap-1 text-[12.5px] text-muted-foreground transition-colors hover:text-foreground [&::-webkit-details-marker]:hidden">
                        <ChevronRight className="h-3.5 w-3.5 transition-transform group-open:rotate-90" />
                        What’s asked ({asked.length})
                    </summary>
                    <ul className="mt-1.5 list-disc space-y-0.5 pl-5 text-[12.5px] text-muted-foreground">
                        {asked.map((name) => (
                            <li key={name}>{name}</li>
                        ))}
                    </ul>
                </details>
            )}
        </div>
    );
}

/** A number, or an order the carrier sent back, as the step that takes what its country asks. */
type Subject = Pick<AvailableNumber, 'phone_number' | 'country' | 'number_type' | 'monthly_credits' | 'upfront_credits' | 'requirements'> &
    Partial<Pick<AvailableNumber, 'locality' | 'region'>>;

export function RequirementsStep({
    number,
    sentBack,
    purchase,
    onBack,
    onSubmit,
    submitLabel,
}: {
    number: Subject;
    /** The carrier's words, where it sent the order back. */
    sentBack?: string | null;
    purchase: PhoneNumberPurchase;
    onBack?: () => void;
    onSubmit: (filing: NumberFiling) => void;
    submitLabel: string;
}) {
    const filing = useFiling(number.country, purchase.contactPhone);
    const items = number.requirements.items;
    const missing = filingMissing(items, filing);
    const busy = purchase.buying === number.phone_number;
    const reviewed = number.requirements.needs === 'documents';
    return (
        <div className="space-y-5" data-testid="requirements-step">
            {onBack && (
                <button type="button" onClick={onBack} disabled={busy} className="inline-flex items-center gap-1.5 text-[13.5px] text-muted-foreground transition-colors hover:text-foreground">
                    <ArrowLeft className="h-4 w-4" />
                    {sentBack !== undefined ? 'Back' : 'Other numbers'}
                </button>
            )}
            <div>
                <p className="text-[20px] font-medium tabular-nums tracking-tight text-foreground">{formatNumber(number.phone_number)}</p>
                <p className="mt-1 text-[13.5px] text-muted-foreground">{placeOf({ locality: number.locality ?? '', region: number.region ?? '', country: number.country })}</p>
                <p className="mt-3 max-w-xl text-[13.5px] leading-relaxed text-muted-foreground">{reviewed ? reviewNote(number.country) : holderNote(number.country)}</p>
            </div>
            {sentBack !== undefined && (
                <p className="flex max-w-xl items-start gap-2 text-[13.5px] leading-snug text-foreground/85" data-testid="sent-back">
                    <AlertCircle className="mt-[1px] h-4 w-4 shrink-0 text-amber-600 dark:text-amber-400" strokeWidth={1.75} />
                    <span>
                        The carrier sent it back{sentBack ? `: “${sentBack}”` : '.'} Correct what it asks and resubmit; nothing is charged until it approves.
                    </span>
                </p>
            )}
            <RequirementFields subject={number} requirements={items} filing={filing} purchase={purchase} disabled={busy} />
            <p className="max-w-xl text-[13px] leading-snug text-muted-foreground">{chargeSentence(number)}</p>
            <PurchaseError error={purchase.error} />
            <button type="button" disabled={busy || missing.length > 0 || !!purchase.uploading} onClick={() => onSubmit(filingToSend(items, filing))} className={BUTTON_PRIMARY}>
                {busy && <Loader2 className="h-4 w-4 animate-spin" />}
                {submitLabel}
            </button>
            {missing.length > 0 && <p className="text-[12.5px] text-muted-foreground">Still needed: {missing.join(', ')}.</p>}
        </div>
    );
}

/** The account's numbers the carrier is reviewing, or sent back to correct. */
function NumberOrders({ orders, onFix, compact }: { orders: NumberOrder[]; onFix: (order: NumberOrder) => void; compact: boolean }) {
    return (
        <div className="space-y-2" data-testid="number-orders">
            <p className="text-[13px] font-medium text-foreground/85">In review</p>
            <div className="divide-y divide-border dark:divide-foreground/[0.06]">
                {orders.map((order) => {
                    const sentBack = order.status === 'rejected';
                    return (
                        <div key={order.id} className={cn('flex flex-wrap items-center gap-x-3 gap-y-1.5', compact ? 'py-2' : 'py-3')} data-testid="number-order">
                            {sentBack ? (
                                <AlertCircle className="h-4 w-4 shrink-0 text-amber-600 dark:text-amber-400" strokeWidth={1.75} />
                            ) : (
                                <Clock3 className="h-4 w-4 shrink-0 text-muted-foreground" strokeWidth={1.75} />
                            )}
                            <div className="min-w-0 flex-[1_1_14rem]">
                                <p className="truncate text-[14px] font-medium tabular-nums text-foreground">{formatNumber(order.phone_number)}</p>
                                <p className="mt-0.5 text-[12.5px] leading-snug text-muted-foreground">
                                    {sentBack
                                        ? `Changes needed${order.reason ? `: ${order.reason}` : ''}`
                                        : `The carrier is reviewing its documents. You’ll get an email when it’s done; nothing is charged until then.`}
                                </p>
                            </div>
                            {sentBack && (
                                <button type="button" onClick={() => onFix(order)} className={cn(BUTTON_SECONDARY, 'h-8 px-3.5 text-[13px]')}>
                                    Fix and resubmit
                                </button>
                            )}
                        </div>
                    );
                })}
            </div>
        </div>
    );
}

export function NumberFinder({
    purchase,
    compact = false,
    review = false,
    list = (rows) => rows,
}: {
    purchase: PhoneNumberPurchase;
    compact?: boolean;
    /** A confirmation link: the row's button prepares a quote to review. */
    review?: boolean;
    /** Wraps the rows (a page sets them on a surface). */
    list?: (rows: ReactNode) => ReactNode;
}) {
    const [confirming, setConfirming] = useState<string | null>(null);
    const [answering, setAnswering] = useState<AvailableNumber | null>(null);
    const [fixing, setFixing] = useState<NumberOrder | null>(null);
    const { numbers, searched, searching, buying, busy, error, filters } = purchase;
    const closed = error && (error.kind === 'unavailable' || error.kind === 'gated');

    if (closed) {
        return (
            <div className="flex flex-col items-center px-6 py-16 text-center" data-testid="numbers-unavailable">
                <span className="grid h-11 w-11 place-items-center rounded-full bg-foreground/[0.05]">
                    <Globe className="h-5 w-5 text-foreground/70" strokeWidth={1.75} />
                </span>
                <p className="mt-4 text-[15px] font-semibold text-foreground">Numbers aren’t available here</p>
                <p className="mt-1 max-w-sm text-balance text-[14px] leading-relaxed text-muted-foreground">{error.text}</p>
            </div>
        );
    }
    if (fixing?.requirements) {
        return (
            <RequirementsStep
                number={{ ...fixing, requirements: fixing.requirements }}
                sentBack={fixing.reason}
                purchase={purchase}
                onBack={() => setFixing(null)}
                submitLabel="Resubmit"
                onSubmit={async (filing) => {
                    if (await purchase.resubmit(fixing, filing)) setFixing(null);
                }}
            />
        );
    }
    if (answering) {
        return (
            <RequirementsStep
                number={answering}
                purchase={purchase}
                onBack={() => setAnswering(null)}
                submitLabel={answering.requirements.needs === 'documents' ? 'Submit for review' : `Buy for ${dueNow(answering)}`}
                onSubmit={async (filing) => {
                    if (await purchase.buy(answering, filing)) setAnswering(null);
                }}
            />
        );
    }

    const pattern = searched?.filters.contains ?? '';
    // Requirements are the country's and kind's, so a search's numbers share them: said once, above the list.
    const asked = numbers?.find((n) => n.requirements.needs === 'steps' || n.requirements.needs === 'documents')?.requirements;
    const buyable = (n: AvailableNumber) => n.requirements.needs !== 'steps' && (n.requirements.needs !== 'documents' || purchase.filesDocuments);
    const row = (n: AvailableNumber) => {
        const asking = confirming === n.phone_number;
        const choose = () => {
            if (review) void purchase.buy(n);
            else if (n.requirements.needs === 'address' || n.requirements.needs === 'documents') setAnswering(n);
            else setConfirming(n.phone_number);
        };
        const action = asking || !buyable(n) ? null : (
            <button
                type="button"
                onClick={choose}
                disabled={busy}
                aria-label={`${review ? 'Review' : 'Buy'} ${formatNumber(n.phone_number)}`}
                className={cn(BUTTON_SECONDARY, 'h-8 px-3.5 text-[13px]')}
            >
                {review && buying === n.phone_number ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
                {review ? 'Review' : 'Buy'}
            </button>
        );
        return (
            <NumberRow key={n.phone_number} number={n} pattern={pattern} action={action} highlighted={asking} compact={compact}>
                {asking && (
                    <div className={cn('mt-3 flex flex-wrap items-center gap-x-4 gap-y-2.5', !compact && 'sm:pl-[54px]')}>
                        <div className="min-w-0 flex-[1_1_16rem] space-y-1">
                            <p className="text-[13px] leading-snug text-muted-foreground">{chargeSentence(n)}</p>
                            {textingNote(n) && <p className="text-[12.5px] leading-snug text-muted-foreground">{textingNote(n)}</p>}
                        </div>
                        <div className="flex shrink-0 items-center gap-1">
                            <button
                                type="button"
                                onClick={() => setConfirming(null)}
                                disabled={!!buying}
                                className="inline-flex h-9 items-center rounded-full px-3 text-[13.5px] text-muted-foreground transition-colors hover:text-foreground"
                            >
                                Cancel
                            </button>
                            <button type="button" onClick={() => void purchase.buy(n)} disabled={!!buying} className={BUTTON_PRIMARY}>
                                {buying === n.phone_number && <Loader2 className="h-4 w-4 animate-spin" />}
                                Buy for {dueNow(n)}
                            </button>
                        </div>
                    </div>
                )}
            </NumberRow>
        );
    };

    return (
        <div className={cn('flex flex-col', compact ? 'gap-3' : 'gap-5')}>
            {purchase.orders.length > 0 && <NumberOrders orders={purchase.orders} onFix={setFixing} compact={compact} />}
            <NumberFilters purchase={purchase} compact={compact} />
            <PurchaseError error={error} />
            {purchase.notSold && filters ? (
                <p className="py-8 text-center text-[14px] text-muted-foreground" data-testid="not-sold">
                    Numbers aren’t sold in {countryName(filters.country)} yet. Choose another country.
                </p>
            ) : (searching || !filters) && numbers === null && !error ? (
                list(
                    <div className="divide-y divide-border dark:divide-foreground/[0.06]">
                        {[0, 1, 2].map((i) => (
                            <div key={i} className="flex items-center gap-3.5 px-4 py-3.5">
                                <Skeleton className="h-10 w-10 rounded-xl" />
                                <div className="flex-1 space-y-1.5">
                                    <Skeleton className="h-3.5 w-36" />
                                    <Skeleton className="h-3 w-48" />
                                </div>
                            </div>
                        ))}
                    </div>
                )
            ) : numbers && numbers.length > 0 ? (
                <>
                    {asked && <AskedNote requirements={asked} filesDocuments={purchase.filesDocuments} />}
                    {list(<div className={cn('divide-y divide-border transition-opacity dark:divide-foreground/[0.06]', searching && 'opacity-60')}>{numbers.map(row)}</div>)}
                    {purchase.canShowMore && (
                        <div className="flex justify-center">
                            <button type="button" disabled={busy} onClick={() => void purchase.showMore()} className={BUTTON_SECONDARY}>
                                More numbers
                            </button>
                        </div>
                    )}
                </>
            ) : numbers ? (
                <div className="py-8 text-center" data-testid="no-numbers">
                    <p className="text-[14px] text-muted-foreground">Nothing for sale matches this search.</p>
                    {purchase.loosen.length > 0 && (
                        <div className="mt-3 flex flex-wrap justify-center gap-1.5">
                            {purchase.loosen.map((l) => (
                                <button key={l.label} type="button" disabled={busy} onClick={() => purchase.update(l.change)} className={cn(BUTTON_SECONDARY, 'h-8 px-3.5 text-[13px]')}>
                                    {l.label}
                                </button>
                            ))}
                        </div>
                    )}
                </div>
            ) : null}
        </div>
    );
}
