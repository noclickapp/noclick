// Words for the Apps and Code repos panels: a deployment's and a schedule's status as a pill, the runtime,
// framework and deploy-on-push choices with a sentence each, a cron
// expression in plain English (through the schedule formatter the canvas
// uses), and the empty states' first calls.
import type { DeployOnPush, PreviewAccess, ProjectRuntime } from 'noclick';
import type { Snippet } from '@/screens/console/lib/snippets';
import type { StatusLook } from '@/screens/console/lib/status';
export { describeCron } from '@/lib/scheduleFormat';

/** A deploy can only be refused up front, so a failed one started by `deploy` failed its build. */
export function deploymentLook(d: { status: string; production?: boolean; startedBy?: string }): StatusLook {
    switch (d.status) {
        case 'queued':
            return { label: 'Queued', glyph: 'hollow', tone: 'ink' };
        case 'building':
            return { label: 'Building', glyph: 'filled', tone: 'ink' };
        case 'ready':
            return { label: 'Ready', reason: d.production ? 'production' : null, glyph: 'check', tone: 'ink' };
        case 'failed':
            return { label: 'Failed', reason: d.startedBy === 'push' ? 'on push' : 'build', glyph: 'cross', tone: 'failure' };
        case 'canceled':
            return { label: 'Canceled', glyph: 'muted', tone: 'muted' };
        default:
            return { label: d.status, glyph: 'hollow', tone: 'muted' };
    }
}

export const NOT_DEPLOYED: StatusLook = { label: 'Not deployed', glyph: 'muted', tone: 'muted' };

export interface ChoiceOption<T extends string> {
    value: T;
    label: string;
    sentence: string;
}

/** Picked from the source on each deploy unless pinned. */
export const RUNTIMES: readonly ChoiceOption<ProjectRuntime>[] = [
    { value: 'auto', label: 'Automatic', sentence: 'Picked from the code on each deploy: edge for web code, a container for a server.' },
    { value: 'edge', label: 'Edge', sentence: 'A JavaScript framework, its server code run near each visitor.' },
    { value: 'container', label: 'Container', sentence: 'Any server in any language, in a container that scales to zero.' },
];

/** What `framework` takes on each runtime; omitted, it's detected from the repo at each build. */
export const FRAMEWORKS: Record<ProjectRuntime, readonly { value: string; label: string }[]> = {
    auto: [],
    edge: [
        { value: 'nextjs', label: 'Next.js' },
        { value: 'remix', label: 'Remix' },
        { value: 'astro', label: 'Astro' },
        { value: 'vite', label: 'Vite' },
        { value: 'static', label: 'Static files' },
    ],
    container: [
        { value: 'python', label: 'Python' },
        { value: 'node', label: 'Node.js' },
        { value: 'docker', label: 'Its Dockerfile' },
    ],
};

export const frameworkLabel = (id: string) => Object.values(FRAMEWORKS).flat().find((f) => f.value === id)?.label ?? id;

/** What a push deploys by itself, said of the production `branch`. */
export function deployOnPushOptions(branch: string): readonly ChoiceOption<DeployOnPush>[] {
    return [
        { value: 'off', label: 'Off', sentence: 'A push deploys nothing; deploy from here, the API or your code.' },
        { value: 'production', label: 'Production branch', sentence: `A push to ${branch} deploys it to production.` },
        { value: 'all', label: 'Every branch', sentence: `A push to ${branch} deploys production, and a push to any other branch deploys its preview.` },
    ];
}

/** Who opens an app's previews (`Project.previewAccess`), with what each means. */
export const PREVIEW_ACCESS: readonly ChoiceOption<PreviewAccess>[] = [
    { value: 'public', label: 'Anyone with the URL', sentence: 'Anyone with a preview’s URL opens it; search engines are told not to list it.' },
    { value: 'link', label: 'Link only', sentence: 'A preview opens only with a link made here or handed back by its deploy; anyone else is told it’s private. Production stays public.' },
];

/** `ProjectUsage.byType` ids as the Usage page names them, hosting being the `apps` type. */
const SPEND_TYPES: Record<string, string> = {
    apps: 'Hosting and builds',
    ai: 'AI',
    model_tokens: 'Agent turns',
    tool_runs: 'Tool runs',
    sandboxes: 'Sandboxes',
    databases: 'Databases',
    storage: 'Storage',
    dicts: 'Dicts',
    queues: 'Queues',
    app_email: 'Email',
};

export const spendTypeLabel = (id: string) => SPEND_TYPES[id] ?? id;

/** What stops an app's paid calls (`this month's $20 budget is used up`), or null while they go through. */
export function limitText(limitedBy: string | null, app: { userId: string | null; budgetUsd: string }): string | null {
    if (limitedBy === 'project') return `this month's ${app.budgetUsd} budget is used up`;
    if (limitedBy === 'user') return `its user ${app.userId} reached their monthly spend cap`;
    if (limitedBy === 'account') return "your account's balance is used up";
    return null;
}

/** Paused by the breaker (it kept failing) reads as a failure; paused by hand is quiet. */
export function scheduleLook(s: { status: string; pausedReason: string | null; lastStatus: string | null }): StatusLook {
    if (s.status === 'active') return { label: 'Active', glyph: 'check', tone: 'ink' };
    const failing = s.lastStatus === 'failed' && !!s.pausedReason;
    return { label: 'Paused', reason: failing ? 'failing' : null, glyph: failing ? 'cross' : 'muted', tone: failing ? 'failure' : 'muted' };
}

export function lastRunLook(status: string | null): StatusLook {
    if (status === 'succeeded') return { label: 'Succeeded', glyph: 'check', tone: 'ink' };
    if (status === 'failed') return { label: 'Failed', glyph: 'cross', tone: 'failure' };
    return { label: 'Never run', glyph: 'muted', tone: 'muted' };
}

/** A schedule's `tz` in words: `user` fires on the app's user's own clock, wherever they are. */
export const zoneLabel = (tz: string) => (tz === 'user' ? "the user's timezone" : tz);

/** An app's own page, under Apps in Resources: every link to an app opens it. */
export const appPath = (id: string) => `resources/apps/${encodeURIComponent(id)}`;

/** Several params in one write: react-router's updater reads the params of this render, so two writes in a row drop the first. */
export function withParams(prev: URLSearchParams, changes: Record<string, string | null>): URLSearchParams {
    const out = new URLSearchParams(prev);
    for (const [key, value] of Object.entries(changes)) {
        if (value === null) out.delete(key);
        else out.set(key, value);
    }
    return out;
}

const lines = (...parts: string[]) => parts.join('\n');

export const SCHEDULES_EMPTY: Snippet = {
    python: lines(
        'import noclick',
        '',
        'app = noclick.Project.from_name("booking")',
        'app.schedule(noclick.Cron("0 9 * * 1-5", tz="America/New_York"), path="/jobs/reminders")'
    ),
    typescript: lines(
        'import { Cron, Project } from "noclick";',
        '',
        'const app = Project.fromName("booking");',
        'await app.schedule(new Cron("0 9 * * 1-5", { tz: "America/New_York" }), { path: "/jobs/reminders" });'
    ),
};
