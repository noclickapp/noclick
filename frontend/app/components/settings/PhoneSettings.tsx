// Verified phones: the numbers WhatsApp messages and calls resolve to this
// account through, each one more channel to the same account. Linked here by a
// code the user proves possession of, or by messaging NoClick on WhatsApp, via
// the phone:* socket events (utils/phone_identity.py owns the rules); the
// section exists only where usePhoneLinkingAvailable says so.

import { useState } from 'react';
import { formatPhoneForDisplay } from '~/lib/phoneFormat';
import { cn } from '~/lib/utils';
import { Button } from '~/components/ui/button';
import { PhoneNumberInput } from '~/components/ui/phone-number-input';
import { usePhoneLink } from '~/hooks/usePhoneLink';
import { FIELD } from '~/components/shell/fields';
import { SettingsGroup, SettingsHeader, SettingsRow } from '~/components/settings/SettingsParts';

export { formatPhoneForDisplay };

export function PhoneSettings() {
    const { status, isLoading, phones, canAdd, challenge, cancelChallenge, busy, startLink: sendCode, checkCode: verify, unlink: unlinkPhone } = usePhoneLink();
    const [phoneInput, setPhoneInput] = useState('');
    const [code, setCode] = useState('');
    const [confirmUnlink, setConfirmUnlink] = useState<string | null>(null);

    const startLink = async () => {
        if (await sendCode(phoneInput)) setCode('');
    };

    const checkCode = async () => {
        if (await verify(code)) setPhoneInput('');
    };

    const unlink = async (phone: string) => {
        if (await unlinkPhone(phone)) setConfirmUnlink(null);
    };

    return (
        <div>
            <SettingsHeader
                title="Phone"
                description="Link the numbers you message and call NoClick from. We send a code to prove each is yours; nothing else is sent until you opt in."
            />

            {phones.length > 0 && (
                <div className="mb-8">
                    <SettingsGroup className={cn('transition-opacity', isLoading && 'opacity-60')}>
                        {phones.map((linked) => (
                            <SettingsRow
                                key={linked.phone}
                                label={formatPhoneForDisplay(linked.phone)}
                                description={`${linked.source === 'whatsapp' ? 'Linked on WhatsApp' : 'Verified'} on ${new Date(linked.verified_at).toLocaleDateString()}`}
                                control={
                                    confirmUnlink === linked.phone ? (
                                        <>
                                            <Button variant="ghost" size="sm" disabled={busy} onClick={() => setConfirmUnlink(null)}>
                                                Keep
                                            </Button>
                                            <Button variant="destructive" size="sm" disabled={busy} onClick={() => unlink(linked.phone)}>
                                                Unlink
                                            </Button>
                                        </>
                                    ) : (
                                        <Button variant="outline" size="sm" disabled={busy || isLoading} onClick={() => setConfirmUnlink(linked.phone)}>
                                            Unlink
                                        </Button>
                                    )
                                }
                            />
                        ))}
                    </SettingsGroup>
                </div>
            )}

            {/* Linking a number is a form under the list, not a row inside it. */}
            {!canAdd ? null : challenge ? (
                <form
                    className="space-y-3"
                    onSubmit={(e) => {
                        e.preventDefault();
                        checkCode();
                    }}
                >
                    <div>
                        <h3 className="text-[14.5px] font-medium text-foreground">
                            Enter the code
                        </h3>
                        <p className="mt-0.5 text-[13px] text-muted-foreground">
                            We sent it to{' '}
                            <span className="font-medium text-foreground/85">
                                {formatPhoneForDisplay(challenge.phone)}
                            </span>
                            . Codes expire after ten minutes.
                        </p>
                    </div>
                    <div className="flex items-center gap-2">
                        <input
                            value={code}
                            onChange={(e) => setCode(e.target.value)}
                            inputMode="numeric"
                            autoComplete="one-time-code"
                            placeholder="123456"
                            aria-label="Code"
                            className={cn(FIELD, 'max-w-[10rem] font-mono tracking-widest placeholder:font-sans placeholder:tracking-normal')}
                        />
                        <Button type="submit" disabled={busy || code.trim().length < 4}>
                            Verify
                        </Button>
                        <Button
                            type="button"
                            variant="ghost"
                            disabled={busy}
                            onClick={cancelChallenge}
                        >
                            Change number
                        </Button>
                    </div>
                    <p className="text-[13px] text-muted-foreground">
                        No code yet?{' '}
                        <button
                            type="button"
                            className="font-medium text-foreground/85 underline decoration-foreground/25 underline-offset-[3px] transition-colors hover:text-foreground"
                            disabled={busy}
                            onClick={startLink}
                        >
                            Send it again
                        </button>
                    </p>
                </form>
            ) : (
                <form
                    className="space-y-3"
                    onSubmit={(e) => {
                        e.preventDefault();
                        startLink();
                    }}
                >
                    <div>
                        <h3 className="text-[14.5px] font-medium text-foreground">
                            {phones.length ? 'Add another number' : 'Link a number'}
                        </h3>
                        <p className="mt-0.5 text-[13px] text-muted-foreground">
                            Pick the country, then type the number.
                        </p>
                    </div>
                    <div className="flex items-center gap-2">
                        <PhoneNumberInput
                            name="phone"
                            value={phoneInput}
                            onChange={setPhoneInput}
                            className="h-10 max-w-[20rem] rounded-xl"
                            disabled={isLoading || !status?.configured}
                        />
                        <Button
                            type="submit"
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
                        <p className="text-[13px] text-muted-foreground">
                            Phone verification is not set up on this
                            instance yet.
                        </p>
                    )}
                </form>
            )}

            <p className="mt-6 text-[12.5px] text-muted-foreground">
                Each number reaches the same account. Unlinking one takes effect
                immediately for every channel that uses it.
            </p>
        </div>
    );
}
