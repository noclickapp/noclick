// NoClick's platform tools, drawn by what a call answered (the card table, cards.tsx):
// - a purchase or a deletion held for a person (status awaiting_approval): what's asked, its price or what goes with
//   it, then, for the account's signed-in owner, Approve or Decline right here: read and answered on /v1 with the page's
//   client, as the approval page reads and answers it (a key reads it and opens that page, ownerOnly.ts). Terms only a
//   person accepts are ticked on that page, never in the chat, so such an approval opens it;
// - an operation still going: drawn as its stages, followed through the job waiting on it (or the operation, on the
//   agent's thread, with the progress its runner reports) until it settles; only the newest card about a site (its
//   deploys and checks) or about one operation (read again while it runs) is drawn;
// - a workflow being built (workflow.build): on its canvas, as the coordinator's own builds are, read on /v1 (its graph,
//   and the question its operation waits on);
// - an agent made or changed: its name and job, when it runs and what it uses (a channel made or joined is
//   ChannelCard.tsx, the channel itself, which carries the agent its turn made);
// - an app served at a domain (projects_domains_create): where the site is now.
// A link the owner pays (account_payment_links_create) is its own card (moneyLinks.tsx).
// Credential approvals answer pending_approval and draw their own card; the two never meet.
import { ArrowUpRight, CreditCard, Globe, ShieldCheck, Trash2 } from 'lucide-react';
import { useContext, useEffect, useState, type ReactNode } from 'react';
import { standing, useSlot } from '@/slots';
import { AskCard, AskMark, AskRow, InlineCard, PILL_PRIMARY, PILL_QUIET, Receipt, Status } from '@/ui/chat/primitives';
import { NodeMark } from '@/ui/primitives';
import { MemberAvatar } from '@/screens/channels/avatars';
import { hueFor, seatMembers } from '@/screens/channels/model';
import type { ChannelMember } from '@/screens/channels/types';
import { approvalUrl } from '@/screens/console/lib/site';
import { useOwnerOnly } from '@/screens/console/ownerOnly';
import { openAgentInWork } from '@/screens/work/place';
import { ProgressMotion } from '@/ui/chat/motion';
import { useNow } from '@/lib/clock';
import { isActiveJob, type CoordinatorJob } from '@/lib/threadJobs';
import { continuedBy, GONE, heldOperationOf } from '@/sdk/useFollowedOperations';
import { list, obj, str, type CoordinatorToolCall, type JsonObject } from '@/lib/toolCalls';
import { cn } from '@/ui/utils';
import { impactRows } from '@/screens/resources/platform';
import { priceLabel, type ApprovalImpact, type ApprovalView } from '../approvals';
import { heldAskOf } from '../atWork/model';
import { ChatSourceContext } from '../source';
import { BUILD_QUESTION, CHAT_PLACES, CONNECT_LINK } from '../slots';
import { useSite } from '../site';
import { jobOf, usesLine, whatItUses, whenItRuns } from './agentWords';
import { BuildBody, stateOf } from './BuildCard';
import { useDrawsCanvas, useNewerCard } from './canvases';
import type { BuildState } from './inline/setup';
import { WorkCard } from './progress/WorkCard';
import { workViewOf } from './progress/workView';
import { OwnerQuestion } from './OwnerQuestionCard';
import { connectAskOf, CoordinatorJobsContext, useCoordinatorJob } from './toolCardRegistry';
import { useAgentCard } from './useTeamCards';
import { useBuiltWorkflow } from './useBuiltWorkflow';
import { usePlatformApproval } from './usePlatformApproval';
import { agentOf, buildOf, connectLinkOf, operationCanvas, servedDomainOf, servedNames } from './cardMatchers';

export {
    agentCanvas,
    isChannelCard,
    isConnectLink,
    isDomainServed,
    isPlatformAgent,
    isPlatformApproval,
    isPlatformOperation,
    isWorkflowBuild,
    operationCanvas,
    workflowBuildCanvas,
} from './cardMatchers';

