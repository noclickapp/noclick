/**
 * Utility for auto-selecting the most appropriate credential for a node type.
 * Uses a two-tier cache (memory + IndexedDB) for instant selection with background refresh.
 * Memory cache provides synchronous lookups; IndexedDB persists across page refreshes.
 * Used when adding nodes via drag-drop or paste operations.
 */

import type { Node } from '@xyflow/react';
import { sendEventAsync } from '~/lib/socket-sender';
import { CredentialAuthorizeForWorkflowRequest } from '~/types/socket-events.generated';
import { valtioCache } from '~/lib/indexeddb';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypes';
import { updateNodeInList } from '~/lib/applyNodeUpdate';

// Import node schemas directly
import telegramSchema from '~/schemas/nodes/telegram.json';
import agentSchema from '~/schemas/nodes/agent.json';
import googleSheetsSchema from '~/schemas/nodes/google-sheets.json';
import googleDriveSchema from '~/schemas/nodes/google-drive.json';
import gmailSchema from '~/schemas/nodes/gmail.json';
import outlookSchema from '~/schemas/nodes/outlook.json';
import excelSchema from '~/schemas/nodes/excel.json';
import wordSchema from '~/schemas/nodes/word.json';
import linearSchema from '~/schemas/nodes/linear.json';
import airtableSchema from '~/schemas/nodes/airtable.json';
import stripeSchema from '~/schemas/nodes/stripe.json';
import clickupSchema from '~/schemas/nodes/clickup.json';
import apolloSchema from '~/schemas/nodes/apollo.json';
import blueskySchema from '~/schemas/nodes/bluesky.json';
import canvaSchema from '~/schemas/nodes/canva.json';
import discordSchema from '~/schemas/nodes/discord.json';
import githubRestSchema from '~/schemas/nodes/github-rest.json';
import apifySchema from '~/schemas/nodes/apify.json';
import googleCalendarSchema from '~/schemas/nodes/google-calendar.json';
import googleDocsSchema from '~/schemas/nodes/google-docs.json';
import googleSlidesSchema from '~/schemas/nodes/google-slides.json';
import googleFormsSchema from '~/schemas/nodes/google-forms.json';
import googleTasksSchema from '~/schemas/nodes/google-tasks.json';
import googleContactsSchema from '~/schemas/nodes/google-contacts.json';
import instagramSchema from '~/schemas/nodes/instagram.json';
import instantlySchema from '~/schemas/nodes/instantly.json';
import jiraSchema from '~/schemas/nodes/jira.json';
import linkedinSchema from '~/schemas/nodes/linkedin.json';
import notionSchema from '~/schemas/nodes/notion.json';
import postgresSchema from '~/schemas/nodes/postgres.json';
import redditSchema from '~/schemas/nodes/reddit.json';
import rssSchema from '~/schemas/nodes/rss.json';
import salesforceSchema from '~/schemas/nodes/salesforce.json';
import shopifySchema from '~/schemas/nodes/shopify.json';
import slackSchema from '~/schemas/nodes/slack.json';
import supabaseSchema from '~/schemas/nodes/supabase.json';
import twitterSchema from '~/schemas/nodes/twitter.json';
import youtubeSchema from '~/schemas/nodes/youtube.json';
import hubspotSchema from '~/schemas/nodes/hubspot.json';
import mailchimpSchema from '~/schemas/nodes/mailchimp.json';
import firestoreSchema from '~/schemas/nodes/firestore.json';
import redisSchema from '~/schemas/nodes/redis.json';
import elevenlabsSchema from '~/schemas/nodes/elevenlabs.json';
import cloudflareSchema from '~/schemas/nodes/cloudflare.json';
import googleAnalyticsSchema from '~/schemas/nodes/google-analytics.json';
import googleAdsSchema from '~/schemas/nodes/google-ads.json';
import googleBusinessProfileSchema from '~/schemas/nodes/google-business-profile.json';
import googleSearchConsoleSchema from '~/schemas/nodes/google-search-console.json';

