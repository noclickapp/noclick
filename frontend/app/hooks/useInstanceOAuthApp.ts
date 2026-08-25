// Whether this instance has an OAuth app registered for a provider.
//
// Self-hosted installs must supply their own OAuth app per provider (see
// backend/utils/instance_oauth.py). Knowing that BEFORE the user clicks Connect
// is what lets the credential panel offer to set one up, instead of opening a
// popup that lands on an explainer page — the point at which most people give up.
//
// The check can't happen inside the click handler: opening the popup after an
// await loses the user-gesture context and browsers block it. So this resolves
// on render and the UI branches on the result.
//
// Hosted returns configured=true without a request. Its OAuth apps come from the
// deployment environment, so there is nothing to ask and nothing to offer.

import { useCallback, useEffect, useState } from 'react';
import { isLocalEdition } from '~/lib/edition';
import { apiBaseUrl } from '~/lib/hostedDefaults';

export function useInstanceOAuthApp(provider: string | undefined) {
    const selfHosted = isLocalEdition();
    const [configured, setConfigured] = useState(!selfHosted);
    const [loading, setLoading] = useState(selfHosted && !!provider);

    const check = useCallback(async () => {
        if (!selfHosted || !provider) {
            setConfigured(true);
            setLoading(false);
            return;
        }
        setLoading(true);
        try {
            const res = await fetch(`${apiBaseUrl()}/api/public/oauth-app/${encodeURIComponent(provider)}`);
            setConfigured(res.ok); // 404 is the ordinary "none configured" answer
        } catch {
            // Unreachable backend is not the same as unconfigured. Assume it is
            // there and let the connect attempt produce the real error, rather
            // than asking for OAuth credentials the operator may already have set.
            setConfigured(true);
        } finally {
            setLoading(false);
        }
    }, [provider, selfHosted]);

    useEffect(() => {
        void check();
    }, [check]);

    return { configured, loading, refresh: check };
}
