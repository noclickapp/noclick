// Register this instance's OAuth app for one provider: the callback URL to paste
// into the provider's console, and the client id/secret to paste back.
//
// Shared deliberately. It is the same job in two places — Settings → OAuth Apps
// (browsing providers) and the node credential panel (a specific provider is
// blocking someone right now) — and the second is where most people meet it, so
// the two must not drift into different instructions.
//
// Self-hosted only; callers gate on isLocalEdition(). Writes go through the
// backend (instance_oauth:set), which owns encryption — the secret is never
// stored or echoed by the client.

import { useState } from 'react';
import { ExternalLink } from 'lucide-react';
import { toast } from 'sonner';
import { CopyableReadonlyField } from '~/components/ui/CopyableReadonlyField';
import { sendEventAsync } from '~/lib/socket-sender';
import { OAUTH_PROVIDER_SETUP } from '~/lib/oauthProviderSetup';
import { InstanceOAuthSetRequest } from '~/types/socket-events.generated';

interface Props {
    provider: string;
    /** Prefill when editing an existing entry. The secret is never prefilled. */
    initialClientId?: string;
    /** True when a secret is already stored, so the field can say "leave blank to keep". */
    hasStoredSecret?: boolean;
    onSaved: () => void;
    onCancel?: () => void;
}

export function callbackUrlFor(provider: string): string {
    if (typeof window === 'undefined') return '';
    return `${window.location.origin}/api/auth/${provider}/callback`;
}

export function InstanceOAuthAppForm({
    provider,
    initialClientId = '',
    hasStoredSecret = false,
    onSaved,
    onCancel,
}: Props) {
    const meta = OAUTH_PROVIDER_SETUP[provider];
    const [clientId, setClientId] = useState(initialClientId);
    const [clientSecret, setClientSecret] = useState('');
    const [saving, setSaving] = useState(false);

    // PKCE providers have no secret to give; asking for one invites confusion.
    const needsSecret = (meta?.backendEnv ?? []).some((v) => v.endsWith('_CLIENT_SECRET'));
    const label = meta?.label ?? provider;

    const save = async () => {
        if (!clientId.trim()) return;
        setSaving(true);
        try {
            await sendEventAsync(
                InstanceOAuthSetRequest.create({
                    request_id: crypto.randomUUID(),
                    provider,
                    client_id: clientId.trim(),
                    client_secret: clientSecret.trim() || undefined,
                }),
            );
            toast.success(`${label} OAuth app saved`);
            setClientSecret('');
            onSaved();
        } catch (e) {
            toast.error(e instanceof Error ? e.message : `Could not save the ${label} OAuth app`);
        } finally {
            setSaving(false);
        }
    };

    // Shared so the copy field and the two inputs line up exactly.
    const inputClass =
        'w-full h-9 px-3 text-sm bg-background/40 border border-input dark:border-white/[0.08] rounded-lg ' +
        'text-foreground placeholder:text-[hsl(var(--placeholder))] outline-none ' +
        'focus:border-muted-foreground/40 dark:focus:border-white/20 font-mono';

    return (
        <div className="space-y-3">
            <div>
                <div className="flex items-center justify-between mb-1.5">
                    <label className="block text-xs font-medium text-muted-foreground dark:text-white/50">
                        Redirect URL — add this to the app
                    </label>
                    {meta?.consoleUrl && (
                        <a
                            href={meta.consoleUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1 text-xs text-muted-foreground/70 dark:text-white/30 hover:text-foreground/80 transition-colors"
                        >
                            {label} console
                            <ExternalLink className="w-3 h-3" />
                        </a>
                    )}
                </div>
                <CopyableReadonlyField
                    value={callbackUrlFor(provider)}
                    inputClassName={`${inputClass} text-xs`}
                />
            </div>

            <div className={needsSecret ? 'grid grid-cols-2 gap-3' : ''}>
                <div>
                    <label className="block text-xs font-medium text-muted-foreground dark:text-white/50 mb-1.5">
                        Client ID
                    </label>
                    <input
                        value={clientId}
                        onChange={(e) => setClientId(e.target.value)}
                        onKeyDown={(e) => e.key === 'Enter' && save()}
                        placeholder="from the OAuth app"
                        className={inputClass}
                    />
                </div>
                {needsSecret && (
                    <div>
                        <label className="block text-xs font-medium text-muted-foreground dark:text-white/50 mb-1.5">
                            Client Secret
                        </label>
                        <input
                            type="password"
                            value={clientSecret}
                            onChange={(e) => setClientSecret(e.target.value)}
                            onKeyDown={(e) => e.key === 'Enter' && save()}
                            placeholder={hasStoredSecret ? 'leave blank to keep' : 'from the OAuth app'}
                            className={inputClass}
                        />
                    </div>
                )}
            </div>

            <div className="flex items-center gap-2">
                <button
                    onClick={save}
                    disabled={saving || !clientId.trim()}
                    className="h-9 px-4 text-sm font-medium bg-primary text-primary-foreground rounded-lg hover:bg-foreground/90 disabled:opacity-40 transition-colors"
                >
                    {saving ? 'Saving…' : 'Save'}
                </button>
                {onCancel && (
                    <button
                        onClick={onCancel}
                        className="h-9 px-3 text-sm text-muted-foreground dark:text-white/40 hover:text-foreground/80 transition-colors"
                    >
                        Cancel
                    </button>
                )}
                <span className="text-xs text-muted-foreground/60 dark:text-white/25 ml-auto">
                    Applies immediately — no restart
                </span>
            </div>
        </div>
    );
}
