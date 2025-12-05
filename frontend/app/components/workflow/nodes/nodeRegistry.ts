// Central node registry - single source of truth for all workflow nodes.
// Simply imports and lists all node definitions.
// To add a new node: create a new file exporting NodeDefinition, then import and add here.

import { ComponentType } from 'react';
import { NodeProps } from 'reactflow';
import { TelegramNode } from './TelegramNode';
import { GoogleSheetsNode } from './GoogleSheetsNode';
import { GmailNode } from './GmailNode';
import { AIAgentNode } from './AIAgentNode';
import { StickyNoteNode } from './StickyNoteNode';
import { IterationNode } from './IterationNode';
import { HttpRequestNode } from './HttpRequestNode';
import { LinearNode } from './LinearNode';
import { DUMMY_NODES } from './DummyNodes';
import type { NodeDefinition, NodeDimensions, NodeDisplayStrategy } from './types';

// All available nodes - just a list, no processing
export const AVAILABLE_NODES: NodeDefinition[] = [
    TelegramNode,
    GoogleSheetsNode,
    GmailNode,
    HttpRequestNode,
    LinearNode,
    AIAgentNode,
    IterationNode,
    StickyNoteNode,
    ...DUMMY_NODES,
];

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

// Build ReactFlow nodeTypes mapping
// Merges registry nodes with any additional node types passed in
// additionalTypes take priority over registry nodes (allows custom renderers with callbacks)
export function buildReactFlowNodeTypes(additionalTypes: Record<string, ComponentType<any>> = {}): Record<string, ComponentType<any>> {
    const types: Record<string, ComponentType<any>> = {};

    // Add all nodes from registry first
    AVAILABLE_NODES.forEach((nodeDef) => {
        types[nodeDef.type] = nodeDef.component;
    });

    // Override with additionalTypes (custom renderers take priority)
    Object.assign(types, additionalTypes);

    return types;
}

// Helper function to get all searchable nodes
export function getSearchableNodes(): NodeDefinition[] {
    return AVAILABLE_NODES;
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

// Helper to create a node with minimal boilerplate
// Pulls Icon and iconColor from registry, only requires node-specific data
export function createNode(
    id: string,
    type: string,
    position: { x: number; y: number },
    data: Record<string, any> = {}
): any {
    return {
        id,
        type,
        position,
        data,
    };
}

// Helper to get display strategy by node type
// Returns undefined if node has no custom strategy (use default behavior)
export function getDisplayStrategy(type: string): NodeDisplayStrategy | undefined {
    const node = AVAILABLE_NODES.find(n => n.type === type);
    return node?.displayStrategy;
}
