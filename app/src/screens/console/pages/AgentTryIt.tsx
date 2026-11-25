// Try it: real turns with an agent from the console, the SDK's own
// `agent.send()` followed to its end. The User field (never a page filter)
// says who the turn acts for and bills; a hold shows as the operation's pill
// with a link (the composer stays free meanwhile), as does where a CLI
// harness's turn is (its sandbox starting, then working), and the call just
// made sits beside it as code.
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Link } from 'react-router';
import { HAIRLINE } from '@/ui/primitives';
import { cn } from '@/ui/utils';
import { NoClickError, OperationTimeout, type Agent, type AgentReply, type JsonObject, type Operation, type OperationStep } from 'noclick';
import { TERMINAL_STATUSES } from '@/sdk/source';
import { operationStatus } from '@/screens/console/lib/status';
import { agentMessageSnippet, snippetTabs } from '@/screens/console/lib/snippets';
import { useConsole, useConsoleHref } from '@/screens/console/hooks/useConsole';
import { invalidateV1 } from '@/sdk/useV1';
import { UserField } from '../ui/UserField';
import { StatusPill } from '../ui/StatusPill';
import { Money } from '../ui/Money';
import { CodeSnippet } from '../ui/CodeSnippet';
import { ConsoleButton } from '../ui/Button';
import { modelUsageText } from '../agentParts';

export const TRY_IT_WARNING = "Messages here are real turns. They bill your Console key and the user's cap.";

interface Turn {
    text: string;
    user: string | null;
    operationId: string | null;
    status: string;
    /** Where a CLI harness's running turn is: `delivering` (its sandbox starting), then `working`. */
    step: OperationStep | null;
    reply: AgentReply | null;
    error: NoClickError | Error | null;
}

const FOLLOW_S = 5;

/** Tool names as the console writes them everywhere: `gmail.send_email`, not the wire's `gmail__send_email`. */
export function dottedTool(name: string): string {
    return name.replace('__', '.');
}

function TurnView({ turn }: { turn: Turn }) {
    const href = useConsoleHref();
    const opLink = turn.operationId && (
        <Link to={href('logs', { op: turn.operationId })} className="text-[12px] text-muted-foreground underline underline-offset-2 hover:text-foreground">
            View operation
        </Link>
    );
    const toolCalls = turn.reply?.toolCalls ?? [];
    const cost = turn.reply && typeof turn.reply.raw.cost_usd === 'number' ? turn.reply.raw.cost_usd : null;
    return (
        <li className="flex flex-col gap-2">
            <p className="m-0 self-end whitespace-pre-wrap rounded-lg bg-foreground/[0.06] px-3 py-2 text-sm text-foreground">{turn.text}</p>
            {turn.reply ? (
                <div className={cn('flex flex-col gap-2 rounded-lg border bg-card px-3 py-2.5', HAIRLINE)}>
                    <p className="m-0 whitespace-pre-wrap text-sm text-foreground">{turn.reply.text}</p>
                    {toolCalls.length > 0 && (
                        <details className="text-[12px]">
                            <summary className="cursor-pointer text-muted-foreground">
                                {toolCalls.length} tool {toolCalls.length === 1 ? 'call' : 'calls'}
                            </summary>
                            <ul className="m-0 mt-1 list-none p-0">
                                {toolCalls.map((c: JsonObject, i) => (
                                    <li key={i} className="flex items-center gap-2 py-0.5">
                                        <span className="font-mono">{dottedTool(String(c.tool))}</span>
                                        {c.source === 'harness' && <span className="text-muted-foreground">built in</span>}
                                        {c.is_error === true && <span className="text-red-600 dark:text-red-400">error</span>}
                                    </li>
                                ))}
                            </ul>
                        </details>
                    )}
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-muted-foreground">
                        {cost !== null && (
                            <span>
                                Cost <Money usd={cost} full />
                            </span>
                        )}
                        {turn.reply.modelUsage && <span className="tabular-nums">Model {modelUsageText(turn.reply.modelUsage)}</span>}
                        {opLink}
                    </div>
                </div>
            ) : turn.error ? (
                <div role="alert" className="text-[13px]">
                    <p className="m-0 text-red-600 dark:text-red-400">{turn.error.message}</p>
                    {turn.error instanceof NoClickError && turn.error.nextStep && <p className="m-0 text-muted-foreground">{turn.error.nextStep}</p>}
                    {opLink}
                </div>
            ) : (
                <div className="flex flex-wrap items-center gap-2">
                    <StatusPill look={operationStatus(turn.status, null, 'agent.message', turn.step)} />
                    {turn.step === 'delivering' && <span className="text-[12px] text-muted-foreground">Starting its sandbox, so this turn takes longer.</span>}
                    {opLink}
                </div>
            )}
        </li>
    );
}

