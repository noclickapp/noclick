// Central node registry - single source of truth for all workflow nodes.
// Simply imports and lists all node definitions.
// To add a new node: create a new file exporting NodeDefinition, then import and add here.
//
// Performance: The registry automatically wraps all node components with React.memo
// using nodePropsAreEqual. Node files should export RAW components (not memoized).
// For custom memo behavior, set `memoCompare` in the node definition.

import { ComponentType, memo } from 'react';
import { NodeProps } from 'reactflow';
import { withCollaborativeBorder } from './withCollaborativeBorder';
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
import { ApifyNode } from './ApifyNode';
import { ApolloNode } from './ApolloNode';
import { BlueSkyNode } from './BlueSkyNode';
import { CanvaNode } from './CanvaNode';
import { CronTriggerNode } from './CronTriggerNode';
import { DiscordNode } from './DiscordNode';
import { FormInputNode } from './FormInputNode';
import { GoogleCalendarNode } from './GoogleCalendarNode';
import { HackerNewsNode } from './HackerNewsNode';
import { InstagramNode } from './InstagramNode';
import { JiraNode } from './JiraNode';
import { LinkedInNode } from './LinkedInNode';
import { NotionNode } from './NotionNode';
import { OutlookMailNode } from './OutlookMailNode';
import { PostgresNode } from './PostgresNode';
import { RedditNode } from './RedditNode';
import { RedisNode } from './RedisNode';
import { RSSNode } from './RSSNode';
import { HubSpotNode } from './HubSpotNode';
import { MailchimpNode } from './MailchimpNode';
import { PerplexityNode } from './PerplexityNode';
import { SalesforceNode } from './SalesforceNode';
import { TypeformNode } from './TypeformNode';
import { SemrushNode } from './SemrushNode';
import { ServerlessFunctionNode } from './ServerlessFunctionNode';
import { ShopifyNode } from './ShopifyNode';
import { SlackNode } from './SlackNode';
import { SupabaseNode } from './SupabaseNode';
import { ToolNode } from './ToolNode';
import { TwitterNode } from './TwitterNode';
import { WebhookTriggerNode } from './WebhookTriggerNode';
import { YouTubeNode } from './YouTubeNode';
import { DUMMY_NODES } from './DummyNodes';
import type { NodeDefinition, NodeDimensions, NodeDisplayStrategy } from './types';

// All available nodes - just a list, no processing
export const AVAILABLE_NODES: NodeDefinition[] = [
    // Trigger nodes (workflow entry points)
    WebhookTriggerNode,
    CronTriggerNode,
    FormInputNode,
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
    ApifyNode,
    ApolloNode,
    BlueSkyNode,
    CanvaNode,
    DiscordNode,
    GoogleCalendarNode,
    HackerNewsNode,
    InstagramNode,
    JiraNode,
    LinkedInNode,
    NotionNode,
    PostgresNode,
    RedditNode,
    RSSNode,
    RedisNode,
    SalesforceNode,
    SemrushNode,
    ShopifyNode,
    SlackNode,
    SupabaseNode,
    TwitterNode,
    TypeformNode,
    YouTubeNode,
    HubSpotNode,
    MailchimpNode,
    PerplexityNode,
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

    // Add all nodes from registry, auto-wrapping with collaborative border + memo
    AVAILABLE_NODES.forEach((nodeDef) => {
        // First wrap with collaborative border support (shows selection by other users)
        const withBorder = withCollaborativeBorder(nodeDef.component);

        if (nodeDef.skipAutoMemo) {
            // Node handles its own memoization
            types[nodeDef.type] = withBorder;
        } else {
            // Auto-wrap with memo using custom compare function or default nodePropsAreEqual
            const compareFunc = nodeDef.memoCompare || nodePropsAreEqual;
            types[nodeDef.type] = memo(withBorder, compareFunc);
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
