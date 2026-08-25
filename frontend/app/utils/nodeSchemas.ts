/**
 * Centralized schema registry for workflow nodes.
 * Single source of truth for node JSON schemas used by NodeConfig (UI) and execution filtering.
 */

// Import credential type mapping
// From the leaf, NOT credentialTypes: that module imports getNodeCredentialInfo
// from this one, and the resulting cycle made module-evaluation order load-bearing
// — any new import edge into the pair could 500 Vite SSR. This file now has no
// non-JSON imports at all.
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';

// Import JSON schemas
import telegramSchema from '~/schemas/nodes/telegram.json';
import agentSchema from '~/schemas/nodes/agent.json';
import googleSheetsSchema from '~/schemas/nodes/google-sheets.json';
import googleDriveSchema from '~/schemas/nodes/google-drive.json';
import gmailSchema from '~/schemas/nodes/gmail.json';
import iterationSchema from '~/schemas/nodes/iteration.json';
import delaySchema from '~/schemas/nodes/delay.json';
import httpRequestSchema from '~/schemas/nodes/http-request.json';
import linearSchema from '~/schemas/nodes/linear.json';
import githubRestSchema from '~/schemas/nodes/github-rest.json';
import airtableSchema from '~/schemas/nodes/airtable.json';
import stripeSchema from '~/schemas/nodes/stripe.json';
import apifySchema from '~/schemas/nodes/apify.json';
import salesforceSchema from '~/schemas/nodes/salesforce.json';
import youtubeSchema from '~/schemas/nodes/youtube.json';
import linkedinSchema from '~/schemas/nodes/linkedin.json';
import redditSchema from '~/schemas/nodes/reddit.json';
import webhookTriggerSchema from '~/schemas/nodes/trigger-webhook.json';
import inboundEmailTriggerSchema from '~/schemas/nodes/trigger-email.json';
import sendEmailSchema from '~/schemas/nodes/send-email.json';
import cronTriggerSchema from '~/schemas/nodes/trigger-cron.json';
import serverlessFunctionSchema from '~/schemas/nodes/serverless-function.json';
import outlookSchema from '~/schemas/nodes/outlook.json';
import excelSchema from '~/schemas/nodes/excel.json';
import onedriveSchema from '~/schemas/nodes/onedrive.json';
import microsoftTodoSchema from '~/schemas/nodes/microsoft-todo.json';
import wordSchema from '~/schemas/nodes/word.json';
import googleCalendarSchema from '~/schemas/nodes/google-calendar.json';
import notionSchema from '~/schemas/nodes/notion.json';
import toolSchema from '~/schemas/nodes/tool.json';
import mcpServerSchema from '~/schemas/nodes/mcp-server.json';
import discordSchema from '~/schemas/nodes/discord.json';
import apolloSchema from '~/schemas/nodes/apollo.json';
import instagramSchema from '~/schemas/nodes/instagram.json';
import facebookSchema from '~/schemas/nodes/facebook.json';
import instantlySchema from '~/schemas/nodes/instantly.json';
import pipedriveSchema from '~/schemas/nodes/pipedrive.json';
import resendSchema from '~/schemas/nodes/resend.json';
import threadsSchema from '~/schemas/nodes/threads.json';
import metaSchema from '~/schemas/nodes/meta.json';
import phantombusterSchema from '~/schemas/nodes/phantombuster.json';
import pineconeSchema from '~/schemas/nodes/pinecone.json';
import calComSchema from '~/schemas/nodes/cal-com.json';
import calendlySchema from '~/schemas/nodes/calendly.json';
import honeycombSchema from '~/schemas/nodes/honeycomb.json';
import sentrySchema from '~/schemas/nodes/sentry.json';
import googleMapsSchema from '~/schemas/nodes/google-maps.json';
import perplexitySchema from '~/schemas/nodes/perplexity.json';
import posthogSchema from '~/schemas/nodes/posthog.json';
import voyageSchema from '~/schemas/nodes/voyage.json';
import qdrantSchema from '~/schemas/nodes/qdrant.json';
import upstashVectorSchema from '~/schemas/nodes/upstash-vector.json';
import weaviateSchema from '~/schemas/nodes/weaviate.json';
import chromaSchema from '~/schemas/nodes/chroma.json';
import milvusSchema from '~/schemas/nodes/milvus.json';
import mongodbSchema from '~/schemas/nodes/mongodb.json';
import elasticsearchSchema from '~/schemas/nodes/elasticsearch.json';
import mailgunSchema from '~/schemas/nodes/mailgun.json';
import gitlabSchema from '~/schemas/nodes/gitlab.json';
import boxSchema from '~/schemas/nodes/box.json';
import clickupSchema from '~/schemas/nodes/clickup.json';
import devinSchema from '~/schemas/nodes/devin.json';
import asanaSchema from '~/schemas/nodes/asana.json';
import firestoreSchema from '~/schemas/nodes/firestore.json';
import googleCloudStorageSchema from '~/schemas/nodes/google-cloud-storage.json';
import mondaySchema from '~/schemas/nodes/monday.json';
import parallelSchema from '~/schemas/nodes/parallel.json';
import datadogSchema from '~/schemas/nodes/datadog.json';
import loopsSchema from '~/schemas/nodes/loops.json';
import exaSchema from '~/schemas/nodes/exa.json';
import reductoSchema from '~/schemas/nodes/reducto.json';
import falSchema from '~/schemas/nodes/fal.json';
import brandfetchSchema from '~/schemas/nodes/brandfetch.json';
import findymailSchema from '~/schemas/nodes/findymail.json';
import beehiivSchema from '~/schemas/nodes/beehiiv.json';
import hexSchema from '~/schemas/nodes/hex.json';
import clickhouseSchema from '~/schemas/nodes/clickhouse.json';
import extendSchema from '~/schemas/nodes/extend.json';
import fellowSchema from '~/schemas/nodes/fellow.json';
import fathomSchema from '~/schemas/nodes/fathom.json';
import sigmaSchema from '~/schemas/nodes/sigma.json';
import trelloSchema from '~/schemas/nodes/trello.json';
import firecrawlSchema from '~/schemas/nodes/firecrawl.json';
import attioSchema from '~/schemas/nodes/attio.json';
import intercomSchema from '~/schemas/nodes/intercom.json';
import zendeskSchema from '~/schemas/nodes/zendesk.json';
import confluenceSchema from '~/schemas/nodes/confluence.json';
import pagerdutySchema from '~/schemas/nodes/pagerduty.json';
import googleMeetSchema from '~/schemas/nodes/google-meet.json';
import expensifySchema from '~/schemas/nodes/expensify.json';
import freshsalesSchema from '~/schemas/nodes/freshsales.json';
import launchdarklySchema from '~/schemas/nodes/launchdarkly.json';
import appsheetSchema from '~/schemas/nodes/appsheet.json';
import tableauSchema from '~/schemas/nodes/tableau.json';
import atlasAdminSchema from '~/schemas/nodes/atlas-admin.json';
import webflowSchema from '~/schemas/nodes/webflow.json';
import pagespeedSchema from '~/schemas/nodes/pagespeed.json';
import googleTranslateSchema from '~/schemas/nodes/google-translate.json';
import bigquerySchema from '~/schemas/nodes/bigquery.json';
import snowflakeSchema from '~/schemas/nodes/snowflake.json';
import databricksSchema from '~/schemas/nodes/databricks.json';
import microsoftTeamsSchema from '~/schemas/nodes/microsoft-teams.json';
import gohighlevelSchema from '~/schemas/nodes/gohighlevel.json';
import quickbooksSchema from '~/schemas/nodes/quickbooks.json';
import zoomSchema from '~/schemas/nodes/zoom.json';
import onelakeSchema from '~/schemas/nodes/onelake.json';
import bamboohrSchema from '~/schemas/nodes/bamboohr.json';
import klaviyoSchema from '~/schemas/nodes/klaviyo.json';
import dv360Schema from '~/schemas/nodes/dv360.json';
import tiktokSchema from '~/schemas/nodes/tiktok.json';
import twitterSchema from '~/schemas/nodes/twitter.json';
import cloudflareSchema from '~/schemas/nodes/cloudflare.json';
import shopifySchema from '~/schemas/nodes/shopify.json';
import slackSchema from '~/schemas/nodes/slack.json';
import postgresSchema from '~/schemas/nodes/postgres.json';
import blueskySchema from '~/schemas/nodes/bluesky.json';
import canvaSchema from '~/schemas/nodes/canva.json';
import hackernewsSchema from '~/schemas/nodes/hackernews.json';
import redisSchema from '~/schemas/nodes/redis.json';
import rssSchema from '~/schemas/nodes/rss.json';
import hubspotSchema from '~/schemas/nodes/hubspot.json';
import affinitySchema from '~/schemas/nodes/affinity.json';
import basedashSchema from '~/schemas/nodes/basedash.json';
import jiraSchema from '~/schemas/nodes/jira.json';
import semrushSchema from '~/schemas/nodes/semrush.json';
import mailchimpSchema from '~/schemas/nodes/mailchimp.json';
import typeformSchema from '~/schemas/nodes/typeform.json';
import supabaseSchema from '~/schemas/nodes/supabase.json';
import twilioSchema from '~/schemas/nodes/twilio.json';
import whatsappSchema from '~/schemas/nodes/whatsapp.json';
import elevenlabsSchema from '~/schemas/nodes/elevenlabs.json';
import dropboxSchema from '~/schemas/nodes/dropbox.json';
import wordpressSchema from '~/schemas/nodes/wordpress.json';
import googleTasksSchema from '~/schemas/nodes/google-tasks.json';
import googleContactsSchema from '~/schemas/nodes/google-contacts.json';
import googleDocsSchema from '~/schemas/nodes/google-docs.json';
import googleFormsSchema from '~/schemas/nodes/google-forms.json';
import googleSlidesSchema from '~/schemas/nodes/google-slides.json';
import googleAnalyticsSchema from '~/schemas/nodes/google-analytics.json';
import googleAdsSchema from '~/schemas/nodes/google-ads.json';
import googleBusinessProfileSchema from '~/schemas/nodes/google-business-profile.json';
import googleSearchConsoleSchema from '~/schemas/nodes/google-search-console.json';
import filterSchema from '~/schemas/nodes/filter.json';
import splitOutSchema from '~/schemas/nodes/split-out.json';
import approvalSchema from '~/schemas/nodes/approval.json';
import logSchema from '~/schemas/nodes/log.json';
import submitExternalFormSchema from '~/schemas/nodes/submit-external-form.json';
import conditionalSchema from '~/schemas/nodes/conditional.json';
import switchSchema from '~/schemas/nodes/switch.json';
import mergeSchema from '~/schemas/nodes/merge.json';
import stateManagerSchema from '~/schemas/nodes/state-manager.json';
import setVariableSchema from '~/schemas/nodes/set-variable.json';
import interfaceFormSchema from '~/schemas/nodes/interface-form.json';
import interfaceFileSchema from '~/schemas/nodes/interface-file.json';
import interfaceDataframeSchema from '~/schemas/nodes/interface-dataframe.json';
import interfaceComponentSchema from '~/schemas/nodes/interface-html-react.json';
import interfaceFileUploadSchema from '~/schemas/nodes/interface-file-upload.json';
import alarmSchema from '~/schemas/nodes/alarm.json';
import filesystemSchema from '~/schemas/nodes/filesystem.json';
import noclickSchema from '~/schemas/nodes/noclick.json';

