// The builder beside the canvas where no host has its own (the `canvas.builder` slot's standard, loaded with the first
// one drawn): say what to add or change, and NoClick's builder makes it on the workflow (`Workflow.build` on the
// platform API), a question it asks answered on its page on NoClick, and what it did in its own words. The canvas sees
// what it saves as it sees any other change to the workflow.
import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { ArrowUpRight, X } from 'lucide-react';
import { AnswerRequired, NoClickError, OperationTimeout, Workflow, type BuildQuestion, type WorkflowBuild } from 'noclick';
import { useClient } from '@/sdk/client';
import { ComposerSendButton, COMPOSER_SURFACE } from '@/ui/composer';
import { InlineCard, LiveDot, PILL_PRIMARY, Status } from '@/ui/chat/primitives';
import { TAP_AREA } from '@/ui/buttons';
import { cn } from '@/ui/utils';
import type { CanvasBuilderProps } from './slots';

/** Its width on a laptop, which it tells the frame once. */
export const BUILDER_WIDTH = 400;

/** How long one wait on the build runs before it checks the panel is still open, so a closed one stops following. */
const WAIT_S = 30;

/** The latest build asked for here, and where it stands. */
type Build =
    | { state: 'building'; ask: string }
    | { state: 'asking'; ask: string; question: BuildQuestion }
    | { state: 'done'; ask: string; summary: string | null; built: boolean | null }
    | { state: 'failed'; ask: string; error: string };

/** What a refusal or failure says, with the API's next step where it gave one. */
function said(error: unknown): string {
    if (error instanceof NoClickError) return error.nextStep ? `${error.message} ${error.nextStep}` : error.message;
    return error instanceof Error ? error.message : String(error);
}

/** Follows `build` until it finishes, showing each question it asks; stops once `live()` is false. */
async function follow(build: WorkflowBuild, ask: string, live: () => boolean, show: (build: Build) => void): Promise<void> {
    while (live()) {
        try {
            const result = await build.wait({ timeoutS: WAIT_S });
            if (live()) show({ state: 'done', ask, summary: result.summary, built: result.built });
            return;
        } catch (error) {
            if (error instanceof OperationTimeout) continue;
            // Thrown once per question; waiting again waits through it for its answer.
            if (error instanceof AnswerRequired && error.question) {
                if (live()) show({ state: 'asking', ask, question: error.question });
                continue;
            }
            throw error;
        }
    }
}

export default function BuilderPanel({ workflowId, open, onOpenChange, phone, offsetLeft, onWidthChange }: CanvasBuilderProps) {
    const client = useClient();
    const [text, setText] = useState('');
    const [build, setBuild] = useState<Build | null>(null);
    // The workflow shown now, null once the panel is gone: a build is followed only while its own workflow is shown, and
    // another workflow's builder starts empty.
    const shown = useRef<string | null>(null);
    useEffect(() => {
        shown.current = workflowId;
        setBuild(null);
        return () => void (shown.current = null);
    }, [workflowId]);
    useEffect(() => {
        if (!phone) onWidthChange?.(BUILDER_WIDTH);
    }, [phone, onWidthChange]);

    if (!phone && !open) return null;
    const working = build?.state === 'building' || build?.state === 'asking';
    const ask = text.trim();
    const canSend = !!workflowId && !!ask && !working;

    const send = () => {
        if (!canSend || !workflowId) return;
        setText('');
        setBuild({ state: 'building', ask });
        const live = () => shown.current === workflowId;
        void (async () => {
            try {
                const started = await Workflow.fromId(workflowId, { client }).build(ask);
                await follow(started, ask, live, setBuild);
            } catch (error) {
                if (live()) setBuild({ state: 'failed', ask, error: said(error) });
            }
        })();
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
            <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-2">
                {!workflowId ? (
                    <p className="text-[14px] leading-relaxed text-muted-foreground">Open an automation to build it.</p>
                ) : !build ? (
                    <p className="text-[14px] leading-relaxed text-muted-foreground">Say what to add or change, and NoClick’s builder makes it on this automation.</p>
                ) : (
                    <>
                        <p className="ml-auto w-fit max-w-[85%] whitespace-pre-wrap rounded-2xl bg-secondary px-3.5 py-2 text-[14px] text-foreground dark:bg-foreground/[0.07]">{build.ask}</p>
                        <BuildState build={build} />
                    </>
                )}
            </div>
            <div className="shrink-0 p-3">
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
                    <ComposerSendButton onClick={send} disabled={!canSend} />
                </div>
            </div>
        </aside>
    );
}

/** Where the latest build stands: at work, waiting on a question, done in the builder's words, or failed. */
function BuildState({ build }: { build: Build }) {
    if (build.state === 'building') {
        return (
            <Status state="working" mark={<LiveDot />}>
                Building…
            </Status>
        );
    }
    if (build.state === 'asking') {
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
    return (
        <div className="space-y-1.5">
            <Status state={build.built === false ? 'idle' : 'done'}>{build.built === false ? 'Nothing changed' : 'Built'}</Status>
            {build.summary && <p className="whitespace-pre-wrap text-[14px] leading-relaxed text-foreground">{build.summary}</p>}
        </div>
    );
}
