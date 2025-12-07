// Central node registry - single source of truth for all workflow nodes.
// Simply imports and lists all node definitions.
// To add a new node: create a new file exporting NodeDefinition, then import and add here.
//
// Performance: The registry automatically wraps all node components with React.memo
// using nodePropsAreEqual. Node files should export RAW components (not memoized).
// For custom memo behavior, set `memoCompare` in the node definition.

import { ComponentType, memo } from 'react';
import { NodeProps } from 'reactflow';
import { TelegramNode } from './TelegramNode';
import { nodePropsAreEqual } from './types';
import { GoogleSheetsNode } from './GoogleSheetsNode';
import { GoogleDriveNode } from './GoogleDriveNode';
import { GmailNode } from './GmailNode';
import { AIAgentNode } from './AIAgentNode';
import { StickyNoteNode } from './StickyNoteNode';
import { IterationNode } from './IterationNode';
import { HttpRequestNode } from './HttpRequestNode';
import { LinearNode } from './LinearNode';
import { GithubRestNode } from './GithubRestNode';
import { AirtableNode } from './AirtableNode';
import { SalesforceNode } from './SalesforceNode';
import { YouTubeNode } from './YouTubeNode';
import { LinkedInNode } from './LinkedInNode';
import { RedditNode } from './RedditNode';
import { GoogleCalendarNode } from './GoogleCalendarNode';
import { WebhookTriggerNode } from './WebhookTriggerNode';
import { CronTriggerNode } from './CronTriggerNode';
import { NotionNode } from './NotionNode';
import { ServerlessFunctionNode } from './ServerlessFunctionNode';
import { OutlookMailNode } from './OutlookMailNode';
import { ToolNode } from './ToolNode';
import { DiscordNode } from './DiscordNode';
import { ApolloNode } from './ApolloNode';
import { DUMMY_NODES } from './DummyNodes';
import type { NodeDefinition, NodeDimensions, NodeDisplayStrategy } from './types';

// All available nodes - just a list, no processing
export const AVAILABLE_NODES: NodeDefinition[] = [
    // Trigger nodes (workflow entry points)
    WebhookTriggerNode,
    CronTriggerNode,
    // Automation nodes
    TelegramNode,
    GoogleSheetsNode,
    GoogleDriveNode,
    GmailNode,
    OutlookMailNode,
    HttpRequestNode,
    LinearNode,
    GithubRestNode,
    AirtableNode,
    SalesforceNode,
    YouTubeNode,
    LinkedInNode,
    RedditNode,
    GoogleCalendarNode,
    NotionNode,
    DiscordNode,
    ApolloNode,
    AIAgentNode,
    ToolNode,
    IterationNode,
    ServerlessFunctionNode,
    StickyNoteNode,
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
//
// Performance: Automatically wraps all node components with React.memo using nodePropsAreEqual.
// This prevents unnecessary re-renders during drag operations. Node definitions can:
// - Export raw components (recommended) - will be auto-wrapped with memo + nodePropsAreEqual
// - Set `memoCompare` for custom comparison logic (e.g., AIAgentNode)
// - Set `skipAutoMemo: true` if component handles its own memoization
export function buildReactFlowNodeTypes(additionalTypes: Record<string, ComponentType<any>> = {}): Record<string, ComponentType<any>> {
    const types: Record<string, ComponentType<any>> = {};

    // Add all nodes from registry, auto-wrapping with memo for performance
    AVAILABLE_NODES.forEach((nodeDef) => {
        if (nodeDef.skipAutoMemo) {
            // Node handles its own memoization
            types[nodeDef.type] = nodeDef.component;
        } else {
            // Auto-wrap with memo using custom compare function or default nodePropsAreEqual
            const compareFunc = nodeDef.memoCompare || nodePropsAreEqual;
            types[nodeDef.type] = memo(nodeDef.component, compareFunc);
        }
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