function jobError(job: CoordinatorJob | undefined): string | undefined {
    return str(job, 'error') ?? str(obj(job, 'error'), 'message');
}

// ── A purchase or a deletion to approve ──────────────────────────────────────

/** What the tool itself answered, until the page's read says how it stands now. */
function asAnswered(call: CoordinatorToolCall): ApprovalTold {
    const price = obj(call.result, 'price');
    return {
        action: str(call.result, 'summary') ?? 'What NoClick asked to do',
        price: price && typeof price.amount_usd === 'number' ? (price as unknown as ApprovalView['price']) : null,
        impact: (obj(call.result, 'impact') as unknown as ApprovalImpact | undefined) ?? null,
        status: str(call.result, 'status') === 'approved_running' ? 'approved' : 'pending',
        expiresAt: str(call.result, 'expires_at'),
        terms: list(call.result, 'accepting').filter((t): t is string => typeof t === 'string'),
    };
}

/** What an approval was asked as (the held call's own words, its price, what a deletion takes), until it's read. */
export type ApprovalTold = Pick<ApprovalView, 'action' | 'price' | 'impact'> & { status: ApprovalView['status']; expiresAt?: string; terms: string[] };

function WhatGoes({ impact }: { impact: ApprovalImpact }) {
    return (
        <div className="space-y-1 text-[13.5px] leading-snug">
            <p className="text-foreground">{impact.deletes}</p>
            {impactRows(impact).map(({ term, items }) => (
                <p key={term}>
                    <span className="text-muted-foreground">{term}: </span>
                    {items.join('; ')}
                </p>
            ))}
            <p className="text-muted-foreground">{impact.reversible ? 'It can be undone.' : 'It can’t be undone.'}</p>
        </div>
    );
}

/** Once it's approved: whether it has run, from the held call's operation, which the approval runs, and through the
 *  work its run started (a domain registering) when it started some. */
function AfterApproval({ action, used, operationId }: { action: string; used: boolean; operationId?: string }) {
    const { job: followed } = useCoordinatorJob(operationId);
    // A held call this tab can't read says nothing of how it went: the approval's own line stands.
    const job = str(followed, 'error') === GONE ? undefined : followed;
    const status = str(job, 'status');
    const next = continuedBy(job);
    if (status === 'completed' && next) {
        const started = obj(obj(job, 'result'), 'response');
        return <OperationWork jobId={next} what={action} kind={str(started, 'kind')} step={str(started, 'step')} since={Date.parse(str(job, 'updated_at') ?? '') || Date.now()} />;
    }
    if (status === 'completed') return <Receipt>Done · {action}</Receipt>;
    if (status === 'failed' || status === 'cancelled') {
        return <Receipt tone="info">Approved, but it didn’t go through · {jobError(job) || action}</Receipt>;
    }
    return <Receipt>{used ? `Approved and run · ${action}` : `Approved · NoClick is doing it now: ${action}`}</Receipt>;
}

export function PlatformApprovalCard({ call }: { call: CoordinatorToolCall }) {
    return <ApprovalAsk approvalId={str(call.result, 'approval_id') ?? ''} told={asAnswered(call)} heldOperationId={heldOperationOf(call)} />;
}

/** A purchase or a deletion held for the owner's OK, as one ask's row: what it does, its price, and Decline and
 *  Approve right here for the account's signed-in owner (read and answered on /v1, as its page does); what a
 *  deletion takes and the terms a person ticks on its page, under it. Where the reader isn't who answers it (a
 *  channel's other people: `mayAnswer` false) it reads as waiting on the owner, settled by NoClick's word of how it
 *  went (`settled`, the held call's status) rather than the approval's own read. */
