/**
 * Shared mapping from Pydantic credential schema titles to database credential_type identifiers.
 * Used by NodeCredentials for schema parsing and credentialAutoSelect for auto-selection logic.
 */

import type { ComponentType, CSSProperties } from 'react';
import {
    CREDENTIAL_TYPE_MAP,
    getCredentialTypeFromSchemaTitle,
} from './credentialTypeMap';
import { fixWordCasing } from './credentialLabels';
import { getNodeIconData } from '~/lib/nodeIconRegistry';
import { serializedIconComponent } from '~/components/shared/SerializedIcon';
type ServiceIconType = ComponentType<{ className?: string; style?: CSSProperties }>;

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

/** Convert DB credential type strings (e.g. `github_pat`) to friendly labels (e.g. `GitHub PAT`). */
export function formatCredentialTypeLabel(dbType: string): string {
    return fixWordCasing(
        dbType
            .split('_')
            .map(w => w.charAt(0).toUpperCase() + w.slice(1))
            .join(' ')
    );
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

/** Returns a list of services that require credentials: each node type with the credential types it accepts, from
 *  the serialized node catalog the dashboard loader hands over (lib/nodeIconRegistry), so listing services never
 *  loads the node registry or the schemas. Empty until that catalog is set. */
export function getServiceCredentialOptions(): ServiceCredentialOption[] {
    if (_serviceCredentialCache) return _serviceCredentialCache;

    const options: ServiceCredentialOption[] = [];
    const seenPrimaryTypes = new Set<string>();

    // The catalog lists nodes in the registry's order, so the first node to claim a primary type keeps it.
    for (const node of Object.values(getNodeIconData())) {
        const acceptedTypes = node.acceptedCredentialTypes;
        if (!acceptedTypes?.length) continue;

        const primaryType = acceptedTypes[0];
        if (seenPrimaryTypes.has(primaryType)) continue;
        seenPrimaryTypes.add(primaryType);

        options.push({
            value: node.type,
            label: node.label,
            primaryCredentialType: primaryType,
            acceptedCredentialTypes: acceptedTypes,
            Icon: serializedIconComponent(node.iconHtml),
            iconColor: node.iconColor,
        });
    }

    if (!options.length) return options;
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
