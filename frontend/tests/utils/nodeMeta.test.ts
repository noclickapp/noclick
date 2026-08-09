// Drift guard for the slim nodeMeta.json artifact: the schema-free predicates
// in ~/utils/nodeMeta must answer identically to a direct read of the full
// NODE_SCHEMAS registry (the authoritative frontend map, keyed by full node
// type e.g. 'automation-slack'). Both artifacts come from the same generator
// run (backend/scripts/generate_socket_types.py); this fails if one is
// regenerated without the other, if the meta keys drift from the registry's
// node types, or if the generator's x-is-trigger walk diverges from the
// frontend semantics the predicates replaced.
import { describe, it, expect } from 'vitest';
import { NODE_SCHEMAS, isAgentToolProviderType, isTriggerSource } from '~/utils/nodeSchemas';

type OpSchema = { const?: string; enum?: string[]; 'x-is-trigger'?: boolean };

// Mirrors the schema walk isTriggerSource performed before the nodeMeta split.
function schemaTriggerOps(schema: {
    properties?: { config?: Record<string, unknown> };
    $defs?: Record<string, { properties?: { operation?: OpSchema } }>;
}): Map<string, boolean> {
    const config = (schema.properties?.config ?? {}) as {
        oneOf?: Array<{ $ref?: string }>;
        anyOf?: Array<{ $ref?: string }>;
        $ref?: string;
    };
    const defs = schema.$defs ?? {};
    const refs = config.oneOf ?? config.anyOf ?? (config.$ref ? [{ $ref: config.$ref }] : []);
    const ops = new Map<string, boolean>();
    for (const ref of refs) {
        const key = ref.$ref?.split('/').pop();
        const op = key ? defs[key]?.properties?.operation : undefined;
        const name = op?.const ?? op?.enum?.[0];
        if (name) ops.set(name, Boolean(op?.['x-is-trigger']));
    }
    return ops;
}

describe('nodeMeta.json stays in lockstep with NODE_SCHEMAS', () => {
    const types = Object.keys(NODE_SCHEMAS);

    it('covers every registered node type', () => {
        expect(types.length).toBeGreaterThan(100);
        // The canary for the key-format bug this test exists to catch: full
        // registry keys, not stripped schema filenames.
        expect(isAgentToolProviderType('automation-slack')).toBe(true);
    });

    it('isAgentToolProviderType matches x-agent-tool-provider for every type', () => {
        for (const type of types) {
            expect(isAgentToolProviderType(type), type).toBe(
                NODE_SCHEMAS[type]?.['x-agent-tool-provider'] === true,
            );
        }
    });

    it('isTriggerSource matches x-is-trigger for every operation of every type', () => {
        for (const type of types) {
            if (type.startsWith('trigger-') || type === 'interface-form') {
                expect(isTriggerSource(type, null), type).toBe(true);
                continue;
            }
            for (const [op, isTrigger] of schemaTriggerOps(NODE_SCHEMAS[type])) {
                expect(isTriggerSource(type, op), `${type}.${op}`).toBe(isTrigger);
            }
        }
    });
});
