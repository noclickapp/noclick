// Buy a phone number for a workflow. The number IS the credential: the backend
// buys it at the provider, mints the phone_number credential and starts its
// monthly charge in one step, and hands back the credential id.
import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router';
import { AlertCircle, Loader2, Search } from 'lucide-react';
import { sendEventAsync } from '~/lib/socket-sender';
import type { OAuthExchange } from '~/hooks/oauth/OAuthExchangeContext';
import { formatPhoneForDisplay, patternSpan, searchQueryFromText } from '~/lib/phoneFormat';
import { invalidateCredentialsCache } from '~/utils/credentialAutoSelect';
import { Badge } from '~/components/ui/badge';
import { Button } from '~/components/ui/button';
import { Input } from '~/components/ui/input';
import { Skeleton } from '~/components/ui/skeleton';
import { UpgradePopup } from '~/components/utils/UpgradePopup';

interface AvailableNumber {
    phone_number: string;
    locality: string;
    region: string;
    capabilities: string[];
}

type Reply<T> = Partial<T> & { error?: string; kind?: string };

const DEFAULT_MONTHLY_CREDITS = 15;
const FIRST_PAGE = 10;
const MORE_PAGE = 20;
const CAPABILITY_LABELS: Record<string, string> = { voice: 'Voice', SMS: 'SMS', MMS: 'MMS' };

const failureText = (reply: Reply<unknown>, fallback: string): string => {
    switch (reply.kind) {
        case 'gated':
            return 'Phone numbers are not enabled on this account yet.';
        case 'unavailable':
            return 'Numbers cannot be bought on this instance.';
        case 'plan':
            return 'Phone numbers are available on the Plus and Pro plans.';
        default:
            return reply.error || fallback;
    }
};

/** A number with the part the pattern matched set in bold, so a search for
 *  "555" or "NOCLICK" shows why each result is there. */
function NumberLabel({ e164, pattern }: { e164: string; pattern: string }) {
    const shown = formatPhoneForDisplay(e164);
    const span = patternSpan(e164, pattern);
    if (!span) return <span className="font-medium tabular-nums text-foreground">{shown}</span>;
    // Map digit positions back onto the grouped display (spaces and the + are skipped).
    const parts: { text: string; hit: boolean }[] = [];
    let digitIndex = 0;
    for (const ch of shown) {
        const isDigit = /\d/.test(ch);
        const hit = isDigit && digitIndex >= span[0] && digitIndex < span[1];
        if (isDigit) digitIndex += 1;
        const last = parts[parts.length - 1];
        if (last && last.hit === hit) last.text += ch;
        else parts.push({ text: ch, hit });
    }
    return (
        <span className="font-medium tabular-nums text-foreground">
            {parts.map((p, i) => (p.hit ? <mark key={i} className="rounded-sm bg-primary/20 px-0.5 text-foreground">{p.text}</mark> : <span key={i}>{p.text}</span>))}
        </span>
    );
}

interface PhoneNumberPurchaseFormProps {
    onCredentialCreated: (credentialId: string, phoneNumber: string) => void;
    // Transport override (default: socket), the same seam the QR form exposes.
    sendEvent?: OAuthExchange;
    confirmation?: {
        initialQuote?: PhonePurchaseQuote | null;
        onState: (state: { status: string; error?: string | null; phone_number?: string | null }) => void;
    };
}

export interface PhonePurchaseQuote {
    id: string;
    phone_number: string;
    monthly_credits: number;
    expires_at: string;
}

