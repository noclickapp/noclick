// Verified phone: the number WhatsApp messages and calls resolve to this
// account through. It is linked only by a code the user proves possession of,
// via the phone:* socket events (utils/phone_identity.py owns the rules), and
// the section exists only where usePhoneLinkingAvailable says so.

import { useEffect, useState } from 'react';
import { ShieldCheck, Smartphone } from 'lucide-react';
import { toast } from 'sonner';
import { cn } from '~/lib/utils';
import { Button } from '~/components/ui/button';
import { Input } from '~/components/ui/input';
import { sendEventAsync } from '~/lib/socket-sender';
import {
    PhoneLinkCheckRequest,
    PhoneLinkStartRequest,
    PhoneStatusRequest,
    PhoneUnlinkRequest,
} from '~/types/socket-events.generated';

interface PhoneStatus {
    configured: boolean;
    phone: string | null;
    verified_at: string | null;
    link_version: number | null;
}

interface Challenge {
    challenge_id: string;
    phone: string;
    expires_at: string;
}

type Reply<T> = Partial<T> & { error?: string; kind?: string };

/** '+14242421064' → '+1 424 242 1064' for display; the wire keeps E.164. */
export function formatPhoneForDisplay(e164: string): string {
    const digits = e164.replace(/^\+/, '');
    if (digits.length <= 4) return e164;
    const country = digits.length > 10 ? digits.slice(0, digits.length - 10) : digits.slice(0, 1);
    const rest = digits.slice(country.length);
    const groups = rest.match(/.{1,3}(?=(.{3})*$)/g) ?? [rest];
    return `+${country} ${groups.join(' ')}`;
}

