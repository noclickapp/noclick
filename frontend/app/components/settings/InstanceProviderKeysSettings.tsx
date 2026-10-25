// Settings → Self-hosted: the keys the INSTANCE holds (self-hosted only) — the
// OpenRouter key the workflow builder runs on, the WAHooks key behind WhatsApp
// QR sign-in. Each is offered inline the first time it is missing
// (InstanceKeyPrompt); this is where they are seen, replaced or removed.
// Stored encrypted; an environment variable of the same name takes precedence.
//
// Backed by instance_keys:* (backend/wss/handlers/instance_keys_handler.py).
import { useCallback, useEffect, useState } from 'react';
import { ArrowUpRight, KeyRound, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import { sendEventAsync } from '~/lib/socket-sender';
import { cn } from '~/lib/utils';
import { BUTTON_PRIMARY } from '~/components/shell/buttons';
import { FIELD, QUIET_LINK } from '~/components/shell/fields';
import { PROVIDER_KEY_SOURCES } from '~/lib/providerKeys';
import { InstanceSmtpForm } from '~/components/credential/InstanceSmtpForm';
import { InstanceTextingSettings } from '~/components/settings/InstanceTextingSettings';
import { applyInstanceKeysState, loadInstanceKeys, type InstanceKeysState as KeysState } from '~/lib/instanceKeys';
import { InstanceKeysDeleteRequest, InstanceKeysSetRequest } from '~/types/socket-events.generated';

/** What each key is for, in the operator's terms. */
const INSTANCE_KEYS: { envVar: string; title: string; purpose: string }[] = [
    { envVar: 'OPENROUTER_API_KEY', title: 'Workflow builder', purpose: 'The builder runs on OpenRouter with this key, shared by everyone on the instance.' },
    { envVar: 'WAHOOKS_API_KEY', title: 'WhatsApp QR sign-in', purpose: 'WhatsApp connections are issued by WAHooks; every QR scan on this instance uses this key.' },
    { envVar: 'DISCORD_BOT_TOKEN', title: 'Discord message triggers', purpose: 'The instance keeps this bot connected to Discord so "On Channel Message" and "On Bot Mention" fire instantly. Pair it with the Discord OAuth app above; enable Message Content Intent on the bot to read message text.' },
    // Operations the cloud runs on NoClick's own keys. Here they run on the instance's — or, for Exa and Perplexity, on each user's own credential.
    { envVar: 'DECODO_AUTH_TOKEN', title: 'Reddit scraping', purpose: 'Public Reddit feeds run on Decodo. Use the Web Scraping API authentication token from its playground.' },
    { envVar: 'APIFY_API_TOKEN', title: 'LinkedIn and Instagram scraping', purpose: 'Scraping operations run on Apify. Without this token they are unavailable on this instance.' },
    { envVar: 'EXA_API_KEY', title: 'Exa search', purpose: 'Lets Exa nodes search without a credential of their own; users can still connect one.' },
    { envVar: 'PERPLEXITY_API_KEY', title: 'Perplexity', purpose: 'Lets Perplexity nodes run without a credential of their own; users can still connect one.' },
    // Phone linking: users prove they own a number with a code sent through the instance's Twilio Verify service.
    { envVar: 'TWILIO_ACCOUNT_SID', title: 'Phone linking (Twilio)', purpose: 'Settings → Phone sends verification codes through your Twilio account. Set the account SID here, then its auth token and the Verify service below.' },
    { envVar: 'TWILIO_AUTH_TOKEN', title: 'Twilio auth token', purpose: 'The auth token of the Twilio account above.' },
    { envVar: 'TWILIO_VERIFY_SERVICE_SID', title: 'Twilio Verify service', purpose: 'The Verify service (VA…) the codes are sent from. Phone linking stays hidden until all three are set.' },
];

const SMTP_VARS = ['SMTP_HOST', 'SMTP_PORT', 'SMTP_USERNAME', 'SMTP_PASSWORD', 'FROM_EMAIL'];


// One key per row of a divided list: the field stands on its own, never inside a card.
const ROW = 'py-5 first:pt-0 last:pb-0';
const ROW_TITLE = 'text-[14.5px] font-medium text-foreground';
const ROW_PURPOSE = 'mt-0.5 text-[13px] leading-snug text-muted-foreground';

function KeyRow({ envVar, title, purpose, state, onChange }: { envVar: string; title: string; purpose: string; state: KeysState; onChange: (s: KeysState) => void }) {
    const [value, setValue] = useState('');
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const source = PROVIDER_KEY_SOURCES[envVar];
    const stored = state.keys.find((k) => k.env_var === envVar) ?? null;
    const fromEnv = state.env_vars.includes(envVar);

    const save = async () => {
        const key = value.trim();
        if (!key) return;
        setSaving(true);
        setError(null);
        try {
            // The sender resolves with the backend's reply either way; the provider's verdict rides its `error`.
            const res = (await sendEventAsync(
                InstanceKeysSetRequest.create({ request_id: crypto.randomUUID(), env_var: envVar, value: key }),
            )) as (KeysState & { error?: string }) | null;
            if (!res || res.error) throw new Error(res?.error || 'Could not save the key');
            applyInstanceKeysState(res);
            onChange(res);
            setValue('');
            toast.success(`${source?.label ?? envVar} key saved`);
        } catch (e) {
            setError(e instanceof Error ? e.message : 'Could not save the key');
        } finally {
            setSaving(false);
        }
    };

    const remove = async () => {
        try {
            const res = (await sendEventAsync(
                InstanceKeysDeleteRequest.create({ request_id: crypto.randomUUID(), env_var: envVar }),
            )) as (KeysState & { error?: string }) | null;
            if (!res || res.error) throw new Error(res?.error || 'Could not remove the key');
            applyInstanceKeysState(res);
            onChange(res);
            toast.success(`${source?.label ?? envVar} key removed`);
        } catch (e) {
            toast.error(e instanceof Error ? e.message : 'Could not remove the key');
        }
    };

    return (
        <div className={ROW}>
            <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                    <div className={ROW_TITLE}>{title}</div>
                    <p className={ROW_PURPOSE}>{purpose}</p>
                </div>
                {source && (
                    <a href={source.url} target="_blank" rel="noreferrer" className={cn(QUIET_LINK, 'shrink-0 pt-0.5 text-[13px]')}>
                        Get {/^[aeiou]/i.test(source.label) ? 'an' : 'a'} {source.label} key
                        <ArrowUpRight className="h-3.5 w-3.5" />
                    </a>
                )}
            </div>

            {fromEnv ? (
                <p className="mt-3 text-[13px] text-muted-foreground">
                    Set by the <code className="font-mono text-[12.5px]">{envVar}</code> environment variable, which takes precedence over anything saved here.
                </p>
            ) : (
                <>
                    {stored && (
                        <div className="mt-3 flex items-center gap-2 text-[13px] text-foreground">
                            <KeyRound className="h-3.5 w-3.5 shrink-0 text-muted-foreground" strokeWidth={2} />
                            A key is saved
                            {stored.updated_at ? <span className="text-muted-foreground/70">· updated {new Date(stored.updated_at).toLocaleDateString()}</span> : null}
                            <button
                                type="button"
                                onClick={() => void remove()}
                                aria-label={`Remove the ${envVar} key`}
                                className="ml-auto rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground"
                            >
                                <Trash2 className="h-4 w-4" strokeWidth={2} />
                            </button>
                        </div>
                    )}
                    <form
                        className="mt-3 flex items-center gap-2.5"
                        onSubmit={(e) => {
                            e.preventDefault();
                            void save();
                        }}
                    >
                        <input
                            type="password"
                            autoComplete="off"
                            value={value}
                            onChange={(e) => setValue(e.target.value)}
                            placeholder={source?.placeholder ?? envVar}
                            aria-label={`${envVar} value`}
                            aria-invalid={error ? true : undefined}
                            className={cn(FIELD, 'font-mono text-[13.5px] placeholder:font-sans aria-[invalid]:border-red-500/60')}
                        />
                        <button type="submit" disabled={saving || !value.trim()} className={cn(BUTTON_PRIMARY, 'h-10 px-4')}>
                            {saving ? 'Checking…' : stored ? 'Replace' : 'Save'}
                        </button>
                    </form>
                    {error && (
                        <p role="alert" className="mt-2 text-[13px] text-red-600 dark:text-red-400">
                            {error}
                        </p>
                    )}
                </>
            )}
        </div>
    );
}

export function InstanceProviderKeysSettings() {
    const [state, setState] = useState<KeysState | null>(null);

    const refresh = useCallback(async () => {
        setState(await loadInstanceKeys());
    }, []);

    useEffect(() => {
        refresh().catch((e) => {
            console.error('[InstanceKeys] load failed', e);
            setState({ keys: [], env_vars: [], supported: [] });
        });
    }, [refresh]);

    return (
        <>
            <div className="mb-10">
                <div className="mb-6">
                    <h2 className="text-lg font-semibold text-foreground">Instance keys</h2>
                    <p className="text-sm text-muted-foreground dark:text-white/40 mt-1">
                        Keys this instance uses on everyone&apos;s behalf. Stored encrypted; environment variables take precedence.
                    </p>
                </div>
                {state === null ? (
                    <p className="text-sm text-muted-foreground/60">Loading…</p>
                ) : (
                    <div className="divide-y divide-border dark:divide-foreground/[0.08]">
                        {INSTANCE_KEYS.map((k) => (
                            <KeyRow key={k.envVar} {...k} state={state} onChange={setState} />
                        ))}
                        <OutboundEmailRow state={state} onChange={setState} />
                    </div>
                )}
            </div>
            {state && <InstanceTextingSettings state={state} onChange={setState} />}
        </>
    );
}

/** Outbound email: the SMTP server the instance sends through (or a Resend key from the environment). */
function OutboundEmailRow({ state, onChange }: { state: KeysState; onChange: (s: KeysState) => void }) {
    const [editing, setEditing] = useState(false);
    const configured = new Set([...state.keys.map((k) => k.env_var), ...state.env_vars]);
    const viaResend = configured.has('RESEND_API_KEY');
    const viaSmtp = configured.has('SMTP_HOST');
    const sender = configured.has('FROM_EMAIL');
    const ready = sender && (viaResend || viaSmtp);
    const fromEnv = state.env_vars.includes('SMTP_HOST') || viaResend;

    const remove = async () => {
        try {
            let next: KeysState | null = null;
            for (const envVar of SMTP_VARS) {
                if (!state.keys.some((k) => k.env_var === envVar)) continue;
                const res = (await sendEventAsync(
                    InstanceKeysDeleteRequest.create({ request_id: crypto.randomUUID(), env_var: envVar }),
                )) as (KeysState & { error?: string }) | null;
                if (!res || res.error) throw new Error(res?.error || 'Could not remove the mail server');
                next = res;
            }
            if (next) {
                applyInstanceKeysState(next);
                onChange(next);
            }
            toast.success('Mail server removed');
        } catch (e) {
            toast.error(e instanceof Error ? e.message : 'Could not remove the mail server');
        }
    };

    return (
        <div className={ROW}>
            <div className={ROW_TITLE}>Outbound email</div>
            <p className={ROW_PURPOSE}>
                The Send Email node and agent updates leave through this: any SMTP server saved here (your domain&apos;s mail provider, a Gmail app password, Mailgun, Postmark), or RESEND_API_KEY + FROM_EMAIL in the environment.
            </p>
            {ready && !editing ? (
                <div className="mt-3 flex items-center gap-2 text-[13px] text-foreground">
                    <KeyRound className="h-3.5 w-3.5 shrink-0 text-muted-foreground" strokeWidth={2} />
                    {viaResend ? 'Sending through Resend' : 'Sending through the saved SMTP server'}
                    {fromEnv ? (
                        <span className="text-muted-foreground/70">· set in the environment, which takes precedence</span>
                    ) : (
                        <>
                            <button type="button" onClick={() => setEditing(true)} className="ml-auto text-muted-foreground transition-colors hover:text-foreground">
                                Change
                            </button>
                            <button
                                type="button"
                                onClick={() => void remove()}
                                aria-label="Remove the mail server"
                                className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground"
                            >
                                <Trash2 className="h-4 w-4" strokeWidth={2} />
                            </button>
                        </>
                    )}
                </div>
            ) : (
                <div className="mt-3">
                    <InstanceSmtpForm
                        titled={false}
                        submitLabel="Check and save"
                        onSaved={() => {
                            setEditing(false);
                            void loadInstanceKeys().then(onChange).catch(() => undefined);
                        }}
                    />
                </div>
            )}
        </div>
    );
}
