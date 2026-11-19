// NoClick's email address, as the Connect menu's email view shows it: the address to copy and write to from the owner's
// mail, whether it answers mail (and whose), and what NoClick sets up itself (naming it, an email for the account).
// Whatever reads and changes the address is its host's (`chat.connect.email`).
import { useEffect, useState } from 'react';
import { ArrowUpRight, Check, Copy, Loader2, PenLine } from 'lucide-react';
import { Skeleton } from '@/ui/skeleton';
import { Switch } from '@/ui/switch';
import { BUTTON_GHOST, BUTTON_PRIMARY, BUTTON_SECONDARY } from '@/ui/buttons';
import { FIELD } from '@/ui/fields';
import { cn } from '@/ui/utils';
import { mailLink } from './mailApp';

const QUIET_LINK =
    'inline-flex items-center gap-0.5 rounded-md text-[13px] text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring';
const ASK_TO_NAME = 'Pick a better name for your email address.';
const ASK_TO_ADD_EMAIL = 'I want to add my email address to this account.';
const ASK_FOR_ADDRESS = 'Give yourself an email address I can write to.';
const SMALL = 'h-8 px-3.5 text-[13px]';
const PILL = cn(BUTTON_SECONDARY, 'h-8 gap-1.5 px-3 text-[13px]');

/** What the email view does with NoClick's address, as its host can: switch its mail on or off, and, where it can,
 *  claim one (true: it has one now; false: this instance has no mail) and rename it. */
export interface MailboxActions {
    setInbound: (on: boolean) => Promise<unknown>;
    claim?: () => Promise<boolean>;
    rename?: (name: string) => Promise<unknown>;
}

/** NoClick's address: claimed the first time this opens where the host can, copied, renamed in place where it can;
 *  asking NoClick to name it is the quiet alternative. Its owner can turn mail to it off (`paused`) and keep the
 *  address; `fromAnyone`: anyone's mail reaches it, else only the owner's. `escape` lets Escape cancel an edit before
 *  it steps back out of the detail. */