// Schema registry mapping node types to their JSON schemas
const _NODE_SCHEMAS_RAW: Record<string, any> = {
    // Trigger nodes
    'trigger-webhook': webhookTriggerSchema,
    'trigger-email': inboundEmailTriggerSchema,
    'automation-send-email': sendEmailSchema,
    'trigger-cron': cronTriggerSchema,
    // Automation nodes
    'automation-telegram': telegramSchema,
    'automation-google-sheets': googleSheetsSchema,
    'automation-google-drive': googleDriveSchema,
    'automation-gmail': gmailSchema,
    'automation-outlook': outlookSchema,
    'automation-excel': excelSchema,
    'automation-onedrive': onedriveSchema,
    'automation-microsoft-todo': microsoftTodoSchema,
    'automation-word': wordSchema,
    'automation-http-request': httpRequestSchema,
    'automation-linear': linearSchema,
    'automation-github-rest': githubRestSchema,
    'automation-airtable': airtableSchema,
    'automation-stripe': stripeSchema,
    'automation-apify': apifySchema,
    'automation-salesforce': salesforceSchema,
    'automation-youtube': youtubeSchema,
    'automation-linkedin': linkedinSchema,
    'automation-reddit': redditSchema,
    'automation-redis': redisSchema,
    'automation-google-calendar': googleCalendarSchema,
    'automation-notion': notionSchema,
    'automation-postgres': postgresSchema,
    'automation-discord': discordSchema,
    'automation-apollo': apolloSchema,
    'automation-instagram': instagramSchema,
    'automation-facebook': facebookSchema,
    'automation-instantly': instantlySchema,
    'automation-pipedrive': pipedriveSchema,
    'automation-resend': resendSchema,
    'automation-quickbooks': quickbooksSchema,
    'automation-threads': threadsSchema,
    'automation-meta': metaSchema,
    'automation-phantombuster': phantombusterSchema,
    'automation-pinecone': pineconeSchema,
    'automation-cal-com': calComSchema,
    'automation-calendly': calendlySchema,
    'automation-honeycomb': honeycombSchema,
    'automation-sentry': sentrySchema,
    'automation-google-maps': googleMapsSchema,
    'automation-perplexity': perplexitySchema,
    'automation-posthog': posthogSchema,
    'automation-voyage': voyageSchema,
    'automation-qdrant': qdrantSchema,
    'automation-upstash-vector': upstashVectorSchema,
    'automation-weaviate': weaviateSchema,
    'automation-chroma': chromaSchema,
    'automation-milvus': milvusSchema,
    'automation-mongodb': mongodbSchema,
    'automation-elasticsearch': elasticsearchSchema,
    'automation-mailgun': mailgunSchema,
    'automation-gitlab': gitlabSchema,
    'automation-box': boxSchema,
    'automation-clickup': clickupSchema,
    'automation-devin': devinSchema,
    'automation-asana': asanaSchema,
    'automation-firestore': firestoreSchema,
    'automation-google-cloud-storage': googleCloudStorageSchema,
    'automation-monday': mondaySchema,
    'automation-parallel': parallelSchema,
    'automation-datadog': datadogSchema,
    'automation-loops': loopsSchema,
    'automation-exa': exaSchema,
    'automation-reducto': reductoSchema,
    'automation-fal': falSchema,
    'automation-brandfetch': brandfetchSchema,
    'automation-findymail': findymailSchema,
    'automation-beehiiv': beehiivSchema,
    'automation-hex': hexSchema,
    'automation-clickhouse': clickhouseSchema,
    'automation-extend': extendSchema,
    'automation-fellow': fellowSchema,
    'automation-fathom': fathomSchema,
    'automation-sigma': sigmaSchema,
    'automation-trello': trelloSchema,
    'automation-firecrawl': firecrawlSchema,
    'automation-attio': attioSchema,
    'automation-intercom': intercomSchema,
    'automation-zendesk': zendeskSchema,
    'automation-confluence': confluenceSchema,
    'automation-pagerduty': pagerdutySchema,
    'automation-google-meet': googleMeetSchema,
    'automation-expensify': expensifySchema,
    'automation-freshsales': freshsalesSchema,
    'automation-launchdarkly': launchdarklySchema,
    'automation-appsheet': appsheetSchema,
    'automation-tableau': tableauSchema,
    'automation-atlas-admin': atlasAdminSchema,
    'automation-webflow': webflowSchema,
    'automation-pagespeed': pagespeedSchema,
    'automation-google-translate': googleTranslateSchema,
    'automation-bigquery': bigquerySchema,
    'automation-snowflake': snowflakeSchema,
    'automation-databricks': databricksSchema,
    'automation-microsoft-teams': microsoftTeamsSchema,
    'automation-gohighlevel': gohighlevelSchema,
    'automation-zoom': zoomSchema,
    'automation-onelake': onelakeSchema,
    'automation-bamboohr': bamboohrSchema,
    'automation-klaviyo': klaviyoSchema,
    'automation-dv360': dv360Schema,
    'automation-serverless-function': serverlessFunctionSchema,
    'automation-tiktok': tiktokSchema,
    'automation-twitter': twitterSchema,
    'automation-cloudflare': cloudflareSchema,
    'automation-shopify': shopifySchema,
    'automation-slack': slackSchema,
    'automation-bluesky': blueskySchema,
    'automation-canva': canvaSchema,
    'automation-hackernews': hackernewsSchema,
    'automation-rss': rssSchema,
    'automation-hubspot': hubspotSchema,
    'automation-affinity': affinitySchema,
    'automation-basedash': basedashSchema,
    'automation-jira': jiraSchema,
    'automation-semrush': semrushSchema,
    'automation-mailchimp': mailchimpSchema,
    'automation-typeform': typeformSchema,
    'automation-supabase': supabaseSchema,
    'automation-twilio': twilioSchema,
    'automation-whatsapp': whatsappSchema,
    'automation-elevenlabs': elevenlabsSchema,
    'automation-dropbox': dropboxSchema,
    'automation-wordpress': wordpressSchema,
    'automation-google-tasks': googleTasksSchema,
    'automation-google-contacts': googleContactsSchema,
    'automation-google-docs': googleDocsSchema,
    'automation-google-forms': googleFormsSchema,
    'automation-google-slides': googleSlidesSchema,
    'automation-google-analytics': googleAnalyticsSchema,
    'automation-google-ads': googleAdsSchema,
    'automation-google-business-profile': googleBusinessProfileSchema,
    'automation-google-search-console': googleSearchConsoleSchema,
    'agent': agentSchema,
    'iteration': iterationSchema,
    'delay': delaySchema,
    'filter': filterSchema,
    'split-out': splitOutSchema,
    'approval': approvalSchema,
    'log': logSchema,
    'automation-submit-external-form': submitExternalFormSchema,
    'conditional': conditionalSchema,
    'switch': switchSchema,
    'merge': mergeSchema,
    'state-manager': stateManagerSchema,
    'set-variable': setVariableSchema,
    'tool': toolSchema,
    'mcp-server': mcpServerSchema,
    'noclick': noclickSchema,
    'alarm': alarmSchema,
    'filesystem': filesystemSchema,
    // Interface nodes
    'interface-form': interfaceFormSchema,
    'interface-file': interfaceFileSchema,
    'interface-dataframe': interfaceDataframeSchema,
    'interface-html-react': interfaceComponentSchema,
    'interface-file-upload': interfaceFileUploadSchema,
};

