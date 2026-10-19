// "Where it goes", drillable in place: a service opens onto what inside it cost the most (its models, lines, tools,
// sites, databases, senders), each of those onto what used it (an agent, an automation's step, the chat with NoClick,
// the builder), and an automation, agent, site or person onto its services and from there onto theirs. The list
// replaces itself and a breadcrumb takes its tabs' place, so the same list grammar holds at every level and on a
// phone; one step back is the back button, a crumb or Escape. Every level narrows the days and the charges to it, and
// picking a row at the bottom narrows them to that row, as picking a day does. The drill is the page's state, so it
// rides the URL.
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { AnimatePresence, LayoutGroup, motion } from 'framer-motion';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { cn } from '~/lib/utils';
import { HUED, serviceColor, type Ink } from './charts';
import { useUsageMotion } from './motion';
import { Breakdown, Pills, SectionTitle, morphIds, rowColor, type BreakdownStyle } from './parts';
import { DIMENSION_LABEL, EARLIER, FACETS, OUTSIDE, ROOT_LABEL, breakdown, consumers, drillLabels, drillList, drillMatch, facets, itemsOpen, money, warmFacets, type Dimension, type Drill, type DrillList, type ServiceId, type UsageView } from './derive';

/** The service a drill is inside, if any: its hue carries down into its rows and the days. */
export function drillService(drill: Drill): ServiceId | null {
    return (drill.path.find((s) => s.dim === 'service')?.id as ServiceId | undefined) ?? null;
}

export function drillHue(drill: Drill, ink: Ink): string | null {
    const s = drillService(drill);
    if (!s) return null;
    return ink === 'services' ? serviceColor(HUED.includes(s) ? s : 'rest', ink) : 'var(--ink-strong)';
}

/** A level's rows: a tab's things, a service's items, or what used one item. */
function levelRows(view: UsageView, list: DrillList, within: ReturnType<typeof drillMatch>) {
    if (list.kind === 'consumer') return consumers(view, list.service, list.item, within);
    return list.kind === 'facet' ? facets(view, list.service, within) : breakdown(view, list.dim, within);
}

/** What the rows the drill can't split further say about themselves, so a missing breakdown reads as the data's. */
function gapNote(drill: Drill, rows: { id: string }[]): string | null {
    const service = drillService(drill);
    if (service === 'calls' && rows.some((r) => r.id === 'calls:earlier')) return 'Calls from before numbers were recorded on them share one row.';
    if (service === 'email' && rows.some((r) => r.id === 'updates:earlier')) return 'Agent updates from before their address was recorded share one row.';
    if (drill.path[drill.path.length - 1]?.dim === 'item' && rows.some((r) => r.id === EARLIER)) return 'Charges recorded before what used them was stamped on them share one row.';
    const thing = drill.path.find((s) => s.dim === 'automation' || s.dim === 'agent');
    if (thing?.id === OUTSIDE) return 'Your sites, the builder and the account’s own services aren’t in an automation.';
    if (thing?.id === EARLIER) return 'Charges an automation recorded before each step and run was stamped on them.';
    return null;
}

