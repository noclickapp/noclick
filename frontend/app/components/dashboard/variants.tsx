// The Bento dashboard: a grid of cards under the greeting, rendered by ONE
// config-driven component so the design axes stay explicit and combinations are
// cheap. Presets below are the curated points of view; the lab's bench can also
// flip each axis independently. Sections come from sections.tsx unchanged.
import { useEffect, type ComponentType, type CSSProperties, type ReactElement, type ReactNode } from 'react';
import { ArrowLeft } from 'lucide-react';
import { cn } from '~/lib/utils';
import { DECISION_KINDS, HAIRLINE, LAYOUT, SURFACE, SectionHeader, SoftButton, compactNumber, fmtBytes, relTime } from './primitives';
import {
    AgentsCompact,
    AttentionCompact,
    CreditsCompact,
    CredentialsCompact,
    FULL_VIEWS,
    FilesCompact,
    Greeting,
    KpiGrouped,
    KpiLedger,
    KpiRow,
    KpiStrip,
    NotificationsCompact,
    RunsCompact,
    TriggersCompact,
    UpcomingCompact,
    focusCount,
    nextUpcoming,
    todayBucket,
    useVisibleAttention,
    type KpiKey,
    type SectionProps,
} from './sections';
import { FOCUS_TITLES, type AttentionItem, type DashboardData, type FocusId } from './types';

// ---------------------------------------------------------------------------
// Axes

export interface BentoConfig {
    /** Card register: near-flat hairline outlines, or solid raised cards. */
    surface: 'hairline' | 'raised';
    /** Card header: small-caps eyebrow, or a title-case heading. */
    header: 'eyebrow' | 'title';
    /** Where the headline numbers live: the plain stat row, a hairline ledger, a one-line strip,
        four semantic groups, a row of stat cards, or folded into each card. */
    kpi: 'row' | 'ledger' | 'strip' | 'grouped' | 'cards' | 'folded';
    /** Grid hierarchy: balanced pairs, a dominant queue card, or uniform thirds. */
    layout: 'balanced' | 'hero' | 'uniform';
}

export const BENTO_AXES: { key: keyof BentoConfig; label: string; options: { value: string; label: string }[] }[] = [
    { key: 'surface', label: 'Surface', options: [{ value: 'hairline', label: 'Hairline' }, { value: 'raised', label: 'Raised' }] },
    { key: 'header', label: 'Headers', options: [{ value: 'eyebrow', label: 'Eyebrow' }, { value: 'title', label: 'Title' }] },
    {
        key: 'kpi',
        label: 'Numbers',
        options: [
            { value: 'ledger', label: 'Ledger' },
            { value: 'strip', label: 'Strip' },
            { value: 'grouped', label: 'Grouped' },
            { value: 'row', label: 'Plain' },
            { value: 'cards', label: 'Cards' },
            { value: 'folded', label: 'Folded' },
        ],
    },
    { key: 'layout', label: 'Grid', options: [{ value: 'balanced', label: 'Balanced' }, { value: 'hero', label: 'Hero' }, { value: 'uniform', label: 'Thirds' }] },
];

export interface DashboardVariantDef {
    slug: string;
    name: string;
    premise: string;
    config: BentoConfig;
}

export const DASHBOARD_VARIANTS: DashboardVariantDef[] = [
    {
        slug: 'hairline',
        name: 'Hairline',
        premise: 'Near-flat cards, eyebrow headers, numbers in a hairline ledger. The pick — try Strip and Grouped on the Numbers axis.',
        config: { surface: 'hairline', header: 'eyebrow', kpi: 'ledger', layout: 'balanced' },
    },
    {
        slug: 'raised',
        name: 'Raised',
        premise: 'Solid cards with a lit top edge, title headers, numbers as a row of small cards.',
        config: { surface: 'raised', header: 'title', kpi: 'cards', layout: 'balanced' },
    },
    {
        slug: 'hero',
        name: 'Hero queue',
        premise: 'Needs-you is a tall card spanning two rows; runs and agents stack beside it.',
        config: { surface: 'hairline', header: 'eyebrow', kpi: 'row', layout: 'hero' },
    },
    {
        slug: 'numeric',
        name: 'Numeric tiles',
        premise: 'No stat row: every card leads with its own big number, on an even grid of thirds.',
        config: { surface: 'hairline', header: 'title', kpi: 'folded', layout: 'uniform' },
    },
];

