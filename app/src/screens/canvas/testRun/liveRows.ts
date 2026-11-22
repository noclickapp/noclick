// A test run's steps as they arrive, and what a finished one sent: the frames a run reports (a tool call under way and
// done, the agent's words between calls) folded into the rows the Test Run's views draw, whoever reports them. Timings
// are measured between frames as they arrive, never invented.
import type { Scenario } from './scenarios';
import type { ReplayRow, ReplayState } from './useReplay';

/** Turn `slack__send_message_to_channel` into something a person would say.
    This line is read by someone deciding whether to trust the agent, so the
    verb and the provider matter and the raw tool name does not. */
// Brands whose casing a title-case pass gets wrong. Everything else is
// title-cased from the slug, so a new provider reads correctly without an entry.
const PROVIDER_NAMES: Record<string, string> = {
    github: 'GitHub',
    gitlab: 'GitLab',
    hubspot: 'HubSpot',
    linkedin: 'LinkedIn',
    youtube: 'YouTube',
    tiktok: 'TikTok',
    wordpress: 'WordPress',
    whatsapp: 'WhatsApp',
    pagerduty: 'PagerDuty',
    quickbooks: 'QuickBooks',
    bamboohr: 'BambooHR',
    dv360: 'DV360',
    onedrive: 'OneDrive',
    bigquery: 'BigQuery',
    clickup: 'ClickUp',
    'cal com': 'Cal.com',
    'github rest': 'GitHub',
    'google sheets': 'Google Sheets',
    'google drive': 'Google Drive',
    'google calendar': 'Google Calendar',
    'google docs': 'Google Docs',
};

function providerName(slug: string): string {
    const spaced = slug.replace(/_/g, ' ').trim();
    const known = PROVIDER_NAMES[spaced] ?? PROVIDER_NAMES[spaced.replace(/\s+/g, '')];
    if (known) return known;
    return spaced.replace(/\b[a-z]/g, (c) => c.toUpperCase());
}

export function readableStep(toolName: string): {
    label: string;
    provider?: string;
    tool?: string;
} {
    const tool = (toolName || '').trim();
    if (!tool) return { label: 'Working…' };
    const [head, ...rest] = tool.split('__');
    const rawAction = (rest.join('__') || head).replace(/_/g, ' ').trim();
    // Sentence case, not Title Case: this sits in a list a person reads, not a
    // menu they scan, and Title Case On Every Row reads like a spreadsheet.
    const action = rawAction.charAt(0).toUpperCase() + rawAction.slice(1);
    return {
        label: action,
        provider: rest.length ? providerName(head) : undefined,
        tool,
    };
}

/** Any `slug__operation` tool carries its provider slug — the icon map is
    keyed by the same backend derivation, and StepMark falls back to a generic
    glyph when the slug has no registered mark. */
function toolMeta(tool: string): { provider?: string; glyph?: 'globe' | 'plug' | 'terminal' } {
    const [head, ...rest] = tool.split('__');
    if (rest.length) return { provider: head, glyph: 'plug' };
    if (/^(web|fetch|http|search)/.test(head)) return { glyph: 'globe' };
    if (/bash|terminal|shell/.test(head)) return { glyph: 'terminal' };
    return { glyph: 'plug' };
}

export interface LiveRow {
    id: string;
    tool: string;
    status: 'in_progress' | 'completed' | 'error';
    startedAt: number;
    ms?: number;
    outbound?: string;
    args?: Record<string, unknown>;
    result?: Record<string, unknown>;
    /** Set on reasoning rows — a slice of the agent's visible thinking
        between tool calls. Renders as a thought row, not a tool row. */
    thought?: string;
}

/** Apply one progress frame (step/thought) to a row list IN PLACE. The one
    upsert rule for a test run's frames — shared by every reader of them (a
    listener the frames are pushed to, a page that polls for them), so a frame
    can never read differently between two surfaces. Terminal frames
    (done/failed) are the caller's business. */
