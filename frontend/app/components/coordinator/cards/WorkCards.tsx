// Cards for work the coordinator set going or looked into: a request it sent an agent (message_agent), a video it's
// making (generate_video), a run it read (get_run), a reminder it set (schedule_alarm), an automation it paused,
// resumed, trashed or restored, and the pages a turn's web searches found.
import { useState } from 'react';
import { ArrowUpRight, Bell, BellOff, Pause, Video } from 'lucide-react';
import { toast } from 'sonner';
import { NodeMark } from '~/components/dashboard/primitives';
import { LiveWork, useLiveState, type LiveState } from '~/components/coordinator/inline/live';
import { sourceKey, VideoCard, type Source } from '~/components/coordinator/inline/media';
import { GlyphTile, PILL_QUIET, Receipt } from '~/components/coordinator/inline/primitives';
import { CheckBackLine, RunCard } from '~/components/coordinator/inline/work';
import { useCoordinatorAlarm } from '~/hooks/useCoordinatorAlarms';
import { isActiveJob, useCoordinatorJob } from '~/hooks/useCoordinatorJobs';
import { useWorkflowGraph } from '~/hooks/useWorkflowGraph';
import { askNoClick } from '~/lib/askNoClick';
import { failed, list, num, obj, str, type CoordinatorToolCall, type JsonObject } from '~/lib/coordinatorToolCalls';
import { navigateToWorkflow } from '~/lib/navigation';
import { socketCall } from '~/lib/socketCall';
import { cn } from '~/lib/utils';
import { whenAt } from '../format';

function until(job: JsonObject | undefined): number | undefined {
    const at = str(job, 'updated_at');
    return at ? Date.parse(at) : undefined;
}

function clip(text: string, max = 90): string {
    const line = text.replace(/\s+/g, ' ').trim();
    return line.length > max ? `${line.slice(0, max - 1)}…` : line;
}

function liveStateOf(job: JsonObject | undefined): LiveState {
    const status = str(job, 'status');
    if (status === 'completed') return 'done';
    if (status === 'failed') return 'failed';
    if (status === 'cancelled') return 'stopped';
    return 'running';
}

// ── An agent working on what the coordinator asked ──────────────────────────

export function AgentRequestCard({ call }: { call: CoordinatorToolCall }) {
    const sent = obj(call.result, 'job');
    const jobId = str(sent, 'job_id');
    const { live, job } = useCoordinatorJob(jobId);
    const [state, setState] = useLiveState(liveStateOf(job));
    if (!sent || !jobId) return null;
    // Followed only while the ledger still has it.
    const following = live && !!job;
    const agent = str(sent, 'agent_name') || 'the agent';
    const workflowId = str(sent, 'workflow_id');
    const asked = str(sent, 'message') || str(call.args, 'message') || '';
    const open = workflowId ? (
        <button type="button" className={cn(PILL_QUIET, 'h-7')} onClick={() => navigateToWorkflow({ id: workflowId, name: agent })}>
            Open
        </button>
    ) : undefined;
    if (!following) {
        return (
            <Receipt tone="info" lead={<NodeMark type="agent" size="sm" />} action={open}>
                Sent to {agent}. Its reply shows up here.
            </Receipt>
        );
    }
    return (
        <LiveWork
            lead={<NodeMark type="agent" size="md" className="mt-0.5" />}
            title={agent}
            meta={asked ? `Working on: ${clip(asked)}` : undefined}
            since={call.startedAt}
            until={isActiveJob(job) ? undefined : until(job)}
            state={state}
            onState={setState}
            current={str(job, 'status') === 'queued' ? 'Waiting to start' : 'Working'}
            done={`${agent} replied`}
            doneAction={open}
            failure={{ reason: str(job, 'error') || `${agent} couldn’t finish.`, actions: open }}
        />
    );
}

// ── A video being made ───────────────────────────────────────────────────────

