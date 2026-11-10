// The credential schema-title -> credential_type map and its lookup, split out of
// credentialTypes.ts into a leaf that imports only generated integration facts.
//
// Why it lives here: nodeSchemas.ts needs the lookup, and credentialTypes.ts needs
// getNodeCredentialInfo from nodeSchemas — a mutual import that Vite SSR resolves
// by module-evaluation order, so adding any new edge into that pair could 500 the
// dev server with "dependency module is not yet fully initialized". Owning the map
// here lets both sides import it without pointing at each other.
//
// credentialTypes.ts re-exports both symbols, so existing importers are unaffected.

import { INTEGRATION_METADATA, mergeDeclarations } from './integrationMetadata';

/**
 * Maps credential schema titles (from Pydantic models) to credential_type strings (DB identifiers).
 * Example: 'GoogleSheetsOAuthCredential' -> 'google_sheets_oauth'
 */
export const CREDENTIAL_TYPE_MAP: Record<string, string> = mergeDeclarations({
    // Named ahead of the generated aliases, whose sorted keys would put a schema title first:
    // getSchemaTitleFromCredentialType returns the first name a credential type has.
    'BytescaleSecretAPIKeyCredential': 'bytescale_secret_api_key',
    'LinkwardenAccessTokenCredential': 'linkwarden_access_token',
    'DocspellAuthTokenCredential': 'docspell_auth_token',
    'RipplingAPITokenCredential': 'rippling_api_token',
    'MindbodyAPIKeyCredential': 'mindbody_api_key',
    'PredictLeadsAPIKeyTokenCredential': 'predictleads_api_key_token',
    'SematextAccountAPIKeyCredential': 'sematext_account_api_key',
    'ImmichAPIKeyCredential': 'immich_api_key',
    'RebrandlyAPIKeyCredential': 'rebrandly_api_key',
    'SingleStoreManagementCredential': 'singlestore_management_api_key',
    'StatusPalAPIKeyCredential': 'statuspal_api_key',
    'StreamChatServerCredential': 'stream_chat_api_key',
    'UptimeComAPITokenCredential': 'uptimecom_api_token',
    'NylasAPIKeyCredential': 'nylas_api_key',
    'NylasAccessTokenCredential': 'nylas_access_token',
    'GoogleClassroomOAuthCredential': 'google_oauth',
    'ForgejoPATCredential': 'forgejo_pat',
    'InvoiceNinjaAPITokenCredential': 'invoiceninja_api_token',
    'DeelAPITokenCredential': 'deel_api_token',
    'KajabiAccessTokenCredential': 'kajabi_access_token',
    'PDFCoAPIKeyCredential': 'pdfco_api_key',
    'SumUpAPIKeyCredential': 'sumup_api_key',
    'BigCommerceAPITokenCredential': 'bigcommerce_api_token',
    'Auth0TokenCredential': 'auth0_token',
    'GustoAccessTokenCredential': 'gusto_access_token',
    'OktaAPITokenCredential': 'okta_api_token',
    'StatuspageAPIKeyCredential': 'statuspage_api_key',
    'RedditOAuthCredential': 'reddit_oauth',
    'PulseticAPIKeyCredential': 'pulsetic_api_key',
    'AprimoBearerCredential': 'aprimo_bearer',
    'BloomerangPrivateApiKeyCredential': 'bloomerang_private_api_key',
    'QonversionSecretKeyCredential': 'qonversion_secret_key',

    'Status Pal API Key': 'statuspal_api_key',
    // Agent credentials
    'AgentCredentials': 'agent_api_key',

    // Telegram
    'TelegramBotTokenCredential': 'telegram_bot_token',

    // OpenAI
    'OpenAIAPIKeyCredential': 'openai_api_key',

    // Google services
    'GoogleSheetsOAuthCredential': 'google_sheets_oauth',
    'GoogleDriveOAuthCredential': 'google_drive_oauth',
    'GmailOAuthCredential': 'google_gmail_oauth',
    'GoogleCalendarOAuthCredential': 'google_calendar_oauth',
    'GoogleFormsOAuthCredential': 'google_forms_oauth',

    // Microsoft
    'OutlookOAuthCredential': 'microsoft_outlook_oauth',
    'MicrosoftTeamsOAuthCredential': 'microsoft_teams_oauth',

    // Linear
    'LinearOAuthCredential': 'linear_oauth',
    'LinearPATCredential': 'linear_pat',

    // Stripe
    'StripeOAuthCredential': 'stripe_oauth',
    'StripeApiKeyCredential': 'stripe_api_key',

    // GitHub
    'GithubPATCredential': 'github_pat',
    'GithubOAuthCredential': 'github_oauth',

    // Discord
    'DiscordBotInstallCredential': 'discord_bot_install',
    'DiscordBotTokenCredential': 'discord_bot_token',

    // Instagram (uses Facebook OAuth)
    'InstagramOAuthCredential': 'instagram_oauth',
    // Facebook (Pages + Messenger)
    'FacebookOAuthCredential': 'facebook_oauth',
    'FacebookAccessTokenCredential': 'facebook_access_token',
    // Meta (Marketing / Ads / Business)
    'MetaOAuthCredential': 'meta_oauth',
    'MetaAccessTokenCredential': 'meta_access_token',

    // Instantly
    'InstantlyAPIKeyCredential': 'instantly_api_key',

    // Jira (Atlassian)
    'JiraOAuthCredential': 'jira_oauth',
    'JiraAPITokenCredential': 'jira_api_token',

    // Confluence (Atlassian)
    'ConfluenceOAuthCredential': 'confluence_oauth',
    'ConfluenceApiTokenCredential': 'confluence_api_token',

    // Notion
    'NotionIntegrationTokenCredential': 'notion_integration_token',
    'NotionOAuthCredential': 'notion_oauth',

    // RSS
    'RSSFeedURLCredential': 'rss_feed_url',

    // Redis
    'RedisCredential': 'redis_rest',
    'RedisStandardCredential': 'redis_standard',
    'RedisReadOnlyCredential': 'redis_readonly',
    'RedisACLCredential': 'redis_acl',

    // Salesforce
    'SalesforceOAuthCredential': 'salesforce_oauth',

    // Shopify
    'ShopifyOAuthCredential': 'shopify_oauth',
    'ShopifyAccessTokenCredential': 'shopify_access_token',

    // Slack
    'SlackOAuthCredential': 'slack_oauth',
    'SlackBotTokenCredential': 'slack_bot_token',

    // Cloudflare
    'CloudflareAPITokenCredential': 'cloudflare_api_token',
    'CloudflareAPIKeyCredential': 'cloudflare_api_key',

    // HubSpot
    'HubSpotOAuthCredential': 'hubspot_oauth',
    'HubSpotPATCredential': 'hubspot_pat',

    // Basedash
    'BasedashApiKeyCredential': 'basedash_api_key',

    // Pipedrive
    'PipedriveOAuthCredential': 'pipedrive_oauth',
    'PipedriveAPITokenCredential': 'pipedrive_api_token',

    // Resend
    'ResendAPIKeyCredential': 'resend_api_key',

    // QuickBooks
    'QuickBooksOAuthCredential': 'quickbooks_oauth',

    // Threads
    'ThreadsOAuthCredential': 'threads_oauth',
    'ThreadsAccessTokenCredential': 'threads_access_token',

    // PhantomBuster
    'PhantomBusterApiKeyCredential': 'phantombuster_api_key',

    // Cal.com
    'CalComOAuthCredential': 'cal_com_oauth',
    'CalComApiKeyCredential': 'cal_com_api_key',
    'CalendlyOAuthCredential': 'calendly_oauth',
    'CalendlyPATCredential': 'calendly_pat',
    'HoneycombApiKeyCredential': 'honeycomb_api_key',
    'HoneycombManagementKeyCredential': 'honeycomb_management_key',
    'SentryOAuthCredential': 'sentry_oauth',
    'SentryAuthTokenCredential': 'sentry_auth_token',

    // Google Maps
    // Perplexity
    'PerplexityApiKeyCredential': 'perplexity_api_key',
    'PostHogPersonalApiKeyCredential': 'posthog_personal_api_key',
    'PostHogProjectApiKeyCredential': 'posthog_project_api_key',
    'PostHogOAuthCredential': 'posthog_oauth',

    // Mailgun
    'MailgunApiKeyCredential': 'mailgun_api_key',

    // GitLab
    'GitLabAccessTokenCredential': 'gitlab_token',
    'GitLabOAuthCredential': 'gitlab_oauth',
    // Box
    'BoxOAuthCredential': 'box_oauth',
    'BoxDeveloperTokenCredential': 'box_developer_token',
    // ClickUp
    'ClickUpOAuthCredential': 'clickup_oauth',
    'ClickUpPersonalTokenCredential': 'clickup_pat',

    // Devin
    'DevinApiKeyCredential': 'devin_api_key',

    // Asana
    'AsanaOAuthCredential': 'asana_oauth',
    'AsanaPATCredential': 'asana_pat',

    // Firestore
    'FirestoreOAuthCredential': 'firestore_oauth',
    'FirestoreServiceAccountCredential': 'firestore_service_account',
    'FirestoreFirebaseIdTokenCredential': 'firestore_firebase_id_token',

    // Google Cloud Storage
    'GoogleCloudStorageOAuthCredential': 'google_cloud_storage_oauth',
    'GoogleCloudStorageServiceAccountCredential': 'google_cloud_storage_service_account',

    // Monday.com
    'MondayOAuthCredential': 'monday_oauth',
    'MondayApiTokenCredential': 'monday_api_token',

    // Parallel
    'ParallelApiKeyCredential': 'parallel_api_key',
    'ParallelOAuthCredential': 'parallel_oauth',

    // Datadog
    'DatadogApiKeyCredential': 'datadog_api_key',

    // Loops
    'LoopsAPIKeyCredential': 'loops_api_key',

    // Exa
    'ExaApiKeyCredential': 'exa_api_key',

    // Reducto
    'ReductoApiKeyCredential': 'reducto_api_key',

    // fal
    'FalApiKeyCredential': 'fal_api_key',

    // Brandfetch
    'BrandfetchApiKeyCredential': 'brandfetch_api_key',

    // Findymail
    'FindymailApiKeyCredential': 'findymail_api_key',

    // beehiiv
    'BeehiivApiKeyCredential': 'beehiiv_api_key',

    // Hex
    'HexApiTokenCredential': 'hex_api_token',

    // ClickHouse
    'ClickHouseApiKeyCredential': 'clickhouse_api_key',

    // Extend
    'ExtendApiKeyCredential': 'extend_api_key',
    // Fellow
    'FellowAPIKeyCredential': 'fellow_api_key',

    // Fathom
    'FathomApiKeyCredential': 'fathom_api_key',
    'FathomBearerTokenCredential': 'fathom_bearer_token',
    'FathomOAuthCredential': 'fathom_oauth',

    // Sigma Computing
    'SigmaApiKeyCredential': 'sigma_api_key',

    // Trello
    'TrelloApiKeyCredential': 'trello_api_key',

    // Firecrawl
    'FirecrawlAPIKeyCredential': 'firecrawl_api_key',
    // Attio
    'AttioOAuthCredential': 'attio_oauth',
    'AttioAPIKeyCredential': 'attio_api_key',

    // Intercom
    'IntercomAccessTokenCredential': 'intercom_token',
    'IntercomOAuthCredential': 'intercom_oauth',

    // Zendesk
    'ZendeskOAuthCredential': 'zendesk_oauth',
    'ZendeskApiTokenCredential': 'zendesk_api_token',
    'ZendeskConversationsCredential': 'zendesk_conversations',
    // Google Meet
    'GoogleMeetOAuthCredential': 'google_meet_oauth',

    // PagerDuty
    'PagerDutyOAuthCredential': 'pagerduty_oauth',
    'PagerDutyApiKeyCredential': 'pagerduty_api_key',
    // Expensify
    'ExpensifyPartnerCredential': 'expensify_partner',

    // Freshsales (API-key only — Freshworks' CRM REST API rejects external OAuth tokens)
    'FreshsalesApiKeyCredential': 'freshsales_api_key',
    // LaunchDarkly
    'LaunchDarklyTokenCredential': 'launchdarkly_token',
    'DopplerTokenCredential': 'doppler_token',
    // AppSheet
    'AppSheetApiKeyCredential': 'appsheet_api_key',
    // Webflow
    'WebflowOAuthCredential': 'webflow_oauth',
    'WebflowApiTokenCredential': 'webflow_api_token',

    // Tableau
    'TableauPATCredential': 'tableau_pat',
    // Google PageSpeed
    // Google Translate
    'GoogleTranslateOAuthCredential': 'google_translate_oauth',
    'GoogleTranslateServiceAccountCredential': 'google_translate_service_account',
    'GoogleTranslateApiKeyCredential': 'google_translate_api_key',
    // GoHighLevel
    'GoHighLevelPitCredential': 'gohighlevel_pit',

    // Google BigQuery
    'BigQueryOAuthCredential': 'bigquery_oauth',
    'BigQueryServiceAccountCredential': 'bigquery_service_account',

    // Snowflake
    'SnowflakePatCredential': 'snowflake_pat',

    // Databricks
    'DatabricksTokenCredential': 'databricks_token',
    // Zoom
    'ZoomServerToServerCredential': 'zoom_server_to_server',
    'ZoomOAuthCredential': 'zoom_oauth',
    // OneLake (Microsoft Fabric)
    'OneLakeOAuthCredential': 'microsoft_onelake_oauth',
    // BambooHR
    'BambooHROAuthCredential': 'bamboohr_oauth',
    'BambooHRApiKeyCredential': 'bamboohr_api_key',

    // Klaviyo
    'KlaviyoOAuthCredential': 'klaviyo_oauth',
    'KlaviyoApiKeyCredential': 'klaviyo_api_key',

    // Typeform
    'TypeformOAuthCredential': 'typeform_oauth',
    'TypeformPATCredential': 'typeform_pat',

    // WhatsApp
    'WhatsAppQRCredential': 'whatsapp_qr',

    // Google DV360
    'DV360OAuthCredential': 'dv360_oauth',
    'DV360ServiceAccountCredential': 'dv360_service_account',

}, INTEGRATION_METADATA.credentialTypes);

/**
 * Get credential type from schema title.
 * Falls back to lowercase title if not found in map.
 */
export function getCredentialTypeFromSchemaTitle(schemaTitle: string): string {
    return CREDENTIAL_TYPE_MAP[schemaTitle] || schemaTitle.toLowerCase();
}
