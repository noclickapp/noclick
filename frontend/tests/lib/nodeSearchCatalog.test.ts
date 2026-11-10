// The palettes search the catalog the server builds (lib/nodeSearchCatalog.server) instead of every node's schema.
// Searching it must find exactly what searching the schemas found, after the trip through JSON.
import { describe, expect, it } from 'vitest';
import { buildNodeSearchCatalog, nodeSearchCatalogJson } from '~/lib/nodeSearchCatalog.server';
import { AVAILABLE_NODES } from '~/components/workflow/nodes/nodeRegistry';
import { buildWiringServices } from '~/components/workflow/AgentWiringPalette';
import { setNodeIconData } from '~/lib/nodeIconRegistry';
import { getAgentWirableCatalog } from '~/utils/nodeSchemas';
import { buildNodeSearchIndexEntry, getNodeSearchScore, getOperationSearchMatch, nodeSearchIndexEntry } from '~/utils/nodeSearchMatch';
import { filterNodeServices, schemaActionText } from '~/utils/nodeServiceSearch';
import { catalogActionText, decodeNodeSearchCatalog, type NodeSearchCatalogWire } from '~/utils/nodeSearchCatalog';

const catalog = decodeNodeSearchCatalog(JSON.parse(nodeSearchCatalogJson()) as NodeSearchCatalogWire);
setNodeIconData(catalog.nodes);

const QUERIES = ['send message', 'create issue', 'get rows', 'append rows', 'subreddit', 'invoice', 'webhook', 'calendar event', 'upload file', 'schedule', 'list users', 'channel', 'email'];

describe('node search catalog', () => {
    it('holds every node, its search text and the wiring lists', () => {
        expect(Object.keys(catalog.text).sort()).toEqual(AVAILABLE_NODES.map((node) => node.type).sort());
        expect(catalog.wirable).toEqual(getAgentWirableCatalog());
        expect(catalog).toEqual(buildNodeSearchCatalog());
        // The palette names and searches a node by its catalog entry, never its definition module.
        for (const node of AVAILABLE_NODES) {
            const { label, description, keywords } = catalog.nodes[node.type];
            expect({ label, description, keywords }).toEqual({ label: node.label, description: node.description, keywords: node.keywords?.length ? node.keywords : undefined });
        }
    });

    it('finds in the canvas palette exactly what each schema found', () => {
        for (const node of AVAILABLE_NODES) {
            const fromSchema = buildNodeSearchIndexEntry(node);
            const fromCatalog = nodeSearchIndexEntry(node, catalog.text[node.type]);
            expect(fromCatalog).toEqual(fromSchema);
            for (const query of QUERIES) {
                expect(getOperationSearchMatch(fromCatalog, query)).toEqual(getOperationSearchMatch(fromSchema, query));
                expect(getNodeSearchScore(fromCatalog, query)).toEqual(getNodeSearchScore(fromSchema, query));
            }
        }
    });

    it('finds in the agent wiring palette exactly what each schema found', () => {
        for (const role of ['trigger', 'tool'] as const) {
            const services = buildWiringServices(role, catalog);
            expect(services.length).toBeGreaterThan(role === 'trigger' ? 50 : 500);
            for (const query of QUERIES) {
                const fromCatalog = filterNodeServices(services, query, role, catalogActionText(catalog)).map((s) => s.nodeType);
                expect(fromCatalog).toEqual(filterNodeServices(services, query, role, schemaActionText).map((s) => s.nodeType));
            }
        }
    });
});