export const PhoneNumberPurchaseForm = ({ onCredentialCreated, sendEvent, confirmation }: PhoneNumberPurchaseFormProps) => {
    const [text, setText] = useState('');
    const [searched, setSearched] = useState<{ areaCode: string | null; pattern: string | null; limit: number } | null>(null);
    const [numbers, setNumbers] = useState<AvailableNumber[] | null>(null);
    const [monthlyCredits, setMonthlyCredits] = useState(DEFAULT_MONTHLY_CREDITS);
    const [searching, setSearching] = useState(false);
    const [buying, setBuying] = useState<string | null>(null);
    const [error, setError] = useState<{ text: string; kind?: string } | null>(null);
    const [upgradeOpen, setUpgradeOpen] = useState(false);
    const [quote, setQuote] = useState(confirmation?.initialQuote ?? null);
    const submitting = useRef(false);
    const sendRef = useRef(sendEvent ?? sendEventAsync);
    useEffect(() => { sendRef.current = sendEvent ?? sendEventAsync; }, [sendEvent]);

    const search = async (limit = FIRST_PAGE) => {
        setSearching(true);
        setError(null);
        const wanted = searchQueryFromText(text);
        const query = { areaCode: wanted.area_code, pattern: wanted.contains, limit };
        try {
            const reply: Reply<{ numbers: AvailableNumber[]; monthly_credits: number }> = await sendRef.current({
                event_name: 'phone_number:search',
                country: 'US',
                area_code: query.areaCode,
                contains: query.pattern,
                limit,
            });
            if (reply.error) {
                if (reply.kind === 'plan') { setUpgradeOpen(true); return; }
                setError({ text: failureText(reply, 'Could not search for numbers.'), kind: reply.kind });
                return;
            }
            setSearched(query);
            setNumbers(reply.numbers ?? []);
            if (reply.monthly_credits) setMonthlyCredits(reply.monthly_credits);
        } catch (e) {
            setError({ text: e instanceof Error ? e.message : 'Could not search for numbers.' });
        } finally {
            setSearching(false);
        }
    };

    const buy = async (phoneNumber: string) => {
        if (submitting.current) return;
        submitting.current = true;
        setBuying(phoneNumber);
        setError(null);
        try {
            if (confirmation) {
                const reply = await sendRef.current({ event_name: 'phone_number:quote', phone_number: phoneNumber });
                if (reply.error || !reply.quote) {
                    setError({ text: failureText(reply, 'Could not prepare that number.'), kind: reply.kind });
                } else {
                    setQuote(reply.quote);
                }
                return;
            }
            const reply: Reply<{ credential_id: string; phone_number: string }> = await sendRef.current({
                event_name: 'phone_number:buy',
                phone_number: phoneNumber,
            });
            if (reply.error || !reply.credential_id) {
                if (reply.kind === 'plan') { setUpgradeOpen(true); return; }
                setError({ text: failureText(reply, 'Could not buy that number.'), kind: reply.kind });
                return;
            }
            invalidateCredentialsCache();
            onCredentialCreated(reply.credential_id, reply.phone_number ?? phoneNumber);
        } catch (e) {
            setError({ text: e instanceof Error ? e.message : 'Could not buy that number.' });
        } finally {
            submitting.current = false;
            setBuying(null);
        }
    };

    const confirm = async () => {
        if (!quote || submitting.current || !confirmation) return;
        submitting.current = true;
        setBuying(quote.phone_number);
        setError(null);
        try {
            const reply = await sendRef.current({ event_name: 'phone_number:confirm', quote_id: quote.id });
            if (reply.status === 'fulfilled' && reply.credential_id) {
                invalidateCredentialsCache();
                onCredentialCreated(reply.credential_id, reply.phone_number);
            } else if (reply.status === 'provisioning') {
                confirmation.onState(reply);
            } else {
                setQuote(null);
                setError({ text: failureText(reply, 'Select the number again to review its current price.'), kind: reply.kind });
            }
        } catch {
            confirmation.onState({ status: 'provisioning', error: 'Connection interrupted. Check the request status before trying again.' });
        } finally {
            submitting.current = false;
            setBuying(null);
        }
    };

    const canShowMore = numbers !== null && searched !== null && searched.limit < MORE_PAGE && numbers.length >= searched.limit;
    const busy = searching || !!buying;

    return (
        <div className="space-y-3">
            {quote && confirmation ? (
                <div className="space-y-6 rounded-2xl bg-foreground/[0.035] p-6" data-testid="phone-purchase-confirmation">
                    <div>
                        <p className="mb-2 text-xs text-muted-foreground">Your selected number</p>
                        <p className="text-2xl font-medium tracking-tight">{formatPhoneForDisplay(quote.phone_number)}</p>
                        <p className="mt-2 text-sm text-muted-foreground">US local number · Voice</p>
                    </div>
                    <dl className="space-y-3 text-sm">
                        <div className="flex justify-between gap-4"><dt className="text-muted-foreground">Due today</dt><dd>{quote.monthly_credits} credits</dd></div>
                        <div className="flex justify-between gap-4"><dt className="text-muted-foreground">Renews monthly</dt><dd>{quote.monthly_credits} credits</dd></div>
                    </dl>
                    <p className="text-xs leading-relaxed text-muted-foreground">The first month is charged when you confirm. Renews on the monthly anniversary while you keep the number. Call usage is billed separately. Delete the phone-number credential to release it and stop renewals.</p>
                    <p className="text-xs text-muted-foreground">Available until purchased by someone else. Review price again if this confirmation expires.</p>
                    <div className="flex flex-wrap items-center gap-2">
                        <Button type="button" disabled={busy} onClick={() => void confirm()}>
                            {buying ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                            Confirm purchase · {quote.monthly_credits} credits
                        </Button>
                        <Button type="button" variant="ghost" disabled={busy} onClick={() => setQuote(null)}>Choose another</Button>
                    </div>
                </div>
            ) : <>
            <UpgradePopup
                isOpen={upgradeOpen}
                onOpenChange={setUpgradeOpen}
                title="Phone numbers are on Plus and Pro"
                description={`A number your agent answers and calls from, ${monthlyCredits} credits a month. Upgrade to buy one.`}
            />
            <p className="text-xs text-muted-foreground">
                {confirmation ? 'Choose a US number. Review the price before confirming.' : `Buy a US number for this agent, ${monthlyCredits} credits a month. Delete the credential to release it.`}
            </p>
            <div className="flex max-w-xl items-center gap-2">
                <div className="relative min-w-0 flex-1">
                    <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
                    <Input
                        value={text}
                        onChange={(e) => setText(e.target.value.toUpperCase().replace(/[^0-9A-Z*]/g, '').slice(0, 10))}
                        onKeyDown={(e) => { if (e.key === 'Enter') void search(); }}
                        placeholder="Area code or digits, e.g. 415 or NOCLICK"
                        aria-label="Digits or letters the number should contain"
                        // The panel's wash, not the page ground: bg-background is pure
                        // black in dark mode and read as a slab on the card.
                        className="h-8 border-border bg-foreground/[0.04] pl-8 text-xs shadow-none placeholder:text-xs focus-visible:border-foreground/30 focus-visible:ring-0 focus-visible:ring-offset-0 md:text-xs"
                        disabled={busy}
                    />
                </div>
                <Button type="button" size="sm" variant="secondary" className="h-8 shrink-0 text-xs font-medium" onClick={() => void search()} disabled={busy}>
                    {searching ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
                    Find numbers
                </Button>
            </div>
            {error && (
                <div className="flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/10 p-2 text-xs text-destructive">
                    <AlertCircle className="mt-0.5 h-3.5 w-3.5 flex-shrink-0" />
                    <span>
                        {error.text}
                        {error.kind === 'credits' && (
                            <>
                                {' '}
                                <Link to="/dashboard?action=topup" className="underline">Top up credits</Link>
                            </>
                        )}
                        {error.kind === 'plan' && (
                            <>
                                {' '}
                                <Link to="/pricing" className="underline">See plans</Link>
                            </>
                        )}
                    </span>
                </div>
            )}
            {searching && numbers === null && (
                <div className="space-y-2 rounded-md border border-border p-3">
                    {[0, 1, 2].map((i) => <Skeleton key={i} className="h-8 w-full" />)}
                </div>
            )}
            {numbers && numbers.length === 0 && !error && (
                <div className="rounded-md border border-dashed border-border p-3 text-xs text-muted-foreground">
                    No numbers match{searched?.pattern ? <> the pattern <span className="font-mono">{searched.pattern}</span></> : ''}
                    {searched?.areaCode ? <> in area code {searched.areaCode}</> : ''}. Try fewer digits or
                    another area code.
                </div>
            )}
            {numbers && numbers.length > 0 && (
                <div className="space-y-2">
                    <ul className="divide-y divide-border rounded-md border border-border">
                        {numbers.map((n) => (
                            <li key={n.phone_number} className="flex items-center justify-between gap-3 px-3 py-2">
                                <div className="min-w-0 space-y-1">
                                    <NumberLabel e164={n.phone_number} pattern={searched?.pattern ?? ''} />
                                    <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                                        <span className="truncate">{[n.locality, n.region].filter(Boolean).join(', ') || 'United States'}</span>
                                        {n.capabilities.filter((c) => CAPABILITY_LABELS[c] && (!confirmation || c === 'voice')).map((c) => (
                                            <Badge key={c} variant="secondary" className="h-4 px-1.5 text-[10px] font-normal">
                                                {CAPABILITY_LABELS[c]}
                                            </Badge>
                                        ))}
                                    </div>
                                </div>
                                <Button type="button" size="sm" onClick={() => void buy(n.phone_number)} disabled={busy}>
                                    {buying === n.phone_number ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
                                    {confirmation ? 'Review' : 'Buy'} · {monthlyCredits}/mo
                                </Button>
                            </li>
                        ))}
                    </ul>
                    <div className="flex items-center justify-between text-[11px] text-muted-foreground">
                        <span>{numbers.length} available{searched?.limit && numbers.length >= searched.limit ? ' shown' : ''}</span>
                        {canShowMore && (
                            <Button type="button" size="sm" variant="ghost" className="h-6 px-2 text-[11px]" onClick={() => void search(MORE_PAGE)} disabled={busy}>
                                More numbers
                            </Button>
                        )}
                    </div>
                </div>
            )}
            </>}
        </div>
    );
};