// Type predicates + legacy-alias resolution live in the schema-free leaf
// utils/nodeMeta (backed by the slim generated nodeMeta.json) so weight-
// sensitive chunks can use them without bundling this module's ~9MB of JSON.
// Re-exported here so existing consumers keep a single import site.
import {
    LEGACY_NODE_TYPE_ALIASES,
    resolveNodeType,
    isAgentToolProviderType,
    isTriggerSource,
} from '~/utils/nodeMeta';

export { LEGACY_NODE_TYPE_ALIASES, resolveNodeType, isAgentToolProviderType, isTriggerSource };

export const NODE_SCHEMAS: Record<string, any> = new Proxy(_NODE_SCHEMAS_RAW, {
    get(target, prop) {
        if (
            typeof prop === 'string' &&
            !(prop in target) &&
            prop in LEGACY_NODE_TYPE_ALIASES
        ) {
            return target[LEGACY_NODE_TYPE_ALIASES[prop]];
        }
        return (target as Record<string, unknown>)[prop as string];
    },
});

/**
 * Gets the schema for a node type.
 */
export function getNodeSchema(nodeType: string): any | undefined {
    return NODE_SCHEMAS[nodeType];
}

/**
 * Whether a node is currently WIRED as an agent tool provider — a qualifying
 * type whose top handle feeds an AI agent's bottom handle. Drives the
 * allowlist config UI and provider-mode validation. Mirrors the backend's
 * is_node_op_provider (nodes/agent/node_op_tools.py). Structural types so
 * callers can pass xyflow Node/Edge objects without importing them here.
 */
