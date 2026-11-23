// The builder beside the canvas (the `canvas.builder` slot's standard, which NoClick's own app draws too): the
// conversation NoClick's builder agent keeps for this workflow, one thread per workflow (`Workflow.builder()`: its agent
// and conversation, read and followed live as any agent conversation is), and a box that starts a build with what the
// person writes (`Workflow.build`). What the builder asks shows as the conversation's own question cards; its edits
// reach the canvas as any other writer's do. A build the agent doesn't run (a user's key, a team's workflow another
// account pays for) is shown by its operation alone: building, its question's page, its summary.
//
// Elsewhere on the page asks for a build without the box: a `noclick:builder:submit` event (`detail.prompt`) starts
// one, as the box does, and `noclick:builder:stop` stops the build under way.
import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import { ArrowUpRight, Square, X } from 'lucide-react';
import { Agent, AnswerRequired, NoClickError, OperationTimeout, Workflow, type BuildQuestion, type NoClick, type WorkflowBuild } from 'noclick';
import type { UserEntry } from '@/lib/agentThread/thread';
import { useClient } from '@/sdk/client';
import { WorkClientContext } from '@/screens/work/client';
import { ThreadCards } from '@/screens/work/conversation/cards';
import { NoteRow, UserRow } from '@/screens/work/conversation/Rows';
import { timelineRows, useToolCalls } from '@/screens/work/conversation/Timeline';
import { useAgentThread } from '@/screens/work/hooks/useAgentThread';
import { ComposerSendButton, COMPOSER_SURFACE } from '@/ui/composer';
import { InlineCard, LiveDot, PILL_PRIMARY, Status } from '@/ui/chat/primitives';
import { TAP_AREA } from '@/ui/buttons';
import { cn } from '@/ui/utils';
import { panelMounted, takeHeld, tellWorking } from './builderRequests';
import { useSlot } from '@/slots';
import { BUILDER_ABOVE_COMPOSER, type CanvasBuilderProps } from './slots';

/** Its width on a laptop, which it tells the frame once. */
export const BUILDER_WIDTH = 400;

/** How long one wait on the build runs before it checks the panel is still on its workflow. */
const WAIT_S = 30;

/** What starts a build from elsewhere on the page (`detail.prompt`), and what stops the one under way. */
export const SUBMIT_EVENT = 'noclick:builder:submit';
export const STOP_EVENT = 'noclick:builder:stop';
/** Told on `document` as a build's question starts and stops waiting on the person. */
export const ASK_OPEN = 'noclick:builder:ask:open';
export const ASK_CLOSE = 'noclick:builder:ask:close';

/** How a build's message to the builder begins (open/agents/builder `definition.request`): its first line names the
 *  workflow, the person's words follow a blank line. */
const REQUEST_HEAD = 'Build request for workflow';

/** How a message NoClick sent the builder about a finished build reads (it went back to fix what a run would refuse,
 *  or to build what it hadn't). */
const SENT_BACK = 'NoClick sent the build back to the builder to finish it.';

/** What the person asked in a build's message to the builder; null for a message that isn't a build's (NoClick sending
 *  a finished build back to it). */
