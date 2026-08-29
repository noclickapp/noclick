// Settings → OAuth Apps & Keys: server-side model-provider keys (self-hosted
// only). The workflow builder's brain reads them from the environment, as does
// any agent left on the instance's shared key. Environment variables take
// precedence over anything saved here. The builder offers the same form inline
// (ProviderKeyPrompt) the moment it finds its key missing; this is the overview.
//
// Backed by instance_keys:* (backend/wss/handlers/instance_keys_handler.py).
import { useCallback, useEffect, useState } from 'react';
import { KeyRound, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import { sendEventAsync } from '~/lib/socket-sender';
import { PROVIDER_KEY_SOURCES, providerKeyLabel } from '~/lib/providerKeys';
import {
    InstanceKeysDeleteRequest,
    InstanceKeysListRequest,
    InstanceKeysSetRequest,
} from '~/types/socket-events.generated';

interface StoredKey {
    env_var: string;
    updated_at: string | null;
}

interface KeysState {
    keys: StoredKey[];
    env_vars: string[];
    supported: string[];
}

const EMPTY: KeysState = { keys: [], env_vars: [], supported: [] };
// The common ones first; the rest of the runtime's provider list after.
const FEATURED = Object.keys(PROVIDER_KEY_SOURCES);

const inputClass =
    'h-9 px-3 text-sm bg-background/40 border border-input dark:border-white/[0.08] rounded-lg ' +
    'text-foreground placeholder:text-[hsl(var(--placeholder))] outline-none ' +
    'focus:border-muted-foreground/40 dark:focus:border-white/20';

export function InstanceProviderKeysSettings() {
    const [state, setState] = useState<KeysState | null>(null);
    const [envVar, setEnvVar] = useState('OPENROUTER_API_KEY');
    const [value, setValue] = useState('');
    const [saving, setSaving] = useState(false);

    const refresh = useCallback(async () => {
        setState((await sendEventAsync(InstanceKeysListRequest.create({ request_id: crypto.randomUUID() }))) as KeysState);
    }, []);

    useEffect(() => {
        refresh().catch((e) => {
            console.error('[InstanceKeys] load failed', e);
            setState(EMPTY);
        });
    }, [refresh]);

    const save = async () => {
        const key = value.trim();
        if (!key) return;
        setSaving(true);
        try {
            setState(
                (await sendEventAsync(
                    InstanceKeysSetRequest.create({ request_id: crypto.randomUUID(), env_var: envVar, value: key }),
                )) as KeysState,
            );
            setValue('');
            toast.success(`${providerKeyLabel(envVar)} key saved`);
        } catch (e) {
            toast.error(e instanceof Error ? e.message : 'Could not save the key');
        } finally {
            setSaving(false);
        }
    };

    const remove = async (name: string) => {
        try {
            setState(
                (await sendEventAsync(
                    InstanceKeysDeleteRequest.create({ request_id: crypto.randomUUID(), env_var: name }),
                )) as KeysState,
            );
            toast.success(`${providerKeyLabel(name)} key removed`);
        } catch (e) {
            toast.error(e instanceof Error ? e.message : 'Could not remove the key');
        }
    };

    const supported = state?.supported ?? [];
    const options = [...FEATURED.filter((k) => supported.includes(k)), ...supported.filter((k) => !FEATURED.includes(k))];
    const fromEnv = state?.env_vars ?? [];

    return (
        <div className="mb-10">
            <div className="mb-6">
                <h2 className="text-lg font-semibold text-foreground">Model provider keys</h2>
                <p className="text-sm text-muted-foreground dark:text-white/40 mt-1">
                    The workflow builder runs on this instance&apos;s key, and agents can use it instead of a
                    credential of their own. Keys are stored encrypted; environment variables take precedence.
                </p>
            </div>

            <div className="mb-6 p-4 bg-card dark:bg-foreground/[0.03] border border-border dark:border-white/[0.06] rounded-xl">
                <form
                    className="flex flex-wrap items-end gap-3"
                    onSubmit={(e) => {
                        e.preventDefault();
                        void save();
                    }}
                >
                    <div className="w-[240px]">
                        <label className="block text-xs font-medium text-muted-foreground dark:text-white/50 mb-1.5">
                            Provider
                        </label>
                        <select value={envVar} onChange={(e) => setEnvVar(e.target.value)} className={`${inputClass} w-full`}>
                            {(options.length ? options : [envVar]).map((name) => (
                                <option key={name} value={name}>
                                    {providerKeyLabel(name)} · {name}
                                </option>
                            ))}
                        </select>
                    </div>
                    <div className="flex-1 min-w-[220px]">
                        <label className="block text-xs font-medium text-muted-foreground dark:text-white/50 mb-1.5">
                            Key
                        </label>
                        <input
                            type="password"
                            autoComplete="off"
                            value={value}
                            onChange={(e) => setValue(e.target.value)}
                            placeholder={PROVIDER_KEY_SOURCES[envVar]?.placeholder ?? envVar}
                            className={`${inputClass} w-full font-mono`}
                        />
                    </div>
                    <button
                        type="submit"
                        disabled={saving || !value.trim()}
                        className="h-9 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground transition-opacity disabled:opacity-40"
                    >
                        {saving ? 'Saving…' : 'Save key'}
                    </button>
                </form>
                {PROVIDER_KEY_SOURCES[envVar] && (
                    <p className="mt-3 text-xs text-muted-foreground/70 dark:text-white/30">
                        Get one at{' '}
                        <a href={PROVIDER_KEY_SOURCES[envVar].url} target="_blank" rel="noreferrer" className="underline-offset-2 hover:underline">
                            {PROVIDER_KEY_SOURCES[envVar].url.replace(/^https:\/\//, '')}
                        </a>
                    </p>
                )}
            </div>

            {state === null ? (
                <p className="text-sm text-muted-foreground/60">Loading…</p>
            ) : state.keys.length === 0 ? (
                <p className="text-sm text-muted-foreground/60 dark:text-white/30">No keys saved yet.</p>
            ) : (
                <ul className="divide-y divide-border dark:divide-white/[0.06] border border-border dark:border-white/[0.06] rounded-xl overflow-hidden">
                    {state.keys.map((k) => (
                        <li key={k.env_var} className="flex items-center gap-3 px-4 py-3 bg-card dark:bg-foreground/[0.02]">
                            <KeyRound className="h-4 w-4 shrink-0 text-muted-foreground" strokeWidth={2} />
                            <div className="min-w-0 flex-1">
                                <div className="text-sm text-foreground">{providerKeyLabel(k.env_var)}</div>
                                <div className="text-xs text-muted-foreground/70 font-mono truncate">
                                    {k.env_var}
                                    {k.updated_at ? ` · updated ${new Date(k.updated_at).toLocaleDateString()}` : ''}
                                </div>
                            </div>
                            <button
                                type="button"
                                onClick={() => void remove(k.env_var)}
                                aria-label={`Remove ${k.env_var}`}
                                className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground"
                            >
                                <Trash2 className="h-4 w-4" strokeWidth={2} />
                            </button>
                        </li>
                    ))}
                </ul>
            )}

            {fromEnv.length > 0 && (
                <p className="mt-4 text-xs text-muted-foreground/70 dark:text-white/30">
                    Set by environment variables, which take precedence over anything saved here:{' '}
                    <span className="font-mono">{fromEnv.join(', ')}</span>
                </p>
            )}
        </div>
    );
}