export function PhoneSettings() {
    const [status, setStatus] = useState<PhoneStatus | null>(null);
    const [challenge, setChallenge] = useState<Challenge | null>(null);
    const [phoneInput, setPhoneInput] = useState('');
    const [code, setCode] = useState('');
    const [busy, setBusy] = useState(false);
    const [confirmUnlink, setConfirmUnlink] = useState(false);
    const isLoading = status === null;

    const refresh = async () => {
        try {
            const reply = (await sendEventAsync(
                PhoneStatusRequest.create({ request_id: crypto.randomUUID() }),
            )) as Reply<PhoneStatus>;
            if (reply.error) throw new Error(reply.error);
            setStatus({
                configured: !!reply.configured,
                phone: reply.phone ?? null,
                verified_at: reply.verified_at ?? null,
                link_version: reply.link_version ?? null,
            });
        } catch (error) {
            console.error('[PhoneSettings] failed to load status:', error);
            toast.error('Failed to load your phone settings');
        }
    };

    useEffect(() => {
        refresh();
    }, []);

    const startLink = async () => {
        setBusy(true);
        try {
            const reply = (await sendEventAsync(
                PhoneLinkStartRequest.create({ request_id: crypto.randomUUID(), phone: phoneInput }),
            )) as Reply<Challenge>;
            if (reply.error || !reply.challenge_id) throw new Error(reply.error || 'No challenge returned');
            setChallenge({ challenge_id: reply.challenge_id, phone: reply.phone!, expires_at: reply.expires_at! });
            setCode('');
        } catch (error) {
            toast.error(error instanceof Error ? error.message : 'Could not send a code');
        } finally {
            setBusy(false);
        }
    };

    const checkCode = async () => {
        if (!challenge) return;
        setBusy(true);
        try {
            const reply = (await sendEventAsync(
                PhoneLinkCheckRequest.create({
                    request_id: crypto.randomUUID(),
                    challenge_id: challenge.challenge_id,
                    code,
                }),
            )) as Reply<{ phone: string; verified_at: string; link_version: number }>;
            if (reply.error) {
                // Expired, exhausted or taken: the challenge is spent, start over.
                if (reply.kind && reply.kind !== 'invalid_code') setChallenge(null);
                throw new Error(reply.error);
            }
            setChallenge(null);
            setPhoneInput('');
            toast.success(`Linked ${formatPhoneForDisplay(reply.phone!)}`);
            await refresh();
        } catch (error) {
            toast.error(error instanceof Error ? error.message : 'Could not verify the code');
        } finally {
            setBusy(false);
        }
    };

    const unlink = async () => {
        setBusy(true);
        try {
            const reply = (await sendEventAsync(
                PhoneUnlinkRequest.create({ request_id: crypto.randomUUID() }),
            )) as Reply<{ unlinked: boolean }>;
            if (reply.error) throw new Error(reply.error);
            setConfirmUnlink(false);
            toast.success('Phone unlinked');
            await refresh();
        } catch (error) {
            toast.error(error instanceof Error ? error.message : 'Could not unlink the phone');
        } finally {
            setBusy(false);
        }
    };

    const card = 'rounded-xl border border-border dark:border-white/[0.06] bg-card dark:bg-foreground/[0.03] overflow-hidden';

    return (
        <div className="max-w-2xl">
            <div className="mb-6">
                <h2 className="text-lg font-semibold text-foreground">Phone</h2>
                <p className="text-sm text-muted-foreground dark:text-white/40 mt-1">
                    Link the number you will message and call NoClick from. We send a code to prove
                    it is yours; nothing else is sent until you opt in.
                </p>
            </div>

            <div className={cn(card, 'transition-opacity', isLoading && 'opacity-60')}>
                {status?.phone ? (
                    <div className="flex items-center gap-3.5 px-4 py-3.5">
                        <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-emerald-500/10 flex-shrink-0">
                            <ShieldCheck className="w-4 h-4 text-emerald-600 dark:text-emerald-400 stroke-[1.5]" />
                        </div>
                        <div className="flex-1 min-w-0">
                            <p className="text-[0.9375rem] font-medium text-foreground leading-tight">
                                {formatPhoneForDisplay(status.phone)}
                            </p>
                            <p className="text-xs text-muted-foreground dark:text-white/40 mt-0.5 truncate">
                                Verified{status.verified_at ? ` on ${new Date(status.verified_at).toLocaleDateString()}` : ''}
                            </p>
                        </div>
                        {confirmUnlink ? (
                            <div className="flex items-center gap-2">
                                <Button variant="ghost" size="sm" disabled={busy} onClick={() => setConfirmUnlink(false)}>
                                    Keep
                                </Button>
                                <Button variant="destructive" size="sm" disabled={busy} onClick={unlink}>
                                    Unlink
                                </Button>
                            </div>
                        ) : (
                            <Button variant="outline" size="sm" disabled={busy || isLoading} onClick={() => setConfirmUnlink(true)}>
                                Unlink
                            </Button>
                        )}
                    </div>
                ) : challenge ? (
                    <form
                        className="px-4 py-3.5 space-y-3"
                        onSubmit={(e) => {
                            e.preventDefault();
                            checkCode();
                        }}
                    >
                        <p className="text-sm text-foreground">
                            Enter the code we sent to <span className="font-medium">{formatPhoneForDisplay(challenge.phone)}</span>.
                        </p>
                        <div className="flex items-center gap-2">
                            <Input
                                value={code}
                                onChange={(e) => setCode(e.target.value)}
                                inputMode="numeric"
                                autoComplete="one-time-code"
                                placeholder="123456"
                                className="max-w-[10rem] font-mono tracking-widest"
                            />
                            <Button type="submit" size="sm" disabled={busy || code.trim().length < 4}>
                                Verify
                            </Button>
                            <Button type="button" variant="ghost" size="sm" disabled={busy} onClick={() => setChallenge(null)}>
                                Change number
                            </Button>
                        </div>
                        <p className="text-xs text-muted-foreground dark:text-white/40">
                            Codes expire after ten minutes. No code yet?{' '}
                            <button type="button" className="underline underline-offset-2" disabled={busy} onClick={startLink}>
                                Send again
                            </button>
                        </p>
                    </form>
                ) : (
                    <form
                        className="px-4 py-3.5 space-y-3"
                        onSubmit={(e) => {
                            e.preventDefault();
                            startLink();
                        }}
                    >
                        <div className="flex items-center gap-3.5">
                            <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-foreground/[0.06] flex-shrink-0">
                                <Smartphone className="w-4 h-4 text-muted-foreground dark:text-white/60 stroke-[1.5]" />
                            </div>
                            <div className="flex-1 min-w-0">
                                <p className="text-[0.9375rem] font-medium text-foreground leading-tight">No phone linked</p>
                                <p className="text-xs text-muted-foreground dark:text-white/40 mt-0.5">
                                    Use the full number with its country code.
                                </p>
                            </div>
                        </div>
                        <div className="flex items-center gap-2">
                            <Input
                                value={phoneInput}
                                onChange={(e) => setPhoneInput(e.target.value)}
                                type="tel"
                                inputMode="tel"
                                autoComplete="tel"
                                placeholder="+1 424 242 1064"
                                className="max-w-[16rem]"
                                disabled={isLoading || !status?.configured}
                            />
                            <Button type="submit" size="sm" disabled={busy || isLoading || !status?.configured || phoneInput.trim().length < 7}>
                                Send code
                            </Button>
                        </div>
                        {status && !status.configured && (
                            <p className="text-xs text-amber-600 dark:text-amber-400">
                                Phone verification is not set up on this instance yet.
                            </p>
                        )}
                    </form>
                )}
            </div>

            <p className="text-xs text-muted-foreground/70 dark:text-white/30 mt-3 px-1">
                One number per account. Unlinking takes effect immediately for every channel that uses it.
            </p>
        </div>
    );
}
