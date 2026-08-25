/**
 * SetupTestRunPreview — the Setup tab's Test Run finale shows the REAL staged
 * situation, not a paragraph: the same LeadCard the Test Run screen renders
 * (native per-modality shape — chat bubble, email envelope — with the trigger
 * switcher in its header and in-place editing that persists), topped by the
 * situation picker WITHOUT run management (rename/new/remove live in the full
 * screen), and a single large Test Run button below. Selection shares the
 * Test Run screen's own valtio keys, so what you previewed here is what the
 * screen opens on.
 */

import { useEffect, useMemo, useState } from 'react';
import { ChevronDown, MessageCircle, Play, Zap } from 'lucide-react';
import { cn } from '~/lib/utils';
import { useValtioState } from '~/hooks/useValtioState';
import { composeScenario } from '~/components/design/rehearsal/fixture';
import { LeadCard } from '~/components/design/rehearsal/variants';
import { useLiveScenarios } from '~/components/design/rehearsal/useLiveScenarios';
import {
    useRehearsalAuthoring,
    withAuthoredRuns,
} from '~/components/design/rehearsal/useRehearsalAuthoring';
import { useRehearsalIcons } from '~/components/design/rehearsal/useRehearsalIcons';
import type { ReplayState } from '~/components/design/rehearsal/useReplay';

// LeadCard wants a run only to disable editing mid-run and to render its own
// button (which we turn off) — the preview is always idle.
const IDLE_RUN: ReplayState = {
    phase: 'idle',
    t: 0,
    rows: [],
    artifacts: null,
    failed: false,
    start: () => {},
    replay: () => {},
};

