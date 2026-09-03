/**
 * Shared OAuth provider configuration used across credential selection components.
 * Centralizes provider names, icons, credential types, and default scopes.
 */

import { ComponentType, createElement } from 'react';
import {
    SiGoogle,
    SiAirtable,
    SiStripe,
    SiGithub,
    SiGitlab,
    SiSalesforce,
    SiLinear,
    SiLinkedin,
    SiReddit,
    SiNotion,
    SiX,
    SiDiscord,
    SiDropbox,
    SiShopify,
    SiSlack,
    SiJira,
    SiConfluence,
    SiHubspot,
    SiCanva,
    SiMailchimp,
    SiTelegram,
    SiTiktok,
    SiYoutube,
    SiWordpress,
    SiSupabase,
    SiCaldotcom,
    SiClickup,
    SiBox,
    SiAsana,
    SiIntercom,
    SiZendesk,
    SiPagerduty,
    SiWebflow,
    SiZoom,
    SiCalendly,
    SiThreads,
    SiCloudflare,
    SiPosthog,
    SiSentry,
    SiFacebook,
    SiMeta,
} from 'react-icons/si';
import { FiLayers } from 'react-icons/fi';
import { BsMicrosoft } from 'react-icons/bs';
import { InstagramIcon } from '~/components/icons/InstagramIcon';
import { TypeformIcon } from '~/components/icons/TypeformIcon';
import { MondayIcon } from '~/components/icons/MondayIcon';
import { AttioIcon } from '~/components/icons/AttioIcon';

const ApolloProviderIcon: ComponentType<{ className?: string }> = ({
    className,
}) => createElement('img', { src: '/icons/apollo.svg', alt: '', className });

// ============================================================================
// Types
// ============================================================================

/** A provider-intrinsic input the user must supply BEFORE the OAuth popup (e.g. Shopify
 *  store, Zendesk subdomain, Atlassian site — the OAuth host/tenant is scoped by it).
 *  Declared once here so both the in-app UI and the public provide link collect it. */
export interface OAuthConnectInput {
    /** Which positional connect() arg this feeds: shop/subdomain → 4th, site → 5th. */
    kind: 'shop' | 'subdomain' | 'site';
    /** Field label (e.g. "Store name"). */
    label: string;
    /** Domain suffix shown after the input and stripped on normalize (e.g. ".myshopify.com"). */
    suffix: string;
    /** Input placeholder (e.g. "my-store"). */
    placeholder: string;
    /** Optional help text under the field. */
    help?: string;
}

export interface OAuthProviderConfig {
    /** Display name for the provider */
    name: string;
    /** Icon component for the provider */
    Icon: ComponentType<{ className?: string }>;
    /** Brand color for the icon (Tailwind `text-*` class or hex); '' / absent = untinted. */
    iconColor?: string;
    /** OAuth provider key (used by useCredentialOAuth and OAuth handlers) */
    oauthProvider: string;
    /** Credential types that belong to this provider (DB credential_type values) */
    credentialTypes: string[];
    /** Default OAuth scopes to request */
    defaultScopes?: string[];
    /** Pre-connect input this provider requires (shop/subdomain/site). Absent = none. */
    connectInput?: OAuthConnectInput;
    /** OAuth flow has an in-popup account/resource selection step that the public provide
     *  link can't complete (the HTTP transport only supports the single redirect exchange).
     *  The provide page gates these; they must be connected in-app. */
    oauthNeedsInAppSelection?: boolean;
    /**
     * Scopes ALWAYS appended to whatever service scopes are requested for this
     * provider (identity/refresh scopes it needs regardless of which APIs are
     * chosen — e.g. Google's `email`/`profile`, Microsoft's `offline_access`).
     * Single source of truth: applied via `augmentScopes()` by BOTH the per-provider
     * connect hooks and the credential-request link, so the two can't drift.
     */
    extraScopes?: string[];
    /**
     * The provider has a tenant-wide admin-consent grant (Microsoft Entra). The connect
     * form then offers "approve for your organization": one admin consents once and every
     * user in that directory connects without the "Need admin approval" wall. Served by the
     * provider's authorize route via `?admin_consent=1`.
     */
    supportsOrgConsent?: boolean;
}

// eslint-disable-next-line react/prop-types
const QuickBooksProviderIcon: ComponentType<{ className?: string }> = ({
    className,
}) =>
    createElement('img', { src: '/icons/quickbooks.svg', alt: '', className });

// Credentials-view only: grayscale the brand SVG so it reads neutral in the
// OAuth connect button. The canvas node (BambooHRNode.tsx) keeps full-color brand.
// eslint-disable-next-line react/prop-types
const BambooHRProviderIcon: ComponentType<{ className?: string }> = ({
    className,
}) =>
    createElement('img', {
        src: '/icons/bamboohr.svg',
        alt: '',
        className: `${className ?? ''} grayscale`.trim(),
    });

// Credentials-view only: grayscale Fathom's multicolor teal brand SVG so it
// reads neutral in the credential picker + OAuth connect button. The canvas node
// (FathomNode.tsx) keeps the full-color mark. Same pattern as BambooHR above.
// eslint-disable-next-line react/prop-types
const FathomProviderIcon: ComponentType<{ className?: string }> = ({
    className,
}) =>
    createElement('img', {
        src: '/icons/fathom.svg',
        alt: '',
        className: `${className ?? ''} grayscale`.trim(),
    });

