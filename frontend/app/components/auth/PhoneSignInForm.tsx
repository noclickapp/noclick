// Phone sign-in, shared by the login page and the auth modal: a number, then
// the SMS code. Both steps post to /auth/login (intents phone_send /
// phone_verify, see lib/auth.server.ts); a verified code redirects to `next`.
// A new number makes an account, so it serves sign-up as well as sign-in.

import { useState } from 'react';
import { useFetcher } from 'react-router';
import { Button } from '~/components/ui/button';
import { Input } from '~/components/ui/input';
import { PhoneNumberInput } from '~/components/ui/phone-number-input';
import { Label } from '~/components/ui/label';
import { TurnstileWidget } from '~/components/auth/TurnstileWidget';
import {
    ButtonSpinner,
    LEADING_SPINNER_CLASS,
} from '~/components/auth/authFormShared';
import {
    THESIS_INPUT_CLASS,
    THESIS_PRIMARY_BUTTON_CLASS,
} from '~/components/auth/AuthThesis';
import { resolveCsrfToken } from '~/lib/csrf';

interface PhoneSignInFormProps {
    /** Where a verified sign-in lands (defaults to the dashboard). */
    next?: string;
    csrfToken?: string;
}

type PhoneReply = { error?: string; phoneSent?: string; csrfToken?: string };

export function PhoneSignInForm({ next, csrfToken }: PhoneSignInFormProps) {
    const fetcher = useFetcher();
    const [captchaToken, setCaptchaToken] = useState('');
    const [attempt, setAttempt] = useState(0);
    const reply = fetcher.data as PhoneReply | undefined;
    const phoneSent = reply?.phoneSent;
    const pending = fetcher.state !== 'idle';
    const action = `/auth/login${next ? `?next=${encodeURIComponent(next)}` : ''}`;
    const token = resolveCsrfToken(csrfToken, reply);

    return (
        <div data-testid="phone-sign-in">
            {reply?.error && (
                <div className="mb-4 rounded-lg bg-red-500/10 p-3 text-sm text-red-600 dark:text-red-400">
                    {reply.error}
                </div>
            )}
            {phoneSent ? (
                <fetcher.Form
                    method="post"
                    action={action}
                    className="space-y-4"
                >
                    <input type="hidden" name="csrf_token" value={token} />
                    <input type="hidden" name="intent" value="phone_verify" />
                    <input type="hidden" name="phone" value={phoneSent} />
                    <div>
                        <Label
                            htmlFor="phone-code"
                            className="mb-2 block text-xs font-medium text-muted-foreground"
                        >
                            Code sent to {phoneSent}
                        </Label>
                        <Input
                            id="phone-code"
                            name="code"
                            required
                            inputMode="numeric"
                            autoComplete="one-time-code"
                            placeholder="123456"
                            className={THESIS_INPUT_CLASS}
                        />
                    </div>
                    <Button
                        type="submit"
                        disabled={pending}
                        className={THESIS_PRIMARY_BUTTON_CLASS}
                    >
                        {pending && (
                            <ButtonSpinner className={LEADING_SPINNER_CLASS} />
                        )}
                        Sign in
                    </Button>
                </fetcher.Form>
            ) : (
                <fetcher.Form
                    method="post"
                    action={action}
                    className="space-y-4"
                    // Captcha tokens are single-use; the widget remounts with a fresh one.
                    onSubmit={() => {
                        setCaptchaToken('');
                        setAttempt((n) => n + 1);
                    }}
                >
                    <input type="hidden" name="csrf_token" value={token} />
                    <input type="hidden" name="intent" value="phone_send" />
                    <div>
                        <Label
                            htmlFor="phone"
                            className="mb-2 block text-xs font-medium text-muted-foreground"
                        >
                            Phone number
                        </Label>
                        <PhoneNumberInput id="phone" name="phone" />
                        <p className="mt-2 text-sm text-muted-foreground/70 dark:text-zinc-500">
                            The number you message NoClick from on WhatsApp
                            signs you in to the same account. New here? This
                            makes one.
                        </p>
                    </div>
                    <TurnstileWidget
                        key={attempt}
                        onSuccess={setCaptchaToken}
                        onError={() => setCaptchaToken('')}
                    />
                    <input
                        type="hidden"
                        name="captchaToken"
                        value={captchaToken}
                    />
                    <Button
                        type="submit"
                        disabled={!captchaToken || pending}
                        className={THESIS_PRIMARY_BUTTON_CLASS}
                    >
                        {pending && (
                            <ButtonSpinner className={LEADING_SPINNER_CLASS} />
                        )}
                        Text me a code
                    </Button>
                </fetcher.Form>
            )}
        </div>
    );
}