export function isWiredAsAgentToolProvider(
    nodeId: string,
    nodes: Array<{ id: string; type?: string }>,
    edges: Array<{ source: string; target: string; targetHandle?: string | null }>,
): boolean {
    return getToolProviderConsumerTypes(nodeId, nodes, edges).length > 0;
}

/**
 * The kinds of consumers this provider node feeds through its top→bottom
 * wiring: AI agents and/or hosting-mode MCP servers. Drives provider-mode
 * config UI and its consumer-aware copy. Empty = not provider-wired.
 */
export function getToolProviderConsumerTypes(
    nodeId: string,
    nodes: Array<{ id: string; type?: string }>,
    edges: Array<{ source: string; target: string; targetHandle?: string | null }>,
): Array<'agent' | 'mcp-server'> {
    const node = nodes.find(n => n.id === nodeId);
    if (!node || !isAgentToolProviderType(node.type)) return [];
    const typeById = new Map(nodes.map(n => [n.id, n.type]));
    const consumers = new Set<'agent' | 'mcp-server'>();
    for (const e of edges) {
        if (e.source !== nodeId || e.targetHandle !== 'bottom') continue;
        const t = typeById.get(e.target);
        if (t === 'agent' || t === 'mcp-server') consumers.add(t);
    }
    return [...consumers];
}

/**
 * An exposable (non-trigger) operation of an integration node, for the
 * agent-tool allowlist UI. Mirrors the backend's list_node_operations.
 */
/** A field on an operation that can be resource-scoped — has both
 *  `x-dynamic-options` (loader-backed picker) AND `x-resource-type`
 *  (identity tag). Backend enforcement in
 *  tool_execution._enforce_field_scopes reads the matching
 *  `agent_tool_operations[i].field_scopes[field]` allowlist. */
export interface AgentToolScopableField {
    field: string;
    label: string;
    resourceType: string;
    /** Loader field_name (what the load_field_options socket call expects);
     *  usually matches `field` but can differ for back-compat schemas. */
    loaderField: string;
    /** Parent field this dependent loader needs context from (e.g. `sheet_name`
     *  depends on `spreadsheet_id`). The scope picker gates this field on the
     *  parent's scope: empty parent scope → can't enumerate options. */
    dependsOn?: string;
}

export interface AgentToolOperation {
    operation: string;
    displayName: string;
    category: string | null;
    description: string;
    /** Author-supplied search synonyms (joined `x-keywords`), so the allowlist
     *  picker's search matches intent words the label doesn't contain. */
    keywords: string;
    /** Operation has ID fields served by dynamic-option loaders — the agent
     *  gets an auto-included {provider}__lookup_options tool for these. */
    hasDynamicFields: boolean;
    /** Subset of fields scopable via field_scopes (x-dynamic-options +
     *  x-resource-type). Empty for ops that have ID fields but no
     *  resource-type tag (e.g. unannotated nodes). */
    scopableFields: AgentToolScopableField[];
}