// eslint-disable-next-line react/prop-types
const KlaviyoProviderIcon: ComponentType<{ className?: string }> = ({
    className,
}) => createElement('img', { src: '/icons/klaviyo.svg', alt: '', className });

// ============================================================================
// Provider Configuration
// ============================================================================

/**
 * Map from provider keys to their configuration.
 * Keys are the values from x-oauth-provider in JSON schemas.
 */
export const OAUTH_PROVIDER_CONFIG: Record<string, OAuthProviderConfig> = {
    google: {
        name: 'Google',
        Icon: SiGoogle,
        oauthProvider: 'google',
        credentialTypes: [
            'google_sheets_oauth',
            'google_drive_oauth',
            'google_gmail_oauth',
            'google_youtube_oauth',
            'google_calendar_oauth',
            'google_tasks_oauth',
            'google_contacts_oauth',
            'google_docs_oauth',
            'google_forms_oauth',
            'google_slides_oauth',
            'google_analytics_oauth',
            'google_ads_oauth',
            'google_business_profile_oauth',
            'google_search_console_oauth',
            'firestore_oauth',
            'google_meet_oauth',
            'google_translate_oauth',
            'bigquery_oauth',
            'dv360_oauth',
        ],
        defaultScopes: [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive',
        ],
        extraScopes: ['email', 'profile'],
    },
    github: {
        name: 'GitHub',
        Icon: SiGithub,
        oauthProvider: 'github',
        credentialTypes: ['github_oauth', 'github_pat'],
    },
    gitlab: {
        name: 'GitLab',
        Icon: SiGitlab,
        oauthProvider: 'gitlab',
        credentialTypes: ['gitlab_oauth', 'gitlab_token'],
        defaultScopes: ['api', 'read_user'],
    },
    airtable: {
        name: 'Airtable',
        Icon: SiAirtable,
        oauthProvider: 'airtable',
        credentialTypes: ['airtable_oauth', 'airtable_pat'],
    },
    zendesk: {
        name: 'Zendesk',
        // No iconColor — render the Zendesk mark in the default (neutral) color.
        Icon: SiZendesk,
        oauthProvider: 'zendesk',
        credentialTypes: [
            'zendesk_oauth',
            'zendesk_api_token',
            'zendesk_conversations',
        ],
        defaultScopes: ['read', 'write'],
        connectInput: {
            kind: 'subdomain',
            label: 'Subdomain',
            suffix: '.zendesk.com',
            placeholder: 'acme',
        },
    },
    bamboohr: {
        name: 'BambooHR',
        Icon: BambooHRProviderIcon,
        oauthProvider: 'bamboohr',
        credentialTypes: ['bamboohr_oauth', 'bamboohr_api_key'],
        defaultScopes: [
            'company:details',
            'company:info',
            'company_file',
            'company_file.write',
            'employee',
            'employee.write',
            'employee:file',
            'employee:file.write',
            'employee:photo',
            'employee_directory',
            'meta',
            'offline_access',
            'openid',
            'report',
            'report.write',
            'time_off',
            'time_off.write',
            'time_tracking',
            'time_tracking.write',
            'user',
            'webhooks',
            'webhooks.write',
        ],
        connectInput: {
            kind: 'subdomain',
            label: 'Company Subdomain',
            suffix: '.bamboohr.com',
            placeholder: 'acme',
        },
    },
    klaviyo: {
        name: 'Klaviyo',
        Icon: KlaviyoProviderIcon,
        oauthProvider: 'klaviyo',
        credentialTypes: ['klaviyo_oauth', 'klaviyo_api_key'],
        defaultScopes: [
            'accounts:read',
            'campaigns:read',
            'campaigns:write',
            'catalogs:read',
            'catalogs:write',
            'coupon-codes:read',
            'coupon-codes:write',
            'coupons:read',
            'coupons:write',
            'data-privacy:write',
            'events:read',
            'events:write',
            'flows:read',
            'flows:write',
            'images:read',
            'images:write',
            'lists:read',
            'lists:write',
            'metrics:read',
            'profiles:read',
            'profiles:write',
            'segments:read',
            'segments:write',
            'subscriptions:read',
            'subscriptions:write',
            'tags:read',
            'tags:write',
            'templates:read',
            'templates:write',
            'webhooks:read',
            'webhooks:write',
        ],
    },
    pagerduty: {
        name: 'PagerDuty',
        // No iconColor — render the PagerDuty mark in the default (neutral) color.
        Icon: SiPagerduty,
        oauthProvider: 'pagerduty',
        credentialTypes: ['pagerduty_oauth', 'pagerduty_api_key'],
        defaultScopes: [
            'abilities.read',
            'addons.read',
            'addons.write',
            'analytics.read',
            'analytics.write',
            'audit_records.read',
            'change_events.read',
            'custom_fields.read',
            'custom_fields.write',
            'escalation_policies.read',
            'escalation_policies.write',
            'event_orchestrations.read',
            'event_orchestrations.write',
            'event_rules.read',
            'event_rules.write',
            'extension_schemas.read',
            'extensions.read',
            'extensions.write',
            'incident_workflows.read',
            'incident_workflows.write',
            'incident_workflows:instances.write',
            'incidents.read',
            'incidents.write',
            'licenses.read',
            'oncalls.read',
            'priorities.read',
            'read',
            'schedules.read',
            'schedules.write',
            'services.read',
            'services.write',
            'status_dashboards.read',
            'status_pages.read',
            'status_pages.write',
            'subscribers.read',
            'subscribers.write',
            'tags.read',
            'tags.write',
            'teams.read',
            'teams.write',
            'templates.read',
            'templates.write',
            'users.read',
            'users.write',
            'users:contact_methods.read',
            'users:contact_methods.write',
            'vendors.read',
            'webhook_subscriptions.read',
            'webhook_subscriptions.write',
            'write',
        ],
    },
    stripe: {
        name: 'Stripe',
        Icon: SiStripe,
        oauthProvider: 'stripe',
        credentialTypes: ['stripe_oauth', 'stripe_api_key'],
        defaultScopes: ['read_write'],
    },
    salesforce: {
        name: 'Salesforce',
        Icon: SiSalesforce,
        oauthProvider: 'salesforce',
        credentialTypes: ['salesforce_oauth'],
    },
    linear: {
        name: 'Linear',
        Icon: SiLinear,
        oauthProvider: 'linear',
        credentialTypes: ['linear_oauth', 'linear_pat'],
    },
    quickbooks: {
        name: 'QuickBooks',
        Icon: QuickBooksProviderIcon,
        oauthProvider: 'quickbooks',
        credentialTypes: ['quickbooks_oauth'],
        defaultScopes: [
            'com.intuit.quickbooks.accounting',
            'email',
            'openid',
            'profile',
        ],
    },
    calcom: {
        name: 'Cal.com',
        Icon: SiCaldotcom,
        oauthProvider: 'calcom',
        credentialTypes: ['cal_com_oauth', 'cal_com_api_key'],
    },
    calendly: {
        name: 'Calendly',
        // No iconColor — render the mark neutral in the credentials view. The
        // canvas node keeps its full-color brand SVG (CalendlyNode.tsx img).
        Icon: SiCalendly,
        oauthProvider: 'calendly',
        credentialTypes: ['calendly_oauth', 'calendly_pat'],
    },
    sentry: {
        name: 'Sentry',
        // No iconColor — render the mark neutral in the credentials view. The
        // canvas node keeps its brand-purple mark (SentryNode.tsx).
        Icon: SiSentry,
        oauthProvider: 'sentry',
        credentialTypes: ['sentry_oauth', 'sentry_auth_token'],
    },
    posthog: {
        name: 'PostHog',
        // No iconColor — render the mark neutral in the credentials view. The
        // canvas node keeps its full-color brand SVG (PostHogNode.tsx img).
        Icon: SiPosthog,
        oauthProvider: 'posthog',
        credentialTypes: [
            'posthog_oauth',
            'posthog_personal_api_key',
            'posthog_project_api_key',
        ],
    },
    clickup: {
        name: 'ClickUp',
        Icon: SiClickup,
        oauthProvider: 'clickup',
        credentialTypes: ['clickup_oauth', 'clickup_pat'],
    },
    asana: {
        name: 'Asana',
        Icon: SiAsana,
        oauthProvider: 'asana',
        credentialTypes: ['asana_oauth'],
    },
    attio: {
        name: 'Attio',
        Icon: AttioIcon as ComponentType<{ className?: string }>,
        oauthProvider: 'attio',
        credentialTypes: ['attio_oauth', 'attio_api_key'],
        defaultScopes: [
            'user_management:read',
            'record_permission:read-write',
            'object_configuration:read-write',
            'list_entry:read-write',
            'list_configuration:read-write',
            'comment:read-write',
            'note:read-write',
            'task:read-write',
            'meeting:read',
            'call_recording:read',
            'webhook:read-write',
            'file:read',
        ],
    },
    linkedin: {
        name: 'LinkedIn',
        Icon: SiLinkedin,
        oauthProvider: 'linkedin',
        credentialTypes: ['linkedin_oauth'],
    },
    reddit: {
        name: 'Reddit',
        Icon: SiReddit,
        oauthProvider: 'reddit',
        credentialTypes: ['reddit_oauth'],
    },
    notion: {
        name: 'Notion',
        Icon: SiNotion,
        oauthProvider: 'notion',
        credentialTypes: ['notion_oauth', 'notion_integration_token'],
    },
    microsoft: {
        name: 'Microsoft',
        Icon: BsMicrosoft,
        oauthProvider: 'microsoft',
        credentialTypes: [
            'microsoft_outlook_oauth',
            'microsoft_excel_oauth',
            'microsoft_onedrive_oauth',
            'microsoft_word_oauth',
            'microsoft_teams_oauth',
            'microsoft_sharepoint_oauth',
            'microsoft_todo_oauth',
            'microsoft_onelake_oauth',
        ],
        extraScopes: [
            'https://graph.microsoft.com/User.Read',
            'offline_access',
        ],
        supportsOrgConsent: true,
    },
    discord: {
        name: 'Discord',
        // No iconColor — render the Discord mark in the default (neutral) color
        // in credential surfaces; the canvas node (DiscordNode.tsx) keeps brand.
        Icon: SiDiscord,
        oauthProvider: 'discord',
        credentialTypes: [
            'discord_oauth',
            'discord_bot_install',
            'discord_bot_token',
        ],
    },
    box: {
        name: 'Box',
        Icon: SiBox,
        oauthProvider: 'box',
        credentialTypes: ['box_oauth', 'box_developer_token'],
    },
    dropbox: {
        name: 'Dropbox',
        Icon: SiDropbox,
        oauthProvider: 'dropbox',
        credentialTypes: ['dropbox_oauth'],
    },
    facebook: {
        name: 'Instagram',
        Icon: InstagramIcon as ComponentType<{ className?: string }>,
        oauthProvider: 'facebook',
        credentialTypes: ['instagram_oauth'],
        oauthNeedsInAppSelection: true, // picks an Instagram account after the popup
    },
    facebook_pages: {
        name: 'Facebook',
        Icon: SiFacebook,
        iconColor: 'text-[#1877F2]',
        oauthProvider: 'facebook_pages',
        credentialTypes: ['facebook_oauth', 'facebook_access_token'],
    },
    fathom: {
        name: 'Fathom',
        Icon: FathomProviderIcon,
        oauthProvider: 'fathom',
        credentialTypes: ['fathom_oauth'],
        defaultScopes: ['public_api'],
    },
    threads: {
        name: 'Threads',
        // No iconColor — render the Threads mark in the default (neutral) color.
        Icon: SiThreads,
        oauthProvider: 'threads',
        credentialTypes: ['threads_oauth', 'threads_access_token'],
    },

    meta: {
        name: 'Meta',
        iconColor: 'text-[#0866FF]',
        Icon: SiMeta,
        oauthProvider: 'meta',
        credentialTypes: ['meta_oauth', 'meta_access_token'],
    },

    // Instagram API *with Instagram Login* — Page-free connect (graph.instagram.com),
    // distinct from the `facebook`-keyed Instagram-with-Facebook-Login flow above.
    instagram_login: {
        name: 'Instagram',
        Icon: InstagramIcon as ComponentType<{ className?: string }>,
        oauthProvider: 'instagram_login',
        credentialTypes: ['instagram_login'],
    },

    tiktok: {
        name: 'TikTok',
        Icon: SiTiktok,
        oauthProvider: 'tiktok',
        credentialTypes: ['tiktok_oauth'],
        defaultScopes: [
            'user.info.basic',
            'user.info.profile',
            'user.info.stats',
            'video.list',
            'video.publish',
            'video.upload',
        ],
    },
    twitter: {
        name: 'Twitter',
        Icon: SiX,
        oauthProvider: 'twitter',
        credentialTypes: ['twitter_oauth', 'twitter_bearer_token'],
    },
    shopify: {
        name: 'Shopify',
        Icon: SiShopify,
        oauthProvider: 'shopify',
        credentialTypes: ['shopify_oauth', 'shopify_access_token'],
        connectInput: {
            kind: 'shop',
            label: 'Store name',
            suffix: '.myshopify.com',
            placeholder: 'my-store',
        },
    },
    slack: {
        name: 'Slack',
        Icon: SiSlack,
        oauthProvider: 'slack',
        credentialTypes: ['slack_oauth', 'slack_bot_token'],
    },
    atlassian: {
        name: 'Jira',
        Icon: SiJira,
        oauthProvider: 'atlassian',
        credentialTypes: [
            'jira_oauth',
            'jira_api_token',
            'confluence_oauth',
            'confluence_api_token',
        ],
        defaultScopes: [
            'delete:sprint:jira-software',
            'manage:jira-configuration',
            'manage:jira-project',
            'manage:jira-webhook',
            'offline_access',
            'read:board-scope:jira-software',
            'read:epic:jira-software',
            'read:issue-details:jira',
            'read:jira-user',
            'read:jira-work',
            'read:jql:jira',
            'read:project:jira',
            'read:sprint:jira-software',
            'write:epic:jira-software',
            'write:jira-work',
            'write:sprint:jira-software',
        ],
        connectInput: {
            kind: 'site',
            label: 'Jira site',
            suffix: '.atlassian.net',
            placeholder: 'your-company',
            help: 'Use the Jira site this Atlassian account can access. Atlassian may display a different signed-in site on the consent page; NoClick verifies this exact site after consent before saving the credential.',
        },
    },
    hubspot: {
        name: 'HubSpot',
        Icon: SiHubspot,
        oauthProvider: 'hubspot',
        credentialTypes: ['hubspot_oauth', 'hubspot_pat'],
    },
    canva: {
        name: 'Canva',
        Icon: SiCanva,
        oauthProvider: 'canva',
        credentialTypes: ['canva_oauth'],
    },
    mailchimp: {
        name: 'Mailchimp',
        Icon: SiMailchimp,
        oauthProvider: 'mailchimp',
        credentialTypes: ['mailchimp_oauth', 'mailchimp_api_key'],
    },
    typeform: {
        name: 'Typeform',
        Icon: TypeformIcon as ComponentType<{ className?: string }>,
        oauthProvider: 'typeform',
        credentialTypes: ['typeform_oauth', 'typeform_pat'],
    },
    wordpress: {
        name: 'WordPress',
        Icon: SiWordpress,
        oauthProvider: 'wordpress',
        credentialTypes: [
            'wordpress_oauth',
            'wordpress_application_password',
            'wordpress_basic_auth',
        ],
        defaultScopes: ['global'],
    },
    supabase: {
        name: 'Supabase',
        Icon: SiSupabase,
        oauthProvider: 'supabase',
        credentialTypes: ['supabase_oauth'],
        oauthNeedsInAppSelection: true, // picks a project after the popup
    },
    monday: {
        name: 'Monday.com',
        Icon: MondayIcon as ComponentType<{ className?: string }>,
        oauthProvider: 'monday',
        credentialTypes: ['monday_oauth', 'monday_api_token'],
    },
    parallel: {
        name: 'Parallel',
        Icon: FiLayers,
        oauthProvider: 'parallel',
        credentialTypes: ['parallel_oauth', 'parallel_api_key'],
        defaultScopes: ['key:read'],
    },
    intercom: {
        name: 'Intercom',
        Icon: SiIntercom,
        oauthProvider: 'intercom',
        credentialTypes: ['intercom_oauth'],
        defaultScopes: [
            'read_admins',
            'read_teams',
            'read_write_companies',
            'read_write_conversations',
            'read_write_events',
            'read_write_tags',
            'read_write_tickets',
            'read_write_users',
        ],
    },
    webflow: {
        name: 'Webflow',
        Icon: SiWebflow,
        oauthProvider: 'webflow',
        credentialTypes: ['webflow_oauth', 'webflow_api_token'],
    },
    zoom: {
        name: 'Zoom',
        // No iconColor — render the Zoom mark in the default (neutral) color.
        Icon: SiZoom,
        oauthProvider: 'zoom',
        credentialTypes: ['zoom_oauth', 'zoom_server_to_server'],
        defaultScopes: [
            'chat_message:write:message',
            'cloud_recording:delete:meeting_recordings',
            'cloud_recording:read:list_account_recordings',
            'cloud_recording:read:list_recording_files',
            'cloud_recording:read:list_user_recordings',
            'meeting:read:invitation',
            'meeting:read:list_meetings',
            'meeting:read:list_past_participants',
            'meeting:read:list_registrants',
            'meeting:read:meeting',
            'meeting:read:past_meeting',
            'meeting:write:meeting',
            'meeting:write:registrant',
            'phone:read:list_call_logs',
            'user:read:list_users',
            'user:read:user',
            'user:write:user',
            'webinar:read:list_registrants',
            'webinar:read:list_webinars',
            'webinar:read:webinar',
            'webinar:write:registrant',
            'webinar:write:webinar',
        ],
    },
    cloudflare: {
        name: 'Cloudflare',
        Icon: SiCloudflare,
        // No iconColor — render the Cloudflare mark in the default (neutral) color.
        oauthProvider: 'cloudflare',
        credentialTypes: ['cloudflare_oauth'],
    },
    apollo: {
        name: 'Apollo',
        Icon: ApolloProviderIcon,
        oauthProvider: 'apollo',
        credentialTypes: ['apollo_oauth'],
        defaultScopes: [
            'read_user_profile',
            'people_match',
            'people_bulk_match',
            'organizations_enrich',
            'organizations_bulk_enrich',
            'organizations_search',
            'organization_read',
            'mixed_people_api_search',
            'mixed_companies_search',
            'contacts_search',
            'contact_read',
            'contact_write',
            'contact_update',
            'contacts_bulk_create',
            'contacts_bulk_update',
            'contact_stages_list',
            'contact_stages_update',
            'contact_owners_update',
            'account_read',
            'account_write',
            'account_update',
            'accounts_search',
            'account_bulk_create',
            'account_stages_list',
            'account_stages_update',
            'account_owners_update',
            'opportunity_read',
            'opportunity_write',
            'opportunity_update',
            'opportunities_list',
            'opportunity_stages_list',
            'emailer_campaigns_search',
            'emailer_campaigns_create',
            'emailer_campaigns_update',
            'emailer_campaigns_add_contact_ids',
            'emailer_campaigns_remove_or_stop_contact_ids',
            'emailer_schedules_list',
            'emailer_messages_search',
            'tasks_create',
            'tasks_list',
            'notes_list',
            'users_list',
            'tags_list',
            'custom_fields_list',
            'custom_field_write',
            'lists_create',
            'lists_update',
            'lists_add_entities',
            'lists_remove_entities',
            'organizations_job_posting',
            'organizations_news_articles',
            'person_read',
        ],
    },
};

