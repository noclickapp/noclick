/* The rehearsal screen as a mountable component: the design route wraps it with
   bench chrome (view/style/speed switchers) and server-serialized icons, while
   the agent interface mounts it inline in place of the chat with client-side
   icon nodes. One implementation, two hosts — extracted so "open the testing
   mode" means swapping a component, not leaving the page. */

import { useEffect, useMemo, useState, type JSX } from 'react';
import { ArrowLeft, ChevronDown, FlaskConical, MessageCircle, Pencil, Plus, Trash2, X, Zap } from 'lucide-react';
import { cn } from '~/lib/utils';
import { TRIGGERS, composeScenario, type MockRun } from './fixture';
import type { LeadPatch } from './native';
import {
    VariantConversation,
    VariantStack,
    VariantStage,
    VariantTimeline,
    type Mark,
    type TraceStyle,
    type VariantProps,
} from './variants';
import { ShareRunButton } from './ShareRunButton';
import { useReplay, type ReplaySpeed } from './useReplay';
import { useLiveRun } from './useLiveRun';
import { useLiveScenarios } from './useLiveScenarios';
import { ThinkingOrb } from '~/components/shared/ThinkingOrb';
import type { TestRunRequest } from './testRunHandoff';
import { useRehearsalAuthoring, withAuthoredRuns } from './useRehearsalAuthoring';
import { useValtioState } from '~/hooks/useValtioState';
import {
    ReadinessCard,
    useWorkflowReadiness,
} from '~/components/workflow/setup/readiness';

const VIEWS: {
    slug: string;
    name: string;
    premise: string;
    Component: (p: VariantProps) => JSX.Element;
}[] = [
    {
        slug: 'stack',
        name: 'Stacked',
        premise: 'Three labelled cards in reading order. Calm and explicit.',
        Component: VariantStack,
    },
    {
        slug: 'conversation',
        name: 'Conversation',
        premise: 'The run as a thread: trigger in, quiet work, reply out.',
        Component: VariantConversation,
    },
    {
        slug: 'stage',
        name: 'Stage',
        premise: 'Cause → machine → effect, side by side.',
        Component: VariantStage,
    },
    {
        slug: 'timeline',
        name: 'Timeline',
        premise: 'One stamped rail. Reads as a flight record.',
        Component: VariantTimeline,
    },
];