export function WhereItGoes({
    view,
    root,
    dims,
    onRoot,
    drill,
    onDrill,
    style,
    ink,
    compact,
    limit = 8,
}: {
    view: UsageView;
    root: Dimension;
    dims: Dimension[];
    onRoot: (d: Dimension) => void;
    drill: Drill;
    onDrill: (d: Drill) => void;
    style: BreakdownStyle;
    ink: Ink;
    compact?: boolean;
    limit?: number;
}) {
    // The drill's path keeps its identity until the drill changes (the page memoizes it from the URL).
    const path = drill.path;
    const list = drillList(drill, root);
    const pathKey = path.map((s) => `${s.dim}:${s.id}`).join(',');
    const rows = useMemo(() => levelRows(view, drillList({ path }, root), drillMatch(view.snap, { path, pick: null })), [view, path, root]);
    const labels = useMemo(() => drillLabels(view, { path, pick: null }), [view, path]);
    const drilled = drill.path.length > 0;
    const total = rows.reduce((a, r) => a + r.total, 0);
    const back = useRef<HTMLButtonElement>(null);
    // Going down moves focus to the way back up, so a keyboard keeps its place; a page opened on a drill leaves focus be.
    const seen = useRef(pathKey);
    useEffect(() => {
        if (seen.current === pathKey) return;
        seen.current = pathKey;
        if (drilled) back.current?.focus({ preventScroll: true });
    }, [pathKey, drilled]);
    const up = () => onDrill(drill.pick ? { ...drill, pick: null } : { path: drill.path.slice(0, -1), pick: null });
    // Escape anywhere in the section climbs one level.
    const section = useRef<HTMLElement>(null);
    const upRef = useRef(up);
    upRef.current = up;
    const climbable = drilled || !!drill.pick;
    useEffect(() => {
        const el = section.current;
        if (!el || !climbable) return;
        const onKey = (e: KeyboardEvent) => {
            if (e.key !== 'Escape') return;
            e.preventDefault();
            upRef.current();
        };
        el.addEventListener('keydown', onKey);
        return () => el.removeEventListener('keydown', onKey);
    }, [climbable]);
    const note = drilled ? gapNote(drill, rows) : null;
    const caption = list.kind === 'facet' ? `By ${FACETS[list.service].by.toLowerCase()}, with what each used` : list.kind === 'consumer' ? 'By what used it' : null;
    const m = useUsageMotion();
    const inService = list.kind !== 'dim';
    const hue = inService ? drillHue(drill, ink) : null;
    const listDim = list.kind === 'dim' ? list.dim : 'facet';
    // The bottom of a drill picks a row; anything above it opens the row as the next level.
    const picks = list.kind === 'consumer' || (list.kind === 'facet' && !itemsOpen(drill, list.service));

    // The row this level opened from, as it looked one level up: the header morphs out of it and back into it.
    const parent = useMemo(() => {
        const last = path[path.length - 1];
        if (!last) return null;
        const above = path.slice(0, -1);
        const at = drillList({ path: above }, root);
        const siblings = levelRows(view, at, drillMatch(view.snap, { path: above, pick: null }));
        const rank = Math.max(0, siblings.findIndex((r) => r.id === last.id));
        const color =
            at.kind !== 'dim' ? rowColor('facet', last.id, rank, ink, drillHue({ path: above, pick: null }, ink)) : style === 'stack' || ink === 'services' ? rowColor(at.dim, last.id, rank, ink) : 'var(--ink)';
        return { id: last.id, prefix: `d${above.length}`, color };
    }, [view, path, root, style, ink]);
    // On the way back, the row the header returns to keeps its parts while its neighbours come back around it.
    const cameFrom = useRef<{ pathKey: string; returnTo: string | null }>({ pathKey, returnTo: null });
    if (cameFrom.current.pathKey !== pathKey) {
        const before = cameFrom.current.pathKey.split(',').filter(Boolean);
        const now = pathKey.split(',').filter(Boolean);
        const shallower = now.length < before.length && now.every((s, i) => s === before[i]);
        cameFrom.current = { pathKey, returnTo: shallower ? (before[now.length]?.slice(before[now.length].indexOf(':') + 1) ?? null) : null };
    }
    const mounted = useRef(false);
    useEffect(() => {
        mounted.current = true;
    }, []);
    // The first drill shouldn't pay for reading every row: do it while the page is idle.
    useEffect(() => {
        const idle = window.requestIdleCallback ?? ((fn: () => void) => window.setTimeout(fn, 200));
        const cancel = window.cancelIdleCallback ?? window.clearTimeout;
        const id = idle(() => warmFacets(view.snap));
        return () => cancel(id);
    }, [view.snap]);
    const levelKey = drilled ? pathKey : `root:${root}`;
    // Siblings slide away up as a level opens, and come back down into place as it closes.
    const level = {
        exit: (dir: number) => ({ opacity: 0, y: m.reduced ? 0 : dir > 0 ? -8 : 6, pointerEvents: 'none' as const, transition: m.t }),
    };

    return (
        <LayoutGroup id="where-it-goes">
            <section ref={section} className="@container" aria-label="Where it goes">
                <SectionTitle aside={drilled ? <span className="tabular-nums">{money(total)} · {Math.round((total / (view.spent || 1)) * 100)}% of the period</span> : undefined}>Where it goes</SectionTitle>
                <div className="relative mb-3 min-h-8">
                    <AnimatePresence mode="popLayout" initial={false}>
                        <motion.div key={drilled ? `crumbs:${pathKey}` : 'tabs'} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0, pointerEvents: 'none' }} transition={m.t}>
                            {drilled ? (
                                <nav aria-label="Where it goes, drilled" className="flex min-w-0 items-center gap-1 text-[13px]">
                                    <button ref={back} type="button" onClick={up} aria-label="Back" title="Back (Esc)" className="-ml-1.5 inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                                        <ChevronLeft className="h-4 w-4" />
                                    </button>
                                    <ol className="flex min-w-0 flex-wrap items-center gap-x-1 gap-y-0.5">
                                        <li>
                                            <button type="button" onClick={() => onDrill({ path: [], pick: null })} className="rounded-md px-1 py-0.5 text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                                                {ROOT_LABEL[root]}
                                            </button>
                                        </li>
                                        {labels.map((label, i) => {
                                            const last = i === labels.length - 1;
                                            return (
                                                <li key={`${i}-${label}`} className="flex min-w-0 items-center gap-1">
                                                    <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground/60" />
                                                    {last ? (
                                                        <span aria-current="location" className="truncate px-1 font-medium text-foreground">
                                                            {label}
                                                        </span>
                                                    ) : (
                                                        <button type="button" onClick={() => onDrill({ path: drill.path.slice(0, i + 1), pick: null })} className="truncate rounded-md px-1 py-0.5 text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                                                            {label}
                                                        </button>
                                                    )}
                                                </li>
                                            );
                                        })}
                                    </ol>
                                </nav>
                            ) : (
                                <Pills size="sm" value={root} onChange={onRoot} options={dims.map((d) => ({ value: d, label: DIMENSION_LABEL[d] }))} />
                            )}
                        </motion.div>
                    </AnimatePresence>
                </div>
                <AnimatedHeight>
                    <AnimatePresence mode="popLayout" initial={false} custom={m.dir}>
                        <motion.div key={levelKey} custom={m.dir} variants={level} exit="exit">
                            {parent && (
                                <LevelHeader
                                    prefix={parent.prefix}
                                    id={parent.id}
                                    label={labels[labels.length - 1]}
                                    total={total}
                                    color={parent.color}
                                    parts={rows.slice(0, 5).map((r, i) => ({ key: r.id, usd: r.total, color: rowColor(listDim, r.id, i, ink, hue) }))}
                                    rest={rows.slice(5).reduce((a, r) => a + r.total, 0)}
                                />
                            )}
                            {caption && (
                                <motion.p initial={mounted.current ? { opacity: 0 } : false} animate={{ opacity: 1 }} transition={{ ...m.t, delay: m.after(0.35) }} className="mb-2 text-[12.5px] text-muted-foreground">
                                    {caption}
                                </motion.p>
                            )}
                            <Breakdown
                                rows={rows}
                                style={inService ? 'bars' : style}
                                dim={listDim}
                                ink={ink}
                                compact={compact}
                                limit={limit}
                                showCount={inService}
                                hue={hue}
                                active={picks ? drill.pick : undefined}
                                layoutPrefix={`d${path.length}`}
                                enter={mounted.current}
                                keep={cameFrom.current.returnTo}
                                noShareBar={drilled}
                                onPick={(r) => {
                                    if (r.id === '__rest__') return;
                                    if (picks) onDrill({ ...drill, pick: drill.pick === r.id ? null : r.id });
                                    else onDrill({ path: [...drill.path, { dim: list.kind === 'facet' ? 'item' : list.dim, id: r.id }], pick: null });
                                }}
                            />
                            {note && (
                                <motion.p initial={mounted.current ? { opacity: 0 } : false} animate={{ opacity: 1 }} transition={{ ...m.t, delay: m.after(0.5) }} className={cn('mt-3 text-[12.5px] text-muted-foreground')}>
                                    {note}
                                </motion.p>
                            )}
                        </motion.div>
                    </AnimatePresence>
                </AnimatedHeight>
            </section>
        </LayoutGroup>
    );
}

