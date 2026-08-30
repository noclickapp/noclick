// Settings → Self-hosted: the keys the INSTANCE holds (self-hosted only) — the
// OpenRouter key the workflow builder runs on, the WAHooks key behind WhatsApp
// QR sign-in. Each is offered inline the first time it is missing
// (InstanceKeyPrompt); this is where they are seen, replaced or removed.
// Stored encrypted; an environment variable of the same name takes precedence.
//
// Backed by instance_keys:* (backend/wss/handlers/instance_keys_handler.py).
import { useCallback, useEffect, useState } from 'react';
import { ExternalLink, KeyRound, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import { sendEventAsync } from '~/lib/socket-sender';
import { PROVIDER_KEY_SOURCES } from '~/lib/providerKeys';
import {
    InstanceKeysDeleteRequest,
    InstanceKeysListRequest,
    InstanceKeysSetRequest,
} from '~/types/socket-events.generated';

/** What each key is for, in the operator's terms. */
const INSTANCE_KEYS: { envVar: string; title: string; purpose: string }[] = [
    { envVar: 'OPENROUTER_API_KEY', title: 'Workflow builder', purpose: 'The builder runs on OpenRouter with this key, shared by everyone on the instance.' },
    { envVar: 'WAHOOKS_API_KEY', title: 'WhatsApp QR sign-in', purpose: 'WhatsApp connections are issued by WAHooks; every QR scan on this instance uses this key.' },
];

interface StoredKey {
    env_var: string;
    updated_at: string | null;
}

interface KeysState {
    keys: StoredKey[];
    env_vars: string[];
    supported: string[];
}

const inputClass =
    'h-9 w-full px-3 text-sm font-mono bg-foreground/[0.035] dark:bg-white/[0.045] border border-input dark:border-white/[0.12] rounded-lg ' +
    'text-foreground placeholder:text-[hsl(var(--placeholder))] outline-none focus:border-muted-foreground/40 dark:focus:border-white/20';

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
            onChange(res);
            toast.success(`${source?.label ?? envVar} key removed`);
        } catch (e) {
            toast.error(e instanceof Error ? e.message : 'Could not remove the key');
        }
    };

    return (
        <div className="p-4 bg-card dark:bg-foreground/[0.03] border border-border dark:border-white/[0.06] rounded-xl">
            <div className="flex items-start justify-between gap-3">
                <div>
                    <div className="text-sm font-medium text-foreground">{title}</div>
                    <p className="mt-0.5 text-xs text-muted-foreground dark:text-white/40">{purpose}</p>
                </div>
                {source && (
                    <a
                        href={source.url}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-border bg-foreground/[0.06] px-2.5 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-foreground/[0.12]"
                    >
                        Get a {source.label} key
                        <ExternalLink className="h-3.5 w-3.5" />
                    </a>
                )}
            </div>

            {fromEnv ? (
                <p className="mt-3 text-xs text-muted-foreground">
                    Set by the <code className="font-mono">{envVar}</code> environment variable, which takes precedence over anything saved here.
                </p>
            ) : (
                <>
                    {stored && (
                        <div className="mt-3 flex items-center gap-2 text-xs text-foreground">
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
                        className="mt-3 flex items-center gap-2"
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
                            className={`${inputClass} aria-[invalid]:border-red-500/60`}
                        />
                        <button
                            type="submit"
                            disabled={saving || !value.trim()}
                            className="h-9 shrink-0 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground transition-opacity disabled:opacity-40"
                        >
                            {saving ? 'Checking…' : stored ? 'Replace' : 'Save'}
                        </button>
                    </form>
                    {error && (
                        <p role="alert" className="mt-2 text-xs text-red-600 dark:text-red-400">
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
        setState((await sendEventAsync(InstanceKeysListRequest.create({ request_id: crypto.randomUUID() }))) as KeysState);
    }, []);

    useEffect(() => {
        refresh().catch((e) => {
            console.error('[InstanceKeys] load failed', e);
            setState({ keys: [], env_vars: [], supported: [] });
        });
    }, [refresh]);

    return (
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
                <div className="space-y-4">
                    {INSTANCE_KEYS.map((k) => (
                        <KeyRow key={k.envVar} {...k} state={state} onChange={setState} />
                    ))}
                </div>
            )}
        </div>
    );
}
