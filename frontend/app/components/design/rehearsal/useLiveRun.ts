/* The live half of the rehearsal screen: maps the real `rehearsal:run` stream —
   an actual agent turn whose tool calls are answered by the fabricated world —
   into the same ReplayState shape the designed composition consumes. One UI,
   two engines: the bench replays a captured fixture; this runs the user's own
   workflow. Timings are measured client-side between frames, never invented.

   Run state lives in a module-level valtio store keyed by workflow, and the
   socket listener is attached for the module's lifetime — so switching
   workspace tabs (which unmounts the screen) neither loses a finished result
   nor drops the frames of a run still in flight. */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { proxy, useSnapshot } from 'valtio';
import { onSocketEvent } from '~/lib/socket-receiver';
import { RehearsalRunRequest, sendEventAsync } from '~/lib/socket-sender';
import { readableStep } from '~/hooks/useRehearsal';
import type { Scenario } from './fixture';
import type { ReplayRow, ReplayState } from './useReplay';

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
    upsert rule for rehearsal frames — shared by the socket listener (valtio
    slot.rows) and the public template page's polling hook, so a frame can
    never read differently between the two surfaces. Terminal frames
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

interface RunSlot {
    /** The staged situation this run belongs to — a different selection reads idle. */
    scenario: string;
    conversationId: string | null;
    phase: 'running' | 'done';
    rows: LiveRow[];
    reply: string;
    error: string | null;
    startedAt: number;
}

const liveRuns = proxy<{ byWorkflow: Record<string, RunSlot> }>({ byWorkflow: {} });

let listening = false;
function ensureListener() {
    if (listening) return;
    listening = true;
    // Module-lifetime subscription, deliberately never detached: frames must
    // land in the store even while no screen is mounted to watch them.
    onSocketEvent('rehearsal:progress' as never, ((data: any) => {
        if (!data?.conversation_id) return;
        const slot = Object.values(liveRuns.byWorkflow).find(
            (s) => s.conversationId === data.conversation_id
        );
        if (!slot) return;

        if (data.kind === 'step' || data.kind === 'thought') {
            applyProgressFrame(slot.rows, data);
            return;
        }

        if (data.kind === 'done') {
            slot.reply = data.reply || '';
            slot.phase = 'done';
        } else if (data.kind === 'failed') {
            slot.error = data.error || 'The test did not finish.';
            slot.phase = 'done';
        }
    }) as never);
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

export function useLiveRun(
    workflowId: string | null,
    scenario = 'sales-inbound-lead',
    /** Builder edits to the staged message (lead terms). Sent with the run so
        the backend rebuilds the payload — the edit is real, not cosmetic. */
    leadPatch?: Record<string, string>
): LiveRunState {
    const snap = useSnapshot(liveRuns);
    const slot = workflowId ? snap.byWorkflow[workflowId] : undefined;
    const current = slot && slot.scenario === scenario ? slot : undefined;

    // A coarse tick so the placeholder clock and in-progress durations move.
    // It MUST be a memo dependency — a re-render alone recomputes nothing.
    const [tick, forceTick] = useState(0);
    const running = current?.phase === 'running';
    useEffect(() => {
        if (!running) return;
        const t = window.setInterval(() => forceTick((n) => n + 1), 300);
        return () => window.clearInterval(t);
    }, [running]);

    const start = useCallback(async () => {
        if (!workflowId) return;
        ensureListener();
        liveRuns.byWorkflow[workflowId] = {
            scenario,
            conversationId: null,
            phase: 'running',
            rows: [],
            reply: '',
            error: null,
            startedAt: Date.now(),
        };
        const fail = (message: string) => {
            const s = liveRuns.byWorkflow[workflowId];
            if (s) {
                s.error = message;
                s.phase = 'done';
            }
        };
        try {
            const patch = Object.fromEntries(
                Object.entries(leadPatch ?? {}).filter(
                    ([, v]) => typeof v === 'string' && v.trim()
                )
            );
            const res: any = await sendEventAsync(
                RehearsalRunRequest.create({
                    workflow_id: workflowId,
                    scenario,
                    ...(Object.keys(patch).length ? { lead_patch: patch } : {}),
                })
            );
            if (!res?.success) {
                fail(res?.message || 'The test could not start.');
                return;
            }
            const s = liveRuns.byWorkflow[workflowId];
            if (s) s.conversationId = res.conversation_id;
        } catch (e) {
            fail(e instanceof Error ? e.message : String(e));
        }
    }, [workflowId, scenario, leadPatch]);

    return useMemo<LiveRunState>(() => {
        void tick;
        const now = Date.now();
        return {
            phase: current?.phase ?? 'idle',
            t: current && current.phase === 'running' ? now - current.startedAt : 0,
            rows: toReplayRows(current?.rows ?? [], now),
            artifacts:
                current?.phase === 'done' ? deriveArtifacts(current?.rows ?? []) : null,
            failed: current?.phase === 'done' && Boolean(current.error),
            start,
            replay: start,
            error: current?.error ?? null,
            reply: current?.reply ?? '',
        };
    }, [current, start, tick]);
}
