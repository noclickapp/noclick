/**
 * Pure search-matching logic for the FlowHelper node palette. Builds a
 * schema-backed search index per node (label/description + per-operation name
 * and field metadata) and scores a query against it. Extracted from
 * NodesTabContent so the matching rules are unit-testable and the component
 * stays focused on rendering.
 *
 * Key rule: an operation is only seeded when the query carries "operation
 * intent" — at least one term that isn't part of the node's own identity
 * (label/type). A bare node-name query like "reddit" must surface the node
 * without preselecting an arbitrary operation, because the service name appears
 * pervasively in every operation's field metadata (e.g. "subreddit") and would
 * otherwise match them all and seed whichever happens to be first.
 */

import type { NodeDefinition } from '~/components/workflow/nodes/types';
import { getAvailableOperations } from '~/utils/operationHelpers';
import { getFieldsForOption, getSchemaInfo } from '~/utils/schemaFieldExtractor';

export interface OperationSearchIndexEntry {
    value: string;
    label: string;
    /** Operation identity: label, value, title, display-name, category. A hit
     *  here is a far stronger signal than a hit buried in field metadata. */
    nameHaystack: string;
    /** Full text: operation identity + field/description metadata. */
    haystack: string;
}

export interface NodeSearchIndexEntry {
    /** Lowercased node label, kept verbatim so an exact node-name query can be
     *  rewarded above a mere substring hit on the identity haystack. */
    label: string;
    /** Node identity (label + type). A query made up entirely of identity
     *  terms is a pure node-name query and must not seed an operation. */
    identityHaystack: string;
    baseHaystack: string;
    operations: OperationSearchIndexEntry[];
}

export interface OperationSearchMatch {
    initialOperation: string;
    seedLabel: string;
    score: number;
}

function addSearchText(parts: string[], value: unknown) {
    if (typeof value === 'string' && value.trim()) {
        parts.push(value.toLowerCase());
    } else if (Array.isArray(value)) {
        value.forEach((item) => addSearchText(parts, item));
    } else if (value && typeof value === 'object') {
        Object.values(value as Record<string, unknown>).forEach((item) => addSearchText(parts, item));
    }
}

function addFieldSearchText(parts: string[], fieldKey: string, prop: unknown) {
    const schemaProp = prop && typeof prop === 'object' ? prop as Record<string, unknown> : {};
    addSearchText(parts, fieldKey);
    addSearchText(parts, schemaProp.title);
    addSearchText(parts, schemaProp['ui:category']);
    addSearchText(parts, schemaProp['x-display-name']);
    addSearchText(parts, schemaProp['x-tier-label']);
    addSearchText(parts, schemaProp['x-dynamic-options']);
    addSearchText(parts, schemaProp.format);
    addSearchText(parts, schemaProp.const);
    addSearchText(parts, schemaProp.enum);
    addSearchText(parts, schemaProp.enumNames);
    addSearchText(parts, schemaProp.enumLabels);
}

export function buildNodeSearchIndexEntry(node: NodeDefinition): NodeSearchIndexEntry {
    const identityHaystack = `${node.label} ${node.type}`.toLowerCase();
    const baseParts: string[] = [node.label, node.description, node.type, ...(node.keywords ?? [])].map((value) => value.toLowerCase());
    const schemaInfo = getSchemaInfo(node.type);
    const operations = getAvailableOperations(node.type);
    const operationEntries: OperationSearchIndexEntry[] = [];

    if (operations.length > 0) {
        operations.forEach((operation) => {
            // nameParts = the operation's own identity (strong signal);
            // fieldParts = prose + field metadata (weak signal). Keeping them
            // apart lets scoring prefer an operation whose label/value matches
            // over one that merely mentions the term in a field description.
            const nameParts: string[] = [];
            const fieldParts: string[] = [];
            const optionIndex = schemaInfo?.discriminator.valueToOptionIndex.get(operation.value);
            const option = optionIndex !== undefined ? schemaInfo?.options[optionIndex] : null;
            const resolved = option?.$ref ? schemaInfo?.resolveRef(option.$ref) : option;
            const discriminatorProp = schemaInfo?.discriminator.fieldName
                ? resolved?.properties?.[schemaInfo.discriminator.fieldName]
                : null;
            addSearchText(nameParts, operation.label);
            addSearchText(nameParts, operation.value);
            addSearchText(nameParts, resolved?.title);
            addSearchText(nameParts, resolved?.['x-category']);
            addSearchText(nameParts, discriminatorProp?.['x-category']);
            addSearchText(nameParts, discriminatorProp?.['x-display-name']);
            addSearchText(nameParts, discriminatorProp?.const);
            // Authored search synonyms — strong, operation-specific signal (a
            // user typing "get rows" should seed Read Sheet Data here, same as
            // in the OperationPicker). Built into the memoized index, so this is
            // free per keystroke; generic synonym expansion is deliberately NOT
            // applied to this hot path (per-keystroke scan over ~3.7k ops).
            addSearchText(nameParts, discriminatorProp?.['x-keywords']);
            addSearchText(fieldParts, resolved?.description);
            getFieldsForOption(node.type, undefined, operation.value).forEach(({ key, prop }) => {
                addFieldSearchText(fieldParts, key, prop);
            });
            operationEntries.push({
                value: operation.value,
                label: operation.label,
                nameHaystack: nameParts.join(' '),
                haystack: [...nameParts, ...fieldParts].join(' '),
            });
        });
    } else {
        getFieldsForOption(node.type).forEach(({ key, prop }) => {
            addFieldSearchText(baseParts, key, prop);
        });
    }

    return { label: node.label.toLowerCase(), identityHaystack, baseHaystack: baseParts.join(' '), operations: operationEntries };
}

