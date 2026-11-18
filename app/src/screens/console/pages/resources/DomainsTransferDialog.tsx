// Transferring a domain in from another registrar: check the name (the quote says whether the
// registry allows it now and what it costs), then the auth code, a ceiling, who it's registered
// to (the Buy dialog's rule), and follow the transfer to active. Opened from the toolbar, or from
// a connected domain's drawer with its name (the drawer then follows the transfer).
import { useState } from 'react';
import { toast } from 'sonner';
import { cn } from '@/ui/utils';
import { Domain, type DomainTransfer, type TransferQuote } from 'noclick';
import { useConsole } from '@/screens/console/hooks/useConsole';
import { invalidateV1 } from '@/sdk/useV1';
import { ConsoleButton } from '../../ui/Button';
import { ConsoleDialog } from '../../ui/ConsoleDialog';
import { ErrorPanel } from '../../ui/ErrorPanel';
import { Money } from '../../ui/Money';
import { UserField } from '../../ui/UserField';
import { ActsFor, INPUT, LabeledInput } from './shared';
import { PurchaseProgress, useRegistrant, type Step } from './DomainsBuyDialog';
import { Notice, dayLabel, everyLabel, yearsLabel } from './DomainsParts';

const TRANSFER_STEPS: readonly Step[] = [
    {
        status: 'transferring_in',
        label: 'Transferring in',
        detail: 'The registry and the current registrar move it, up to about 5 days; the registrar may email the current owner to approve. Its DNS keeps working where it is. Charged to your account once it completes.',
    },
    { status: 'active', label: 'Active', detail: null },
];

/** The quote: what it costs, or why it can't move now. */
function QuoteFacts({ quote }: { quote: TransferQuote }) {
    if (!quote.eligible) {
        return (
            <Notice title={`${quote.name} can't transfer in yet`}>
                {quote.reason}
                {quote.lockedUntil && ` It can move from ${dayLabel(quote.lockedUntil)}.`}
            </Notice>
        );
    }
    const years = quote.years ?? 1;
    return (
        <p className="m-0 text-[13px] text-muted-foreground">
            {quote.name} can transfer in: <Money usd={quote.priceUsd} full className="text-foreground" /> now, which adds {yearsLabel(years)} to its registration, then{' '}
            <Money usd={quote.renewalUsd} full /> {everyLabel(years)}.
        </p>
    );
}