/** An entry in `agent_tool_operations`: either a bare operation name string
 *  (unscoped, legacy/default shape) OR a scoped object pinning specific
 *  resource IDs to specific fields. Backend validator
 *  validate_agent_tool_operations enforces the schema. */
export type AgentToolOperationEntry =
    | string
    | { operation: string; field_scopes: Record<string, string[]> };

/** Pull the operation name from a mixed-shape entry. Used by callers that
 *  only care about which ops are selected (display, picker keyboard nav,
 *  edge-presence checks) — they don't need to know about field_scopes. */
export function operationName(entry: AgentToolOperationEntry): string {
    return typeof entry === 'string' ? entry : entry.operation;
}

/** Flatten mixed entries to a names-only array. Cheap; safe on null. */
export function operationNamesOf(
    entries: AgentToolOperationEntry[] | string[] | null | undefined,
): string[] {
    if (!Array.isArray(entries)) return [];
    return entries.map(e =>
        typeof e === 'string' ? e : (e?.operation ?? ''),
    ).filter(Boolean);
}

/** Field_scopes for a given operation, indexed by field name. Empty if the
 *  op is unscoped. */
export function fieldScopesFor(
    entries: AgentToolOperationEntry[] | null | undefined,
    operation: string,
): Record<string, string[]> {
    if (!Array.isArray(entries)) return {};
    for (const e of entries) {
        if (typeof e === 'object' && e?.operation === operation && e.field_scopes) {
            return e.field_scopes;
        }
    }
    return {};
}

/**
 * Enumerates the operations of a node that can be exposed as agent tools,
 * derived from the schema's per-operation union (triggers excluded).
 */
export function getAgentToolOperations(nodeType: string): AgentToolOperation[] {
    const schema = NODE_SCHEMAS[nodeType];
    if (!schema) return [];
    const config = schema.properties?.config ?? {};
    const defs = schema.$defs ?? {};
    // Union shape (oneOf/anyOf of $refs) or single-model shape (direct $ref) —
    // mirrors the backend's _iter_operation_defs so both sides enumerate the
    // same operations for every stamped schema.
    const refs: Array<{ $ref?: string }> =
        config.oneOf ?? config.anyOf ?? (config.$ref ? [{ $ref: config.$ref }] : []);

    const ops: AgentToolOperation[] = [];
    for (const ref of refs) {
        const key = ref.$ref?.split('/').pop();
        const member = key ? defs[key] : undefined;
        const op = member?.properties?.operation;
        const constValue = op?.const ?? op?.enum?.[0];
        if (!constValue || op?.['x-is-trigger']) continue;
        let hasDynamicFields = false;
        const scopableFields: AgentToolScopableField[] = [];
        for (const [field, propRaw] of Object.entries(member.properties ?? {})) {
            const prop = propRaw as Record<string, any> | null | undefined;
            if (field === 'operation' || !prop || prop['ui:hidden']) continue;
            const dyn = prop['x-dynamic-options'];
            if (!dyn) continue;
            hasDynamicFields = true;
            const resourceType = prop['x-resource-type'];
            if (typeof resourceType === 'string' && resourceType) {
                const dependsOn = typeof dyn === 'object' && typeof dyn?.depends_on === 'string'
                    ? dyn.depends_on
                    : undefined;
                scopableFields.push({
                    field,
                    label: prop.title || field,
                    resourceType,
                    loaderField: (typeof dyn === 'object' && dyn?.field_name) || field,
                    dependsOn,
                });
            }
        }
        ops.push({
            operation: constValue,
            displayName: op['x-display-name'] ?? op.title ?? constValue,
            category: op['x-category'] ?? null,
            description: member.description ?? '',
            keywords: Array.isArray(op['x-keywords'])
                ? op['x-keywords'].join(' ')
                : op['x-keywords'] ?? '',
            hasDynamicFields,
            scopableFields,
        });
    }
    return ops;
}

/** A trigger node wired directly into an agent's input — one chip under the
 *  agent's Message field. */
export interface AgentTriggerSource {
    edgeId: string;
    nodeId: string;
    nodeType: string;
    /** User-given node label; empty when unset (render the type's default). */
    label: string;
    /** Selected operation — set for integration triggers (x-is-trigger ops). */
    operation?: string;
}

/**
 * Trigger nodes wired directly into an agent's input handle. When one fires,
 * the agent runs with the fired event delivered as part of its user turn
 * (backend: AgentNode._resolve_trigger_event). Bottom-handle edges are
 * excluded — tool providers and alarms have their own visual surfaces.
 */
export function getAgentTriggerSources(
    agentNodeId: string,
    nodes: Array<{ id: string; type?: string; data?: Record<string, any> }>,
    edges: Array<{ id: string; source: string; target: string; targetHandle?: string | null }>,
): AgentTriggerSource[] {
    const byId = new Map(nodes.map(n => [n.id, n]));
    const sources: AgentTriggerSource[] = [];
    for (const e of edges) {
        if (e.target !== agentNodeId || e.targetHandle === 'bottom') continue;
        const src = byId.get(e.source);
        if (!src?.type) continue;
        const operation = (src.data?.operation ?? src.data?.config?.operation) as
            | string
            | undefined;
        if (!isTriggerSource(src.type, operation)) continue;
        sources.push({
            edgeId: e.id,
            nodeId: src.id,
            nodeType: src.type,
            label: (src.data?.label as string | undefined) || '',
            operation,
        });
    }
    return sources;
}

