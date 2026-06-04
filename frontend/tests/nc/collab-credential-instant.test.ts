// Verifies the load-bearing invariants behind live collaborative credential
// display — a credential a collaborator ADDS resolves to its name instantly, and
// one they DELETE disappears, both with no backend refetch:
//  1. ADD — upsertCredentialsIntoCache merges a descriptor into the shared cache
//     and notifies subscribers ({added}). useCredentialOAuth merges into
//     availableCredentials → an open dropdown resolves the name next render.
//  2. REMOVE — removeCredentialsFromCache drops it from the cache and notifies
//     ({removed}) → an open dropdown drops it next render.
//  3. NO-PERSIST — the `_credentialMeta` transport key is stripped by
//     buildSaveConfig (credentialIds, the real reference, persists).
// The full two-session live DOM update is the manual E2E gate (per CLAUDE.md).
import {
    upsertCredentialsIntoCache,
    removeCredentialsFromCache,
    subscribeCredentialCache,
    getAllCredentialsFromCache,
    invalidateCredentialsCache,
} from '~/utils/credentialAutoSelect';
import { buildSaveConfig } from '~/lib/applyNodeUpdate';

export default async function () {
    const out: Record<string, unknown> = {};
    const fakeId = 'collab-cred-test-0001';
    const fakeType = 'telegram_bot_token';

    const changes: Array<{ added?: Array<{ id: string }>; removed?: string[] }> = [];
    const unsub = subscribeCredentialCache((c) => changes.push(c as { added?: Array<{ id: string }>; removed?: string[] }));

    // 1. ADD.
    upsertCredentialsIntoCache([{ id: fakeId, name: 'Collab Cred', credential_type: fakeType }]);
    out.addNotified = changes.some((c) => (c.added || []).some((d) => d.id === fakeId));
    const cachedAfterAdd = getAllCredentialsFromCache().find((c: { id: string }) => c.id === fakeId);
    out.inCacheAfterAdd = !!cachedAfterAdd;
    out.cachedName = cachedAfterAdd?.name;
    out.overCapForcedFalse = cachedAfterAdd?.over_cap === false;

    // 2. REMOVE.
    removeCredentialsFromCache([fakeId]);
    out.removeNotified = changes.some((c) => (c.removed || []).includes(fakeId));
    out.goneFromCacheAfterRemove = !getAllCredentialsFromCache().some((c: { id: string }) => c.id === fakeId);
    unsub();

    // 3. NO-PERSIST: _credentialMeta / _credentialRemoved are stripped on save.
    const node = {
        id: 'n1',
        type: 'automation-telegram',
        position: { x: 0, y: 0 },
        data: {
            config: { operation: 'send' },
            credentialIds: { telegram_bot_token: fakeId },
            _credentialMeta: { [fakeId]: { id: fakeId, name: 'Collab Cred', credential_type: fakeType } },
            _credentialRemoved: [fakeId],
        },
    } as unknown as Parameters<typeof buildSaveConfig>[0];
    const savedStr = JSON.stringify(buildSaveConfig(node));
    out.savedStripsTransportHints = !savedStr.includes('_credentialMeta') && !savedStr.includes('_credentialRemoved');
    out.savedKeepsCredentialId = savedStr.includes(fakeId); // persists via credentialIds

    invalidateCredentialsCache();
    return out;
}