export function askedIn(text: string): string | null {
    if (!text.startsWith(REQUEST_HEAD)) return null;
    const words = text.split('\n\n').slice(1);
    // What the request adds after the person's words (ask nothing, publish once built) is NoClick's, not theirs.
    const theirs = words.filter((part) => !/^(Ask nothing in this build|Once it's built, publish)/.test(part));
    return theirs.join('\n\n').trim() || null;
}

/** The latest build asked for here, and where it stands. */
type Build =
    | { state: 'starting' }
    | { state: 'building'; build: WorkflowBuild }
    | { state: 'asking'; build: WorkflowBuild; question: BuildQuestion }
    | { state: 'done'; summary: string | null; built: boolean | null }
    | { state: 'failed'; error: string };

/** What a refusal or failure says, with the API's next step where it gave one. */
function said(error: unknown): string {
    if (error instanceof NoClickError) return error.nextStep ? `${error.message} ${error.nextStep}` : error.message;
    return error instanceof Error ? error.message : String(error);
}

/** Follows `build` until it settles, showing each question it asks; stops once `live()` is false. */
async function follow(build: WorkflowBuild, live: () => boolean, show: (build: Build) => void): Promise<void> {
    show({ state: 'building', build });
    while (live()) {
        try {
            const result = await build.wait({ timeoutS: WAIT_S });
            if (live()) show({ state: 'done', summary: result.summary, built: result.built });
            return;
        } catch (error) {
            if (error instanceof OperationTimeout) continue;
            // Thrown once per question; waiting again waits through it for its answer.
            if (error instanceof AnswerRequired && error.question) {
                if (live()) show({ state: 'asking', build, question: error.question });
                continue;
            }
            throw error;
        }
    }
}

/** Where the workflow's builds are talked through, read once per workflow and again as a build starts. */
interface Thread {
    agent: Agent | null;
    conversation: string | null;
}

function useBuilderThread(client: NoClick, workflowId: string | null, onLiveBuild: (build: WorkflowBuild) => void) {
    const [thread, setThread] = useState<Thread | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [read, setRead] = useState(0);
    const liveBuild = useRef(onLiveBuild);
    liveBuild.current = onLiveBuild;
    useEffect(() => {
        setThread(null);
        setError(null);
        if (!workflowId) return;
        let left = false;
        Workflow.fromId(workflowId, { client })
            .builder()
            .then(
                (found) => {
                    if (left) return;
                    setThread({ agent: found.agentId ? Agent.fromId(found.agentId, { client }) : null, conversation: found.conversation });
                    if (found.build) liveBuild.current(found.build);
                },
                (e: unknown) => !left && setError(said(e))
            );
        return () => {
            left = true;
        };
    }, [client, workflowId, read]);
    /** A build just started names the agent and conversation (the account's first build makes the agent). */
    const adopt = useCallback(
        (build: WorkflowBuild) => {
            const agentId = build.agentId;
            const conversation = build.conversation;
            if (!agentId || !conversation) return;
            setThread((now) => (now?.agent?.id === agentId && now.conversation === conversation ? now : { agent: Agent.fromId(agentId, { client }), conversation }));
        },
        [client]
    );
    return { thread, error, retry: () => setRead((n) => n + 1), adopt };
}

export default function BuilderPanel({ workflowId, open, onOpenChange, phone, offsetLeft, onWidthChange }: CanvasBuilderProps) {
    const client = useClient();
    const [text, setText] = useState('');
    const [build, setBuild] = useState<Build | null>(null);
    // What was asked last, drawn as the person's message where no agent thread holds it.
    const [asked, setAsked] = useState<string | null>(null);
    // The workflow shown now, null once the panel is gone: a build is followed only while its own workflow is shown.
    const shown = useRef<string | null>(null);
    const followed = useRef<string | null>(null);

    const followBuild = useCallback((started: WorkflowBuild) => {
        const id = shown.current;
        const buildId = started.id;
        if (followed.current === buildId) return;
        followed.current = buildId;
        const live = () => shown.current === id && followed.current === buildId;
        void follow(started, live, setBuild).catch((error: unknown) => live() && setBuild({ state: 'failed', error: said(error) }));
    }, []);
    // Read once the panel is drawn or a build starts, never for a panel nobody opened.
    const active = open || phone || build !== null;
    const { thread, error: threadError, retry, adopt } = useBuilderThread(client, active ? workflowId : null, followBuild);

    useEffect(() => {
        shown.current = workflowId;
        followed.current = null;
        setBuild(null);
        setAsked(null);
        return () => void (shown.current = null);
    }, [workflowId]);
    useEffect(() => {
        if (!phone) onWidthChange?.(BUILDER_WIDTH);
    }, [phone, onWidthChange]);

    const AboveComposer = useSlot(BUILDER_ABOVE_COMPOSER);
    const working = build?.state === 'starting' || build?.state === 'building' || build?.state === 'asking';
    useEffect(() => {
        if (!workflowId || !working) return;
        tellWorking(workflowId, true);
        return () => tellWorking(workflowId, false);
    }, [workflowId, working]);
    // A build's question is answered here, so the frame opens the panel while one waits (`ASK_OPEN`).
    const asking = build?.state === 'asking';
    useEffect(() => {
        if (!asking) return;
        document.dispatchEvent(new CustomEvent(ASK_OPEN));
        return () => void document.dispatchEvent(new CustomEvent(ASK_CLOSE));
    }, [asking]);

    const start = useCallback(
        (ask: string) => {
            const id = shown.current;
            if (!id || !ask.trim() || working) return false;
            setBuild({ state: 'starting' });
            setAsked(ask.trim());
            void Workflow.fromId(id, { client })
                .build(ask.trim())
                .then(
                    (started) => {
                        if (shown.current !== id) return;
                        adopt(started);
                        followBuild(started);
                    },
                    (error: unknown) => shown.current === id && setBuild({ state: 'failed', error: said(error) })
                );
            return true;
        },
        [client, working, adopt, followBuild]
    );

    const stop = useCallback(() => {
        if (build?.state === 'building' || build?.state === 'asking') void build.build.cancel().catch((error: unknown) => setBuild({ state: 'failed', error: said(error) }));
    }, [build]);

    // A build asked for elsewhere on the page (an agent's proposed edit approved, a template's first request).
    const startRef = useRef(start);
    startRef.current = start;
    const stopRef = useRef(stop);
    stopRef.current = stop;
    const openRef = useRef(onOpenChange);
    openRef.current = onOpenChange;
    useEffect(() => {
        const submit = (event: Event) => {
            const prompt = (event as CustomEvent<{ prompt?: unknown }>).detail?.prompt;
            if (typeof prompt !== 'string') return;
            openRef.current?.(true);
            startRef.current(prompt);
        };
        const halt = () => stopRef.current();
        const unmount = panelMounted();
        for (const prompt of takeHeld()) {
            openRef.current?.(true);
            startRef.current(prompt);
        }
        document.addEventListener(SUBMIT_EVENT, submit);
        document.addEventListener(STOP_EVENT, halt);
        return () => {
            document.removeEventListener(SUBMIT_EVENT, submit);
            document.removeEventListener(STOP_EVENT, halt);
            unmount();
        };
    }, []);

    if (!phone && !open) return null;
    const ask = text.trim();
    const canSend = !!workflowId && !!ask && !working;
    const send = () => {
        if (canSend && start(ask)) setText('');
    };
    const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
        if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            send();
        }
    };

    return (
        <aside
            aria-label="Build with NoClick"
            data-testid="builder-panel"
            className={cn('flex flex-col bg-background', phone ? 'h-full min-h-0 flex-1' : 'fixed inset-y-0 z-20 border-r border-border')}
            style={phone ? undefined : { left: offsetLeft ?? 0, width: BUILDER_WIDTH }}
        >
            <header className="flex h-14 shrink-0 items-center justify-between gap-2 px-4">
                <h2 className="text-[15px] font-semibold text-foreground">Build with NoClick</h2>
                <button
                    type="button"
                    onClick={() => onOpenChange(false)}
                    aria-label="Close the builder"
                    className={cn('relative grid h-8 w-8 place-items-center rounded-full text-muted-foreground hover:bg-foreground/[0.06] hover:text-foreground', TAP_AREA)}
                >
                    <X className="h-4 w-4" />
                </button>
            </header>
            <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-2" data-testid="builder-thread">
                {!workflowId ? (
                    <p className="text-[14px] leading-relaxed text-muted-foreground">Open an automation to build it.</p>
                ) : threadError ? (
                    <p role="alert" className="text-[14px] leading-relaxed text-red-600 dark:text-red-400">
                        {threadError}{' '}
                        <button type="button" onClick={retry} className="underline">
                            Try again
                        </button>
                    </p>
                ) : (
                    <>
                        {thread?.agent && thread.conversation ? (
                            <WorkClientContext.Provider value={client}>
                                <AgentThread agent={thread.agent} conversation={thread.conversation} />
                            </WorkClientContext.Provider>
                        ) : (
                            !build && <p className="text-[14px] leading-relaxed text-muted-foreground">Say what to add or change, and NoClick’s builder makes it on this automation.</p>
                        )}
                        {asked && !thread?.agent && (
                            <div className="flex justify-end">
                                <p className="max-w-[85%] whitespace-pre-wrap rounded-2xl bg-foreground/[0.06] px-3.5 py-2 text-[14px] leading-relaxed text-foreground">{asked}</p>
                            </div>
                        )}
                        {build && <BuildState build={build} inThread={!!thread?.agent} />}
                    </>
                )}
            </div>
            <div className="shrink-0 p-3">
                {workflowId && <AboveComposer workflowId={workflowId} />}
                <div className={cn('flex items-end gap-2 rounded-[26px] p-2 pl-4', COMPOSER_SURFACE)}>
                    <textarea
                        value={text}
                        onChange={(e) => setText(e.target.value)}
                        onKeyDown={onKeyDown}
                        rows={1}
                        disabled={!workflowId}
                        placeholder={working ? 'The builder is at work…' : 'What should it do?'}
                        aria-label="What to build"
                        className="max-h-40 min-h-9 flex-1 resize-none bg-transparent py-2 text-[14px] text-foreground outline-none placeholder:text-muted-foreground"
                    />
                    {working && build?.state !== 'starting' ? (
                        <button
                            type="button"
                            onClick={stop}
                            aria-label="Stop the build"
                            className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-foreground text-background"
                        >
                            <Square className="h-3.5 w-3.5 fill-current" />
                        </button>
                    ) : (
                        <ComposerSendButton onClick={send} disabled={!canSend} />
                    )}
                </div>
            </div>
        </aside>
    );
}