export function applyProgressFrame(rows: LiveRow[], data: any): void {
    if (data.kind === 'step' && data.step_id) {
        const at = rows.findIndex((r) => r.id === data.step_id);
        const before = at >= 0 ? rows[at] : null;
        const completed = data.status === 'completed';
        const began = before?.startedAt ?? Date.now();
        const row: LiveRow = {
            id: data.step_id,
            tool: data.tool || '',
            // The stream has no failure frames yet; when it gains them
            // this is where they land as 'error'.
            status: completed ? 'completed' : 'in_progress',
            startedAt: began,
            ms: completed && before ? Date.now() - began : undefined,
            outbound:
                typeof data.outbound === 'string' && data.outbound.trim()
                    ? data.outbound.trim()
                    : before?.outbound,
            args:
                data.args && typeof data.args === 'object'
                    ? (data.args as Record<string, unknown>)
                    : before?.args,
            result:
                data.result && typeof data.result === 'object'
                    ? (data.result as Record<string, unknown>)
                    : before?.result,
        };
        if (at >= 0) rows[at] = row;
        else rows.push(row);
        return;
    }
    if (data.kind === 'thought' && data.step_id && data.text) {
        if (!rows.some((r) => r.id === data.step_id)) {
            rows.push({
                id: data.step_id,
                tool: '',
                status: 'completed',
                startedAt: Date.now(),
                thought: data.text,
            });
        }
    }
}

/** LiveRows → the ReplayRows the variants render (readable labels, provider
    marks, live elapsed for in-progress rows). */
export function toReplayRows(rows: readonly LiveRow[], now: number): ReplayRow[] {
    return rows.map((r) =>
        r.thought !== undefined
            ? { kind: 'thought' as const, id: r.id, at: r.startedAt, text: r.thought }
            : {
                  kind: 'tool' as const,
                  id: r.id,
                  at: r.startedAt,
                  text: readableStep(r.tool).label,
                  ...toolMeta(r.tool),
                  status: r.status,
                  ms: r.ms,
                  elapsed: r.status === 'in_progress' ? now - r.startedAt : 0,
                  args: r.args ? ({ ...r.args } as Record<string, unknown>) : undefined,
                  result: r.result
                      ? ({ ...r.result } as Record<string, unknown>)
                      : undefined,
              }
    );
}

/** The run's outbound sends → outcome artifacts (callers gate on phase done).
    Null when nothing went out — the outcome then renders restraint. */
export function deriveArtifacts(rows: readonly LiveRow[]): Scenario['artifacts'] {
    const sends = rows.filter((r) => r.outbound);
    if (!sends.length) return null;
    return sends.map((r) => ({
        // The sender's REAL slug — the frame router and the via mark both key
        // on it; coercing unknowns to a chat channel dressed the send-email
        // node as Slack.
        provider: toolMeta(r.tool).provider ?? '',
        to:
            pickString(r.args, [
                'to',
                'recipient',
                'channel',
                'channel_id',
                'chat_id',
                'email',
            ]) ?? '',
        subject: pickString(r.args, ['subject']),
        text: r.outbound as string,
    }));
}

/** First non-empty value under any of `keys` — how the artifact learns its
    destination/subject from the tool's own arguments. Numbers count: a
    Telegram chat id is numeric, and dropping it left the frame channel-less. */
function pickString(
    args: Record<string, unknown> | undefined,
    keys: string[]
): string | undefined {
    for (const k of keys) {
        const v = args?.[k];
        if (typeof v === 'string' && v.trim()) return v.trim();
        if (typeof v === 'number' && Number.isFinite(v)) return String(v);
    }
    return undefined;
}

export interface LiveRunState extends ReplayState {
    /** Why the run stopped, when it stopped badly. */
    error: string | null;
    /** The agent's closing words — the outcome text when nothing was composed. */
    reply: string;
}
