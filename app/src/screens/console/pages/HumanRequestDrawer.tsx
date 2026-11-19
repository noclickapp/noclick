// The human request drawer (`/logs?req=<request id>`), read-only: the whole
// request, who it waits on, and where it's answered. The console builds and
// watches; a person answers in the product (through the SDK) or from the link
// they were sent, never here. An approval also says what's being approved: the
// operation as the service labels it, its arguments, and for an agent's call
// its conversation and stated reason.
import { useEffect, type ReactNode } from 'react';
import { Link } from 'react-router';
import { HAIRLINE } from '@/ui/primitives';
import { cn } from '@/ui/utils';
import type { NoClick } from 'noclick';
import { humanRequestStatus } from '@/screens/console/lib/status';
import { userLabel } from '@/screens/console/lib/userFilter';
import { useConsole, useConsoleHref } from '@/screens/console/hooks/useConsole';
import { useV1 } from '@/sdk/useV1';
import { recordRecent } from '@/screens/console/hooks/useRecent';
import { answerSummary, EYEBROW, type HumanRequestAnswer, type HumanRequestKind, type HumanRequestStatus } from '@/screens/humans/HumanRequestView';
import { ANSWERED_ELSEWHERE, conversationParam } from './OperationDrawer';
import { Drawer } from '../ui/Drawer';
import { ErrorPanel } from '../ui/ErrorPanel';
import { IdChip } from '../ui/IdChip';
import { JsonView } from '../ui/JsonView';
import { StatusPill } from '../ui/StatusPill';
import { TimeCell } from '../ui/TimeCell';

/** `GET /v1/humans/requests` row (the account view). */
export interface RequestView {
    id: string;
    kind: HumanRequestKind;
    status: HumanRequestStatus;
    to: { email: string | null; phone: string | null; name: string | null };
    message: string;
    options: string[];
    details: Record<string, unknown>;
    answer: HumanRequestAnswer | null;
    answered_at: string | null;
    answered_by: 'link' | 'owner' | 'person' | 'code' | null;
    expires_at: string | null;
    delivered_via: string[];
    url: string | null;
    operation_id: string;
    user_id: string | null;
    approval: {
        id: string;
        tool: string;
        user_id: string | null;
        used_at: string | null;
        /** The operation as the service labels it ("Stripe: Create Refund"). */
        label?: string | null;
        /** For an agent's call, the agent and its conversation... */
        agent?: { id: string; name: string } | null;
        conversation?: string | null;
        /** ...and what it wrote in its turn before making the call. */
        reason?: string | null;
    } | null;
    /** `person`: someone a policy rule names approves it (the request's `to`). */
    approver: 'owner' | 'user' | 'person' | null;
    requested_by: { key_id: string; key_name: string | null } | null;
    owner_can_answer?: boolean;
    created_at: string;
}

type Scalar = string | number | boolean;
const isScalar = (v: unknown): v is Scalar => ['string', 'number', 'boolean'].includes(typeof v);

/**
 * The arguments an approval asks about. A policy approval carries them as
 * `details.Arguments`: an object, one row per argument (older approvals: its
 * JSON text, clipped at 4000 characters, so it may not parse); any other
 * request's scalar details are its arguments.
 */
export function requestArguments(view: Pick<RequestView, 'approval' | 'details'>): Record<string, unknown> {
    const shown = view.details?.Arguments;
    if (view.approval && shown && typeof shown === 'object' && !Array.isArray(shown)) return shown as Record<string, unknown>;
    if (view.approval && typeof shown === 'string') {
        try {
            const parsed: unknown = JSON.parse(shown);
            if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) return parsed as Record<string, unknown>;
        } catch {
            return { Arguments: shown };
        }
    }
    return Object.fromEntries(Object.entries(view.details ?? {}).filter(([key]) => !(view.approval && key === 'Action')));
}

/** `to: ana@acme.com · subject: Weekly summary` (scalars only, each clipped). */
export function argumentLine(args: Record<string, unknown>): string {
    return Object.entries(args)
        .filter(([, v]) => isScalar(v))
        .map(([k, v]) => `${k}: ${String(v).replace(/\s+/g, ' ').slice(0, 60)}`)
        .join(' · ');
}

