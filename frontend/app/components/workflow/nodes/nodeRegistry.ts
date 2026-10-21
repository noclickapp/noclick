// The eager node registry: every node definition, imported up front, in palette order (from the one list in
// ./nodeDefinitions). For the server's node catalog, the labs and surfaces that show every node at once. The
// canvas never imports it: it loads each type's definition as the type appears (./nodeDefinitions).

import { ComponentType } from 'react';
import { NodeProps } from '@xyflow/react';
import { LEGACY_NODE_TYPE_ALIASES } from '~/utils/nodeMeta';
import { getDefaultLabelFromType } from './base/NodeLabel';
import { NODE_DEFINITION_FILES, definitionIn, isOfferedNodeType } from './nodeDefinitions';
import { nodeTypeComponent } from './nodeTypeComponent';
import type { NodeDefinition, NodeDimensions, NodeDisplayStrategy } from './types';
import { displayStrategyOf } from './strategyDefaults';

const MODULES = import.meta.glob<Record<string, unknown>>(['./*Node.tsx', './interface/*Node.tsx'], { eager: true });

// All available nodes — built on first access, so this module finishes evaluating
// without reading a node module's exports: a node module whose imports lead back here
// would still be mid-eval (TDZ). The first read happens after all imports have settled.
let _availableCache: NodeDefinition[] | null = null;
function _buildAvailable(): NodeDefinition[] {
    return NODE_DEFINITION_FILES.map(([type, file]) => definitionIn(MODULES[`./${file}.tsx`], type));
}
export const AVAILABLE_NODES: NodeDefinition[] = new Proxy([] as NodeDefinition[], {
    get(_t, prop) {
        if (_availableCache === null) _availableCache = _buildAvailable();
        const v = (_availableCache as any)[prop];
        return typeof v === 'function' ? v.bind(_availableCache) : v;
    },
    has(_t, prop) {
        if (_availableCache === null) _availableCache = _buildAvailable();
        return prop in _availableCache;
    },
    ownKeys() {
        if (_availableCache === null) _availableCache = _buildAvailable();
        return Reflect.ownKeys(_availableCache);
    },
    getOwnPropertyDescriptor(_t, prop) {
        if (_availableCache === null) _availableCache = _buildAvailable();
        return Object.getOwnPropertyDescriptor(_availableCache, prop);
    },
});


// Re-export types for convenience
export type {
    NodeDefinition,
    NodeDimensions,
    NodeDisplayStrategy,
    OutputPanelContentProps,
    JsonValue,
    JsonObject,
    JsonArray,
    JsonPrimitive,
    ReferenceSuggestion,
} from './types';

// ReactFlow nodeTypes for every node (each wrapped and memoized by nodeTypeComponent), legacy types drawn by
// the node that replaced them, and `additionalTypes` taking priority (custom renderers with callbacks).
export function buildReactFlowNodeTypes(additionalTypes: Record<string, ComponentType<any>> = {}): Record<string, ComponentType<any>> {
    const types: Record<string, ComponentType<any>> = {};
    for (const definition of AVAILABLE_NODES) types[definition.type] = nodeTypeComponent(definition);
    for (const [legacy, current] of Object.entries(LEGACY_NODE_TYPE_ALIASES)) {
        if (types[current]) types[legacy] ??= types[current];
    }
    return Object.assign(types, additionalTypes);
}

/** The nodes offered for adding, in palette order. */
export function getSearchableNodes(): NodeDefinition[] {
    return AVAILABLE_NODES.filter((node) => isOfferedNodeType(node.type));
}

// Helper to get node component by type
export function getNodeComponent(type: string): ComponentType<NodeProps> | undefined {
    const node = AVAILABLE_NODES.find(n => n.type === type);
    return node?.component;
}

// Helper to get dimensions by node type
export function getDimensionsByType(type: string): NodeDimensions | undefined {
    const node = AVAILABLE_NODES.find(n => n.type === type);
    return node?.dimensions;
}

// Helper to get full metadata by type
export function getNodeMetadata(type: string): NodeDefinition | undefined {
    return AVAILABLE_NODES.find(n => n.type === type);
}

// Display name for a node type — the registry's authored label ('Schedule',
// 'GitHub', 'X'), which is what the node palette shows, falling back to the
// type-derived one for types with no registry entry. Use this wherever a node
// type is named to the user; the derived label alone reads wrong for ~a third
// of the catalog ('Trigger Cron', 'Github Rest', 'Whatsapp').
export function getNodeDisplayName(type: string): string {
    return getNodeMetadata(type)?.label || getDefaultLabelFromType(type) || type;
}

export { CONNECTIONLESS_TYPES } from '~/utils/nodeMeta';

// DEPRECATED: Use createWorkflowNode from ~/lib/applyNodeUpdate instead.
// createWorkflowNode enforces the correct data model (operation top-level, config nested).
// This function is kept only as a type reference — do not call it.
/** @deprecated Use createWorkflowNode from ~/lib/applyNodeUpdate */
export function createNode(
    _id: string,
    _type: string,
    _position: { x: number; y: number },
    _data: Record<string, any> = {}
): never {
    throw new Error('createNode is deprecated. Use createWorkflowNode from ~/lib/applyNodeUpdate instead.');
}

// A complete display strategy for the given node type: its overrides (if any) over the defaults, so callers can
// always invoke `strategy.buildSuggestions(...)` / `strategy.validateReference(...)` without guarding.
export function getDisplayStrategy(type: string | undefined): NodeDisplayStrategy {
    return displayStrategyOf(type ? getNodeMetadata(type) : undefined);
}