/**
 * Extended provider aliases for GenerationCredentialSelector.
 * Maps service-specific keys to provider configs.
 */
export const PROVIDER_ALIASES: Record<string, OAuthProviderConfig> = {
    // Instagram uses Facebook OAuth
    instagram: {
        name: 'Instagram',
        Icon: InstagramIcon as ComponentType<{ className?: string }>,
        oauthProvider: 'facebook',
        credentialTypes: ['instagram_oauth'],
    },
    // Telegram doesn't use OAuth but needs config for display
    telegram: {
        name: 'Telegram',
        Icon: SiTelegram,
        oauthProvider: '', // Uses bot tokens, not OAuth
        credentialTypes: ['telegram_bot_token'],
    },
    // YouTube uses Google OAuth
    youtube: {
        name: 'YouTube',
        Icon: SiYoutube,
        oauthProvider: 'google',
        credentialTypes: ['google_youtube_oauth'],
        defaultScopes: [
            'https://www.googleapis.com/auth/youtube.force-ssl',
            'https://www.googleapis.com/auth/youtube.upload',
            'https://www.googleapis.com/auth/yt-analytics.readonly',
            'https://www.googleapis.com/auth/yt-analytics-monetary.readonly',
            'https://www.googleapis.com/auth/youtube.channel-memberships.creator',
        ],
    },
    // Jira alias (maps to atlassian)
    jira: {
        name: 'Jira',
        Icon: SiJira,
        oauthProvider: 'atlassian',
        credentialTypes: ['jira_oauth', 'jira_api_token'],
        defaultScopes: [
            'delete:sprint:jira-software',
            'manage:jira-configuration',
            'manage:jira-project',
            'manage:jira-webhook',
            'offline_access',
            'read:board-scope:jira-software',
            'read:epic:jira-software',
            'read:issue-details:jira',
            'read:jira-user',
            'read:jira-work',
            'read:jql:jira',
            'read:project:jira',
            'read:sprint:jira-software',
            'write:epic:jira-software',
            'write:jira-work',
            'write:sprint:jira-software',
        ],
    },
    // Confluence alias (maps to atlassian with Confluence-specific scopes)
    confluence: {
        name: 'Confluence',
        // No iconColor — render the Confluence mark in the default (neutral) color
        // in credential surfaces; the canvas node (ConfluenceNode.tsx) keeps brand.
        Icon: SiConfluence,
        oauthProvider: 'atlassian',
        credentialTypes: ['confluence_oauth', 'confluence_api_token'],
        defaultScopes: [
            'delete:attachment:confluence',
            'delete:blogpost:confluence',
            'delete:comment:confluence',
            'delete:content-details:confluence',
            'delete:page:confluence',
            'offline_access',
            'read:attachment:confluence',
            'read:blogpost:confluence',
            'read:comment:confluence',
            'read:confluence-content.all',
            'read:confluence-content.summary',
            'read:confluence-groups',
            'read:confluence-props',
            'read:confluence-space.summary',
            'read:confluence-user',
            'read:content-details:confluence',
            'read:group:confluence',
            'read:inlinetask:confluence',
            'read:label:confluence',
            'read:page:confluence',
            'read:space:confluence',
            'read:task:confluence',
            'read:user:confluence',
            'readonly:content.attachment:confluence',
            'search:confluence',
            'write:attachment:confluence',
            'write:blogpost:confluence',
            'write:comment:confluence',
            'write:confluence-content',
            'write:confluence-file',
            'write:confluence-props',
            'write:confluence-space',
            'write:content-details:confluence',
            'write:inlinetask:confluence',
            'write:label:confluence',
            'write:page:confluence',
            'write:space:confluence',
            'write:task:confluence',
        ],
    },
    // Google service-specific aliases
    google_sheets: {
        name: 'Google Sheets',
        Icon: SiGoogle,
        oauthProvider: 'google',
        credentialTypes: ['google_sheets_oauth'],
        defaultScopes: [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive.metadata.readonly',
        ],
    },
    google_drive: {
        name: 'Google Drive',
        Icon: SiGoogle,
        oauthProvider: 'google',
        credentialTypes: ['google_drive_oauth'],
        defaultScopes: ['https://www.googleapis.com/auth/drive'],
    },
    gmail: {
        name: 'Gmail',
        Icon: SiGoogle,
        oauthProvider: 'google',
        credentialTypes: ['google_gmail_oauth'],
        defaultScopes: [
            'https://www.googleapis.com/auth/gmail.modify',
            'https://www.googleapis.com/auth/gmail.compose',
            'https://www.googleapis.com/auth/gmail.labels',
            'https://www.googleapis.com/auth/gmail.settings.basic',
        ],
    },
    google_calendar: {
        name: 'Google Calendar',
        Icon: SiGoogle,
        oauthProvider: 'google',
        credentialTypes: ['google_calendar_oauth'],
        defaultScopes: ['https://www.googleapis.com/auth/calendar'],
    },
    google_tasks: {
        name: 'Google Tasks',
        Icon: SiGoogle,
        oauthProvider: 'google',
        credentialTypes: ['google_tasks_oauth'],
        defaultScopes: ['https://www.googleapis.com/auth/tasks'],
    },
    google_contacts: {
        name: 'Google Contacts',
        Icon: SiGoogle,
        oauthProvider: 'google',
        credentialTypes: ['google_contacts_oauth'],
        defaultScopes: ['https://www.googleapis.com/auth/contacts'],
    },
    google_docs: {
        name: 'Google Docs',
        Icon: SiGoogle,
        oauthProvider: 'google',
        credentialTypes: ['google_docs_oauth'],
        defaultScopes: [
            'https://www.googleapis.com/auth/documents',
            'https://www.googleapis.com/auth/drive',
        ],
    },
    google_forms: {
        name: 'Google Forms',
        Icon: SiGoogle,
        oauthProvider: 'google',
        credentialTypes: ['google_forms_oauth'],
        defaultScopes: [
            'https://www.googleapis.com/auth/forms.body',
            'https://www.googleapis.com/auth/forms.responses.readonly',
            'https://www.googleapis.com/auth/drive',
        ],
    },
    google_analytics: {
        name: 'Google Analytics',
        Icon: SiGoogle,
        oauthProvider: 'google',
        credentialTypes: ['google_analytics_oauth'],
        defaultScopes: ['https://www.googleapis.com/auth/analytics.readonly'],
    },
    google_ads: {
        name: 'Google Ads',
        Icon: SiGoogle,
        oauthProvider: 'google',
        credentialTypes: ['google_ads_oauth'],
        defaultScopes: ['https://www.googleapis.com/auth/adwords'],
    },
    google_business_profile: {
        name: 'Google Business Profile',
        Icon: SiGoogle,
        oauthProvider: 'google',
        credentialTypes: ['google_business_profile_oauth'],
        defaultScopes: ['https://www.googleapis.com/auth/business.manage'],
    },
    google_search_console: {
        name: 'Google Search Console',
        Icon: SiGoogle,
        oauthProvider: 'google',
        credentialTypes: ['google_search_console_oauth'],
        defaultScopes: ['https://www.googleapis.com/auth/webmasters'],
    },
    google_meet: {
        name: 'Google Meet',
        Icon: SiGoogle,
        oauthProvider: 'google',
        credentialTypes: ['google_meet_oauth'],
        defaultScopes: [
            'https://www.googleapis.com/auth/meetings.space.created',
            'https://www.googleapis.com/auth/meetings.space.readonly',
            'https://www.googleapis.com/auth/meetings.space.settings',
        ],
    },
    google_slides: {
        name: 'Google Slides',
        Icon: SiGoogle,
        oauthProvider: 'google',
        credentialTypes: ['google_slides_oauth'],
        defaultScopes: [
            'https://www.googleapis.com/auth/presentations',
            'https://www.googleapis.com/auth/drive',
        ],
    },
    firestore: {
        name: 'Firestore',
        Icon: SiGoogle,
        oauthProvider: 'google',
        credentialTypes: [
            'firestore_oauth',
            'firestore_service_account',
            'firestore_firebase_id_token',
        ],
        defaultScopes: ['https://www.googleapis.com/auth/datastore'],
    },
    // Microsoft service-specific aliases
    outlook: {
        name: 'Outlook',
        Icon: BsMicrosoft,
        oauthProvider: 'microsoft',
        credentialTypes: ['microsoft_outlook_oauth'],
        defaultScopes: [
            'https://graph.microsoft.com/Calendars.Read',
            'https://graph.microsoft.com/Calendars.ReadWrite',
            'https://graph.microsoft.com/Calendars.ReadWrite.Shared',
            'https://graph.microsoft.com/Contacts.Read',
            'https://graph.microsoft.com/Contacts.ReadWrite',
            'https://graph.microsoft.com/Mail.Read',
            'https://graph.microsoft.com/Mail.ReadWrite',
            'https://graph.microsoft.com/Mail.Send',
            'https://graph.microsoft.com/MailboxSettings.ReadWrite',
            'https://graph.microsoft.com/User.Read',
            'offline_access',
        ],
    },
    excel: {
        name: 'Excel',
        Icon: BsMicrosoft,
        oauthProvider: 'microsoft',
        credentialTypes: ['microsoft_excel_oauth'],
        defaultScopes: [
            'https://graph.microsoft.com/Files.ReadWrite.All',
            'https://graph.microsoft.com/User.Read',
        ],
    },
    onedrive: {
        name: 'OneDrive',
        Icon: BsMicrosoft,
        oauthProvider: 'microsoft',
        credentialTypes: ['microsoft_onedrive_oauth'],
        defaultScopes: [
            'https://graph.microsoft.com/Files.Read.All',
            'https://graph.microsoft.com/Files.ReadWrite.All',
            'https://graph.microsoft.com/User.Read',
        ],
    },
    teams: {
        name: 'Microsoft Teams',
        Icon: BsMicrosoft,
        oauthProvider: 'microsoft',
        credentialTypes: ['microsoft_teams_oauth'],
        defaultScopes: [
            'https://graph.microsoft.com/Channel.Create',
            'https://graph.microsoft.com/Channel.Delete.All',
            'https://graph.microsoft.com/Channel.ReadBasic.All',
            'https://graph.microsoft.com/ChannelMessage.Read.All',
            'https://graph.microsoft.com/ChannelMessage.Send',
            'https://graph.microsoft.com/Chat.ReadWrite',
            'https://graph.microsoft.com/ChatMessage.Send',
            'https://graph.microsoft.com/OnlineMeetings.ReadWrite',
            'https://graph.microsoft.com/Presence.Read.All',
            'https://graph.microsoft.com/Team.Create',
            'https://graph.microsoft.com/Team.ReadBasic.All',
            'https://graph.microsoft.com/TeamMember.ReadWrite.All',
            'https://graph.microsoft.com/TeamsAppInstallation.ReadWriteForTeam',
            'https://graph.microsoft.com/TeamsTab.ReadWriteForTeam',
            'https://graph.microsoft.com/User.Read',
        ],
    },
    sharepoint: {
        name: 'SharePoint',
        Icon: BsMicrosoft,
        oauthProvider: 'microsoft',
        credentialTypes: ['microsoft_sharepoint_oauth'],
        defaultScopes: [
            'https://graph.microsoft.com/Sites.Read.All',
            'https://graph.microsoft.com/Sites.ReadWrite.All',
            'https://graph.microsoft.com/User.Read',
        ],
    },
    microsoft_todo: {
        name: 'Microsoft To Do',
        Icon: BsMicrosoft,
        oauthProvider: 'microsoft',
        credentialTypes: ['microsoft_todo_oauth'],
        defaultScopes: [
            'https://graph.microsoft.com/Tasks.Read',
            'https://graph.microsoft.com/Tasks.ReadWrite',
            'https://graph.microsoft.com/User.Read',
            'offline_access',
        ],
    },
};

