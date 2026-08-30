// Where this instance's email leaves from: an SMTP server, checked with a real
// login before it is stored (instance_smtp:set). Offered in the Send Email
// node's Credentials tab the first time it is missing, and kept under
// Settings → Self-hosted; both render this one card. Resend is the alternative
// transport, configured through the environment (RESEND_API_KEY + FROM_EMAIL).
import { useState } from 'react';
import { toast } from 'sonner';
import { sendEventAsync } from '~/lib/socket-sender';
import {
    applyInstanceKeysState,
    type InstanceKeysState,
} from '~/lib/instanceKeys';
import { InstanceSmtpSetRequest } from '~/types/socket-events.generated';
import { INSTANCE_FORM, InstanceSetupCard } from './InstanceSetupCard';

export function InstanceSmtpForm({
    onSaved,
    submitLabel = 'Check and save',
}: {
    onSaved?: () => void;
    submitLabel?: string;
}) {
    const [host, setHost] = useState('');
    const [port, setPort] = useState('587');
    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');
    const [fromEmail, setFromEmail] = useState('');
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const ready = host.trim() && fromEmail.trim() && /^\d+$/.test(port.trim());

    const save = async () => {
        if (!ready) return;
        setSaving(true);
        setError(null);
        try {
            // The sender resolves with the backend's reply either way; the server's verdict rides its `error`.
            const res = (await sendEventAsync(
                InstanceSmtpSetRequest.create({
                    request_id: crypto.randomUUID(),
                    host: host.trim(),
                    port: Number(port.trim()),
                    username: username.trim(),
                    password,
                    from_email: fromEmail.trim(),
                })
            )) as (InstanceKeysState & { error?: string }) | null;
            if (!res || res.error)
                throw new Error(res?.error || 'Could not save the mail server');
            applyInstanceKeysState(res);
            toast.success('Mail server saved for this instance');
            setPassword('');
            onSaved?.();
        } catch (e) {
            setError(
                e instanceof Error
                    ? e.message
                    : 'Could not save the mail server'
            );
        } finally {
            setSaving(false);
        }
    };

    const field = (
        label: string,
        value: string,
        set: (v: string) => void,
        props: Record<string, unknown> = {}
    ) => (
        <div>
            <label className={INSTANCE_FORM.label}>{label}</label>
            <input
                value={value}
                onChange={(e) => set(e.target.value)}
                className={INSTANCE_FORM.input}
                autoComplete="off"
                {...props}
            />
        </div>
    );

    return (
        <div data-testid="instance-smtp-form">
            <InstanceSetupCard
                title="Send through your mail server"
                steps={[
                    'Any SMTP server works — your domain\u2019s mail provider, a Gmail app password, Mailgun, Postmark.',
                    'Enter its details. Every email this instance sends leaves through it, from the sender below.',
                ]}
            >
                <form
                    className="space-y-3.5"
                    onSubmit={(e) => {
                        e.preventDefault();
                        void save();
                    }}
                >
                    <div className="grid grid-cols-[1fr_6rem] gap-3">
                        {field('SMTP host', host, setHost, {
                            placeholder: 'smtp.yourdomain.com',
                            'aria-label': 'SMTP host',
                        })}
                        {field('Port', port, setPort, {
                            inputMode: 'numeric',
                            'aria-label': 'SMTP port',
                        })}
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                        {field('Username', username, setUsername, {
                            placeholder: 'optional',
                            'aria-label': 'SMTP username',
                        })}
                        {field('Password', password, setPassword, {
                            type: 'password',
                            placeholder: 'optional',
                            'aria-label': 'SMTP password',
                        })}
                    </div>
                    {field('Send as', fromEmail, setFromEmail, {
                        placeholder: 'NoClick <noclick@yourdomain.com>',
                        'aria-label': 'Sender address',
                    })}
                    {error && (
                        <p
                            role="alert"
                            className="text-xs text-red-600 dark:text-red-400"
                        >
                            {error}
                        </p>
                    )}
                    <div className="flex items-center gap-2">
                        <button
                            type="submit"
                            disabled={saving || !ready}
                            className={INSTANCE_FORM.primaryButton}
                        >
                            {saving ? 'Checking\u2026' : submitLabel}
                        </button>
                        <span className={INSTANCE_FORM.note}>
                            Checked with a real login — stored encrypted
                        </span>
                    </div>
                </form>
            </InstanceSetupCard>
        </div>
    );
}
