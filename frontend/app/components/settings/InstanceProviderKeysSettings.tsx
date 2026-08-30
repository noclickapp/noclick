// Settings → Self-hosted: the OpenRouter key the workflow builder runs on
// (self-hosted only). The builder asks for it inline the first time it is
// missing (ProviderKeyPrompt); this is where it is seen, replaced or removed.
// Stored encrypted for the instance; an OPENROUTER_API_KEY in the environment
// takes precedence over anything saved here.
//
// Backed by instance_keys:* (backend/wss/handlers/instance_keys_handler.py).
import { useCallback, useEffect, useState } from 'react';
import { KeyRound, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import { sendEventAsync } from '~/lib/socket-sender';
import { PROVIDER_KEY_SOURCES } from '~/lib/providerKeys';
import {
    InstanceKeysDeleteRequest,
    InstanceKeysListRequest,
    InstanceKeysSetRequest,
} from '~/types/socket-events.generated';

const ENV_VAR = 'OPENROUTER_API_KEY';
const SOURCE = PROVIDER_KEY_SOURCES[ENV_VAR];

interface StoredKey {
    env_var: string;
    updated_at: string | null;
}

interface KeysState {
    keys: StoredKey[];
    env_vars: string[];
    supported: string[];
}

export function InstanceProviderKeysSettings() {
    const [state, setState] = useState<KeysState | null>(null);
    const [value, setValue] = useState('');
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const refresh = useCallback(async () => {
        setState((await sendEventAsync(InstanceKeysListRequest.create({ request_id: crypto.randomUUID() }))) as KeysState);
    }, []);

    useEffect(() => {
        refresh().catch((e) => {
            console.error('[InstanceKeys] load failed', e);
            setState({ keys: [], env_vars: [], supported: [] });
        });
    }, [refresh]);

    const stored = state?.keys.find((k) => k.env_var === ENV_VAR) ?? null;
    const fromEnv = state?.env_vars.includes(ENV_VAR) ?? false;

    const save = async () => {
        const key = value.trim();
        if (!key) return;
        setSaving(true);
        setError(null);
        try {
            const res = (await sendEventAsync(
                InstanceKeysSetRequest.create({ request_id: crypto.randomUUID(), env_var: ENV_VAR, value: key }),
            )) as (KeysState & { error?: string }) | null;
            if (!res || res.error) throw new Error(res?.error || 'Could not save the key');
            setState(res);
            setValue('');
            toast.success('OpenRouter key saved');
        } catch (e) {
            // The provider's own verdict (invalid key, no credits) lands here.
            setError(e instanceof Error ? e.message : 'Could not save the key');
        } finally {
            setSaving(false);
        }
    };

    const remove = async () => {
        try {
            setState(
                (await sendEventAsync(
                    InstanceKeysDeleteRequest.create({ request_id: crypto.randomUUID(), env_var: ENV_VAR }),
                )) as KeysState,
            );
            toast.success('OpenRouter key removed');
        } catch (e) {
            toast.error(e instanceof Error ? e.message : 'Could not remove the key');
        }
    };

    return (
        <div className="mb-10">
            <div className="mb-6">
                <h2 className="text-lg font-semibold text-foreground">Workflow builder</h2>
                <p className="text-sm text-muted-foreground dark:text-white/40 mt-1">
                    The builder runs on an OpenRouter key shared by everyone on this instance. It is stored
                    encrypted; an <code className="font-mono text-xs">OPENROUTER_API_KEY</code> environment
                    variable takes precedence.
                </p>
            </div>

            <div className="p-4 bg-card dark:bg-foreground/[0.03] border border-border dark:border-white/[0.06] rounded-xl">
                {fromEnv ? (
                    <p className="text-sm text-muted-foreground">
                        Set by the <code className="font-mono text-xs">OPENROUTER_API_KEY</code> environment
                        variable, which takes precedence over anything saved here.
                    </p>
                ) : (
                    <>
                        {stored && (
                            <div className="mb-4 flex items-center gap-3">
                                <KeyRound className="h-4 w-4 shrink-0 text-muted-foreground" strokeWidth={2} />
                                <div className="min-w-0 flex-1 text-sm text-foreground">
                                    A key is saved
                                    {stored.updated_at ? (
                                        <span className="text-muted-foreground/70">
                                            {' '}· updated {new Date(stored.updated_at).toLocaleDateString()}
                                        </span>
                                    ) : null}
                                </div>
                                <button
                                    type="button"
                                    onClick={() => void remove()}
                                    aria-label="Remove the OpenRouter key"
                                    className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground"
                                >
                                    <Trash2 className="h-4 w-4" strokeWidth={2} />
                                </button>
                            </div>
                        )}
                        <form
                            className="flex flex-wrap items-end gap-3"
                            onSubmit={(e) => {
                                e.preventDefault();
                                void save();
                            }}
                        >
                            <div className="flex-1 min-w-[240px]">
                                <label className="block text-xs font-medium text-muted-foreground dark:text-white/50 mb-1.5">
                                    {stored ? 'Replace the key' : 'OpenRouter API key'}
                                </label>
                                <input
                                    type="password"
                                    autoComplete="off"
                                    value={value}
                                    onChange={(e) => setValue(e.target.value)}
                                    placeholder={SOURCE?.placeholder ?? ENV_VAR}
                                    className="h-9 w-full px-3 text-sm font-mono bg-background/40 border border-input dark:border-white/[0.08] rounded-lg text-foreground placeholder:text-[hsl(var(--placeholder))] outline-none focus:border-muted-foreground/40 dark:focus:border-white/20"
                                />
                            </div>
                            <button
                                type="submit"
                                disabled={saving || !value.trim()}
                                className="h-9 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground transition-opacity disabled:opacity-40"
                            >
                                {saving ? 'Checking…' : stored ? 'Replace key' : 'Save key'}
                            </button>
                        </form>
                        {error && (
                            <p role="alert" className="mt-2 text-xs text-red-600 dark:text-red-400">
                                {error}
                            </p>
                        )}
                        {SOURCE && (
                            <p className="mt-3 text-xs text-muted-foreground/70 dark:text-white/30">
                                Get one at{' '}
                                <a href={SOURCE.url} target="_blank" rel="noreferrer" className="underline-offset-2 hover:underline">
                                    {SOURCE.url.replace(/^https:\/\//, '')}
                                </a>
                            </p>
                        )}
                    </>
                )}
            </div>
        </div>
    );
}
