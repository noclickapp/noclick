// The builder's inline ask for the one server-side key it is missing. Shown in
// place of a bare "Generation failed" when the backend reports
// provider_key_missing; saving stores the key for the whole instance (the same
// store as Settings → OAuth Apps & Keys) and retries the prompt that failed.
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
    const source = PROVIDER_KEY_SOURCES[envVar];
    const label = providerKeyLabel(envVar);

    const save = async () => {
        const key = value.trim();
        if (!key) return;
        setSaving(true);
        try {
            await sendEventAsync(
                InstanceKeysSetRequest.create({ request_id: crypto.randomUUID(), env_var: envVar, value: key }),
            );
            toast.success(`${label} key saved for this instance`);
            setValue('');
            onSaved();
        } catch (e) {
            toast.error(e instanceof Error ? e.message : `Could not save the ${label} key`);
        } finally {
            setSaving(false);
        }
    };

    return (
        <div
            data-testid="provider-key-prompt"
            className="mt-2 rounded-lg border border-border/60 dark:border-white/[0.08] bg-card dark:bg-foreground/[0.03] px-3 py-2.5 text-xs"
        >
            <div className="flex items-start gap-2 text-muted-foreground">
                <KeyRound className="mt-0.5 h-3.5 w-3.5 shrink-0" strokeWidth={2} />
                <p>
                    The builder runs on {label}. Paste an API key for this instance — it is stored encrypted and
                    shared by everyone here, and you can change it later in Settings.
                    {source && (
                        <>
                            {' '}
                            <a
                                href={source.url}
                                target="_blank"
                                rel="noreferrer"
                                className="inline-flex items-center gap-0.5 text-foreground/80 underline-offset-2 hover:underline"
                            >
                                Get a key
                                <ExternalLink className="h-3 w-3" />
                            </a>
                        </>
                    )}
                </p>
            </div>
            <form
                className="mt-2 flex items-center gap-2"
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
                    className="h-8 min-w-0 flex-1 rounded-md border border-input dark:border-white/[0.08] bg-background/40 px-2.5 font-mono text-xs text-foreground outline-none placeholder:text-[hsl(var(--placeholder))] focus:border-muted-foreground/40 dark:focus:border-white/20"
                />
                <button
                    type="submit"
                    disabled={saving || !value.trim()}
                    className="h-8 shrink-0 rounded-md bg-primary px-3 text-xs font-medium text-primary-foreground transition-opacity disabled:opacity-40"
                >
                    {saving ? 'Saving…' : 'Save and retry'}
                </button>
            </form>
        </div>
    );
}
