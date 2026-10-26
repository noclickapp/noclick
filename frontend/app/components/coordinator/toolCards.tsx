// Which card a coordinator tool call draws under the turn that made it. A call draws once it has answered; a call that
// was refused with a way past it (a plan, a top-up) draws that way past, and a credential call held for review
// draws the review. Calls that only look things up draw nothing: the reply says what they found. Web searches are
// the exception: the turn's pages are one Sources list above its cards.
import { Suspense, type ReactNode } from 'react';
import { ArrowUpRight, ShieldCheck } from 'lucide-react';
import { SourcesList } from '~/components/coordinator/inline/media';
import { PILL_QUIET, Receipt, Status } from '~/components/coordinator/inline/primitives';
import { obj, str, type CoordinatorToolCall } from '~/lib/coordinatorToolCalls';
import { cn } from '~/lib/utils';
import type { CoordinatorSetupRef } from '~/types/socket-events.generated';
import { useNewerCard } from './canvases';
import { MATCHED_CARDS, setupCard, type ToolCard } from './toolCardRegistry';
import { approvalOf, ConnectCard, CredentialApprovalCard, EmailAddressLine, MemoryCard, ReachLine } from './cards/AccountCards';
import { BuildCard } from './cards/BuildCard';
import { PaymentCard, PhoneNumberCard, RefusalCard, refusalLinks } from './cards/PurchaseCards';
import { AgentRequestCard, AlarmLine, RunResultCard, turnSources, VideoJobCard, WorkflowChangeLine } from './cards/WorkCards';

function PermissionsLine({ call }: { call: CoordinatorToolCall }) {
    const url = str(call.result, 'settings_url');
    if (!url) return null;
    return (
        <Receipt
            tone="info"
            lead={<ShieldCheck className="h-4 w-4 shrink-0 text-foreground/60" />}
            action={
                <a href={url} target="_blank" rel="noopener noreferrer" className={cn(PILL_QUIET, 'h-7')}>
                    Review
                    <ArrowUpRight className="h-3.5 w-3.5" />
                </a>
            }
        >
            Choose what NoClick may do with this account
        </Receipt>
    );
}

const CARDS: Record<string, ToolCard> = {
    request_build: BuildCard,
    message_agent: AgentRequestCard,
    generate_video: VideoJobCard,
    get_run: RunResultCard,
    schedule_alarm: AlarmLine,
    pause_workflow: WorkflowChangeLine,
    resume_workflow: WorkflowChangeLine,
    trash_workflow: WorkflowChangeLine,
    restore_workflow: WorkflowChangeLine,
    connect_credential: ConnectCard,
    request_credential_permissions: PermissionsLine,
    save_memory: MemoryCard,
    set_email_address: EmailAddressLine,
    message_owner: ReachLine,
    request_phone_number: PhoneNumberCard,
    purchase_link: PaymentCard,
};

function cardFor(call: CoordinatorToolCall): ReactNode {
    if (call.running || !call.result) return null;
    const links = refusalLinks(call);
    if (links.length) return <RefusalCard call={call} links={links} />;
    const approval = approvalOf(call);
    if (approval) return <CredentialApprovalCard approvalId={approval} />;
    // A search's pages join the turn's one Sources list (TurnCards), never a list of their own.
    if (call.tool === 'web_search') return null;
    const Card = CARDS[call.tool] ?? MATCHED_CARDS.find((m) => m.match(call))?.Card;
    return Card ? <Card call={call} /> : null;
}

/** The jobs a turn's calls started, for reading their progress back. */
export function jobIdsOf(calls: readonly CoordinatorToolCall[]): string[] {
    return calls.flatMap((call) => {
        const carded = !!CARDS[call.tool] || MATCHED_CARDS.some((m) => m.match(call));
        const id = call.tool === 'message_agent' ? str(obj(call.result, 'job'), 'job_id') : carded ? str(call.result, 'job_id') : undefined;
        return id ? [id] : [];
    });
}

/** The reminders a turn's calls set, for reading back whether each is still to come. */
export function alarmIdsOf(calls: readonly CoordinatorToolCall[]): string[] {
    return calls.flatMap((call) => {
        const id = call.tool === 'schedule_alarm' ? str(call.result, 'schedule_id') : undefined;
        return id ? [id] : [];
    });
}

export { registerSetupCard, registerToolCard, registerTurnWork, turnWorkDrawing, type TurnWorkDrawing } from './toolCardRegistry';

/** The card under a setup note; `id` is its place among the thread's cards, so a newer one about the same automation
 *  (set up for another client, or built again) folds it. */
export function SetupNoteCard({ id, setup }: { id: string; setup: CoordinatorSetupRef }) {
    const Card = setupCard();
    const newer = useNewerCard(id, setup.workflow_id);
    if (!Card) return null;
    return (
        <div className="mt-3" data-testid="coordinator-setup-card" data-folded={newer ? '' : undefined}>
            <Suspense fallback={<Status state="working">Loading</Status>}>
                <Card setup={setup} newer={newer} />
            </Suspense>
        </div>
    );
}

export function TurnCards({ calls, text }: { calls: readonly CoordinatorToolCall[]; text?: string }) {
    const sources = turnSources(calls, text);
    const cards = calls.flatMap((call) => {
        const card = cardFor(call);
        return card ? [<div key={call.id}>{card}</div>] : [];
    });
    if (!sources.length && !cards.length) return null;
    return (
        <div className="mt-3 flex flex-col gap-2.5" data-testid="coordinator-cards">
            {sources.length > 0 && <SourcesList sources={sources} />}
            {cards}
        </div>
    );
}