/** The builder's conversation for this workflow, as every agent conversation draws (Work's rows and cards): the
 *  person's asks without the request's own lines, NoClick sending a build back as a quiet line. */
function AgentThread({ agent, conversation }: { agent: Agent; conversation: string }) {
    const state = useAgentThread(agent, conversation, { key: agent.id, label: 'builder' });
    const [mode] = useToolCalls();
    const renderUser = useCallback((entry: UserEntry): ReactNode | undefined => {
        const asked = askedIn(entry.text);
        if (asked !== null) return <UserRow entry={{ ...entry, text: asked }} mine />;
        return <NoteRow entry={{ kind: 'note', key: entry.key, text: SENT_BACK, at: entry.at, setup: null, space: null }} />;
    }, []);
    const rows = useMemo(
        () => timelineRows({ thread: state.thread, mode, mine: () => true, agentName: 'The builder', onAnswer: (r, d) => void state.answer(r, d), renderUser }),
        [state, mode, renderUser]
    );
    if (state.loadError) {
        return (
            <p role="alert" className="text-[14px] leading-relaxed text-red-600 dark:text-red-400">
                {state.loadError}
            </p>
        );
    }
    if (!state.thread.entries.length) {
        return <p className="text-[14px] leading-relaxed text-muted-foreground">Say what to add or change, and NoClick’s builder makes it on this automation.</p>;
    }
    return (
        <ThreadCards thread={state.thread} follow={state.followJobs}>
            <div data-testid="builder-transcript">{rows}</div>
        </ThreadCards>
    );
}

