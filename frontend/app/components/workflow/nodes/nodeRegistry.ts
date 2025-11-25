// Central node registry - single source of truth for all workflow nodes.
// Simply imports and lists all node definitions.
// To add a new node: create a new file exporting NodeDefinition, then import and add here.

import { ComponentType } from 'react';
import { NodeProps } from 'reactflow';
import { TelegramNode } from './TelegramNode';
import { WhatsAppNode } from './WhatsAppNode';
import { GoogleNode } from './GoogleNode';
import { AIAgentNode } from './AIAgentNode';
import { NodeDefinition, NodeDimensions } from './types';

// All available nodes - just a list, no processing
export const AVAILABLE_NODES: NodeDefinition[] = [
    TelegramNode,
    WhatsAppNode,
    GoogleNode,
    AIAgentNode,
];

// Re-export types for convenience
export type { NodeDefinition, NodeDimensions, NodeOutputDisplayProps } from './types';

// Build ReactFlow nodeTypes mapping
// Merges registry nodes with any additional node types passed in
export function buildReactFlowNodeTypes(additionalTypes: Record<string, ComponentType<any>> = {}): Record<string, ComponentType<any>> {
    const types: Record<string, ComponentType<any>> = {
        ...additionalTypes
    };

    // Add all nodes from registry
    AVAILABLE_NODES.forEach((nodeDef) => {
        types[nodeDef.type] = nodeDef.component;
    });

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

// Helper to get output display component by node type
export function getOutputDisplayComponent(type: string): ComponentType<any> | undefined {
    const node = AVAILABLE_NODES.find(n => n.type === type);
    return node?.OutputDisplay;
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