// ============================================================================
// Helper Functions
// ============================================================================

/**
 * Get provider config by provider key (e.g., 'google', 'github').
 * Checks main config first, then aliases.
 */
export function getProviderConfig(
    providerKey: string | undefined
): OAuthProviderConfig | undefined {
    if (!providerKey) return undefined;
    return OAUTH_PROVIDER_CONFIG[providerKey] || PROVIDER_ALIASES[providerKey];
}

/**
 * Resolve the pre-connect input a provider requires, product-aware for Atlassian
 * (Confluence credentials relabel the Jira-site field). One source both surfaces use.
 */
export function getOAuthConnectInput(
    provider: string | undefined,
    credentialType: string
): OAuthConnectInput | undefined {
    const base = getProviderConfig(provider)?.connectInput;
    if (!base) return undefined;
    if (provider === 'atlassian' && credentialType?.startsWith('confluence')) {
        return {
            ...base,
            label: 'Confluence site',
            help: base.help?.replace(/Jira/g, 'Confluence'),
        };
    }
    return base;
}

/** Whether a provider's OAuth needs an in-app selection step the public provide link
 *  can't complete (Facebook/Instagram account, Supabase project). Used to gate the link. */
export function oauthNeedsInAppSelection(
    provider: string | undefined
): boolean {
    return getProviderConfig(provider)?.oauthNeedsInAppSelection === true;
}

