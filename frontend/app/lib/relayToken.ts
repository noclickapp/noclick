// The token a user-events relay viewer sends as its first frame to prove it is
// the user. Short-lived and checked only when a socket connects, so a reconnect
// after it lapses mints another. It travels in a frame, never in the socket URL,
// so it can't land in request logs.

import { sendEventAsync } from '~/lib/socket-sender';
import {
    RelayUserTokenRequest,
    type RelayUserTokenResponse,
} from '~/types/socket-events.generated';

// Re-mint this long before expiry, so a token never lapses on its way.
const REFRESH_MARGIN_S = 60;
// Give up on one mint well inside the relay's 30s auth deadline, so the
// caller has time to try again on the same connection.
const MINT_TIMEOUT_MS = 8_000;

let cached: { userId: string; token: string; expiresAt: number } | null = null;
let inFlight: { userId: string; promise: Promise<string | null> } | null = null;

/**
 * A live token for `userId`'s relay room. Resolves null when the app's socket
 * acts as another user (a mimic starting or ending: no token it can mint opens
 * this room until the room follows); rejects when
 * none could be minted (a timeout, a refusal, a rate limit), so the caller
 * can try again.
 */
export function getUserRelayToken(userId: string): Promise<string | null> {
    if (
        cached?.userId === userId &&
        Date.now() / 1000 < cached.expiresAt - REFRESH_MARGIN_S
    ) {
        return Promise.resolve(cached.token);
    }
    if (inFlight?.userId === userId) return inFlight.promise;
    const promise = mint(userId).finally(() => {
        if (inFlight?.promise === promise) inFlight = null;
    });
    inFlight = { userId, promise };
    return promise;
}

/** Drop the cached token (the relay refused it), so the next connect mints anew. */
export function forgetUserRelayToken(): void {
    cached = null;
}

async function mint(userId: string): Promise<string | null> {
    const reply = (await sendEventAsync(
        RelayUserTokenRequest.create({ request_id: crypto.randomUUID() }),
        undefined,
        MINT_TIMEOUT_MS
    )) as RelayUserTokenResponse & { error?: string };
    if (!(reply?.success && reply.token && reply.expires_at && reply.user_id)) {
        throw new Error(
            `relay token not minted: ${reply?.message ?? reply?.error ?? 'no reply'}`
        );
    }
    cached = {
        userId: reply.user_id,
        token: reply.token,
        expiresAt: reply.expires_at,
    };
    if (reply.user_id === userId) return reply.token;
    // The app's socket acts as another user than this room's (a mimic
    // starting or ending): this room would refuse the token.
    console.warn(
        '[EventRelay] relay token is for another user; not authenticating this room'
    );
    return null;
}
