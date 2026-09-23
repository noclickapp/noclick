// Verified phones: the numbers WhatsApp messages and calls resolve to this
// account through, each one more channel to the same account. Linked here by a
// code the user proves possession of, or by messaging NoClick on WhatsApp, via
// the phone:* socket events (utils/phone_identity.py owns the rules); the
// section exists only where usePhoneLinkingAvailable says so.

import { useEffect, useState } from 'react';
import { formatPhoneForDisplay } from '~/lib/phoneFormat';
import { ShieldCheck, Smartphone } from 'lucide-react';
import { toast } from 'sonner';
import { cn } from '~/lib/utils';
import { Button } from '~/components/ui/button';
import { Input } from '~/components/ui/input';
import { PhoneNumberInput } from '~/components/ui/phone-number-input';
import { sendEventAsync } from '~/lib/socket-sender';
import {
    PhoneLinkCheckRequest,
    PhoneLinkStartRequest,
    PhoneStatusRequest,
    PhoneUnlinkRequest,
} from '~/types/socket-events.generated';

interface LinkedPhone {
    phone: string;
    verified_at: string;
    source: 'verify' | 'whatsapp';
}

interface PhoneStatus {
    configured: boolean;
    max_phones: number;
    phones: LinkedPhone[];
}

interface Challenge {
    challenge_id: string;
    phone: string;
    expires_at: string;
}

type Reply<T> = Partial<T> & { error?: string; kind?: string };

export { formatPhoneForDisplay };

