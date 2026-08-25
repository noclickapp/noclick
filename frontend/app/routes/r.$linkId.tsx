// Public shared-run page (/r/{linkId}). The link id is a capability minted
// from the Test Run screen's Share button; anyone with the URL sees a
// read-only snapshot of the finished rehearsal — trigger card, step trace,
// outcome — rendered by the same components the sharer watched. Static by
// construction: nothing executes, nothing bills, and the loader resolves
// brand icons server-side (nodeCatalog.server) so the client bundle never
// pulls the node registry.

import { type LoaderFunctionArgs, type MetaFunction } from 'react-router';
import { json, type JsonPayloadOf } from '~/lib/routerResponse';
import { isRouteErrorResponse, useLoaderData, useRouteError } from 'react-router';
import { FlaskConical } from 'lucide-react';
import { getSerializedNodeMeta } from '~/lib/nodeCatalog.server';
import { RunReadout, type Mark } from '~/components/design/rehearsal/variants';
import type { Scenario } from '~/components/design/rehearsal/fixture';
import type { ReplayRow, ReplayState } from '~/components/design/rehearsal/useReplay';
import { buildSeoMeta } from '~/lib/seo';
import { LogoMark } from '~/components/shared/LogoMark';

interface PublicRunSnapshot {
    version?: number;
    workflowName?: string;
    agentName?: string;
    scenario: Scenario;
    rows: ReplayRow[];
    artifacts: Scenario['artifacts'];
    failed?: boolean;
    reply?: string;
    /** Provider slugs the run renders (trigger + tool rows + artifacts) —
        the loader resolves each to a serialized brand mark. */
    providers?: string[];
}

export const meta: MetaFunction = ({ data }) => {
    const typedData = data as JsonPayloadOf<typeof loader> | undefined;
    const name = typedData?.payload?.workflow_name || 'Agent workflow';
    return buildSeoMeta({
        title: `${name} — simulated run`,
        description: `Watch ${name} handle a staged event on NoClick — a simulated run, step by step.`,
        indexable: false,
    });
};

export function headers() {
    // Capability URL — a future revoke must apply immediately.
    return { 'Cache-Control': 'no-store' };
}

/** Provider slug (backend tool-name prefix) → registry node type. */
function slugCandidates(slug: string): string[] {
    return [`automation-${slug.replace(/_/g, '-')}`, slug];
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
            `${backendUrl}/api/public/run-link/${encodeURIComponent(linkId)}`,
            { headers: { Accept: 'application/json' } }
        );
    } catch (e) {
        console.error('Failed to load run link:', e);
        throw new Response('Service temporarily unavailable', { status: 503 });
    }
    if (response.status === 404) {
        throw new Response('Run link not found or no longer active', {
            status: 404,
        });
    }
    if (!response.ok) {
        throw new Response('Service temporarily unavailable', { status: 503 });
    }

    const payload = (await response.json()) as {
        title: string;
        workflow_name: string;
        created_at: string | null;
        snapshot: PublicRunSnapshot;
    };
    const snapshot = payload.snapshot ?? ({} as PublicRunSnapshot);

    const slugs = new Set<string>(snapshot.providers ?? []);
    const sc = snapshot.scenario;
    if (sc) {
        if (sc.iconSlug) slugs.add(sc.iconSlug);
        if (sc.provider && sc.provider !== 'generic') slugs.add(sc.provider);
    }
    for (const row of snapshot.rows ?? []) {
        if (row.kind === 'tool' && row.provider) slugs.add(row.provider);
    }
    for (const a of snapshot.artifacts ?? []) {
        if (a.provider) slugs.add(a.provider);
    }
    const icons: Record<string, Mark> = {};
    for (const slug of slugs) {
        for (const type of slugCandidates(slug)) {
            const meta = getSerializedNodeMeta(type);
            if (meta?.iconHtml) {
                icons[slug] = { iconHtml: meta.iconHtml, iconColor: meta.iconColor };
                break;
            }
        }
    }

    return json({ payload, icons });
}

