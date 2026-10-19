// Settings → Usage: what the period will come to at this pace (and, where the deployment bills, the balance beside
// it), each day by service, where the money went with a drill into each service, what's coming, and every charge.
// The data is one read (hooks/useUsagePage); the drill and the picked tab ride the URL, so Back steps out of a drill.
import { useCallback, useMemo, useState, type ReactNode } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { useSearchParams } from 'react-router';
import { cn } from '~/lib/utils';
import { BUTTON_SECONDARY } from '~/components/shell/buttons';
import { SettingsHeader } from '~/components/settings/SettingsParts';
import { useUsagePage } from '~/hooks/useUsagePage';
import { usageBillingSlots } from './billing';
import { ChargesTable } from './charges';
import { ColumnsKey, DayColumns, type Ink } from './charts';
import { WhereItGoes, drillHue } from './drill';
import { UsageMotionProvider, useUsageMotion, FADE } from './motion';
import { ComingUp, Hero, SectionTitle } from './parts';
import {
    DIMENSION_LABEL,
    NO_DRILL,
    dayLabel,
    deriveView,
    dimensionsFor,
    drillFromParams,
    drillLabels,
    drillMatch,
    drillToParams,
    money,
    selectionOf,
    type Dimension,
    type Drill,
    type ServiceId,
    type ThingRow,
    type UsageView,
} from './derive';
import type { ChargesPage, ChargesSource, UsageSnapshot } from './types';

const INK: Ink = 'services';

/** The page as Settings shows it: reads its data, keeps its drill in the URL. */
export function UsagePage() {
    const { snap, firstPage, error, reload, charges } = useUsagePage();
    const [params, setParams] = useSearchParams();
    const inParam = params.get('in');
    const pickParam = params.get('pick');
    const drill = useMemo(() => drillFromParams(inParam, pickParam), [inParam, pickParam]);
    const by = params.get('by');
    const root = by && by in DIMENSION_LABEL ? (by as Dimension) : 'service';
    const go = useCallback(
        (next: Record<string, string | null>, replace = false) =>
            setParams(
                (p) => {
                    const out = new URLSearchParams(p);
                    for (const [k, v] of Object.entries(next)) {
                        if (v == null) out.delete(k);
                        else out.set(k, v);
                    }
                    return out;
                },
                { replace, preventScrollReset: true }
            ),
        [setParams]
    );
    if (!snap) {
        return (
            <PageFrame>
                <SettingsHeader title="Usage" description="What each thing cost, as it was used." />
                {error ? (
                    <div role="alert" className="py-10">
                        <p className="text-[14px] text-foreground">Usage didn’t load.</p>
                        <p className="mt-1 text-[13px] text-muted-foreground">{error}</p>
                        <button type="button" className={cn(BUTTON_SECONDARY, 'mt-4 h-8')} onClick={reload}>
                            Try again
                        </button>
                    </div>
                ) : (
                    <PageSkeleton />
                )}
            </PageFrame>
        );
    }
    return (
        <UsageDashboard
            snap={snap}
            firstPage={firstPage}
            charges={charges}
            drill={drill}
            onDrill={(d) => go(drillToParams(d))}
            root={root}
            onRoot={(d) => go({ by: d === 'service' ? null : d, in: null, pick: null }, true)}
        />
    );
}

function PageFrame({ children }: { children: ReactNode }) {
    return <div className="usage-page @container w-full">{children}</div>;
}

function PageSkeleton() {
    return (
        <div aria-label="Loading usage" className="space-y-10">
            <div className="h-14 w-56 animate-pulse rounded-lg bg-foreground/[0.06]" />
            <div className="h-[210px] w-full animate-pulse rounded-xl bg-foreground/[0.04]" />
            <div className="grid gap-10 @[720px]:grid-cols-2">
                {[0, 1].map((k) => (
                    <div key={k} className="space-y-3">
                        <div className="h-3 w-full animate-pulse rounded-full bg-foreground/[0.06]" />
                        {Array.from({ length: 5 }, (_, i) => (
                            <div key={i} className="h-4 animate-pulse rounded bg-foreground/[0.05]" style={{ width: `${90 - i * 9}%` }} />
                        ))}
                    </div>
                ))}
            </div>
        </div>
    );
}

/** The days, narrowed when the drill narrows the page: columns move their own bars, and under Reduce Motion a
 *  change crossfades instead. */
