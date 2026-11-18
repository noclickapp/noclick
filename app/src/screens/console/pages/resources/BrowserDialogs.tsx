// The Browser profiles panel's dialogs: create a profile, ask a person to sign
// in to a site (they get a link to a live browser), and forget a site.
import { useState } from 'react';
import { Link } from 'react-router';
import { toast } from 'sonner';
import { HAIRLINE } from '@/ui/primitives';
import { cn } from '@/ui/utils';
import { BrowserProfile, type BrowserLogin } from 'noclick';
import { operationStatus } from '@/screens/console/lib/status';
import { userLabel } from '@/screens/console/lib/userFilter';
import { useConsole, useConsoleHref } from '@/screens/console/hooks/useConsole';
import { invalidateV1 } from '@/sdk/useV1';
import { ConsoleButton } from '../../ui/Button';
import { ConsoleDialog } from '../../ui/ConsoleDialog';
import { CopyButton } from '../../ui/CopyButton';
import { ErrorPanel } from '../../ui/ErrorPanel';
import { StatusPill } from '../../ui/StatusPill';
import { UserField } from '../../ui/UserField';
import { TimeCell } from '../../ui/TimeCell';
import { ActsFor, INPUT, LabeledInput } from './shared';

export function NewProfile({ defaultUser }: { defaultUser: string | null }) {
    const { client } = useConsole();
    const [open, setOpen] = useState(false);
    const [user, setUser] = useState<string | null>(defaultUser);
    const [name, setName] = useState('');
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>(undefined);
    const create = async () => {
        setBusy(true);
        setError(undefined);
        try {
            const profile = await BrowserProfile.create(name.trim(), { client, user });
            setOpen(false);
            invalidateV1('browser_profiles');
            invalidateV1('account');
            toast(`Created ${profile.name}. Ask its person to sign in to a site next.`);
        } catch (e) {
            setError(e);
        } finally {
            setBusy(false);
        }
    };
    return (
        <>
            <ConsoleButton
                variant="primary"
                onClick={() => {
                    setUser(defaultUser);
                    setName('');
                    setError(undefined);
                    setOpen(true);
                }}
            >
                New profile
            </ConsoleButton>
            <ConsoleDialog
                open={open}
                onOpenChange={setOpen}
                title="New browser profile"
                description="One person's sign-ins, used only by its user's browsers and agents."
                footer={
                    <ConsoleButton variant="primary" disabled={busy || !name.trim()} onClick={() => void create()}>
                        {busy ? 'Creating…' : 'Create'}
                    </ConsoleButton>
                }
            >
                <div className="flex flex-col gap-3">
                    <UserField value={user} onChange={setUser} />
                    <LabeledInput label="Name" id="profile-name">
                        <input id="profile-name" className={cn(INPUT, 'font-mono')} value={name} onChange={(e) => setName(e.target.value)} placeholder="ana-work" />
                    </LabeledInput>
                    {error !== undefined && <ErrorPanel error={error} />}
                </div>
            </ConsoleDialog>
        </>
    );
}

const HTTPS = /^https:\/\/[^\s/]+/;

/** Who gets the link, in words: the profile's user, or nobody for an account profile. */
function recipientOf(profile: BrowserProfile): { sent: boolean; line: string } {
    if (!profile.userId) return { sent: false, line: "This profile is your account's, so nobody is emailed. Copy the link and send it to the person who signs in." };
    return { sent: true, line: `${userLabel(profile.userId)} gets an email with a link to a live browser open at this address.` };
}

