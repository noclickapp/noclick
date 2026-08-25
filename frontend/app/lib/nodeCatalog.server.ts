// Server-only node catalog for public marketing pages (integrations, templates).
//
// WHY THIS EXISTS: the node registry (app/components/workflow/nodes/nodeRegistry)
// statically imports ~80 full ReactFlow node components (AutomationNode + each
// node's config UI, schemas, ModelDropdown, MarkdownRenderer) — a ~4.7MB client
// chunk. The marketing pages only need lightweight per-node metadata + a brand
// icon, never the node component, yet importing the registry from a route dragged
// that whole 4.7MB graph into the route's client bundle. Downloading + (more
// importantly) synchronously module-evaluating it on the main thread at navigation
// commit is what froze the Templates/Integrations routes on click.
//
// This module is `.server` so it can NEVER be imported into the client bundle
// (Remix's Vite plugin enforces it). The route LOADER (server) calls it; the icon
// is pre-rendered to an HTML string here and the client renders it via
// <SerializedIcon> (app/components/shared/SerializedIcon) — so the registry stays
// entirely server-side and the client bundle carries only serialized data.
import { renderToStaticMarkup } from 'react-dom/server';
import { createElement, type ComponentType } from 'react';
import { OpenAI } from '@lobehub/icons';
import {
    AVAILABLE_NODES,
    getNodeMetadata,
} from '~/components/workflow/nodes/nodeRegistry';
import { HARNESS_BRANDS, type HarnessSlug } from '~/lib/harnessBrand';
import { inboundEmailDomain } from '~/lib/inboundEmail';
import {
    getSchemaInfo,
    createRefResolver,
    getFieldsForOption,
} from '~/utils/schemaFieldExtractor';
import type {
    SerializedNodeMeta,
    OperationInfo,
    FieldInfo,
    ProviderToolOperation,
    ProviderIntegration,
    TriggerOption,
} from '~/lib/nodeCatalogTypes';

export type {
    SerializedNodeMeta,
    OperationInfo,
    FieldInfo,
    ProviderToolOperation,
    ProviderIntegration,
    TriggerOption,
} from '~/lib/nodeCatalogTypes';

// AVAILABLE_NODES is static, so the serialized catalog is computed once per server
// process and cached (renderToStaticMarkup per icon is cheap, but no reason to
// repeat it on every request).
const _metaCache = new Map<string, SerializedNodeMeta>();