/** The table's one line: an approval's tool and arguments, else the question or notice. */
export function requestSummary(view: Pick<RequestView, 'approval' | 'details' | 'message'>): { tool: string | null; text: string } {
    if (view.approval) return { tool: view.approval.tool, text: argumentLine(requestArguments(view)) };
    return { tool: null, text: view.message.split('\n')[0] };
}

/**
 * Who answers: "You", the user (by your id for them), or the address it went to.
 * A user's request reaches only the user's own contact
 * (`humans/service.resolve_recipient`), so its email or phone names the user.
 */
export function addressee(view: Pick<RequestView, 'user_id' | 'approver' | 'owner_can_answer' | 'to'>): string {
    if (view.user_id && (view.approver === 'user' || view.to.email || view.to.phone)) return view.user_id;
    if (view.owner_can_answer || view.approver === 'owner') return 'You';
    return view.to.email ?? view.to.phone ?? view.to.name ?? 'Unknown';
}

function Field({ label, children }: { label: string; children: ReactNode }) {
    return (
        <div className="flex min-h-8 items-baseline gap-3 py-1">
            <dt className="w-32 shrink-0 text-[12px] text-muted-foreground">{label}</dt>
            <dd className="m-0 min-w-0 flex-1 text-[13px]">{children}</dd>
        </div>
    );
}

function getRequest(client: NoClick, requestId: string, signal: AbortSignal): Promise<RequestView> {
    return client.request<RequestView>('GET', `/v1/humans/requests/${encodeURIComponent(requestId)}`, { user: null, signal });
}

const ANSWERED_BY: Record<string, string> = {
    link: 'through the link',
    owner: 'by you, in the console',
    person: 'through the link NoClick sent them',
    code: 'from your code',
};

