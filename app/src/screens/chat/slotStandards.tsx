// What stands in the Chat page's slots (slots.ts) when no host fills them: each a whole way to do the thing over the
// platform API and NoClick's own pages, never a gap.
import { useState } from 'react';
import { ArrowUpRight, Wallet } from 'lucide-react';
import { standing } from '@/slots';
import { openTabForLater } from '@/lib/oauthPopup';
import { str, type CoordinatorToolCall } from '@/lib/toolCalls';
import { addFundsUrl, NOCLICK_SITE, workflowUrl } from '@/screens/console/lib/site';
import { AskCard, AskMark, InlineCard, LiveDot, PILL_PRIMARY, PILL_QUIET, Receipt, Row, Status } from '@/ui/chat/primitives';
import { FIELD } from '@/ui/fields';
import { CONNECTION_MARK } from '@/ui/slots';
import { cn } from '@/ui/utils';
import { connectLinkOf } from './cards/cardMatchers';
import { connectAsksOf, useCoordinatorJob, type ConnectAsk } from './cards/toolCardRegistry';
import { ConnectedSummary, type ConnectedAccount } from './cards/inline/setup';
import type { BuildQuestionProps, ChatPlaces, ConnectAccountProps, ConnectRowsProps, QuestionPickProps, QuestionStepProps } from './slots';
import { useSite } from './site';

export { emailOnNoClick, textOnNoClick } from './connect/onNoClick';

/** A build at work: a live dot. */
export function WorkingDot() {
    return <LiveDot />;
}

const external = { target: '_blank', rel: 'noopener noreferrer' } as const;

/** What a build's question asks, answered on its page on NoClick (where the builder's own form is). */
export function AnswerOnNoClick({ question }: BuildQuestionProps) {
    const title = str(question, 'title') ?? 'The builder has a question';
    const page = str(question, 'answer_url');
    return (
        <div className="mt-3" data-testid="coordinator-build-question">
            <InlineCard
                title={title}
                meta="The builder waits on your answer."
                actions={
                    page && (
                        <a href={page} {...external} className={PILL_PRIMARY}>
                            Answer on NoClick
                            <ArrowUpRight className="h-3.5 w-3.5" />
                        </a>
                    )
                }
            />
        </div>
    );
}

/** A question that fills in a workflow step: which connection it uses, each that fits a tap away (the signed-in
 *  owner's read lists them), connecting another on its page on NoClick; a secret's values, typed on that page (the
 *  owner's own link, which the signed-in owner's read names), never in the chat. */
export function StepOnNoClick({ question, onAnswer, disabled }: QuestionStepProps) {
    const choices = question.connect?.choices ?? [];
    const page = question.url ? (
        <a href={question.url} {...external} className={choices.length ? PILL_QUIET : PILL_PRIMARY}>
            {question.connect ? (choices.length ? 'Connect another' : `Connect ${question.connect.label}`) : 'Enter the values'} on NoClick
            <ArrowUpRight className="h-3.5 w-3.5" />
        </a>
    ) : null;
    if (!question.connect) return page ?? <p className="text-[13px] text-muted-foreground">NoClick sent the link to answer it.</p>;
    return (
        <div className="flex flex-wrap items-center gap-2">
            {choices.map((choice, i) => (
                <button key={choice.ref} type="button" className={i === 0 ? PILL_PRIMARY : PILL_QUIET} disabled={disabled} onClick={() => onAnswer({ connection: choice.ref })}>
                    {choice.account || choice.name}
                </button>
            ))}
            {page}
        </div>
    );
}

/** A pick from the owner's own account, given in words. */
export function PickInWords({ pick, onAnswer }: QuestionPickProps) {
    const [text, setText] = useState('');
    return (
        <form
            className="flex items-center gap-2"
            onSubmit={(e) => {
                e.preventDefault();
                if (text.trim()) onAnswer(text.trim());
            }}
        >
            <input value={text} onChange={(e) => setText(e.target.value)} placeholder={`The ${pick.field_label.toLowerCase()}`} aria-label={pick.field_label} className={cn(FIELD, 'h-9 flex-1')} />
            <button type="submit" disabled={!text.trim()} className={PILL_PRIMARY}>
                Send
            </button>
        </form>
    );
}