function Days({ view, selected, onSelect, emphasis, scopeRow, hue }: { view: UsageView; selected: string | null; onSelect: (k: string | null) => void; emphasis: ServiceId | null; scopeRow: ThingRow | null; hue: string | null }) {
    const m = useUsageMotion();
    const key = m.reduced ? `${emphasis ?? ''}:${scopeRow ? scopeRow.total : ''}` : 'columns';
    return (
        <div className="relative">
            <AnimatePresence initial={false} mode="popLayout">
                <motion.div key={key} initial={{ opacity: m.reduced ? 0.3 : 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={m.reduced ? FADE : m.t}>
                    <DayColumns view={view} ink={INK} projection="ghost" height={210} selected={selected} onSelect={onSelect} emphasis={emphasis} values={scopeRow?.daily} valuesColor={hue} />
                    {!scopeRow && <ColumnsKey view={view} projection="ghost" ink={emphasis ? 'mono' : INK} />}
                </motion.div>
            </AnimatePresence>
        </div>
    );
}

/** The page over a snapshot: what Settings renders once it has read, and what a fixture renders without a backend. */
export function UsageDashboard({
    snap,
    firstPage,
    charges,
    drill,
    onDrill,
    root,
    onRoot,
    reducedMotion,
}: {
    snap: UsageSnapshot;
    firstPage: ChargesPage | null;
    charges: ChargesSource;
    drill: Drill;
    onDrill: (d: Drill) => void;
    root: Dimension;
    onRoot: (d: Dimension) => void;
    /** The product follows the OS ('user'); a preview can force the fallback ('always'). */
    reducedMotion?: 'user' | 'always';
}) {
    const view = useMemo(() => deriveView(snap), [snap]);
    const dims = useMemo(() => dimensionsFor(view), [view]);
    const tab = dims.includes(root) ? root : 'service';
    const [day, setDay] = useState<string | null>(null);
    const slots = usageBillingSlots();

    // What the drill narrows the page to: inside one service alone, the days show it against the rest; anything
    // deeper (a model, an automation) draws its own days, in the service's hue when it's inside one.
    const match = useMemo(() => drillMatch(view.snap, drill), [view, drill]);
    const selection = useMemo(() => (match ? selectionOf(view, match) : null), [view, match]);
    const labels = useMemo(() => drillLabels(view, drill), [view, drill]);
    const onlyService = drill.path.length === 1 && drill.path[0].dim === 'service' && !drill.pick;
    const emphasis = onlyService ? (drill.path[0].id as ServiceId) : null;
    const narrowed = match && !onlyService ? selection : null;
    const hue = drillHue(drill, INK);
    const chargeFilter = useMemo(() => ({ day, match, label: labels.length ? labels.join(' › ') : undefined }), [day, match, labels]);

    const chargesId = 'usage-charges';
    const pickDay = (k: string | null) => {
        setDay(k);
        if (k) requestAnimationFrame(() => document.getElementById(chargesId)?.scrollIntoView({ behavior: 'smooth', block: 'start' }));
    };
    const Balance = view.billed ? slots.Balance : undefined;
    const PlanLine = view.billed ? slots.PlanLine : undefined;
    const Alert = view.billed ? slots.Alert : undefined;
    const days = view.period.days;

    return (
        <UsageMotionProvider depth={drill.path.length} reducedMotion={reducedMotion}>
            <div className="usage-page @container w-full">
                <SettingsHeader
                    title="Usage"
                    description={PlanLine ? <PlanLine view={view} /> : 'What each thing cost, as it was used.'}
                    actions={
                        <span className="text-[13px] tabular-nums text-muted-foreground">
                            {dayLabel(days[0])} – {dayLabel(days[days.length - 1])}
                        </span>
                    }
                />
                <div className="space-y-11">
                    {Alert && <Alert view={view} />}
                    <div className={cn('grid gap-x-10 gap-y-6', Balance && '@[600px]:grid-cols-[minmax(0,1fr)_minmax(250px,292px)] @[600px]:items-end')}>
                        <Hero view={view} />
                        {Balance && (
                            <div className="@[600px]:pb-0.5">
                                <Balance view={view} />
                            </div>
                        )}
                    </div>
                    <section aria-label="Each day">
                        {match && (
                            <p className="mb-3 flex flex-wrap items-baseline gap-x-2 text-[13px] text-muted-foreground">
                                <span>
                                    Showing <span className="text-foreground">{labels.join(' › ')}</span>
                                    {selection && (
                                        <>
                                            : <span className="tabular-nums text-foreground">{money(selection.total)}</span> of {money(view.spent)}
                                        </>
                                    )}
                                </span>
                                <button type="button" className="text-foreground underline-offset-4 hover:underline" onClick={() => onDrill(NO_DRILL)}>
                                    Show everything
                                </button>
                            </p>
                        )}
                        <Days view={view} selected={day} onSelect={pickDay} emphasis={emphasis} scopeRow={narrowed} hue={hue} />
                    </section>
                    <div className={cn('grid gap-x-12 gap-y-11', view.upcoming.length > 0 && '@[720px]:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]')}>
                        <WhereItGoes view={view} root={tab} dims={dims} onRoot={onRoot} drill={drill} onDrill={onDrill} style="stack" ink={INK} />
                        {view.upcoming.length > 0 && (
                            <section aria-label="Coming up">
                                <SectionTitle>Coming up</SectionTitle>
                                <ComingUp view={view} />
                            </section>
                        )}
                    </div>
                    <ChargesTable
                        id={chargesId}
                        view={view}
                        filter={chargeFilter}
                        source={charges}
                        firstPage={firstPage}
                        ink={INK}
                        onClear={(w) => (w === 'day' ? setDay(null) : onDrill(drill.pick ? { ...drill, pick: null } : NO_DRILL))}
                    />
                </div>
            </div>
        </UsageMotionProvider>
    );
}
