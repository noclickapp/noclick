// The builder's inline ask for the one server-side key it is missing. Shown in
// place of a bare "Generation failed" when the backend reports
// provider_key_missing; saving validates the key with the provider, stores it
// for the whole instance (the same store as Settings → Self-hosted) and
// retries the prompt that failed.
import { useState } from 'react';
import { ExternalLink, KeyRound } from 'lucide-react';
import { toast } from 'sonner';
import { sendEventAsync } from '~/lib/socket-sender';
import { InstanceKeysSetRequest } from '~/types/socket-events.generated';
import { PROVIDER_KEY_SOURCES, providerKeyLabel } from '~/lib/providerKeys';

export function ProviderKeyPrompt({
    envVar,
    onSaved,
}: {
    envVar: string;
    /** Called once the key is stored — the caller retries the failed prompt. */
    onSaved: () => void;
}) {
    const [value, setValue] = useState('');
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const source = PROVIDER_KEY_SOURCES[envVar];
    const label = providerKeyLabel(envVar);

    const save = async () => {
        const key = value.trim();
        if (!key) return;
        setSaving(true);
        setError(null);
        try {
            // The sender resolves with the backend's reply either way; the
            // provider's verdict rides its `error`.
            const res = (await sendEventAsync(
                InstanceKeysSetRequest.create({ request_id: crypto.randomUUID(), env_var: envVar, value: key }),
            )) as { error?: string } | null;
            if (res?.error) throw new Error(res.error);
            toast.success(`${label} key saved for this instance`);
            setValue('');
            onSaved();
        } catch (e) {
            // The provider's own verdict (invalid key, no credits) lands here.
            setError(e instanceof Error ? e.message : `Could not save the ${label} key`);
        } finally {
            setSaving(false);
        }
    };

    return (
        <div data-testid="provider-key-prompt" className="mt-2 space-y-2 text-xs">
            <div className="flex items-center justify-between gap-3">
                <p className="flex items-center gap-2 text-muted-foreground">
                    <KeyRound className="h-3.5 w-3.5 shrink-0" strokeWidth={2} />
                    Paste an {label} API key for this instance — stored encrypted, changeable later in Settings.
                </p>
                {source && (
                    <a
                        href={source.url}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-border bg-foreground/[0.06] px-2.5 py-1 font-medium text-foreground transition-colors hover:bg-foreground/[0.12]"
                    >
                        Get a key
                        <ExternalLink className="h-3 w-3" />
                    </a>
                )}
            </div>
            <form
                className="flex items-center gap-2"
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
                    className="h-8 min-w-0 flex-1 rounded-md border border-input bg-background/40 px-2.5 font-mono text-xs text-foreground outline-none placeholder:text-[hsl(var(--placeholder))] focus:border-muted-foreground/40 aria-[invalid]:border-red-500/60"
                />
                <button
                    type="submit"
                    disabled={saving || !value.trim()}
                    className="h-8 shrink-0 rounded-md bg-primary px-3 text-xs font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-40"
                >
                    {saving ? 'Checking…' : 'Save and retry'}
                </button>
            </form>
            {error && (
                <p role="alert" className="text-red-600 dark:text-red-400">
                    {error}
                </p>
            )}
        </div>
    );
}