export function ApprovalAsk({
    approvalId,
    told,
    heldOperationId,
    mayAnswer = true,
    settled,
}: {
    approvalId: string;
    told: ApprovalTold;
    heldOperationId?: string;
    mayAnswer?: boolean;
    settled?: string | null;
}) {
    const review = usePlatformApproval(mayAnswer ? approvalId : '');
    const live = review.approval;
    const action = live?.action || told.action;
    const price = live ? live.price : told.price;
    const impact = live ? (live.impact ?? null) : told.impact;
    const terms = live ? (live.consent ?? []).map((c) => c.title) : told.terms;
    const expiresAt = live?.expires_at ?? told.expiresAt;
    const lapsed = (live?.status ?? told.status) === 'pending' && !!expiresAt && Date.parse(expiresAt) <= Date.now();
    const status = lapsed ? 'expired' : (live?.status ?? told.status);
    // NoClick's approval page, wherever the link the tool answered points.
    const page = approvalUrl(useSite(), approvalId);
    // Only the account's signed-in owner answers it here; a key opens its page.
    const answers = useOwnerOnly()('approvals') && mayAnswer;

    if (settled === 'succeeded') return <Receipt>Approved · {action}</Receipt>;
    if (settled) return <Receipt tone="info">Not approved, so nothing happened · {action}</Receipt>;
    if (status === 'approved' || status === 'used') return <AfterApproval action={action} used={status === 'used'} operationId={heldOperationId} />;
    if (status === 'declined') return <Receipt tone="info">Declined · nothing happened: {action}</Receipt>;
    if (status === 'expired') return <Receipt tone="info">Nobody approved it in time, so nothing happened: {action}</Receipt>;
    if (status === 'canceled') return <Receipt tone="info">Withdrawn · nothing happened: {action}</Receipt>;

    const open = (label: string, className: string) => (
        <a href={page} target="_blank" rel="noopener noreferrer" className={className} data-testid="platform-approval-open">
            {label}
            <ArrowUpRight className="h-3.5 w-3.5" />
        </a>
    );
    const ready = !!live && !review.answering;
    const decline = (
        <button type="button" className={PILL_QUIET} disabled={!ready} onClick={() => review.decide('decline')}>
            Decline
        </button>
    );
    // Approving with terms ticks a box per term, which only the page has; so does an approval this tab can't read here.
    let actions: ReactNode;
    if (!mayAnswer) actions = <Status state="idle">Waiting for the owner’s OK</Status>;
    else if (terms.length > 0 || review.unreadable || !answers) {
        actions = (
            <>
                {terms.length > 0 && answers && decline}
                {open(!answers ? 'Review on NoClick' : terms.length ? 'Review terms and approve' : 'Open to approve', PILL_PRIMARY)}
            </>
        );
    } else {
        actions = (
            <>
                {decline}
                <button type="button" className={PILL_PRIMARY} disabled={!ready} onClick={() => review.decide('approve')}>
                    Approve
                </button>
            </>
        );
    }
    const Icon = impact ? Trash2 : price ? CreditCard : ShieldCheck;
    const whose = mayAnswer ? 'your' : 'the owner’s';
    const more = mayAnswer && (price?.terms || impact || terms.length > 0 || review.failure || (!live && !review.unreadable));
    return (
        <AskCard testId="platform-approval">
            <AskRow
                lead={
                    <AskMark>
                        <Icon />
                    </AskMark>
                }
                title={heldAskOf({ action, price, impact, operation: live?.operation, arguments: live?.arguments, subject: live?.subject }).title}
                detail={price ? `${priceLabel(price)} · waiting for ${whose} OK` : `Waiting for ${whose} OK`}
                action={actions}
            >
                {more ? (
                    <div className="space-y-2">
                        {price?.terms && <p className="text-[13px] leading-relaxed text-muted-foreground">{price.terms}</p>}
                        {impact && <WhatGoes impact={impact} />}
                        {terms.length > 0 && (
                            <p className="text-[13px] leading-relaxed text-muted-foreground" data-testid="platform-approval-terms">
                                Approving accepts {terms.join(' and ')}. You read and tick each on the approval page; NoClick never accepts terms for you.
                            </p>
                        )}
                        {!live && !review.unreadable && <Status state="working">Checking it’s still waiting</Status>}
                        {review.failure && (
                            <p className="text-[13px] text-red-600 dark:text-red-400">
                                {review.failure.message}
                                {review.failure.next_step ? ` ${review.failure.next_step}` : ''}
                            </p>
                        )}
                    </div>
                ) : null}
            </AskRow>
        </AskCard>
    );
}

