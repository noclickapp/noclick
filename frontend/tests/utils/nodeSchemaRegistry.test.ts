// A node that renders on the canvas but has no schema in NODE_SCHEMAS opens
// its config panel to "No schema found for node type" (the Phone node,
// 2026-09-18): the component registry is hand-kept and the schemas are
// generated, so this pins them to each other. The lazy definition registry
// discovers filenames without importing components, including new integrations.
// A node with no config by design is declared in CONFIGLESS_NODE_TYPES instead.
import { describe, expect, it } from 'vitest';
import { NODE_DEFINITION_TYPES } from '~/components/workflow/nodes/nodeDefinitions';
import { CONFIGLESS_NODE_TYPES } from '~/utils/nodeMeta';
import { getNodeSchema, loadAllNodeSchemas } from '~/utils/nodeSchemas';

// The subjects read node schemas, which load per type (some at collection time).
await loadAllNodeSchemas();

describe('node schema registry', () => {
    it('every canvas node has a config schema unless it has no config by design', () => {
        expect(NODE_DEFINITION_TYPES.filter(type => type.startsWith('automation-')).length).toBeGreaterThan(50);
        expect(NODE_DEFINITION_TYPES).toContain('automation-phone');
        const missing = NODE_DEFINITION_TYPES.filter((type) => !getNodeSchema(type) && !CONFIGLESS_NODE_TYPES.has(type));
        expect(missing, 'register the node in the backend NODE_REGISTRY and regenerate (backend/scripts/generate_socket_types.py)').toEqual([]);
    });

    it('every node declared configless is a canvas node with no schema', () => {
        for (const type of CONFIGLESS_NODE_TYPES) {
            expect(NODE_DEFINITION_TYPES, type).toContain(type);
            expect(getNodeSchema(type), `${type} has a schema now: drop it from CONFIGLESS_NODE_TYPES`).toBeUndefined();
        }
    });
});