export function configMatches(a: BentoConfig, b: BentoConfig): boolean {
    return a.surface === b.surface && a.header === b.header && a.kpi === b.kpi && a.layout === b.layout;
}

// ---------------------------------------------------------------------------
// Surface

const RAISED_SHADOW = 'inset 0 1px 0 0 hsl(var(--foreground) / 0.05), 0 10px 30px -18px rgba(0, 0, 0, 0.45)';

function surfaceProps(surface: BentoConfig['surface']): { className: string; style?: CSSProperties } {
    return surface === 'raised'
        ? { className: 'rounded-xl border border-border bg-card', style: { boxShadow: RAISED_SHADOW } }
        : { className: SURFACE };
}

// ---------------------------------------------------------------------------
// Headline — the number a card leads with when KPIs are folded in.

interface Headline {
    value: string;
    sub: ReactNode;
}

function headlineFor(id: FocusId, data: DashboardData, attention: AttentionItem[]): Headline | null {
    switch (id) {
        case 'attention': {
            const decisions = attention.filter((a) => DECISION_KINDS.has(a.kind)).length;
            const fixes = attention.length - decisions;
            return {
                value: String(attention.length),
                sub: attention.length ? [decisions ? `${decisions} to decide` : null, fixes ? `${fixes} to fix` : null].filter(Boolean).join(' · ') : 'all clear',
            };
        }
        case 'runs': {
            const t = todayBucket(data);
            const total14 = data.runs.days.reduce((a, b) => a + b.ok + b.failed, 0);
            return {
                value: String(t.ok + t.failed),
                sub: (
                    <>
                        today · {t.failed ? <span className="text-red-600 dark:text-red-400">{t.failed} failed</span> : 'none failed'} · {compactNumber(total14)} in 14 days
                    </>
                ),
            };
        }
        case 'agents': {
            const busy = data.agents.running.filter((r) => r.busy).length;
            return { value: String(data.agents.running.length), sub: data.agents.running.length ? `up · ${busy} working` : 'up' };
        }
        case 'files': {
            const all = data.files.flatMap((s) => s.files);
            return { value: String(all.length), sub: `files · ${fmtBytes(all.reduce((a, f) => a + f.size, 0))} across ${data.files.length} places` };
        }
        case 'credentials': {
            const dead = data.credentials.filter((c) => c.health === 'disconnected' || c.health === 'revoked').length;
            return {
                value: String(data.credentials.length),
                sub: dead ? (
                    <>
                        connected · <span className="text-red-600 dark:text-red-400">{dead} need attention</span>
                    </>
                ) : (
                    'connected · all healthy'
                ),
            };
        }
        case 'triggers': {
            const broken = data.triggers.filter((t) => !t.armed).length;
            return {
                value: String(data.triggers.length - broken),
                sub: broken ? (
                    <>
                        armed · <span className="text-red-600 dark:text-red-400">{broken} broken</span>
                    </>
                ) : (
                    'armed'
                ),
            };
        }
        case 'upcoming': {
            const next = nextUpcoming(data);
            return next
                ? { value: relTime(next.at!, data.now), sub: `${next.agent?.label ?? next.workflow.name} · ${data.upcoming.filter((u) => u.at).length} scheduled` }
                : { value: '—', sub: 'nothing scheduled' };
        }
        case 'notifications':
            return { value: String(data.notifications.filter((n) => !n.readAt).length), sub: 'unread' };
        default:
            return null;
    }
}