export function EmailView({
    address,
    paused,
    fromAnyone,
    ownerEmail,
    onAsk,
    escape,
    actions,
}: {
    address: string | null | undefined;
    paused: boolean;
    fromAnyone: boolean;
    ownerEmail?: string;
    onAsk: (text: string) => void;
    escape: { current: (() => boolean) | null };
    actions: MailboxActions;
}) {
    const [claim, setClaim] = useState<'claiming' | 'unavailable' | 'failed' | null>(null);
    const [claimError, setClaimError] = useState('');
    const [draft, setDraft] = useState<string | null>(null);
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState('');
    const [copied, setCopied] = useState(false);
    const [switchError, setSwitchError] = useState('');
    const [local, domain] = address ? [address.split('@')[0], address.split('@')[1]] : ['', ''];
    // Nothing to compose to an address that ignores its mail.
    const mail = address && ownerEmail && !paused ? mailLink(address, ownerEmail) : null;
    const takeMail = (on: boolean) => {
        setSwitchError('');
        actions.setInbound(on).catch((e: unknown) => setSwitchError(e instanceof Error ? e.message : 'Could not change it'));
    };
    const copy = () => {
        if (!address) return;
        void navigator.clipboard.writeText(address).then(() => {
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
        });
    };

    const tryClaim = () => {
        if (!actions.claim) return;
        setClaim('claiming');
        actions.claim().then(
            (claimed) => setClaim(claimed ? null : 'unavailable'),
            (e: unknown) => {
                setClaimError(e instanceof Error ? e.message : 'Could not get an address');
                setClaim('failed');
            }
        );
    };
    // A reach that has loaded without an address gets one where the host can; until it loads there's nothing to decide.
    useEffect(() => {
        if (address === null && claim === null && actions.claim) tryClaim();
        // eslint-disable-next-line react-hooks/exhaustive-deps -- once per address that's missing
    }, [address]);

    const cancel = () => {
        setDraft(null);
        setError('');
    };
    useEffect(() => {
        escape.current = () => {
            if (draft === null) return false;
            cancel();
            return true;
        };
        return () => {
            escape.current = null;
        };
    }, [draft, escape]);

    const save = async () => {
        const name = (draft ?? '').trim().toLowerCase();
        if (!name || name === local) return cancel();
        setSaving(true);
        try {
            await actions.rename?.(name);
            cancel();
        } catch (e) {
            setError(e instanceof Error ? e.message : 'Could not change the address');
        } finally {
            setSaving(false);
        }
    };

    if (claim === 'unavailable') return <p className="text-[13.5px] leading-relaxed text-muted-foreground">Email isn’t set up on this instance.</p>;
    if (claim === 'failed') {
        return (
            <>
                <p className="text-[13.5px] leading-relaxed text-muted-foreground">{claimError}</p>
                <button type="button" className={cn(BUTTON_GHOST, SMALL, '-ml-3 mt-2')} onClick={tryClaim}>
                    Try again
                </button>
            </>
        );
    }
    if (address === null && !actions.claim) {
        return (
            <>
                <p className="text-[13.5px] leading-relaxed text-muted-foreground">NoClick has no email address yet.</p>
                <button type="button" className={cn(QUIET_LINK, 'mt-2.5')} onClick={() => onAsk(ASK_FOR_ADDRESS)}>
                    Ask NoClick for one
                </button>
            </>
        );
    }
    if (!address) return <Skeleton className="h-10 w-full rounded-xl" />;

    return (
        <>
            {draft === null ? (
                <>
                    {/* Never cut short: a long name wraps, at the @ where it can. */}
                    <p className="m-0 select-all text-[16px] font-medium leading-snug text-foreground [overflow-wrap:anywhere]" data-testid="connect-email-address">
                        {local}
                        <wbr />@{domain}
                    </p>
                    <div className="mt-3 flex flex-wrap items-center gap-1.5">
                        <button type="button" className={PILL} onClick={copy}>
                            {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
                            {copied ? 'Copied' : 'Copy'}
                        </button>
                        {actions.rename && (
                            <button type="button" className={PILL} onClick={() => setDraft(local)}>
                                <PenLine className="h-3.5 w-3.5" />
                                Change
                            </button>
                        )}
                        {mail && (
                            <a href={mail.href} {...(mail.web ? { target: '_blank', rel: 'noopener noreferrer' } : {})} className={PILL}>
                                <ArrowUpRight className="h-3.5 w-3.5" />
                                Open {mail.label}
                            </a>
                        )}
                    </div>
                </>
            ) : (
                <form
                    onSubmit={(e) => {
                        e.preventDefault();
                        void save();
                    }}
                >
                    <div className={cn(FIELD, 'flex items-center gap-0 pr-3 focus-within:border-foreground/25')}>
                        <input
                            // eslint-disable-next-line jsx-a11y/no-autofocus -- Change opened it to be typed in
                            autoFocus
                            value={draft}
                            onChange={(e) => {
                                setDraft(e.target.value);
                                setError('');
                            }}
                            aria-label="Address name"
                            aria-invalid={!!error}
                            spellCheck={false}
                            autoCapitalize="none"
                            className="h-full min-w-0 flex-1 bg-transparent text-[14px] text-foreground outline-none"
                        />
                        <span className="shrink-0 text-[14px] text-muted-foreground">@{domain}</span>
                    </div>
                    {error && (
                        <p role="alert" className="mt-1.5 text-[12.5px] text-red-600 dark:text-red-400">
                            {error}
                        </p>
                    )}
                    <div className="mt-2.5 flex items-center gap-1.5">
                        <button type="submit" disabled={saving} className={cn(BUTTON_PRIMARY, SMALL)}>
                            {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : 'Save'}
                        </button>
                        <button type="button" className={cn(BUTTON_GHOST, SMALL)} onClick={cancel}>
                            Cancel
                        </button>
                    </div>
                </form>
            )}
            {fromAnyone || ownerEmail ? (
                <div className="mt-4">
                    <div className="flex items-center justify-between gap-3">
                        <label htmlFor="connect-email-inbound" className="min-w-0 text-[13.5px] leading-snug text-foreground">
                            Answer emails
                        </label>
                        <Switch
                            id="connect-email-inbound"
                            checked={!paused}
                            onCheckedChange={takeMail}
                            className="data-[state=unchecked]:bg-input dark:data-[state=unchecked]:bg-input"
                        />
                    </div>
                    <p className="mt-1 text-[13px] leading-relaxed text-muted-foreground [overflow-wrap:anywhere]" data-testid="connect-email-inbound-note">
                        {paused
                            ? 'Mail to this address is ignored. The address stays yours.'
                            : !fromAnyone
                              ? `Email it from ${ownerEmail} and it replies on the same thread. Mail from other addresses is ignored.`
                              : ownerEmail
                                ? `Anyone can email it, and it replies on the same thread. Mail from ${ownerEmail} shows here too.`
                                : 'Anyone can email it, and it replies on the same thread.'}
                    </p>
                    {switchError && (
                        <p role="alert" className="mt-1.5 text-[12.5px] text-red-600 dark:text-red-400">
                            {switchError}
                        </p>
                    )}
                </div>
            ) : (
                <p className="mt-3 text-[13px] leading-relaxed text-muted-foreground">It reads mail from your account’s email, and this account doesn’t have one yet.</p>
            )}
            <div className="mt-2.5 flex items-center gap-4">
                {!ownerEmail && (
                    <button type="button" className={QUIET_LINK} onClick={() => onAsk(ASK_TO_ADD_EMAIL)}>
                        Add your email
                    </button>
                )}
                <button type="button" className={QUIET_LINK} onClick={() => onAsk(ASK_TO_NAME)}>
                    Ask NoClick to name it
                </button>
            </div>
        </>
    );
}