/** Whether a provider offers a tenant-wide admin-consent grant (`supportsOrgConsent`). */
export function providerSupportsOrgConsent(
    provider: string | undefined
): boolean {
    return getProviderConfig(provider)?.supportsOrgConsent === true;
}

/**
 * Append a provider's always-on scopes (`config.extraScopes`) to a requested scope
 * list, de-duplicated. The ONE place per-provider scope augmentation lives — used by
 * the connect hooks AND the credential-request link (and the createOAuthHook factory)
 * so identity/refresh scopes can't be applied to one flow and not the other. Providers
 * with no `extraScopes` (e.g. Slack) pass through unchanged — which is exactly why the
 * link must NOT hardcode Google's `email`/`profile` for all.
 */
export function augmentScopes(
    providerKey: string | undefined,
    scopes: string[]
): string[] {
    const extra = getProviderConfig(providerKey)?.extraScopes ?? [];
    return [...new Set([...scopes, ...extra])];
}

/**
 * Get provider config by normalizing a credential type string.
 * Handles variations like "google-sheets" -> "google_sheets"
 */
export function getProviderConfigNormalized(
    key: string | undefined
): OAuthProviderConfig | undefined {
    if (!key) return undefined;
    const normalized = key.toLowerCase().replace(/-/g, '_');
    return OAUTH_PROVIDER_CONFIG[normalized] || PROVIDER_ALIASES[normalized];
}

