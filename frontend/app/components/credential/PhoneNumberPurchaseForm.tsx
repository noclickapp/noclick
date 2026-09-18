// Buy a phone number for a workflow. The number IS the credential: the backend
// buys it at the provider, mints the phone_number credential and starts its
// monthly charge in one step, and hands back the credential id.
import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router';
import { AlertCircle, Loader2, Search } from 'lucide-react';
import { sendEventAsync } from '~/lib/socket-sender';
import type { OAuthExchange } from '~/hooks/oauth/OAuthExchangeContext';
import { NUMBER_CELLS, formatPhoneForDisplay, patternSpan, searchQueryFromCells } from '~/lib/phoneFormat';
import { NumberPatternInput } from '~/components/credential/NumberPatternInput';
import { invalidateCredentialsCache } from '~/utils/credentialAutoSelect';
import { Badge } from '~/components/ui/badge';
import { Button } from '~/components/ui/button';
import { Skeleton } from '~/components/ui/skeleton';

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
}

export const PhoneNumberPurchaseForm = ({ onCredentialCreated, sendEvent }: PhoneNumberPurchaseFormProps) => {
    const [cells, setCells] = useState<string[]>(() => Array.from({ length: NUMBER_CELLS }, () => ''));
    const [searched, setSearched] = useState<{ areaCode: string | null; pattern: string | null; limit: number } | null>(null);
    const [numbers, setNumbers] = useState<AvailableNumber[] | null>(null);
    const [monthlyCredits, setMonthlyCredits] = useState(DEFAULT_MONTHLY_CREDITS);
    const [searching, setSearching] = useState(false);
    const [buying, setBuying] = useState<string | null>(null);
    const [error, setError] = useState<{ text: string; kind?: string } | null>(null);
    const sendRef = useRef(sendEvent ?? sendEventAsync);
    useEffect(() => { sendRef.current = sendEvent ?? sendEventAsync; }, [sendEvent]);

    const search = async (limit = FIRST_PAGE) => {
        setSearching(true);
        setError(null);
        const wanted = searchQueryFromCells(cells);
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
        setBuying(phoneNumber);
        setError(null);
        try {
            const reply: Reply<{ credential_id: string; phone_number: string }> = await sendRef.current({
                event_name: 'phone_number:buy',
                phone_number: phoneNumber,
            });
            if (reply.error || !reply.credential_id) {
                setError({ text: failureText(reply, 'Could not buy that number.'), kind: reply.kind });
                return;
            }
            invalidateCredentialsCache();
            onCredentialCreated(reply.credential_id, reply.phone_number ?? phoneNumber);
        } catch (e) {
            setError({ text: e instanceof Error ? e.message : 'Could not buy that number.' });
        } finally {
            setBuying(null);
        }
    };

    const canShowMore = numbers !== null && searched !== null && searched.limit < MORE_PAGE && numbers.length >= searched.limit;
    const busy = searching || !!buying;

    return (
        <div className="space-y-3">
            <p className="text-xs text-muted-foreground">
                Buy a US number for this agent — {monthlyCredits} credits a month while you keep it. Deleting the
                credential releases it.
            </p>
            <div className="flex flex-wrap items-center gap-2">
                <NumberPatternInput cells={cells} onChange={setCells} onSubmit={() => void search()} disabled={busy} />
                <Button type="button" size="sm" variant="outline" onClick={() => void search()} disabled={busy}>
                    {searching ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Search className="h-3.5 w-3.5" />}
                    Find numbers
                </Button>
                {cells.some(Boolean) && (
                    <Button type="button" size="sm" variant="ghost" className="h-8 px-2 text-xs" onClick={() => setCells(Array.from({ length: NUMBER_CELLS }, () => ''))} disabled={busy}>
                        Clear
                    </Button>
                )}
            </div>
            <p className="text-[11px] text-muted-foreground">
                Type the digits or letters you want where you want them; blank spots match anything. Just an area
                code finds numbers in that area; letters spell on the keypad, so <span className="font-mono">NOCLICK</span> works
                too.
            </p>
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
                    No numbers match{searched?.pattern ? <> the pattern <span className="font-mono">{searched.pattern.replace(/\*/g, '·')}</span></> : ''}
                    {searched?.areaCode ? <> in area code {searched.areaCode}</> : ''}. Leave more spots blank or try
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
                                        {n.capabilities.filter((c) => CAPABILITY_LABELS[c]).map((c) => (
                                            <Badge key={c} variant="secondary" className="h-4 px-1.5 text-[10px] font-normal">
                                                {CAPABILITY_LABELS[c]}
                                            </Badge>
                                        ))}
                                    </div>
                                </div>
                                <Button type="button" size="sm" onClick={() => void buy(n.phone_number)} disabled={busy}>
                                    {buying === n.phone_number ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
                                    Buy · {monthlyCredits}/mo
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
        </div>
    );
};