function HeadlineBlock({ h }: { h: Headline }) {
    return (
        <div className="mb-3 flex items-baseline gap-2">
            <span className="text-[26px] font-semibold leading-none tracking-tight">{h.value}</span>
            <span className="text-[12px] text-foreground/65 dark:text-foreground/45">{h.sub}</span>
        </div>
    );
}

// ---------------------------------------------------------------------------
// Card + drill-down

function Card({
    id,
    title,
    count,
    onOpen,
    openLabel,
    children,
    className,
    config,
    headline,
}: {
    id: FocusId;
    title: string;
    count?: number;
    onOpen?: () => void;
    openLabel?: string;
    children: ReactNode;
    className?: string;
    config: BentoConfig;
    headline?: Headline | null;
}) {
    const surface = surfaceProps(config.surface);
    return (
        <section className={cn(surface.className, 'flex min-w-0 flex-col', LAYOUT.cardPad, className)} style={surface.style} data-card={id}>
            <SectionHeader
                as={config.header}
                title={title}
                count={headline ? undefined : count}
                onOpen={onOpen}
                openLabel={openLabel}
                className={headline ? 'mb-2' : 'mb-3'}
            />
            {headline && <HeadlineBlock h={headline} />}
            <div className="min-w-0 flex-1">{children}</div>
        </section>
    );
}