/**
 * Get provider config by credential type (e.g., 'google_sheets_oauth').
 * Searches through all providers to find which one owns this credential type.
 */
export function getProviderConfigByCredentialType(
    credentialType: string
): OAuthProviderConfig | undefined {
    // Prefer the most-specific match (fewest credentialTypes) so that e.g.
    // 'google_youtube_oauth' resolves to the 'youtube' provider (1 type) rather
    // than the generic 'google' provider (10 types) which has wrong default scopes.
    let bestMatch: OAuthProviderConfig | undefined;
    for (const config of Object.values(OAUTH_PROVIDER_CONFIG)) {
        if (config.credentialTypes.includes(credentialType)) {
            if (
                !bestMatch ||
                config.credentialTypes.length < bestMatch.credentialTypes.length
            ) {
                bestMatch = config;
            }
        }
    }
    if (bestMatch) return bestMatch;
    // Check aliases
    for (const config of Object.values(PROVIDER_ALIASES)) {
        if (config.credentialTypes.includes(credentialType)) {
            return config;
        }
    }
    // Node-backed credential types are resolved by credentialIcons.tsx via the
    // registry-free node-icon singleton BEFORE falling back to this function,
    // so unknown types are simply undefined here (callers all handle it).
    return undefined;
}

/**
 * Get provider key from credential type.
 */
export function getProviderKeyFromCredentialType(
    credentialType: string
): string | undefined {
    for (const [key, config] of Object.entries(OAUTH_PROVIDER_CONFIG)) {
        if (config.credentialTypes.includes(credentialType)) {
            return key;
        }
    }
    return undefined;
}

/**
 * Get all provider keys (for iteration).
 */
export function getAllProviderKeys(): string[] {
    return Object.keys(OAUTH_PROVIDER_CONFIG);
}
