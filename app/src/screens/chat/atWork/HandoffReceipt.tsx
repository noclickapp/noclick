// Under the message that handed a change to an app's coding agent, once its job is done: one line of what changed and
// how long it took, and the way to the change. While it works the Beside is where it's followed, so nothing is drawn
// here until then; a job that failed or was stopped is the coordinator's to tell. While the account's cap (or its
// balance) holds the agent, the hold is drawn here, where the work it holds was handed over, with its one action: the
// same ask the Beside's Needs you lists, which jumps here.
import { useRef } from 'react';
import { standing } from '@/slots';
import { Link } from 'react-router';
import { Check } from 'lucide-react';
import { PILL_PRIMARY } from '@/ui/chat/primitives';
import type { CoordinatorJob } from '@/lib/threadJobs';
import { useCoordinatorJob } from '../cards/toolCardRegistry';
import { list, obj, str, type CoordinatorToolCall } from '@/lib/toolCalls';
import { cn } from '@/ui/utils';
import { useNeeds } from '../beside/needs';
import type { NeedsYou } from '../beside/model';
import { FitWords, useInkCentring } from '@/screens/chat/atWork/ink';
import { CHAT_PLACES } from '../slots';
import { taskOf } from './model';
import { durationWords, QuietPill } from '@/screens/chat/atWork/pieces';

export function HandoffReceiptCard({ call }: { call: CoordinatorToolCall }) {
    const handed = obj(call.result, 'response');
    const { job } = useCoordinatorJob(str(handed, 'operation_id'));
    const agentId = str(handed, 'agent_id');
    const { needs, draft } = useNeeds();
    const hold = agentId ? needs.find((n) => n.held.includes(agentId)) : undefined;
    if (hold) return <Held need={hold} draft={draft} />;
    return job?.status === 'completed' ? <Receipt job={job} /> : null;
}

/** "Your $50 monthly cap paused Larkspur · Raise cap": the account's hold on the agent this hand-off went to. */
function Held({ need, draft }: { need: NeedsYou; draft: (text: string) => void }) {
    const action = cn(PILL_PRIMARY, 'h-7 px-3 text-[12.5px]');
    const ask = need.ask;
    return (
        <div className="mt-3 flex max-w-[560px] items-center gap-2.5 text-[13.5px]" data-testid="held-note">
            <span className="h-2 w-2 shrink-0 rounded-full bg-foreground ring-[3px] ring-foreground/15" aria-hidden />
            <span className="min-w-0 flex-1 text-foreground">
                {need.sentence}
            </span>
            {ask?.href ? (
                <Link to={ask.href} className={action}>
                    {ask.label}
                </Link>
            ) : ask ? (
                <button type="button" className={action} onClick={() => draft(ask.draft ?? '')}>
                    {ask.label}
                </button>
            ) : null}
        </div>
    );
}

function Receipt({ job }: { job: CoordinatorJob }) {
    const root = useRef<HTMLDivElement>(null);
    useInkCentring(root);
    const code = obj(obj(job, 'result'), 'code');
    const newest = list(code, 'commits')[0] as Record<string, unknown> | undefined;
    const sha = str(newest, 'sha');
    const repo = str(code, 'repo_id');
    const since = Date.parse(job.created_at);
    const until = Date.parse(str(job, 'finished_at') ?? job.updated_at);
    return (
        <div ref={root} className="mt-3 flex max-w-[560px] items-center gap-2 text-[13.5px] text-muted-foreground" data-testid="handoff-receipt">
            <Check className="h-4 w-4 shrink-0 text-foreground/70" strokeWidth={2.25} />
            <span className="min-w-0 flex-1">
                <FitWords text={str(newest, 'message') ?? taskOf(str(job, 'title'), str(job, 'summary'))} quiet={`done in ${durationWords((until - since) / 1000)}`} className="leading-[20px]" />
            </span>
            {sha && repo && (
                <QuietPill href={standing(CHAT_PLACES).href('resources', { kind: 'repos', resource: repo, view: 'commit', sha })} way={false}>
                    See the change
                </QuietPill>
            )}
        </div>
    );
}