// ── An operation still going ─────────────────────────────────────────────────

/** The operation a result answered with, when it carries one whole. */
function operationOf(result: JsonObject | undefined, id: string): JsonObject | undefined {
    return Object.values(result ?? {}).find(
        (v): v is JsonObject => !!v && typeof v === 'object' && !Array.isArray(v) && (v as JsonObject).object === 'operation' && (v as JsonObject).id === id
    );
}

/** Work an operation is doing, drawn as its stages (each a check and how long it took, the live one with its last
 *  line and how fresh it is) through what the job waiting on it says, as the thread follows it (or the operation, on
 *  a thread that follows those, with the progress its runner reports), until it settles into one line. Until either
 *  says anything, it's the work as the call answered it. Failed, it can be asked for again in the chat. */
export function OperationWork({
    jobId,
    job: followed,
    what,
    kind,
    step,
    waiting,
    since,
    doneAction,
}: {
    jobId?: string;
    /** The job as its card follows it, where the thread doesn't (the domain picker's purchase, by its frames). */
    job?: CoordinatorJob;
    what: string;
    kind?: string;
    step?: string;
    waiting?: boolean;
    since: number;
    doneAction?: ReactNode;
}) {
    const thread = useCoordinatorJob(jobId);
    const job = followed ?? thread.job;
    const chat = useContext(ChatSourceContext);
    const view = workViewOf({
        // The operation's own kind; a coordinator job's is only `platform`.
        kind: kind ?? str(job, 'kind'),
        title: str(job, 'summary') ?? what,
        status: str(job, 'status') ?? (waiting ? 'awaiting_human' : 'running'),
        startedAt: Date.parse(str(job, 'created_at') ?? '') || since,
        updatedAt: Date.parse(str(job, 'updated_at') ?? '') || undefined,
        progress: job?.progress ?? (step ? { step } : undefined),
        error: jobError(job),
        result: job?.result,
    });
    const now = useNow(view.state === 'running' || view.state === 'waiting');
    return (
        <>
            <ProgressMotion />
            <WorkCard view={view} now={now} onRetry={chat ? () => chat.send(view.retry) : undefined} doneAction={doneAction} />
        </>
    );
}

export function PlatformOperationCard({ call }: { call: CoordinatorToolCall }) {
    const newer = useNewerCard(call.id, operationCanvas(call, useContext(CoordinatorJobsContext)));
    if (newer) return null;
    return <OperationCard call={call} />;
}

function OperationCard({ call }: { call: CoordinatorToolCall }) {
    const operationId = str(call.result, 'operation_id') ?? '';
    // The job waiting on it, or, where the thread follows operations themselves (the coordinator agent's), the operation.
    const jobId = str(call.result, 'job_id') ?? operationId;
    const operation = operationOf(call.result, operationId);
    const what = str(operation, 'summary') || str(call.result, 'summary') || (str(operation, 'kind') ?? 'The work').replace(/[._]/g, ' ');
    return (
        <OperationWork
            jobId={jobId}
            what={what}
            kind={str(operation, 'kind')}
            step={str(operation, 'step')}
            waiting={str(call.result, 'status') === 'awaiting_human'}
            since={call.startedAt}
        />
    );
}

// ── A workflow being built ───────────────────────────────────────────────────

