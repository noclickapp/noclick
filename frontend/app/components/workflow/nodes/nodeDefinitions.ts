// Every node type the canvas draws, with the module that defines it, in palette order: the one list of node
// definitions. The canvas loads a type's module as the type first appears (the open workflow's, then one added
// from the palette, the builder or a collaborator), so it never carries every node's component; the eager
// registry (nodeRegistry.ts: the server's catalog, the labs) is built from the same list. Reads are synchronous
// over what has loaded, behind useNodeDefinitions in a component or `await loadNodeDefinitions(types)`.
import { inboundEmailDomain } from '~/lib/inboundEmail';
import { createLazyTypeStore, type LazyTypeStore } from '~/lib/lazyTypeStore';
import { getNodeIconMeta } from '~/lib/nodeIconRegistry';
import { resolveNodeType } from '~/utils/nodeMeta';
import { getDefaultLabelFromType } from './base/NodeLabel';
import { displayStrategyOf } from './strategyDefaults';
import type { NodeDefinition, NodeDimensions, NodeDisplayStrategy } from './types';

type DefinitionModule = Record<string, unknown>;

/** [type, its module under nodes/ without the extension], in palette order. */
export const NODE_DEFINITION_FILES: ReadonlyArray<readonly [type: string, file: string]> = [
    ['trigger-run', 'RunTriggerNode'],
    ['trigger-webhook', 'WebhookTriggerNode'],
    ['trigger-email', 'InboundEmailTriggerNode'],
    ['trigger-cron', 'CronTriggerNode'],
    ['interface-form', 'interface/InterfaceFormNode'],
    ['automation-telegram', 'TelegramNode'],
    ['automation-google-sheets', 'GoogleSheetsNode'],
    ['automation-google-drive', 'GoogleDriveNode'],
    ['automation-gmail', 'GmailNode'],
    ['automation-outlook', 'OutlookMailNode'],
    ['automation-excel', 'ExcelNode'],
    ['automation-onedrive', 'OneDriveNode'],
    ['automation-microsoft-todo', 'MicrosoftTodoNode'],
    ['automation-microsoft-teams', 'MicrosoftTeamsNode'],
    ['automation-word', 'WordNode'],
    ['automation-wordpress', 'WordPressNode'],
    ['automation-http-request', 'HttpRequestNode'],
    ['automation-linear', 'LinearNode'],
    ['automation-github-rest', 'GithubRestNode'],
    ['automation-airtable', 'AirtableNode'],
    ['automation-stripe', 'StripeNode'],
    ['automation-apify', 'ApifyNode'],
    ['automation-apollo', 'ApolloNode'],
    ['automation-bluesky', 'BlueSkyNode'],
    ['automation-canva', 'CanvaNode'],
    ['automation-discord', 'DiscordNode'],
    ['automation-dropbox', 'DropboxNode'],
    ['automation-google-calendar', 'GoogleCalendarNode'],
    ['automation-google-tasks', 'GoogleTasksNode'],
    ['automation-google-contacts', 'GoogleContactsNode'],
    ['automation-google-docs', 'GoogleDocsNode'],
    ['automation-google-forms', 'GoogleFormsNode'],
    ['automation-google-slides', 'GoogleSlidesNode'],
    ['automation-google-analytics', 'GoogleAnalyticsNode'],
    ['automation-google-ads', 'GoogleAdsNode'],
    ['automation-google-business-profile', 'GoogleBusinessProfileNode'],
    ['automation-google-search-console', 'GoogleSearchConsoleNode'],
    ['automation-hackernews', 'HackerNewsNode'],
    ['automation-instagram', 'InstagramNode'],
    ['automation-facebook', 'FacebookNode'],
    ['automation-instantly', 'InstantlyNode'],
    ['automation-jira', 'JiraNode'],
    ['automation-intercom', 'IntercomNode'],
    ['automation-linkedin', 'LinkedInNode'],
    ['automation-notion', 'NotionNode'],
    ['automation-postgres', 'PostgresNode'],
    ['automation-reddit', 'RedditNode'],
    ['automation-rss', 'RSSNode'],
    ['automation-extend', 'ExtendNode'],
    ['automation-redis', 'RedisNode'],
    ['automation-salesforce', 'SalesforceNode'],
    ['automation-affinity', 'AffinityNode'],
    ['automation-nocodb', 'NocoDBNode'],
    ['automation-basedash', 'BasedashNode'],
    ['automation-semrush', 'SemrushNode'],
    ['automation-shopify', 'ShopifyNode'],
    ['automation-slack', 'SlackNode'],
    ['automation-supabase', 'SupabaseNode'],
    ['automation-tiktok', 'TikTokNode'],
    ['automation-twilio', 'TwilioNode'],
    ['automation-phone', 'PhoneNode'],
    ['automation-twitter', 'TwitterNode'],
    ['automation-cloudflare', 'CloudflareNode'],
    ['automation-typeform', 'TypeformNode'],
    ['automation-whatsapp', 'WhatsAppNode'],
    ['automation-elevenlabs', 'ElevenLabsNode'],
    ['automation-youtube', 'YouTubeNode'],
    ['automation-hubspot', 'HubSpotNode'],
    ['automation-mailchimp', 'MailchimpNode'],
    ['automation-pipedrive', 'PipedriveNode'],
    ['automation-resend', 'ResendNode'],
    ['automation-dv360', 'DV360Node'],
    ['automation-quickbooks', 'QuickBooksNode'],
    ['automation-threads', 'ThreadsNode'],
    ['automation-meta', 'MetaNode'],
    ['automation-bigquery', 'BigQueryNode'],
    ['automation-gohighlevel', 'GoHighLevelNode'],
    ['automation-expensify', 'ExpensifyNode'],
    ['automation-launchdarkly', 'LaunchDarklyNode'],
    ['automation-webflow', 'WebflowNode'],
    ['automation-connecteam', 'ConnecteamNode'],
    ['automation-phantombuster', 'PhantomBusterNode'],
    ['automation-cal-com', 'CalComNode'],
    ['automation-calendly', 'CalendlyNode'],
    ['automation-honeycomb', 'HoneycombNode'],
    ['automation-sentry', 'SentryNode'],
    ['automation-google-maps', 'GoogleMapsNode'],
    ['automation-perplexity', 'PerplexityNode'],
    ['automation-posthog', 'PostHogNode'],
    ['automation-pinecone', 'PineconeNode'],
    ['automation-qdrant', 'QdrantNode'],
    ['automation-upstash-vector', 'UpstashVectorNode'],
    ['automation-weaviate', 'WeaviateNode'],
    ['automation-chroma', 'ChromaNode'],
    ['automation-milvus', 'MilvusNode'],
    ['automation-mongodb', 'MongoDBNode'],
    ['automation-elasticsearch', 'ElasticsearchNode'],
    ['automation-mailgun', 'MailgunNode'],
    ['automation-gitlab', 'GitLabNode'],
    ['automation-box', 'BoxNode'],
    ['automation-clickup', 'ClickUpNode'],
    ['automation-devin', 'DevinNode'],
    ['automation-asana', 'AsanaNode'],
    ['automation-firestore', 'FirestoreNode'],
    ['automation-google-cloud-storage', 'GoogleCloudStorageNode'],
    ['automation-monday', 'MondayNode'],
    ['automation-parallel', 'ParallelNode'],
    ['automation-datadog', 'DatadogNode'],
    ['automation-loops', 'LoopsNode'],
    ['automation-exa', 'ExaNode'],
    ['automation-reducto', 'ReductoNode'],
    ['automation-fal', 'FalNode'],
    ['automation-brandfetch', 'BrandfetchNode'],
    ['automation-recurly', 'RecurlyNode'],
    ['automation-findymail', 'FindymailNode'],
    ['automation-beehiiv', 'BeehiivNode'],
    ['automation-hex', 'HexNode'],
    ['automation-clickhouse', 'ClickHouseNode'],
    ['automation-fellow', 'FellowNode'],
    ['automation-fathom', 'FathomNode'],
    ['automation-sigma', 'SigmaNode'],
    ['automation-trello', 'TrelloNode'],
    ['automation-firecrawl', 'FirecrawlNode'],
    ['automation-attio', 'AttioNode'],
    ['automation-zendesk', 'ZendeskNode'],
    ['automation-confluence', 'ConfluenceNode'],
    ['automation-pagerduty', 'PagerDutyNode'],
    ['automation-google-meet', 'GoogleMeetNode'],
    ['automation-freshsales', 'FreshsalesNode'],
    ['automation-appsheet', 'AppSheetNode'],
    ['automation-tableau', 'TableauNode'],
    ['automation-atlas-admin', 'AtlasAdminNode'],
    ['automation-pagespeed', 'PagespeedNode'],
    ['automation-snowflake', 'SnowflakeNode'],
    ['automation-google-translate', 'GoogleTranslateNode'],
    ['automation-voyage', 'VoyageNode'],
    ['automation-send-email', 'SendEmailNode'],
    ['agent', 'AIAgentNode'],
    ['tool', 'ToolNode'],
    ['mcp-server', 'MCPServerNode'],
    ['automation-databricks', 'DatabricksNode'],
    ['automation-zoom', 'ZoomNode'],
    ['automation-onelake', 'OneLakeNode'],
    ['automation-bamboohr', 'BambooHRNode'],
    ['automation-klaviyo', 'KlaviyoNode'],
    ['noclick', 'NoClickNode'],
    ['alarm', 'AlarmNode'],
    ['filesystem', 'FilesystemNode'],
    ['iteration', 'IterationNode'],
    ['delay', 'DelayNode'],
    ['filter', 'FilterNode'],
    ['split-out', 'SplitOutNode'],
    ['conditional', 'ConditionalNode'],
    ['approval', 'ApprovalNode'],
    ['log', 'LogNode'],
    ['switch', 'SwitchNode'],
    ['merge', 'MergeNode'],
    ['automation-submit-external-form', 'SubmitExternalFormNode'],
    ['automation-serverless-function', 'ServerlessFunctionNode'],
    ['state-manager', 'StateManagerNode'],
    ['on-error', 'OnErrorNode'],
    ['set-variable', 'SetVariableNode'],
    ['stickyNote', 'StickyNoteNode'],
    ['interface-file', 'interface/InterfaceFileNode'],
    ['interface-dataframe', 'interface/InterfaceDataframeNode'],
    ['interface-html-react', 'interface/InterfaceHtmlReactNode'],
    ['interface-file-upload', 'interface/InterfaceFileUploadNode'],
];