export default function SharedRunPage() {
    const { payload, icons } = useLoaderData() as JsonPayloadOf<typeof loader>;
    const snapshot = payload.snapshot;
    const run: ReplayState = {
        phase: 'done',
        t: 0,
        rows: (snapshot.rows ?? []) as ReplayRow[],
        artifacts: snapshot.artifacts ?? null,
        failed: snapshot.failed,
        start: () => {},
        replay: () => {},
    };
    const when = payload.created_at
        ? new Intl.DateTimeFormat('en-US', {
              month: 'short',
              day: 'numeric',
              year: 'numeric',
              timeZone: 'UTC',
          }).format(new Date(payload.created_at))
        : null;

    return (
        <div className="min-h-dvh bg-background text-foreground">
            {/* One column width for everything — the honesty strip, header and
                RunReadout (max-w-[560px] internally) must share an edge. */}
            <div className="mx-auto w-full max-w-[560px] px-4 py-8 sm:py-12">
                <header className="mb-6">
                    {/* The LandingNav lockup, scaled down and muted as ONE
                        unit — opacity on the container keeps mark and wordmark
                        in the same tone (tinting only the text mismatched the
                        white logo). */}
                    <a
                        href="https://noclick.com/?utm_source=run-share&utm_medium=header"
                        className="inline-flex items-center gap-1.5 opacity-55 transition-opacity hover:opacity-100"
                    >
                        <LogoMark alt="NoClick Logo" className="h-[18px] w-[18px]" />
                        <span className="text-[15px] font-bold text-foreground">
                            NoClick
                        </span>
                    </a>
                    <h1 className="mb-0 mt-4 text-[20px] font-semibold tracking-[-0.01em]">
                        {payload.workflow_name || snapshot.workflowName || 'Agent workflow'}
                    </h1>
                    <p className="m-0 mt-1 text-[13.5px] text-muted-foreground/80">
                        {payload.title || 'Test run'}
                        {when ? ` · ${when}` : ''}
                    </p>
                </header>

                {/* Honesty up front — same doctrine as the Test Run screen. */}
                <div className="mb-5 flex items-start gap-2.5 rounded-xl border border-border bg-foreground/[0.02] px-4 py-3">
                    <FlaskConical className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground/80" />
                    <p className="m-0 text-[12.5px] leading-relaxed text-muted-foreground/80">
                        This is a simulation — the agent ran for real, but every
                        tool call was answered by a fabricated world. Nothing
                        touched real accounts, and nothing was actually sent.
                    </p>
                </div>

                {snapshot.scenario ? (
                    <RunReadout run={run} scenario={snapshot.scenario} icons={icons} />
                ) : (
                    <p className="text-sm text-muted-foreground/70">
                        This run has nothing to show.
                    </p>
                )}

                <footer className="mt-10 border-t border-border pt-6 text-center">
                    <p className="m-0 text-[13px] text-muted-foreground/70">
                        Built with NoClick
                    </p>
                    <a
                        href="https://noclick.com/?utm_source=run-share&utm_medium=share-page"
                        className="mt-3 inline-block rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
                    >
                        Build your own agent
                    </a>
                </footer>
            </div>
        </div>
    );
}

export function ErrorBoundary() {
    const error = useRouteError();
    const notFound = isRouteErrorResponse(error) && error.status === 404;
    return (
        <div className="flex min-h-dvh items-center justify-center bg-background px-6 text-foreground">
            <div className="w-full max-w-sm rounded-2xl border border-border bg-sunken px-8 py-10 text-center dark:bg-sunken/60">
                <LogoMark className="mx-auto mb-5 h-8 w-8" />
                <h1 className="text-lg font-semibold tracking-tight">
                    {notFound
                        ? 'This run link is no longer active'
                        : 'Something went wrong'}
                </h1>
                <p className="mt-2 text-sm text-muted-foreground/70 dark:text-zinc-500">
                    {notFound
                        ? 'The link may have been removed by its owner.'
                        : 'Please try again in a moment.'}
                </p>
                <a
                    href="https://noclick.com/?utm_source=run-share&utm_medium=error-page"
                    className="mt-6 inline-block rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
                >
                    Build your own agent on NoClick
                </a>
            </div>
        </div>
    );
}