export function RehearsalScreen({
    icons,
    bench = false,
    onClose,
    live,
    className,
}: {
    /** Marks keyed by provider slug (the backend's tool-name prefix) plus
        'agent'. The workspace host passes the whole node registry; the bench
        passes the handful its fixtures use. */
    icons: Record<string, Mark>;
    /** Design-bench chrome: the view / row-style / speed switchers. The
        product mount hides them — the composition is decided. */
    bench?: boolean;
    /** Present when mounted inline (the agent interface): renders the back
        affordance and marks this as a mode to leave, not a page. */
    onClose?: () => void;
    /** Run the REAL rehearsal for this workflow instead of replaying the
        fixture: the actual agent, tool calls answered by the fabricated
        world. The staged card shows the scenario the backend stages. */
    live?: { workflowId: string };
    className?: string;
}) {
    // Conversation + cards + header outcome is the chosen composition — what
    // the Test button lands on. The bench can still flip through the rest.
    const [view, setView] = useState('conversation');
    // Fixture data exists ONLY behind the bench flag. The product mount
    // derives everything from the workflow — and if it is ever mounted without
    // a workflow, it shows the honest empty state, never the fixture: a staged
    // Gmail lead on a workflow with no Gmail trigger is a lying screen.
    const isLive = !bench;
    const staged = useLiveScenarios(isLive ? (live?.workflowId ?? null) : null);
    const baseTriggers = bench ? TRIGGERS : staged.triggers;
    // Selection lives in the session store, scoped per workflow: switching
    // workspace tabs unmounts this screen, and coming back must land on the
    // same staged situation — with its run result, held in useLiveRun's own
    // store — not a reset one.
    const stateScope = live?.workflowId ?? 'bench';
    // Builder-authored test runs, display names and staged-message edits are
    // CONTENT, not UI state — they persist with the WORKFLOW
    // (settings.rehearsal_authoring, server-backed, rides forks: a template
    // ships its test suite). Names apply to authored situations too (renaming
    // "Qualified lead" is fine — the registry key underneath never changes).
    const authoring = useRehearsalAuthoring(stateScope);
    const {
        loaded: authoringLoaded,
        runs: customRuns,
        names: runNames,
        edits,
        setRuns: setCustomRuns,
        setNames: setRunNames,
        setEdits,
        hidden,
        setHidden,
    } = authoring;
    const availableTriggers = useMemo(
        () => withAuthoredRuns(baseTriggers, customRuns, runNames, hidden),
        [baseTriggers, customRuns, runNames, hidden]
    );
    const [triggerSlug, setTriggerSlug] = useValtioState<string>(
        'rehearsalScreen',
        `trigger-${stateScope}`,
        TRIGGERS[0].slug
    );
    const [mockSlug, setMockSlug] = useValtioState<string>(
        'rehearsalScreen',
        `mock-${stateScope}`,
        TRIGGERS[0].mocks[0].slug
    );
    // The live list arrives async: adopt its first entry once, and heal a
    // selection that no longer exists after a graph edit.
    useEffect(() => {
        if (!availableTriggers.length) return;
        const t = availableTriggers.find((x) => x.slug === triggerSlug);
        if (!t) {
            setTriggerSlug(availableTriggers[0].slug);
            setMockSlug(availableTriggers[0].mocks[0]?.slug ?? '');
        } else if (!t.mocks.some((m) => m.slug === mockSlug)) {
            setMockSlug(t.mocks[0]?.slug ?? '');
        }
    }, [availableTriggers, triggerSlug, mockSlug]);
    const [speed, setSpeed] = useState<ReplaySpeed>(1);
    // What still stands between this simulation and the real thing.
    const wiringUnmet = useWorkflowReadiness(isLive ? (live?.workflowId ?? null) : null);
    const [picking, setPicking] = useState(false);
    const [traceStyle, setTraceStyle] = useState<TraceStyle>('cards');
    const trigger =
        availableTriggers.find((t) => t.slug === triggerSlug) ?? availableTriggers[0] ?? TRIGGERS[0];
    const base = composeScenario(trigger, mockSlug);
    const [editingLead, setEditingLead] = useState(false);
    const [renamingRun, setRenamingRun] = useState(false);
    const patch = edits[base.key];
    const scenario = patch ? { ...base, lead: { ...base.lead, ...patch } } : base;
    // A custom run's content exists nowhere server-side, so the WHOLE
    // displayed lead rides as the patch — not just the overlay deltas.
    const livePatch = useMemo(() => {
        if (!scenario.custom) return patch as Record<string, string> | undefined;
        const full: Record<string, string> = {
            title: scenario.lead.title,
            body: scenario.lead.body,
        };
        if (scenario.lead.author) full.author = scenario.lead.author;
        if (scenario.lead.handle) full.handle = scenario.lead.handle;
        return full;
    }, [scenario.custom, scenario.lead, patch]);
    const replay = useReplay(scenario, speed);
    const liveRun = useLiveRun(
        live?.workflowId ?? null,
        base.backendKey ?? 'sales-inbound-lead',
        livePatch
    );
    const run = isLive ? liveRun : replay;
    // The live outcome text when nothing was composed is the agent's own
    // closing words, not the fixture's.
    const displayScenario =
        isLive && liveRun.reply
            ? { ...scenario, outcome: liveRun.reply }
            : scenario;
    const active = VIEWS.find((v) => v.slug === view) ?? VIEWS[0];

    // Builder-initiated auto-start (testRunHandoff.requestTestRun): the sticky
    // payload names a trigger/situation; selection is applied only once the
    // live list confirms it exists (unknown names fall back to the first
    // available), then the run starts exactly once. The effect re-fires as
    // the selection state settles — each pass advances one step.
    const [autoRun, setAutoRun] = useValtioState<TestRunRequest | null>(
        'rehearsalScreen',
        `autorun-${stateScope}`,
        null
    );
    useEffect(() => {
        if (!autoRun || !isLive || staged.loading) return;
        if (!availableTriggers.length || run.phase === 'running') {
            setAutoRun(null);
            return;
        }
        // A named run may still be hydrating from the server (the builder
        // authored it moments ago) — judge its existence only once the
        // authoring store has loaded.
        if (autoRun.run && !authoringLoaded) return;
        // A payload without a trigger/run keeps the last-viewed selection when
        // it still exists — a bare "Test Run" re-runs what you were looking
        // at, not whatever happens to sort first.
        const wantTrigger =
            autoRun.trigger && availableTriggers.some((t) => t.slug === autoRun.trigger)
                ? autoRun.trigger
                : availableTriggers.some((t) => t.slug === triggerSlug)
                  ? triggerSlug
                  : availableTriggers[0].slug;
        const chosen = availableTriggers.find((x) => x.slug === wantTrigger)!;
        if (autoRun.run && !chosen.mocks.some((m) => m.slug === autoRun.run)) {
            // The named run doesn't resolve. Auto-starting a DIFFERENT
            // situation instead staged the bare sample event's empty world
            // and read as a broken product (2026-08-21) — land on the screen
            // unstarted and let the user pick.
            console.warn(
                `[rehearsal] autorun run '${autoRun.run}' not found under '${wantTrigger}' — not auto-starting`
            );
            setAutoRun(null);
            return;
        }
        const wantMock =
            autoRun.run ??
            (chosen.mocks.some((m) => m.slug === mockSlug)
                ? mockSlug
                : (chosen.mocks[0]?.slug ?? ''));
        if (triggerSlug !== wantTrigger) {
            setTriggerSlug(wantTrigger);
            return;
        }
        if (mockSlug !== wantMock) {
            setMockSlug(wantMock);
            return;
        }
        if (!base.backendKey) return; // key still resolving — next pass starts
        setAutoRun(null);
        void run.start();
    }, [
        autoRun,
        isLive,
        staged.loading,
        authoringLoaded,
        availableTriggers,
        triggerSlug,
        mockSlug,
        base.backendKey,
        run,
        setAutoRun,
        setTriggerSlug,
        setMockSlug,
    ]);

    const commitRename = (value: string) => {
        const v = value.trim();
        if (v) setRunNames((n) => ({ ...n, [base.key]: v }));
        setRenamingRun(false);
    };
    const addRun = () => {
        // A new run starts from a copy of the one on screen — edits included —
        // then immediately asks for its name.
        const id = `run-${Date.now().toString(36)}`;
        setCustomRuns((c) => ({
            ...c,
            [trigger.slug]: [
                ...(c[trigger.slug] ?? []),
                { slug: id, backendKey: base.backendKey, lead: { ...scenario.lead } },
            ],
        }));
        setRunNames((n) => ({ ...n, [`${trigger.slug}:${id}`]: `${scenario.name} copy` }));
        setMockSlug(id);
        setPicking(false);
        setRenamingRun(true);
    };
    const removeRun = (slug: string) => {
        const removed = trigger.mocks.find((m) => m.slug === slug);
        const key = `${trigger.slug}:${slug}`;
        if (removed && !removed.custom) {
            // Registry situations are derived, not stored — deletion is a
            // persistent hide overlay. They're deletable DEFAULTS, not
            // fixtures (2026-08-10 request).
            setHidden((h) => (h.includes(key) ? h : [...h, key]));
        } else {
            setCustomRuns((c) => ({
                ...c,
                [trigger.slug]: (c[trigger.slug] ?? []).filter((x) => x.slug !== slug),
            }));
        }
        setEdits((e) => {
            const next = { ...e };
            delete next[key];
            return next;
        });
        setRunNames((n) => {
            const next = { ...n };
            delete next[key];
            return next;
        });
        if (mockSlug === slug) {
            setMockSlug(trigger.mocks.find((m) => m.slug !== slug)?.slug ?? '');
        }
    };

    const columnWidth = active.slug === 'stage' ? 'max-w-[1060px]' : 'max-w-[560px]';

    return (
        <div className={className}>
            {!bench && onClose && (
                <div className={cn('mx-auto mb-6 flex w-full items-center gap-3', columnWidth)}>
                    <button
                        onClick={onClose}
                        aria-label="Back to chat"
                        title="Back to chat"
                        className="-ml-2 grid h-8 w-8 shrink-0 place-items-center rounded-lg text-muted-foreground transition-colors hover:bg-foreground/[0.04] hover:text-foreground"
                    >
                        <ArrowLeft className="h-4 w-4" />
                    </button>
                    <h1 className="m-0 font-brand text-[26px] font-semibold tracking-[-0.02em]">
                        Test Run
                    </h1>
                    <button
                        onClick={onClose}
                        className="ml-auto flex shrink-0 items-center gap-1.5 rounded-lg border border-border/60 px-3 py-1.5 text-[12.5px] font-medium text-muted-foreground transition-colors hover:border-border hover:bg-foreground/[0.04] hover:text-foreground"
                    >
                        <X className="h-3.5 w-3.5" />
                        Exit Testing
                    </button>
                </div>
            )}
            {/* Honesty up front: everything below is a simulation. The per-row
                'simulated' pills survive screenshots; this line frames the
                whole screen before anyone reads a single result. */}
            {isLive && (
                <div className={cn('mx-auto mb-5 w-full', columnWidth)}>
                    <p className="m-0 flex items-start gap-2 rounded-lg border border-foreground/10 bg-foreground/[0.02] px-3 py-2 text-[12px] leading-relaxed text-foreground/50">
                        <FlaskConical className="mt-0.5 h-3.5 w-3.5 shrink-0 text-foreground/40" />
                        <span>
                            This is a simulation — your real agent runs, but every
                            tool call is answered with made-up data. Nothing touches
                            your real accounts, and nothing is actually sent.
                        </span>
                    </p>
                </div>
            )}
            {bench && (
                <div className="mx-auto mb-4 flex w-full max-w-[1060px] flex-wrap items-center gap-x-6 gap-y-3">
                    <div className="min-w-0">
                        <h1 className="m-0 text-[15px] font-semibold tracking-[-0.01em]">
                            Rehearsal views
                        </h1>
                        <p className="m-0 mt-0.5 text-[12px] text-foreground/40">
                            {active.premise}
                        </p>
                    </div>

                    {bench && (
                        <>
                            <div className="ml-auto flex items-center gap-1 rounded-lg border border-foreground/12 p-0.5">
                                {VIEWS.map((v) => (
                                    <button
                                        key={v.slug}
                                        onClick={() => setView(v.slug)}
                                        className={cn(
                                            'rounded-md px-3 py-1.5 text-[12.5px] transition-colors',
                                            view === v.slug
                                                ? 'bg-foreground/10 text-foreground'
                                                : 'text-foreground/45 hover:text-foreground/80'
                                        )}
                                    >
                                        {v.name}
                                    </button>
                                ))}
                            </div>

                            <div className="flex items-center gap-1 rounded-lg border border-foreground/12 p-0.5">
                                {(['rail', 'chips', 'console', 'cards'] as const).map((v) => (
                                    <button
                                        key={v}
                                        onClick={() => setTraceStyle(v)}
                                        className={cn(
                                            'rounded-md px-2.5 py-1.5 text-[12px] capitalize transition-colors',
                                            traceStyle === v
                                                ? 'bg-foreground/10 text-foreground'
                                                : 'text-foreground/45 hover:text-foreground/80'
                                        )}
                                    >
                                        {v}
                                    </button>
                                ))}
                            </div>

                            <div className="flex items-center gap-1 rounded-lg border border-foreground/12 p-0.5">
                                {([1, 4, 'end'] as const).map((s) => (
                                    <button
                                        key={String(s)}
                                        onClick={() => setSpeed(s)}
                                        className={cn(
                                            'rounded-md px-2.5 py-1.5 font-mono text-[11.5px] transition-colors',
                                            speed === s
                                                ? 'bg-foreground/10 text-foreground'
                                                : 'text-foreground/45 hover:text-foreground/80'
                                        )}
                                    >
                                        {s === 'end' ? 'end' : `${s}×`}
                                    </button>
                                ))}
                            </div>
                        </>
                    )}
                </div>
            )}

            {isLive && staged.loading && (
                <div className={cn('mx-auto flex w-full items-center gap-3 py-8', columnWidth)}>
                    <ThinkingOrb size={20} style={{ width: 18, height: 18 }} />
                    <span className="text-[13px] text-foreground/45">
                        Looking at your workflow…
                    </span>
                </div>
            )}

            {isLive && !staged.loading && (staged.error || !availableTriggers.length) && (
                <div className={cn('mx-auto w-full', columnWidth)}>
                    <div className="rounded-xl border border-foreground/10 bg-foreground/[0.02] px-4 py-4">
                        <p className="m-0 text-[13.5px] font-medium">Nothing to stage yet</p>
                        <p className="mb-0 mt-1 text-[12.5px] leading-relaxed text-foreground/50">
                            {staged.error ??
                                'This workflow has no trigger the test can stage. Wire any trigger into the agent and a staged event will appear here.'}
                        </p>
                    </div>
                </div>
            )}

            {(!isLive || (!staged.loading && availableTriggers.length > 0)) && (
                <>
            {/* One selector for the whole staged world. Same anchor idiom as
                the agent interface's model dropdown, and the solid amber bolt
                is the SAME mark real triggers carry on the canvas — this
                dropdown IS the trigger. */}
            <div
                className={cn(
                    'mx-auto mb-3 w-full',
                    active.slug === 'stage' ? 'max-w-[1060px]' : 'max-w-[560px]'
                )}
            >
                <div className="relative inline-flex items-center gap-0.5">
                    {renamingRun ? (
                        <span className="-ml-1 flex items-center gap-2.5 px-2.5 py-2">
                            <Zap
                                className="h-4 w-4 shrink-0 text-amber-600 dark:text-amber-400"
                                fill="currentColor"
                            />
                            <input
                                autoFocus
                                defaultValue={scenario.name}
                                onFocus={(e) => e.currentTarget.select()}
                                onKeyDown={(e) => {
                                    if (e.key === 'Enter') commitRename(e.currentTarget.value);
                                    else if (e.key === 'Escape') setRenamingRun(false);
                                }}
                                onBlur={(e) => commitRename(e.currentTarget.value)}
                                placeholder="Name this test run"
                                className="w-[220px] border-b border-foreground/25 bg-transparent pb-0.5 text-[13px] font-medium outline-none placeholder:text-foreground/30 focus:border-foreground/50"
                            />
                        </span>
                    ) : (
                        <span className="flex items-center gap-0.5">
                            {trigger.mocks.length <= 1 ? (
                                // One staged situation is a fact, not a choice.
                                <span className="-ml-1 flex items-center gap-2.5 px-2.5 py-2">
                                    <Zap
                                        className="h-4 w-4 shrink-0 text-amber-600 dark:text-amber-400"
                                        fill="currentColor"
                                    />
                                    <span className="min-w-0 truncate text-[13px] font-medium">
                                        {scenario.name}
                                    </span>
                                </span>
                            ) : (
                                <button
                                    onClick={() => setPicking((v) => !v)}
                                    className="group -ml-1 flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-left transition-colors hover:bg-foreground/[0.04]"
                                >
                                    <Zap
                                        className="h-4 w-4 shrink-0 text-amber-600 dark:text-amber-400"
                                        fill="currentColor"
                                    />
                                    <span className="min-w-0 truncate text-[13px] font-medium">
                                        {scenario.name}
                                    </span>
                                    <ChevronDown
                                        className={cn(
                                            'h-4 w-4 shrink-0 text-foreground/35 transition-colors group-hover:text-foreground/80',
                                            picking && 'rotate-180'
                                        )}
                                    />
                                </button>
                            )}
                            <button
                                onClick={() => setRenamingRun(true)}
                                title="Rename this test run"
                                aria-label="Rename this test run"
                                className="flex shrink-0 items-center rounded-md p-1.5 text-foreground/35 transition-colors hover:bg-foreground/[0.04] hover:text-foreground/80"
                            >
                                <Pencil className="h-3.5 w-3.5" />
                            </button>
                        </span>
                    )}
                    <button
                        onClick={addRun}
                        title="New test run — starts from a copy of this one"
                        className="flex shrink-0 items-center gap-1.5 rounded-md px-2 py-1.5 text-[12px] font-medium text-foreground/35 transition-colors hover:bg-foreground/[0.04] hover:text-foreground/80"
                    >
                        <Plus className="h-3.5 w-3.5" />
                        New run
                    </button>
                    {picking && !renamingRun && trigger.mocks.length > 1 && (
                        <>
                            <button
                                aria-label="Close"
                                onClick={() => setPicking(false)}
                                className="fixed inset-0 z-10 cursor-default"
                            />
                            <div className="absolute left-0 top-full z-20 mt-1.5 max-h-[300px] w-[280px] overflow-y-auto rounded-xl border border-border bg-popover/95 shadow-2xl backdrop-blur-md dark:bg-zinc-950/95">
                                {trigger.mocks.map((m) => {
                                    const sel = m.slug === mockSlug;
                                    return (
                                        <button
                                            key={m.slug}
                                            onClick={() => {
                                                setMockSlug(m.slug);
                                                setPicking(false);
                                                setRenamingRun(false);
                                            }}
                                            className={cn(
                                                'group/row flex w-full items-center gap-2.5 px-3.5 py-2 text-left transition-colors',
                                                sel
                                                    ? 'bg-foreground/[0.06]'
                                                    : 'hover:bg-foreground/[0.03]'
                                            )}
                                        >
                                            <span
                                                className={cn(
                                                    'min-w-0 flex-1 truncate text-[12.5px]',
                                                    sel
                                                        ? 'font-medium text-foreground'
                                                        : 'text-foreground/65'
                                                )}
                                            >
                                                {m.name}
                                            </span>
                                            {trigger.mocks.length > 1 && (
                                                // Any row is deletable EXCEPT the
                                                // trigger's last situation — an
                                                // empty picker would leave a
                                                // stageable trigger untestable.
                                                // span, not button: rows are buttons
                                                // and buttons cannot nest.
                                                <span
                                                    role="button"
                                                    aria-label="Delete this test run"
                                                    title="Delete this test run"
                                                    onClick={(e) => {
                                                        e.stopPropagation();
                                                        removeRun(m.slug);
                                                    }}
                                                    className="flex shrink-0 items-center rounded p-1 text-foreground/30 transition-colors hover:bg-foreground/[0.06] hover:text-foreground/80"
                                                >
                                                    <Trash2 className="h-3.5 w-3.5" />
                                                </span>
                                            )}
                                        </button>
                                    );
                                })}
                            </div>
                        </>
                    )}
                </div>
            </div>

            <active.Component
                run={run}
                scenario={displayScenario}
                icons={icons}
                editing={editingLead && run.phase !== 'running'}
                onToggleEdit={() => setEditingLead((v) => !v)}
                onPatch={(p) =>
                    setEdits((e) => ({ ...e, [base.key]: { ...e[base.key], ...p } }))
                }
                traceStyle={traceStyle}
                triggers={availableTriggers}
                onTrigger={(slug) => {
                    const t = availableTriggers.find((x) => x.slug === slug);
                    if (!t) return;
                    setTriggerSlug(slug);
                    setMockSlug(t.mocks[0].slug);
                    setRenamingRun(false);
                }}
            />

            {/* Share sits at the END of the run, under the outcome — that's
                where the eye is when it finishes, and what it shares. */}
            {isLive && live?.workflowId && run.phase === 'done' && !liveRun.error && (
                <div className={cn('mx-auto mt-4 flex w-full items-center justify-end gap-2', columnWidth)}>
                    <ShareRunButton
                        workflowId={live.workflowId}
                        scenario={displayScenario}
                        run={run}
                    />
                    {/* The natural next step after a convincing test: leave the
                        simulation and talk to the agent for real. */}
                    {onClose && (
                        <button
                            onClick={onClose}
                            className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-3.5 py-1.5 text-[12.5px] font-medium text-primary-foreground transition-opacity hover:opacity-90"
                        >
                            <MessageCircle className="h-3.5 w-3.5" />
                            Talk to your agent
                        </button>
                    )}
                </div>
            )}

            </>
            )}

            {isLive && liveRun.error && (
                <div className={cn('mx-auto mt-4 w-full', columnWidth)}>
                    <div className="rounded-xl border border-red-400/25 bg-red-400/[0.06] px-4 py-3">
                        <p className="m-0 text-[13px] font-medium">The test didn&rsquo;t finish</p>
                        {/* Shown, not swallowed: a failed test is the real bug
                            found before anything live depended on it. */}
                        <p className="mb-0 mt-1 font-mono text-[11.5px] text-red-400/80">
                            {liveRun.error}
                        </p>
                        <button
                            onClick={liveRun.start}
                            className="mt-2.5 rounded-lg border border-foreground/15 px-3 py-1.5 text-[12.5px] transition-colors hover:bg-foreground/5"
                        >
                            Try again
                        </button>
                    </div>
                </div>
            )}

            {/* What still stands between this simulation and the real thing —
                the same consequence-first cards Setup shows. Connect jumps to
                that node's credential step in the Setup tab. */}
            {isLive && wiringUnmet.length > 0 && (
                <div className={cn('mx-auto mt-8 w-full', columnWidth)}>
                    <p className="m-0 mb-2 text-[11px] font-semibold uppercase tracking-wider text-foreground/35">
                        To make this real
                    </p>
                    <ReadinessCard
                        unmet={wiringUnmet}
                        onConnect={(item) => {
                            onClose?.();
                            document.dispatchEvent(
                                new CustomEvent('noclick:open-setup-step', {
                                    detail: {
                                        workflowId: live?.workflowId,
                                        stepKey: `${item.nodeId}:credentials`,
                                    },
                                })
                            );
                        }}
                    />
                </div>
            )}
        </div>
    );
}
