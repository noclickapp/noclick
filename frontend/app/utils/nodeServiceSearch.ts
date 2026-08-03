// Search over a list of node types presented as *services* — the agent wiring
// palette's "Add trigger" / "Add tool" steps. A service matches on its own
// identity (registry label, node type, authored keywords, description) and,
// failing that, on the actions it can perform, so "schedule" finds Schedule and
// "issue" finds Linear even though neither word is in the node's name.
//
// Written because the palette used to match ONLY the type-derived label
// ("Trigger Cron"), which made the Schedule trigger unfindable by any word a
// user would actually type.

import { getAgentToolOperations, getTriggerOperations } from './nodeSchemas';
import { scoreFields, type SearchField } from './fuzzySearch';

export type ServiceSearchRole = 'trigger' | 'tool';

export interface NodeServiceTarget {
    nodeType: string;
    /** Registry display label ('Schedule'), not the type-derived one. */
    label: string;
    description?: string;
    /** NodeDefinition.keywords — authored aliases for this node type. */
    keywords?: string[];
}

// Identity hits are banded above every action hit. scoreFields contributes at
// most ~1 per query token, so no realistic query can score into the band.
const IDENTITY_BAND = 100;

const _actionText = new Map<string, string>();

/** Lowercased haystack of what the node can DO in this role — operation display
 *  names, raw values and authored `x-keywords`. Memoized per (role, type): the
 *  schema walk is pure and the palette re-filters on every keystroke. */
function actionText(nodeType: string, role: ServiceSearchRole): string {
    const key = `${role}:${nodeType}`;
    const cached = _actionText.get(key);
    if (cached !== undefined) return cached;
    const parts =
        role === 'trigger'
            ? getTriggerOperations(nodeType).map(
                  (op) => `${op.displayName} ${op.operation} ${op.keywords}`
              )
            : getAgentToolOperations(nodeType).map(
                  (op) =>
                      `${op.displayName} ${op.operation} ${op.keywords} ${op.category ?? ''}`
              );
    const text = parts.join(' ').replace(/[_-]+/g, ' ').toLowerCase();
    _actionText.set(key, text);
    return text;
}

function identityFields(target: NodeServiceTarget): SearchField[] {
    const fields: SearchField[] = [
        { text: target.label.toLowerCase(), weight: 1, fuzzy: true },
        {
            text: target.nodeType
                .replace(/^automation-/, '')
                .replace(/[_-]+/g, ' ')
                .toLowerCase(),
            weight: 0.6,
            fuzzy: true,
        },
    ];
    if (target.keywords?.length)
        fields.push({
            text: target.keywords.join(' ').toLowerCase(),
            weight: 0.7,
        });
    if (target.description)
        fields.push({ text: target.description.toLowerCase(), weight: 0.4 });
    return fields;
}

/** Relevance of one service to the query, or null when it doesn't match. */
export function scoreNodeService(
    target: NodeServiceTarget,
    role: ServiceSearchRole,
    query: string
): number | null {
    const identity = identityFields(target);
    const own = scoreFields(identity, query);
    if (own !== null) return IDENTITY_BAND + own;
    // Mixed queries ("linear issue") only survive when identity and actions are
    // scored in ONE pool — scoreFields requires every token to hit some field.
    return scoreFields(
        [...identity, { text: actionText(target.nodeType, role), weight: 0.5 }],
        query
    );
}

/** Filter + rank services best-first. An empty query returns them unchanged. */
export function filterNodeServices<T extends NodeServiceTarget>(
    items: T[],
    query: string,
    role: ServiceSearchRole
): T[] {
    if (!query.trim()) return items;
    const scored: { item: T; score: number }[] = [];
    for (const item of items) {
        const score = scoreNodeService(item, role, query);
        if (score !== null) scored.push({ item, score });
    }
    // Array.prototype.sort is stable, so equal scores keep alphabetical order.
    scored.sort((a, b) => b.score - a.score);
    return scored.map((s) => s.item);
}
