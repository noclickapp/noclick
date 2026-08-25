// Apollo OAuth authorize route.
// Redirects to Apollo's consent screen to request user authorization.
// Scope names must match exactly what was approved on the Apollo OAuth client.

import { oauthRedirect } from '~/lib/oauthFlow.server';
import { redirect, type LoaderFunctionArgs } from 'react-router';
import crypto from 'crypto';
import { oauthNotConfiguredResponse } from '~/lib/oauthSetupPage.server';
import { applyInstanceOAuthEnv } from '~/lib/instanceOAuth.server';

const APOLLO_AUTH_URL = 'https://app.apollo.io/#/oauth/authorize';

const APOLLO_DEFAULT_SCOPES = [
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
].join(',');

export async function loader({ request }: LoaderFunctionArgs) {
    // Self-hosted: an OAuth app saved in Settings shows up as env vars here.
    await applyInstanceOAuthEnv(request, 'apollo');
    const url = new URL(request.url);
    const scopesParam = url.searchParams.get('scopes') || APOLLO_DEFAULT_SCOPES;
    const scopes = scopesParam
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean);

    const clientId = process.env.APOLLO_CLIENT_ID;
    const redirectUri = process.env.APOLLO_REDIRECT_URI;

    if (!clientId || !redirectUri) {
        console.error(
            '[apollo.authorize] Missing APOLLO_CLIENT_ID or APOLLO_REDIRECT_URI env vars'
        );
        return oauthNotConfiguredResponse({
            request,
            provider: 'apollo',
            missing: ['APOLLO_CLIENT_ID', 'APOLLO_REDIRECT_URI'],
        });
    }

    const state = Buffer.from(
        JSON.stringify({
            scopes,
            nonce: crypto.randomUUID(),
            timestamp: Date.now(),
        })
    ).toString('base64url');

    const params = new URLSearchParams({
        client_id: clientId,
        redirect_uri: redirectUri,
        response_type: 'code',
        scope: scopes.join(' '),
        state,
    });

    return oauthRedirect(request, `${APOLLO_AUTH_URL}?${params.toString()}`);
}
