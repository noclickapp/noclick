/**
 * Picks the credential a node starts with when it's added to a canvas (drag-drop, click-to-add, paste, import) or
 * made for a workflow arriving from a public page: the most recent of the viewer's own credentials of the type the
 * node's schema names. Apart from credentialAutoSelect (the credentials cache, on every page) because it reads node
 * schemas, which load with the canvas.
 */

import type { Node } from '@xyflow/react';
import { updateNodeInList } from '~/lib/applyNodeUpdate';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypes';
import {
    authorizeCredentialsForWorkflow,
    cachedCredentialsOfType,
    fetchAndCacheCredentials,
    isDeadCredential,
    isInjectedDisplayCredential,
} from '~/utils/credentialAutoSelect';
import { NODE_SCHEMAS, loadNodeSchemas, nodeSchemasLoaded } from '~/utils/nodeSchemas';

// The node types whose new nodes pick a credential on their own.
const AUTO_SELECT_TYPES: ReadonlySet<string> = new Set([
    'automation-telegram',
    'automation-google-sheets',
    'automation-google-drive',
    'automation-gmail',
    'automation-outlook',
    'automation-excel',
    'automation-word',
    'automation-linear',
    'automation-airtable',
    'automation-stripe',
    'automation-github-rest',
    'automation-apify',
    'automation-apollo',
    'automation-bluesky',
    'automation-canva',
    'automation-discord',
    'automation-google-calendar',
    'automation-google-docs',
    'automation-google-slides',
    'automation-google-forms',
    'automation-google-tasks',
    'automation-google-contacts',
    'automation-instagram',
    'automation-instantly',
    'automation-jira',
    'automation-clickup',
    'automation-linkedin',
    'automation-notion',
    'automation-postgres',
    'automation-reddit',
    'automation-rss',
    'automation-redis',
    'automation-salesforce',
    'automation-shopify',
    'automation-slack',
    'automation-supabase',
    'automation-twitter',
    'automation-youtube',
    'automation-hubspot',
    'automation-mailchimp',
    'automation-firestore',
    'automation-elevenlabs',
    'automation-cloudflare',
    'automation-google-analytics',
    'automation-google-ads',
    'automation-google-business-profile',
    'automation-google-search-console',
    'automation-connecteam',
    'agent',
]);

/**
 * Helper to get credential type from node schema.
 */
function getCredentialTypeForNode(nodeType: string): string | null {
    const schema = AUTO_SELECT_TYPES.has(nodeType) ? NODE_SCHEMAS[nodeType] : undefined;
    if (!schema) return null;

    const credentialProp = schema.properties?.credentials;
    if (!credentialProp) return null;

    let credentialType: string | undefined;

    if (credentialProp.anyOf) {
        const credRef = credentialProp.anyOf.find((opt: any) => opt.$ref);
        if (credRef?.$ref) {
            credentialType = credRef.$ref.split('/').pop();
        }
    } else {
        credentialType = credentialProp.title || credentialProp.$ref?.split('/').pop();
    }

    if (!credentialType) return null;

    return CREDENTIAL_TYPE_MAP[credentialType] || null;
}

/**
 * Synchronously selects credential from memory cache.
 * Returns empty object if cache is not populated or no matching credential found.
 * This is instant and never makes network requests; the node type's schema must have loaded.
 *
 * @param nodeType - The node type (e.g., 'automation-google-sheets')
 * @returns { [credentialType]: credentialId } or empty object
 */
