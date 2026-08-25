// PagerDuty OAuth authorize route.
// Redirects to PagerDuty's consent screen to request user authorization.
// PagerDuty uses standard OAuth 2.0 (authorization_code) with space-delimited scopes.

import { oauthRedirect } from '~/lib/oauthFlow.server';
import { redirect, type LoaderFunctionArgs } from 'react-router';
import crypto from 'crypto';
import { oauthNotConfiguredResponse } from '~/lib/oauthSetupPage.server';
import { applyInstanceOAuthEnv } from '~/lib/instanceOAuth.server';

const PAGERDUTY_AUTH_URL = 'https://identity.pagerduty.com/oauth/authorize';

// Default scopes. NodeCredentials pulls the canonical list from the credential
// schema's x-oauth-scopes (see backend/nodes/pagerduty_node.py:PagerDutyOAuthCredential
// -> PAGERDUTY_DEFAULT_SCOPES) and passes it via the ?scopes= param (comma-separated)
// — this granular Scoped-OAuth fallback only triggers for callers that forgot to.
// Classic read/write cannot reach scoped-only endpoints (e.g. Audit Records).
const PAGERDUTY_DEFAULT_SCOPES = [
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
].join(',');

export async function loader({ request }: LoaderFunctionArgs) {
    // Self-hosted: an OAuth app saved in Settings shows up as env vars here.
    await applyInstanceOAuthEnv(request, 'pagerduty');
    const url = new URL(request.url);
    const scopesParam =
        url.searchParams.get('scopes') || PAGERDUTY_DEFAULT_SCOPES;

    const clientId = process.env.PAGERDUTY_CLIENT_ID;
    const redirectUri = process.env.PAGERDUTY_REDIRECT_URI;

    if (!clientId || !redirectUri) {
        console.error(
            '[pagerduty.authorize] Missing PAGERDUTY_CLIENT_ID or PAGERDUTY_REDIRECT_URI env vars'
        );
        return oauthNotConfiguredResponse({
            request,
            provider: 'pagerduty',
            missing: ['PAGERDUTY_CLIENT_ID', 'PAGERDUTY_REDIRECT_URI'],
        });
    }

    const scopes = scopesParam
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean);

    // State contains metadata to pass through OAuth flow; base64url encoded so
    // it survives the URL round-trip.
    const state = Buffer.from(
        JSON.stringify({
            scopes,
            nonce: crypto.randomUUID(), // CSRF protection
            timestamp: Date.now(),
        })
    ).toString('base64url');

    // PagerDuty expects space-delimited scopes.
    const params = new URLSearchParams({
        client_id: clientId,
        redirect_uri: redirectUri,
        response_type: 'code',
        scope: scopes.join(' '),
        state,
    });

    const authUrl = `${PAGERDUTY_AUTH_URL}?${params.toString()}`;

    return oauthRedirect(request, authUrl);
}
