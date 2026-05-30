/**
 * useServiceCredentialOptions returns the list of services that accept
 * credentials (derived from node schemas). getServiceCredentialOptions() returns
 * [] on its first call while it lazily imports the node registry, so this hook
 * polls until the list is populated — letting standalone surfaces (the
 * create-credential dialog) render the full service list without depending on a
 * node being mounted first.
 */

import { useEffect, useState } from 'react';
import { getServiceCredentialOptions, type ServiceCredentialOption } from '~/utils/credentialTypes';

export function useServiceCredentialOptions(): ServiceCredentialOption[] {
    const [options, setOptions] = useState<ServiceCredentialOption[]>(() => getServiceCredentialOptions());

    useEffect(() => {
        if (options.length > 0) return;

        let cancelled = false;
        let attempts = 0;
        const poll = () => {
            if (cancelled) return;
            const next = getServiceCredentialOptions();
            if (next.length > 0) {
                setOptions(next);
                return;
            }
            // Registry import hasn't resolved yet — retry briefly (cap at ~2.5s).
            if (attempts++ < 50) setTimeout(poll, 50);
        };
        poll();

        return () => { cancelled = true; };
    }, [options.length]);

    return options;
}