/**
 * Agent nodes with NO trigger wired into their input handle — i.e. chat-driven
 * agents that run by chatting rather than by a fired event. Used after an AI
 * build to surface such agents in the Interface tab. Reuses
 * getAgentTriggerSources so the "what counts as a trigger" rule stays in one place.
 */
export function getTriggerlessAgents<
    N extends { id: string; type?: string; data?: Record<string, any> },
>(
    nodes: N[],
    edges: Array<{ id: string; source: string; target: string; targetHandle?: string | null }>,
): N[] {
    return nodes.filter(
        (n) => n.type === 'agent' && getAgentTriggerSources(n.id, nodes, edges).length === 0,
    );
}

/** A trigger operation of an integration node (x-is-trigger), for pickers
 *  that wire integration triggers (e.g. the agent chat sidebar). */
export interface TriggerOperation {
    operation: string;
    displayName: string;
    description: string;
    /** Author-supplied search synonyms (joined `x-keywords`), so trigger search
     *  matches intent words the display name doesn't contain. */
    keywords: string;
}

/**
 * Enumerates a node type's TRIGGER operations (x-is-trigger) — the complement
 * of getAgentToolOperations' enumeration, same schema walk.
 */
export function getTriggerOperations(nodeType: string): TriggerOperation[] {
    const schema = NODE_SCHEMAS[nodeType];
    if (!schema) return [];
    const config = schema.properties?.config ?? {};
    const defs = schema.$defs ?? {};
    const refs: Array<{ $ref?: string }> =
        config.oneOf ?? config.anyOf ?? (config.$ref ? [{ $ref: config.$ref }] : []);
    const ops: TriggerOperation[] = [];
    for (const ref of refs) {
        const key = ref.$ref?.split('/').pop();
        const member = key ? defs[key] : undefined;
        const op = member?.properties?.operation;
        const constValue = op?.const ?? op?.enum?.[0];
        if (!constValue || !op?.['x-is-trigger']) continue;
        ops.push({
            operation: constValue,
            displayName: op['x-display-name'] ?? op.title ?? constValue,
            description: member.description ?? '',
            keywords: Array.isArray(op['x-keywords'])
                ? op['x-keywords'].join(' ')
                : op['x-keywords'] ?? '',
        });
    }
    return ops;
}

/** A tool-provider node wired to an agent's bottom handle — one row in the
 *  agent chat sidebar's Tools section. */
export interface AgentWiredTool {
    edgeId: string;
    nodeId: string;
    nodeType: string;
    /** User-given node label; empty when unset (render the type's default). */
    label: string;
    /** Allowlisted operations (config.agent_tool_operations). */
    operations: string[];
    /** Node has credential slots but none connected — tool calls will fail. */
    credentialsMissing: boolean;
    /** Attached credential ids (credential_type → id) — lets consumers check
     *  credential HEALTH (revoked/deleted) against the loaded list. */
    credentialIds: Record<string, string>;
}

/**
 * Tool-provider nodes wired to an agent's bottom handle, with their allowlist
 * state. Mirrors is_node_op_provider (backend) for display purposes.
 */
export function getAgentToolProviders(
    agentNodeId: string,
    nodes: Array<{ id: string; type?: string; data?: Record<string, any> }>,
    edges: Array<{ id: string; source: string; target: string; targetHandle?: string | null }>,
    hasUnconnectedCredentials: (nodeType: string, credentialIds: Record<string, string>, nodeData?: Record<string, any>) => boolean,
): AgentWiredTool[] {
    const byId = new Map(nodes.map(n => [n.id, n]));
    const tools: AgentWiredTool[] = [];
    for (const e of edges) {
        if (e.target !== agentNodeId || e.targetHandle !== 'bottom') continue;
        const src = byId.get(e.source);
        // The four STRUCTURAL_AGENT_TOOL_TYPES are wirable here without an
        // allowlist (their tool surfaces are emitted by the node itself).
        if (!src?.type || !(isAgentToolProviderType(src.type) || STRUCTURAL_AGENT_TOOL_TYPES.has(src.type))) continue;
        const cfg = (src.data?.config ?? {}) as Record<string, any>;
        const credentialIds = (src.data?.credentialIds ?? cfg.credentialIds ?? {}) as Record<string, string>;
        tools.push({
            edgeId: e.id,
            nodeId: src.id,
            nodeType: src.type,
            label: (src.data?.label as string | undefined) || '',
            // Always present as op names — mixed-shape entries (scoped objects)
            // are normalized for downstream display (sidebar count chip, etc).
            operations: operationNamesOf(cfg.agent_tool_operations),
            credentialsMissing: hasUnconnectedCredentials(src.type, credentialIds, src.data),
            credentialIds,
        });
    }
    return tools;
}

/**
 * Structural tool-provider node types: not integration-operation allowlists,
 * but their own first-class providers that emit fixed tool surfaces when
 * wired into an agent's bottom handle (or an MCP host's bottom handle):
 *   - `tool`        — ToolNode, exposes a custom downstream subgraph
 *   - `mcp-server`  — external MCP server or hosted bundle
 *   - `alarm`       — AlarmNode (4 alarm tools: schedule/list/cancel/update)
 *   - `filesystem`  — FilesystemNode (sandbox volume + upload_file tool)
 * Mirrors FlowCanvas.isValidConnection's BOTTOM_HANDLE_TYPES.
 */
export const STRUCTURAL_AGENT_TOOL_TYPES: ReadonlySet<string> = new Set([
    'tool',
    'mcp-server',
    'alarm',
    'filesystem',
]);

/** Can this node type wire its 'top' into an agent's 'bottom' as a tool
 *  provider? THE rule — shared by isValidConnection and the agent drop target
 *  so the canvas can't accept a drop the validator would reject. */
export function canFeedAgentBottom(nodeType: string | undefined | null): boolean {
    return (
        (!!nodeType && STRUCTURAL_AGENT_TOOL_TYPES.has(nodeType)) ||
        isAgentToolProviderType(nodeType)
    );
}