export function TransferDomainDialog({
    defaultUser,
    onOpenDomain,
    from,
}: {
    defaultUser: string | null;
    onOpenDomain: (id: string) => void;
    /** A connected domain to transfer in: its name and user, checked as the dialog opens. */
    from?: Domain;
}) {
    const { client } = useConsole();
    const [open, setOpen] = useState(false);
    const [name, setName] = useState('');
    const [quote, setQuote] = useState<TransferQuote | null>(null);
    const [user, setUser] = useState<string | null>(defaultUser);
    const [authCode, setAuthCode] = useState('');
    const [max, setMax] = useState('');
    const [transfer, setTransfer] = useState<DomainTransfer | null>(null);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>(undefined);
    const reg = useRegistrant(open && !!quote?.eligible, user);

    const check = async (domain: string) => {
        setBusy(true);
        setError(undefined);
        try {
            const next = await Domain.transferQuote(domain, { client, user: null });
            setQuote(next);
            setMax(next.priceUsd != null ? String(next.priceUsd) : '');
        } catch (e) {
            setError(e);
        } finally {
            setBusy(false);
        }
    };
    const start = () => {
        const initial = from?.name ?? '';
        setName(initial);
        setQuote(null);
        setUser(from ? from.userId : defaultUser);
        setAuthCode('');
        setMax('');
        reg.reset();
        setTransfer(null);
        setError(undefined);
        setOpen(true);
        if (initial) void check(initial);
    };
    const submit = async () => {
        if (!quote) return;
        setBusy(true);
        setError(undefined);
        try {
            const charge = { client, authCode: authCode.trim(), maxPriceUsd: Number(max), registrant: reg.registrant };
            // A connected domain transfers in its own scope, so it carries no user of its own.
            const started = await (from ? Domain.transferIn(from, charge) : Domain.transferIn(quote, { ...charge, user }));
            // From a domain's drawer, the drawer follows it; from the toolbar, the dialog does.
            if (from) {
                setOpen(false);
                toast(`Transferring ${quote.name} in`);
            } else setTransfer(started);
            invalidateV1('domains');
            invalidateV1('account');
        } catch (e) {
            setError(e);
        } finally {
            setBusy(false);
        }
    };
    const ready = !busy && !!authCode.trim() && Number(max) > 0 && reg.ready;

    const footer = transfer ? (
        <>
            {transfer.domainId && (
                <ConsoleButton
                    variant="ghost"
                    onClick={() => {
                        setOpen(false);
                        onOpenDomain(transfer.domainId!);
                    }}
                >
                    View domain
                </ConsoleButton>
            )}
            <ConsoleButton
                variant="primary"
                onClick={() => {
                    setOpen(false);
                    toast(`Transferring ${quote?.name} in`);
                }}
            >
                Done
            </ConsoleButton>
        </>
    ) : quote?.eligible ? (
        <>
            {!from && (
                <ConsoleButton variant="ghost" onClick={() => setQuote(null)}>
                    Back
                </ConsoleButton>
            )}
            <ConsoleButton variant="primary" disabled={!ready} onClick={() => void submit()}>
                {busy ? 'Transferring…' : 'Transfer in'}
            </ConsoleButton>
        </>
    ) : (
        <ConsoleButton variant="primary" disabled={busy || !name.trim()} onClick={() => void check(name.trim().toLowerCase())}>
            {busy ? 'Checking…' : 'Check'}
        </ConsoleButton>
    );

    return (
        <>
            <ConsoleButton size={from ? 'sm' : undefined} onClick={start}>
                Transfer in
            </ConsoleButton>
            <ConsoleDialog
                open={open}
                onOpenChange={setOpen}
                size={quote?.eligible && !transfer ? 'lg' : 'md'}
                title={transfer ? `Transferring ${quote?.name} in` : quote?.eligible ? `Transfer ${quote.name} in` : 'Transfer a domain in'}
                description={
                    transfer
                        ? 'Its nameservers stay as they are, so its DNS keeps working.'
                        : 'Move a domain registered elsewhere to NoClick. It renews here, charged to your account.'
                }
                footer={footer}
            >
                {transfer && quote ? (
                    <PurchaseProgress
                        purchase={transfer}
                        name={quote.name}
                        steps={TRANSFER_STEPS}
                        label="Transfer progress"
                        failed={`The registry refused to transfer ${quote.name}, and nothing was charged. Check the auth code with its current registrar.`}
                    />
                ) : quote?.eligible ? (
                    <div className="flex flex-col gap-4">
                        <QuoteFacts quote={quote} />
                        <div className="grid gap-3 sm:grid-cols-2">
                            {from ? <ActsFor userId={from.userId} /> : <UserField value={user} onChange={setUser} />}
                            <LabeledInput label="Auth code" id="transfer-auth">
                                <input
                                    id="transfer-auth"
                                    type="password"
                                    autoComplete="off"
                                    className={cn(INPUT, 'font-mono')}
                                    value={authCode}
                                    onChange={(e) => setAuthCode(e.target.value)}
                                    placeholder="From its current registrar"
                                />
                            </LabeledInput>
                        </div>
                        <div className="flex flex-col gap-1.5">
                            <LabeledInput label="Most you'll pay (USD)" id="transfer-max">
                                <input id="transfer-max" inputMode="decimal" className={cn(INPUT, 'sm:w-48')} value={max} onChange={(e) => setMax(e.target.value)} />
                            </LabeledInput>
                            <p className="m-0 text-[12px] text-muted-foreground">
                                The transfer is refused if it costs more than your ceiling. It&apos;s charged once the transfer completes; if the registry refuses it (a wrong
                                auth code, say), nothing is charged.
                            </p>
                        </div>
                        {reg.fields}
                        {error !== undefined && <ErrorPanel error={error} />}
                    </div>
                ) : (
                    <div className="flex flex-col gap-3">
                        <form
                            onSubmit={(e) => {
                                e.preventDefault();
                                if (name.trim()) void check(name.trim().toLowerCase());
                            }}
                        >
                            <LabeledInput label="Domain" id="transfer-name">
                                <input
                                    id="transfer-name"
                                    className={cn(INPUT, 'font-mono')}
                                    value={name}
                                    onChange={(e) => {
                                        setName(e.target.value);
                                        setQuote(null);
                                    }}
                                    placeholder="acme.com"
                                />
                            </LabeledInput>
                        </form>
                        <p className="m-0 text-[12px] text-muted-foreground">
                            Unlock it at its current registrar and ask there for its auth code. The registry keeps a domain from moving for a while after it&apos;s
                            registered, transferred in or its registrant changes.
                        </p>
                        {quote && <QuoteFacts quote={quote} />}
                        {error !== undefined && <ErrorPanel error={error} />}
                    </div>
                )}
            </ConsoleDialog>
        </>
    );
}
