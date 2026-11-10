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
const LEGACY_NODE_DEFINITION_FILES: ReadonlyArray<readonly [type: string, file: string]> = [
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
    ['automation-microsoft-teams', 'MicrosoftTeamsNode'],
    ['automation-http-request', 'HttpRequestNode'],
    ['automation-linear', 'LinearNode'],
    ['automation-github-rest', 'GithubRestNode'],
    ['automation-stripe', 'StripeNode'],
    ['automation-discord', 'DiscordNode'],
    ['automation-google-calendar', 'GoogleCalendarNode'],
    ['automation-google-forms', 'GoogleFormsNode'],
    ['automation-instagram', 'InstagramNode'],
    ['automation-facebook', 'FacebookNode'],
    ['automation-instantly', 'InstantlyNode'],
    ['automation-jira', 'JiraNode'],
    ['automation-intercom', 'IntercomNode'],
    ['automation-notion', 'NotionNode'],
    ['automation-extend', 'ExtendNode'],
    ['automation-redis', 'RedisNode'],
    ['automation-salesforce', 'SalesforceNode'],
    ['automation-shopify', 'ShopifyNode'],
    ['automation-slack', 'SlackNode'],
    ['automation-twilio', 'TwilioNode'],
    ['automation-phone', 'PhoneNode'],
    ['automation-cloudflare', 'CloudflareNode'],
    ['automation-typeform', 'TypeformNode'],
    ['automation-whatsapp', 'WhatsAppNode'],
    ['automation-hubspot', 'HubSpotNode'],
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
    ['automation-phantombuster', 'PhantomBusterNode'],
    ['automation-cal-com', 'CalComNode'],
    ['automation-calendly', 'CalendlyNode'],
    ['automation-honeycomb', 'HoneycombNode'],
    ['automation-sentry', 'SentryNode'],
    ['automation-perplexity', 'PerplexityNode'],
    ['automation-posthog', 'PostHogNode'],
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
    ['automation-snowflake', 'SnowflakeNode'],
    ['automation-google-translate', 'GoogleTranslateNode'],
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
    ['automation-table', 'TableNode'],
    ['state-manager', 'StateManagerNode'],
    ['on-error', 'OnErrorNode'],
    ['set-variable', 'SetVariableNode'],
    ['stickyNote', 'StickyNoteNode'],
    ['interface-file', 'interface/InterfaceFileNode'],
    ['interface-dataframe', 'interface/InterfaceDataframeNode'],
    ['interface-html-react', 'interface/InterfaceHtmlReactNode'],
    ['interface-file-upload', 'interface/InterfaceFileUploadNode'],
];

// Filenames are the contract: integrations/<slug>.tsx declares automation-<slug>.
// Glob keys are synchronous; the component modules stay lazy.
const INTEGRATION_MODULES = import.meta.glob<DefinitionModule>('./integrations/*.tsx');
const integrationFiles = Object.keys(INTEGRATION_MODULES).sort().map((path) => {
    const slug = path.slice('./integrations/'.length, -'.tsx'.length);
    if (LEGACY_NODE_DEFINITION_FILES.some(([type]) => type === `automation-${slug}`)) {
        throw new Error(`Duplicate node definition: automation-${slug}`);
    }
    return [`automation-${slug}`, `integrations/${slug}`] as const;
});
export const NODE_DEFINITION_FILES = [...LEGACY_NODE_DEFINITION_FILES, ...integrationFiles];

/** Every node type the canvas draws, in palette order. */
export const NODE_DEFINITION_TYPES: readonly string[] = NODE_DEFINITION_FILES.map(([type]) => type);

const FILE_BY_TYPE = new Map(NODE_DEFINITION_FILES);
// One lazy chunk per node module.
const MODULES = import.meta.glob<DefinitionModule>(['./*Node.tsx', './interface/*Node.tsx', './integrations/*.tsx']);

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
