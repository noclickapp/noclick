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
import { StripeNode } from './StripeNode';
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
import { GoogleAnalyticsNode } from './GoogleAnalyticsNode';
import { GoogleAdsNode } from './GoogleAdsNode';
import { GoogleBusinessProfileNode } from './GoogleBusinessProfileNode';
import { GoogleSearchConsoleNode } from './GoogleSearchConsoleNode';
import { HackerNewsNode } from './HackerNewsNode';
import { InstagramNode } from './InstagramNode';
import { InstantlyNode } from './InstantlyNode';
import { JiraNode } from './JiraNode';
import { PipedriveNode } from './PipedriveNode';
import { ResendNode } from './ResendNode';
import { PhantomBusterNode } from './PhantomBusterNode';
import { CalComNode } from './CalComNode';
import { GoogleMapsNode } from './GoogleMapsNode';
import { PerplexityNode } from './PerplexityNode';
import { VoyageNode } from './VoyageNode';
import { PineconeNode } from './PineconeNode';
import { QdrantNode } from './QdrantNode';
import { UpstashVectorNode } from './UpstashVectorNode';
import { WeaviateNode } from './WeaviateNode';
import { ChromaNode } from './ChromaNode';
import { MilvusNode } from './MilvusNode';
import { MongoDBNode } from './MongoDBNode';
import { ElasticsearchNode } from './ElasticsearchNode';
import { MailgunNode } from './MailgunNode';
import { GitLabNode } from './GitLabNode';
import { BoxNode } from './BoxNode';
import { ClickUpNode } from './ClickUpNode';
import { DevinNode } from './DevinNode';
import { AsanaNode } from './AsanaNode';
import { FirestoreNode } from './FirestoreNode';
import { GoogleCloudStorageNode } from './GoogleCloudStorageNode';
import { MondayNode } from './MondayNode';
import { ParallelNode } from './ParallelNode';
import { DatadogNode } from './DatadogNode';
import { LoopsNode } from './LoopsNode';
import { ExaNode } from './ExaNode';
import { ReductoNode } from './ReductoNode';
import { FalNode } from './FalNode';
import { BrandfetchNode } from './BrandfetchNode';
import { FindymailNode } from './FindymailNode';
import { BeehiivNode } from './BeehiivNode';
import { HexNode } from './HexNode';
import { ClickHouseNode } from './ClickHouseNode';
import { ExtendNode } from './ExtendNode';
import { FellowNode } from './FellowNode';
import { FathomNode } from './FathomNode';
import { SigmaNode } from './SigmaNode';
import { TrelloNode } from './TrelloNode';
import { FirecrawlNode } from './FirecrawlNode';
import { AttioNode } from './AttioNode';
import { IntercomNode } from './IntercomNode';
import { ZendeskNode } from './ZendeskNode';
import { ConfluenceNode } from './ConfluenceNode';
import { PagerDutyNode } from './PagerDutyNode';
import { GoogleMeetNode } from './GoogleMeetNode';
import { ExpensifyNode } from './ExpensifyNode';
import { FreshsalesNode } from './FreshsalesNode';
import { LaunchDarklyNode } from './LaunchDarklyNode';
import { AppSheetNode } from './AppSheetNode';
import { TableauNode } from './TableauNode';
import { AtlasAdminNode } from './AtlasAdminNode';
import { WebflowNode } from './WebflowNode';
import { PagespeedNode } from './PagespeedNode';
import { GoogleTranslateNode } from './GoogleTranslateNode';
import { BigQueryNode } from './BigQueryNode';
import { SnowflakeNode } from './SnowflakeNode';
import { DatabricksNode } from './DatabricksNode';
import { MicrosoftTeamsNode } from './MicrosoftTeamsNode';
import { GoHighLevelNode } from './GoHighLevelNode';
import { QuickBooksNode } from './QuickBooksNode';
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
import { AffinityNode } from './AffinityNode';
import { MailchimpNode } from './MailchimpNode';
import { SalesforceNode } from './SalesforceNode';
import { TypeformNode } from './TypeformNode';
import { SemrushNode } from './SemrushNode';
import { ServerlessFunctionNode } from './ServerlessFunctionNode';
import { ShopifyNode } from './ShopifyNode';
import { SlackNode } from './SlackNode';
import { SupabaseNode } from './SupabaseNode';
import { ToolNode } from './ToolNode';
import { MCPServerNode } from './MCPServerNode';
import { NoClickNode } from './NoClickNode';
import { AlarmNode } from './AlarmNode';
import { FilesystemNode } from './FilesystemNode';
import { TwilioNode } from './TwilioNode';
import { TikTokNode } from './TikTokNode';
import { TwitterNode } from './TwitterNode';
import { CloudflareNode } from './CloudflareNode';
import { RunTriggerNode } from './RunTriggerNode';
import { SubmitExternalFormNode } from './SubmitExternalFormNode';
import { WebhookTriggerNode } from './WebhookTriggerNode';
import { InboundEmailTriggerNode } from './InboundEmailTriggerNode';
import { SendEmailNode } from './SendEmailNode';
import { WhatsAppNode } from './WhatsAppNode';
import { ElevenLabsNode } from './ElevenLabsNode';
import { YouTubeNode } from './YouTubeNode';
import { FilterNode } from './FilterNode';
import { SplitOutNode } from './SplitOutNode';
import { ConditionalNode } from './ConditionalNode';
import { ApprovalNode } from './ApprovalNode';
import { LogNode } from './LogNode';
import { SwitchNode } from './SwitchNode';
import { MergeNode } from './MergeNode';
import { StateManagerNode } from './StateManagerNode';
import { SetupNode } from './SetupNode';
import { OnErrorNode } from './OnErrorNode';
import { SetVariableNode } from './SetVariableNode';
import {
    InterfaceFormNode,
    InterfaceImageNode,
    InterfaceAudioNode,
    InterfaceVideoNode,
    InterfaceFileNode,
    InterfaceDataframeNode,
    InterfaceHtmlReactNode,
    InterfaceFileUploadNode,
    InterfaceConfigFormNode,
} from './interface';
import { DUMMY_NODES } from './DummyNodes';
import type { NodeDefinition, NodeDimensions, NodeDisplayStrategy } from './types';
import { extractPathsFromData, validatePathDefault } from './strategyDefaults';