/** A build through the platform API, drawn as the coordinator's own builds are: on the canvas, its question below. */
export function PlatformBuildCard({ call }: { call: CoordinatorToolCall }) {
    const build = buildOf(call)!;
    const jobId = str(call.result, 'job_id') ?? str(call.result, 'operation_id');
    const { job } = useCoordinatorJob(jobId);
    const workflowId = build.workflowId ?? str(job, 'workflow_id');
    // Until the operation is read, a workflow the call didn't name is followed as any operation is.
    if (!workflowId) return <PlatformOperationCard call={call} />;
    return <PlatformWorkflowBuild callId={call.id} workflowId={workflowId} jobId={jobId} reported={build.operation ?? { status: str(call.result, 'status') }} name={build.name} />;
}

/** The build read on /v1: its automation's graph (Workflow.graph()), re-read while it builds, and the question its
 *  operation carries while it waits on one (the thread follows the operation, so a question arrives as it's asked):
 *  each input a human request, answered on its own card as any question to the owner is; a question asked before
 *  its inputs were requests, with the host's form. */
function PlatformWorkflowBuild({ callId, workflowId, jobId, reported, name }: { callId: string; workflowId: string; jobId?: string; reported: JsonObject; name?: string }) {
    const { live, job } = useCoordinatorJob(jobId);
    const view: JsonObject | undefined = job ?? reported;
    // A question just answered gives way to the build going on with it, until it asks something else.
    const [sent, setSent] = useState<string | null>(null);
    const reportedState = stateOf(str(view, 'status'), live && !!job);
    const canvas = useDrawsCanvas(callId, workflowId);
    const { graph } = useBuiltWorkflow(workflowId, isActiveJob(job));
    // Only while it waits: a newer word on the operation without a question keeps the older one's.
    const questionId = reportedState === 'waiting' ? str(obj(view, 'question'), 'id') : undefined;
    const asking = questionId && questionId !== sent ? questionId : null;
    const state: BuildState = reportedState === 'waiting' && sent && !asking ? 'building' : reportedState;
    const Question = useSlot(BUILD_QUESTION);
    const asked = obj(view, 'question') ?? {};
    const requests = buildRequests(asked);
    const question =
        asking &&
        (requests.length > 0 ? (
            <div key={asking} className="mt-3 space-y-2.5" data-testid="coordinator-build-requests">
                {requests.map((r) => (
                    <OwnerQuestion key={r.requestId} requestId={r.requestId} asked={r.label} offered={r.options} />
                ))}
            </div>
        ) : (
            <Question key={asking} askId={asking} workflowId={workflowId} question={asked} onSending={setSent} />
        ));
    return <BuildBody workflowId={workflowId} view={view} state={state} graph={graph} name={name} canvas={canvas} question={question} />;
}

/** The human requests a build's question asks, in its order: each input that names one (a pick waiting for the
 *  account it reads with names none until it's asked). */
export function buildRequests(question: JsonObject): { requestId: string; label?: string; options: string[] }[] {
    return list(question, 'inputs').flatMap((raw) => {
        const input = raw as JsonObject;
        const requestId = str(input, 'request_id');
        if (!requestId) return [];
        const options = list(input, 'options').flatMap((o) => {
            const label = typeof o === 'string' ? o : (str(o as JsonObject, 'label') ?? str(o as JsonObject, 'id'));
            return label ? [label] : [];
        });
        return [{ requestId, label: str(input, 'label'), options }];
    });
}

// ── An agent made or changed ─────────────────────────────────────────────────

// How long after the call an agent's or a channel's card reads it again: the turn adds its triggers, channels and
// members in the calls after it.
export const AGENT_SETTLING_MS = 60_000;

/** Whether `since` is under `ms` ago, turning false once it isn't. */
function useWithin(since: number, ms: number): boolean {
    const [within, setWithin] = useState(() => Date.now() - since < ms);
    useEffect(() => {
        if (!within) return;
        const timer = window.setTimeout(() => setWithin(false), Math.max(0, since + ms - Date.now()));
        return () => window.clearTimeout(timer);
    }, [within, since, ms]);
    return within;
}

