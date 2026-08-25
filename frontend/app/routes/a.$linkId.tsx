// Public shared-agent chat page (/a/{linkId}). The link id is a capability
// minted from the agent interface's Share button; anyone with the URL chats
// with the agent as an anonymous visitor while costs bill to the workflow
// owner. SSR loader fetches sanitized metadata from the backend and resolves
// brand icons server-side (nodeCatalog.server) so the client bundle never
// pulls the node registry.

import { type LoaderFunctionArgs, type MetaFunction } from 'react-router';
import { json, type JsonPayloadOf } from '~/lib/routerResponse';
import { isRouteErrorResponse, useLoaderData, useRouteError } from 'react-router';
import {
    getHarnessIcon,
    getSerializedNodeMeta,
    getSerializedNodeMetaMap,
} from '~/lib/nodeCatalog.server';
import {
    PublicAgentChatView,
    type PublicAgentMeta,
} from '~/components/agent-share/PublicAgentChatView';
import type { ToolLogo } from '~/components/agent-share/ToolLogosRow';
import { buildSeoMeta } from '~/lib/seo';
import { LogoMark } from '~/components/shared/LogoMark';

// CLI-harness model ids get their brand mark; anything else falls back to the
// generic agent node icon. Kept inline (tiny + stable) instead of importing
// lib/agentChat, which would drag the agent schema into this route's bundle.
const CLI_HARNESS_MODELS = new Set([
    'codex',
    'claude-code',
    'opencode',
    'openclaw',
    'hermes',
]);

export const meta: MetaFunction = ({ data }) => {
    const typedData = data as JsonPayloadOf<typeof loader> | undefined;
    const label = typedData?.meta?.agent?.label || 'Agent';
    return buildSeoMeta({
        title: `${label} — NoClick Agent`,
        description: `Chat with ${label}, an AI agent built on NoClick.`,
        indexable: false,
    });
};

export function headers() {
    // Capability URL — rotate / deactivate must apply immediately.
    return { 'Cache-Control': 'no-store' };
}

export async function loader({ params }: LoaderFunctionArgs) {
    const linkId = params.linkId;
    if (!linkId) {
        throw new Response('Link ID is required', { status: 400 });
    }

    const backendUrl = process.env.VITE_API_URL || 'http://localhost:8000';
    let response: Response;
    try {
        response = await fetch(
            `${backendUrl}/api/public/agent-link/${encodeURIComponent(linkId)}`,
            { headers: { Accept: 'application/json' } }
        );
    } catch (e) {
        console.error('Failed to load agent link:', e);
        throw new Response('Service temporarily unavailable', { status: 503 });
    }
    if (response.status === 404) {
        throw new Response('Agent link not found or no longer active', {
            status: 404,
        });
    }
    if (!response.ok) {
        throw new Response('Service temporarily unavailable', { status: 503 });
    }

    const meta = (await response.json()) as PublicAgentMeta;

    const model = meta.agent?.model;
    const agentIcon =
        model && CLI_HARNESS_MODELS.has(model)
            ? getHarnessIcon(model)
            : (() => {
                  const agentMeta = getSerializedNodeMeta('agent');
                  return agentMeta
                      ? {
                            iconHtml: agentMeta.iconHtml,
                            iconColor: agentMeta.iconColor,
                        }
                      : null;
              })();

    const iconMap = getSerializedNodeMetaMap(
        meta.tools.map((t) => t.node_type)
    );
    const toolLogos: ToolLogo[] = meta.tools
        .map((t) => ({
            node_type: t.node_type,
            label: t.label,
            iconHtml: iconMap[t.node_type]?.iconHtml ?? '',
            iconColor: iconMap[t.node_type]?.iconColor ?? '',
        }))
        .filter((t) => t.iconHtml);

    return json({ linkId, meta, agentIcon, toolLogos });
}

export default function SharedAgentPage() {
    const { linkId, meta, agentIcon, toolLogos } =
        useLoaderData() as JsonPayloadOf<typeof loader>;
    return (
        <PublicAgentChatView
            linkId={linkId}
            meta={meta}
            agentIcon={agentIcon}
            toolLogos={toolLogos}
        />
    );
}

export function ErrorBoundary() {
    const error = useRouteError();
    const notFound = isRouteErrorResponse(error) && error.status === 404;
    return (
        <div className="min-h-dvh bg-background text-foreground flex items-center justify-center px-6">
            <div className="max-w-sm w-full text-center border border-border rounded-2xl bg-sunken dark:bg-sunken/60 px-8 py-10">
                <LogoMark className="mx-auto w-8 h-8 mb-5" />
                <h1 className="text-lg font-semibold tracking-tight">
                    {notFound
                        ? 'This agent link is no longer active'
                        : 'Something went wrong'}
                </h1>
                <p className="mt-2 text-sm text-muted-foreground/70 dark:text-zinc-500">
                    {notFound
                        ? 'The link may have been reset or turned off by its owner.'
                        : 'Please try again in a moment.'}
                </p>
                <a
                    href="https://noclick.com/?utm_source=agent-share&utm_medium=error-page"
                    className="mt-6 inline-block text-sm font-medium bg-primary text-primary-foreground hover:bg-primary/90 rounded-lg px-4 py-2 transition-colors"
                >
                    Build your own agent on NoClick
                </a>
            </div>
        </div>
    );
}