function FocusView({ data, focus, onBack, overrides }: { data: DashboardData; focus: FocusId; onBack: () => void; overrides?: FullViewOverrides }) {
    const attention = useVisibleAttention(data);
    const Full = overrides?.[focus] ?? FULL_VIEWS[focus];
    const count = focusCount(data, focus, attention);
    useEffect(() => {
        const onKey = (e: KeyboardEvent) => {
            if (e.key === 'Escape') onBack();
        };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, [onBack]);
    return (
        <div className="absolute inset-0 z-20 bg-background" data-testid="dashboard-focus">
            <div className="scrollbar-subtle h-full overflow-y-auto">
                <div className={cn('mx-auto', LAYOUT.pagePad)} style={{ maxWidth: 1180 }}>
                    {/* The drill-down is a page, not a toolbar: a findable way back,
                        then the section's name at the greeting's weight. Browser Back
                        works too — opening a drill-down pushes a history entry. */}
                    <div className="flex items-center gap-3">
                        <SoftButton onClick={onBack}>
                            <ArrowLeft className="h-3.5 w-3.5" />
                            Dashboard
                        </SoftButton>
                        <span className="text-[11.5px] text-foreground/55 dark:text-foreground/35">or press Esc</span>
                    </div>
                    <h1 className={cn('m-0 mt-4 flex items-baseline gap-2.5 text-[22px] font-semibold tracking-tight', LAYOUT.greetingGap)}>
                        {FOCUS_TITLES[focus]}
                        {count != null && <span className="text-[14px] font-normal tabular-nums text-foreground/60 dark:text-foreground/40">{count}</span>}
                    </h1>
                    <Full data={data} onFocus={(id) => (id ? undefined : onBack())} />
                </div>
            </div>
        </div>
    );
}

// ---------------------------------------------------------------------------
// The grid

/** Full views the host supplies in place of the section's own (the product
 *  mounts Settings' credentials and usage views so there is one of each). */
export type FullViewOverrides = Partial<Record<FocusId, ComponentType<SectionProps>>>;

export interface BentoDashboardProps {
    data: DashboardData;
    config: BentoConfig;
    /** The section shown full-screen, if any. */
    focus: FocusId | null;
    onFocus: (id: FocusId | null) => void;
    fullViewOverrides?: FullViewOverrides;
}

/** Column spans per layout, in a 12-column grid. `hero` makes the queue span two rows. */
export const SPANS: Record<BentoConfig['layout'], Record<FocusId, string>> = {
    balanced: {
        attention: 'col-span-12 lg:col-span-7',
        runs: 'col-span-12 lg:col-span-5',
        agents: 'col-span-12 lg:col-span-5',
        upcoming: 'col-span-12 lg:col-span-7',
        files: 'col-span-12 lg:col-span-7',
        credentials: 'col-span-12 lg:col-span-5',
        triggers: 'col-span-12 lg:col-span-4',
        credits: 'col-span-12 lg:col-span-4',
        notifications: 'col-span-12 lg:col-span-4',
    },
    hero: {
        attention: 'col-span-12 lg:col-span-8 lg:row-span-2',
        runs: 'col-span-12 lg:col-span-4',
        agents: 'col-span-12 lg:col-span-4',
        upcoming: 'col-span-12 lg:col-span-5',
        files: 'col-span-12 lg:col-span-7',
        credentials: 'col-span-12 lg:col-span-6',
        triggers: 'col-span-12 lg:col-span-6',
        credits: 'col-span-12 lg:col-span-4',
        notifications: 'col-span-12 lg:col-span-8',
    },
    uniform: {
        attention: 'col-span-12 md:col-span-6 lg:col-span-4',
        runs: 'col-span-12 md:col-span-6 lg:col-span-4',
        agents: 'col-span-12 md:col-span-6 lg:col-span-4',
        upcoming: 'col-span-12 md:col-span-6 lg:col-span-4',
        files: 'col-span-12 md:col-span-6 lg:col-span-4',
        credentials: 'col-span-12 md:col-span-6 lg:col-span-4',
        triggers: 'col-span-12 md:col-span-6 lg:col-span-4',
        credits: 'col-span-12 md:col-span-6 lg:col-span-4',
        notifications: 'col-span-12 md:col-span-6 lg:col-span-4',
    },
};

/** Card order per layout — auto-placement fills the grid in this sequence. */
export const ORDER: Record<BentoConfig['layout'], FocusId[]> = {
    balanced: ['attention', 'runs', 'agents', 'upcoming', 'files', 'credentials', 'triggers', 'credits', 'notifications'],
    hero: ['attention', 'runs', 'agents', 'upcoming', 'files', 'credentials', 'triggers', 'credits', 'notifications'],
    uniform: ['attention', 'runs', 'agents', 'upcoming', 'files', 'credentials', 'triggers', 'credits', 'notifications'],
};

export function BentoDashboard({ data, config, focus, onFocus, fullViewOverrides }: BentoDashboardProps) {
    const attention = useVisibleAttention(data);
    const folded = config.kpi === 'folded';
    const hero = config.layout === 'hero';
    const narrow = config.layout === 'uniform';
    const surface = surfaceProps(config.surface);
    // In the hero layout the queue card carries its own number, so the stat row drops it.
    const kpiItems: KpiKey[] | undefined = hero ? ['runs', 'failed', 'agents', 'next', 'credits'] : undefined;
    const go = (id: FocusId) => () => onFocus(id);
    const head = (id: FocusId) => (folded || (hero && id === 'attention') ? headlineFor(id, data, attention) : null);

    const cards: Record<FocusId, ReactNode> = {
        attention: (
            <Card key="attention" id="attention" config={config} title="Needs you" count={attention.length} onOpen={go('attention')} headline={head('attention')} className={SPANS[config.layout].attention}>
                <AttentionCompact data={data} onFocus={onFocus} limit={hero ? 7 : 4} dense={narrow} />
            </Card>
        ),
        runs: (
            <Card key="runs" id="runs" config={config} title="Runs" onOpen={go('runs')} headline={head('runs')} className={SPANS[config.layout].runs}>
                <RunsCompact data={data} onFocus={onFocus} top={3} stats={!folded} narrow={narrow || hero} />
            </Card>
        ),
        agents: (
            <Card key="agents" id="agents" config={config} title="Agents" count={data.agents.running.length} onOpen={go('agents')} headline={head('agents')} className={SPANS[config.layout].agents}>
                <AgentsCompact data={data} onFocus={onFocus} />
            </Card>
        ),
        upcoming: (
            <Card key="upcoming" id="upcoming" config={config} title="Upcoming" count={data.upcoming.filter((u) => u.at).length} onOpen={go('upcoming')} headline={head('upcoming')} className={SPANS[config.layout].upcoming}>
                <UpcomingCompact data={data} onFocus={onFocus} limit={4} />
            </Card>
        ),
        files: (
            <Card key="files" id="files" config={config} title="Files" onOpen={go('files')} openLabel="Browse" headline={head('files')} className={SPANS[config.layout].files}>
                <FilesCompact data={data} onFocus={onFocus} limit={5} footer={!folded} narrow={narrow} />
            </Card>
        ),
        credentials: (
            <Card key="credentials" id="credentials" config={config} title="Credentials" count={data.credentials.length} onOpen={go('credentials')} headline={head('credentials')} className={SPANS[config.layout].credentials}>
                <CredentialsCompact data={data} onFocus={onFocus} footer={!folded} />
            </Card>
        ),
        triggers: (
            <Card key="triggers" id="triggers" config={config} title="Triggers" onOpen={go('triggers')} headline={head('triggers')} className={SPANS[config.layout].triggers}>
                <TriggersCompact data={data} onFocus={onFocus} stats={!folded} />
            </Card>
        ),
        credits: (
            <Card key="credits" id="credits" config={config} title="Credits" onOpen={go('credits')} openLabel="Usage" className={SPANS[config.layout].credits}>
                <CreditsCompact data={data} onFocus={onFocus} />
            </Card>
        ),
        notifications: (
            <Card key="notifications" id="notifications" config={config} title="Notifications" count={data.notifications.filter((n) => !n.readAt).length} onOpen={go('notifications')} headline={head('notifications')} className={SPANS[config.layout].notifications}>
                <NotificationsCompact data={data} onFocus={onFocus} limit={3} />
            </Card>
        ),
    };

    return (
        <div className="relative h-full" data-testid="dashboard-variant-bento" data-config={`${config.surface}/${config.header}/${config.kpi}/${config.layout}`}>
            <div className="scrollbar-subtle h-full overflow-y-auto">
                <div className={cn('mx-auto', LAYOUT.pagePad)} style={{ maxWidth: LAYOUT.pageMaxWidth }}>
                    <Greeting data={data} className={config.kpi === 'strip' ? 'mb-3' : LAYOUT.greetingGap} summary={config.kpi !== 'strip'} />
                    {config.kpi === 'row' && <KpiRow data={data} onFocus={onFocus} items={kpiItems} className={cn('mb-6 border-b pb-6', HAIRLINE)} />}
                    {config.kpi === 'ledger' && <KpiLedger data={data} onFocus={onFocus} className={LAYOUT.ledgerGap} />}
                    {config.kpi === 'strip' && <KpiStrip data={data} onFocus={onFocus} className={cn('mb-6 border-b pb-5', HAIRLINE)} />}
                    {config.kpi === 'grouped' && <KpiGrouped data={data} onFocus={onFocus} className={cn('mb-6 border-b pb-6', HAIRLINE)} />}
                    {config.kpi === 'cards' && (
                        <KpiRow data={data} onFocus={onFocus} items={kpiItems} className="mb-4 gap-4" tileClassName={cn(surface.className, 'p-4')} tileStyle={surface.style} />
                    )}
                    <div className={cn('grid', LAYOUT.gridGap)} style={{ gridTemplateColumns: 'repeat(12, minmax(0, 1fr))' }}>
                        {ORDER[config.layout].map((id) => cards[id])}
                    </div>
                </div>
            </div>
            {focus && <FocusView data={data} focus={focus} onBack={() => onFocus(null)} overrides={fullViewOverrides} />}
        </div>
    );
}

export type DashboardVariantComponent = (p: BentoDashboardProps) => ReactElement;