export function SignInToSite({ profile }: { profile: BrowserProfile }) {
    const href = useConsoleHref();
    const recipient = recipientOf(profile);
    const [open, setOpen] = useState(false);
    const [url, setUrl] = useState('');
    const [reason, setReason] = useState('');
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>(undefined);
    const [login, setLogin] = useState<BrowserLogin | null>(null);
    const start = () => {
        setUrl('');
        setReason('');
        setError(undefined);
        setLogin(null);
        setOpen(true);
    };
    const send = async () => {
        setBusy(true);
        setError(undefined);
        try {
            setLogin(await profile.login(url.trim(), { reason: reason.trim() || undefined }));
            invalidateV1('operations');
        } catch (e) {
            setError(e);
        } finally {
            setBusy(false);
        }
    };
    return (
        <>
            <ConsoleButton size="sm" onClick={start}>
                Sign in to a site
            </ConsoleButton>
            <ConsoleDialog
                open={open}
                onOpenChange={setOpen}
                title={login ? `Waiting for a sign-in to ${login.domain ?? 'the site'}` : 'Sign in to a site'}
                description={
                    login
                        ? login.deliveredVia.length
                            ? `The link went out by ${login.deliveredVia.join(' and ')}. It lasts until the time below.`
                            : 'Nobody was emailed: send this link to the person who signs in.'
                        : 'The person signs in once, in a live browser, and the sign-in is saved to this profile.'
                }
                footer={
                    login ? (
                        <ConsoleButton variant="primary" onClick={() => setOpen(false)}>
                            Done
                        </ConsoleButton>
                    ) : (
                        <ConsoleButton variant="primary" disabled={busy || !HTTPS.test(url.trim())} onClick={() => void send()}>
                            {busy ? 'Sending…' : recipient.sent ? 'Send link' : 'Create link'}
                        </ConsoleButton>
                    )
                }
            >
                {login ? (
                    <div className="flex flex-col gap-3">
                        <div className={cn('flex items-center gap-2 rounded-lg border bg-foreground/[0.03] px-3 py-2', HAIRLINE)}>
                            <span className="min-w-0 flex-1 truncate font-mono text-[12px]" title={login.url}>
                                {login.url}
                            </span>
                            <CopyButton value={login.url} label="Copy link" />
                        </div>
                        <dl className="m-0 flex flex-col gap-1 text-[13px]">
                            <div className="flex items-center gap-3">
                                <dt className="w-20 shrink-0 text-[12px] text-muted-foreground">Status</dt>
                                <dd className="m-0 flex items-center gap-2">
                                    <StatusPill look={{ ...operationStatus('awaiting_human'), reason: 'sign-in' }} />
                                    {login.id && (
                                        <Link to={href('logs', { op: login.id })} className="text-[12px] text-muted-foreground underline-offset-2 hover:text-foreground hover:underline">
                                            View operation
                                        </Link>
                                    )}
                                </dd>
                            </div>
                            <div className="flex items-center gap-3">
                                <dt className="w-20 shrink-0 text-[12px] text-muted-foreground">Expires</dt>
                                <dd className="m-0">
                                    <TimeCell value={login.expiresAt} tier="absolute" />
                                </dd>
                            </div>
                        </dl>
                    </div>
                ) : (
                    <form
                        className="flex flex-col gap-3"
                        onSubmit={(e) => {
                            e.preventDefault();
                            if (HTTPS.test(url.trim())) void send();
                        }}
                    >
                        <ActsFor userId={profile.userId} />
                        <LabeledInput label="Site address" id="login-url">
                            <input id="login-url" type="url" className={cn(INPUT, 'font-mono')} value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://portal.example.com" />
                        </LabeledInput>
                        <LabeledInput label="Why (shown to them, optional)" id="login-reason">
                            <input id="login-reason" className={INPUT} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="to download your invoices" />
                        </LabeledInput>
                        <p className="m-0 text-[12px] text-muted-foreground">{recipient.line} Nobody else sees what they type, and the link lasts 24 hours.</p>
                    </form>
                )}
                {error !== undefined && <ErrorPanel error={error} className="mt-3" />}
            </ConsoleDialog>
        </>
    );
}

export function ForgetSite({ profile, domain, onForgotten }: { profile: BrowserProfile; domain: string; onForgotten: () => void }) {
    const [open, setOpen] = useState(false);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>(undefined);
    const forget = async () => {
        setBusy(true);
        setError(undefined);
        try {
            await profile.forget(domain);
            setOpen(false);
            onForgotten();
            toast(`Signed ${profile.name} out of ${domain}`);
        } catch (e) {
            setError(e);
        } finally {
            setBusy(false);
        }
    };
    return (
        <>
            <ConsoleButton variant="ghost" size="sm" aria-label={`Forget ${domain}`} onClick={() => setOpen(true)}>
                Forget
            </ConsoleButton>
            <ConsoleDialog
                open={open}
                onOpenChange={setOpen}
                size="sm"
                title={`Forget ${domain}?`}
                description="The profile is signed out and what the site stored is dropped. Browsers stop being signed in there until the person signs in again."
                footer={
                    <>
                        <ConsoleButton variant="ghost" onClick={() => setOpen(false)}>
                            Cancel
                        </ConsoleButton>
                        <ConsoleButton variant="danger" disabled={busy} onClick={() => void forget()}>
                            {busy ? 'Working…' : 'Forget site'}
                        </ConsoleButton>
                    </>
                }
            >
                {error !== undefined && <ErrorPanel error={error} />}
            </ConsoleDialog>
        </>
    );
}
