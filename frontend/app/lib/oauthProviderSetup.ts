// GENERATED. Provider labels from the provider key (brand casing applied);
// console URLs from the schemas' x-credential-url where declared, hand-filled
// otherwise; env vars read from the source that actually consumes them —
// frontendEnv from the Remix authorize/callback routes, backendEnv from the
// Python OAuth modules. The split matters: CLIENT_ID is needed by BOTH
// processes, CLIENT_SECRET only by the backend, REDIRECT_URI only by the
// frontend — telling someone to put them all in one file does not work.
//
// Standalone rather than reusing utils/oauthProviders.ts: that module pulls
// react-icons, and this map is imported by server-only routes.

export interface OAuthProviderSetup {
    label: string;
    /** Where the operator creates the OAuth app. */
    consoleUrl?: string;
    /** Connects through the app registered under this other provider key
     *  (Facebook Pages rides the Facebook app); not offered separately. */
    appOf?: string;
    /** Read by the Remix process (frontend/.env). */
    frontendEnv: string[];
    /** Read by the Python process (backend/.env). Empty for PKCE providers. */
    backendEnv: string[];
}

export const OAUTH_PROVIDER_SETUP: Record<string, OAuthProviderSetup> = {
    "airtable": { label: "Airtable", consoleUrl: "https://airtable.com/create/oauth", frontendEnv: ["AIRTABLE_CLIENT_ID", "AIRTABLE_REDIRECT_URI"], backendEnv: ["AIRTABLE_CLIENT_ID", "AIRTABLE_CLIENT_SECRET"] },
    "apollo": { label: "Apollo", consoleUrl: "https://developer.apollo.io/", frontendEnv: ["APOLLO_CLIENT_ID", "APOLLO_REDIRECT_URI"], backendEnv: ["APOLLO_CLIENT_ID", "APOLLO_CLIENT_SECRET"] },
    "asana": { label: "Asana", consoleUrl: "https://app.asana.com/0/my-apps", frontendEnv: ["ASANA_CLIENT_ID", "ASANA_REDIRECT_URI"], backendEnv: ["ASANA_CLIENT_ID", "ASANA_CLIENT_SECRET"] },
    "atlassian": { label: "Atlassian", consoleUrl: "https://developer.atlassian.com/console/myapps/", frontendEnv: ["ATLASSIAN_CLIENT_ID", "ATLASSIAN_REDIRECT_URI"], backendEnv: ["ATLASSIAN_CLIENT_ID", "ATLASSIAN_CLIENT_SECRET"] },
    "attio": { label: "Attio", consoleUrl: "https://app.attio.com/settings/developers", frontendEnv: ["ATTIO_CLIENT_ID", "ATTIO_REDIRECT_URI"], backendEnv: ["ATTIO_CLIENT_ID", "ATTIO_CLIENT_SECRET"] },
    "bamboohr": { label: "BambooHR", consoleUrl: "https://documentation.bamboohr.com/page/authenticate-integration", frontendEnv: ["BAMBOOHR_CLIENT_ID", "BAMBOOHR_REDIRECT_URI"], backendEnv: ["BAMBOOHR_CLIENT_ID", "BAMBOOHR_CLIENT_SECRET"] },
    "box": { label: "Box", consoleUrl: "https://app.box.com/developers/console", frontendEnv: ["BOX_CLIENT_ID", "BOX_REDIRECT_URI"], backendEnv: ["BOX_CLIENT_ID", "BOX_CLIENT_SECRET"] },
    "calcom": { label: "Cal.com", consoleUrl: "https://app.cal.com/settings/developer/api-keys", frontendEnv: ["CALCOM_CLIENT_ID", "CALCOM_REDIRECT_URI"], backendEnv: ["CALCOM_CLIENT_ID", "CALCOM_CLIENT_SECRET"] },
    "calendly": { label: "Calendly", consoleUrl: "https://developer.calendly.com/", frontendEnv: ["CALENDLY_CLIENT_ID", "CALENDLY_REDIRECT_URI"], backendEnv: ["CALENDLY_CLIENT_ID", "CALENDLY_CLIENT_SECRET"] },
    "canva": { label: "Canva", consoleUrl: "https://www.canva.com/developers/apps", frontendEnv: ["CANVA_CLIENT_ID", "CANVA_REDIRECT_URI"], backendEnv: ["CANVA_CLIENT_ID", "CANVA_CLIENT_SECRET"] },
    "clickup": { label: "ClickUp", consoleUrl: "https://app.clickup.com/settings/apps", frontendEnv: ["CLICKUP_CLIENT_ID", "CLICKUP_REDIRECT_URI"], backendEnv: ["CLICKUP_CLIENT_ID", "CLICKUP_CLIENT_SECRET"] },
    "cloudflare": { label: "Cloudflare", consoleUrl: "https://dash.cloudflare.com/profile/api-tokens", frontendEnv: ["CLOUDFLARE_CLIENT_ID", "CLOUDFLARE_REDIRECT_URI"], backendEnv: ["CLOUDFLARE_CLIENT_ID", "CLOUDFLARE_CLIENT_SECRET"] },
    "discord": { label: "Discord", consoleUrl: "https://discord.com/developers/applications", frontendEnv: ["DISCORD_CLIENT_ID", "DISCORD_REDIRECT_URI"], backendEnv: ["DISCORD_CLIENT_ID", "DISCORD_CLIENT_SECRET"] },
    "dropbox": { label: "Dropbox", consoleUrl: "https://www.dropbox.com/developers/apps", frontendEnv: ["DROPBOX_CLIENT_ID", "DROPBOX_REDIRECT_URI"], backendEnv: ["DROPBOX_CLIENT_ID", "DROPBOX_CLIENT_SECRET"] },
    "facebook": { label: "Facebook", consoleUrl: "https://developers.facebook.com/apps/", frontendEnv: ["FACEBOOK_APP_ID", "FACEBOOK_OAUTH_REDIRECT_URI"], backendEnv: ["FACEBOOK_APP_ID", "FACEBOOK_APP_SECRET"] },
    "facebook_pages": { label: "Facebook Pages", consoleUrl: "https://developers.facebook.com/apps/", appOf: "facebook", frontendEnv: ["FACEBOOK_APP_ID", "FACEBOOK_PAGES_REDIRECT_URI"], backendEnv: ["FACEBOOK_APP_ID", "FACEBOOK_APP_SECRET"] },
    "fathom": { label: "Fathom", consoleUrl: "https://fathom.video/apps", frontendEnv: ["FATHOM_CLIENT_ID", "FATHOM_REDIRECT_URI"], backendEnv: ["FATHOM_CLIENT_ID", "FATHOM_CLIENT_SECRET"] },
    "github": { label: "GitHub", consoleUrl: "https://github.com/settings/developers", frontendEnv: ["GITHUB_CLIENT_ID", "GITHUB_REDIRECT_URI"], backendEnv: ["GITHUB_CLIENT_ID", "GITHUB_CLIENT_SECRET"] },
    "gitlab": { label: "GitLab", consoleUrl: "https://gitlab.com/-/user_settings/applications", frontendEnv: ["GITLAB_CLIENT_ID", "GITLAB_REDIRECT_URI"], backendEnv: ["GITLAB_CLIENT_ID", "GITLAB_CLIENT_SECRET"] },
    "google": { label: "Google", consoleUrl: "https://console.cloud.google.com/apis/credentials", frontendEnv: ["GOOGLE_CLIENT_ID", "GOOGLE_REDIRECT_URI"], backendEnv: ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"] },
    "hubspot": { label: "HubSpot", consoleUrl: "https://developers.hubspot.com/docs/apps/developer-platform/list-apps/listing-your-app/create-an-app-listing-setup-guide", frontendEnv: ["HUBSPOT_CLIENT_ID", "HUBSPOT_REDIRECT_URI"], backendEnv: ["HUBSPOT_CLIENT_ID", "HUBSPOT_CLIENT_SECRET"] },
    "intercom": { label: "Intercom", consoleUrl: "https://app.intercom.com/a/apps/_/developer-hub", frontendEnv: ["INTERCOM_CLIENT_ID", "INTERCOM_REDIRECT_URI"], backendEnv: ["INTERCOM_CLIENT_ID", "INTERCOM_CLIENT_SECRET"] },
    "intuit": { label: "Intuit", frontendEnv: ["QUICKBOOKS_CLIENT_ID", "INTUIT_CLIENT_ID", "QUICKBOOKS_REDIRECT_URI", "INTUIT_REDIRECT_URI"], backendEnv: ["INTUIT_CLIENT_ID", "INTUIT_CLIENT_SECRET", "QUICKBOOKS_CLIENT_ID", "QUICKBOOKS_CLIENT_SECRET"] },
    "klaviyo": { label: "Klaviyo", consoleUrl: "https://developers.klaviyo.com/en/docs/set_up_oauth", frontendEnv: ["KLAVIYO_CLIENT_ID", "KLAVIYO_REDIRECT_URI"], backendEnv: ["KLAVIYO_CLIENT_ID", "KLAVIYO_CLIENT_SECRET"] },
    "linear": { label: "Linear", consoleUrl: "https://linear.app/settings/api", frontendEnv: ["LINEAR_CLIENT_ID", "LINEAR_REDIRECT_URI"], backendEnv: ["LINEAR_CLIENT_ID", "LINEAR_CLIENT_SECRET"] },
    "linkedin": { label: "LinkedIn", consoleUrl: "https://www.linkedin.com/developers/apps", frontendEnv: ["LINKEDIN_CLIENT_ID", "LINKEDIN_REDIRECT_URI"], backendEnv: ["LINKEDIN_CLIENT_ID", "LINKEDIN_CLIENT_SECRET"] },
    "mailchimp": { label: "Mailchimp", consoleUrl: "https://mailchimp.com/developer/marketing/guides/access-user-data-oauth-2/", frontendEnv: ["MAILCHIMP_CLIENT_ID", "MAILCHIMP_REDIRECT_URI"], backendEnv: ["MAILCHIMP_CLIENT_ID", "MAILCHIMP_CLIENT_SECRET"] },
    "meta": { label: "Meta", consoleUrl: "https://developers.facebook.com/apps/", frontendEnv: ["META_APP_ID", "META_REDIRECT_URI"], backendEnv: ["META_APP_ID", "META_APP_SECRET"] },
    "microsoft": { label: "Microsoft", consoleUrl: "https://portal.azure.com/#blade/Microsoft_AAD_RegisteredApps/ApplicationsListBlade", frontendEnv: ["MICROSOFT_CLIENT_ID", "MICROSOFT_REDIRECT_URI"], backendEnv: ["MICROSOFT_CLIENT_ID", "MICROSOFT_CLIENT_SECRET"] },
    "monday": { label: "monday.com", consoleUrl: "https://monday.com/developers/apps", frontendEnv: ["MONDAY_CLIENT_ID", "MONDAY_REDIRECT_URI"], backendEnv: ["MONDAY_CLIENT_ID", "MONDAY_CLIENT_SECRET"] },
    "notion": { label: "Notion", consoleUrl: "https://www.notion.so/my-integrations", frontendEnv: ["NOTION_CLIENT_ID", "NOTION_REDIRECT_URI"], backendEnv: ["NOTION_CLIENT_ID", "NOTION_CLIENT_SECRET"] },
    "pagerduty": { label: "PagerDuty", consoleUrl: "https://developer.pagerduty.com/docs/register-an-app", frontendEnv: ["PAGERDUTY_CLIENT_ID", "PAGERDUTY_REDIRECT_URI"], backendEnv: ["PAGERDUTY_CLIENT_ID", "PAGERDUTY_CLIENT_SECRET"] },
    "parallel": { label: "Parallel", consoleUrl: "https://platform.parallel.ai", frontendEnv: ["PARALLEL_CLIENT_ID"], backendEnv: ["PARALLEL_CLIENT_ID"] },
    "pipedrive": { label: "Pipedrive", consoleUrl: "https://developers.pipedrive.com", frontendEnv: ["PIPEDRIVE_CLIENT_ID", "PIPEDRIVE_REDIRECT_URI"], backendEnv: ["PIPEDRIVE_CLIENT_ID", "PIPEDRIVE_CLIENT_SECRET"] },
    "posthog": { label: "PostHog", consoleUrl: "https://posthog.com/docs/api/oauth", frontendEnv: ["POSTHOG_CLIENT_ID", "POSTHOG_REDIRECT_URI"], backendEnv: ["POSTHOG_CLIENT_ID"] },
    "reddit": { label: "Reddit", consoleUrl: "https://www.reddit.com/prefs/apps", frontendEnv: ["REDDIT_CLIENT_ID", "REDDIT_REDIRECT_URI"], backendEnv: ["REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET"] },
    "salesforce": { label: "Salesforce", consoleUrl: "https://help.salesforce.com/s/articleView?id=sf.connected_app_create.htm", frontendEnv: ["SALESFORCE_CLIENT_ID", "SALESFORCE_REDIRECT_URI"], backendEnv: ["SALESFORCE_CLIENT_ID", "SALESFORCE_CLIENT_SECRET"] },
    "sentry": { label: "Sentry", consoleUrl: "https://docs.sentry.io/api/auth/", frontendEnv: ["SENTRY_CLIENT_ID", "SENTRY_REDIRECT_URI"], backendEnv: ["SENTRY_CLIENT_ID", "SENTRY_CLIENT_SECRET"] },
    "shopify": { label: "Shopify", consoleUrl: "https://partners.shopify.com/", frontendEnv: ["SHOPIFY_CLIENT_ID", "SHOPIFY_REDIRECT_URI"], backendEnv: ["SHOPIFY_CLIENT_ID", "SHOPIFY_CLIENT_SECRET"] },
    "slack": { label: "Slack", consoleUrl: "https://api.slack.com/apps", frontendEnv: ["SLACK_CLIENT_ID", "SLACK_REDIRECT_URI"], backendEnv: ["SLACK_CLIENT_ID", "SLACK_CLIENT_SECRET"] },
    "stripe": { label: "Stripe", consoleUrl: "https://dashboard.stripe.com/settings/connect", frontendEnv: ["STRIPE_CONNECT_CLIENT_ID", "STRIPE_REDIRECT_URI"], backendEnv: ["STRIPE_CONNECT_CLIENT_ID", "STRIPE_CONNECT_CLIENT_SECRET"] },
    "supabase": { label: "Supabase", consoleUrl: "https://supabase.com/dashboard/account/apps", frontendEnv: ["SUPABASE_CLIENT_ID", "SUPABASE_REDIRECT_URI"], backendEnv: ["SUPABASE_CLIENT_ID", "SUPABASE_CLIENT_SECRET"] },
    "threads": { label: "Threads", consoleUrl: "https://developers.facebook.com/apps/", frontendEnv: ["THREADS_CLIENT_ID", "THREADS_REDIRECT_URI"], backendEnv: ["THREADS_CLIENT_ID", "THREADS_CLIENT_SECRET"] },
    "tiktok": { label: "TikTok", consoleUrl: "https://developers.tiktok.com/", frontendEnv: ["TIKTOK_CLIENT_KEY", "TIKTOK_REDIRECT_URI"], backendEnv: ["TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET"] },
    "typeform": { label: "Typeform", consoleUrl: "https://admin.typeform.com/account#/section/apps", frontendEnv: ["TYPEFORM_CLIENT_ID", "TYPEFORM_REDIRECT_URI"], backendEnv: ["TYPEFORM_CLIENT_ID", "TYPEFORM_CLIENT_SECRET"] },
    "webflow": { label: "Webflow", consoleUrl: "https://developers.webflow.com/data/docs/register-an-app", frontendEnv: ["WEBFLOW_CLIENT_ID", "WEBFLOW_REDIRECT_URI"], backendEnv: ["WEBFLOW_CLIENT_ID", "WEBFLOW_CLIENT_SECRET"] },
    "wordpress": { label: "WordPress", consoleUrl: "https://developer.wordpress.com/apps/", frontendEnv: ["WORDPRESS_CLIENT_ID", "WORDPRESS_REDIRECT_URI"], backendEnv: ["WORDPRESS_CLIENT_ID", "WORDPRESS_CLIENT_SECRET"] },
    "zendesk": { label: "Zendesk", consoleUrl: "https://support.zendesk.com/hc/en-us/articles/4408845965210-Using-OAuth-authentication-with-your-application", frontendEnv: ["ZENDESK_CLIENT_ID", "ZENDESK_REDIRECT_URI"], backendEnv: ["ZENDESK_CLIENT_ID", "ZENDESK_CLIENT_SECRET"] },
    "zoom": { label: "Zoom", consoleUrl: "https://marketplace.zoom.us/develop/create", frontendEnv: ["ZOOM_CLIENT_ID", "ZOOM_REDIRECT_URI"], backendEnv: ["ZOOM_CLIENT_ID", "ZOOM_CLIENT_SECRET"] },
};

export function providerSetup(provider: string): OAuthProviderSetup {
    return (
        OAUTH_PROVIDER_SETUP[provider] ?? {
            label: provider.replace(/[-_]/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()),
            frontendEnv: [],
            backendEnv: [],
        }
    );
}
