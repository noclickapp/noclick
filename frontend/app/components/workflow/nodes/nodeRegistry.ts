// Central node registry - single source of truth for all workflow nodes.
// Simply imports and lists all node definitions.
// To add a new node: create a new file exporting NodeDefinition, then import and add here.
//
// Performance: The registry automatically wraps all node components with React.memo
// using nodePropsAreEqual. Node files should export RAW components (not memoized).
// For custom memo behavior, set `memoCompare` in the node definition.

import { ComponentType, memo } from 'react';
import { NodeProps } from '@xyflow/react';
import { withNodeWrapper } from './withNodeWrapper';
import { TelegramNode } from './TelegramNode';
import { nodePropsAreEqual } from './types';
import { GoogleSheetsNode } from './GoogleSheetsNode';
import { GoogleDriveNode } from './GoogleDriveNode';
import { GmailNode } from './GmailNode';
import { AIAgentNode } from './AIAgentNode';
import { StickyNoteNode } from './StickyNoteNode';
import { IterationNode } from './IterationNode';
import { DelayNode } from './DelayNode';
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
import { DropboxNode } from './DropboxNode';
import { FormInputNode } from './FormInputNode';
import { GoogleCalendarNode } from './GoogleCalendarNode';
import { GoogleTasksNode } from './GoogleTasksNode';
import { GoogleContactsNode } from './GoogleContactsNode';
import { GoogleDocsNode } from './GoogleDocsNode';
import { GoogleFormsNode } from './GoogleFormsNode';
import { GoogleSlidesNode } from './GoogleSlidesNode';
import { HackerNewsNode } from './HackerNewsNode';
import { InstagramNode } from './InstagramNode';
import { JiraNode } from './JiraNode';
import { LinkedInNode } from './LinkedInNode';
import { NotionNode } from './NotionNode';
import { OutlookMailNode } from './OutlookMailNode';
import { ExcelNode } from './ExcelNode';
import { OneDriveNode } from './OneDriveNode';
import { MicrosoftTodoNode } from './MicrosoftTodoNode';
import { WordNode } from './WordNode';
import { WordPressNode } from './WordPressNode';
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
import { MCPServerNode } from './MCPServerNode';
import { TwilioNode } from './TwilioNode';
import { TwitterNode } from './TwitterNode';
import { RunTriggerNode } from './RunTriggerNode';
import { WebhookTriggerNode } from './WebhookTriggerNode';
import { WhatsAppNode } from './WhatsAppNode';
import { ElevenLabsNode } from './ElevenLabsNode';
import { YouTubeNode } from './YouTubeNode';
import { CSVInputNode } from './CSVInputNode';
import { FilterNode } from './FilterNode';
import { ConditionalNode } from './ConditionalNode';
import { SwitchNode } from './SwitchNode';
import { MergeNode } from './MergeNode';
import { SplitNode } from './SplitNode';
import { StateManagerNode } from './StateManagerNode';
import {
    InterfaceFormNode,
    InterfaceMarkdownNode,
    InterfaceImageNode,
    InterfaceAudioNode,
    InterfaceVideoNode,
    InterfaceFileNode,
    InterfaceDataframeNode,
    InterfacePlotNode,
    InterfaceHtmlNode,
    InterfaceFileUploadNode,
    InterfaceChatbotNode,
    InterfaceConfigFormNode,
} from './interface';
import { DUMMY_NODES } from './DummyNodes';
import type { NodeDefinition, NodeDimensions, NodeDisplayStrategy } from './types';

// All available nodes - just a list, no processing
export const AVAILABLE_NODES: NodeDefinition[] = [
    // Trigger nodes (workflow entry points)
    RunTriggerNode,
    WebhookTriggerNode,
    CronTriggerNode,
    FormInputNode,
    // Automation nodes
    TelegramNode,
    GoogleSheetsNode,
    GoogleDriveNode,
    GmailNode,
    OutlookMailNode,
    ExcelNode,
    OneDriveNode,
    MicrosoftTodoNode,
    WordNode,
    WordPressNode,
    HttpRequestNode,
    LinearNode,
    GithubRestNode,
    AirtableNode,
    ApifyNode,
    ApolloNode,
    BlueSkyNode,
    CanvaNode,
    DiscordNode,
    DropboxNode,
    GoogleCalendarNode,
    GoogleTasksNode,
    GoogleContactsNode,
    GoogleDocsNode,
    GoogleFormsNode,
    GoogleSlidesNode,
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
    TwilioNode,
    TwitterNode,
    TypeformNode,
    WhatsAppNode,
    ElevenLabsNode,
    YouTubeNode,
    HubSpotNode,
    MailchimpNode,
    PerplexityNode,
    AIAgentNode,
    ToolNode,
    MCPServerNode,
    IterationNode,
    DelayNode,
    CSVInputNode,
    FilterNode,
    ConditionalNode,
    SwitchNode,
    MergeNode,
    SplitNode,
    ServerlessFunctionNode,
    StateManagerNode,
    StickyNoteNode,
    // Interface nodes (UI components for the workflow interface builder)
    InterfaceFormNode,
    InterfaceMarkdownNode,
    InterfaceImageNode,
    InterfaceAudioNode,
    InterfaceVideoNode,
    InterfaceFileNode,
    InterfaceDataframeNode,
    InterfacePlotNode,
    InterfaceHtmlNode,
    InterfaceFileUploadNode,
    InterfaceChatbotNode,
    InterfaceConfigFormNode,
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

    // Add all nodes from registry, auto-wrapping with node wrapper (border + label) + memo
    AVAILABLE_NODES.forEach((nodeDef) => {
        // Wrap with node wrapper (collaborative border + editable label)
        const wrapped = withNodeWrapper(nodeDef.component);

        if (nodeDef.skipAutoMemo) {
            // Node handles its own memoization
            types[nodeDef.type] = wrapped;
        } else {
            // Auto-wrap with memo using custom compare function or default nodePropsAreEqual
            const compareFunc = nodeDef.memoCompare || nodePropsAreEqual;
            types[nodeDef.type] = memo(wrapped, compareFunc);
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
