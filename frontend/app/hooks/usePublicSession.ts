// Client-side visitor session for cookie-free marketing pages: fetches
// {isAuthenticated, userID, csrfToken} once per page load from the uncached
// /api/public-session endpoint (which also sets the csrf cookie) and shares the
// result across all consumers via a module-level cache. Replaces the per-route
// createPublicLoaderData pattern, whose Set-Cookie made every marketing document
// uncacheable at the edge. Deliberately dependency-free (no valtio/socket) so
// marketing bundles stay slim; SSR and first paint render the anonymous state.
import { useEffect, useState } from 'react';
import { initTelemetry } from '~/lib/telemetry';

export interface PublicSession {
    isAuthenticated: boolean;
    userID: string | null;
    /** undefined until the fetch lands — consumers treat it as "not yet available". */
    csrfToken: string | undefined;
}

const ANONYMOUS: PublicSession = { isAuthenticated: false, userID: null, csrfToken: undefined };

let cached: PublicSession | null = null;
let inflight: Promise<PublicSession> | null = null;

async function fetchPublicSession(): Promise<PublicSession> {
    if (cached) return cached;
    inflight ??= fetch('/api/public-session', { credentials: 'same-origin' })
        .then(async (res) => {
            if (!res.ok) throw new Error(`public-session ${res.status}`);
            const data = (await res.json()) as PublicSession;
            cached = data;
            // Cached marketing documents carry no identity — re-stamp telemetry
            // context for logged-in visitors (idempotent, see root.tsx).
            if (data.userID) initTelemetry({ userId: data.userID });
            return data;
        })
        .catch((err) => {
            inflight = null; // allow a retry on the next mount
            throw err;
        });
    return inflight;
}

export function usePublicSession(): PublicSession & { ready: boolean } {
    const [session, setSession] = useState<PublicSession | null>(cached);
    useEffect(() => {
        let cancelled = false;
        fetchPublicSession().then(
            (s) => {
                if (!cancelled) setSession(s);
            },
            () => {
                // Network failure: stay anonymous — the UI's SSR default.
            },
        );
        return () => {
            cancelled = true;
        };
    }, []);
    return { ...(session ?? ANONYMOUS), ready: session !== null };
}
