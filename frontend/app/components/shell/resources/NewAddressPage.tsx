// Making an email address by hand, as a page one level under Email: the part
// before the @ and where it lives (one of the account's domains, where any
// address works, or NoClick's own mail domain), then Create. Mail sent to it
// arrives on its page, and answers go out from it.
import { useState, type FormEvent } from 'react';
import { ChevronDown, Loader2 } from 'lucide-react';
import { cn } from '~/lib/utils';
import { BUTTON_PRIMARY } from '../buttons';
import { FIELD, FIELD_LABEL, QUIET_LINK } from '../fields';
import { PageFrame } from '../PageFrame';

/** The domain picker's value for NoClick's own mail domain. */
const NOCLICK = '';

export function NewAddressPage({
    domains,
    create,
    onBack,
    onCreated,
    onBuyDomain,
}: {
    /** The account's domains an address can be on. */
    domains: string[];
    /** Makes the address; resolves to its id, or throws an Error saying why it couldn't. */
    create(localPart: string, domain: string | null): Promise<string>;
    onBack(): void;
    onCreated(id: string): void;
    /** Where to get a domain of one's own, offered when there's none yet. */
    onBuyDomain?: () => void;
}) {
    const [localPart, setLocalPart] = useState('');
    const [domain, setDomain] = useState(domains[0] ?? NOCLICK);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const name = localPart.trim().toLowerCase();

    const submit = async (event: FormEvent) => {
        event.preventDefault();
        if (!name || busy) return;
        setBusy(true);
        setError(null);
        try {
            onCreated(await create(name, domain || null));
        } catch (err) {
            setError(err instanceof Error ? err.message : String(err));
            setBusy(false);
        }
    };

    return (
        <PageFrame
            title="New email address"
            description="Mail sent to it arrives on its page, and you answer from the same address."
            back={{ label: 'Email', onBack }}
        >
            <form onSubmit={(e) => void submit(e)} className="max-w-xl">
                <label htmlFor="address-local-part" className={FIELD_LABEL}>
                    Address
                </label>
                <div className="flex flex-wrap items-center gap-2 sm:flex-nowrap">
                    <input
                        id="address-local-part"
                        value={localPart}
                        onChange={(e) => setLocalPart(e.target.value)}
                        placeholder="hello"
                        autoComplete="off"
                        spellCheck={false}
                        disabled={busy}
                        className={cn(FIELD, 'min-w-0 flex-1 basis-40')}
                    />
                    {/* The @ stays with its domain when a narrow screen wraps the row. */}
                    <div className="flex min-w-0 flex-1 basis-56 items-center gap-2">
                        <span aria-hidden className="text-[15px] text-muted-foreground">
                            @
                        </span>
                        <div className="relative min-w-0 flex-1">
                            <select aria-label="Domain" value={domain} onChange={(e) => setDomain(e.target.value)} disabled={busy} className={cn(FIELD, 'cursor-pointer appearance-none truncate pr-9')}>
                                {domains.map((d) => (
                                    <option key={d} value={d}>
                                        {d}
                                    </option>
                                ))}
                                <option value={NOCLICK}>NoClick’s mail domain</option>
                            </select>
                            <ChevronDown aria-hidden className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                        </div>
                    </div>
                </div>
                <p className="mt-2 text-[13px] leading-relaxed text-muted-foreground">
                    {domain ? `Any address works on ${domain}: hello, sales, your name.` : 'A free address on NoClick’s mail domain, for trying things out.'}
                    {!domains.length && onBuyDomain && (
                        <>
                            {' '}
                            <button type="button" onClick={onBuyDomain} className={cn(QUIET_LINK, 'text-foreground underline underline-offset-4')}>
                                Get a domain of your own
                            </button>
                        </>
                    )}
                </p>
                {error && (
                    <p role="alert" className="mt-4 text-[13.5px] text-red-600 dark:text-red-400">
                        {error}
                    </p>
                )}
                <button type="submit" disabled={!name || busy} className={cn(BUTTON_PRIMARY, 'mt-6')}>
                    {busy && <Loader2 className="h-4 w-4 animate-spin" />}
                    Create address
                </button>
            </form>
        </PageFrame>
    );
}