/** An agent the coordinator made or changed, as the person it works for reads it: its name, marked as an agent, and job, when it runs
 *  (its schedules, and the channels it answers in) and what it uses. It opens in Work from it, its profile beside,
 *  where it's changed. An older card about the same agent is one line. */
export function PlatformAgentCard({ call }: { call: CoordinatorToolCall }) {
    const made = agentOf(call)!;
    const newer = useNewerCard(call.id, made.workflowId);
    const name = made.name ?? 'Your agent';
    if (!newer) return <AgentCard call={call} />;
    return (
        <div data-testid="coordinator-agent-card" data-folded="">
            <Receipt tone="info" lead={<AgentAvatar agentId={made.agentId} name={name} size={16} />} action={<EditAgent agent={{ ...made, name }} folded />}>
                {name}
            </Receipt>
        </div>
    );
}

/** A channel's agents as the Channels page seats them: each in its colour and letters among the others there. */
function seatedAgents(channel: JsonObject | undefined): ChannelMember[] {
    return seatMembers(
        list(channel, 'members').flatMap((m) => {
            const member = m as JsonObject;
            const type = str(member, 'type');
            if (type !== 'agent' && type !== 'workflow_agent') return [];
            const [agentId, workflowId, nodeId] = [str(member, 'agent_id'), str(member, 'workflow_id'), str(member, 'node_id')];
            return [{ id: str(member, 'id') ?? '', kind: 'agent' as const, name: str(member, 'name') ?? 'agent', ...(agentId ? { agentId } : { workflowId, nodeId }) }];
        })
    );
}

/** An agent's avatar: as its first channel seats it, else in its own colour; `role` dresses its mascot. */
function AgentAvatar({ agentId, name, size, seat, role }: { agentId: string; name: string; size: 16 | 32; seat?: JsonObject; role?: string }) {
    const member = seatedAgents(seat).find((m) => m.agentId === agentId) ?? { id: agentId, kind: 'agent' as const, name, hue: hueFor(agentId) };
    return <MemberAvatar member={{ ...member, role }} size={size} />;
}

/** An agent to edit: a platform agent by its id, else (an automation's agent node in a channel) its automation. */
export interface EditableAgent {
    agentId?: string | null;
    workflowId?: string | null;
    name: string;
}

/** Where editing an agent opens: the agent in Work (its conversation, its profile beside); an automation's agent node,
 *  which Work doesn't hold, its automation. */
export function editAgent({ agentId, workflowId, name }: EditableAgent): void {
    if (agentId) openAgentInWork(agentId);
    else if (workflowId) standing(CHAT_PLACES).openWorkflow(workflowId, name);
}

function EditAgent({ agent, folded = false }: { agent: EditableAgent; folded?: boolean }) {
    return (
        <button type="button" className={cn(PILL_QUIET, folded && 'h-7')} onClick={() => editAgent(agent)}>
            Edit agent
            <ArrowUpRight className="h-3.5 w-3.5" />
        </button>
    );
}

