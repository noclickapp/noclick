// @vitest-environment happy-dom
// (The node catalog's ag-grid sets a bare `Node = {}` where there's no DOM.)
//
// Every integration's generated wiring links up, checked once over all of them in place of a test file per
// integration: its definition (a label search finds, an icon that draws, every icon file it shows on disk), its schema
// (each operation one config member; an agent tool provider offering some of them), and its credentials (each class's
// title and name mapped to the type it declares, the node accepting exactly those, an OAuth class naming its provider).
import { existsSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import {
    methodFromRequirement,
    requirementsFromSchema,
} from '~/components/credential/credentialMethods';
import { NODE_DEFINITION_FILES } from '~/components/workflow/nodes/nodeDefinitions';
import { getSerializedNodeMeta } from '~/lib/nodeCatalog.server';
import {
    CREDENTIAL_TYPE_MAP,
    getCredentialTypeFromSchemaTitle,
} from '~/utils/credentialTypeMap';
import {
    NODE_SCHEMAS,
    getAgentToolOperations,
    getNodeCredentialInfo,
    isAgentToolProviderType,
} from '~/utils/nodeSchemas';
import {
    buildNodeSearchIndexEntry,
    getNodeSearchScore,
} from '~/utils/nodeSearchMatch';

type Schema = (typeof NODE_SCHEMAS)[string];

const PUBLIC = join(dirname(fileURLToPath(import.meta.url)), '../../public');
const INTEGRATIONS = NODE_DEFINITION_FILES.filter(([, file]) =>
    file.startsWith('integrations/')
).map(([type]) => type);

function operations(schema: Schema): string[] {
    const config = schema.properties?.config ?? {};
    const refs: Array<{ $ref?: string }> =
        config.oneOf ??
        config.anyOf ??
        (config.$ref ? [{ $ref: config.$ref }] : []);
    return refs.map((ref) => {
        const operation =
            schema.$defs?.[ref.$ref?.split('/').pop() ?? '']?.properties
                ?.operation;
        return operation?.const ?? operation?.enum?.[0];
    });
}

function credentialClasses(
    schema: Schema
): Array<[name: string, cls: Schema | undefined]> {
    const prop = schema.properties?.credentials;
    if (!prop) return [];
    const refs: string[] = prop.$ref
        ? [prop.$ref]
        : (prop.anyOf ?? []).map((e: Schema) => e.$ref).filter(Boolean);
    return refs.map((ref) => {
        const name = ref.split('/').pop()!;
        return [name, schema.$defs?.[name]];
    });
}

/** Each integration's offences under one check, so a failure names every integration it catches. */
function offences(check: (type: string, schema: Schema) => string[]): string[] {
    return INTEGRATIONS.flatMap((type) =>
        check(type, NODE_SCHEMAS[type]).map((problem) => `${type}: ${problem}`)
    );
}

describe('every integration', () => {
    it('is enough of them to be the catalog', () => {
        expect(INTEGRATIONS.length).toBeGreaterThan(500);
    });

    it('has a schema, a label its search finds and an icon that draws', () => {
        expect(
            offences((type, schema) => {
                if (!schema) return ['no schema'];
                const meta = getSerializedNodeMeta(type);
                if (!meta?.label.trim()) return ['no definition with a label'];
                const problems: string[] = [];
                if (!meta.iconHtml.trim())
                    problems.push('its icon draws nothing');
                if (
                    getNodeSearchScore(
                        buildNodeSearchIndexEntry(meta),
                        meta.label
                    ) === null
                )
                    problems.push(`search for "${meta.label}" misses it`);
                return problems;
            })
        ).toEqual([]);
    });

    it('shows only icon files that exist, with nothing in an SVG that runs', () => {
        expect(
            offences((type) => {
                const html = getSerializedNodeMeta(type)?.iconHtml ?? '';
                return [...html.matchAll(/\bsrc="(\/icons\/[^"]+)"/g)].flatMap(
                    ([, src]) => {
                        const file = join(PUBLIC, decodeURIComponent(src));
                        if (!existsSync(file)) return [`${src} is missing`];
                        if (
                            file.endsWith('.svg') &&
                            /<script|<foreignObject|\son\w+\s*=/i.test(
                                readFileSync(file, 'utf8')
                            )
                        )
                            return [`${src} carries script`];
                        return [];
                    }
                );
            })
        ).toEqual([]);
    });

    it('makes each operation one config member', () => {
        expect(
            offences((type, schema) => {
                if (!schema) return [];
                const ops = operations(schema);
                const problems = ops.some((op) => typeof op !== 'string')
                    ? ['a config member names no operation']
                    : [];
                if (new Set(ops).size !== ops.length)
                    problems.push('repeats an operation');
                if (isAgentToolProviderType(type)) {
                    const tools = getAgentToolOperations(type).map(
                        (op) => op.operation
                    );
                    if (!tools.length)
                        problems.push(
                            'is an agent tool provider with no tool operations'
                        );
                    problems.push(
                        ...tools
                            .filter((op) => !ops.includes(op))
                            .map(
                                (op) =>
                                    `offers ${op}, not one of its operations`
                            )
                    );
                }
                return problems;
            })
        ).toEqual([]);
    });

    it('maps each credential class to the type it declares, and accepts exactly those', () => {
        expect(
            offences((type, schema) => {
                if (!schema) return [];
                const classes = credentialClasses(schema);
                const problems: string[] = [];
                const declared: string[] = [];
                for (const [name, cls] of classes) {
                    if (!cls) {
                        problems.push(`${name} is not in its $defs`);
                        continue;
                    }
                    const credentialType: unknown =
                        cls.properties?.credential_type?.const ??
                        cls.properties?.credential_type?.default;
                    if (typeof credentialType !== 'string' || !credentialType) {
                        // A class without the field is typed by the map alone, which must name it.
                        const mapped = CREDENTIAL_TYPE_MAP[cls.title ?? ''];
                        if (mapped) declared.push(mapped);
                        else
                            problems.push(
                                `${name} declares no credential_type and the map doesn't name "${cls.title}"`
                            );
                        continue;
                    }
                    declared.push(credentialType);
                    for (const title of [cls.title, name]) {
                        const mapped = getCredentialTypeFromSchemaTitle(
                            title ?? ''
                        );
                        if (mapped !== credentialType)
                            problems.push(
                                `"${title}" maps to ${mapped}, not ${credentialType}`
                            );
                    }
                }
                if (!classes.length) return problems;
                const accepted =
                    getNodeCredentialInfo(type)?.acceptedTypes ?? [];
                if ([...accepted].sort().join() !== [...declared].sort().join())
                    problems.push(
                        `accepts [${accepted}], declares [${declared}]`
                    );
                for (const method of requirementsFromSchema(schema).map(
                    methodFromRequirement
                )) {
                    if (
                        method.method_kind === 'oauth' &&
                        !method.oauth_provider
                    )
                        problems.push(
                            `${method.credential_type} is OAuth with no provider`
                        );
                }
                return problems;
            })
        ).toEqual([]);
    });
});
