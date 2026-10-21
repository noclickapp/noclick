// Read-only view of the cached credential:list rows (memory/IndexedDB cache
// maintained by credentialAutoSelect + the collab descriptor channel), for
// surfaces that need credential HEALTH (revoked/unknown badges) without
// mounting the full credential-manager machinery. Fails safe: an empty cache
// yields an empty list, and health helpers treat that as no-signal.

import { useEffect, useState } from 'react';
import { CREDENTIALS_CHANGED_EVENT } from '~/components/shared/popups/CreateCredentialDialog';
import type { CredentialInfo } from '~/types/socket-events.generated';
import {
    getAllCredentialsFromCache,
    invalidateCredentialsCache,
    prefetchCredentials,
    subscribeCredentialCache,
} from '~/utils/credentialAutoSelect';

function useCacheRows() {
    const state = useState<CredentialInfo[]>(() => getAllCredentialsFromCache());
    const setCreds = state[1];
    useEffect(
        () =>
            subscribeCredentialCache(() =>
                setCreds(getAllCredentialsFromCache())
            ),
        [setCreds]
    );
    return state;
}

export function useCachedCredentialList(): CredentialInfo[] {
    return useCacheRows()[0];
}

/** The same rows, owned: fetched on mount (or each time `active` turns true)
 *  and again whenever a credential is created, renamed or deleted anywhere in
 *  the app while active. `loaded` turns true once the first fetch has answered,
 *  so an empty list can be told from a pending one. */
export function useCredentialList(active = true): { credentials: CredentialInfo[]; loaded: boolean } {
    const [credentials, setCreds] = useCacheRows();
    const [loaded, setLoaded] = useState(false);
    useEffect(() => {
        if (!active) return;
        let live = true;
        // A refetch replaces the cache without notifying subscribers, so read it back here.
        const reload = () =>
            void prefetchCredentials()
                .then(() => live && setCreds(getAllCredentialsFromCache()))
                .catch((err: unknown) => console.warn('[credentials] list failed:', err))
                .finally(() => live && setLoaded(true));
        const onChanged = () => {
            invalidateCredentialsCache();
            reload();
        };
        reload();
        window.addEventListener(CREDENTIALS_CHANGED_EVENT, onChanged);
        return () => {
            live = false;
            window.removeEventListener(CREDENTIALS_CHANGED_EVENT, onChanged);
        };
    }, [setCreds, active]);
    return { credentials, loaded };
}
