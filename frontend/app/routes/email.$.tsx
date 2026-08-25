// Serves the signed email action links (one-click disable/unsubscribe and
// their confirmation pages) on the primary domain by proxying /email/* to the
// backend worker that owns the routes (backend/utils/email_routes.py).
// Emails link here (www.noclick.com) instead of email.hooks.example.test because
// link domains matching the brand domain are less likely to trip mail filters.

import type { ActionFunctionArgs, LoaderFunctionArgs } from 'react-router';
import { emailWorkerUrl } from '~/lib/hostedDefaults';

// Self-hosted installs serve these routes on the main backend;
// emailWorkerUrl() can point at a separately deployed worker.


async function proxyEmailAction(request: Request, splat: string | undefined) {
    const url = new URL(request.url);
    const target = `${emailWorkerUrl()}/email/${splat ?? ''}${url.search}`;
    const hasBody = !['GET', 'HEAD'].includes(request.method);
    const response = await fetch(target, {
        method: request.method,
        headers: { 'content-type': request.headers.get('content-type') ?? 'application/json' },
        body: hasBody ? await request.arrayBuffer() : undefined,
    });
    return new Response(await response.arrayBuffer(), {
        status: response.status,
        headers: { 'content-type': response.headers.get('content-type') ?? 'text/html' },
    });
}

export const loader = ({ request, params }: LoaderFunctionArgs) =>
    proxyEmailAction(request, params['*']);

export const action = ({ request, params }: ActionFunctionArgs) =>
    proxyEmailAction(request, params['*']);
