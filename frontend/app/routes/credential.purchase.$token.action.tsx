// A phone-number purchase link's operations (coverage, places, search, quote, confirm, status, and resubmitting what the
// carrier sent back with its documents) as JSON, for the link's page and the chat's number card. A route of its own because
// a page route answers a POST with its HTML, never the action's JSON. A document's file goes straight to the backend, at a
// link ``document_upload`` signs for it, never through here.
import type { ActionFunctionArgs } from 'react-router';
import { csrfFailureResponse } from '~/lib/csrf.server';
import { PURCHASE_OPERATIONS, phonePurchaseBackend } from '~/lib/phonePurchase.server';
import { json } from '~/lib/routerResponse';
import { requireAuth } from '~/lib/supabase';

export async function action({ request, params }: ActionFunctionArgs) {
    const { backendHeaders, headers } = await requireAuth(request);
    const form = await request.formData();
    const csrfFailure = await csrfFailureResponse(request, form);
    if (csrfFailure) {
        // Keep any rotated auth cookies even when CSRF needs refreshing.
        for (const cookie of headers.getSetCookie()) csrfFailure.headers.append('Set-Cookie', cookie);
        return csrfFailure;
    }
    headers.set('Cache-Control', 'private, no-store');
    const operation = String(form.get('operation'));
    if (!(PURCHASE_OPERATIONS as readonly string[]).includes(operation)) return json({ error: 'Unknown action.' }, { status: 400, headers });
    let body: unknown;
    try {
        body = JSON.parse(String(form.get('payload') || '{}'));
    } catch {
        return json({ error: 'Invalid request.' }, { status: 400, headers });
    }
    return json(await phonePurchaseBackend(params.token!, backendHeaders, operation === 'status' ? undefined : operation, body), { headers });
}