const NODE_SCHEMAS: Record<string, any> = {
    'automation-telegram': telegramSchema,
    'automation-google-sheets': googleSheetsSchema,
    'automation-google-drive': googleDriveSchema,
    'automation-gmail': gmailSchema,
    'automation-outlook': outlookSchema,
    'automation-excel': excelSchema,
    'automation-word': wordSchema,
    'automation-linear': linearSchema,
    'automation-airtable': airtableSchema,
    'automation-stripe': stripeSchema,
    'automation-github-rest': githubRestSchema,
    'automation-apify': apifySchema,
    'automation-apollo': apolloSchema,
    'automation-bluesky': blueskySchema,
    'automation-canva': canvaSchema,
    'automation-discord': discordSchema,
    'automation-google-calendar': googleCalendarSchema,
    'automation-google-docs': googleDocsSchema,
    'automation-google-slides': googleSlidesSchema,
    'automation-google-forms': googleFormsSchema,
    'automation-google-tasks': googleTasksSchema,
    'automation-google-contacts': googleContactsSchema,
    'automation-instagram': instagramSchema,
    'automation-instantly': instantlySchema,
    'automation-jira': jiraSchema,
    'automation-clickup': clickupSchema,
    'automation-linkedin': linkedinSchema,
    'automation-notion': notionSchema,
    'automation-postgres': postgresSchema,
    'automation-reddit': redditSchema,
    'automation-rss': rssSchema,
    'automation-redis': redisSchema,
    'automation-salesforce': salesforceSchema,
    'automation-shopify': shopifySchema,
    'automation-slack': slackSchema,
    'automation-supabase': supabaseSchema,
    'automation-twitter': twitterSchema,
    'automation-youtube': youtubeSchema,
    'automation-hubspot': hubspotSchema,
    'automation-mailchimp': mailchimpSchema,
    'automation-firestore': firestoreSchema,
    'automation-elevenlabs': elevenlabsSchema,
    'automation-cloudflare': cloudflareSchema,
    'automation-google-analytics': googleAnalyticsSchema,
    'automation-google-ads': googleAdsSchema,
    'automation-google-business-profile': googleBusinessProfileSchema,
    'automation-google-search-console': googleSearchConsoleSchema,
    'agent': agentSchema,
};

// IndexedDB key for persisted credentials cache
const CREDENTIALS_CACHE_KEY = 'credentials-cache';

// ============= Two-Tier Credentials Cache =============
// Memory cache: credential_type -> sorted credentials array (most recent first)
// Provides synchronous lookups for instant UI updates
let memoryCache: Record<string, any[]> | null = null;
let fetchPromise: Promise<Record<string, any[]>> | null = null;
let idbLoadPromise: Promise<void> | null = null;

// Run-as-owner display-only descriptors: credentials owned by ANOTHER user (the
// flow owner) but referenced by a node in a shared workflow. They can NEVER appear
// in the viewer's own credential:list, and memoryCache is replaced wholesale by
// fetchAndCacheCredentials, so they're held separately here (id -> entry) and
// unioned in by getAllCredentialsFromCache. This is what lets the name + owner tag
// survive a credential:list refetch and a credentials-view remount.
//
// Each entry is TAGGED with the workflow it was injected for (`_wf`), and reads are
// filtered by `activeCredentialWorkflowId` (set by FlowCanvas). That scopes them to
// the open workflow WITHOUT clearing on leave — so returning to a workflow restores
// its descriptors instantly (no dependency on a display_info re-fetch), while
// another workflow never sees them (no cross-workflow bleed).
const displayOnlyById: Map<string, any> = new Map();
let activeCredentialWorkflowId: string | null = null;

/** Set the workflow whose run-as-owner descriptors should be visible. FlowCanvas
 *  calls this on mount / workflow change (and null when no workflow is open). */
export function setActiveCredentialWorkflow(workflowId: string | null): void {
    activeCredentialWorkflowId = workflowId;
}

/**
 * Loads credentials from IndexedDB into memory cache.
 * Called on module initialization and can be awaited for guaranteed cache population.
 */