/** A request turned down for want of funds: added on NoClick. */
export function OutOfFundsLink() {
    const site = useSite();
    return (
        <Receipt
            tone="info"
            lead={<Wallet className="h-4 w-4 shrink-0 text-foreground/60" />}
            action={
                <a href={addFundsUrl(site)} {...external} className={cn(PILL_QUIET, 'h-7')}>
                    Add funds on NoClick
                    <ArrowUpRight className="h-3.5 w-3.5" />
                </a>
            }
        >
            The account is out of funds
        </Receipt>
    );
}

/** An account's name as a card says it: an AI company's for an `agent_…` key, else its service's. */
const accountName = (type: string) => standing(CONNECTION_MARK).aiCompany(type) ?? standing(CONNECTION_MARK).label(type);

type LinkAsk = Pick<ConnectAsk, 'credentialType' | 'url' | 'message' | 'operationId'>;

/** One account to connect, as a row: its app, what it's for, and Connect, its link's page on NoClick; connected
 *  once the operation it waits on settles, or `landed` says it is. */
function LinkRow({ ask, landed }: { ask: LinkAsk; landed?: ConnectedAccount }) {
    const { job } = useCoordinatorJob(ask.operationId);
    const { Mark } = standing(CONNECTION_MARK);
    const name = accountName(ask.credentialType);
    const done = !!landed || str(job, 'status') === 'succeeded' || str(job, 'status') === 'completed';
    return (
        <Row
            lead={
                <AskMark>
                    <Mark credentialType={ask.credentialType} size="sm" />
                </AskMark>
            }
            title={name}
            detail={done ? (landed?.account ?? 'Connected') : (ask.message ?? `Connect your ${name} account`)}
            aside={
                done ? (
                    <Status state="done">Connected</Status>
                ) : (
                    <a href={ask.url} {...external} className={PILL_PRIMARY}>
                        Connect
                        <ArrowUpRight className="h-3.5 w-3.5" />
                    </a>
                )
            }
        />
    );
}

/** A turn's asks to connect, on one card under the first that asked. */
export function ConnectAsksLinks({ call, turn }: { call: CoordinatorToolCall; turn?: readonly CoordinatorToolCall[] }) {
    const asks = connectAsksOf(turn ?? [call]);
    if (asks[0]?.id !== call.id) return null;
    return (
        <AskCard testId="coordinator-connect">
            {asks.map((ask) => (
                <LinkRow key={ask.id} ask={ask} />
            ))}
        </AskCard>
    );
}

export function ConnectAccountLink({ type, url, message, operationId }: ConnectAccountProps) {
    return (
        <AskCard testId="coordinator-connect">
            <LinkRow ask={{ credentialType: type, url, message, operationId }} />
        </AskCard>
    );
}

/** An AI company's account for an agent's model, on its link's page on NoClick (where its plan's sign-in is). */
export function ConnectPlansLinks({ call }: { call: CoordinatorToolCall }) {
    const link = connectLinkOf(call);
    if (!link) return null;
    return <ConnectAccountLink type={link.credentialType} url={link.url} message={link.reason} startedAt={call.startedAt} operationId={str(call.result, 'operation_id')} />;
}

/** The accounts an agent's message in a channel asks for, each on its link's page on NoClick; once all are in, one
 *  line saying who connected them. */
export function ConnectRowsLinks({ asks, landed }: ConnectRowsProps) {
    if (asks.every((ask) => landed[ask.id])) return <ConnectedSummary accounts={asks.map((ask) => ({ ...landed[ask.id], name: accountName(ask.credentialType) }))} />;
    return (
        <AskCard testId="coordinator-connect">
            {asks.map((ask) => (
                <LinkRow key={ask.id} ask={ask} landed={landed[ask.id]} />
            ))}
        </AskCard>
    );
}

const search = (params: Record<string, string | null>) => new URLSearchParams(Object.entries(params).filter((entry): entry is [string, string] => !!entry[1])).toString();

/** This app's Resources, and an automation's canvas on NoClick in a new tab. */
export const noclickPlaces: ChatPlaces = {
    href: (page, params) => `/${page}${search(params) ? `?${search(params)}` : ''}`,
    go: (page, params) => window.location.assign(`/${page}${search(params) ? `?${search(params)}` : ''}`),
    openWorkflow: (workflowId) => void openTabForLater({ url: workflowUrl(NOCLICK_SITE, workflowId) }),
};