export function autoSelectCredentialFromCache(nodeType: string): Record<string, string> {
    const mappedType = getCredentialTypeForNode(nodeType);
    if (!mappedType) return {};

    const matchingCredentials = cachedCredentialsOfType(mappedType);
    if (!matchingCredentials || matchingCredentials.length === 0) return {};

    // Auto-select the most recent credential the viewer OWNS. Skip ALL injected
    // display-only descriptors (isInjectedDisplayCredential) — upsert unshifts those to index
    // 0, so without this guard a collaborator dragging a same-type node would
    // auto-select the flow owner's credential. Keying on map membership (not
    // owner_name) also covers a LIVE descriptor that hasn't been owner-enriched yet.
    // Prefer healthy credentials over dead ones (revoked / provider session
    // dropped); fall back to a dead one only when nothing healthy exists so the
    // picker still shows it (flagged) rather than nothing.
    const own = matchingCredentials.find((c) => !isInjectedDisplayCredential(c.id) && !isDeadCredential(c))
        ?? matchingCredentials.find((c) => !isInjectedDisplayCredential(c.id));
    if (!own) return {};
    return { [mappedType]: own.id };
}

/**
 * Auto-selects the most recently used credential for a given node type.
 * Fetches from backend and updates both caches.
 * Returns a credentialIds object mapping credential_type to credential_id.
 *
 * @param nodeType - The node type (e.g., 'automation-google-sheets')
 * @returns Promise resolving to { [credentialType]: credentialId } or empty object
 */
export async function autoSelectCredential(nodeType: string): Promise<Record<string, string>> {
    try {
        await loadNodeSchemas([nodeType]);
        const mappedType = getCredentialTypeForNode(nodeType);
        if (!mappedType) return {};

        // Fetch fresh credentials (updates both caches)
        const credentials = await fetchAndCacheCredentials();

        const matchingCredentials = credentials[mappedType];
        if (!matchingCredentials || matchingCredentials.length === 0) return {};

        // Return the most recent healthy credential (dead ones only as last resort)
        const pick = matchingCredentials.find((c) => !isDeadCredential(c)) ?? matchingCredentials[0];
        return { [mappedType]: pick.id };
    } catch (err) {
        console.error('[autoSelectCredential] Error:', err);
        return {};
    }
}

/**
 * Auto-select credentials for a freshly-added node: an instant update from the
 * local cache, then a background refresh that corrects it when the fetched data
 * differs. Each picked credential is authorized for run-as-owner resolution.
 * Shared by every node-add path (drag-drop, click-to-add, paste, import) so they
 * stay in lockstep.
 *
 * - Nodes that already carry credentialIds (import/paste) keep them and are only
 *   (re)authorized — auto-select never overwrites them.
 * - Node types without a credential schema are a no-op (the lookups return {}),
 *   so callers may pass any node.
 *
 * @param workflowId The workflow id when known; null falls back to the open
 *                   workflow (set by FlowCanvas) for hooks not threaded one.
 */
export function autoSelectCredentialsForNewNode(
    node: Node,
    setNodes: (updater: (prev: Node[]) => Node[]) => void,
    workflowId: string | null = null,
): void {
    const existing = node.data?.credentialIds as Record<string, string> | undefined;
    if (existing && Object.keys(existing).length > 0) {
        authorizeCredentialsForWorkflow(workflowId, existing);
        return;
    }

    const nodeType = node.type || '';
    const select = () => {
        // Immediate update from the local cache (synchronous, no network).
        const cached = autoSelectCredentialFromCache(nodeType);
        if (Object.keys(cached).length > 0) {
            setNodes((prev) => updateNodeInList(prev, node.id, { credentialIds: cached }));
            authorizeCredentialsForWorkflow(workflowId, cached);
        }

        // Background fetch — only re-applies when fresh data differs from the cache.
        autoSelectCredential(nodeType).then((fresh) => {
            if (Object.keys(fresh).length > 0 && JSON.stringify(fresh) !== JSON.stringify(cached)) {
                setNodes((prev) => updateNodeInList(prev, node.id, { credentialIds: fresh }));
                authorizeCredentialsForWorkflow(workflowId, fresh);
            }
        });
    };
    // A node of a type new to the canvas picks once its schema has loaded.
    if (nodeSchemasLoaded([nodeType])) select();
    else loadNodeSchemas([nodeType]).then(select, (err) => console.error('[autoSelectCredentialsForNewNode]', err));
}