async function loadFromIndexedDB(): Promise<void> {
    if (idbLoadPromise) return idbLoadPromise;

    idbLoadPromise = (async () => {
        try {
            const cached = await valtioCache.get<Record<string, any[]>>(CREDENTIALS_CACHE_KEY);
            if (cached && !memoryCache) {
                // Only populate if memory cache is still empty (backend fetch might have won the race)
                memoryCache = cached;
            }
        } catch (err) {
            console.error('[credentialAutoSelect] Failed to load from IndexedDB:', err);
        }
    })();

    return idbLoadPromise;
}

// Kick off IndexedDB load on module initialization (non-blocking)
if (typeof window !== 'undefined') {
    loadFromIndexedDB();
}

/**
 * Fetches all credentials from backend and updates both caches.
 * Uses a single in-flight promise to prevent duplicate concurrent requests.
 */
async function fetchAndCacheCredentials(): Promise<Record<string, any[]>> {
    // Return existing promise if fetch is already in progress
    if (fetchPromise) {
        return fetchPromise;
    }

    fetchPromise = (async () => {
        try {
            const response = await sendEventAsync({
                event_name: 'credential:list',
                request_id: `credential-cache-${Date.now()}`,
            });

            if (!response?.credentials || response.credentials.length === 0) {
                memoryCache = {};
                await valtioCache.set(CREDENTIALS_CACHE_KEY, {});
                return {};
            }

            // Group credentials by type
            const grouped: Record<string, any[]> = {};
            for (const cred of response.credentials) {
                if (!grouped[cred.credential_type]) {
                    grouped[cred.credential_type] = [];
                }
                grouped[cred.credential_type].push(cred);
            }

            // Sort each group by updated_at (most recent first)
            for (const type in grouped) {
                grouped[type].sort((a, b) =>
                    new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
                );
            }

            // Update both caches
            memoryCache = grouped;
            await valtioCache.set(CREDENTIALS_CACHE_KEY, grouped);

            return grouped;
        } finally {
            fetchPromise = null;
        }
    })();

    return fetchPromise;
}

/**
 * Helper to get credential type from node schema.
 */
