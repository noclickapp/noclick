// Regression test for run-as-owner credential VISIBILITY on the collaborator (B)
// side. Such a credential is owned by the flow owner, referenced by a node, and can
// NEVER be in B's own credential:list — so it lives only as an injected display-only
// descriptor. It must stay visible across: (1) the credentials-view collapse/reopen,
// (2) a wholesale cache replace (credential:list refetch / invalidate), and
// (3) LEAVING the workflow and coming BACK. It must NOT bleed into a different
// workflow. The fix holds descriptors in a durable `displayOnlyById` map TAGGED with
// the workflow they belong to, filtered on read by the active workflow (set by
// FlowCanvas). Tagging (not clearing-on-leave) is what makes leave/return restore
// instantly without depending on a display_info re-fetch. Live-synced descriptors
// carry NO owner_name yet (built from the SENDER's own-cred view), so durability must
// not require owner_name. Pins these invariants without a two-session E2E.
import {
    upsertCredentialsIntoCache,
    removeCredentialsFromCache,
    getDisplayOnlyCredentials,
    invalidateCredentialsCache,
    setActiveCredentialWorkflow,
    autoSelectCredentialFromCache,
} from '~/utils/credentialAutoSelect';

type Cred = { id: string; name?: string; credential_type?: string; owner_name?: string | null };

export default async function () {
    const out: Record<string, unknown> = {};
    const t = 'telegram_bot_token';
    const WF_X = 'reopen-wf-x';
    const WF_Y = 'reopen-wf-y';
    const ownerCred = 'reopen-owner-1';         // display_info: owned by another (owner_name set, owned_by_me false)
    const liveCred = 'reopen-live-1';           // live _credentialMeta: name only, NO owner_name yet (the repro)
    const ownCred = 'reopen-own-1';             // the viewer's own (comes back from credential:list)
    const ownedByMeCred = 'reopen-ownedbyme-1'; // display_info confirmed owned_by_me=true

    // Simulate loadCredentials' merge for a given own credential:list.
    const mergeAvailable = (ownList: Cred[]) => {
        const ownIds = new Set(ownList.map((c) => c.id));
        const injected = getDisplayOnlyCredentials().filter((c: Cred) => c?.id && !ownIds.has(c.id));
        return injected.length ? [...ownList, ...injected] : ownList;
    };
    const inDisplay = (id: string) => getDisplayOnlyCredentials().some((c: Cred) => c.id === id);

    // B opens workflow X (FlowCanvas sets the active workflow).
    setActiveCredentialWorkflow(WF_X);
    upsertCredentialsIntoCache([{ id: ownerCred, name: 'Prod TG', credential_type: t, owner_name: 'Alice', owned_by_me: false }]);
    upsertCredentialsIntoCache([{ id: liveCred, name: 'New TG', credential_type: t }]); // live: no owner info yet
    upsertCredentialsIntoCache([{ id: ownedByMeCred, name: 'My Own TG', credential_type: t, owned_by_me: true }]);

    out.ownerTracked = inDisplay(ownerCred);
    out.liveTracked = inDisplay(liveCred);
    out.ownedByMeExcluded = !inDisplay(ownedByMeCred);

    // Wipe memoryCache (fetchAndCacheCredentials replace / invalidate) — descriptors persist.
    invalidateCredentialsCache();
    out.ownerSurvivesWipe = inDisplay(ownerCred);
    out.liveSurvivesWipe = inDisplay(liveCred); // <- the original repro

    // loadCredentials merge: B's own list excludes the owner + live creds.
    const merged = mergeAvailable([{ id: ownCred, name: 'My TG', credential_type: t }]);
    out.mergeKeepsOwner = merged.some((c: Cred) => c.id === ownerCred);
    out.mergeKeepsLive = merged.some((c: Cred) => c.id === liveCred); // <- the original repro fix
    out.mergeKeepsOwn = merged.some((c: Cred) => c.id === ownCred);
    out.ownerTagPreserved = merged.find((c: Cred) => c.id === ownerCred)?.owner_name === 'Alice';

    // LEAVE workflow X -> nothing scoped to the (null) active workflow is visible...
    setActiveCredentialWorkflow(null);
    out.hiddenWhileAway = getDisplayOnlyCredentials().length === 0;
    // ...and RETURN to X restores them INSTANTLY (descriptors were tagged, not cleared).
    setActiveCredentialWorkflow(WF_X);
    out.leaveReturnRestoresOwner = inDisplay(ownerCred);
    out.leaveReturnRestoresLive = inDisplay(liveCred); // <- the NEW repro

    // NO CROSS-WORKFLOW BLEED: in another workflow, X's descriptors are not visible.
    setActiveCredentialWorkflow(WF_Y);
    out.noBleedIntoOtherWorkflow = !inDisplay(ownerCred) && !inDisplay(liveCred);
    setActiveCredentialWorkflow(WF_X);

    // Un-share (owner removes the cred from the node) drops it everywhere.
    removeCredentialsFromCache([ownerCred]);
    out.unshareDropsOwner = !inDisplay(ownerCred);

    // AUTO-SELECT must never pick another user's run-as-owner cred onto a new node.
    removeCredentialsFromCache([ownerCred, liveCred, ownCred, ownedByMeCred]);
    invalidateCredentialsCache();
    upsertCredentialsIntoCache([{ id: ownerCred, name: 'Prod TG', credential_type: t, owner_name: 'Alice', owned_by_me: false }]);
    out.autoSelectSkipsOwnerOnly = autoSelectCredentialFromCache('automation-telegram')[t] === undefined;
    upsertCredentialsIntoCache([{ id: ownCred, name: 'My TG', credential_type: t, owned_by_me: true }]);
    out.autoSelectPicksOwn = autoSelectCredentialFromCache('automation-telegram')[t] === ownCred;

    // Cleanup so no test ids linger in the module singletons.
    removeCredentialsFromCache([ownerCred, liveCred, ownCred, ownedByMeCred]);
    invalidateCredentialsCache();
    setActiveCredentialWorkflow(null);

    out.allPassed = Object.entries(out).every(([k, v]) => k === 'allPassed' || v === true);
    return out;
}
