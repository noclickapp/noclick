// Asking someone else for a credential: their email (sent as a request whose page lets them connect it without a
// NoClick account) or a link to send however you like. The connect flow swaps its body to `AskSomeoneForm`.

import { useCallback, useId, useState } from 'react';
import { Check, Link2, Loader2, Send } from 'lucide-react';
import { toast } from 'sonner';
import { sendEventAsync } from '~/lib/socket-sender';
import type { OAuthExchange } from '~/hooks/oauth/OAuthExchangeContext';
import { BUTTON_PRIMARY, BUTTON_SECONDARY } from '~/components/shell/buttons';
import { FIELD, FIELD_LABEL, QUIET_LINK } from '~/components/shell/fields';
import { cn } from '~/lib/utils';

/** A `sendEventAsync`-shaped transport, so a design lab can answer the request itself. */
export type AskTransport = OAuthExchange;

/** A switch inside a line of text (another way in, asking someone, back): ink that underlines on hover, so it reads as
 *  an action beside the muted words around it without competing with the primary. */
export const INLINE_ACTION =
    'self-start rounded-sm text-[13px] text-foreground underline-offset-4 transition-colors hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring';

/** Asking someone else for a credential: by email, or as a link to send however you like. Both make a credential
 *  request whose page (/credential/provide) lets them connect it without a NoClick account. */
export function useAskForCredential(credentialType: string, send: AskTransport = sendEventAsync) {
    const [sending, setSending] = useState(false);
    const [sentTo, setSentTo] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [copying, setCopying] = useState(false);
    const [copied, setCopied] = useState(false);

    // A link-mode request (no email), its provide URL copied for the user to hand off (Slack, DM, etc.).
    const copyLink = useCallback(async () => {
        setCopying(true);
        try {
            const response = await send({
                event_name: 'credential:request:create',
                request_id: `cred-req-link-${Date.now()}`,
                credential_type: credentialType,
                frontend_url: window.location.origin,
            });
            if (response?.provide_url) {
                await navigator.clipboard.writeText(response.provide_url);
                setCopied(true);
                toast.success('Link copied. Anyone with it can connect this account for you.');
                setTimeout(() => setCopied(false), 2000);
            } else {
                toast.error(response?.error || 'Couldn’t make a link');
            }
        } catch (err) {
            console.error('Failed to copy credential request link:', err);
            toast.error('Couldn’t copy the link');
        } finally {
            setCopying(false);
        }
    }, [credentialType, send]);

    const sendEmail = useCallback(
        async (email: string, message: string) => {
            if (!email.trim()) return;
            setSending(true);
            setError(null);
            try {
                const response = await send({
                    event_name: 'credential:request:create',
                    request_id: `cred-req-${Date.now()}`,
                    target_email: email.trim(),
                    credential_type: credentialType,
                    message: message.trim() || undefined,
                    frontend_url: window.location.origin,
                });
                if (response?.success) setSentTo(email.trim());
                else setError(response?.error || 'Couldn’t send the request. Try again, or copy a link instead.');
            } catch (err) {
                setError(err instanceof Error ? err.message : 'Couldn’t send the request. Try again, or copy a link instead.');
            } finally {
                setSending(false);
            }
        },
        [credentialType, send]
    );

    return { copyLink, copying, copied, sendEmail, sending, sentTo, error };
}

/** Asking someone else, drawn in place: their email (a note tucked behind a link), sent as a request whose page
 *  lets them connect `app` without a NoClick account; or a link to send however you like. Sent, it says to whom. */
export function AskSomeoneForm({
    credentialType,
    app,
    send,
    initialEmail = '',
    sent,
}: {
    credentialType: string;
    app: string;
    send?: AskTransport;
    initialEmail?: string;
    /** Open on the sent state, for the design lab. */
    sent?: string;
}) {
    const ask = useAskForCredential(credentialType, send);
    const [email, setEmail] = useState(initialEmail);
    const [message, setMessage] = useState('');
    const [noting, setNoting] = useState(false);
    const [missing, setMissing] = useState(false);
    const id = useId();
    const sentTo = ask.sentTo ?? sent;

    if (sentTo) {
        return (
            <div className="flex items-start gap-3.5" data-testid="ask-sent">
                <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-foreground/[0.06] text-foreground">
                    <Send className="h-4 w-4" strokeWidth={1.75} />
                </span>
                <div className="min-w-0 pt-1.5">
                    <p className="text-[14.5px] font-medium leading-snug text-foreground">Sent to {sentTo}</p>
                    <p className="mt-1 text-[13px] leading-relaxed text-muted-foreground">
                        They get a link to connect {app}, no NoClick account needed. It appears in your Connections once they have.
                    </p>
                </div>
            </div>
        );
    }

    return (
        <form
            className="space-y-4"
            data-testid="ask-someone-form"
            onSubmit={(e) => {
                e.preventDefault();
                // A dialog portals its content, but React still bubbles a submit to any form around it.
                e.stopPropagation();
                if (!email.trim()) return setMissing(true);
                void ask.sendEmail(email, message);
            }}
        >
            <div>
                <label htmlFor={`${id}-email`} className={FIELD_LABEL}>
                    Their email
                </label>
                <input
                    id={`${id}-email`}
                    type="email"
                    value={email}
                    onChange={(e) => {
                        setEmail(e.target.value);
                        setMissing(false);
                    }}
                    placeholder="colleague@company.com"
                    aria-invalid={missing || undefined}
                    className={cn(FIELD, missing && 'border-red-500/60 dark:border-red-400/50')}
                    autoComplete="off"
                />
                {missing && <p className="mt-1.5 text-[12.5px] text-red-600 dark:text-red-400">Enter their email.</p>}
            </div>
            {noting ? (
                <div>
                    <label htmlFor={`${id}-note`} className={FIELD_LABEL}>
                        Note <span className="font-normal text-muted-foreground">(optional)</span>
                    </label>
                    <textarea id={`${id}-note`} value={message} onChange={(e) => setMessage(e.target.value)} rows={2} placeholder={`Can you connect our ${app} for the weekly report?`} className={cn(FIELD, 'h-auto resize-none py-2.5')} />
                </div>
            ) : (
                <button type="button" onClick={() => setNoting(true)} className={cn(QUIET_LINK, 'text-[13px]')}>
                    Add a note
                </button>
            )}
            {ask.error && (
                <p role="alert" className="text-[13px] leading-relaxed text-red-600 dark:text-red-400">
                    {ask.error}
                </p>
            )}
            <div className="flex flex-col gap-2 pt-1">
                <button type="submit" aria-busy={ask.sending || undefined} className={cn(BUTTON_PRIMARY, 'h-10 w-full justify-center', ask.sending && 'cursor-wait')}>
                    {ask.sending ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                    {ask.sending ? 'Sending…' : 'Send request'}
                </button>
                <button type="button" onClick={ask.copyLink} disabled={ask.copying} className={cn(BUTTON_SECONDARY, 'h-10 w-full justify-center')}>
                    {ask.copying ? <Loader2 className="h-4 w-4 animate-spin" /> : ask.copied ? <Check className="h-4 w-4" /> : <Link2 className="h-4 w-4" />}
                    {ask.copied ? 'Link copied' : 'Copy a link instead'}
                </button>
            </div>
        </form>
    );
}