export function HumanRequestDrawer({
    requestId,
    row,
    listLoading = false,
    onClose,
}: {
    requestId: string | null;
    row?: RequestView;
    /** The page's list is still loading: the row may arrive with it, so the request isn't read on its own yet. */
    listLoading?: boolean;
    onClose: () => void;
}) {
    const { client } = useConsole();
    const href = useConsoleHref();
    const fetched = useV1(requestId && !row ? `humans/request/${requestId}` : null, (signal) => getRequest(client, requestId!, signal), { enabled: !listLoading });
    const view = row ?? fetched.data;

    useEffect(() => {
        if (!view) return;
        recordRecent({ type: 'human_request', id: view.id, label: EYEBROW[view.kind], path: 'logs', params: { req: view.id } });
    }, [view?.id]); // eslint-disable-line react-hooks/exhaustive-deps

    const summary = view ? requestSummary(view) : null;
    const args = view ? requestArguments(view) : {};
    const scalarArgs = Object.entries(args).filter(([, v]) => isScalar(v));
    const waitingOn = view ? addressee(view) : '';
    const approval = view?.approval ?? null;
    const conversationHref =
        approval?.agent && approval.conversation ? href(`agents/${approval.agent.id}`, { conv: conversationParam(approval.user_id, approval.conversation) }) : null;
    return (
        <Drawer
            open={requestId !== null}
            onOpenChange={(open) => !open && onClose()}
            kind={view ? `human.${view.kind}` : 'human request'}
            title={view ? EYEBROW[view.kind] : undefined}
            id={requestId ?? undefined}
            status={view ? <StatusPill look={humanRequestStatus(view.status)} /> : undefined}
        >
            {!view && fetched.error !== undefined && <ErrorPanel error={fetched.error} onRetry={() => void fetched.refresh()} />}
            {!view && fetched.error === undefined && <div aria-busy className="h-40 animate-pulse rounded-lg bg-foreground/[0.04]" />}
            {view && (
                <div className="flex flex-col gap-5">
                    <section>
                        {approval?.label && <p className="m-0 mb-0.5 text-[13px] font-medium text-foreground">{approval.label}</p>}
                        {summary?.tool && <p className="m-0 mb-1 font-mono text-[12px] text-foreground">{summary.tool}</p>}
                        <p className="m-0 whitespace-pre-wrap text-sm leading-relaxed text-foreground">{view.message}</p>
                    </section>

                    {approval?.reason && (
                        <section>
                            <h3 className="m-0 mb-1.5 text-[14px] font-semibold tracking-[-0.01em] text-foreground">{approval.agent ? `Why ${approval.agent.name} made the call` : 'Why'}</h3>
                            <blockquote className={cn('m-0 whitespace-pre-wrap border-l-2 pl-3 text-[13px] leading-relaxed text-foreground/85', HAIRLINE)}>{approval.reason}</blockquote>
                        </section>
                    )}

                    {view.kind === 'ask' && view.options.length > 0 && (
                        <section>
                            <h3 className="m-0 mb-1.5 text-[14px] font-semibold tracking-[-0.01em] text-foreground">Options</h3>
                            <ul className="m-0 flex list-none flex-wrap gap-1.5 p-0">
                                {view.options.map((o) => (
                                    <li key={o} className="rounded-md bg-foreground/[0.05] px-2 py-0.5 text-[13px]">
                                        {o}
                                    </li>
                                ))}
                            </ul>
                        </section>
                    )}

                    {(scalarArgs.length > 0 || Object.keys(view.details ?? {}).length > 0) && (
                        <section className="flex flex-col gap-2">
                            <h3 className="m-0 text-[14px] font-semibold tracking-[-0.01em] text-foreground">{view.approval ? 'Arguments' : 'Details'}</h3>
                            {scalarArgs.length > 0 && (
                                <dl className={cn('m-0 rounded-lg border px-3 py-1', HAIRLINE)}>
                                    {scalarArgs.map(([k, v]) => (
                                        <Field key={k} label={k}>
                                            <span className="whitespace-pre-wrap break-words">{String(v)}</span>
                                        </Field>
                                    ))}
                                </dl>
                            )}
                            <JsonView value={view.details} />
                        </section>
                    )}

                    <dl className="m-0">
                        <Field label="To">{waitingOn}</Field>
                        <Field label="User">{userLabel(view.approval?.user_id ?? view.user_id)}</Field>
                        {conversationHref && (
                            <Field label="Conversation">
                                <Link to={conversationHref} className="hover:underline">
                                    <span className="font-mono text-[12px]">{approval!.conversation}</span>{' '}
                                    <span className="text-muted-foreground">with {approval!.agent!.name}</span>
                                </Link>
                            </Field>
                        )}
                        <Field label="Requested by">{view.requested_by?.key_name ?? <span className="text-muted-foreground">Unknown</span>}</Field>
                        <Field label="Asked">
                            <TimeCell value={view.created_at} tier="absolute" />
                        </Field>
                        {view.status === 'pending' && (
                            <Field label="Expires">
                                <TimeCell value={view.expires_at} />
                            </Field>
                        )}
                        {view.delivered_via.length > 0 && <Field label="Delivered by">{view.delivered_via.join(', ')}</Field>}
                        {view.answer && (
                            <Field label="Answer">
                                {answerSummary(view.answer, view.answered_by === 'owner' ? 'You' : waitingOn)}
                                {view.answered_by && <span className="text-muted-foreground"> · {ANSWERED_BY[view.answered_by]}</span>}
                            </Field>
                        )}
                        <Field label="Operation">
                            <Link to={href('logs', { op: view.operation_id })} className="inline-flex hover:underline">
                                <IdChip id={view.operation_id} />
                            </Link>
                        </Field>
                    </dl>

                    {view.kind === 'hand_off' && view.status === 'pending' && view.url && (
                        <p className={cn('m-0 border-t pt-3 text-[13px] text-muted-foreground', HAIRLINE)}>
                            {waitingOn} has the conversation and replies from{' '}
                            <a href={view.url} target="_blank" rel="noreferrer" className="text-foreground hover:underline">
                                its page
                            </a>
                            {", until it's handed back."}
                        </p>
                    )}
                    {view.kind !== 'hand_off' && view.status === 'pending' && (
                        <p className={cn('m-0 border-t pt-3 text-[13px] text-muted-foreground', HAIRLINE)}>
                            Waiting on {waitingOn === 'You' ? 'a person' : waitingOn}. {ANSWERED_ELSEWHERE}
                        </p>
                    )}
                </div>
            )}
        </Drawer>
    );
}