function getCredentialTypeForNode(nodeType: string): string | null {
    const schema = NODE_SCHEMAS[nodeType];
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
 * This is instant and never makes network requests.
 *
 * @param nodeType - The node type (e.g., 'automation-google-sheets')
 * @returns { [credentialType]: credentialId } or empty object
 */
export function autoSelectCredentialFromCache(nodeType: string): Record<string, string> {
    const mappedType = getCredentialTypeForNode(nodeType);
    if (!mappedType) return {};

    if (!memoryCache) return {};

    const matchingCredentials = memoryCache[mappedType];
    if (!matchingCredentials || matchingCredentials.length === 0) return {};

    // Auto-select the most recent credential the viewer OWNS. Skip ALL injected
    // display-only descriptors (in displayOnlyById) — upsert unshifts those to index
    // 0, so without this guard a collaborator dragging a same-type node would
    // auto-select the flow owner's credential. Keying on map membership (not
    // owner_name) also covers a LIVE descriptor that hasn't been owner-enriched yet.
    // Prefer healthy credentials over dead ones (revoked / provider session
    // dropped); fall back to a dead one only when nothing healthy exists so the
    // picker still shows it (flagged) rather than nothing.
    const own = matchingCredentials.find((c) => !displayOnlyById.has(c.id) && !isDeadCredential(c))
        ?? matchingCredentials.find((c) => !displayOnlyById.has(c.id));
    if (!own) return {};
    return { [mappedType]: own.id };
}

/** Revoked, or a connection-backed credential (whatsapp_qr) whose provider
 *  session dropped — either way it cannot work as attached right now. */
export function isDeadCredential(cred: { revoked_at?: string | null; connection_status?: string | null }): boolean {
    return !!cred.revoked_at || (!!cred.connection_status && cred.connection_status !== 'connected');
}

/**
 * Pre-fetches credentials to populate both caches.
 * Call this early (e.g., on workflow canvas load) for best UX.
 */
export async function prefetchCredentials(): Promise<void> {
    await fetchAndCacheCredentials();
}

/**
 * Invalidates both caches, forcing next fetch to get fresh data.
 * Call this when credentials are added/removed/updated.
 */
export function invalidateCredentialsCache(): void {
    memoryCache = null;
    valtioCache.delete(CREDENTIALS_CACHE_KEY);
}

/**
 * Returns all cached credentials as a flat array.
 * Used by NodeCredentials component for instant dropdown display.
 * Returns empty array if cache is not populated.
 */
export function getAllCredentialsFromCache(): any[] {
    const own = memoryCache ? Object.values(memoryCache).flat() : [];
    const injected = getDisplayOnlyCredentials();
    if (injected.length === 0) return own;
    // Union the run-as-owner display-only descriptors (deduped against own creds),
    // so they survive a wholesale memoryCache replace and a credentials-view remount.
    const ownIds = new Set(own.map((c) => c?.id));
    const extra = injected.filter((c) => !ownIds.has(c.id));
    return extra.length ? [...own, ...extra] : own;
}

/**
 * The connected account email for a cached credential (OAuth credentials store
 * it in metadata.email), or undefined if not cached / not an email credential.
 * Synchronous read off the same cache the dropdowns use.
 */
export function getCredentialEmail(credentialId: string): string | undefined {
    if (!credentialId) return undefined;
    const cred = getAllCredentialsFromCache().find((c) => c?.id === credentialId);
    const email = cred?.metadata?.email;
    return typeof email === 'string' && email.includes('@') ? email : undefined;
}

/**
 * Returns the injected run-as-owner display-only descriptors for the ACTIVE workflow
 * (credentials owned by the flow owner, referenced by a node). These can never be in
 * the viewer's own credential:list, so loadCredentials re-merges them after the
 * authoritative refetch. Scoped to activeCredentialWorkflowId so one workflow's owner
 * creds never leak into another's pickers; descriptors persist across leave/return,
 * so returning to a workflow restores them without waiting on a display_info fetch.
 */
export function getDisplayOnlyCredentials(): any[] {
    if (!activeCredentialWorkflowId) return [];
    return [...displayOnlyById.values()].filter((c) => c._wf === activeCredentialWorkflowId);
}

// ============= Collaborative optimistic display =============
// Display-only credential descriptor carried over the collaborative worker so a
// credential a collaborator just set on a node resolves to its NAME instantly,
// before the backend share + refetch lands. NEVER carries secret material.
export interface CredentialDisplayMeta {
    id: string;
    name: string;
    credential_type: string;
    metadata?: Record<string, unknown>;
    // Display-only owner tag: who really owns the credential (set only when it's
    // NOT the current user's own). The credential is resolved as the owner at
    // execution; this is purely so collaborators can see whose credential it is.
    owner_name?: string | null;
    owned_by_me?: boolean;
}

// Optimistic cache change: credentials added (descriptors) and/or removed (ids).
export interface CredCacheChange {
    added?: CredentialDisplayMeta[];
    removed?: string[];
}
type CredCacheSubscriber = (change: CredCacheChange) => void;
const cacheSubscribers = new Set<CredCacheSubscriber>();

/** Subscribe to optimistic credential add/remove changes (returns an unsubscribe fn). */
export function subscribeCredentialCache(cb: CredCacheSubscriber): () => void {
    cacheSubscribers.add(cb);
    return () => {
        cacheSubscribers.delete(cb);
    };
}

/**
 * Optimistically merge display-only credential descriptors into the in-memory
 * cache and notify subscribers, so an open NodeCredentials resolves the name on
 * the next render with NO backend round-trip. In-memory only (not IndexedDB) —
 * the next authoritative loadCredentials() replaces these with the real records.
 */
export function upsertCredentialsIntoCache(creds: CredentialDisplayMeta[]): void {
    if (!creds || creds.length === 0) return;
    if (!memoryCache) memoryCache = {};
    for (const cred of creds) {
        if (!cred?.id || !cred?.credential_type) continue;
        const bucket = memoryCache[cred.credential_type] || (memoryCache[cred.credential_type] = []);
        const existing = bucket.find((c) => c.id === cred.id);
        let entry: any;
        if (existing) {
            // Enrich an existing entry (e.g. owner tag from display_info arriving
            // after the instant _credentialMeta name).
            if (cred.name) existing.name = cred.name;
            if (cred.metadata !== undefined) existing.metadata = cred.metadata;
            if (cred.owner_name !== undefined) existing.owner_name = cred.owner_name;
            if (cred.owned_by_me !== undefined) existing.owned_by_me = cred.owned_by_me;
            entry = existing;
        } else {
            entry = { ...cred, over_cap: false };
            bucket.unshift(entry);
        }
        // Everything upserted is an injected display-only descriptor (from the live
        // _credentialMeta sync or credential:display_info), so keep it in the durable
        // map — it must survive a wholesale memoryCache replace and a view remount.
        // EXCEPTION: a credential confirmed to be the viewer's OWN (owned_by_me) needs
        // no preservation — it always comes back from credential:list. The live path
        // can't know ownership yet (owner_name/owned_by_me absent — the descriptor was
        // built from the SENDER's view, where it's THEIR own cred), so it's kept
        // durable here and the loadCredentials merge dedupes it against own creds.
        if (entry.owned_by_me === true) {
            displayOnlyById.delete(entry.id);
        } else {
            // Tag with the active workflow so reads stay scoped to the open workflow
            // (no cross-workflow bleed) while persisting across leave/return.
            entry._wf = activeCredentialWorkflowId;
            displayOnlyById.set(entry.id, entry);
        }
    }
    cacheSubscribers.forEach((cb) => cb({ added: creds }));
}

/**
 * Optimistically drop credentials (by id) from the in-memory cache and notify
 * subscribers, so a credential deleted by a collaborator disappears from open
 * dropdowns live (the deletion arrives over the collaborative node:update sync).
 */
export function removeCredentialsFromCache(ids: string[]): void {
    if (!ids || ids.length === 0) return;
    const remove = new Set(ids);
    if (memoryCache) {
        for (const type of Object.keys(memoryCache)) {
            memoryCache[type] = memoryCache[type].filter((c) => !remove.has(c.id));
        }
    }
    for (const id of ids) displayOnlyById.delete(id);
    cacheSubscribers.forEach((cb) => cb({ removed: ids }));
}

/**
 * True if `id` is an injected run-as-owner display-only descriptor (not one of the
 * viewer's own credentials). Used to exclude these from auto-select and the
 * plan-limit cap count, which must only consider the viewer's own credentials.
 */
export function isInjectedDisplayCredential(id: string): boolean {
    return displayOnlyById.has(id);
}

/**
 * Authorize credentials for run-as-owner resolution on a workflow. Call this from
 * every LOCAL owner credential-placement site (manual pick, auto-select on add/paste).
 * The backend no longer authorizes off the autosaved blob because it is presence-tainted
 * (a collaborator could inject credentialIds via the collaborative channel). Owner-gated
 * server-side, so a collaborator's call is a harmless no-op. Fire-and-forget.
 */
export function authorizeCredentialsForWorkflow(
    workflowId: string | undefined | null,
    credentialIds: Record<string, string> | string[] | undefined | null,
): void {
    // Fall back to the open workflow when a caller (e.g. the paste hook) doesn't
    // thread workflowId — activeCredentialWorkflowId is set by FlowCanvas on mount.
    const wfId = workflowId || activeCredentialWorkflowId;
    if (!wfId || !credentialIds) return;
    const ids = Array.isArray(credentialIds) ? credentialIds : Object.values(credentialIds);
    for (const credId of new Set(ids.filter(Boolean))) {
        sendEventAsync(CredentialAuthorizeForWorkflowRequest.create({
            workflow_id: wfId, credential_id: credId,
        })).catch(() => { /* owner-gated no-op / transient */ });
    }
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
}