export function VideoJobCard({ call }: { call: CoordinatorToolCall }) {
    const jobId = str(call.result, 'job_id');
    const { live, job } = useCoordinatorJob(jobId);
    const [state, setState] = useLiveState(liveStateOf(job));
    if (!jobId) return null;
    const seconds = num(call.result, 'seconds');
    const resolution = str(call.result, 'resolution');
    const spec = [seconds && `${seconds}s`, resolution].filter(Boolean).join(' · ');
    const url = str(obj(job, 'result'), 'url');
    const following = live && !!job;
    if (state === 'done' && url) return <VideoCard src={url} caption={[clip(str(call.args, 'prompt') || 'Your video', 60), spec].filter(Boolean).join(' · ')} />;
    if (!following) {
        return (
            <Receipt tone="info" lead={<Video className="h-4 w-4 shrink-0 text-foreground/60" />}>
                Making a video{spec ? ` (${spec})` : ''}. It shows up here when it’s ready.
            </Receipt>
        );
    }
    return (
        <LiveWork
            lead={
                <GlyphTile>
                    <Video className="h-4 w-4" />
                </GlyphTile>
            }
            title="Making a video"
            meta={[spec, clip(str(call.args, 'prompt') || '', 70)].filter(Boolean).join(' · ')}
            since={call.startedAt}
            until={isActiveJob(job) ? undefined : until(job)}
            state={state}
            onState={setState}
            current="Rendering"
            done="Video made"
            failure={{ reason: str(job, 'error') || 'The video couldn’t be made.' }}
        />
    );
}

// ── A run the coordinator read ───────────────────────────────────────────────

const TRIGGERS: Record<string, string> = { manual: 'run by hand', schedule: 'on its schedule', cron: 'on its schedule', webhook: 'from a webhook' };

export function RunResultCard({ call }: { call: CoordinatorToolCall }) {
    const run = obj(call.result, 'run');
    const workflowId = str(run, 'workflow_id');
    const { graph } = useWorkflowGraph(workflowId, false);
    if (!run || !workflowId) return null;
    const name = graph?.name || 'The automation';
    const started = str(run, 'started_at');
    const trigger = str(run, 'trigger');
    const status = str(run, 'status');
    const steps = list(run, 'nodes').flatMap((n) => {
        const node = n as JsonObject;
        const label = str(node, 'label') || str(node, 'node_id');
        return label ? [{ label, error: str(node, 'status') === 'error' ? str(node, 'error') || 'failed' : undefined }] : [];
    });
    return (
        <RunCard
            name={name}
            when={[started && whenAt(started), trigger && (TRIGGERS[trigger] ?? trigger.replace(/_/g, ' '))].filter(Boolean).join(' · ')}
            steps={steps}
            failed={status === 'error' || status === 'failed'}
            actions={
                <button type="button" className={PILL_QUIET} onClick={() => navigateToWorkflow({ id: workflowId, name })}>
                    Open automation
                    <ArrowUpRight className="h-3.5 w-3.5" />
                </button>
            }
        />
    );
}

// ── A reminder ───────────────────────────────────────────────────────────────

