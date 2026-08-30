// An inline ask for one key the INSTANCE is missing — the builder's OpenRouter
// key, the WAHooks key behind WhatsApp QR sign-in. Shown in place of a dead end
// (a bare "Generation failed", an error panel) wherever the backend reports a
// typed missing-key failure. Saving validates the key with the provider, stores
// it for the whole instance (the same store as Settings → Self-hosted) and
// hands control back to the caller to retry what failed.
import { useState } from 'react';
import { ExternalLink } from 'lucide-react';
import { toast } from 'sonner';
import { sendEventAsync } from '~/lib/socket-sender';
import { InstanceKeysSetRequest } from '~/types/socket-events.generated';
import { PROVIDER_KEY_SOURCES, providerKeyLabel } from '~/lib/providerKeys';
import { applyInstanceKeysState, type InstanceKeysState } from '~/lib/instanceKeys';
import { INSTANCE_FORM, InstanceSetupCard } from './InstanceSetupCard';

export function InstanceKeyPrompt({
    envVar,
    onSaved,
    title,
    steps,
    submitLabel = 'Save and retry',
}: {
    envVar: string;
    /** Called once the key is stored — the caller retries what failed. */
    onSaved: () => void;
    /** What the key unlocks, in the caller's words. */
    title?: string;
    steps?: string[];
    submitLabel?: string;
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
                InstanceKeysSetRequest.create({
                    request_id: crypto.randomUUID(),
                    env_var: envVar,
                    value: key,
                })
            )) as (InstanceKeysState & { error?: string }) | null;
            if (res?.error) throw new Error(res.error);
            applyInstanceKeysState(res);
            toast.success(`${label} key saved for this instance`);
            setValue('');
            onSaved();
        } catch (e) {
            // The provider's own verdict (invalid key, no credits) lands here.
            setError(
                e instanceof Error
                    ? e.message
                    : `Could not save the ${label} key`
            );
        } finally {
            setSaving(false);
        }
    };

    return (
        <div data-testid="instance-key-prompt">
            <InstanceSetupCard
                title={title ?? `Add this instance's ${label} key`}
                steps={
                    steps ?? [
                        `Create a key in your ${label} account (button below).`,
                        'Paste it here. Everyone on this instance shares it, once.',
                    ]
                }
            >
                {source && (
                    <a
                        href={source.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className={INSTANCE_FORM.chip}
                    >
                        Get your {label} key
                        <ExternalLink className="h-3.5 w-3.5" />
                    </a>
                )}
                <form
                    onSubmit={(e) => {
                        e.preventDefault();
                        void save();
                    }}
                >
                    <label
                        className={INSTANCE_FORM.label}
                        htmlFor={`instance-key-${envVar}`}
                    >
                        API key
                    </label>
                    <input
                        id={`instance-key-${envVar}`}
                        type="password"
                        autoComplete="off"
                        value={value}
                        onChange={(e) => setValue(e.target.value)}
                        placeholder={source?.placeholder ?? envVar}
                        aria-invalid={error ? true : undefined}
                        className={`${INSTANCE_FORM.input} aria-[invalid]:border-red-500/60 dark:aria-[invalid]:border-red-500/60`}
                    />
                    {error && (
                        <p
                            role="alert"
                            className="mt-1.5 text-xs text-red-600 dark:text-red-400"
                        >
                            {error}
                        </p>
                    )}
                    <div className="mt-3.5 flex items-center gap-2">
                        <button
                            type="submit"
                            disabled={saving || !value.trim()}
                            className={INSTANCE_FORM.primaryButton}
                        >
                            {saving ? 'Checking…' : submitLabel}
                        </button>
                        <span className={INSTANCE_FORM.note}>
                            Stored encrypted — change it in Settings
                        </span>
                    </div>
                </form>
            </InstanceSetupCard>
        </div>
    );
}