function tokenize(query: string): string[] {
    return query.toLowerCase().split(/\s+/).filter(Boolean);
}

// Ranking bands. A higher band always beats a lower one regardless of the
// within-band length/name bonuses (every gap dwarfs the largest bonus), so the
// bands encode the core rule on their own: a node matched by its OWN NAME
// outranks any node matched only through another node's operation metadata.
// Without this, the flat operation boost let a sibling node whose field
// metadata merely mentioned the term (e.g. "subreddit") bury the node the user
// literally named.
const BAND_NODE_NAME = 40_000; // query matches the node's identity (label/type)
const BAND_OP_NAME = 30_000; // query names a specific operation
const BAND_NODE_DESC = 20_000; // query appears only in the node description
const BAND_OP_FIELD = 10_000; // query appears only in operation field metadata
const EXACT_NAME_BONUS = 5_000; // query is exactly the node name

export function scoreSearchText(haystack: string, query: string): number | null {
    const normalizedQuery = query.toLowerCase();
    if (haystack.includes(normalizedQuery)) return 1000 + normalizedQuery.length;
    const terms = normalizedQuery.split(/\s+/).filter(Boolean);
    if (terms.length > 0 && terms.every((term) => haystack.includes(term))) {
        return 100 + terms.reduce((sum, term) => sum + term.length, 0);
    }
    return null;
}

export function getNodeSearchScore(entry: NodeSearchIndexEntry, query: string): number | null {
    // Identity (name/type) match is the strongest node-level signal — surface
    // it in the top band, with an extra bump when the query is exactly the name.
    const identity = scoreSearchText(entry.identityHaystack, query);
    if (identity !== null) {
        const exact = query.trim().toLowerCase() === entry.label ? EXACT_NAME_BONUS : 0;
        return BAND_NODE_NAME + exact + identity;
    }
    // Otherwise a description/type-only hit — a real but weaker node match.
    const base = scoreSearchText(entry.baseHaystack, query);
    return base === null ? null : BAND_NODE_DESC + base;
}

export function getOperationSearchMatch(
    entry: NodeSearchIndexEntry,
    query: string,
): OperationSearchMatch | null {
    // Operation-intent terms = query words that aren't part of the node's own
    // identity. A query that's purely the node name has none, so it surfaces
    // the node without seeding an arbitrary operation.
    const intentTerms = tokenize(query).filter((term) => !entry.identityHaystack.includes(term));
    if (intentTerms.length === 0) return null;

    const intentQuery = intentTerms.join(' ');
    const intentLength = intentTerms.reduce((sum, term) => sum + term.length, 0);
    let best: { operation: OperationSearchIndexEntry; score: number } | null = null;
    for (const operation of entry.operations) {
        // Every intent term must appear somewhere in the operation, otherwise
        // the query doesn't reasonably describe it.
        if (!intentTerms.every((term) => operation.haystack.includes(term))) continue;
        // A query that names the operation (all intent terms hit its own name)
        // is a strong signal; one that only surfaces via field metadata is weak
        // and must sit below node-name matches. Banding both selects the best
        // operation within the node and ranks it correctly across nodes.
        const matchedName = intentTerms.every((term) => operation.nameHaystack.includes(term));
        let score = (matchedName ? BAND_OP_NAME : BAND_OP_FIELD) + intentLength;
        // Reward matches on the operation's own name over field-metadata hits,
        // so "get comments" lands on Get Comments rather than another operation
        // that merely mentions comments in a field description.
        if (operation.nameHaystack.includes(intentQuery)) score += 1000;
        score += intentTerms.filter((term) => operation.nameHaystack.includes(term)).length * 100;
        if (!best || score > best.score) best = { operation, score };
    }
    return best
        ? { initialOperation: best.operation.value, seedLabel: best.operation.label, score: best.score }
        : null;
}
