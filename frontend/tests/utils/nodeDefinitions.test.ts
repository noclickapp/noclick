// @vitest-environment jsdom
//
// Node definitions (each node's component, icon and label) load per node type, so the canvas
// carries only the open workflow's nodes. One list names every node with its module; this pins
// the list to the node files, and the loading to exactly the types asked for. This file's module
// graph is its own, so nothing has loaded when it starts.
import { readdirSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import {
    NODE_DEFINITION_FILES,
    NODE_DEFINITION_TYPES,
    getNodeDefinition,
    loadNodeDefinitions,
    nodeDefinitionStore,
} from '~/components/workflow/nodes/nodeDefinitions';

const nodesDir = join(dirname(fileURLToPath(import.meta.url)), '../../app/components/workflow/nodes');

describe('the node definition list', () => {
    it('names every node file, each with the type it defines', () => {
        const files = [
            ...readdirSync(nodesDir).filter((f) => f.endsWith('Node.tsx')),
            ...readdirSync(join(nodesDir, 'interface')).filter((f) => f.endsWith('Node.tsx')).map((f) => `interface/${f}`),
        ]
            .map((f) => f.slice(0, -'.tsx'.length))
            // The interface nodes' shared body, not a node of its own.
            .filter((f) => f !== 'interface/InterfaceNode')
            .sort();
        expect(NODE_DEFINITION_FILES.map(([, file]) => file).sort()).toEqual(files);
        expect(new Set(NODE_DEFINITION_TYPES).size).toBe(NODE_DEFINITION_TYPES.length);
        for (const [type, file] of NODE_DEFINITION_FILES) {
            expect(readFileSync(join(nodesDir, `${file}.tsx`), 'utf8'), `${file} defines ${type}`).toContain(`'${type}'`);
        }
    });
});

describe('node definitions load per node type', () => {
    it('loads only the types asked for, and a legacy type as the node that replaced it', async () => {
        expect(Object.keys(nodeDefinitionStore.values)).toEqual([]);
        expect(getNodeDefinition('automation-slack')).toBeUndefined();

        await loadNodeDefinitions(['automation-slack', 'agent', 'agent', 'interface-image', 'not-a-node']);
        expect(Object.keys(nodeDefinitionStore.values).sort()).toEqual(['agent', 'automation-slack', 'interface-file']);
        expect(getNodeDefinition('automation-slack')).toMatchObject({ type: 'automation-slack', label: 'Slack' });
        expect(getNodeDefinition('interface-image')?.type).toBe('interface-file');
        expect(nodeDefinitionStore.loaded(['automation-slack', 'not-a-node'])).toBe(true);
        expect(nodeDefinitionStore.loaded(['automation-gmail'])).toBe(false);
        // The first import of a node module transforms its whole component graph.
    }, 60_000);
});