function escapeRegExp(s: string): string {
    return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

// Make every SVG element id in a serialized icon globally unique by suffixing the
// node type. WHY: several node icons build gradients with useId(), but
// renderToStaticMarkup resets useId per render, so every serialized icon reuses
// the same id (e.g. `«r0»`). Multiple icons injected into one DOM via
// dangerouslySetInnerHTML then collide — a `fill="url(#«r0»)"` resolves to the
// FIRST matching gradient in document order, so Telegram's blue gradient would
// paint with an earlier green sibling's (Excel/Sheets). Namespacing per type
// keeps each icon referencing its own defs. Rewrites the id definition plus every
// url(#id) / href="#id" / xlink:href="#id" reference.
function namespaceSvgIds(html: string, type: string): string {
    const ns = type.replace(/[^a-zA-Z0-9]/g, '');
    const ids = new Set<string>();
    // Leading \s so this matches the real `id` attribute only, not `data-id` etc.
    for (const m of html.matchAll(/\sid="([^"]+)"/g)) ids.add(m[1]);
    let out = html;
    for (const id of ids) {
        const esc = escapeRegExp(id);
        const next = `${id}-${ns}`;
        out = out
            .replace(new RegExp(`(\\s)id="${esc}"`, 'g'), `$1id="${next}"`)
            .replace(
                new RegExp(`url\\((['"]?)#${esc}\\1\\)`, 'g'),
                `url($1#${next}$1)`
            )
            .replace(
                new RegExp(`(xlink:href|href)="#${esc}"`, 'g'),
                `$1="#${next}"`
            );
    }
    return out;
}

function serialize(type: string): SerializedNodeMeta | undefined {
    const node = getNodeMetadata(type);
    if (!node) return undefined;
    const meta: SerializedNodeMeta = {
        type,
        label: node.label,
        description: node.description,
        iconColor: node.iconColor ?? '',
        iconHtml: node.Icon
            ? namespaceSvgIds(
                  // All catalog icons render without required props. Collapse
                  // the heterogeneous img/svg/lucide union only at this React
                  // overload boundary.
                  renderToStaticMarkup(createElement(node.Icon as ComponentType)),
                  type
              )
            : '',
        dimensions: {
            width: node.dimensions?.width ?? 0,
            height: node.dimensions?.height ?? 0,
            iconSize: node.dimensions?.iconSize ?? 0,
        },
    };
    const triggerOps = extractNodeOperations(type)
        .filter((o) => o.isTrigger)
        .map((o) => o.value);
    if (triggerOps.length > 0) meta.triggerOps = triggerOps;
    return meta;
}

/** Serialized metadata (incl. pre-rendered icon HTML) for one node type. */
export function getSerializedNodeMeta(
    type: string
): SerializedNodeMeta | undefined {
    const cached = _metaCache.get(type);
    if (cached) return cached;
    const meta = serialize(type);
    if (meta) _metaCache.set(type, meta);
    return meta;
}

// Harness brand-mark svg paths come from the shared HARNESS_BRANDS registry (the
// single source of truth reused by the canvas AgentModelIcon + credential icons).
// Codex is intentionally absent — its mark is the @lobehub/icons OpenAI component,
// rendered separately in getHarnessIcon (no public SVG exists for it).
const _harnessIconCache = new Map<
    string,
    { iconHtml: string; iconColor: string }
>();

/** Serialized brand icon (markup + color) for a harness slug, for SerializedIcon.
    iconColor '' lets multicolor SVGs render as-is; Codex's mono mark (currentColor)
    gets text-foreground so it flips with the theme (dark glyph on light chips). */
export function getHarnessIcon(slug: string): {
    iconHtml: string;
    iconColor: string;
} {
    const cached = _harnessIconCache.get(slug);
    if (cached) return cached;
    let result: { iconHtml: string; iconColor: string };
    if (slug === 'codex') {
        result = {
            iconHtml: renderToStaticMarkup(createElement(OpenAI)),
            iconColor: 'text-foreground',
        };
    } else {
        const brand = HARNESS_BRANDS[slug as HarnessSlug];
        // object-fit:contain preserves each mark's aspect ratio — SerializedIcon
        // forces the <img> to fill a square box, which would otherwise squish
        // non-square marks like clawd.svg (294x224). A per-mark inset scale pads
        // full-bleed markers (e.g. opencode) in within the badge.
        const style = `object-fit:contain${brand?.inset ? `;transform:scale(${brand.inset})` : ''}`;
        result = brand
            ? {
                  iconHtml: `<img src="${brand.markSrc}" alt="${slug}" style="${style}" />`,
                  iconColor: '',
              }
            : { iconHtml: '', iconColor: '' };
    }
    _harnessIconCache.set(slug, result);
    return result;
}

const _harnessNodeIconCache = new Map<
    string,
    { iconHtml: string; iconColor: string; includesName: boolean }
>();

/** The larger "agent node" harness icon: a full wordmark (logo + name) where one
    exists, otherwise the brand mark with includesName=false so the caller renders
    the name as text alongside it. Claude Code and Codex are mark-only. */
export function getHarnessNodeIcon(slug: string): {
    iconHtml: string;
    iconColor: string;
    includesName: boolean;
} {
    const cached = _harnessNodeIconCache.get(slug);
    if (cached) return cached;
    const wordmark = HARNESS_BRANDS[slug as HarnessSlug]?.wordmarkSrc;
    const result = wordmark
        ? {
              iconHtml: `<img src="${wordmark}" alt="${slug}" style="object-fit:contain" />`,
              iconColor: '',
              includesName: true,
          }
        : { ...getHarnessIcon(slug), includesName: false };
    _harnessNodeIconCache.set(slug, result);
    return result;
}

/** Serialized metadata for many node types (skips unknown types). */
export function getSerializedNodeMetaMap(
    types: string[]
): Record<string, SerializedNodeMeta> {
    const out: Record<string, SerializedNodeMeta> = {};
    for (const type of types) {
        const meta = getSerializedNodeMeta(type);
        if (meta) out[type] = meta;
    }
    return out;
}

/** Every node type in the registry. */
export function listAllNodeTypes(): string[] {
    return AVAILABLE_NODES.map((node) => node.type);
}

// Display names for the synthetic per-harness agent icon entries below.
const HARNESS_AGENT_LABELS: Record<string, string> = {
    codex: 'Codex',
    'claude-code': 'Claude Code',
    opencode: 'OpenCode',
    openclaw: 'OpenClaw',
    hermes: 'Hermes',
};

/** Serialized icon metadata for EVERY node type (for the authed app's icon paths),
 *  plus synthetic `agent:<harness>` entries so light surfaces (the workflow-browser
 *  card pill) can show an agent node's actual harness mark without brand imports. */
export function getAllSerializedNodeMeta(): Record<string, SerializedNodeMeta> {
    const map = getSerializedNodeMetaMap(listAllNodeTypes());
    for (const [slug, label] of Object.entries(HARNESS_AGENT_LABELS)) {
        const icon = getHarnessIcon(slug);
        if (!icon.iconHtml) continue;
        map[`agent:${slug}`] = {
            type: `agent:${slug}`,
            label: `Agent (${label})`,
            description: '',
            iconColor: icon.iconColor,
            iconHtml: icon.iconHtml,
            dimensions: { width: 0, height: 0, iconSize: 0 },
        };
    }
    return map;
}

/** Node types that represent external integrations (automation + trigger nodes). */
export function listIntegrationNodeTypes(): string[] {
    return AVAILABLE_NODES.filter(
        (node) =>
            node.type.startsWith('automation-') ||
            node.type.startsWith('trigger-') ||
            // The unified form node absorbed trigger-form-input; keep its
            // integrations page (slug 'form-input') listed.
            node.type === 'interface-form'
    ).map((node) => node.type);
}

/** Operation count for an integration node, derived from its JSON schema. */
export function getNodeOperationCount(type: string): number {
    const schemaInfo = getSchemaInfo(type);
    if (!schemaInfo) return 0;
    if (schemaInfo.hasOptions) return schemaInfo.options.length;
    return 1; // single operation
}

/** Convert a node type to its URL slug ('automation-google-sheets' -> 'google-sheets'). */
export function typeToSlug(type: string): string {
    // The unified form node keeps the pre-merge trigger's indexed slug.
    if (type === 'interface-form') return 'form-input';
    return type.replace(/^(automation|trigger)-/, '');
}

/**
 * Whether a node type can act as an AI-agent tool provider (wired into an
 * agent's bottom/tools handle). Ground truth is the `x-agent-tool-provider`
 * marker the backend stamps onto qualifying schemas (see node_supports_op_tools);
 * reading it here avoids re-implementing the predicate on the frontend.
 */
export function isAgentToolProvider(type: string): boolean {
    const info = getSchemaInfo(type);
    return info?.rootSchema?.['x-agent-tool-provider'] === true;
}

/** The operation discriminator prop on a config schema (the `operation` field). */
interface OpDiscriminatorProp {
    const?: unknown;
    'x-is-trigger'?: unknown;
    'x-display-name'?: unknown;
    'x-category'?: unknown;
}

/**
 * All operation consts a node exposes, each tagged isTrigger from `x-is-trigger`.
 * Mirrors backend list_node_operations, handling both schema shapes:
 *  - multi-op: a `oneOf` discriminated on the `operation` field (one const per option)
 *  - single-op: a `$ref` config whose resolved schema carries `operation.const`
 * getNodeOperations() is unsuitable here because it returns a synthetic 'default'
 * value for the single-op case. Shared by the tool (non-trigger) + trigger views.
 */
function extractNodeOperations(
    type: string
): (ProviderToolOperation & { isTrigger: boolean })[] {
    const info = getSchemaInfo(type);
    if (!info) return [];

    const ops: (ProviderToolOperation & { isTrigger: boolean })[] = [];
    const push = (
        prop: OpDiscriminatorProp | null | undefined,
        fallbackDesc?: string
    ) => {
        const value = prop?.const;
        if (!value || typeof value !== 'string') return;
        const isTrigger = prop?.['x-is-trigger'] === true;
        const displayName = prop?.['x-display-name'];
        const category = prop?.['x-category'];
        ops.push({
            value,
            name:
                typeof displayName === 'string' && displayName
                    ? displayName
                    : formatOperationValue(value),
            description: fallbackDesc || '',
            category:
                typeof category === 'string' && category
                    ? category
                    : isTrigger
                      ? 'Triggers'
                      : 'General',
            isTrigger,
        });
    };

    if (info.hasOptions && info.hasDiscriminator) {
        const field = info.discriminator.fieldName;
        info.options.forEach((option) => {
            const resolved = option.$ref
                ? info.resolveRef(option.$ref)
                : option;
            const prop = field ? resolved?.properties?.[field] : null;
            push(prop, resolved?.description);
        });
    } else {
        const prop = info.resolvedConfigSchema?.properties?.operation;
        push(prop, info.resolvedConfigSchema?.description);
    }
    return ops;
}

const stripTriggerFlag = (
    o: ProviderToolOperation & { isTrigger: boolean }
): ProviderToolOperation => ({
    value: o.value,
    name: o.name,
    description: o.description,
    category: o.category,
});

/** The real (non-trigger) operation consts an op-tool provider exposes as agent
    tools — the values that go into `config.agent_tool_operations`. */
export function getProviderToolOperations(
    type: string
): ProviderToolOperation[] {
    return extractNodeOperations(type)
        .filter((o) => !o.isTrigger)
        .map(stripTriggerFlag);
}

/** The trigger operation consts (x-is-trigger) a node exposes — the ones that can
    fire an agent when the node is wired into its input. */
export function getNodeTriggerOperations(
    type: string
): ProviderToolOperation[] {
    return extractNodeOperations(type)
        .filter((o) => o.isTrigger)
        .map(stripTriggerFlag);
}

// Built-in trigger nodes offered in the agent builder. trigger-run is excluded:
// it's the manual run button (agents are runnable on demand without a node).
const BUILTIN_TRIGGER_TYPES = [
    'trigger-webhook',
    'trigger-cron',
    ...(inboundEmailDomain() ? ['trigger-email'] : []),
    'interface-form',
];
let _triggerOptionsCache: TriggerOption[] | null = null;

/** Every trigger selectable in the agent builder: the built-in triggers plus
    every integration node that exposes a trigger operation (its default op). */
export function listTriggerOptions(): TriggerOption[] {
    if (_triggerOptionsCache) return _triggerOptionsCache;
    const options: TriggerOption[] = [];

    for (const type of BUILTIN_TRIGGER_TYPES) {
        const meta = getSerializedNodeMeta(type);
        if (!meta) continue;
        options.push({
            type,
            slug: typeToSlug(type),
            label: meta.label,
            description: meta.description,
            iconColor: meta.iconColor,
            iconHtml: meta.iconHtml,
            operation: null,
            kind: 'builtin',
        });
    }

    const integration = AVAILABLE_NODES.filter((n) =>
        n.type.startsWith('automation-')
    )
        .map((n): TriggerOption | null => {
            const trigOps = getNodeTriggerOperations(n.type);
            if (trigOps.length === 0) return null;
            const meta = getSerializedNodeMeta(n.type);
            if (!meta) return null;
            return {
                type: n.type,
                slug: typeToSlug(n.type),
                label: meta.label,
                description: meta.description,
                iconColor: meta.iconColor,
                iconHtml: meta.iconHtml,
                operation: trigOps[0].value,
                operationLabel: trigOps[0].name,
                kind: 'integration' as const,
            };
        })
        .filter((x): x is TriggerOption => x !== null)
        .sort((a, b) => a.label.localeCompare(b.label));

    const result = [...options, ...integration];
    _triggerOptionsCache = result;
    return result;
}

/** Every integration node type that can be wired in as an agent tool provider. */
export function listAgentToolProviderTypes(): string[] {
    return AVAILABLE_NODES.map((n) => n.type).filter(
        (t) => t.startsWith('automation-') && isAgentToolProvider(t)
    );
}

/** Resolve a provider URL slug ('slack') to its provider node type, or null. */
export function resolveProviderTypeFromSlug(slug: string): string | null {
    const type = `automation-${slug}`;
    return isAgentToolProvider(type) ? type : null;
}

/** Serialized provider integration (meta + slug + exposable operations) for the
    /agents hub picker, connect pages, and scaffold builder. */
export function getProviderIntegration(
    type: string
): ProviderIntegration | null {
    const meta = getSerializedNodeMeta(type);
    if (!meta) return null;
    return {
        type,
        slug: typeToSlug(type),
        label: meta.label,
        description: meta.description,
        iconColor: meta.iconColor,
        iconHtml: meta.iconHtml,
        operations: getProviderToolOperations(type),
    };
}

/** All provider integrations, serialized for the client. */
export function listProviderIntegrations(): ProviderIntegration[] {
    return listAgentToolProviderTypes()
        .map(getProviderIntegration)
        .filter((x): x is ProviderIntegration => x !== null);
}

/** Resolve an integration URL slug to its node type, or null if unknown. */
export function resolveNodeTypeFromSlug(slug: string): string | null {
    // Pre-merge trigger slug: the unified form node kept the indexed URL.
    if (slug === 'form-input') return 'interface-form';
    const automationType = `automation-${slug}`;
    const triggerType = `trigger-${slug}`;
    const node = AVAILABLE_NODES.find(
        (n) =>
            n.type === automationType ||
            n.type === triggerType ||
            n.type === slug
    );
    return node?.type || null;
}

/** Whether a node type exists in the registry. */
export function nodeTypeExists(type: string): boolean {
    return AVAILABLE_NODES.some((n) => n.type === type);
}

function getTypeName(prop: Record<string, unknown>): string {
    if (prop.enum) return 'select';
    if (prop.type === 'array') return 'list';
    if (prop.type === 'object') return 'object';
    if (prop.type === 'boolean') return 'boolean';
    if (prop.type === 'integer' || prop.type === 'number') return 'number';
    return 'text';
}

function getOperationFields(
    nodeType: string,
    operationIndex: number
): FieldInfo[] {
    const extractedFields = getFieldsForOption(nodeType, operationIndex) || [];
    return extractedFields
        .filter((f) => f.key !== 'operation')
        .map((f) => ({
            key: f.key,
            title:
                f.prop.title ||
                f.key
                    .replace(/_/g, ' ')
                    .replace(/\b\w/g, (c: string) => c.toUpperCase()),
            description: f.prop.description || '',
            type: getTypeName(f.prop),
            required: f.required,
        }));
}

function formatOperationValue(value: string): string {
    return value
        .split('_')
        .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
        .join(' ');
}

/** Extract the operations (with fields) for an integration node from its schema. */
export function getNodeOperations(nodeType: string): OperationInfo[] {
    const schemaInfo = getSchemaInfo(nodeType);
    if (!schemaInfo) return [];

    const operations: OperationInfo[] = [];

    if (schemaInfo.hasOptions && schemaInfo.hasDiscriminator) {
        const resolveRef = createRefResolver(schemaInfo.rootSchema);

        schemaInfo.options.forEach((option, index) => {
            const resolved = option.$ref ? resolveRef(option.$ref) : option;
            if (!resolved) return;

            const discriminatorField = schemaInfo.discriminator.fieldName;
            const discriminatorProp = discriminatorField
                ? resolved.properties?.[discriminatorField]
                : null;
            const discriminatorValue = discriminatorProp?.const ?? null;
            // Trigger operations carry `x-is-trigger` and a null `x-category`;
            // surface them under a dedicated "Triggers" group.
            const isTrigger = discriminatorProp?.['x-is-trigger'] === true;
            const category: string = isTrigger
                ? 'Triggers'
                : discriminatorProp?.['x-category'] || 'General';

            let name = resolved.title || '';
            if (name) {
                name = name.replace(/Config$/, '');
                name = name.replace(/^[A-Z][a-z]+(?=[A-Z])/, '');
                name = name.replace(/([A-Z])/g, ' $1').trim();
            }

            const description = resolved.description || '';
            const fields = getOperationFields(nodeType, index);

            if (discriminatorValue || name) {
                operations.push({
                    name:
                        name || formatOperationValue(discriminatorValue || ''),
                    description,
                    value: discriminatorValue || '',
                    index,
                    fields,
                    category,
                });
            }
        });
    } else if (!schemaInfo.hasOptions) {
        const description =
            schemaInfo.resolvedConfigSchema?.description ||
            schemaInfo.rootSchema?.description ||
            '';
        const fields = getOperationFields(nodeType, 0);
        operations.push({
            name: 'Execute',
            description,
            value: 'default',
            index: 0,
            fields,
            category: 'General',
        });
    }

    return operations;
}