// All available nodes — built lazily.
//
// WHY: Several node files transitively re-import this module (e.g.
// InterfaceFormNode → InterfaceNode → BlockRenderer → FormBlock → FieldRenderer →
// SchedulesWidget → DroppableTextField → ReferenceAutocompleteContext → here).
// During an eager construction `[RunTriggerNode, …]`, accessing these variables while
// any of the chain is mid-eval throws TDZ. By wrapping the array in a Proxy that builds
// on first access, the module finishes evaluating without touching any variable; the
// eventual first read happens after all imports have settled.
let _availableCache: NodeDefinition[] | null = null;
function _buildAvailable(): NodeDefinition[] {
    return [
        RunTriggerNode,
        WebhookTriggerNode,
        InboundEmailTriggerNode,
        CronTriggerNode,
        FormInputNode,
        TelegramNode, GoogleSheetsNode, GoogleDriveNode, GmailNode, OutlookMailNode,
        ExcelNode, OneDriveNode, MicrosoftTodoNode, MicrosoftTeamsNode, WordNode, WordPressNode,
        HttpRequestNode, LinearNode, GithubRestNode, AirtableNode, StripeNode, ApifyNode,
        ApolloNode, BlueSkyNode, CanvaNode, DiscordNode, DropboxNode,
        GoogleCalendarNode, GoogleTasksNode, GoogleContactsNode, GoogleDocsNode,
        GoogleFormsNode, GoogleSlidesNode, GoogleAnalyticsNode, GoogleAdsNode,
        GoogleBusinessProfileNode, GoogleSearchConsoleNode, HackerNewsNode, InstagramNode, InstantlyNode,
        JiraNode, IntercomNode, LinkedInNode, NotionNode, PostgresNode, RedditNode, RSSNode, ExtendNode,
        RedisNode, SalesforceNode, AffinityNode, SemrushNode, ShopifyNode, SlackNode,
        SupabaseNode, TikTokNode, TwilioNode, TwitterNode, CloudflareNode,
        TypeformNode, WhatsAppNode, ElevenLabsNode, YouTubeNode, HubSpotNode,
        MailchimpNode, PipedriveNode, ResendNode, QuickBooksNode, BigQueryNode, GoHighLevelNode, ExpensifyNode, LaunchDarklyNode, WebflowNode, PhantomBusterNode, CalComNode, GoogleMapsNode, PerplexityNode, PineconeNode, QdrantNode, UpstashVectorNode, WeaviateNode, ChromaNode, MilvusNode, MongoDBNode, ElasticsearchNode, MailgunNode,
        GitLabNode, BoxNode, ClickUpNode, DevinNode, AsanaNode, FirestoreNode,
        GoogleCloudStorageNode, MondayNode, ParallelNode, DatadogNode, LoopsNode,
        ExaNode, ReductoNode, FalNode, BrandfetchNode, FindymailNode, BeehiivNode,
        HexNode, ClickHouseNode, FellowNode, FathomNode, SigmaNode, TrelloNode,
        FirecrawlNode, AttioNode, ZendeskNode, ConfluenceNode, PagerDutyNode, GoogleMeetNode, FreshsalesNode, AppSheetNode, TableauNode, AtlasAdminNode, PagespeedNode, SnowflakeNode, GoogleTranslateNode, VoyageNode, SendEmailNode, AIAgentNode, ToolNode, MCPServerNode,
        DatabricksNode,
        NoClickNode, AlarmNode, FilesystemNode, IterationNode, DelayNode, FilterNode,
        SplitOutNode,
        ConditionalNode, ApprovalNode, LogNode, SwitchNode, MergeNode, SubmitExternalFormNode,
        ServerlessFunctionNode, StateManagerNode, SetupNode, OnErrorNode,
        SetVariableNode, StickyNoteNode,
        InterfaceFormNode, InterfaceImageNode, InterfaceAudioNode, InterfaceVideoNode,
        InterfaceFileNode, InterfaceDataframeNode, InterfaceHtmlReactNode,
        InterfaceFileUploadNode, InterfaceConfigFormNode,
    ];
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

// SDK-based node types that use @noclick/sdk for communication, not edges.
// Derived from x-connectionless in backend-generated JSON schemas (single source of truth).
// Definition lives in ./connectionlessTypes so node component files can read it without
// transitively pulling the heavy registry (would create a circular dep on lazy load).
export { CONNECTIONLESS_TYPES } from './connectionlessTypes';

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

// Returns a complete display strategy for the given node type, merging the node's
// overrides (if any) on top of the defaults from ./strategyDefaults. Callers can
// always invoke `strategy.buildSuggestions(...)` / `strategy.validateReference(...)`
// without guarding — those methods are required on the returned strategy.
//
// For unknown node types or when `type` is undefined, returns the bare default
// strategy. This means an unknown node still gets sensible autocomplete (recursive
// path extraction from its output) instead of nothing.
export function getDisplayStrategy(type: string | undefined): NodeDisplayStrategy {
    const overrides = type
        ? AVAILABLE_NODES.find(n => n.type === type)?.displayStrategy
        : undefined;
    return {
        buildSuggestions: overrides?.buildSuggestions ?? extractPathsFromData,
        validateReference: overrides?.validateReference ?? validatePathDefault,
        buildSuggestionsFromConfig: overrides?.buildSuggestionsFromConfig,
        OutputPanelContent: overrides?.OutputPanelContent,
    };
}