/** Every node type the canvas draws, in palette order. */
export const NODE_DEFINITION_TYPES: readonly string[] = NODE_DEFINITION_FILES.map(([type]) => type);

const FILE_BY_TYPE = new Map(NODE_DEFINITION_FILES);
// One lazy chunk per node module.
const MODULES = import.meta.glob<DefinitionModule>(['./*Node.tsx', './interface/*Node.tsx']);

/** The definition of `type` among a node module's exports. */
export function definitionIn(module: DefinitionModule, type: string): NodeDefinition {
    for (const value of Object.values(module)) {
        if (value && typeof value === 'object' && (value as NodeDefinition).type === type) return value as NodeDefinition;
    }
    throw new Error(`No NodeDefinition of type ${type} in its module`);
}

/** The definitions, loaded per node type (useNodeDefinitions reads it). */
export const nodeDefinitionStore: LazyTypeStore<NodeDefinition> = createLazyTypeStore((type) => {
    const file = FILE_BY_TYPE.get(type);
    return file ? () => MODULES[`./${file}.tsx`]().then((module) => definitionIn(module, type)) : undefined;
});

/** A type's definition once loaded (a legacy type resolves to the node that draws it). */
export function getNodeDefinition(type: string | null | undefined): NodeDefinition | undefined {
    return type ? nodeDefinitionStore.values[resolveNodeType(type)] : undefined;
}

