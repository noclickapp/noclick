// Read-only view of the cached credential:list rows (memory/IndexedDB cache
// maintained by credentialAutoSelect + the collab descriptor channel), for
// surfaces that need credential HEALTH (revoked/unknown badges) without
// mounting the full credential-manager machinery. Fails safe: an empty cache
// yields an empty list, and health helpers treat that as no-signal.

import { useEffect, useState } from 'react';
import {
    getAllCredentialsFromCache,
    subscribeCredentialCache,
} from '~/utils/credentialAutoSelect';
import type { CredentialHealthRow } from '~/lib/credentialHealth';

export function useCachedCredentialList(): CredentialHealthRow[] {
    const [creds, setCreds] = useState<CredentialHealthRow[]>(() =>
        getAllCredentialsFromCache()
    );
    useEffect(
        () =>
            subscribeCredentialCache(() =>
                setCreds(getAllCredentialsFromCache())
            ),
        []
    );
    return creds;
}
