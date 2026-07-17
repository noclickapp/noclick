// Health of a node's ATTACHED credentials — the single place that decides
// whether an attached credential id is usable, revoked, or gone. Added after a
// revoked Google Sheets credential sat attached to a provider node looking
// exactly like a live one: the picker listed it normally and the only hint was
// an unexplained amber dot, so tool calls failed with "no credential" while
// the user believed one was connected.

export type CredentialHealth = 'ok' | 'revoked' | 'unknown';

export interface CredentialHealthRow {
    id: string;
    revoked_at?: string | null;
}

/** Health of one attached credential id against the loaded credential list.
 *  'unknown' = not in the list (deleted, or inaccessible to this viewer —
 *  collaborators see owner credentials via injected display rows, so a
 *  resolvable owner credential still reports 'ok'). */
export function credentialHealth(
    credentialId: string | undefined | null,
    credentials: readonly CredentialHealthRow[]
): CredentialHealth {
    if (!credentialId) return 'ok'; // nothing attached = a different problem
    const row = credentials.find((c) => c?.id === credentialId);
    if (!row) return 'unknown';
    return row.revoked_at ? 'revoked' : 'ok';
}

/** Worst health across a node's credentialIds map ('revoked' beats 'unknown'
 *  beats 'ok'), so a single indicator can summarize multi-slot nodes.
 *  Fail-safe: an EMPTY credential list means "list not loaded yet", not
 *  "everything is broken" — report 'ok' rather than false-alarm. */
export function attachedCredentialsHealth(
    credentialIds: Record<string, string> | undefined | null,
    credentials: readonly CredentialHealthRow[]
): CredentialHealth {
    if (credentials.length === 0) return 'ok';
    let worst: CredentialHealth = 'ok';
    for (const id of Object.values(credentialIds || {})) {
        const h = credentialHealth(id, credentials);
        if (h === 'revoked') return 'revoked';
        if (h === 'unknown') worst = 'unknown';
    }
    return worst;
}

/** Human copy for a non-ok health state. */
export function credentialHealthMessage(
    health: CredentialHealth
): string | null {
    if (health === 'revoked') {
        return 'This credential was disconnected or revoked and can no longer be used — reconnect the account or pick another credential.';
    }
    if (health === 'unknown') {
        return 'The attached credential no longer exists or is not accessible — reconnect the account or pick another credential.';
    }
    return null;
}
