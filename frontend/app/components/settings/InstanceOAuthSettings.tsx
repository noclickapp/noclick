// Settings → OAuth Apps (self-hosted only). One OAuth client per provider,
// shared by everyone on this instance, replacing the alternative of editing two
// .env files and restarting both processes.
//
// Most people never come here: the same form is offered inline by the node
// credential panel at the moment a provider blocks them (InstanceOAuthAppForm).
// This page is the overview — what is registered, what the environment already
// covers, and somewhere to change a client id after the fact.
//
// Backed by instance_oauth:* (backend/wss/handlers/instance_oauth_handler.py).

import { useCallback, useEffect, useMemo, useState } from 'react';
import { Check, ChevronDown, KeyRound, Search, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import { cn } from '~/lib/utils';
import { Popover, PopoverContent, PopoverTrigger } from '~/components/ui/popover';
import { BrandIcon } from '~/components/shared/BrandIcon';
import { getOAuthProviderIcon } from '~/utils/credentialIcons';
import { InstanceOAuthAppForm } from '~/components/credential/InstanceOAuthAppForm';
import { sendEventAsync } from '~/lib/socket-sender';
import { OAUTH_PROVIDER_SETUP } from '~/lib/oauthProviderSetup';
import { InstanceOAuthListRequest, InstanceOAuthDeleteRequest } from '~/types/socket-events.generated';

interface StoredApp {
    provider: string;
    client_id: string;
    has_secret: boolean;
    updated_at: string | null;
}

const PROVIDERS = Object.entries(OAUTH_PROVIDER_SETUP)
    .filter(([, meta]) => !meta.appOf) // an alias rides another provider's app
    .map(([key, meta]) => ({ key, label: meta.label }))
    .sort((a, b) => a.label.localeCompare(b.label));

function ProviderIcon({ provider, className }: { provider: string; className?: string }) {
    const { Icon, iconColor, hasServiceIcon } = getOAuthProviderIcon(provider);
    return <BrandIcon Icon={Icon} className={cn(className, hasServiceIcon && iconColor)} />;
}

/** Searchable provider picker, matching the Scope dropdown in Developer settings. */
function ProviderPicker({
    value,
    taken,
    onChange,
}: {
    value: string;
    taken: Set<string>;
    onChange: (provider: string) => void;
}) {
    const [open, setOpen] = useState(false);
    const [search, setSearch] = useState('');
    const q = search.trim().toLowerCase();
    const options = PROVIDERS.filter((p) => !taken.has(p.key) && p.label.toLowerCase().includes(q));
    const selected = PROVIDERS.find((p) => p.key === value);

    return (
        <Popover open={open} onOpenChange={setOpen}>
            <PopoverTrigger asChild>
                <button className="h-9 px-3 rounded-lg text-sm border border-input dark:border-white/[0.08] bg-background/40 text-foreground hover:border-muted-foreground/30 dark:hover:border-white/[0.12] transition-colors flex items-center gap-2 w-full">
                    {selected ? (
                        <ProviderIcon provider={selected.key} className="w-4 h-4 flex-shrink-0" />
                    ) : (
                        <KeyRound className="w-4 h-4 flex-shrink-0 text-muted-foreground/70 dark:text-white/30" />
                    )}
                    <span
                        className={cn(
                            'truncate flex-1 text-left',
                            !selected && 'text-muted-foreground dark:text-white/40',
                        )}
                    >
                        {selected ? selected.label : 'Choose a provider'}
                    </span>
                    <ChevronDown className="w-3 h-3 flex-shrink-0 text-muted-foreground/70 dark:text-zinc-600" />
                </button>
            </PopoverTrigger>
            <PopoverContent
                align="start"
                className="w-[260px] p-0 bg-popover border-border dark:border-white/[0.08] shadow-2xl rounded-lg overflow-hidden"
            >
                <div className="p-1.5">
                    <div className="flex items-center gap-2 px-2 py-1.5 rounded-md bg-foreground/[0.04]">
                        <Search className="w-3 h-3 text-muted-foreground/70 dark:text-zinc-600 flex-shrink-0" />
                        <input
                            autoFocus
                            value={search}
                            onChange={(e) => setSearch(e.target.value)}
                            placeholder="Search providers..."
                            className="w-full bg-transparent text-xs text-foreground placeholder:text-[hsl(var(--placeholder))] focus:outline-none"
                        />
                    </div>
                </div>
                <div className="max-h-[260px] overflow-y-auto scrollbar-subtle py-1">
                    {options.map((p) => (
                        <button
                            key={p.key}
                            onClick={() => {
                                onChange(p.key);
                                setOpen(false);
                                setSearch('');
                            }}
                            className={cn(
                                'w-full text-left px-3 py-1.5 text-xs flex items-center gap-2 transition-colors',
                                p.key === value
                                    ? 'text-foreground'
                                    : 'text-muted-foreground dark:text-zinc-500 hover:text-foreground/80',
                            )}
                        >
                            <ProviderIcon provider={p.key} className="w-3.5 h-3.5 flex-shrink-0" />
                            <span className="truncate">{p.label}</span>
                            {p.key === value && <Check className="w-3 h-3 ml-auto" />}
                        </button>
                    ))}
                    {options.length === 0 && (
                        <p className="px-3 py-4 text-xs text-center text-muted-foreground/70 dark:text-white/30">
                            {q ? `No provider matches "${search}"` : 'Every provider is already configured'}
                        </p>
                    )}
                </div>
            </PopoverContent>
        </Popover>
    );
}

export function InstanceOAuthSettings() {
    const [apps, setApps] = useState<StoredApp[] | null>(null);
    const [envProviders, setEnvProviders] = useState<string[]>([]);
    const [draftProvider, setDraftProvider] = useState('');
    const [editing, setEditing] = useState<string | null>(null);

    const applyState = useCallback((res: unknown) => {
        const state = res as { apps?: StoredApp[]; env_providers?: string[] } | undefined;
        setApps((state?.apps ?? []) as StoredApp[]);
        setEnvProviders(state?.env_providers ?? []);
    }, []);

    const refresh = useCallback(async () => {
        applyState(await sendEventAsync(InstanceOAuthListRequest.create({ request_id: crypto.randomUUID() })));
    }, [applyState]);

    useEffect(() => {
        refresh().catch((e) => {
            console.error('[InstanceOAuth] load failed', e);
            setApps([]);
        });
    }, [refresh]);

    const remove = async (provider: string) => {
        try {
            applyState(
                await sendEventAsync(
                    InstanceOAuthDeleteRequest.create({ request_id: crypto.randomUUID(), provider }),
                ),
            );
            toast.success(`${OAUTH_PROVIDER_SETUP[provider]?.label ?? provider} OAuth app removed`);
        } catch (e) {
            toast.error(e instanceof Error ? e.message : 'Could not remove the OAuth app');
        }
    };

    const stored = useMemo(
        () => (apps ?? []).filter((a) => !envProviders.includes(a.provider)),
        [apps, envProviders],
    );
    const taken = useMemo(
        () => new Set([...(apps ?? []).map((a) => a.provider), ...envProviders]),
        [apps, envProviders],
    );
    const fromEnv = envProviders.map((p) => OAUTH_PROVIDER_SETUP[p]?.label ?? p).sort();

    return (
        <div>
            <div className="mb-6">
                <h2 className="text-lg font-semibold text-foreground">OAuth Apps</h2>
                <p className="text-sm text-muted-foreground dark:text-white/40 mt-1">
                    Integrations that sign in with OAuth need an app registered with the provider. Add one here and
                    everyone on this instance connects through it.
                </p>
            </div>

            {/* Add a provider — mirrors the "create key" card in Developer settings. */}
            <div className="mb-6 p-4 bg-card dark:bg-foreground/[0.03] border border-border dark:border-white/[0.06] rounded-xl">
                <div className="flex items-end gap-3">
                    <div className="flex-1 max-w-[260px]">
                        <label className="block text-xs font-medium text-muted-foreground dark:text-white/50 mb-1.5">
                            Provider
                        </label>
                        <ProviderPicker
                            value={draftProvider}
                            taken={taken}
                            onChange={(p) => {
                                setDraftProvider(p);
                                setEditing(null);
                            }}
                        />
                    </div>
                    {!draftProvider && (
                        <p className="text-xs text-muted-foreground/60 dark:text-white/25 pb-2.5">
                            Pick one to see the redirect URL it needs.
                        </p>
                    )}
                </div>
                {draftProvider && (
                    <div className="mt-4 pt-4 border-t border-border dark:border-white/[0.06]">
                        <InstanceOAuthAppForm
                            provider={draftProvider}
                            onSaved={() => {
                                setDraftProvider('');
                                void refresh();
                            }}
                            onCancel={() => setDraftProvider('')}
                        />
                    </div>
                )}
            </div>

            {apps === null ? (
                <div className="text-sm text-muted-foreground/70 dark:text-white/30 py-8 text-center">Loading...</div>
            ) : stored.length === 0 && fromEnv.length === 0 ? (
                <div className="text-sm text-muted-foreground/70 dark:text-white/30 py-8 text-center">
                    No OAuth apps yet. Add one above, or connect an integration and you&apos;ll be prompted there.
                </div>
            ) : (
                <div className="space-y-2">
                    {stored.map((app) => {
                        const label = OAUTH_PROVIDER_SETUP[app.provider]?.label ?? app.provider;
                        const isEditing = editing === app.provider;
                        return (
                            <div
                                key={app.provider}
                                className="bg-card dark:bg-foreground/[0.03] border border-border dark:border-white/[0.06] rounded-xl"
                            >
                                <div className="flex items-center gap-4 px-4 py-3">
                                    <ProviderIcon provider={app.provider} className="w-4 h-4 shrink-0" />
                                    <div className="flex-1 min-w-0">
                                        <div className="flex items-center gap-2">
                                            <span className="text-sm font-medium text-foreground">{label}</span>
                                            <code className="text-xs font-mono text-muted-foreground/70 dark:text-white/30 truncate">
                                                {app.client_id}
                                            </code>
                                        </div>
                                        <div className="flex items-center gap-3 mt-0.5">
                                            <span className="text-xs text-muted-foreground/50 dark:text-white/20">
                                                {app.has_secret ? 'Client secret stored' : 'No client secret (PKCE)'}
                                            </span>
                                            {app.updated_at && (
                                                <span className="text-xs text-muted-foreground/50 dark:text-white/20">
                                                    Updated {new Date(app.updated_at).toLocaleDateString()}
                                                </span>
                                            )}
                                        </div>
                                    </div>
                                    <button
                                        onClick={() => setEditing(isEditing ? null : app.provider)}
                                        className="text-xs text-muted-foreground/70 dark:text-white/30 hover:text-foreground/80 transition-colors"
                                    >
                                        {isEditing ? 'Close' : 'Edit'}
                                    </button>
                                    <button
                                        onClick={() => remove(app.provider)}
                                        title={`Remove the ${label} OAuth app`}
                                        className="p-2 text-muted-foreground/50 dark:text-white/20 hover:text-red-600 dark:hover:text-red-400 hover:bg-red-500/10 rounded-lg transition-colors"
                                    >
                                        <Trash2 className="w-4 h-4" />
                                    </button>
                                </div>
                                {isEditing && (
                                    <div className="px-4 pb-4 border-t border-border dark:border-white/[0.06]">
                                        <div className="pt-4">
                                            <InstanceOAuthAppForm
                                                provider={app.provider}
                                                initialClientId={app.client_id}
                                                hasStoredSecret={app.has_secret}
                                                onSaved={() => {
                                                    setEditing(null);
                                                    void refresh();
                                                }}
                                                onCancel={() => setEditing(null)}
                                            />
                                        </div>
                                    </div>
                                )}
                            </div>
                        );
                    })}

                    {/* Env-configured providers are inert here; saying so beats showing
                        them as missing and inviting an edit that would be ignored. */}
                    {fromEnv.length > 0 && (
                        <div className="flex items-start gap-3 px-4 py-3 bg-card dark:bg-foreground/[0.02] border border-border dark:border-white/[0.04] rounded-xl">
                            <KeyRound className="w-4 h-4 text-muted-foreground/50 dark:text-white/20 shrink-0 mt-0.5" />
                            <p className="text-xs text-muted-foreground dark:text-white/40">
                                Set by environment variables, which take precedence over anything saved here:{' '}
                                <span className="text-foreground/80">{fromEnv.join(', ')}</span>
                            </p>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}
