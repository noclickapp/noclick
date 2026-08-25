/**
 * useCredentialOAuth - The in-app credential manager: the shared OAuth connect engine
 * (useOAuthConnect) PLUS credential listing/caching. Used by NodeCredentials and
 * GenerationCredentialSelector. The public API is unchanged; the OAuth connect logic now
 * lives in useOAuthConnect so the public credential-provide page can reuse it with an HTTP
 * transport (see OAuthExchangeContext) instead of the authed socket.
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { sendEventAsync } from '~/lib/socket-sender';
import {
    getAllCredentialsFromCache, getDisplayOnlyCredentials, invalidateCredentialsCache,
    subscribeCredentialCache, upsertCredentialsIntoCache,
} from '~/utils/credentialAutoSelect';
import {
    useOAuthConnect,
    type OAuthCreatedCredential,
    type OAuthSelectionOption,
    type OAuthPendingSelection,
} from '~/hooks/useOAuthConnect';

export type { OAuthSelectionOption, OAuthPendingSelection, OAuthCreatedCredential };

export interface Credential {
    id: string;
    name: string;
    credential_type: string;
    /** Provider-specific display metadata returned by the credential API. */
    metadata?: Record<string, any>;
    created_at: string;
    updated_at: string;
    owner_name?: string | null;
    // Ownership, as told by the backend. `access_type` rides credential:list
    // ('owner' | 'shared' | 'shared_org'); `owned_by_me` rides the
    // workflow-scoped credential:display_info path. Injected display-only
    // descriptors carry neither. Gate owner-only controls on these — never on
    // `owner_name`, which is a display label absent on directly-shared creds.
    access_type?: string;
    owned_by_me?: boolean;
    shared_by_name?: string | null;
    shared_by_email?: string | null;
    over_cap?: boolean;
    revoked_at?: string | null;
    revoked_reason?: string | null;
    connection_status?: string | null;
}

export interface UseCredentialOAuthOptions {
    onCredentialCreated?: (credentialId: string, provider: string, credential?: OAuthCreatedCredential) => void;
    onError?: (error: string) => void;
    onCancel?: () => void;
}

export function useCredentialOAuth(options: UseCredentialOAuthOptions = {}) {
    const { onCredentialCreated, onError, onCancel } = options;

    const [availableCredentials, setAvailableCredentials] = useState<Credential[]>(() => getAllCredentialsFromCache());
    const [loading, setLoading] = useState(() => getAllCredentialsFromCache().length === 0);
    const [hiddenSharedCredentials, setHiddenSharedCredentials] = useState(0);
    const [credentialTier, setCredentialTier] = useState('free');

    const loadCredentialsRef = useRef<() => Promise<void>>(async () => {});

    // Load credentials from backend (the manager-only concern).
    const loadCredentials = useCallback(async () => {
        try {
            const cached = getAllCredentialsFromCache();
            if (cached.length > 0) {
                setAvailableCredentials(cached);
                setLoading(false);
            }
            const response = await sendEventAsync({ event_name: 'credential:list', request_id: `cred-list-${Date.now()}` });
            if (response?.credentials) {
                const own = response.credentials;
                const ownIds = new Set(own.map((c: Credential) => c.id));
                const injected = getDisplayOnlyCredentials().filter((c) => c?.id && !ownIds.has(c.id));
                setAvailableCredentials(injected.length ? [...own, ...injected] : own);
                setHiddenSharedCredentials(response.hidden_shared_count || 0);
                setCredentialTier(response.subscription_tier || 'free');
            }
        } catch (err) {
            console.error('[useCredentialOAuth] Error loading credentials:', err);
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => { loadCredentialsRef.current = loadCredentials; }, [loadCredentials]);
    useEffect(() => { loadCredentials(); }, [loadCredentials]);

    // Collaborative live list: merge added / drop removed credential descriptors.
    useEffect(() => {
        return subscribeCredentialCache((change) => {
            setAvailableCredentials((prev) => {
                let next = prev;
                const ensureCopy = () => { if (next === prev) next = [...prev]; };
                if (change.removed?.length) {
                    const drop = new Set(change.removed);
                    if (next.some((c) => drop.has(c.id))) next = next.filter((c) => !drop.has(c.id));
                }
                if (change.added?.length) {
                    for (const d of change.added) {
                        if (!d?.id) continue;
                        const idx = next.findIndex((c) => c.id === d.id);
                        if (idx >= 0) {
                            ensureCopy();
                            next[idx] = {
                                ...next[idx],
                                name: d.name || next[idx].name,
                                metadata: d.metadata ?? next[idx].metadata,
                                owner_name: d.owner_name ?? next[idx].owner_name,
                            };
                        } else {
                            ensureCopy();
                            next.push({
                                id: d.id,
                                name: d.name,
                                credential_type: d.credential_type,
                                metadata: d.metadata,
                                created_at: '',
                                updated_at: '',
                                over_cap: false,
                                owner_name: d.owner_name,
                            } as Credential);
                        }
                    }
                }
                return next;
            });
        });
    }, []);

    // The shared connect engine — reloads the manager's list after a successful mint.
    const oauth = useOAuthConnect({
        onCredentialCreated,
        onError,
        onCancel,
        onAfterOAuthCredential: async (createdCredential) => {
            invalidateCredentialsCache();
            await loadCredentialsRef.current();
            if (createdCredential) {
                upsertCredentialsIntoCache([{ ...createdCredential, owned_by_me: true }]);
            }
        },
    });

    return {
        ...oauth,
        availableCredentials,
        loading,
        loadCredentials,
        hiddenSharedCredentials,
        credentialTier,
    };
}
