// Which keys this INSTANCE holds (self-hosted only): the OpenRouter key the
// builder runs on, the Apify token LinkedIn scraping runs on, the SMTP server
// email leaves through. The credential predicates in NodeCredentials read it
// synchronously — a platform-keyed operation is credential-optional here only
// while its key is configured — and React surfaces subscribe to it, so a key
// saved in one panel flips every badge without a reload.
//
// Loaded once per session from instance_keys:list (the same reply every
// instance_keys:* / instance_smtp:* write returns, so writers feed it back
// through applyInstanceKeysState). Hosted never loads it: there the platform
// key is a given, and the predicates short-circuit before reading this.
import { proxy } from 'valtio';
import { isLocalEdition } from '~/lib/edition';
import { sendEventAsync } from '~/lib/socket-sender';
import { InstanceKeysListRequest } from '~/types/socket-events.generated';

export interface InstanceKeysState {
    keys: { env_var: string; updated_at: string | null }[];
    env_vars: string[];
    supported: string[];
}

export const instanceKeysStore = proxy({
    loaded: false,
    /** Env vars configured either way — stored on the instance or set in its environment. */
    configured: [] as string[],
});

export function applyInstanceKeysState(
    state: InstanceKeysState | null | undefined
): void {
    if (!state) return;
    instanceKeysStore.configured = Array.from(
        new Set([...state.keys.map((k) => k.env_var), ...state.env_vars])
    );
    instanceKeysStore.loaded = true;
}

export function isInstanceKeyConfigured(envVar: string): boolean {
    return instanceKeysStore.configured.includes(envVar);
}

let inflight: Promise<void> | null = null;
let lastAttempt = 0;

/** Fetch the instance's keys once (retrying no more than every 30s if the
 *  socket wasn't ready). Safe to call from render-time predicates. */
export function ensureInstanceKeysLoaded(): void {
    if (!isLocalEdition() || instanceKeysStore.loaded || inflight) return;
    if (Date.now() - lastAttempt < 30_000) return;
    lastAttempt = Date.now();
    inflight = (async () => {
        try {
            const res = (await sendEventAsync(
                InstanceKeysListRequest.create({
                    request_id: crypto.randomUUID(),
                })
            )) as (InstanceKeysState & { error?: string }) | null;
            if (res && !res.error) applyInstanceKeysState(res);
        } catch {
            // Not authenticated yet, or no socket: the next predicate call retries.
        } finally {
            inflight = null;
        }
    })();
}

export async function loadInstanceKeys(): Promise<InstanceKeysState> {
    const res = (await sendEventAsync(
        InstanceKeysListRequest.create({ request_id: crypto.randomUUID() })
    )) as (InstanceKeysState & { error?: string }) | null;
    if (!res || res.error)
        throw new Error(res?.error || 'Could not load the instance keys');
    applyInstanceKeysState(res);
    return res;
}

/** The schema marker a platform-keyed operation carries (nodes/core/platform_billing.py). */
export interface PlatformKeyMarker {
    env: string;
    /** Whether the node's own credential is an alternative to the instance key. */
    byok: boolean;
}

export function platformKeyMarker(
    def: Record<string, unknown> | undefined
): PlatformKeyMarker | null {
    const marker = def?.['x-platform-key'] as
        | Partial<PlatformKeyMarker>
        | undefined;
    return marker && typeof marker.env === 'string'
        ? { env: marker.env, byok: marker.byok !== false }
        : null;
}

/** Whether a credential-optional operation carrying `marker` can run
 *  credential-less HERE: always in the cloud (NoClick's key pays), on a
 *  self-hosted instance only while the operator configured that key. */
export function platformKeyFunds(marker: PlatformKeyMarker | null): boolean {
    if (!marker || !isLocalEdition()) return true;
    ensureInstanceKeysLoaded();
    return isInstanceKeyConfigured(marker.env);
}