let _wirableCatalog: { triggers: Array<{ nodeType: string; triggerOps: TriggerOperation[] }>; tools: string[] } | null = null;

/**
 * Node types wirable to an agent from the chat sidebar: dedicated trigger-*
 * types (minus the manual Run button) + integrations with ≥1 trigger
 * operation, and tool-provider-capable types — both operation-allowlist
 * providers (~58 integrations exposing node_op tools) AND the four
 * structural tool types in STRUCTURAL_AGENT_TOOL_TYPES. Schema walk over
 * the full registry — computed once and cached (NODE_SCHEMAS is static).
 */
export function getAgentWirableCatalog(): { triggers: Array<{ nodeType: string; triggerOps: TriggerOperation[] }>; tools: string[] } {
    if (_wirableCatalog) return _wirableCatalog;
    const triggers: Array<{ nodeType: string; triggerOps: TriggerOperation[] }> = [];
    const tools: string[] = [];
    for (const nodeType of Object.keys(NODE_SCHEMAS)) {
        if (nodeType.startsWith('trigger-') && nodeType !== 'trigger-run') {
            triggers.push({ nodeType, triggerOps: [] });
        } else {
            const triggerOps = getTriggerOperations(nodeType);
            if (triggerOps.length > 0) triggers.push({ nodeType, triggerOps });
        }
        if (isAgentToolProviderType(nodeType) || STRUCTURAL_AGENT_TOOL_TYPES.has(nodeType)) tools.push(nodeType);
    }
    _wirableCatalog = { triggers, tools };
    return _wirableCatalog;
}

/**
 * Credential info extracted from a node schema.
 * Used by template loading and workflow generation to determine what credentials a node needs.
 */
export interface NodeCredentialInfo {
    /** Provider key for getProviderConfigNormalized (e.g., 'google_sheets', 'slack') */
    providerKey: string;
    /** Array of accepted DB credential types (e.g., ['slack_oauth', 'slack_bot_token']) */
    acceptedTypes: string[];
    /** Display label for the credential (e.g., 'Google Account', 'Slack Workspace') */
    label: string;
}


/**
 * Extract a provider key from node type or credential schema.
 * E.g., 'automation-google-sheets' → 'google_sheets', 'automation-slack' → 'slack'
 */
function extractProviderKeyFromNodeType(nodeType: string): string {
    // Remove 'automation-' or 'trigger-' prefix and convert to snake_case
    return nodeType
        .replace(/^(automation|trigger)-/, '')
        .replace(/-/g, '_');
}

/**
 * Get a display label for a provider.
 * E.g., 'google_sheets' → 'Google Sheets', 'slack' → 'Slack'
 */
function getProviderLabel(providerKey: string): string {
    // Special cases for display names
    const labelMap: Record<string, string> = {
        'google_sheets': 'Google Account',
        'google_drive': 'Google Account',
        'gmail': 'Google Account',
        'google_calendar': 'Google Account',
        'google_tasks': 'Google Account',
        'google_contacts': 'Google Account',
        'google_docs': 'Google Account',
        'google_forms': 'Google Account',
        'google_slides': 'Google Account',
        'google_analytics': 'Google Account',
        'google_ads': 'Google Account',
        'google_business_profile': 'Google Account',
        'youtube': 'Google Account',
        'github': 'GitHub Account',
        'github_rest': 'GitHub Account',
        'slack': 'Slack Workspace',
        'airtable': 'Airtable Account',
        'stripe': 'Stripe Account',
        'notion': 'Notion Workspace',
        'linear': 'Linear Account',
        'discord': 'Discord Account',
        'outlook': 'Microsoft Account',
        'excel': 'Microsoft Account',
        'onedrive': 'Microsoft Account',
        'microsoft_todo': 'Microsoft Account',
        'word': 'Microsoft Account',
        'microsoft_teams': 'Microsoft Account',
        'microsoft': 'Microsoft Account',
        'hubspot': 'HubSpot Account',
        'affinity': 'Affinity Account',
        'basedash': 'Basedash Account',
        'salesforce': 'Salesforce Account',
        'jira': 'Jira Account',
        'shopify': 'Shopify Store',
        'dropbox': 'Dropbox Account',
        'mailchimp': 'Mailchimp Account',
        'typeform': 'Typeform Account',
        'canva': 'Canva Account',
        'twitter': 'Twitter Account',
        'linkedin': 'LinkedIn Account',
        'reddit': 'Reddit Account',
        'telegram': 'Telegram Bot',
        'instagram': 'Instagram Account',
        'instantly': 'Instantly Account',
        'tiktok': 'TikTok Account',
        'bluesky': 'Bluesky Account',
        'wordpress': 'WordPress Account',
    };

    if (labelMap[providerKey]) return labelMap[providerKey];

    // Default: Convert snake_case to Title Case
    return providerKey
        .split('_')
        .map(word => word.charAt(0).toUpperCase() + word.slice(1))
        .join(' ') + ' Account';
}

/**
 * Extract credential info from a node schema.
 * Returns info about what credentials the node requires, or undefined if no credentials needed.
 *
 * This function analyzes the schema's credentials property to determine:
 * - Provider key for OAuth lookup
 * - List of accepted credential types (OAuth, PAT, API key, etc.)
 * - Display label for the credential
 */
