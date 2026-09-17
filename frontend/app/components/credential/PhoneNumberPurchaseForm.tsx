// Buy a phone number for a workflow. The number IS the credential: the backend
// buys it at the provider, mints the phone_number credential and starts its
// monthly charge in one step, and hands back the credential id.
import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router';
import { AlertCircle, Loader2, Phone, Search } from 'lucide-react';
import { sendEventAsync } from '~/lib/socket-sender';
import type { OAuthExchange } from '~/hooks/oauth/OAuthExchangeContext';
import { invalidateCredentialsCache } from '~/utils/credentialAutoSelect';
import { Button } from '~/components/ui/button';
import { Input } from '~/components/ui/input';

interface AvailableNumber {
    phone_number: string;
    locality: string;
    region: string;
    capabilities: string[];
}

type Reply<T> = Partial<T> & { error?: string; kind?: string };

const DEFAULT_MONTHLY_CREDITS = 15;

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

interface PhoneNumberPurchaseFormProps {
    onCredentialCreated: (credentialId: string) => void;
    // Transport override (default: socket), the same seam the QR form exposes.
    sendEvent?: OAuthExchange;
}

export const PhoneNumberPurchaseForm = ({ onCredentialCreated, sendEvent }: PhoneNumberPurchaseFormProps) => {
    const [areaCode, setAreaCode] = useState('');
    const [numbers, setNumbers] = useState<AvailableNumber[] | null>(null);
    const [monthlyCredits, setMonthlyCredits] = useState(DEFAULT_MONTHLY_CREDITS);
    const [searching, setSearching] = useState(false);
    const [buying, setBuying] = useState<string | null>(null);
    const [error, setError] = useState<{ text: string; kind?: string } | null>(null);
    const sendRef = useRef(sendEvent ?? sendEventAsync);
    useEffect(() => { sendRef.current = sendEvent ?? sendEventAsync; }, [sendEvent]);

    const search = async () => {
        setSearching(true);
        setError(null);
        try {
            const reply: Reply<{ numbers: AvailableNumber[]; monthly_credits: number }> = await sendRef.current({
                event_name: 'phone_number:search',
                country: 'US',
                area_code: areaCode.trim() || null,
            });
            if (reply.error) {
                setError({ text: failureText(reply, 'Could not search for numbers.'), kind: reply.kind });
                return;
            }
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
            onCredentialCreated(reply.credential_id);
        } catch (e) {
            setError({ text: e instanceof Error ? e.message : 'Could not buy that number.' });
        } finally {
            setBuying(null);
        }
    };

    return (
        <div className="space-y-3">
            <p className="text-xs text-muted-foreground">
                Buy a number for this agent — {monthlyCredits} credits a month while you keep it. Deleting the
                credential releases it.
            </p>
            <div className="flex items-center gap-2">
                <Input
                    value={areaCode}
                    onChange={(e) => setAreaCode(e.target.value.replace(/\D/g, '').slice(0, 3))}
                    placeholder="Area code (optional)"
                    inputMode="numeric"
                    className="h-8 w-44 text-xs"
                    onKeyDown={(e) => { if (e.key === 'Enter') void search(); }}
                />
                <Button type="button" size="sm" variant="outline" onClick={() => void search()} disabled={searching || !!buying}>
                    {searching ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Search className="h-3.5 w-3.5" />}
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
                    </span>
                </div>
            )}
            {numbers && numbers.length === 0 && !error && (
                <p className="text-xs text-muted-foreground">No numbers found there. Try another area code.</p>
            )}
            {numbers && numbers.length > 0 && (
                <ul className="divide-y divide-border rounded-md border border-border">
                    {numbers.map((n) => (
                        <li key={n.phone_number} className="flex items-center justify-between gap-3 px-3 py-2">
                            <div className="flex min-w-0 items-center gap-2">
                                <Phone className="h-3.5 w-3.5 flex-shrink-0 text-muted-foreground" />
                                <div className="min-w-0">
                                    <div className="text-sm text-foreground">{n.phone_number}</div>
                                    <div className="truncate text-xs text-muted-foreground">
                                        {[n.locality, n.region].filter(Boolean).join(', ')}
                                    </div>
                                </div>
                            </div>
                            <Button
                                type="button"
                                size="sm"
                                onClick={() => void buy(n.phone_number)}
                                disabled={!!buying || searching}
                            >
                                {buying === n.phone_number ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
                                Buy · {monthlyCredits} credits/mo
                            </Button>
                        </li>
                    ))}
                </ul>
            )}
        </div>
    );
};
