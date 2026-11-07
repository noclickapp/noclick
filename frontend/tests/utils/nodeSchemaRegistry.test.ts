// A node that renders on the canvas but has no schema in NODE_SCHEMAS opens
// its config panel to "No schema found for node type" (the Phone node,
// 2026-09-18): the component registry is hand-kept and the schemas are
// generated, so this pins them to each other. The lazy definition registry
// discovers filenames without importing components, including new integrations.
import { describe, expect, it } from 'vitest';
import { NODE_DEFINITION_TYPES } from '~/components/workflow/nodes/nodeDefinitions';
import { getNodeSchema, loadAllNodeSchemas } from '~/utils/nodeSchemas';

// The subjects read node schemas, which load per type (some at collection time).
await loadAllNodeSchemas();

describe('node schema registry', () => {
    it('every canvas node has a config schema', () => {
        const types = NODE_DEFINITION_TYPES.filter(type => type.startsWith('automation-'));
        expect(types.length).toBeGreaterThan(50);
        expect(types).toContain('automation-phone');
        const missing = types.filter((type) => !getNodeSchema(type));
        expect(missing, 'register the node in the backend NODE_REGISTRY and regenerate (backend/scripts/generate_socket_types.py)').toEqual([]);
    });
});
