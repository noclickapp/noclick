// Verifies that adding a node via click-to-add (the `noclick:add-connected-node`
// event handled in useClickToAddNode) auto-selects a credential, matching the
// drag-drop path. Added alongside the fix that routed both paths through the
// shared autoSelectCredentialsForNewNode helper.
//
// Preconditions (the test skips with a clear reason if unmet): a workflow must
// be open and the credential cache must hold at least one credential whose type
// maps to a credentialed node type.
import { nc } from '~/lib/nc';

export default async function () {
    // Requires an open workflow canvas (the click-add handler lives there).
    if (!window.screenToFlowPosition) {
        return { skipped: 'No workflow open — open a workflow, then re-run.' };
    }

    const { prefetchCredentials, autoSelectCredentialFromCache } = await import(
        '~/utils/credentialAutoSelect'
    );
    await prefetchCredentials();

    // Find a credentialed node type that has a cached credential to auto-select.
    const candidates = [
        'automation-slack', 'automation-gmail', 'automation-google-sheets',
        'automation-google-drive', 'automation-notion', 'automation-airtable',
        'automation-telegram', 'automation-discord', 'automation-github-rest',
        'automation-linear', 'automation-twitter', 'automation-hubspot', 'agent',
    ];
    let nodeType = '';
    let expected: Record<string, string> = {};
    for (const t of candidates) {
        const creds = autoSelectCredentialFromCache(t);
        if (Object.keys(creds).length > 0) {
            nodeType = t;
            expected = creds;
            break;
        }
    }
    if (!nodeType) {
        return { skipped: 'No cached credential for any probed node type — add a credential, then re-run.' };
    }

    const before = new Set(nc.nodes.list().map((n: any) => n.id));
    document.dispatchEvent(
        new CustomEvent('noclick:add-connected-node', { detail: { nodeType } })
    );

    // Wait for the new node of this type to appear, then for the async
    // auto-select to populate its credentialIds.
    let newId = '';
    await nc.wait.until(() => {
        const fresh = nc.nodes.list().find((n: any) => n.type === nodeType && !before.has(n.id));
        if (fresh) newId = fresh.id;
        return !!fresh;
    });
    await nc.wait.until(() => {
        const n = nc.node(newId);
        return !!n && Object.keys(n.credentialIds || {}).length > 0;
    });

    const created = nc.node(newId);
    const credentialIds = created?.credentialIds || {};
    nc.assert.truthy(
        Object.keys(credentialIds).length > 0,
        `Click-added ${nodeType} node should have an auto-selected credential`,
    );
    nc.assert.deepEqual(
        credentialIds,
        expected,
        'Click-add credentialIds should match the cache-selected credential (drag-drop parity)',
    );

    return { nodeType, newNodeId: newId, credentialIds };
}