export function AgentTryIt({ agent }: { agent: Agent }) {
    // A user's own agent always talks as that user; an account agent talks as the chosen one.
    const ownUser = agent.userId;
    const [user, setUser] = useState<string | null>(ownUser);
    const [conversation, setConversation] = useState('');
    const [text, setText] = useState('');
    const { client } = useConsole();
    const [turns, setTurns] = useState<Turn[]>([]);
    // A held turn doesn't hold the composer: its pill and link carry it.
    const sending = turns.some((t) => !t.reply && !t.error && t.status !== 'awaiting_human');
    const alive = useRef(true);
    // Set on every mount: StrictMode's dev remount would otherwise leave it false and drop every update.
    useEffect(() => {
        alive.current = true;
        return () => {
            alive.current = false;
        };
    }, []);
    const acting = ownUser ?? user;

    const update = (index: number, patch: Partial<Turn>) => {
        if (alive.current) setTurns((all) => all.map((t, i) => (i === index ? { ...t, ...patch } : t)));
    };

    // The server's long-poll answers when the turn ends or after FOLLOW_S, so a
    // turn costs at most one read per FOLLOW_S however long a hold lasts.
    const follow = async (index: number, op: Operation<AgentReply>) => {
        while (alive.current && !TERMINAL_STATUSES.has(op.status as string)) {
            try {
                await op.wait({ timeoutS: FOLLOW_S });
            } catch (err) {
                if (!(err instanceof OperationTimeout)) break; // it ended badly: the read below says how
            }
            update(index, { status: op.status as string, step: op.step });
        }
        if (!alive.current) return;
        // The finished operation, read once through the SDK for its typed reply or error.
        try {
            const reply = await op.wait();
            update(index, { status: op.status, step: null, reply });
            if (reply.conversation) setConversation(reply.conversation);
        } catch (err) {
            update(index, { status: op.status, step: null, error: err instanceof Error ? err : new Error(String(err)) });
        }
        invalidateV1('operations');
    };

    const send = async (e: FormEvent) => {
        e.preventDefault();
        const message = text.trim();
        if (!message || sending) return;
        const index = turns.length;
        setTurns((all) => [...all, { text: message, user: acting, operationId: null, status: 'queued', step: null, reply: null, error: null }]);
        setText('');
        try {
            const op = await agent.send(message, { conversation: conversation.trim() || undefined, user: acting });
            update(index, { operationId: op.id, status: op.status, step: op.step });
            await follow(index, op);
        } catch (err) {
            update(index, { status: 'failed', error: err instanceof Error ? err : new Error(String(err)) });
        }
    };

    const snippet = agentMessageSnippet({
        agentId: agent.id,
        text: text.trim() || turns[turns.length - 1]?.text || 'hi',
        user: acting,
        conversation: conversation.trim() || null,
    });

    return (
        <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,420px)]">
            <div className="flex min-w-0 flex-col gap-4">
                <p className="m-0 text-[13px] text-muted-foreground">{TRY_IT_WARNING}</p>
                <div className="grid gap-3 sm:grid-cols-2">
                    <UserField value={acting} onChange={setUser} disabled={!!ownUser} label={ownUser ? 'User (this agent’s own)' : 'User'} />
                    <label className="flex flex-col gap-1.5">
                        <span className="text-[12px] font-medium text-muted-foreground">Conversation</span>
                        <input
                            value={conversation}
                            onChange={(e) => setConversation(e.target.value)}
                            placeholder="New conversation"
                            className="h-9 rounded-md border border-input bg-background px-3 font-mono text-[12px] text-foreground outline-none placeholder:font-sans placeholder:text-[13px] placeholder:text-[hsl(var(--placeholder))] focus-visible:ring-2 focus-visible:ring-ring"
                        />
                    </label>
                </div>
                {turns.length > 0 && (
                    <ol aria-label="Turns" className="m-0 flex list-none flex-col gap-4 p-0">
                        {turns.map((t, i) => (
                            <TurnView key={i} turn={t} />
                        ))}
                    </ol>
                )}
                <form onSubmit={send} className="flex flex-col gap-2">
                    <textarea
                        value={text}
                        onChange={(e) => setText(e.target.value)}
                        onKeyDown={(e) => {
                            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) void send(e);
                        }}
                        rows={3}
                        aria-label="Message"
                        placeholder={`Message ${agent.name}`}
                        className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground outline-none placeholder:text-[hsl(var(--placeholder))] focus-visible:ring-2 focus-visible:ring-ring"
                    />
                    <div className="flex items-center justify-end gap-2">
                        <ConsoleButton type="submit" variant="primary" disabled={!text.trim() || sending}>
                            {sending ? 'Sending…' : 'Send'}
                        </ConsoleButton>
                    </div>
                </form>
            </div>
            <aside className="flex min-w-0 flex-col gap-2" aria-label="As code">
                <span className="text-[12px] font-medium text-muted-foreground">The same call from your code</span>
                <CodeSnippet tabs={snippetTabs(snippet)} />
                <span className="text-[12px] text-muted-foreground">
                    Reads <span className="font-mono">$NOCLICK_API_KEY</span>.
                </span>
            </aside>
        </div>
    );
}
