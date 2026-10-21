// @vitest-environment jsdom
//
// Node schemas load per node type (each generated file is its own lazy chunk), so
// opening a workflow fetches only its own types' schemas, plus one more each time
// a node of a new type arrives. This file starts with nothing loaded: its module
// graph is its own.
import { readdirSync, readFileSync } from 'node:fs';
import { dirname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { useNodeSchemas } from '~/hooks/useNodeSchemas';
import {
    NODE_SCHEMAS,
    NODE_SCHEMA_TYPES,
    credentialMarks,
    getAgentWirableCatalog,
    loadAllNodeSchemas,
    nodeSchemasLoaded,
} from '~/utils/nodeSchemas';
import { getSchemaInfo } from '~/utils/schemaFieldExtractor';

const loadedTypes = () => Object.keys(NODE_SCHEMAS).sort();

describe('node schemas load per node type', () => {
    it("opening a workflow loads only its types' schemas, and a new type's when a node of it arrives", async () => {
        expect(loadedTypes()).toEqual([]);
        // A schema still loading has no info, and that answer is not kept.
        expect(getSchemaInfo('automation-slack')).toBeNull();

        // The canvas asks for its nodes' types (duplicates, a node with no schema, a legacy alias).
        const workflow = ['trigger-webhook', 'agent', 'automation-slack', 'automation-slack', 'stickyNote', 'interface-image'];
        const { result, rerender } = renderHook(({ types }) => useNodeSchemas(types), {
            initialProps: { types: workflow },
        });
        expect(result.current).toBe(false);
        await waitFor(() => expect(result.current).toBe(true));
        expect(loadedTypes()).toEqual(['agent', 'automation-slack', 'interface-file', 'trigger-webhook']);
        expect(getSchemaInfo('automation-slack')?.hasDiscriminator).toBe(true);

        // A node of a new type arrives (palette, builder, collaborator): just its schema follows.
        rerender({ types: [...workflow, 'automation-gmail'] });
        expect(result.current).toBe(false);
        await waitFor(() => expect(result.current).toBe(true));
        expect(loadedTypes()).toEqual(['agent', 'automation-gmail', 'automation-slack', 'interface-file', 'trigger-webhook']);
    });

    it('readers that walk every type refuse until every schema has loaded', async () => {
        expect(() => getAgentWirableCatalog()).toThrow(/loadAllNodeSchemas/);
        expect(() => credentialMarks(() => true)).toThrow(/loadAllNodeSchemas/);

        await loadAllNodeSchemas();
        expect(nodeSchemasLoaded(NODE_SCHEMA_TYPES)).toBe(true);
        expect(loadedTypes()).toEqual([...NODE_SCHEMA_TYPES].sort());
        expect(getAgentWirableCatalog().tools).toContain('automation-slack');
    });
});

describe('the generated schema files and the type list agree', () => {
    const schemaDir = join(dirname(fileURLToPath(import.meta.url)), '../../app/schemas/nodes');

    it('every schema file is a listed type, and every listed type has its file', () => {
        const stems = readdirSync(schemaDir).filter((f) => f.endsWith('.json')).map((f) => f.slice(0, -5)).sort();
        expect(NODE_SCHEMA_TYPES.map((type) => type.replace(/^automation-/, '')).sort()).toEqual(stems);
    });
});

describe('no module bundles node schemas', () => {
    // A static import of a schema file puts it in its importer's chunk: the canvas
    // carried every schema before a node could draw. Load through utils/nodeSchemas.
    // agent.json rides the dashboard's own bundle for the agent chat's model lists.
    const ALLOWED: Record<string, string[]> = {
        'app/lib/agentChat.ts': ['agent.json'],
        'app/lib/agentCredentialModel.ts': ['agent.json'],
    };

    it('only the allowed modules import a schema file directly', () => {
        const frontend = join(dirname(fileURLToPath(import.meta.url)), '../..');
        const offenders: string[] = [];
        const walk = (dir: string) => {
            for (const entry of readdirSync(dir, { withFileTypes: true })) {
                const path = join(dir, entry.name);
                if (entry.isDirectory()) {
                    if (entry.name !== 'node_modules' && entry.name !== 'schemas') walk(path);
                    continue;
                }
                if (!/\.tsx?$/.test(entry.name) || /\.test\.tsx?$/.test(entry.name)) continue;
                const rel = relative(frontend, path);
                for (const match of readFileSync(path, 'utf8').matchAll(/^import\s[^;]*?from\s+'~\/schemas\/nodes\/([\w-]+\.json)'/gm)) {
                    if (!ALLOWED[rel]?.includes(match[1])) offenders.push(`${rel}: ${match[1]}`);
                }
            }
        };
        walk(join(frontend, 'app'));
        expect(offenders).toEqual([]);
    });
});
