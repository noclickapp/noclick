// HubSpot OAuth authorize route.
// Redirects to HubSpot's consent screen to request user authorization.
// HubSpot uses standard OAuth 2.0 Web Server Flow.

import { oauthRedirect } from '~/lib/oauthFlow.server';
import { redirect, type LoaderFunctionArgs } from 'react-router';
import crypto from 'crypto';
import { oauthNotConfiguredResponse } from '~/lib/oauthSetupPage.server';
import { applyInstanceOAuthEnv } from '~/lib/instanceOAuth.server';

const HUBSPOT_AUTH_URL = 'https://app.hubspot.com/oauth/authorize';

// Required scopes: requested in `scope=` — MUST be granted or the whole install
// fails. Limited to the core CRM scopes every HubSpot tier has (proven to install).
// Everything tier-gated goes in optional below, so a Free/Starter account that
// lacks CMS/Marketing/etc can still install. Keep in sync with the app config
// requiredScopes (project noclick-oauth-app / app-hsmeta.json).
const REQUIRED_HUBSPOT_SCOPES = [
    'oauth',
    'crm.objects.contacts.read',
    'crm.objects.contacts.write',
    'crm.objects.companies.read',
    'crm.objects.companies.write',
    'crm.objects.deals.read',
    'crm.objects.deals.write',
    'tickets',
];

// Optional scopes: requested in `optional_scope=` — HubSpot grants each on
// accounts whose tier supports it and SILENTLY SKIPS the rest, so installs never
// fail. Everything beyond the core CRM lives here (an op whose scope wasn't
// granted returns a clear 403 the node surfaces).
const OPTIONAL_HUBSPOT_SCOPES = [
    'crm.objects.owners.read',
    'crm.objects.line_items.read',
    'crm.objects.line_items.write',
    'crm.objects.quotes.read',
    'crm.objects.quotes.write',
    'crm.objects.orders.read',
    'crm.objects.orders.write',
    'e-commerce',
    'crm.lists.read',
    'crm.lists.write',
    'crm.schemas.contacts.read',
    'crm.schemas.contacts.write',
    'crm.schemas.companies.read',
    'crm.schemas.companies.write',
    'crm.schemas.deals.read',
    'crm.schemas.deals.write',
    'crm.objects.marketing_events.read',
    'crm.objects.marketing_events.write',
    'content',
    'hubdb',
    'files',
    'cms.domains.read',
    'communication_preferences.read',
    'communication_preferences.read_write',
    'conversations.read',
    'conversations.write',
    'automation',
    'crm.export',
    'crm.import',
    'crm.objects.goals.read',
    'crm.objects.leads.read',
    'crm.objects.leads.write', // Sales Hub Pro/Ent
    'crm.objects.custom.read',
    'crm.objects.custom.write', // Enterprise
    'crm.schemas.custom.read', // Enterprise (no .write scope exists)
    'crm.objects.feedback_submissions.read', // Service Hub
    'marketing.campaigns.read',
    'marketing.campaigns.write',
    'marketing.campaigns.revenue.read',
    'sales-email-read', // sensitive: email content
    'automation.sequences.read',
    'automation.sequences.enrollments.write',
    'settings.users.read',
    'settings.users.write',
    'settings.users.teams.read',
    'account-info.security.read', // audit logs (Enterprise)
    'business_units_view.read', // Business Units add-on
    'behavioral_events.event_definitions.read_write',
    'analytics.behavioral_events.send',
];

const DEFAULT_HUBSPOT_SCOPES = REQUIRED_HUBSPOT_SCOPES.join(',');

export async function loader({ request }: LoaderFunctionArgs) {
    // Self-hosted: an OAuth app saved in Settings shows up as env vars here.
    await applyInstanceOAuthEnv(request, 'hubspot');
    const url = new URL(request.url);
    const credentialName = url.searchParams.get('name') || 'HubSpot';
    const scopesParam =
        url.searchParams.get('scopes') || DEFAULT_HUBSPOT_SCOPES;

    const clientId = process.env.HUBSPOT_CLIENT_ID?.trim();
    const redirectUri = process.env.HUBSPOT_REDIRECT_URI?.trim();

    if (!clientId || !redirectUri) {
        console.error(
            '[hubspot.authorize] Missing HUBSPOT_CLIENT_ID or HUBSPOT_REDIRECT_URI env vars'
        );
        return oauthNotConfiguredResponse({
            request,
            provider: 'hubspot',
            missing: ['HUBSPOT_CLIENT_ID', 'HUBSPOT_REDIRECT_URI'],
        });
    }

    // State contains metadata to pass through OAuth flow
    const state = Buffer.from(
        JSON.stringify({
            credentialName,
            scopes: scopesParam.split(','),
            nonce: crypto.randomUUID(), // CSRF protection
            timestamp: Date.now(),
        })
    ).toString('base64url');

    // HubSpot expects space-separated scopes
    const spaceSeparatedScopes = scopesParam.split(',').join(' ');

    const params = new URLSearchParams({
        client_id: clientId,
        redirect_uri: redirectUri,
        scope: spaceSeparatedScopes,
        state: state,
    });

    // Optional scopes go in a separate param — HubSpot drops any the account's
    // tier can't grant instead of failing the install.
    const optionalScopes = OPTIONAL_HUBSPOT_SCOPES.join(' ');
    if (optionalScopes) {
        params.set('optional_scope', optionalScopes);
    }

    const fullUrl = `${HUBSPOT_AUTH_URL}?${params.toString()}`;

    return oauthRedirect(request, fullUrl);
}