/** Where the latest build stands. In the agent's thread its words and questions are the thread's own, so only its
 *  starting, a failure and a question's page (a build the agent doesn't run) show here. */
function BuildState({ build, inThread }: { build: Build; inThread: boolean }) {
    if (build.state === 'starting' || (build.state === 'building' && !inThread)) {
        return (
            <Status state="working" mark={<LiveDot />}>
                Building…
            </Status>
        );
    }
    if (build.state === 'asking' && !inThread) {
        const page = build.question.answerUrl;
        return (
            <InlineCard
                title={build.question.title ?? 'The builder has a question'}
                meta="It goes on once you answer."
                actions={
                    page && (
                        <a href={page} target="_blank" rel="noopener noreferrer" className={PILL_PRIMARY}>
                            Answer on NoClick
                            <ArrowUpRight className="h-3.5 w-3.5" />
                        </a>
                    )
                }
            />
        );
    }
    if (build.state === 'failed') {
        return (
            <p role="alert" className="text-[14px] leading-relaxed text-red-600 dark:text-red-400">
                {build.error}
            </p>
        );
    }
    if (build.state === 'done' && !inThread) {
        return (
            <div className="space-y-1.5">
                <Status state={build.built === false ? 'idle' : 'done'}>{build.built === false ? 'Nothing changed' : 'Built'}</Status>
                {build.summary && <p className="whitespace-pre-wrap text-[14px] leading-relaxed text-foreground">{build.summary}</p>}
            </div>
        );
    }
    return null;
}
