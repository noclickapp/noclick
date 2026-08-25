/**
 * Shared mapping from Pydantic credential schema titles to database credential_type identifiers.
 * Used by NodeCredentials for schema parsing and credentialAutoSelect for auto-selection logic.
 */

// IMPORTANT: do NOT import AVAILABLE_NODES at module top-level — that pulls in the
// entire 92-node-component registry, which transitively re-enters this file via the
// FieldRenderer → credentialTypes chain and triggers a TDZ error during lazy loads
// of individual node files. Resolve it dynamically inside the function instead.
import type { ComponentType, CSSProperties } from 'react';
import {
    CREDENTIAL_TYPE_MAP,
    getCredentialTypeFromSchemaTitle,
} from './credentialTypeMap';
import { getNodeCredentialInfo } from '~/utils/nodeSchemas';
type ServiceIconType = ComponentType<{ className?: string; style?: CSSProperties }>;
type AvailableNode = { type: string; label: string; Icon: ServiceIconType; iconColor?: string };
let _availableNodesCache: AvailableNode[] | null = null;
let _loadInflight: Promise<void> | null = null;
function ensureAvailableNodes(): Promise<void> {
    if (_availableNodesCache) return Promise.resolve();
    if (_loadInflight) return _loadInflight;
    _loadInflight = import('~/components/workflow/nodes/nodeRegistry').then((m) => {
        // Cast through unknown: NodeDefinition.Icon is a wider union than the
        // className-only component type we expose, but every variant renders the
        // same way.
        _availableNodesCache = m.AVAILABLE_NODES as unknown as AvailableNode[];
    });
    return _loadInflight;
}

// CREDENTIAL_TYPE_MAP + getCredentialTypeFromSchemaTitle live in a leaf module
// so nodeSchemas.ts can read the lookup without importing this file — the two
// used to import each other, and Vite SSR would break on the cycle. Imported
// (several helpers below still read the map) and re-exported, so this stays the
// one public entry point for credential-type helpers.
export { CREDENTIAL_TYPE_MAP, getCredentialTypeFromSchemaTitle };

/**
 * Authoritative credential_type for a credential JSON schema: its discriminator
 * `credential_type.const` — the exact DB identifier the BACKEND keys on. Prefer this
 * over the title map (a hand-maintained duplicate that silently drops unmapped titles
 * to a lowercased title, e.g. `ApiKeyCredential` → `apikeycredential` instead of
 * `http_api_key`). Reading the const keeps the frontend and backend in lockstep.
 */
export function getCredentialTypeFromSchema(credSchema: any): string {
    return credSchema?.properties?.credential_type?.const
        || getCredentialTypeFromSchemaTitle(credSchema?.title || '');
}

/**
 * Get schema title from credential type (reverse lookup).
 * Returns null if not found.
 */
export function getSchemaTitleFromCredentialType(credentialType: string): string | null {
    for (const [title, type] of Object.entries(CREDENTIAL_TYPE_MAP)) {
        if (type === credentialType) {
            return title;
        }
    }
    return null;
}

const ABBREVIATIONS: Record<string, string> = {
    oauth: 'OAuth', api: 'API', pat: 'PAT', url: 'URL',
    acl: 'ACL', rss: 'RSS', rest: 'REST',
};

/** Convert DB credential type strings (e.g. `google_sheets_oauth`) to friendly labels (e.g. `Google Sheets OAuth`). */
export function formatCredentialTypeLabel(dbType: string): string {
    return dbType
        .split('_')
        .map(w => ABBREVIATIONS[w] || (w.charAt(0).toUpperCase() + w.slice(1)))
        .join(' ');
}

/** All unique DB credential type values, for use in searchable dropdowns. */
export const CREDENTIAL_TYPE_VALUES = [...new Set(Object.values(CREDENTIAL_TYPE_MAP))];

/** Human-readable labels corresponding to CREDENTIAL_TYPE_VALUES. */
export const CREDENTIAL_TYPE_LABELS = CREDENTIAL_TYPE_VALUES.map(formatCredentialTypeLabel);

// ============================================================================
// Service-level credential options (node type → all credential types)
// ============================================================================

export interface ServiceCredentialOption {
    /** Dropdown value — node type (e.g., 'automation-wordpress') */
    value: string;
    /** Display label — service name (e.g., 'WordPress') */
    label: string;
    /** First credential type for this service */
    primaryCredentialType: string;
    /** All credential types this service accepts */
    acceptedCredentialTypes: string[];
    /** The node's brand icon (same component the canvas uses). */
    Icon: ServiceIconType;
    /** Tailwind text-color class for the icon's brand color (e.g. 'text-sky-500'). */
    iconColor?: string;
}

let _serviceCredentialCache: ServiceCredentialOption[] | null = null;

/** Returns a list of services that require credentials, derived from node schemas.
 *  Each entry maps a node type to all credential types it supports.
 *  First call returns [] while it kicks off the async registry import; subsequent calls
 *  (after the registry has resolved) return the populated list. */
export function getServiceCredentialOptions(): ServiceCredentialOption[] {
    if (_serviceCredentialCache) return _serviceCredentialCache;
    if (!_availableNodesCache) {
        // Trigger lazy load; the next call (after promise resolves) will populate.
        void ensureAvailableNodes();
        return [];
    }

    const options: ServiceCredentialOption[] = [];
    const seenPrimaryTypes = new Set<string>();

    for (const node of _availableNodesCache) {
        const credInfo = getNodeCredentialInfo(node.type);
        if (!credInfo || credInfo.acceptedTypes.length === 0) continue;

        const primaryType = credInfo.acceptedTypes[0];
        if (seenPrimaryTypes.has(primaryType)) continue;
        seenPrimaryTypes.add(primaryType);

        options.push({
            value: node.type,
            label: node.label,
            primaryCredentialType: primaryType,
            acceptedCredentialTypes: credInfo.acceptedTypes,
            Icon: node.Icon,
            iconColor: node.iconColor,
        });
    }

    options.sort((a, b) => a.label.localeCompare(b.label));
    _serviceCredentialCache = options;
    return options;
}

/** Reverse lookup: find which service contains a given credential type. */
export function getServiceForCredentialType(credentialType: string): ServiceCredentialOption | undefined {
    return getServiceCredentialOptions().find(
        opt => opt.acceptedCredentialTypes.includes(credentialType)
    );
}
