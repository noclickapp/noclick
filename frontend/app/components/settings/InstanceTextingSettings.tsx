// Settings → Self-hosted → Texting: the lines people text this instance's assistant on (self-hosted only), WhatsApp
// through the operator's own Meta app and iMessage through their own Sendblue line. Each app's keys are checked with
// the provider and saved together (instance_texting:set); the webhook URL to give the provider is shown here, and
// the secret its webhook is checked with is shown once, when it's made. Texts land in the same conversation as Chat.
import { useState } from 'react';
import { ArrowUpRight, KeyRound, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import { sendEventAsync } from '~/lib/socket-sender';
import { cn } from '~/lib/utils';
import { BUTTON_PRIMARY } from '~/components/shell/buttons';
import { FIELD, FIELD_LABEL, QUIET_LINK } from '~/components/shell/fields';
import { CopyButton } from '~/components/ui/CopyButton';
import { formatPhoneForDisplay } from '~/lib/phoneFormat';
import {
    applyInstanceKeysState,
    type InstanceKeysState,
    type TextingApp,
} from '~/lib/instanceKeys';
import {
    InstanceKeysDeleteRequest,
    InstanceTextingSetRequest,
} from '~/types/socket-events.generated';

interface AppSpec {
    app: TextingApp;
    title: string;
    purpose: string;
    console: { label: string; url: string };
    steps: string[];
    fields: {
        envVar: string;
        label: string;
        placeholder: string;
        secret?: boolean;
    }[];
    /** Every variable the app's keys are saved as, removed together. */
    vars: string[];
    /** The value made for the provider's webhook, shown once. */
    secret: { envVar: string; label: string };
}

const APPS: AppSpec[] = [
    {
        app: 'whatsapp',
        title: 'WhatsApp',
        purpose:
            'Text the assistant from WhatsApp, through a number on your own Meta app.',
        console: {
            label: 'Open Meta for Developers',
            url: 'https://developers.facebook.com/apps',
        },
        steps: [
            'Make a Meta app with WhatsApp. Under WhatsApp → API Setup, copy the phone number ID and an access token (a system user’s, which doesn’t expire). The app secret is under App settings → Basic.',
            'Save them here.',
            'Under WhatsApp → Configuration, set the callback URL and verify token shown after saving, and subscribe to messages.',
        ],
        fields: [
            {
                envVar: 'WHATSAPP_PHONE_NUMBER_ID',
                label: 'Phone number ID',
                placeholder: '1234567890123456',
            },
            {
                envVar: 'WHATSAPP_CLOUD_API_TOKEN',
                label: 'Access token',
                placeholder: 'EAAG…',
                secret: true,
            },
            {
                envVar: 'WHATSAPP_APP_SECRET',
                label: 'App secret',
                placeholder: 'App settings → Basic',
                secret: true,
            },
        ],
        vars: [
            'WHATSAPP_CLOUD_API_TOKEN',
            'WHATSAPP_PHONE_NUMBER_ID',
            'WHATSAPP_APP_SECRET',
            'WHATSAPP_WEBHOOK_VERIFY_TOKEN',
            'WHATSAPP_DISPLAY_NUMBER',
        ],
        secret: {
            envVar: 'WHATSAPP_WEBHOOK_VERIFY_TOKEN',
            label: 'Verify token',
        },
    },
    {
        app: 'imessage',
        title: 'iMessage',
        purpose:
            'Text the assistant from iMessage, through a line on your own Sendblue account.',
        console: {
            label: 'Open Sendblue',
            url: 'https://dashboard.sendblue.com',
        },
        steps: [
            'In Sendblue, copy your API key and secret, and the number of the line to answer on.',
            'Save them here.',
            'Under Developer → Webhooks, add a receive webhook with the URL and secret shown after saving.',
        ],
        fields: [
            {
                envVar: 'SENDBLUE_NUMBER',
                label: 'Line',
                placeholder: '+1 415 555 0123',
            },
            {
                envVar: 'SENDBLUE_API_KEY',
                label: 'API key',
                placeholder: 'sb-api-key-id',
            },
            {
                envVar: 'SENDBLUE_API_SECRET',
                label: 'API secret',
                placeholder: 'sb-api-secret-key',
                secret: true,
            },
        ],
        vars: [
            'SENDBLUE_API_KEY',
            'SENDBLUE_API_SECRET',
            'SENDBLUE_NUMBER',
            'SENDBLUE_WEBHOOK_SECRET',
        ],
        secret: { envVar: 'SENDBLUE_WEBHOOK_SECRET', label: 'Webhook secret' },
    },
];

const ROW = 'py-5 first:pt-0 last:pb-0';
const ROW_TITLE = 'text-[14.5px] font-medium text-foreground';
const ROW_PURPOSE = 'mt-0.5 text-[13px] leading-snug text-muted-foreground';
const NOTE = 'mt-3 text-[13px] leading-snug text-amber-700 dark:text-amber-400';

/** A value to paste into the provider, with a copy button. */
function Pasted({ label, value }: { label: string; value: string }) {
    return (
        <div>
            <div className={FIELD_LABEL}>{label}</div>
            <div className="flex items-center gap-1.5">
                <code className="min-w-0 flex-1 truncate rounded-lg bg-foreground/[0.04] px-3 py-2 font-mono text-[12.5px] text-foreground">
                    {value}
                </code>
                <CopyButton value={value} />
            </div>
        </div>
    );
}

function TextingRow({
    spec,
    state,
    onChange,
}: {
    spec: AppSpec;
    state: InstanceKeysState;
    onChange: (s: InstanceKeysState) => void;
}) {
    const texting = state.texting?.[spec.app];
    const fromEnv = spec.fields.some((f) => state.env_vars.includes(f.envVar));
    const [editing, setEditing] = useState(false);
    const [values, setValues] = useState<Record<string, string>>({});
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState<string | null>(null);
    // The secret made for the provider's webhook, shown this once.
    const [made, setMade] = useState<string | null>(null);

    const save = async () => {
        setSaving(true);
        setError(null);
        try {
            const res = (await sendEventAsync(
                InstanceTextingSetRequest.create({
                    request_id: crypto.randomUUID(),
                    app: spec.app,
                    fields: values,
                })
            )) as
                | (InstanceKeysState & {
                      made?: Record<string, string>;
                      error?: string;
                  })
                | null;
            if (!res || res.error)
                throw new Error(res?.error || 'Could not save the keys');
            applyInstanceKeysState(res);
            onChange(res);
            setMade(res.made?.[spec.secret.envVar] ?? null);
            setValues({});
            setEditing(false);
            toast.success(`${spec.title} keys saved`);
        } catch (e) {
            setError(
                e instanceof Error ? e.message : 'Could not save the keys'
            );
        } finally {
            setSaving(false);
        }
    };

    const remove = async () => {
        try {
            let next: InstanceKeysState | null = null;
            for (const envVar of spec.vars) {
                if (!state.keys.some((k) => k.env_var === envVar)) continue;
                const res = (await sendEventAsync(
                    InstanceKeysDeleteRequest.create({
                        request_id: crypto.randomUUID(),
                        env_var: envVar,
                    })
                )) as (InstanceKeysState & { error?: string }) | null;
                if (!res || res.error)
                    throw new Error(
                        res?.error || `Could not remove ${spec.title}`
                    );
                next = res;
            }
            if (next) {
                applyInstanceKeysState(next);
                onChange(next);
            }
            setMade(null);
            toast.success(`${spec.title} removed`);
        } catch (e) {
            toast.error(
                e instanceof Error
                    ? e.message
                    : `Could not remove ${spec.title}`
            );
        }
    };

    const ready = spec.fields.every((f) => (values[f.envVar] ?? '').trim());
    return (
        <div className={ROW} data-testid={`texting-${spec.app}`}>
            <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                    <div className={ROW_TITLE}>{spec.title}</div>
                    <p className={ROW_PURPOSE}>{spec.purpose}</p>
                </div>
                <a
                    href={spec.console.url}
                    target="_blank"
                    rel="noreferrer"
                    className={cn(QUIET_LINK, 'shrink-0 pt-0.5 text-[13px]')}
                >
                    {spec.console.label}
                    <ArrowUpRight className="h-3.5 w-3.5" />
                </a>
            </div>

            {texting?.configured && !editing ? (
                <div className="mt-3 space-y-3">
                    <div className="flex items-center gap-2 text-[13px] text-foreground">
                        <KeyRound
                            className="h-3.5 w-3.5 shrink-0 text-muted-foreground"
                            strokeWidth={2}
                        />
                        {texting.line
                            ? `Answering on ${formatPhoneForDisplay(texting.line)}`
                            : 'Keys saved'}
                        {fromEnv ? (
                            <span className="text-muted-foreground/70">
                                · set in the environment, which takes precedence
                            </span>
                        ) : (
                            <>
                                <button
                                    type="button"
                                    onClick={() => setEditing(true)}
                                    className="ml-auto text-muted-foreground transition-colors hover:text-foreground"
                                >
                                    Change
                                </button>
                                <button
                                    type="button"
                                    onClick={() => void remove()}
                                    aria-label={`Remove ${spec.title}`}
                                    className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground"
                                >
                                    <Trash2
                                        className="h-4 w-4"
                                        strokeWidth={2}
                                    />
                                </button>
                            </>
                        )}
                    </div>
                    {texting.webhook_url && (
                        <Pasted
                            label="Webhook URL"
                            value={texting.webhook_url}
                        />
                    )}
                    {made ? (
                        <Pasted
                            label={`${spec.secret.label} (shown once)`}
                            value={made}
                        />
                    ) : fromEnv ? null : (
                        <p className={ROW_PURPOSE}>
                            The {spec.secret.label.toLowerCase()} was shown when
                            the keys were first saved. To make a new one, remove{' '}
                            {spec.title} and save it again.
                        </p>
                    )}
                </div>
            ) : (
                <form
                    className="mt-3 space-y-3"
                    onSubmit={(e) => {
                        e.preventDefault();
                        void save();
                    }}
                >
                    <ol className="list-decimal space-y-0.5 pl-4 text-[13px] leading-relaxed text-muted-foreground">
                        {spec.steps.map((step) => (
                            <li key={step}>{step}</li>
                        ))}
                    </ol>
                    {spec.fields.map((f) => (
                        <div key={f.envVar}>
                            <label
                                className={FIELD_LABEL}
                                htmlFor={`texting-${f.envVar}`}
                            >
                                {f.label}
                            </label>
                            <input
                                id={`texting-${f.envVar}`}
                                type={f.secret ? 'password' : 'text'}
                                autoComplete="off"
                                value={values[f.envVar] ?? ''}
                                onChange={(e) =>
                                    setValues((v) => ({
                                        ...v,
                                        [f.envVar]: e.target.value,
                                    }))
                                }
                                placeholder={f.placeholder}
                                aria-invalid={error ? true : undefined}
                                className={cn(
                                    FIELD,
                                    'font-mono text-[13.5px] placeholder:font-sans aria-[invalid]:border-red-500/60'
                                )}
                            />
                        </div>
                    ))}
                    {error && (
                        <p
                            role="alert"
                            className="text-[13px] text-red-600 dark:text-red-400"
                        >
                            {error}
                        </p>
                    )}
                    <div className="flex items-center gap-2">
                        <button
                            type="submit"
                            disabled={saving || !ready}
                            className={cn(BUTTON_PRIMARY, 'h-10 px-4')}
                        >
                            {saving ? 'Checking…' : 'Check and save'}
                        </button>
                        {editing && (
                            <button
                                type="button"
                                onClick={() => setEditing(false)}
                                className="h-10 px-3 text-[13.5px] text-muted-foreground hover:text-foreground"
                            >
                                Cancel
                            </button>
                        )}
                    </div>
                </form>
            )}
        </div>
    );
}

/** The texting apps, under the instance's keys. */
export function InstanceTextingSettings({
    state,
    onChange,
}: {
    state: InstanceKeysState;
    onChange: (s: InstanceKeysState) => void;
}) {
    const texting = state.texting;
    if (!texting) return null;
    const url = texting.whatsapp.webhook_url;
    const reachable =
        !!url &&
        url.startsWith('https://') &&
        !/\/\/(localhost|127\.|0\.0\.0\.0|[^/]*\.localhost)/.test(url);
    return (
        <div className="mb-10" data-testid="instance-texting">
            <div className="mb-6">
                <h2 className="text-lg font-semibold text-foreground">
                    Texting
                </h2>
                <p className="mt-1 text-sm text-muted-foreground dark:text-white/40">
                    Text this instance’s assistant from your phone. It answers
                    in the same conversation as Chat; each person links their
                    number from Chat → Connect.
                </p>
                {!texting.whatsapp.redis && (
                    <p className={NOTE}>
                        Texting needs Redis, which this instance doesn’t have
                        yet: set REDIS_URL (the Docker install comes with it).
                    </p>
                )}
                {!reachable && (
                    <p className={NOTE}>
                        Meta and Sendblue reach this instance at{' '}
                        {url ? (
                            <code className="font-mono">
                                {url.replace(/\/whatsapp\/meta$/, '')}
                            </code>
                        ) : (
                            'its public URL'
                        )}
                        , which has to be a public HTTPS address: set
                        PUBLIC_WEBHOOK_URL, or put a tunnel in front of it.
                    </p>
                )}
            </div>
            <div className="divide-y divide-border dark:divide-foreground/[0.08]">
                {APPS.map((spec) => (
                    <TextingRow
                        key={spec.app}
                        spec={spec}
                        state={state}
                        onChange={onChange}
                    />
                ))}
            </div>
        </div>
    );
}
