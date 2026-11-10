// What searching nodes needs from every node's schema, built once on the server (lib/nodeSearchCatalog.server) and
// fetched by a palette when it opens, so neither the canvas palette nor the agent wiring palette loads a thousand
// schemas to search them. Each palette lists its nodes without it and searches their names at once; operations and
// actions match once it lands.
import type { NodeSearchText, OperationSearchIndexEntry } from './nodeSearchMatch';
import type { ActionTextOf, ServiceSearchRole } from './nodeServiceSearch';
import type { TriggerOperation } from './nodeSchemas';
import type { SerializedNodeMeta } from '~/lib/nodeCatalogTypes';
import { setNodeIconData } from '~/lib/nodeIconRegistry';

export const NODE_SEARCH_CATALOG_PATH = '/api/node-search';

export interface NodeSearchCatalog {
    /** The node catalog the dashboard's loader serves (lib/nodeIconRegistry), for a page that has none (a shared
     *  workflow's palette). */
    nodes: Record<string, SerializedNodeMeta>;
    /** Each node type's schema search text (nodeSearchText). */
    text: Record<string, NodeSearchText>;
    /** Every node that can wake an agent, with its triggers, and every agent tool provider: the agent wiring
     *  palette's lists (getAgentWirableCatalog). */
    wirable: { triggers: Array<{ nodeType: string; triggerOps: TriggerOperation[] }>; tools: string[] };
    /** What each of them does, as search text (triggerActionText, toolActionText). */
    actions: Record<ServiceSearchRole, Record<string, string>>;
}

/** An operation as sent: [value, label, name words, field words]. */
type WireOperation = [string, string, string, string];

/** The catalog as sent: the same, each operation a tuple (as objects, the four property names would repeat on each
 *  of about 39,000 operations). */
export interface NodeSearchCatalogWire extends Omit<NodeSearchCatalog, 'text'> {
    text: Record<string, { operations: WireOperation[]; fields: string }>;
}

export function encodeNodeSearchCatalog(catalog: NodeSearchCatalog): NodeSearchCatalogWire {
    const text: NodeSearchCatalogWire['text'] = {};
    for (const [type, { operations, fields }] of Object.entries(catalog.text)) {
        text[type] = { fields, operations: operations.map((op) => [op.value, op.label, op.nameHaystack, op.fieldHaystack]) };
    }
    return { ...catalog, text };
}

export function decodeNodeSearchCatalog(wire: NodeSearchCatalogWire): NodeSearchCatalog {
    const text: NodeSearchCatalog['text'] = {};
    for (const [type, { operations, fields }] of Object.entries(wire.text)) {
        text[type] = {
            fields,
            operations: operations.map(([value, label, nameHaystack, fieldHaystack]): OperationSearchIndexEntry => ({ value, label, nameHaystack, fieldHaystack })),
        };
    }
    return { ...wire, text };
}

/** The catalog's action text, for filterNodeServices. */
export function catalogActionText(catalog: NodeSearchCatalog): ActionTextOf {
    return (nodeType, role) => catalog.actions[role][nodeType] ?? '';
}

let _catalog: NodeSearchCatalog | null = null;
let _loading: Promise<NodeSearchCatalog> | null = null;

/** The catalog once fetched this session. */
export function nodeSearchCatalog(): NodeSearchCatalog | null {
    return _catalog;
}

/** Fetches the catalog once a session; a failed fetch is thrown and the next call asks again. */
export function loadNodeSearchCatalog(): Promise<NodeSearchCatalog> {
    _loading ??= fetch(NODE_SEARCH_CATALOG_PATH)
        .then(async (response) => {
            if (!response.ok) throw new Error(`Node search catalog: HTTP ${response.status}`);
            _catalog = decodeNodeSearchCatalog((await response.json()) as NodeSearchCatalogWire);
            setNodeIconData(_catalog.nodes);
            return _catalog;
        })
        .catch((error: unknown) => {
            _loading = null;
            throw error;
        });
    return _loading;
}