/** The opened row at the top of its level: its dot, name and amount moved up from the row, and its share segment
 *  widened to the whole bar, which then splits into what's inside it. */
function LevelHeader({ prefix, id, label, total, color, parts, rest }: { prefix: string; id: string; label: string; total: number; color: string; parts: { key: string; usd: number; color: string }[]; rest: number }) {
    const m = useUsageMotion();
    const ids = morphIds(prefix, id);
    const all = [...parts, { key: 'rest', usd: rest, color: 'var(--svc-rest)' }].filter((x) => x.usd > 0);
    const sum = all.reduce((a, x) => a + x.usd, 0) || 1;
    return (
        <div className="mb-4">
            <div className="flex h-10 items-center gap-3">
                <motion.span layoutId={ids.dot} layout="position" transition={m.t} className="h-2.5 w-2.5 shrink-0" style={{ background: color, borderRadius: 3 }} />
                <motion.span layoutId={ids.name} layout="position" transition={m.t} className="min-w-0 flex-1 truncate text-[13.5px] font-medium text-foreground">
                    {label}
                </motion.span>
                <motion.span layoutId={ids.amount} layout="position" transition={m.t} className="text-[13.5px] tabular-nums text-foreground">
                    {money(total)}
                </motion.span>
            </div>
            <motion.div layoutId={ids.segment} layout transition={m.t} className="relative h-3 w-full overflow-hidden" style={{ background: color, borderRadius: 4 }}>
                {/* The split: what's inside shows through once the bar has widened. */}
                <motion.div className="absolute inset-0 flex gap-[2px] bg-background" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: m.reduced ? 0.16 : 0.2, ease: 'easeOut', delay: m.after(0.55) }}>
                    {all.map((x) => (
                        <span key={x.key} className="block h-full" style={{ width: `${(x.usd / sum) * 100}%`, background: x.color, minWidth: 2 }} />
                    ))}
                </motion.div>
            </motion.div>
        </div>
    );
}

/** A box whose height follows its content's, smoothly, so what's under the list moves with it rather than jumping. */
function AnimatedHeight({ children }: { children: ReactNode }) {
    const m = useUsageMotion();
    const inner = useRef<HTMLDivElement>(null);
    const [height, setHeight] = useState<number | 'auto'>('auto');
    useLayoutEffect(() => {
        const el = inner.current;
        if (!el) return;
        const ro = new ResizeObserver(([e]) => setHeight(e.contentRect.height));
        ro.observe(el);
        return () => ro.disconnect();
    }, []);
    return (
        // The overflow keeps leaving content inside; the padding keeps rows' hover fills and focus rings out of its clip.
        <motion.div initial={false} animate={{ height }} transition={m.reduced ? { duration: 0 } : m.t} className="-mx-2.5 -my-1 overflow-hidden px-2.5 py-1">
            <div ref={inner} className="relative">
                {children}
            </div>
        </motion.div>
    );
}
