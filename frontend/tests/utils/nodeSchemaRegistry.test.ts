// A node that renders on the canvas but has no schema in NODE_SCHEMAS opens
// its config panel to "No schema found for node type" (the Phone node,
// 2026-09-18): the component registry is hand-kept and the schemas are
// generated, so this pins them to each other. The component files are scanned as
// source — importing the registry drags every React component and icon pack
// into the test runner.
import { readdirSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { getNodeSchema, loadAllNodeSchemas } from '~/utils/nodeSchemas';

// The subjects read node schemas, which load per type (some at collection time).
await loadAllNodeSchemas();

const nodesDir = join(dirname(fileURLToPath(import.meta.url)), '../../app/components/workflow/nodes');

function canvasNodeTypes(): string[] {
    const types: string[] = [];
    for (const file of readdirSync(nodesDir)) {
        if (!file.endsWith('Node.tsx')) continue;
        const source = readFileSync(join(nodesDir, file), 'utf8');
        // Integration nodes only: structural nodes (interface blocks, references,
        // sticky notes) are drawn from their own definitions, not a config schema.
        for (const match of source.matchAll(/^\s*type:\s*'(automation-[a-z0-9-]+)'/gm)) types.push(match[1]);
    }
    return types;
}

describe('node schema registry', () => {
    it('every canvas node has a config schema', () => {
        const types = canvasNodeTypes();
        expect(types.length).toBeGreaterThan(50);
        expect(types).toContain('automation-phone');
        const missing = types.filter((type) => !getNodeSchema(type));
        expect(missing, 'register the node in the backend NODE_REGISTRY and regenerate (backend/scripts/generate_socket_types.py)').toEqual([]);
    });
});