/** Loads the listed types' definitions (each once). */
export function loadNodeDefinitions(types: Iterable<string | null | undefined>): Promise<void> {
    return nodeDefinitionStore.load(types);
}

/** Whether a new node of the type is offered: drawing an imported inbound-email trigger stays possible, but a
 *  new one waits until this installation has a mail domain of its own. */
export function isOfferedNodeType(type: string): boolean {
    return type !== 'trigger-email' || !!inboundEmailDomain();
}

/** The nodes offered for adding, in palette order, once every definition has loaded. */
export function offeredNodeDefinitions(): NodeDefinition[] {
    return NODE_DEFINITION_TYPES.filter(isOfferedNodeType).flatMap((type) => getNodeDefinition(type) ?? []);
}

/** A node type's name for people: its definition's label, the catalog's (served with the dashboard) for one not
 *  loaded, else the type's own words. */
export function nodeDisplayName(type: string): string {
    return getNodeDefinition(type)?.label || getNodeIconMeta(type)?.label || getDefaultLabelFromType(type) || type;
}

/** A node type's canvas size: its definition's, or the catalog's for one not loaded. */
export function nodeDimensions(type: string): NodeDimensions | undefined {
    return getNodeDefinition(type)?.dimensions ?? getNodeIconMeta(type)?.dimensions;
}

/** A loaded node's display strategy (the defaults until its definition loads). */
export function getDisplayStrategy(type: string | undefined): NodeDisplayStrategy {
    return displayStrategyOf(getNodeDefinition(type));
}
