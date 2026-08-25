/**
 * Public workflow share route - displays a read-only view of a publicly shared workflow.
 * Fetches from backend API with cache fallback on failure via stale-if-error headers.
 */

import { type MetaFunction, type LoaderFunctionArgs } from 'react-router';
import { json, type JsonPayloadOf } from '~/lib/routerResponse';
import { useLoaderData } from 'react-router';
import { createPublicLoaderData } from '~/lib/csrf.server';
import { PublicWorkflowView } from '~/components/workflow/PublicWorkflowView';
import { buildSeoMeta } from '~/lib/seo';

export const meta: MetaFunction = ({ data, params }) => {
    const typedData = data as JsonPayloadOf<typeof loader> | undefined;
    const workflowName = typedData?.workflow?.name || 'Shared Workflow';
    const description = typedData?.workflow?.description || 'View this shared workflow on NoClick.';
    const workflowId = params.workflowId;

    return buildSeoMeta({
        title: `${workflowName} - NoClick`,
        description,
        url: workflowId ? `/share/${workflowId}` : undefined,
    });
};

export function headers() {
    return {
        'Cache-Control': 'public, s-maxage=300, stale-while-revalidate=60, stale-if-error=3600',
    };
}

export async function loader({ params, request }: LoaderFunctionArgs) {
    const workflowId = params.workflowId;
    const url = new URL(request.url);
    const isEmbed = url.searchParams.get('embed') === 'true';
    const autoFork = url.searchParams.get('fork') === 'true';
    const initialView = url.searchParams.get('view') as 'canvas' | 'interface' | null;

    if (!workflowId) {
        throw new Response('Workflow ID is required', { status: 400 });
    }

    const backendUrl = process.env.VITE_API_URL || 'http://localhost:8000';

    // Get auth and CSRF data
    const authResponse = await createPublicLoaderData(request);
    const baseData = await authResponse.json();
    const headers = authResponse.headers;

    try {
        const response = await fetch(
            `${backendUrl}/api/public/workflow/${encodeURIComponent(workflowId)}`,
            { headers: { 'Accept': 'application/json' } }
        );

        if (response.status === 404) {
            throw new Response('Workflow not found or is not public', { status: 404 });
        }

        if (!response.ok) {
            throw new Error(`Backend returned ${response.status}`);
        }

        const workflow = await response.json();

        return json(
            {
                ...baseData,
                workflow,
                isEmbed,
                autoFork,
                initialView,
            },
            { headers }
        );
    } catch (e) {
        // Re-throw Response objects (404s, 400s)
        if (e instanceof Response) throw e;
        // Return 503 so CDN can serve stale cached content via stale-if-error
        console.error('Failed to load workflow:', e);
        throw new Response('Service temporarily unavailable', {
            status: 503,
            headers: {
                'Cache-Control': 'no-store',
                'Retry-After': '60',
            },
        });
    }
}

export default function ShareWorkflowPage() {
    const { workflow, isAuthenticated, isEmbed, autoFork, csrfToken, initialView } = useLoaderData() as JsonPayloadOf<typeof loader>;

    return (
        <PublicWorkflowView
            workflow={workflow}
            isAuthenticated={isAuthenticated}
            isEmbed={isEmbed}
            csrfToken={csrfToken}
            autoFork={autoFork}
            initialView={initialView ?? undefined}
        />
    );
}