function AgentCard({ call }: { call: CoordinatorToolCall }) {
    const made = agentOf(call)!;
    const settling = useWithin(call.startedAt, AGENT_SETTLING_MS);
    const { view, gone } = useAgentCard(made.agentId, settling);
    const name = str(view?.agent, 'name') ?? made.name ?? 'Your agent';
    if (gone) return <Receipt tone="info">{name} was deleted</Receipt>;
    const used = whatItUses(view?.agent);
    return (
        <div data-testid="coordinator-agent-card">
            <InlineCard lead={<AgentAvatar agentId={made.agentId} name={name} size={32} seat={view?.seats[0]?.channel} role={jobOf(view?.agent)} />} title={name} kind="Agent" meta={jobOf(view?.agent)} actions={<EditAgent agent={{ ...made, name }} />}>
                {view ? (
                    <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1.5 text-[14px] leading-snug">
                        <dt className="text-[12.5px] leading-[1.45rem] text-muted-foreground">Runs</dt>
                        <dd className="min-w-0 space-y-0.5 text-foreground/90">
                            {whenItRuns(view.agent, view.triggers, view.seats).map((line) => (
                                <p key={line}>{line}</p>
                            ))}
                        </dd>
                        <dt className="text-[12.5px] leading-[1.45rem] text-muted-foreground">Uses</dt>
                        <dd className="flex min-w-0 items-center gap-2 text-foreground/90">
                            {used.some((u) => u.nodeType) && (
                                <span className="flex shrink-0 items-center gap-1">
                                    {used.flatMap((u) => (u.nodeType ? [<NodeMark key={u.nodeType} type={u.nodeType} size="xs" />] : []))}
                                </span>
                            )}
                            <span className="min-w-0">{usesLine(used)}</span>
                        </dd>
                    </dl>
                ) : (
                    <Status state="working">Reading what it does</Status>
                )}
            </InlineCard>
        </div>
    );
}

// ── An account to connect ────────────────────────────────────────────────────

/** A link to connect an account the agent made, connected right here over the link's own request (as its page
 *  would): the owner is in the chat, so nothing is sent to them, and the agent is woken once it's connected. An app's
 *  link is a row on the turn's one connect card; an AI company's key with no plan to offer has a card of its own. */
export function ConnectLinkCard({ call, turn }: { call: CoordinatorToolCall; turn?: readonly CoordinatorToolCall[] }) {
    const { Asks, Account } = useSlot(CONNECT_LINK);
    if (connectAskOf(call)) return <Asks call={call} turn={turn} />;
    const link = connectLinkOf(call);
    if (!link) return null;
    return <Account type={link.credentialType} url={link.url} message={link.reason} startedAt={call.startedAt} />;
}

/** A link to connect an AI company's account for an agent's model: offered as its plan's sign-in, the plans one turn
 *  offers side by side. */
export function ModelConnectLinkCard({ call, turn }: { call: CoordinatorToolCall; turn?: readonly CoordinatorToolCall[] }) {
    const { Plans } = useSlot(CONNECT_LINK);
    return <Plans call={call} turn={turn} />;
}

// ── An app served at a domain ────────────────────────────────────────────────

/** Where the site is going: live there once its certificate is issued, a few minutes on, or, on a domain connected
 *  from elsewhere, once the DNS records its host still lacks are added (Domains shows them). */
export function DomainServedCard({ call }: { call: CoordinatorToolCall }) {
    const served = servedDomainOf(call)!;
    const { app = 'Your site', hostnames } = servedNames(served);
    const where = hostnames.join(' and ');
    if (str(served.domain, 'status') === 'pending_dns' && served.domain.noclick_dns !== true) {
        return (
            <Receipt
                tone="info"
                lead={<Globe className="h-4 w-4 shrink-0 text-foreground/60" />}
                action={
                    <button type="button" className={cn(PILL_QUIET, 'h-7')} onClick={() => standing(CHAT_PLACES).go('resources', { kind: 'domains' })}>
                        DNS records
                    </button>
                }
            >
                {app} goes live at {where} once its DNS records are added
            </Receipt>
        );
    }
    return (
        <Receipt
            tone="info"
            lead={<Globe className="h-4 w-4 shrink-0 text-foreground/60" />}
            action={
                <a href={`https://${hostnames[0]}`} target="_blank" rel="noopener noreferrer" className={cn(PILL_QUIET, 'h-7')}>
                    Open
                    <ArrowUpRight className="h-3.5 w-3.5" />
                </a>
            }
        >
            {app} goes live at {where} in a few minutes
        </Receipt>
    );
}
