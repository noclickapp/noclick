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
import { INSTANCE_FORM } from './InstanceSetupCard';

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
    const needsSecret = (meta?.backendEnv ?? []).some((v) => v.endsWith('_CLIENT_SECRET') || v.endsWith('_APP_SECRET'));
    const label = meta?.label ?? provider;
    // Name the fields the way the provider's console does (TikTok: client key; Meta: app id).
    const idVar = (meta?.frontendEnv ?? []).find((v) => !v.endsWith('REDIRECT_URI')) ?? '';
    const idLabel = idVar.endsWith('_CLIENT_KEY') ? 'Client key' : idVar.endsWith('_APP_ID') ? 'App ID' : 'Client ID';
    const secretLabel = idVar.endsWith('_APP_ID') ? 'App secret' : 'Client secret';

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

    const inputClass = INSTANCE_FORM.input;

    return (
        <div className="space-y-3.5">
            {/* The way in, first and unmistakable: the console is where the app gets made. */}
            {meta?.consoleUrl && (
                <a
                    href={meta.consoleUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className={INSTANCE_FORM.chip}
                >
                    Open the {label} console
                    <ExternalLink className="h-3.5 w-3.5" />
                </a>
            )}
            <div>
                <label className={INSTANCE_FORM.label}>
                    Redirect URL — add this to the app
                </label>
                <CopyableReadonlyField
                    value={callbackUrlFor(provider)}
                    copyable
                    inputClassName={`${inputClass} text-xs`}
                />
            </div>

            <div className={needsSecret ? 'grid grid-cols-2 gap-3' : ''}>
                <div>
                    <label className={INSTANCE_FORM.label}>
                        {idLabel}
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
                        <label className={INSTANCE_FORM.label}>
                            {secretLabel}
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
                    className={INSTANCE_FORM.primaryButton}
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
                <span className={INSTANCE_FORM.note}>
                    Applies immediately — no restart
                </span>
            </div>
        </div>
    );
}
