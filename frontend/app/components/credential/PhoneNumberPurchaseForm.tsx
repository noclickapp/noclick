// Buy a phone number for a workflow. The number IS the credential: the backend buys it at the provider, mints the
// phone_number credential and starts its monthly charge in one step, and hands back the credential id. On a purchase
// link (``confirmation``) a picked number is quoted first, and the owner confirms the quoted price (and, where its
// country asks, the holder's name and address, and its documents) before anything is charged. A number bought with
// documents waits on the carrier's review (``OrderReview``), and one it sends back is corrected on the link.
import { Clock3, Loader2 } from 'lucide-react';
import { Button } from '~/components/ui/button';
import { NumberFinder, PurchaseError, RequirementsStep } from '~/components/phone/NumberFinder';
import { capabilityLabels, formatNumber, holderNote, placeOf, reviewNote, textingNote } from '~/components/phone/numberDisplay';
import { RequirementFields, filingMissing, filingToSend, useFiling } from '~/components/phone/RequirementFields';
import type { OAuthExchange } from '~/hooks/oauth/OAuthExchangeContext';
import { TYPE_LABELS, usePhoneNumberPurchase, type NumberOrder, type PhonePurchaseQuote } from '~/hooks/usePhoneNumberPurchase';
import { countryName } from '~/components/ui/country-picker';
import { formatUsd } from '~/lib/money';

export type { PhonePurchaseQuote } from '~/hooks/usePhoneNumberPurchase';

type PurchaseState = { status: string; error?: string | null; phone_number?: string | null; order?: NumberOrder | null };

interface PhoneNumberPurchaseFormProps {
    onCredentialCreated: (credentialId: string, phoneNumber: string) => void;
    /** A number the carrier reviews first was ordered (outside a purchase link, whose page shows its order). */
    onOrdered?: (order: { order_id: string; phone_number: string }) => void;
    // Transport override (default: socket), the same seam the QR form exposes.
    sendEvent?: OAuthExchange;
    confirmation?: {
        initialQuote?: PhonePurchaseQuote | null;
        onState: (state: PurchaseState) => void;
    };
}