// Still to come, it can be cancelled; read back, a one-off that went off reads as done and one called off says so.
// Until it's read back (or where it can't be), the card says what the tool reported.
export function AlarmLine({ call }: { call: CoordinatorToolCall }) {
    const { alarm } = useCoordinatorAlarm(str(call.result, 'schedule_id'));
    const message = str(call.args, 'message');
    if (failed(call.result) || !message) return null;
    const recurring = str(call.args, 'alarm_type') === 'cron';
    const next = str(alarm, 'next_run') ?? str(call.result, 'next_run');
    const what = clip(message, 120);
    const status = str(alarm, 'status');
    const firedAt = str(alarm, 'fired_at');
    if (!recurring && firedAt) return <Receipt>Reminded you {whenAt(firedAt)}: {what}</Receipt>;
    if (status === 'cancelled') return <Receipt tone="info" lead={<BellOff className="h-4 w-4 shrink-0 text-foreground/60" />}>Cancelled: {what}</Receipt>;
    // Stopped without going off (its delivery failed).
    if (alarm && status !== 'scheduled') return <Receipt tone="info" lead={<Bell className="h-4 w-4 shrink-0 text-foreground/60" />}>Was due {next ? whenAt(next) : 'earlier'}: {what}</Receipt>;
    return (
        <CheckBackLine
            when={next ? `${recurring ? 'next ' : ''}${whenAt(next)}` : 'later'}
            what={what}
            action={
                <button type="button" className={cn(PILL_QUIET, 'h-7')} onClick={() => askNoClick(`Cancel the reminder “${clip(message, 80)}”`)}>
                    Cancel…
                </button>
            }
        />
    );
}

// ── An automation paused, resumed, trashed or restored ───────────────────────

export function WorkflowChangeLine({ call }: { call: CoordinatorToolCall }) {
    const [restored, setRestored] = useState(false);
    const workflowId = str(call.args, 'workflow_id');
    if (failed(call.result) || !workflowId) return null;
    if (call.tool === 'pause_workflow') {
        const paused = list(call.result, 'paused_triggers').filter((t): t is string => typeof t === 'string');
        return (
            <Receipt
                tone="info"
                lead={<Pause className="h-4 w-4 shrink-0 text-foreground/60" />}
                action={
                    <button type="button" className={cn(PILL_QUIET, 'h-7')} onClick={() => askNoClick('Resume the automation you just paused')}>
                        Resume…
                    </button>
                }
            >
                Paused {paused.length ? paused.join(', ') : 'its triggers'}
                {str(call.args, 'reason') ? ` · ${clip(str(call.args, 'reason')!, 80)}` : ''}
            </Receipt>
        );
    }
    if (call.tool === 'resume_workflow') {
        const resumed = list(call.result, 'resumed_triggers').filter((t): t is string => typeof t === 'string');
        return <Receipt>Switched {resumed.length ? resumed.join(', ') : 'its triggers'} back on</Receipt>;
    }
    if (call.tool === 'restore_workflow') return <Receipt>Restored from Trash</Receipt>;
    return (
        <Receipt
            tone="info"
            action={
                !restored && (
                    <button
                        type="button"
                        className={cn(PILL_QUIET, 'h-7')}
                        onClick={() =>
                            socketCall('workflow:restore', { workflow_id: workflowId })
                                .then(() => setRestored(true))
                                .catch((e: unknown) => toast.error(e instanceof Error ? e.message : 'Could not restore it'))
                        }
                    >
                        Restore
                    </button>
                )
            }
        >
            {restored ? 'Restored from Trash' : 'Moved to Trash · kept for 30 days'}
        </Receipt>
    );
}

// ── What a turn's web searches found ────────────────────────────────────────

const LINK = /https?:\/\/[^\s<>()[\]"'`]+/g;

/** Every page the turn's web searches found, once each, the ones the reply links to first: a search returns more
 *  than the answer used, and searches in one turn overlap. */
export function turnSources(calls: readonly CoordinatorToolCall[], text = ''): Source[] {
    const cited = new Set((text.match(LINK) ?? []).map((url) => sourceKey(url.replace(/[.,;:!?]+$/, ''))));
    const pages = new Map<string, Source>();
    for (const call of calls) {
        if (call.tool !== 'web_search' || call.running) continue;
        for (const r of list(call.result, 'results')) {
            const row = r as JsonObject;
            const url = str(row, 'url');
            if (url && !pages.has(sourceKey(url))) pages.set(sourceKey(url), { url, title: str(row, 'title') ?? '' });
        }
    }
    const all = [...pages];
    return [...all.filter(([key]) => cited.has(key)), ...all.filter(([key]) => !cited.has(key))].map(([, source]) => source);
}