export function PhoneSettings() {
    const [status, setStatus] = useState<PhoneStatus | null>(null);
    const [challenge, setChallenge] = useState<Challenge | null>(null);
    const [phoneInput, setPhoneInput] = useState('');
    const [code, setCode] = useState('');
    const [busy, setBusy] = useState(false);
    const [confirmUnlink, setConfirmUnlink] = useState<string | null>(null);
    const isLoading = status === null;
    const phones = status?.phones ?? [];
    const canAdd = !status || phones.length < status.max_phones;

    const refresh = async () => {
        try {
            const reply = (await sendEventAsync(
                PhoneStatusRequest.create({ request_id: crypto.randomUUID() })
            )) as Reply<PhoneStatus>;
            if (reply.error) throw new Error(reply.error);
            setStatus({
                configured: !!reply.configured,
                max_phones: reply.max_phones ?? 1,
                phones: reply.phones ?? [],
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
                PhoneLinkStartRequest.create({
                    request_id: crypto.randomUUID(),
                    phone: phoneInput,
                })
            )) as Reply<Challenge>;
            if (reply.error || !reply.challenge_id)
                throw new Error(reply.error || 'No challenge returned');
            setChallenge({
                challenge_id: reply.challenge_id,
                phone: reply.phone!,
                expires_at: reply.expires_at!,
            });
            setCode('');
        } catch (error) {
            toast.error(
                error instanceof Error ? error.message : 'Could not send a code'
            );
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
                })
            )) as Reply<{ phone: string; verified_at: string }>;
            if (reply.error) {
                // Expired, exhausted or taken: the challenge is spent, start over.
                if (reply.kind && reply.kind !== 'invalid_code')
                    setChallenge(null);
                throw new Error(reply.error);
            }
            setChallenge(null);
            setPhoneInput('');
            toast.success(`Linked ${formatPhoneForDisplay(reply.phone!)}`);
            await refresh();
        } catch (error) {
            toast.error(
                error instanceof Error
                    ? error.message
                    : 'Could not verify the code'
            );
        } finally {
            setBusy(false);
        }
    };

    const unlink = async (phone: string) => {
        setBusy(true);
        try {
            const reply = (await sendEventAsync(
                PhoneUnlinkRequest.create({
                    request_id: crypto.randomUUID(),
                    phone,
                })
            )) as Reply<{ unlinked: boolean }>;
            if (reply.error) throw new Error(reply.error);
            setConfirmUnlink(null);
            toast.success(`Unlinked ${formatPhoneForDisplay(phone)}`);
            await refresh();
        } catch (error) {
            toast.error(
                error instanceof Error
                    ? error.message
                    : 'Could not unlink the phone'
            );
        } finally {
            setBusy(false);
        }
    };

    const card =
        'rounded-xl border border-border dark:border-white/[0.06] bg-card dark:bg-foreground/[0.03] overflow-hidden';

    return (
        <div className="max-w-2xl">
            <div className="mb-6">
                <h2 className="text-lg font-semibold text-foreground">Phone</h2>
                <p className="text-sm text-muted-foreground dark:text-white/40 mt-1">
                    Link the numbers you message and call NoClick from. We send
                    a code to prove each is yours; nothing else is sent until
                    you opt in.
                </p>
            </div>

            <div
                className={cn(
                    card,
                    'transition-opacity divide-y divide-border dark:divide-white/[0.06]',
                    isLoading && 'opacity-60'
                )}
            >
                {phones.map((linked) => (
                    <div
                        key={linked.phone}
                        className="flex items-center gap-3.5 px-4 py-3.5"
                    >
                        <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-emerald-500/10 flex-shrink-0">
                            <ShieldCheck className="w-4 h-4 text-emerald-600 dark:text-emerald-400 stroke-[1.5]" />
                        </div>
                        <div className="flex-1 min-w-0">
                            <p className="text-[0.9375rem] font-medium text-foreground leading-tight">
                                {formatPhoneForDisplay(linked.phone)}
                            </p>
                            <p className="text-xs text-muted-foreground dark:text-white/40 mt-0.5 truncate">
                                {linked.source === 'whatsapp'
                                    ? 'Linked on WhatsApp'
                                    : 'Verified'}
                                {` on ${new Date(linked.verified_at).toLocaleDateString()}`}
                            </p>
                        </div>
                        {confirmUnlink === linked.phone ? (
                            <div className="flex items-center gap-2">
                                <Button
                                    variant="ghost"
                                    size="sm"
                                    disabled={busy}
                                    onClick={() => setConfirmUnlink(null)}
                                >
                                    Keep
                                </Button>
                                <Button
                                    variant="destructive"
                                    size="sm"
                                    disabled={busy}
                                    onClick={() => unlink(linked.phone)}
                                >
                                    Unlink
                                </Button>
                            </div>
                        ) : (
                            <Button
                                variant="outline"
                                size="sm"
                                disabled={busy || isLoading}
                                onClick={() => setConfirmUnlink(linked.phone)}
                            >
                                Unlink
                            </Button>
                        )}
                    </div>
                ))}
                {!canAdd ? null : challenge ? (
                    <form
                        className="px-4 py-3.5 space-y-3"
                        onSubmit={(e) => {
                            e.preventDefault();
                            checkCode();
                        }}
                    >
                        <p className="text-sm text-foreground">
                            Enter the code we sent to{' '}
                            <span className="font-medium">
                                {formatPhoneForDisplay(challenge.phone)}
                            </span>
                            .
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
                            <Button
                                type="submit"
                                size="sm"
                                disabled={busy || code.trim().length < 4}
                            >
                                Verify
                            </Button>
                            <Button
                                type="button"
                                variant="ghost"
                                size="sm"
                                disabled={busy}
                                onClick={() => setChallenge(null)}
                            >
                                Change number
                            </Button>
                        </div>
                        <p className="text-xs text-muted-foreground dark:text-white/40">
                            Codes expire after ten minutes. No code yet?{' '}
                            <button
                                type="button"
                                className="underline underline-offset-2"
                                disabled={busy}
                                onClick={startLink}
                            >
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
                                <p className="text-[0.9375rem] font-medium text-foreground leading-tight">
                                    {phones.length
                                        ? 'Add another number'
                                        : 'No phone linked'}
                                </p>
                                <p className="text-xs text-muted-foreground dark:text-white/40 mt-0.5">
                                    Pick the country, then type the number.
                                </p>
                            </div>
                        </div>
                        <div className="flex items-center gap-2">
                            <PhoneNumberInput
                                name="phone"
                                value={phoneInput}
                                onChange={setPhoneInput}
                                className="h-9 max-w-[18rem] rounded-md"
                                disabled={isLoading || !status?.configured}
                            />
                            <Button
                                type="submit"
                                size="sm"
                                disabled={
                                    busy ||
                                    isLoading ||
                                    !status?.configured ||
                                    phoneInput.trim().length < 7
                                }
                            >
                                Send code
                            </Button>
                        </div>
                        {status && !status.configured && (
                            <p className="text-xs text-amber-600 dark:text-amber-400">
                                Phone verification is not set up on this
                                instance yet.
                            </p>
                        )}
                    </form>
                )}
            </div>

            <p className="text-xs text-muted-foreground/70 dark:text-white/30 mt-3 px-1">
                Each number reaches the same account. Unlinking one takes effect
                immediately for every channel that uses it.
            </p>
        </div>
    );
}