function QuoteReview({ quote, purchase }: { quote: PhonePurchaseQuote; purchase: ReturnType<typeof usePhoneNumberPurchase> }) {
    const items = quote.requirements.items;
    const filing = useFiling(quote.country, purchase.contactPhone);
    const missing = filingMissing(items, filing);
    const reviewed = quote.requirements.needs === 'documents';
    const kind = `${countryName(quote.country)} ${TYPE_LABELS[quote.number_type].toLowerCase()} number`;
    const can = capabilityLabels(quote.capabilities ?? []);
    const texting = quote.texting ? textingNote({ texting: quote.texting, country: quote.country }) : null;
    return (
        <div className="space-y-6" data-testid="phone-purchase-confirmation">
            <div>
                <p className="mb-2 text-xs text-muted-foreground">Your selected number</p>
                <p className="text-2xl font-medium tabular-nums tracking-tight">{formatNumber(quote.phone_number)}</p>
                <p className="mt-2 text-sm text-muted-foreground">{[kind, placeOf({ locality: quote.locality ?? '', region: quote.region ?? '', country: quote.country }), ...can].join(' · ')}</p>
                {texting && <p className="mt-1 text-xs text-muted-foreground">{texting}</p>}
            </div>
            <dl className="space-y-3 text-sm">
                <div className="flex justify-between gap-4">
                    <dt className="text-muted-foreground">{reviewed ? 'Due once approved' : 'Due today'}</dt>
                    <dd>{formatUsd(quote.monthly_credits + quote.upfront_credits)}</dd>
                </div>
                {quote.upfront_credits > 0 && (
                    <div className="flex justify-between gap-4">
                        <dt className="text-muted-foreground">Of which, one-time setup</dt>
                        <dd>{formatUsd(quote.upfront_credits)}</dd>
                    </div>
                )}
                <div className="flex justify-between gap-4">
                    <dt className="text-muted-foreground">Renews monthly</dt>
                    <dd>{formatUsd(quote.monthly_credits)}</dd>
                </div>
            </dl>
            {items.length > 0 && (
                <div className="space-y-4">
                    <p className="text-sm text-muted-foreground">{reviewed ? reviewNote(quote.country) : holderNote(quote.country)}</p>
                    <RequirementFields subject={quote} requirements={items} filing={filing} purchase={purchase} disabled={!!purchase.buying} />
                </div>
            )}
            <p className="text-xs leading-relaxed text-muted-foreground">
                {reviewed
                    ? 'Nothing is charged until the carrier approves the documents; then the first month'
                    : 'The first month'}
                {quote.upfront_credits > 0 ? ' and the setup are' : ' is'} charged{reviewed ? '' : ' when you confirm'}. Renews on the monthly anniversary while you keep the
                number. Call usage is billed separately. Delete the phone-number credential to release it and stop renewals.
            </p>
            <p className="text-xs text-muted-foreground">Available until purchased by someone else. Review price again if this confirmation expires.</p>
            <PurchaseError error={purchase.error} />
            <div className="flex flex-wrap items-center gap-2">
                <Button
                    type="button"
                    disabled={!!purchase.buying || missing.length > 0 || !!purchase.uploading}
                    onClick={() => void purchase.confirm(items.length ? filingToSend(items, filing) : {})}
                >
                    {purchase.buying ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                    {reviewed ? 'Submit for review' : 'Confirm purchase'} · {formatUsd(quote.monthly_credits + quote.upfront_credits)}
                </Button>
                <Button type="button" variant="ghost" disabled={!!purchase.buying} onClick={() => purchase.setQuote(null)}>
                    Choose another
                </Button>
            </div>
            {missing.length > 0 && <p className="text-xs text-muted-foreground">Still needed: {missing.join(', ')}.</p>}
        </div>
    );
}

/** A purchase link's number in the carrier's review: waiting on it, or sent back to correct and resubmit. */
export function OrderReview({ order, sendEvent, onState }: { order: NumberOrder; sendEvent: OAuthExchange; onState: (state: PurchaseState) => void }) {
    const purchase = usePhoneNumberPurchase({ sendEvent, confirmation: { onState }, onCredentialCreated: () => undefined, finding: false });
    if (order.status === 'rejected' && order.requirements) {
        return (
            <RequirementsStep
                number={{ ...order, requirements: order.requirements }}
                sentBack={order.reason}
                purchase={purchase}
                submitLabel="Resubmit"
                onSubmit={(filing) => void purchase.resubmit(order, filing)}
            />
        );
    }
    return (
        <div className="space-y-2" data-testid="order-in-review">
            <p className="flex items-center gap-2 text-2xl font-medium tabular-nums tracking-tight">
                <Clock3 className="h-5 w-5 text-muted-foreground" />
                {formatNumber(order.phone_number)}
            </p>
            <p className="text-sm leading-relaxed text-muted-foreground">
                The carrier is reviewing what you filed for this number, which can take a few days. You’ll get an email when it’s done; nothing is charged until
                it approves.
            </p>
        </div>
    );
}

export const PhoneNumberPurchaseForm = ({ onCredentialCreated, onOrdered, sendEvent, confirmation }: PhoneNumberPurchaseFormProps) => {
    const purchase = usePhoneNumberPurchase({ onCredentialCreated, onOrdered, sendEvent, confirmation });
    if (purchase.quote && confirmation) return <QuoteReview quote={purchase.quote} purchase={purchase} />;
    return (
        <div className="space-y-3">
            <p className="text-xs text-muted-foreground">
                {confirmation
                    ? 'Choose a number. Review its price before confirming.'
                    : 'A number your agents answer and call from, in any country numbers are sold in. Delete it to release the number.'}
            </p>
            <NumberFinder
                purchase={purchase}
                compact
                review={!!confirmation}
                list={(rows) => <div className="overflow-hidden rounded-xl border border-border">{rows}</div>}
            />
        </div>
    );
};