export function SetupTestRunPreview({
    workflowId,
    onRun,
    onSkip,
}: {
    workflowId: string;
    /** Navigate to the interface and start THIS situation (bare = whatever
        the Test Run screen would pick — used when nothing is stageable). */
    onRun: (sel?: { trigger: string; run: string }) => void;
    /** Leave setup for the agent interface WITHOUT running a test. */
    onSkip?: () => void;
}) {
    const staged = useLiveScenarios(workflowId);
    const authoring = useRehearsalAuthoring(workflowId);
    const availableTriggers = useMemo(
        () => withAuthoredRuns(staged.triggers, authoring.runs, authoring.names, authoring.hidden),
        [staged.triggers, authoring.runs, authoring.names, authoring.hidden]
    );
    const icons = useRehearsalIcons();

    // The Test Run screen's own selection keys — previewing here IS selecting
    // there. Same healing rule: adopt the first entry, repair stale slugs.
    const [triggerSlug, setTriggerSlug] = useValtioState<string>(
        'rehearsalScreen',
        `trigger-${workflowId}`,
        ''
    );
    const [mockSlug, setMockSlug] = useValtioState<string>(
        'rehearsalScreen',
        `mock-${workflowId}`,
        ''
    );
    useEffect(() => {
        if (!availableTriggers.length) return;
        const t = availableTriggers.find((x) => x.slug === triggerSlug);
        if (!t) {
            setTriggerSlug(availableTriggers[0].slug);
            setMockSlug(availableTriggers[0].mocks[0]?.slug ?? '');
        } else if (!t.mocks.some((m) => m.slug === mockSlug)) {
            setMockSlug(t.mocks[0]?.slug ?? '');
        }
    }, [availableTriggers, triggerSlug, mockSlug, setTriggerSlug, setMockSlug]);

    const [pickingRun, setPickingRun] = useState(false);
    const [editing, setEditing] = useState(false);

    const trigger =
        availableTriggers.find((t) => t.slug === triggerSlug) ?? availableTriggers[0];
    if (staged.loading) return null;
    if (!trigger) {
        // Nothing stageable: an agent with no trigger wired (the pair-page
        // wizard's cloud scaffold) has no event to rehearse — the chat IS the
        // test, so the finale hands the user straight to it instead of an
        // empty Test Run screen.
        if (onSkip) {
            return (
                <button
                    onClick={onSkip}
                    className="inline-flex items-center gap-2 rounded-lg bg-primary px-5 py-2.5 text-[14px] font-medium text-primary-foreground transition-opacity hover:opacity-90"
                >
                    <MessageCircle className="h-3.5 w-3.5" />
                    Talk to your agent
                </button>
            );
        }
        return (
            <button
                onClick={() => onRun()}
                className="inline-flex items-center gap-2 rounded-lg bg-primary px-5 py-2.5 text-[14px] font-medium text-primary-foreground transition-opacity hover:opacity-90"
            >
                <Play className="h-3.5 w-3.5" />
                Test Run
            </button>
        );
    }

    const base = composeScenario(trigger, mockSlug);
    const patch = authoring.edits[base.key];
    const scenario = patch ? { ...base, lead: { ...base.lead, ...patch } } : base;

    return (
        <div>
            {/* Situation row: pick which staged run to preview. Management
                (rename / new / remove) belongs to the full Test Run screen. */}
            <div className="relative mb-3 flex items-center gap-2">
                <button
                    onClick={() => setPickingRun((v) => !v)}
                    aria-expanded={pickingRun}
                    className="flex items-center gap-2 rounded-lg px-1.5 py-1 text-left transition-colors hover:bg-foreground/[0.04]"
                >
                    <Zap className="h-4 w-4 shrink-0 fill-amber-400 text-amber-400" />
                    <span className="text-[15px] font-semibold">{scenario.name}</span>
                    <ChevronDown
                        className={cn(
                            'h-3.5 w-3.5 text-foreground/40 transition-transform',
                            pickingRun && 'rotate-180'
                        )}
                    />
                </button>
                {pickingRun && (
                    <div className="absolute left-0 top-full z-20 mt-1 min-w-[220px] rounded-xl border border-foreground/[0.12] bg-popover p-1 shadow-xl">
                        {trigger.mocks.map((m) => (
                            <button
                                key={m.slug}
                                onClick={() => {
                                    setMockSlug(m.slug);
                                    setPickingRun(false);
                                    setEditing(false);
                                }}
                                className={cn(
                                    'flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-[13px] transition-colors hover:bg-foreground/[0.05]',
                                    m.slug === mockSlug
                                        ? 'text-foreground'
                                        : 'text-foreground/60'
                                )}
                            >
                                {m.name}
                            </button>
                        ))}
                    </div>
                )}
            </div>

            <LeadCard
                scenario={scenario}
                icons={icons}
                run={IDLE_RUN}
                triggers={availableTriggers}
                onTrigger={(slug) => {
                    const t = availableTriggers.find((x) => x.slug === slug);
                    if (!t) return;
                    setTriggerSlug(slug);
                    setMockSlug(t.mocks[0]?.slug ?? '');
                    setEditing(false);
                }}
                editing={editing}
                onToggleEdit={() => setEditing((v) => !v)}
                onPatch={(p) =>
                    authoring.setEdits((e) => ({
                        ...e,
                        [base.key]: { ...e[base.key], ...p },
                    }))
                }
                runButton={false}
            />

            <div className="mt-5 flex items-center justify-end gap-2">
                {onSkip && (
                    <button
                        onClick={onSkip}
                        className="inline-flex items-center rounded-lg border border-foreground/15 px-4 py-2.5 text-[14px] font-medium text-foreground/70 transition-colors hover:bg-foreground/5 hover:text-foreground"
                    >
                        Skip test run
                    </button>
                )}
                <button
                    onClick={() => onRun({ trigger: trigger.slug, run: base.slug })}
                    className="inline-flex items-center gap-2 rounded-lg bg-primary px-5 py-2.5 text-[14px] font-medium text-primary-foreground transition-opacity hover:opacity-90"
                >
                    <Play className="h-3.5 w-3.5" />
                    Test Run
                </button>
            </div>
        </div>
    );
}
