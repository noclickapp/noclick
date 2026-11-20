// A NoClick agent another one started (its `agents__spawn`): a real agent with its own session, never inline.
// Its row in the parent's log says who it is, what it was given, and where it stands, and opens it.
import { ChevronRight } from 'lucide-react';
import { MemberAvatar } from '@/screens/channels/avatars';
import type { AgentState as FaceState } from '@/screens/channels/types';
import { cn } from '@/ui/utils';
import { useAgentFaces, useAgentStates } from '../agents/reads';
import { nowWords } from '../agents/states';
import { useWorkNav } from '../nav';
import type { Step } from '@/lib/agentThread/thread';

export interface Child {
    agentId: string;
    name: string;
    task: string;
    /** Its task's operation (cancelled to stop it). */
    jobId: string | null;
}

/** A call's answer as an object: as it came, or the JSON text (or text content) a harness passed it on as. */
function answerOf(result: unknown): Record<string, unknown> | null {
    if (typeof result === 'string') {
        try {
            return answerOf(JSON.parse(result));
        } catch {
            return null;
        }
    }
    if (Array.isArray(result)) return answerOf(result.map((r) => (r && typeof r === 'object' && typeof (r as { text?: unknown }).text === 'string' ? (r as { text: string }).text : '')).join(''));
    if (!result || typeof result !== 'object') return null;
    const r = result as Record<string, unknown>;
    return Array.isArray(r.content) && !('agent_id' in r) ? answerOf(r.content) : r;
}

/** The agent a step started, where the step is an `agents__spawn` (on its own, or through a harness's MCP) that it
 *  answered. */
export function spawnedChild(step: Step): Child | null {
    if (!/(^|__)agents__spawn$/.test(step.tool)) return null;
    const answer = answerOf(step.result);
    const agentId = answer && typeof answer.agent_id === 'string' ? answer.agent_id : null;
    if (!agentId) return null;
    const name = typeof answer?.name === 'string' && answer.name ? answer.name : typeof step.arguments.name === 'string' && step.arguments.name ? step.arguments.name : 'An agent';
    return { agentId, name, task: String(step.arguments.task ?? '').split('\n')[0], jobId: typeof answer?.job_id === 'string' ? answer.job_id : null };
}

/** Where a child agent stands, as its mascot's face. */
const CHILD_FACE = { working: 'working', waiting: 'needs', failed: 'failed', done: 'done' } as const satisfies Record<string, FaceState>;

/** Its row: its face and name, what it was given, where it stands (working, waiting on you, done), and Open. */
export function ChildAgentRow({ child }: { child: Child }) {
    const nav = useWorkNav();
    const faces = useAgentFaces();
    const state = useAgentStates(null).data?.find((s) => s.agentId === child.agentId);
    const face = faces.get(child.agentId) ?? { id: child.agentId, kind: 'agent' as const, name: child.name, agentId: child.agentId };
    const where = state?.state === 'working' || state?.state === 'waking' ? 'working' : state?.state === 'needs_you' ? 'waiting' : state?.state === 'failed' ? 'failed' : state ? 'done' : null;
    const line = where === 'working' ? nowWords(state?.now) || 'Working' : where === 'waiting' ? 'Waiting on you' : where === 'failed' ? `Failed: ${state?.failed?.message ?? 'its turn didn’t finish'}` : where === 'done' ? 'Done' : null;
    return (
        <li data-child-agent={child.agentId}>
            <button
                type="button"
                onClick={() => nav.openAgent(child.agentId)}
                className="group/child flex w-full items-center gap-2 rounded-lg px-0.5 py-1 text-left transition-colors hover:bg-foreground/[0.04] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/70"
            >
                <span className="grid h-6 w-6 shrink-0 place-items-center">
                    <MemberAvatar member={face} size={20} state={where ? CHILD_FACE[where] : undefined} />
                </span>
                <span className="min-w-0 flex-1">
                    <span className="flex min-w-0 items-baseline gap-1.5 text-sm">
                        <span className="shrink-0 font-medium text-foreground/90">{face.name}</span>
                        {child.task && <span className="min-w-0 truncate text-muted-foreground">{child.task}</span>}
                    </span>
                    {line && (
                        <span className="flex min-w-0 items-center gap-1.5 whitespace-nowrap text-xs text-muted-foreground" data-testid="child-agent-state">
                            <span className={cn('h-1.5 w-1.5 shrink-0 rounded-full', where === 'working' ? 'work-breathe bg-foreground/60' : where === 'waiting' ? 'bg-foreground' : where === 'failed' ? 'bg-red-500' : 'bg-foreground/30')} />
                            <span className={cn('min-w-0 truncate', where === 'working' && 'work-shine', where === 'waiting' && 'text-foreground/85')}>{line}</span>
                        </span>
                    )}
                </span>
                <span className="inline-flex shrink-0 items-center gap-0.5 text-xs text-muted-foreground transition-colors group-hover/child:text-foreground">
                    Open
                    <ChevronRight className="h-3.5 w-3.5" strokeWidth={2} />
                </span>
            </button>
        </li>
    );
}