export function getNodeCredentialInfo(nodeType: string): NodeCredentialInfo | undefined {
    const schema = NODE_SCHEMAS[nodeType];
    if (!schema?.properties?.credentials) return undefined;

    const credentialProp = schema.properties.credentials;
    const $defs = schema.$defs || schema.definitions || {};

    // Resolve $ref to get the actual credential schema
    const resolveRef = (ref: string): any => {
        const path = ref.replace('#/$defs/', '').replace('#/definitions/', '');
        return $defs[path];
    };

    // Collect all credential schemas
    const credentialSchemas: Array<{ schema: any; title: string }> = [];

    if (credentialProp.$ref) {
        // Direct $ref - single credential type
        const credSchema = resolveRef(credentialProp.$ref);
        if (credSchema) {
            credentialSchemas.push({ schema: credSchema, title: credSchema.title || '' });
        }
    } else if (credentialProp.anyOf) {
        // anyOf pattern - multiple credential types (OAuth, PAT, etc.)
        for (const entry of credentialProp.anyOf) {
            if (entry.$ref) {
                const credSchema = resolveRef(entry.$ref);
                if (credSchema && credSchema.title) {
                    credentialSchemas.push({ schema: credSchema, title: credSchema.title });
                }
            }
        }
    }

    if (credentialSchemas.length === 0) return undefined;

    // Extract accepted types from all credential schemas
    const acceptedTypes: string[] = [];
    let oauthProvider: string | undefined;

    for (const { schema: credSchema, title } of credentialSchemas) {
        // Convert title to DB type using explicit map (e.g., 'SlackOAuthCredential' → 'slack_oauth')
        const dbType = getCredentialTypeFromSchemaTitle(title);
        acceptedTypes.push(dbType);

        // Check for OAuth provider marker
        if (credSchema['x-oauth-provider'] && !oauthProvider) {
            oauthProvider = credSchema['x-oauth-provider'];
        }
    }

    // Determine provider key:
    // 1. For Google services, use node-derived key (google_sheets, gmail, etc.) for service-specific scopes
    // 2. For non-Google OAuth services, use x-oauth-provider (e.g., 'microsoft' for outlook)
    // 3. Otherwise derive from node type
    const baseProviderKey = extractProviderKeyFromNodeType(nodeType);

    // Use oauthProvider for non-Google services that need it (e.g., outlook → microsoft)
    // Google services use service-specific keys for proper scope handling via PROVIDER_ALIASES
    const providerKey = (oauthProvider && oauthProvider !== 'google')
        ? oauthProvider
        : baseProviderKey;

    return {
        providerKey,
        acceptedTypes,
        label: getProviderLabel(providerKey),
    };
}

/**
 * Filters a node's config to only include fields that belong to the currently selected operation.
 * This is critical for nodes with discriminated unions (e.g., Google Sheets with read/write/append).
 *
 * When users switch between operations in the UI, we intentionally keep all fields to allow
 * easy switching. However, when sending to the backend, we must filter out fields from
 * non-selected operations to ensure proper schema validation.
 */
export function filterConfigForExecution(
    nodeType: string | undefined,
    config: Record<string, any>
): Record<string, any> {
    if (!config || typeof config !== 'object') return config;
    if (!nodeType) return config;

    const rootSchema = NODE_SCHEMAS[nodeType];
    if (!rootSchema) return config;

    // Extract config sub-schema (root schema has { properties: { config: {...} } })
    const configSchema = rootSchema?.properties?.config || rootSchema;

    // Resolve $refs from root schema's $defs
    const resolveRef = (ref: string): any => {
        const path = ref.replace('#/$defs/', '');
        return rootSchema?.$defs?.[path] || rootSchema?.definitions?.[path];
    };

    // If schema is a $ref, resolve it
    const resolvedSchema = configSchema?.$ref ? resolveRef(configSchema.$ref) : configSchema;
    if (!resolvedSchema) return config;

    // Check for anyOf/oneOf (discriminated union)
    const options = resolvedSchema?.oneOf || resolvedSchema?.anyOf || [];
    if (options.length === 0) return config;

    // Detect discriminator field (field with const values in all options)
    let discriminatorField: string | null = null;
    const valueToOptionIndex = new Map<string, number>();

    const firstOption = options[0].$ref ? resolveRef(options[0].$ref) : options[0];
    const firstProps = firstOption?.properties || {};

    for (const [fieldName, fieldProp] of Object.entries(firstProps) as [string, any][]) {
        const constValue = fieldProp?.const;
        if (!constValue) continue;

        let isDiscriminator = true;
        const values = new Map<string, number>();
        values.set(constValue, 0);

        for (let i = 1; i < options.length; i++) {
            const option = options[i].$ref ? resolveRef(options[i].$ref) : options[i];
            const prop = option?.properties?.[fieldName];
            if (!prop?.const) {
                isDiscriminator = false;
                break;
            }
            values.set(prop.const, i);
        }

        if (isDiscriminator && values.size === options.length) {
            discriminatorField = fieldName;
            values.forEach((idx, val) => valueToOptionIndex.set(val, idx));
            break;
        }
    }

    if (!discriminatorField) return config;

    // Get the discriminator value from config
    const discriminatorValue = config[discriminatorField];
    if (!discriminatorValue || !valueToOptionIndex.has(discriminatorValue)) return config;

    // Get the selected option's fields
    const optionIndex = valueToOptionIndex.get(discriminatorValue)!;
    const selectedOption = options[optionIndex].$ref
        ? resolveRef(options[optionIndex].$ref)
        : options[optionIndex];
    const selectedOptionFields = new Set(Object.keys(selectedOption?.properties || {}));

    // Collect all schema fields from all options
    const allSchemaFields = new Set<string>();
    options.forEach((opt: any) => {
        const resolved = opt.$ref ? resolveRef(opt.$ref) : opt;
        Object.keys(resolved?.properties || {}).forEach(key => allSchemaFields.add(key));
    });

    // Build filtered config: non-schema fields + selected option's fields only
    const filteredConfig: Record<string, any> = {};
    for (const [key, value] of Object.entries(config)) {
        if (!allSchemaFields.has(key) || selectedOptionFields.has(key)) {
            filteredConfig[key] = value;
        }
    }

    return filteredConfig;
}
