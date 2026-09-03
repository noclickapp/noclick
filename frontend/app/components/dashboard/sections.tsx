// The Dashboard's sections, each in two registers: a COMPACT block for the
// overview and a FULL view for the drill-down. Variants only arrange these;
// the content and its affordances are the same in every skeleton so a design
// decision is about layout, never about what the tab can do.
import { useEffect, useMemo, useState, type CSSProperties, type ReactElement, type ReactNode, type SyntheticEvent, type ButtonHTMLAttributes } from 'react';
import {
    Archive,
    ArrowUpRight,
    Bell,
    Check,
    ChevronDown,
    ChevronUp,
    Clock,
    Settings2,
    ChevronRight,
    Code2,
    Copy,
    File,
    FileText,
    Image as ImageIcon,
    RefreshCw,
    Table2,
    Terminal,
    X,
    Trash2,
    Film,
    Music,

} from 'lucide-react';
import { cn } from '~/lib/utils';
import { IODataDisplay } from '~/components/workflow/IODataDisplay';
import { OutboundMessage, type Mark } from '~/components/design/rehearsal/native';
import { buildRunStory, deriveSends, type RunStory as Story, type StoryInput } from '~/components/design/run-results/runStory';
import { InboundCard, SentFrame, TriggerIdentity, buildStoryIcons } from '~/components/design/run-results/variants';
import type { ReplayToolCall } from '~/components/workflow/ReplayToolCallsPanel';
import { getNodeIconMeta } from '~/lib/nodeIconRegistry';
import { ApprovalField } from '~/components/dashboard/ApprovalFields';
import { isPersistedExecutionId, loadRunStory } from '~/lib/runResults';
import { workspaceFileUrl } from '~/hooks/useAgentWorkspaceFiles';
import { useValtioState } from '~/hooks/useValtioState';
import { AskAnswer } from '~/components/dashboard/AskAnswer';
import {
    ATTENTION_KIND_LABEL,
    CredentialMark,
    DECISION_KINDS,
    EmptyState,
    Eyebrow,
    LAYOUT,
    KindPill,
    LiveDot,
    MarkRow,
    Meter,
    NodeMark,
    ROW_HOVER,
    ROWS,
    RunsColumns,
    SectionHeader,
    SURFACE,
    Sparkline,
    StatTile,
    TextLink,
    Verdict,
    WorkflowLine,
    agentMarkType,
    clockLabel,
    compactNumber,
    credentialLabel,
    clickableRow,
    dateLabel,
    fmtBytes,
    fmtCredits,
    fmtDuration,
    harnessLabel,
    relTime,
    useDashboardActions,
    type VerdictStatus,
} from './primitives';
import type { ToolCallSummary,
    AgentTurn,
    AttentionItem,
    AttentionKind,
    CredentialEntry,
    DashboardData,
    FileEntry,
    FileKind,
    FileSource,
    FileSourceKind,
    FocusId,
    NotificationEntry,
    RunRow,
    RunStatus,
    TriggerEntry,
    TriggerSource,
    UpcomingKind,
    UpcomingRun,
} from './types';

export interface SectionProps {
    data: DashboardData;
    onFocus?: (id: FocusId) => void;
}

// ---------------------------------------------------------------------------
// Greeting + the one-line summary

export function greetingFor(now: string, name: string): string {
    const hour = new Date(now).getHours();
    const part = hour < 5 ? 'Still up' : hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening';
    return `${part}, ${name}.`;
}

export function useVisibleAttention(data: DashboardData): AttentionItem[] {
    const { dismissed } = useDashboardActions();
    return useMemo(() => data.attention.filter((a) => !dismissed.has(a.id)), [data.attention, dismissed]);
}

export function todayBucket(data: DashboardData) {
    return data.runs.days[data.runs.days.length - 1] ?? { date: '', ok: 0, failed: 0 };
}

/** "8 things need you · 24 runs today, 1 failed · 2 agents up". */
export function summaryLine(data: DashboardData, attention: AttentionItem[]): string[] {
    const today = todayBucket(data);
    const runsToday = today.ok + today.failed;
    const parts: string[] = [];
    if (attention.length) parts.push(`${attention.length} ${attention.length === 1 ? 'thing needs' : 'things need'} you`);
    else parts.push('Nothing needs you');
    if (runsToday) parts.push(`${runsToday} ${runsToday === 1 ? 'run' : 'runs'} today${today.failed ? `, ${today.failed} failed` : ''}`);
    else parts.push('No runs yet today');
    const up = data.agents.running.length;
    if (up) parts.push(`${up} ${up === 1 ? 'agent' : 'agents'} up`);
    return parts;
}

/** "Dhruv" from "Dhruv Yadav"; an email-shaped name keeps its local part. */
function firstName(name: string): string {
    const first = name.trim().split(/\s+/)[0] ?? '';
    return first.includes('@') ? first.split('@')[0] : first || name;
}

export function Greeting({ data, size = 'md', className, summary = true }: { data: DashboardData; size?: 'md' | 'lg'; className?: string; summary?: boolean }) {
    const attention = useVisibleAttention(data);
    const parts = summaryLine(data, attention);
    return (
        <div className={className}>
            <h1 className={cn('m-0 font-semibold tracking-tight', size === 'lg' ? 'text-[32px]' : 'text-[26px]')}>
                {greetingFor(data.now, firstName(data.workspace.userName))}
            </h1>
            {summary && <p className="m-0 mt-1.5 text-[15px] text-foreground/70 dark:text-foreground/50">{parts.join(' · ')}</p>}
        </div>
    );
}

/** The next thing that will run, by time; unscheduled entries never win. */
export function nextUpcoming(data: DashboardData): UpcomingRun | null {
    return [...data.upcoming].filter((u) => u.at).sort((a, b) => Date.parse(a.at!) - Date.parse(b.at!))[0] ?? null;
}

/** Every headline number the stat treatments draw from, computed once. */
export function useKpiFacts(data: DashboardData) {
    const attention = useVisibleAttention(data);
    return useMemo(() => {
        const today = todayBucket(data);
        const decisions = attention.filter((a) => DECISION_KINDS.has(a.kind)).length;
        const total14 = data.runs.days.reduce((a, b) => a + b.ok + b.failed, 0);
        const failed14 = data.runs.days.reduce((a, b) => a + b.failed, 0);
        return {
            attention: attention.length,
            decisions,
            fixes: attention.length - decisions,
            today: today.ok + today.failed,
            failedToday: today.failed,
            total14,
            failed14,
            rate: total14 ? Math.round(((total14 - failed14) / total14) * 100) : 100,
            trend: data.runs.days.map((b) => b.ok + b.failed),
            agentsUp: data.agents.running.length,
            busy: data.agents.running.filter((r) => r.busy).length,
            next: nextUpcoming(data),
            credits: data.credits,
        };
    }, [data, attention]);
}

// ---------------------------------------------------------------------------
// KPI row

export type KpiKey = 'attention' | 'runs' | 'failed' | 'agents' | 'next' | 'credits';

export function KpiRow({ data, onFocus, className, items, tileClassName, tileStyle }: SectionProps & { className?: string; items?: KpiKey[]; tileClassName?: string; tileStyle?: CSSProperties }) {
    const attention = useVisibleAttention(data);
    const today = todayBucket(data);
    const failed14 = data.runs.days.reduce((a, b) => a + b.failed, 0);
    const total14 = data.runs.days.reduce((a, b) => a + b.ok + b.failed, 0);
    const trend = data.runs.days.map((b) => b.ok + b.failed);
    const next = nextUpcoming(data);
    const tiles: Record<KpiKey, ReactNode> = {
        attention: (
            <StatTile
                key="attention"
                label="Needs you"
                value={String(attention.length)}
                tone={attention.length ? 'attention' : 'neutral'}
                delta={attention.length ? { text: `${attention.filter((a) => DECISION_KINDS.has(a.kind)).length} decisions` } : { text: 'All clear' }}
                onClick={() => onFocus?.('attention')}
            />
        ),
        runs: (
            <StatTile
                key="runs"
                label="Runs today"
                value={String(today.ok + today.failed)}
                trend={trend}
                delta={{ text: `${compactNumber(total14)} in 14 days` }}
                onClick={() => onFocus?.('runs')}
            />
        ),
        failed: (
            <StatTile
                key="failed"
                label="Failed"
                value={String(today.failed)}
                tone={today.failed ? 'failure' : 'neutral'}
                delta={{ text: `${failed14} in 14 days` }}
                onClick={() => onFocus?.('runs')}
            />
        ),
        next: (
            <StatTile
                key="next"
                label="Next run"
                value={next ? relTime(next.at!, data.now) : '—'}
                delta={{ text: next ? `${next.agent?.label ?? next.workflow.name} · ${UPCOMING_KIND_LABEL[next.kind].toLowerCase()}` : 'nothing scheduled' }}
                onClick={() => onFocus?.('upcoming')}
            />
        ),
        agents: (
            <StatTile
                key="agents"
                label="Agents up"
                value={String(data.agents.running.length)}
                delta={{ text: data.agents.running.filter((r) => r.busy).length ? `${data.agents.running.filter((r) => r.busy).length} working now` : 'idle' }}
                onClick={() => onFocus?.('agents')}
            />
        ),
        credits: (
            <StatTile
                key="credits"
                label="Credits used"
                value={`${fmtCredits(data.credits.used)}`}
                delta={{ text: `of ${compactNumber(data.credits.cap)} · resets ${relTime(data.credits.nextRefreshAt, data.now)}`, good: data.credits.used / data.credits.cap < 0.9 }}
                onClick={() => onFocus?.('credits')}
            />
        ),
    };
    const order: KpiKey[] = items ?? ['attention', 'runs', 'failed', 'agents', 'next', 'credits'];
    return (
        <div className={cn('grid gap-6', className)} style={{ gridTemplateColumns: `repeat(${order.length}, minmax(0, 1fr))` }}>
            {order.map((k) =>
                tileClassName ? (
                    <div key={k} className={tileClassName} style={tileStyle}>
                        {tiles[k]}
                    </div>
                ) : (
                    tiles[k]
                )
            )}
        </div>
    );
}

// ---------------------------------------------------------------------------
// Stat treatments — the same facts, three more ways to set them.

const EYEBROW = 'text-[11px] font-semibold uppercase tracking-[0.1em] text-foreground/55 dark:text-foreground/35';

function LedgerCell({ label, value, suffix, sub, tone, trend, onClick }: { label: string; value: string; suffix?: string; sub: ReactNode; tone?: 'failure'; trend?: number[]; onClick?: () => void }) {
    // Every cell is exactly label / value / sub, so the grid's equal heights hold
    // no dead space (an extra element in one cell stretches all the others).
    return (
        <button type="button" onClick={onClick} className={cn('flex min-w-0 flex-col items-start gap-2 text-left transition-colors hover:bg-foreground/[0.025]', LAYOUT.ledgerCell)}>
            <span className={EYEBROW}>{label}</span>
            <span className="flex w-full items-end gap-4">
                <span className="inline-flex items-baseline gap-1.5">
                    <span className={cn('text-[28px] font-semibold leading-none tracking-tight', tone === 'failure' && 'text-red-600 dark:text-red-400')}>{value}</span>
                    {suffix && <span className="text-[13px] text-foreground/60 dark:text-foreground/40">{suffix}</span>}
                </span>
                {trend && <Sparkline values={trend} width={72} height={22} className="mb-[2px] shrink-0" />}
            </span>
            <span className="w-full truncate text-[12.5px] text-foreground/65 dark:text-foreground/45">{sub}</span>
        </button>
    );
}

/** One hairline strip, equal cells, eyebrow labels — the card vocabulary applied to numbers. */
export function KpiLedger({ data, onFocus, className }: SectionProps & { className?: string }) {
    const f = useKpiFacts(data);
    const cells: ReactNode[] = [
        <LedgerCell key="attention" label="Needs you" value={String(f.attention)} sub={f.attention ? [f.decisions ? `${f.decisions} to decide` : null, f.fixes ? `${f.fixes} to fix` : null].filter(Boolean).join(' · ') : 'all clear'} onClick={() => onFocus?.('attention')} />,
        <LedgerCell key="runs" label="Runs today" value={String(f.today)} trend={f.trend} sub={`${compactNumber(f.total14)} in 14 days`} onClick={() => onFocus?.('runs')} />,
        <LedgerCell key="failed" label="Failed" value={String(f.failedToday)} tone={f.failedToday ? 'failure' : undefined} sub={`${f.failed14} in 14 days`} onClick={() => onFocus?.('runs')} />,
        <LedgerCell key="agents" label="Agents up" value={String(f.agentsUp)} sub={f.agentsUp ? `${f.busy} working now` : 'none running'} onClick={() => onFocus?.('agents')} />,
        <LedgerCell key="next" label="Next run" value={f.next ? relTime(f.next.at!, data.now) : '—'} sub={f.next ? `${f.next.agent?.label ?? f.next.workflow.name} · ${UPCOMING_KIND_LABEL[f.next.kind].toLowerCase()}` : 'nothing scheduled'} onClick={() => onFocus?.('upcoming')} />,
        <LedgerCell
            key="credits"
            label="Credits"
            value={fmtCredits(f.credits.used)}
            suffix={`/ ${compactNumber(f.credits.cap)}`}
            sub={`resets ${relTime(f.credits.nextRefreshAt, data.now)}${f.credits.topup ? ` · ${compactNumber(f.credits.topup)} top-up` : ''}`}
            onClick={() => onFocus?.('credits')}
        />,
    ];
    return (
        <div className={cn(SURFACE, 'grid divide-x divide-border dark:divide-foreground/[0.06] overflow-hidden', className)} style={{ gridTemplateColumns: `repeat(${cells.length}, minmax(0, 1fr))` }}>
            {cells}
        </div>
    );
}

function StripStat({ n, text, tone, onClick }: { n: string; text: string; tone?: 'failure'; onClick?: () => void }) {
    return (
        <button type="button" onClick={onClick} className="inline-flex items-baseline gap-1.5 whitespace-nowrap text-foreground/70 dark:text-foreground/50 transition-colors hover:text-foreground">
            <span className={cn('text-[17px] font-semibold tabular-nums tracking-tight text-foreground', tone === 'failure' && 'text-red-600 dark:text-red-400')}>{n}</span>
            <span className="text-[13px]">{text}</span>
        </button>
    );
}

/** One line of numbers under the greeting — replaces its summary sentence. */
export function KpiStrip({ data, onFocus, className }: SectionProps & { className?: string }) {
    const f = useKpiFacts(data);
    const dot = <span className="text-foreground/40 dark:text-foreground/25">·</span>;
    return (
        <div className={cn('flex flex-wrap items-baseline gap-x-3 gap-y-1', className)}>
            <StripStat n={String(f.attention)} text={f.attention === 1 ? 'needs you' : 'need you'} onClick={() => onFocus?.('attention')} />
            {dot}
            <StripStat n={String(f.today)} text="runs today" onClick={() => onFocus?.('runs')} />
            {f.failedToday > 0 && <StripStat n={String(f.failedToday)} text="failed" tone="failure" onClick={() => onFocus?.('runs')} />}
            {dot}
            <StripStat n={String(f.agentsUp)} text={f.agentsUp === 1 ? 'agent up' : 'agents up'} onClick={() => onFocus?.('agents')} />
            {dot}
            {f.next ? (
                <StripStat n={relTime(f.next.at!, data.now)} text={`next run · ${f.next.agent?.label ?? f.next.workflow.name}`} onClick={() => onFocus?.('upcoming')} />
            ) : (
                <StripStat n="—" text="nothing scheduled" onClick={() => onFocus?.('upcoming')} />
            )}
            {dot}
            <StripStat n={fmtCredits(f.credits.used)} text={`of ${compactNumber(f.credits.cap)} credits`} onClick={() => onFocus?.('credits')} />
        </div>
    );
}

function Figure({ n, word, tone }: { n: string; word?: string; tone?: 'failure' }) {
    return (
        <span className="inline-flex items-baseline gap-1.5">
            <span className={cn('text-[26px] font-semibold leading-none tracking-tight', tone === 'failure' && 'text-red-600 dark:text-red-400')}>{n}</span>
            {word && <span className="text-[12px] text-foreground/65 dark:text-foreground/45">{word}</span>}
        </span>
    );
}

function Group({ label, sub, children, onClick }: { label: string; sub: ReactNode; children: ReactNode; onClick?: () => void }) {
    return (
        <button type="button" onClick={onClick} className="flex min-w-0 flex-1 flex-col items-start gap-2 px-7 text-left first:pl-0 last:pr-0">
            <span className={EYEBROW}>{label}</span>
            <span className="flex w-full items-end gap-5">{children}</span>
            <span className="w-full truncate text-[11.5px] text-foreground/65 dark:text-foreground/45">{sub}</span>
        </button>
    );
}

/** Four semantic clusters separated by hairlines; the sparkline lives with the runs. */
export function KpiGrouped({ data, onFocus, className }: SectionProps & { className?: string }) {
    const f = useKpiFacts(data);
    return (
        <div className={cn('flex items-stretch divide-x divide-border dark:divide-foreground/[0.06]', className)}>
            <Group label="Needs you" sub={f.attention ? [f.decisions ? `${f.decisions} to decide` : null, f.fixes ? `${f.fixes} to fix` : null].filter(Boolean).join(' · ') : 'all clear'} onClick={() => onFocus?.('attention')}>
                <Figure n={String(f.attention)} />
            </Group>
            <Group label="Runs" sub={`${compactNumber(f.total14)} in 14 days · ${f.rate}% succeeded`} onClick={() => onFocus?.('runs')}>
                <Figure n={String(f.today)} word="today" />
                <Figure n={String(f.failedToday)} word="failed" tone={f.failedToday ? 'failure' : undefined} />
                <Sparkline values={f.trend} width={72} height={22} className="mb-[2px] shrink-0" />
            </Group>
            <Group label="Agents" sub={f.next ? `next run ${relTime(f.next.at!, data.now)} · ${f.next.agent?.label ?? f.next.workflow.name}` : 'nothing scheduled'} onClick={() => onFocus?.('agents')}>
                <Figure n={String(f.agentsUp)} word="up" />
                <Figure n={String(f.busy)} word="working" />
            </Group>
            <Group label="Credits" sub={`resets ${relTime(f.credits.nextRefreshAt, data.now)}${f.credits.topup ? ` · ${compactNumber(f.credits.topup)} top-up in reserve` : ''}`} onClick={() => onFocus?.('credits')}>
                <span className="flex flex-col gap-2" style={{ minWidth: 140 }}>
                    <Figure n={fmtCredits(f.credits.used)} word={`/ ${compactNumber(f.credits.cap)}`} />
                    <Meter value={f.credits.used} max={f.credits.cap} />
                </span>
            </Group>
        </div>
    );
}

// ---------------------------------------------------------------------------
// Upcoming

export const UPCOMING_KIND_LABEL: Record<UpcomingKind, string> = { schedule: 'Schedule', alarm: 'Agent alarm', resume: 'Resumes' };

/** "Today 08:00" · "Tomorrow 07:00" · "Sep 8, 07:00", against the fixture clock. */
function whenLabel(iso: string, now: string): string {
    const t = new Date(iso);
    const n = new Date(now);
    const sameDay = t.toDateString() === n.toDateString();
    const tomorrow = new Date(n);
    tomorrow.setDate(n.getDate() + 1);
    if (sameDay) return `Today ${clockLabel(iso)}`;
    if (t.toDateString() === tomorrow.toDateString()) return `Tomorrow ${clockLabel(iso)}`;
    return dateLabel(iso);
}

function sortUpcoming(list: UpcomingRun[]): UpcomingRun[] {
    return [...list].sort((a, b) => (a.at ? Date.parse(a.at) : Infinity) - (b.at ? Date.parse(b.at) : Infinity));
}

function UpcomingRowView({ u, now, compact = false }: { u: UpcomingRun; now: string; compact?: boolean }) {
    const { openWorkflow } = useDashboardActions();
    const soon = u.at ? Date.parse(u.at) - Date.parse(now) < 6 * 3600_000 : false;
    return (
        <div className={cn('-mx-2 flex items-center gap-3 rounded-lg px-2 py-2.5', ROW_HOVER)}>
            <span className={cn('w-14 shrink-0 text-[12.5px] tabular-nums', !u.at ? 'text-red-600 dark:text-red-400' : soon ? 'text-foreground' : 'text-foreground/70 dark:text-foreground/50')}>{u.at ? relTime(u.at, now) : 'not set'}</span>
            <NodeMark type={u.agent ? agentMarkType(u.agent.model) : u.nodeType} size="md" />
            <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 text-[14px]">
                    <span className="truncate">{u.label}</span>
                    {!compact && <span className="hidden shrink-0 text-[11px] text-foreground/55 dark:text-foreground/35 sm:inline">{UPCOMING_KIND_LABEL[u.kind]}</span>}
                </div>
                <div className="mt-0.5 flex min-w-0 items-center gap-2 whitespace-nowrap text-[12px] text-foreground/60 dark:text-foreground/40">
                    <WorkflowLine workflow={u.workflow} className="min-w-0 shrink" showMarks={!compact} />
                    {u.agent && !compact && <span className="shrink-0">· {u.agent.label}</span>}
                    {u.recurrence && <span className="shrink-0">· {u.recurrence}</span>}
                    {u.error && <span className="truncate text-red-600 dark:text-red-400">· {u.error}</span>}
                </div>
            </div>
            <span className="shrink-0 text-[12px] tabular-nums text-foreground/60 dark:text-foreground/40">
                {u.at ? whenLabel(u.at, now) : <PrimaryButton onClick={() => openWorkflow(u.workflow)}>Fix</PrimaryButton>}
            </span>
        </div>
    );
}

export function UpcomingCompact({ data, onFocus, limit = 4 }: SectionProps & { limit?: number }) {
    const list = sortUpcoming(data.upcoming);
    if (!list.length) return <EmptyState title="Nothing scheduled" hint="Schedules, agent alarms and delayed runs show up here in time order." />;
    return (
        <div>
            <div className={ROWS}>
                {list.slice(0, limit).map((u) => (
                    <UpcomingRowView key={u.id} u={u} now={data.now} compact />
                ))}
            </div>
            {list.length > limit && (
                <div className="pt-2">
                    <TextLink onClick={() => onFocus?.('upcoming')}>{list.length - limit} more</TextLink>
                </div>
            )}
        </div>
    );
}

export function UpcomingFull({ data, onFocus }: SectionProps) {
    const list = sortUpcoming(data.upcoming);
    const n = new Date(data.now);
    const dayOf = (iso: string) => new Date(iso).toDateString();
    const groups: { title: string; items: UpcomingRun[] }[] = [
        { title: 'Overdue', items: list.filter((u) => u.at && Date.parse(u.at) < n.getTime()) },
        { title: 'Today', items: list.filter((u) => u.at && Date.parse(u.at) >= n.getTime() && dayOf(u.at) === n.toDateString()) },
        { title: 'Tomorrow', items: list.filter((u) => u.at && dayOf(u.at) === new Date(n.getTime() + 86_400_000).toDateString()) },
        { title: 'Later', items: list.filter((u) => u.at && Date.parse(u.at) >= new Date(n.getTime() + 86_400_000).setHours(24, 0, 0, 0)) },
        { title: 'Not scheduled', items: list.filter((u) => !u.at) },
    ].filter((g) => g.items.length);
    if (!groups.length) return <EmptyState title="Nothing scheduled" hint="Schedules, agent alarms and delayed runs show up here in time order." />;
    return (
        <div className="space-y-8">
            {groups.map((g) => (
                <div key={g.title}>
                    <Eyebrow className="mb-1" right={g.title === 'Not scheduled' ? undefined : <span className="text-[11px] text-foreground/55 dark:text-foreground/35">{g.items.length}</span>}>
                        {g.title}
                    </Eyebrow>
                    <div className={ROWS}>
                        {g.items.map((u) => (
                            <UpcomingRowView key={u.id} u={u} now={data.now} />
                        ))}
                    </div>
                </div>
            ))}
            <div className="flex items-center gap-3 text-[11.5px] text-foreground/65 dark:text-foreground/45">
                <TextLink onClick={() => onFocus?.('triggers')}>Manage triggers</TextLink>
                <span className="inline-flex items-center gap-1">
                    <Clock className="h-3 w-3" /> Alarms are set by agents in their own chats
                </span>
            </div>
        </div>
    );
}

// ---------------------------------------------------------------------------
// Attention

function AttentionMark({ item, size }: { item: AttentionItem; size: 'sm' | 'md' }) {
    if (item.provider) return <NodeMark type={item.provider} size={size} className="mt-[3px]" />;
    if (item.credentialType) return <CredentialMark credentialType={item.credentialType} size={size} className="mt-[3px]" />;
    if (item.from) return <NodeMark type={agentMarkType(item.from.model)} size={size} className="mt-[3px]" />;
    return <NodeMark type={item.workflow.marks[0] ?? 'agent'} size={size} className="mt-[3px]" />;
}

function PrimaryButton({ children, onClick, className }: { children: ReactNode; onClick?: () => void; className?: string }) {
    return (
        <button
            type="button"
            onClick={(e) => {
                e.stopPropagation();
                onClick?.();
            }}
            className={cn(
                'inline-flex h-7 items-center gap-1 rounded-md bg-primary px-2.5 text-[12px] font-medium text-primary-foreground transition-opacity hover:opacity-90',
                className
            )}
        >
            {children}
        </button>
    );
}

function QuietButton({ children, onClick, className, ...rest }: { children: ReactNode; onClick?: () => void; className?: string } & Pick<ButtonHTMLAttributes<HTMLButtonElement>, 'aria-label' | 'title'>) {
    return (
        <button
            type="button"
            {...rest}
            onClick={(e) => {
                e.stopPropagation();
                onClick?.();
            }}
            className={cn(
                'inline-flex h-7 items-center gap-1 rounded-md px-2 text-[12px] text-foreground/75 dark:text-foreground/60 transition-colors hover:bg-foreground/[0.06] hover:text-foreground',
                className
            )}
        >
            {children}
        </button>
    );
}

type AskInput = { id: string; type?: string; label?: string; credentialType?: string; multiple?: boolean; options?: { id: string; label: string }[] };

/** The builder's first question, typed — it decides what the row offers. */
function firstAskInput(item: AttentionItem): AskInput | undefined {
    return item.inputs?.[0] as AskInput | undefined;
}

/** What answering means for this ask, in one verb. */
function askVerb(item: AttentionItem): string {
    const input = firstAskInput(item);
    switch (input?.type) {
        case 'credential':
            return 'Connect';
        case 'selection':
            return 'Choose';
        case 'env':
            return 'Add env vars';
        case 'config':
            return 'Fill in';
        default:
            return 'Answer';
    }
}

/** Single-choice asks are answered from the row itself: the options, inline. */
function inlineChoices(item: AttentionItem): { inputId: string; options: { id: string; label: string }[] } | null {
    const input = firstAskInput(item);
    if (input?.type === 'selection' && !input.multiple && input.options?.length && input.options.length <= 4 && (item.inputs?.length ?? 0) === 1) {
        return { inputId: input.id, options: input.options };
    }
    if (item.choices?.length && !item.inputs?.length) {
        return { inputId: String(item.fields?.[0]?.name ?? item.meta?.inputId ?? 'answer'), options: item.choices.map((c) => ({ id: c, label: c })) };
    }
    return null;
}

/** Icon-only "copy link": a secondary act that should not compete with the row's
 *  verbs. The icon flips to a check while the copy is fresh. */
function CopyLinkButton({ onCopy, className }: { onCopy: () => Promise<boolean> | boolean; className?: string }) {
    const [copied, setCopied] = useState(false);
    return (
        <QuietButton
            aria-label={copied ? 'Link copied' : 'Copy link'}
            title="Copy link"
            className={cn('w-7 justify-center px-0 text-foreground/60 dark:text-foreground/40', className)}
            onClick={async () => {
                if (!(await onCopy())) return;
                setCopied(true);
                setTimeout(() => setCopied(false), 2000);
            }}
        >
            {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
        </QuietButton>
    );
}

/** Mint the ask's public link and copy it. */
function CopyAskLink({ item }: { item: AttentionItem }) {
    const { shareAsk } = useDashboardActions();
    if (!shareAsk) return null;
    return (
        <CopyLinkButton
            onCopy={async () => {
                const url = await shareAsk(item);
                if (!url) return false;
                await navigator.clipboard?.writeText(url);
                return true;
            }}
        />
    );
}

function AttentionActions({ item, values, expanded, onToggle }: { item: AttentionItem; values: Record<string, unknown>; expanded?: boolean; onToggle?: () => void }) {
    const actions = useDashboardActions();
    switch (item.kind) {
        case 'builder_ask':
            // Expanded, the wizard's own footer carries Copy link and Skip.
            return (
                <>
                    {!expanded && <CopyAskLink item={item} />}
                    {!expanded && actions.dismissAsk && <QuietButton onClick={() => actions.dismissAsk?.(item)}>Skip</QuietButton>}
                    {onToggle && (
                        <PrimaryButton onClick={onToggle}>
                            {expanded ? 'Hide' : askVerb(item)} {expanded ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                        </PrimaryButton>
                    )}
                </>
            );
        case 'approval':
            return (
                <>
                    <QuietButton onClick={() => actions.respondApproval(item, 'rejected', values)}>Reject</QuietButton>
                    <PrimaryButton onClick={() => actions.respondApproval(item, 'approved', values)}>
                        <Check className="h-3 w-3" strokeWidth={2.5} /> Approve
                    </PrimaryButton>
                </>
            );
        case 'builder_prompt':
            return (
                <>
                    <QuietButton onClick={() => actions.decideProposal(item, 'dismissed')}>Dismiss</QuietButton>
                    <PrimaryButton onClick={() => actions.decideProposal(item, 'approved')}>Build it</PrimaryButton>
                </>
            );
        case 'bridge_link':
            return (
                <>
                    <CopyLinkButton
                        onCopy={() => {
                            actions.copyLink(item);
                            return true;
                        }}
                    />
                    <PrimaryButton onClick={() => actions.openLink(item)}>Connect</PrimaryButton>
                </>
            );
        case 'credential_request':
            return (
                <>
                    <QuietButton onClick={() => actions.cancelCredentialRequest(item)}>Cancel</QuietButton>
                    {actions.resendCredentialRequest && (
                        <QuietButton onClick={() => actions.resendCredentialRequest?.(item)}>
                            <RefreshCw className="h-3 w-3" /> Resend
                        </QuietButton>
                    )}
                </>
            );
        case 'credential_dead':
            return (
                <PrimaryButton onClick={() => actions.reconnectCredential({ credentialId: item.meta?.credentialId as string | undefined, credentialType: item.credentialType, name: item.title })}>
                    Reconnect
                </PrimaryButton>
            );
        case 'trigger_broken':
            return <PrimaryButton onClick={() => actions.openWorkflow(item.workflow, item.meta?.nodeId as string | undefined)}>Open trigger</PrimaryButton>;
        default:
            return null;
    }
}

function AskChoices({ item, className }: { item: AttentionItem; className?: string }) {
    const { answerAsk } = useDashboardActions();
    const choices = inlineChoices(item);
    if (!choices) return null;
    return (
        <div className={cn('flex flex-wrap gap-1.5', className)} role="presentation" onClick={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()}>
            {choices.options.map((o) => (
                <button
                    key={o.id}
                    type="button"
                    onClick={() => answerAsk(item, { [choices.inputId]: o.id })}
                    className="rounded-md border border-border dark:border-foreground/10 px-2.5 py-1 text-[12px] text-foreground/80 transition-colors hover:border-foreground/30 hover:bg-foreground/[0.04] hover:text-foreground"
                >
                    {o.label}
                </button>
            ))}
        </div>
    );
}

export function AttentionRow({
    item,
    now,
    expanded,
    onToggle,
    dense = false,
    compact = false,
    onActivate,
}: {
    item: AttentionItem;
    now: string;
    expanded?: boolean;
    onToggle?: () => void;
    /** Dense rows carry no inline actions; the whole row opens the queue instead. */
    dense?: boolean;
    /** Overview cards: title, one line of context, actions — no kind label, no marks. */
    compact?: boolean;
    onActivate?: () => void;
}) {
    const quiet = dense || compact;
    const isDecision = DECISION_KINDS.has(item.kind);
    // A row expands only when there is a form to show; a choice-only ask is
    // answered from its chips, so it has nothing to open.
    const expandable = !dense && !!(item.fields?.length || item.inputs?.length);
    const [values, setValues] = useState<Record<string, unknown>>(() => Object.fromEntries((item.fields ?? []).map((f) => [f.name, f.value ?? ''])));
    const { answerAsk } = useDashboardActions();
    return (
        <div
            className={cn('group/row -mx-2 rounded-lg px-2', (expandable || dense) && 'cursor-pointer', ROW_HOVER)}
            {...clickableRow(dense ? onActivate : expandable ? onToggle : undefined)}
        >
            <div className={cn('flex items-start gap-3', dense ? 'py-2' : 'py-3')}>
                <AttentionMark item={item} size={dense ? 'sm' : 'md'} />
                <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                        <span className={cn('truncate text-[14px] text-foreground', isDecision && 'font-medium')}>{item.title}</span>
                        {!quiet && (
                            <span className="hidden shrink-0 text-[11px] text-foreground/55 dark:text-foreground/35 sm:inline">
                                {ATTENTION_KIND_LABEL[item.kind]}
                            </span>
                        )}
                    </div>
                    {!dense && item.detail && !expanded && (
                        <p className="m-0 mt-0.5 line-clamp-1 text-[13px] text-foreground/70 dark:text-foreground/50">{item.detail}</p>
                    )}
                    {!dense && !expanded && item.kind === 'builder_ask' && <AskChoices item={item} className="mt-2" />}
                    <div className="mt-1 flex min-w-0 items-center gap-2 whitespace-nowrap text-[12px] text-foreground/60 dark:text-foreground/40">
                        <WorkflowLine workflow={item.workflow} className="min-w-0 shrink" maxMarks={3} showMarks={!quiet} />
                        {item.from && !quiet && (
                            <span className="inline-flex shrink-0 items-center gap-1">
                                · <NodeMark type={agentMarkType(item.from.model)} size="xs" /> {item.from.label}
                            </span>
                        )}
                        <span className="shrink-0">· {relTime(item.createdAt, now)}</span>
                    </div>
                </div>
                {dense ? (
                    <ChevronRight className="mt-[5px] h-3.5 w-3.5 shrink-0 text-foreground/0 transition-colors group-hover/row:text-foreground/70 dark:group-hover/row:text-foreground/50" />
                ) : (
                    <div className="flex shrink-0 items-center gap-1" role="presentation" onClick={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()}>
                        <AttentionActions item={item} values={values} expanded={expanded} onToggle={expandable ? onToggle : undefined} />
                    </div>
                )}
            </div>
            {expanded && (
                <div className="ml-8 space-y-3 pb-3 pr-1" role="presentation" onClick={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()}>
                    {item.detail && !item.inputs?.length && <p className="m-0 text-[13px] leading-relaxed text-foreground/75 dark:text-foreground/60">{item.detail}</p>}
                    {item.kind === 'builder_ask' && item.inputs?.length ? (
                        <AskAnswer item={item} />
                    ) : (
                        <>
                            {item.fields && (
                                <div className="grid gap-3 sm:grid-cols-2">
                                    {item.fields.map((f) => (
                                        <div key={f.name} className={f.type === 'text' || f.type === 'media' || f.type === 'list' ? 'sm:col-span-2' : ''}>
                                            <ApprovalField field={f} value={values[f.name]} onChange={(v) => setValues((prev) => ({ ...prev, [f.name]: v }))} />
                                        </div>
                                    ))}
                                </div>
                            )}
                            {item.kind === 'builder_ask' && item.fields && !item.choices && (
                                <div className="flex justify-end">
                                    <PrimaryButton onClick={() => answerAsk(item, values)}>Send answers</PrimaryButton>
                                </div>
                            )}
                        </>
                    )}
                </div>
            )}
        </div>
    );
}

export function AttentionCompact({ data, onFocus, limit = 4, dense = false }: SectionProps & { limit?: number; dense?: boolean }) {
    const items = useVisibleAttention(data);
    const [open, setOpen] = useState<string | null>(null);
    if (!items.length) return <EmptyState title="Nothing needs you" hint="Approvals, questions and disconnected accounts land here." />;
    const shown = items.slice(0, limit);
    return (
        <div>
            <div className={ROWS}>
                {shown.map((it) => (
                    <AttentionRow
                        key={it.id}
                        item={it}
                        now={data.now}
                        dense={dense}
                        compact
                        expanded={open === it.id}
                        onToggle={() => setOpen((v) => (v === it.id ? null : it.id))}
                        onActivate={() => onFocus?.('attention')}
                    />
                ))}
            </div>
            {items.length > shown.length && (
                <div className="pt-2">
                    <TextLink onClick={() => onFocus?.('attention')}>{items.length - shown.length} more</TextLink>
                </div>
            )}
        </div>
    );
}

type AttentionFilter = 'all' | 'decisions' | 'fixes' | AttentionKind;

export function AttentionFull({ data }: SectionProps) {
    const items = useVisibleAttention(data);
    const [filter, setFilter] = useState<AttentionFilter>('all');
    const [open, setOpen] = useState<string | null>(null);
    const decisions = items.filter((i) => DECISION_KINDS.has(i.kind));
    const fixes = items.filter((i) => !DECISION_KINDS.has(i.kind));
    const kinds = Array.from(new Set(items.map((i) => i.kind)));
    const visible = filter === 'all' ? items : filter === 'decisions' ? decisions : filter === 'fixes' ? fixes : items.filter((i) => i.kind === filter);
    const chip = (key: AttentionFilter, label: string, n: number) => (
        <button
            key={key}
            type="button"
            onClick={() => setFilter(key)}
            className={cn(
                'inline-flex h-7 items-center gap-1.5 rounded-md px-2.5 text-[12px] transition-colors',
                filter === key ? 'bg-foreground/[0.08] text-foreground' : 'text-foreground/70 dark:text-foreground/50 hover:text-foreground'
            )}
        >
            {label}
            <span className="tabular-nums text-foreground/55 dark:text-foreground/35">{n}</span>
        </button>
    );
    return (
        <div>
            <div className="mb-3 flex flex-wrap items-center gap-1">
                {chip('all', 'All', items.length)}
                {chip('decisions', 'Decisions', decisions.length)}
                {chip('fixes', 'To fix', fixes.length)}
                <span className="mx-1 h-4 w-px bg-foreground/10" />
                {kinds.map((k) => chip(k, ATTENTION_KIND_LABEL[k], items.filter((i) => i.kind === k).length))}
            </div>
            {visible.length ? (
                <div className={ROWS}>
                    {visible.map((it) => (
                        <AttentionRow key={it.id} item={it} now={data.now} expanded={open === it.id} onToggle={() => setOpen((v) => (v === it.id ? null : it.id))} />
                    ))}
                </div>
            ) : (
                <EmptyState title="Nothing here" hint={items.length ? 'Try another filter.' : 'Approvals, questions and disconnected accounts land here.'} />
            )}
        </div>
    );
}

// ---------------------------------------------------------------------------
// Runs

const TRIGGER_LABEL: Record<TriggerSource, string> = {
    manual: 'Manual',
    webhook: 'Event',
    cron: 'Schedule',
    mcp: 'MCP',
    api: 'API',
    email: 'Email',
    agent_turn: 'Agent turn',
    shared_agent: 'Shared link',
    builder_event: 'Builder',
    agent_email_reply: 'Email reply',
    error_handler: 'Error handler',
};

function runVerdict(status: RunStatus): VerdictStatus {
    if (status === 'completed') return 'ok';
    if (status === 'error') return 'failed';
    if (status === 'running') return 'running';
    return 'waiting';
}

function runStatusLabel(status: RunStatus): string {
    switch (status) {
        case 'completed':
            return 'Finished';
        case 'error':
            return 'Failed';
        case 'running':
            return 'Running';
        case 'awaiting_approval':
            return 'Waiting for approval';
        default:
            return 'Waiting';
    }
}

export function RunRowView({ run, now, expanded, onToggle }: { run: RunRow; now: string; expanded?: boolean; onToggle?: () => void }) {
    const actions = useDashboardActions();
    const failed = run.status === 'error';
    return (
        <div className={cn('-mx-2 cursor-pointer rounded-lg px-2', ROW_HOVER)} {...clickableRow(onToggle)}>
            <div className="flex items-center gap-3 py-2">
                <Verdict status={runVerdict(run.status)} className="w-4" label={runStatusLabel(run.status)} />
                <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 text-[14px]">
                        <span className="truncate text-foreground">{run.workflow.name}</span>
                        <span className="shrink-0 text-[11.5px] text-foreground/55 dark:text-foreground/35">{TRIGGER_LABEL[run.trigger]}</span>
                    </div>
                    <p className={cn('m-0 mt-0.5 line-clamp-1 text-[13px]', failed ? 'text-red-600 dark:text-red-400' : 'text-foreground/70 dark:text-foreground/50')}>
                        {failed ? run.error : run.summary ?? runStatusLabel(run.status)}
                    </p>
                </div>
                <div className="flex shrink-0 items-center gap-3 text-[11px] tabular-nums text-foreground/60 dark:text-foreground/40">
                    {run.durationMs != null && <span>{fmtDuration(run.durationMs)}</span>}
                    <span title={dateLabel(run.startedAt)}>{relTime(run.startedAt, now)}</span>
                    <ChevronRight className={cn('h-3.5 w-3.5 transition-transform', expanded && 'rotate-90')} />
                </div>
            </div>
            {expanded && (
                <div className="ml-7 mb-3 grid gap-3 rounded-lg border border-border dark:border-foreground/[0.06] bg-foreground/[0.02] px-3.5 py-3 text-[12px] sm:grid-cols-[auto_1fr]" role="presentation" onClick={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()}>
                    <span className="text-foreground/60 dark:text-foreground/40">Started</span>
                    <span>{dateLabel(run.startedAt)}</span>
                    <span className="text-foreground/60 dark:text-foreground/40">Nodes</span>
                    <span>{run.nodesExecuted} ran</span>
                    {run.failedNode && (
                        <>
                            <span className="text-foreground/60 dark:text-foreground/40">Failed at</span>
                            <span className="inline-flex items-center gap-1.5">
                                <NodeMark type={run.failedNode.type} size="xs" /> {run.failedNode.label}
                            </span>
                        </>
                    )}
                    {run.error && (
                        <>
                            <span className="text-foreground/60 dark:text-foreground/40">Error</span>
                            <span className="font-mono text-[11.5px] text-red-600 dark:text-red-400">{run.error}</span>
                        </>
                    )}
                    <span />
                    <span className="flex gap-3">
                        <TextLink onClick={() => (actions.openExecution && isPersistedExecutionId(run.id) ? actions.openExecution(run) : actions.openRun(run))}>Open run</TextLink>
                        <TextLink onClick={() => actions.openWorkflow(run.workflow)}>Open workflow</TextLink>
                        {failed && actions.retryRun && <TextLink onClick={() => actions.retryRun?.(run)} icon={false}>Retry</TextLink>}
                    </span>
                </div>
            )}
        </div>
    );
}

/** One workflow's window: the row opens the workflow, where its run log and
 *  the failing node live. */
function WorkflowStatsRow({ stat, now, narrow = false, showLast = true }: { stat: DashboardData['runs']['byWorkflow'][number]; now: string; narrow?: boolean; showLast?: boolean }) {
    const { openWorkflow } = useDashboardActions();
    return (
        <div {...clickableRow(() => openWorkflow(stat.workflow))} className={cn('group/wf -mx-2 flex cursor-pointer items-center gap-3 rounded-lg px-2 py-2', ROW_HOVER)}>
            <MarkRow types={stat.workflow.marks} size="xs" max={narrow ? 2 : 3} hideRest className={cn('shrink-0', narrow ? 'w-[38px]' : 'w-[58px]')} />
            <span className="min-w-0 flex-1 truncate text-[14px] transition-colors group-hover/wf:text-foreground">{stat.workflow.name}</span>
            {!narrow && <Sparkline values={stat.days.map((d) => d.ok + d.failed)} width={64} height={18} />}
            <span className="w-10 shrink-0 text-right text-[12px] tabular-nums text-foreground/75 dark:text-foreground/60">{stat.runs}</span>
            <span className={cn('w-[76px] shrink-0 whitespace-nowrap text-right text-[12px] tabular-nums', stat.failed ? 'text-red-600 dark:text-red-400' : 'text-foreground/45 dark:text-foreground/30')}>
                {stat.failed ? `${stat.failed} failed` : '—'}
            </span>
            {!narrow && showLast && <span className="w-16 shrink-0 text-right text-[11px] tabular-nums text-foreground/60 dark:text-foreground/40">{relTime(stat.lastRunAt, now)}</span>}
            <ArrowUpRight className="h-3 w-3 shrink-0 text-foreground/0 transition-colors group-hover/wf:text-foreground/50" />
        </div>
    );
}

export function RunsCompact({ data, onFocus, chart = true, top = 4, narrow = false, stats = true }: SectionProps & { chart?: boolean; top?: number; narrow?: boolean; stats?: boolean }) {
    const total = data.runs.days.reduce((a, b) => a + b.ok + b.failed, 0);
    const failed = data.runs.days.reduce((a, b) => a + b.failed, 0);
    if (!total) return <EmptyState title="Nothing has run yet" hint="Runs from every workflow show up here, with failures called out." />;
    const rate = total ? Math.round(((total - failed) / total) * 100) : 100;
    return (
        <div>
            <div className={cn('mb-3 flex items-baseline gap-4 text-[12px] text-foreground/70 dark:text-foreground/50', !stats && 'hidden')}>
                <span>
                    <span className="text-[15px] font-semibold tabular-nums text-foreground">{compactNumber(total)}</span> runs · 14 days
                </span>
                <span>
                    <span className={cn('text-[15px] font-semibold tabular-nums', failed ? 'text-red-600 dark:text-red-400' : 'text-foreground')}>{failed}</span> failed
                </span>
                <span className="ml-auto tabular-nums">{rate}% succeeded</span>
            </div>
            {chart && <RunsColumns days={data.runs.days} height={88} now={data.now} />}
            <div className={cn('mt-3', ROWS, chart && 'border-t border-border dark:border-foreground/[0.06]')}>
                {data.runs.byWorkflow.slice(0, top).map((s) => (
                    <WorkflowStatsRow key={s.workflow.id} stat={s} now={data.now} narrow={narrow} showLast={false} />
                ))}
            </div>
            {data.runs.byWorkflow.length > top && (
                <div className="pt-2">
                    <TextLink onClick={() => onFocus?.('runs')}>{data.runs.byWorkflow.length - top} more workflows</TextLink>
                </div>
            )}
        </div>
    );
}

type RunFilter = 'all' | 'failed' | 'waiting' | 'running';

export function RunsFull({ data }: SectionProps) {
    const actions = useDashboardActions();
    const [filter, setFilter] = useState<RunFilter>('all');
    const [window, setWindow] = useState<'24h' | '7d' | '14d'>('14d');
    const [open, setOpen] = useState<string | null>(null);
    const rows = data.runs.recent.filter((r) =>
        filter === 'all' ? true : filter === 'failed' ? r.status === 'error' : filter === 'running' ? r.status === 'running' : r.status.startsWith('awaiting')
    );
    const days = window === '14d' ? data.runs.days : window === '7d' ? data.runs.days.slice(-7) : data.runs.days.slice(-1);
    const total = days.reduce((a, b) => a + b.ok + b.failed, 0);
    const failed = days.reduce((a, b) => a + b.failed, 0);
    const seg = <T extends string>(value: T, current: T, set: (v: T) => void, label: string, n?: number) => (
        <button
            type="button"
            onClick={() => set(value)}
            className={cn('inline-flex h-7 items-center gap-1.5 rounded-md px-2.5 text-[12px] transition-colors', current === value ? 'bg-foreground/[0.08] text-foreground' : 'text-foreground/70 dark:text-foreground/50 hover:text-foreground')}
        >
            {label}
            {n != null && <span className="tabular-nums text-foreground/55 dark:text-foreground/35">{n}</span>}
        </button>
    );
    return (
        <div className="space-y-8">
            <div>
                <div className="mb-3 flex flex-wrap items-center gap-1">
                    {seg('24h', window, setWindow, 'Today')}
                    {seg('7d', window, setWindow, '7 days')}
                    {seg('14d', window, setWindow, '14 days')}
                    <span className="ml-auto flex items-baseline gap-4 text-[12px] text-foreground/70 dark:text-foreground/50">
                        <span>
                            <span className="text-[15px] font-semibold tabular-nums text-foreground">{compactNumber(total)}</span> runs
                        </span>
                        <span>
                            <span className={cn('text-[15px] font-semibold tabular-nums', failed ? 'text-red-600 dark:text-red-400' : 'text-foreground')}>{failed}</span> failed
                        </span>
                    </span>
                </div>
                <RunsColumns days={days} height={140} now={data.now} />
            </div>

            <div>
                {/* Column headings ride the eyebrow row, right-anchored with the rows'
                    own column widths, so the table has one heading line. */}
                <Eyebrow
                    className="mb-1"
                    right={
                        data.runs.byWorkflow.length ? (
                            <span className="flex items-center gap-3 text-[10.5px] uppercase tracking-[0.08em] text-foreground/45 dark:text-foreground/30">
                                <span className="w-16">Trend</span>
                                <span className="w-10 text-right">Runs</span>
                                <span className="w-[76px] text-right">Failed</span>
                                <span className="w-16 text-right">Last</span>
                                <span className="w-3" />
                            </span>
                        ) : null
                    }
                >
                    By workflow
                </Eyebrow>
                {data.runs.byWorkflow.length ? (
                    <div className={cn(ROWS, 'border-t border-border dark:border-foreground/[0.06]')}>
                        {data.runs.byWorkflow.map((s) => (
                            <WorkflowStatsRow key={s.workflow.id} stat={s} now={data.now} />
                        ))}
                    </div>
                ) : (
                    <EmptyState title="No workflows have run yet" />
                )}
            </div>

            <div>
                <div className="mb-2 flex items-center gap-1">
                    <Eyebrow>Recent runs</Eyebrow>
                    <span className="ml-auto flex items-center gap-1">
                        {seg('all', filter, setFilter, 'All', data.runs.recent.length)}
                        {seg('failed', filter, setFilter, 'Failed', data.runs.recent.filter((r) => r.status === 'error').length)}
                        {seg('waiting', filter, setFilter, 'Waiting', data.runs.recent.filter((r) => r.status.startsWith('awaiting')).length)}
                        {seg('running', filter, setFilter, 'Running', data.runs.recent.filter((r) => r.status === 'running').length)}
                    </span>
                </div>
                {rows.length ? (
                    <div className={ROWS}>
                        {rows.map((r) => (
                            <RunRowView key={r.id} run={r} now={data.now} expanded={open === r.id} onToggle={() => setOpen((v) => (v === r.id ? null : r.id))} />
                        ))}
                    </div>
                ) : (
                    <EmptyState title="No runs match" />
                )}
                {rows.length > 0 && actions.loadOlderRuns && (
                    <div className="pt-3">
                        <TextLink onClick={() => actions.loadOlderRuns?.()}>Older runs</TextLink>
                    </div>
                )}
            </div>
        </div>
    );
}

// ---------------------------------------------------------------------------
// Agents

function humanizeTool(tool: string): string {
    const op = tool.includes('__') ? tool.split('__').slice(1).join(' ') : tool;
    return op.replace(/_/g, ' ');
}

/** The run popup's tool-call shape, so its send derivation and native frames apply to a turn. */
function toReplayCalls(turn: AgentTurn): ReplayToolCall[] {
    return turn.toolCalls.map((c) => ({
        agent_node_id: turn.agent.nodeId,
        tool_name: c.tool,
        tool_type: 'node_op',
        provider_node_id: null,
        operation: c.operation || null,
        credential_id: null,
        arguments: (c.arguments && typeof c.arguments === 'object' ? (c.arguments as Record<string, unknown>) : null),
        result_status: c.status,
        error: c.error ?? null,
        result_preview: c.result ?? null,
        duration_ms: c.durationMs,
        timestamp: c.at ?? null,
    }));
}

/** Brand marks keyed by provider slug for the native frames. */
function iconsForProviders(slugs: string[]): Record<string, Mark> {
    const icons: Record<string, Mark> = {};
    for (const slug of slugs) {
        for (const type of [slug, `automation-${slug.replace(/_/g, '-')}`]) {
            const meta = getNodeIconMeta(type);
            if (meta?.iconHtml) {
                icons[slug] = { iconHtml: meta.iconHtml, iconColor: meta.iconColor };
                break;
            }
        }
    }
    return icons;
}

/** What the agent sent, in each app's own shape — the run popup's frames. */
function TurnSends({ turn }: { turn: AgentTurn }) {
    const sends = useMemo(() => deriveSends(toReplayCalls(turn)).filter((s) => turn.toolCalls[s.callIndex]?.status !== 'error'), [turn]);
    const icons = useMemo(() => iconsForProviders(sends.map((s) => s.provider)), [sends]);
    if (!sends.length) return null;
    return (
        <div className="space-y-3">
            {sends.map((send, i) => (
                <div key={i}>
                    <div className="mb-1.5 flex items-center justify-between gap-3 px-0.5 text-[12px]">
                        <span className="min-w-0 truncate font-medium text-foreground/75 dark:text-foreground/60">{send.to || 'Sent'}</span>
                        <span className="inline-flex shrink-0 items-center gap-1.5 text-[11px] text-foreground/65 dark:text-foreground/45">
                            <Check className="h-3 w-3 text-foreground/60 dark:text-foreground/40" /> Sent{send.clock ? ` · ${send.clock}` : ''}
                        </span>
                    </div>
                    <OutboundMessage
                        icons={icons}
                        artifact={{ provider: send.provider, to: send.to, text: send.text ?? '', subject: send.subject, media: send.media }}
                        hideDestination
                        agentName={turn.agent.label}
                        suppressByline
                    />
                </div>
            ))}
        </div>
    );
}

/** The popup's story for a turn that ran as an execution, loaded once per run
 *  and only when the card is open. The same loader and builder the Story popup
 *  uses, so "what came in" wears the app's own frame and sends carry resolved
 *  names. `null` while loading or when the turn has no persisted run. */
const turnStories = new Map<string, Promise<Story | null>>();
function useTurnStory(turn: AgentTurn, open: boolean): Story | null {
    const [story, setStory] = useState<Story | null>(null);
    const id = turn.executionId && isPersistedExecutionId(turn.executionId) ? turn.executionId : null;
    useEffect(() => {
        if (!open || !id) return;
        let cancelled = false;
        let pending = turnStories.get(id);
        if (!pending) {
            pending = loadRunStory(turn.workflow.id, id)
                .then((loaded) =>
                    buildRunStory({
                        results: loaded.results,
                        agentInputs: loaded.extras.agentInputs as StoryInput['agentInputs'],
                        workflowName: turn.workflow.name,
                        agentName: turn.agent.label,
                        startedAt: turn.startedAt,
                        durationMs: turn.durationMs,
                    })
                )
                .catch(() => null);
            turnStories.set(id, pending);
        }
        pending.then((s) => {
            if (!cancelled) setStory(s);
        });
        return () => {
            cancelled = true;
        };
    }, [open, id, turn]);
    return story;
}

/** The Story popup keys on a RunRow; a turn that ran as an execution is one. */
function turnAsRun(turn: AgentTurn): RunRow {
    return {
        id: turn.executionId ?? '',
        workflow: turn.workflow,
        status: turn.status === 'error' ? 'error' : turn.status === 'awaiting' ? 'awaiting_approval' : 'completed',
        startedAt: turn.startedAt,
        durationMs: turn.durationMs,
        trigger: turn.trigger,
        nodesExecuted: 0,
    };
}

function ToolCallRow({ call }: { call: ToolCallSummary }) {
    const [open, setOpen] = useState(false);
    const inspectable = call.arguments != null || !!call.result || !!call.error;
    const returned = useMemo(() => {
        if (!call.result) return null;
        try {
            return JSON.parse(call.result) as unknown;
        } catch {
            return call.result;
        }
    }, [call.result]);
    return (
        <div>
            <div
                className={cn('flex items-center gap-2.5 px-3 py-2 text-[13px]', inspectable && 'cursor-pointer hover:bg-foreground/[0.03]')}
                {...clickableRow(inspectable ? () => setOpen((v) => !v) : undefined)}
            >
                {call.tool === 'execute_bash' ? <Terminal className="h-3.5 w-3.5 text-foreground/65 dark:text-foreground/45" /> : <NodeMark type={call.providerType} size="xs" />}
                <span className="text-foreground/80">{humanizeTool(call.tool)}</span>
                {call.detail && <span className="truncate text-foreground/60 dark:text-foreground/40">{call.detail}</span>}
                <span className="ml-auto flex shrink-0 items-center gap-2 tabular-nums text-[12px] text-foreground/55 dark:text-foreground/35">
                    {call.error && <span className="max-w-[280px] truncate text-red-600 dark:text-red-400">{call.error}</span>}
                    <span>{fmtDuration(call.durationMs)}</span>
                    <Verdict status={call.status === 'error' ? 'failed' : 'ok'} />
                    {inspectable && <ChevronRight className={cn('h-3.5 w-3.5 transition-transform', open && 'rotate-90')} />}
                </span>
            </div>
            {open && (
                <div className="space-y-3 border-t border-border dark:border-foreground/[0.06] bg-foreground/[0.02] px-3 py-3" role="presentation" onClick={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()}>
                    {call.arguments != null && <IODataDisplay data={call.arguments} label="Called with" />}
                    {call.error ? (
                        <div>
                            <p className="m-0 mb-1 text-[11px] font-semibold uppercase tracking-[0.1em] text-foreground/55 dark:text-foreground/35">Failed</p>
                            <pre className="m-0 whitespace-pre-wrap break-words rounded-md bg-red-500/[0.06] px-3 py-2 font-mono text-[12px] text-red-600 dark:text-red-400">{call.error}</pre>
                        </div>
                    ) : returned != null ? (
                        typeof returned === 'string' ? (
                            <div>
                                <p className="m-0 mb-1 text-[11px] font-semibold uppercase tracking-[0.1em] text-foreground/55 dark:text-foreground/35">Returned</p>
                                <pre className="m-0 max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-md bg-muted/50 px-3 py-2 text-[12px] leading-relaxed text-foreground/85">{returned}</pre>
                            </div>
                        ) : (
                            <IODataDisplay data={returned} label="Returned" />
                        )
                    ) : null}
                </div>
            )}
        </div>
    );
}

function RunningRow({ r, now }: { r: DashboardData['agents']['running'][number]; now: string }) {
    const { openWorkflow } = useDashboardActions();
    return (
        <button type="button" onClick={() => openWorkflow(r.workflow, r.agent.nodeId)} className={cn('-mx-2 flex w-[calc(100%+1rem)] items-center gap-3 rounded-lg px-2 py-2 text-left', ROW_HOVER)}>
            <NodeMark type={agentMarkType(r.agent.model)} size="md" />
            <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 text-[14px]">
                    <span className="shrink-0 whitespace-nowrap font-medium">{r.agent.label}</span>
                    <span className="truncate text-foreground/70 dark:text-foreground/50">{r.conversationTitle}</span>
                </div>
                <div className="mt-0.5 truncate text-[11px] text-foreground/60 dark:text-foreground/40">
                    {r.workflow.name} · {harnessLabel(r.agent.model)}
                </div>
            </div>
            <div className="flex shrink-0 items-center gap-2 whitespace-nowrap text-[11px] text-foreground/70 dark:text-foreground/50">
                {r.busy ? (
                    <>
                        <LiveDot /> working · {relTime(r.sinceIso, now).replace(' ago', '')}
                    </>
                ) : (
                    <>
                        <span className="h-2 w-2 rounded-full bg-foreground/25" /> idle · {relTime(r.sinceIso, now)}
                    </>
                )}
            </div>
        </button>
    );
}

function TurnCard({ turn, now, compact = false }: { turn: AgentTurn; now: string; compact?: boolean }) {
    const actions = useDashboardActions();
    const [open, setOpen] = useState(!compact);
    const failed = turn.status === 'error';
    const story = useTurnStory(turn, open);
    const storyIcons = useMemo(() => (story ? buildStoryIcons(story) : {}), [story]);
    const storySends = story?.agent?.sends ?? [];
    return (
        <div className={cn('-mx-2 rounded-lg px-2', ROW_HOVER)}>
            <button type="button" onClick={() => setOpen((v) => !v)} className="flex w-full items-start gap-3 py-2.5 text-left">
                <NodeMark type={agentMarkType(turn.agent.model)} size="md" className="mt-px" />
                <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 text-[14px]">
                        <span className="shrink-0 whitespace-nowrap font-medium">{turn.agent.label}</span>
                        <span className="truncate text-foreground/70 dark:text-foreground/50">{turn.conversationTitle}</span>
                    </div>
                    <p className={cn('m-0 mt-0.5 text-[13px] leading-relaxed', failed ? 'text-red-600 dark:text-red-400' : 'text-foreground/70', !open && 'line-clamp-1')}>
                        {failed ? turn.toolCalls.find((c) => c.error)?.error ?? 'Turn failed' : turn.response || 'No reply'}
                    </p>
                    <div className="mt-1 truncate text-[11px] text-foreground/60 dark:text-foreground/40">
                        {turn.workflow.name} · {turn.toolCalls.length} {turn.toolCalls.length === 1 ? 'tool call' : 'tool calls'} · {fmtDuration(turn.durationMs)}
                        {turn.credits != null && ` · ${fmtCredits(turn.credits)} cr`}
                    </div>
                </div>
                <div className="flex shrink-0 items-center gap-2 whitespace-nowrap text-[11px] tabular-nums text-foreground/60 dark:text-foreground/40">
                    <Verdict status={failed ? 'failed' : turn.status === 'awaiting' ? 'waiting' : 'ok'} />
                    <span title={dateLabel(turn.startedAt)}>{relTime(turn.startedAt, now)}</span>
                    <ChevronRight className={cn('h-3.5 w-3.5 transition-transform', open && 'rotate-90')} />
                </div>
            </button>
            {open && (
                <div className="ml-8 mb-3 space-y-3">
                    {story?.trigger ? (
                        <div>
                            <Eyebrow className="mb-1.5" right={<TriggerIdentity story={story} icons={storyIcons} />}>
                                What came in
                            </Eyebrow>
                            <InboundCard story={story} />
                        </div>
                    ) : (
                        turn.inbound && (
                            <div className="flex items-start gap-2 rounded-lg border border-border dark:border-foreground/[0.06] bg-foreground/[0.02] px-3 py-2 text-[12px]">
                                <NodeMark type={turn.inbound.provider} size="xs" className="mt-[3px]" />
                                <span className="min-w-0">
                                    {turn.inbound.from && <span className="mr-1.5 text-foreground/70 dark:text-foreground/50">{turn.inbound.from}</span>}
                                    <span className="text-foreground/80">{turn.inbound.text}</span>
                                </span>
                            </div>
                        )
                    )}
                    {storySends.length ? (
                        <div>
                            <Eyebrow className="mb-1.5">What went out ({storySends.length})</Eyebrow>
                            <div className="space-y-3">
                                {storySends.map((send, i) => (
                                    <SentFrame key={i} send={send} icons={storyIcons} agentName={story?.agentName} />
                                ))}
                            </div>
                        </div>
                    ) : (
                        <TurnSends turn={turn} />
                    )}
                    {turn.toolCalls.length > 0 && (
                        <div className={cn(ROWS, "rounded-lg border border-border dark:border-foreground/[0.06]")}>
                            {turn.toolCalls.map((c, i) => (
                                <ToolCallRow key={i} call={c} />
                            ))}
                        </div>
                    )}
                    <div className="flex gap-3 pt-1">
                        <TextLink onClick={() => actions.openConversation(turn)}>Open conversation</TextLink>
                        {turn.executionId && actions.openExecution && (
                            <TextLink onClick={() => actions.openExecution?.(turnAsRun(turn))}>Open run</TextLink>
                        )}
                    </div>
                </div>
            )}
        </div>
    );
}

export function AgentsCompact({ data, onFocus, turns = 1 }: SectionProps & { turns?: number }) {
    const { running } = data.agents;
    const recent = data.agents.turns.slice(0, turns);
    if (!running.length && !recent.length) return <EmptyState title="No agent has run yet" hint="Live sandboxes and each agent’s latest turn show up here." />;
    return (
        <div className="space-y-4">
            {running.length > 0 && (
                <div>
                    <Eyebrow className="mb-1">Up now</Eyebrow>
                    <div className={ROWS}>
                        {running.map((r) => (
                            <RunningRow key={`${r.workflow.id}-${r.agent.nodeId}-${r.conversationTitle}`} r={r} now={data.now} />
                        ))}
                    </div>
                </div>
            )}
            {recent.length > 0 && (
                <div>
                    <Eyebrow className="mb-1" right={<TextLink onClick={() => onFocus?.('agents')}>All turns</TextLink>}>
                        Last turn{turns > 1 ? 's' : ''}
                    </Eyebrow>
                    <div className={ROWS}>
                        {recent.map((t) => (
                            <TurnCard key={t.id} turn={t} now={data.now} compact />
                        ))}
                    </div>
                </div>
            )}
        </div>
    );
}

export function AgentsFull({ data }: SectionProps) {
    const { running, turns } = data.agents;
    const [only, setOnly] = useState<'all' | 'failed'>('all');
    const rows = only === 'all' ? turns : turns.filter((t) => t.status === 'error');
    return (
        <div className="space-y-8">
            <div>
                <Eyebrow className="mb-1">Up now</Eyebrow>
                {running.length ? (
                    <div className={ROWS}>
                        {running.map((r) => (
                            <RunningRow key={`${r.workflow.id}-${r.agent.nodeId}-${r.conversationTitle}`} r={r} now={data.now} />
                        ))}
                    </div>
                ) : (
                    <p className="m-0 py-2 text-[12.5px] text-foreground/60 dark:text-foreground/40">No sandbox is up. Warm sandboxes bill uptime, so idle is good.</p>
                )}
            </div>
            <div>
                <div className="mb-1 flex items-center">
                    <Eyebrow>Turns</Eyebrow>
                    <span className="ml-auto flex gap-1">
                        {(['all', 'failed'] as const).map((k) => (
                            <button key={k} type="button" onClick={() => setOnly(k)} className={cn('h-7 rounded-md px-2.5 text-[12px] transition-colors', only === k ? 'bg-foreground/[0.08] text-foreground' : 'text-foreground/70 dark:text-foreground/50 hover:text-foreground')}>
                                {k === 'all' ? 'All' : 'Failed'}
                            </button>
                        ))}
                    </span>
                </div>
                {rows.length ? (
                    <div className={ROWS}>
                        {rows.map((t) => (
                            <TurnCard key={t.id} turn={t} now={data.now} compact />
                        ))}
                    </div>
                ) : (
                    <EmptyState title="No turns" />
                )}
            </div>
        </div>
    );
}

// ---------------------------------------------------------------------------
// Files

const SOURCE_LABEL: Record<FileSourceKind, string> = {
    resources: 'Uploads & outputs',
    workspace: 'Agent workspaces',
    volume: 'Volumes',
    builder: 'Builder workspace',
};

const SOURCE_HINT: Record<FileSourceKind, string> = {
    resources: 'Files uploaded to a workflow or produced by its nodes — attachments, downloads, generated media.',
    workspace: 'Each agent conversation gets its own durable folder, mounted at /workspace in the sandbox.',
    volume: 'Named volumes wired into an agent through a Filesystem node; shared across its conversations.',
    builder: 'The scratch folder the AI builder uses to probe APIs while it designs — one per workspace.',
};

function FileGlyph({ kind, className }: { kind: FileKind; className?: string }) {
    const c = cn('h-4 w-4 shrink-0 text-foreground/65 dark:text-foreground/45', className);
    switch (kind) {
        case 'image':
            return <ImageIcon className={c} />;
        case 'video':
            return <Film className={c} />;
        case 'audio':
            return <Music className={c} />;
        case 'doc':
            return <FileText className={c} />;
        case 'data':
            return <Table2 className={c} />;
        case 'code':
            return <Code2 className={c} />;
        case 'archive':
            return <Archive className={c} />;
        default:
            return <File className={c} />;
    }
}

interface FlatFile extends FileEntry {
    source: FileSource;
}

function flattenFiles(sources: FileSource[]): FlatFile[] {
    return sources
        .flatMap((s) => s.files.map((f) => ({ ...f, source: s })))
        .sort((a, b) => Date.parse(b.mtime) - Date.parse(a.mtime));
}

function basename(path: string): string {
    const i = path.lastIndexOf('/');
    return i >= 0 ? path.slice(i + 1) : path;
}

/** A real thumbnail for images that already have a URL; the type glyph otherwise. */
function FileThumb({ file }: { file: FileEntry }) {
    const src = file.kind === 'image' || file.kind === 'video' ? (file.url ?? (file.urlPath ? workspaceFileUrl(file.urlPath) : null)) : null;
    if (src) {
        return (
            <span className="h-8 w-8 shrink-0 overflow-hidden rounded-md border border-border dark:border-foreground/[0.08] bg-foreground/[0.04]">
                {file.kind === 'video' ? (
                    // The first frame is the thumbnail; metadata-only, so no download.
                    <video src={src} muted playsInline preload="metadata" className="h-full w-full object-cover" />
                ) : (
                    <img src={src} alt="" loading="lazy" className="h-full w-full object-cover" />
                )}
            </span>
        );
    }
    return (
        <span className="grid h-8 w-8 shrink-0 place-items-center rounded-md border border-border dark:border-foreground/[0.06] bg-foreground/[0.03]">
            <FileGlyph kind={file.kind} />
        </span>
    );
}

function fileSizeLabel(file: FileEntry): string {
    if (file.rows != null) return `${compactNumber(file.rows)} rows`;
    return fmtBytes(file.size);
}

function FileRowView({ file, now, showSource = true, showDir = false, onDelete }: { file: FlatFile; now: string; showSource?: boolean; showDir?: boolean; onDelete?: () => Promise<void> }) {
    const { openFile } = useDashboardActions();
    // Deleting is a two-step inline confirm on the row itself — no modal.
    const [confirm, setConfirm] = useState<'idle' | 'asking' | 'deleting'>('idle');
    const dir = file.path.includes('/') ? file.path.slice(0, file.path.lastIndexOf('/') + 1) : '';
    const swallow = { role: 'presentation' as const, onClick: (e: SyntheticEvent) => e.stopPropagation(), onKeyDown: (e: SyntheticEvent) => e.stopPropagation() };
    return (
        <div {...clickableRow(() => openFile(file, file.source))} className={cn('group/file -mx-2 flex w-[calc(100%+1rem)] items-center gap-3 rounded-lg px-2 py-2 text-left', ROW_HOVER)}>
            <FileThumb file={file} />
            <span className="min-w-0 flex-1 truncate text-[13.5px]">
                {showDir && dir && <span className="text-foreground/55 dark:text-foreground/35">{dir}</span>}
                {basename(file.path)}
            </span>
            {showSource && (
                <span className="hidden min-w-0 max-w-[240px] shrink truncate text-[12px] text-foreground/60 dark:text-foreground/40 sm:inline">{file.source.label}</span>
            )}
            {confirm === 'idle' ? (
                <>
                    <span className="w-16 shrink-0 text-right text-[12px] tabular-nums text-foreground/60 dark:text-foreground/40">{fileSizeLabel(file)}</span>
                    <span className="w-14 shrink-0 text-right text-[12px] tabular-nums text-foreground/60 dark:text-foreground/40">{relTime(file.mtime, now)}</span>
                    {onDelete ? (
                        <span {...swallow} className="shrink-0">
                            <button
                                type="button"
                                aria-label={`Delete ${basename(file.path)}`}
                                onClick={() => setConfirm('asking')}
                                className="grid h-6 w-6 place-items-center rounded-md text-foreground/45 transition-colors hover:bg-foreground/[0.06] hover:text-red-600 dark:text-foreground/35 dark:hover:text-red-400"
                            >
                                <Trash2 className="h-3.5 w-3.5" />
                            </button>
                        </span>
                    ) : (
                        <ArrowUpRight className="h-3 w-3 shrink-0 text-foreground/0 transition-colors group-hover/file:text-foreground/70 dark:group-hover/file:text-foreground/50" />
                    )}
                </>
            ) : (
                <span {...swallow} className="flex shrink-0 items-center gap-3 text-[12px]">
                    {confirm === 'deleting' ? (
                        <span className="text-foreground/60 dark:text-foreground/40">Deleting…</span>
                    ) : (
                        <>
                            <span className="text-foreground/70 dark:text-foreground/50">Delete this file?</span>
                            <button
                                type="button"
                                onClick={() => {
                                    setConfirm('deleting');
                                    onDelete?.().finally(() => setConfirm('idle'));
                                }}
                                className="font-medium text-red-600 hover:underline dark:text-red-400"
                            >
                                Delete
                            </button>
                            <button type="button" onClick={() => setConfirm('idle')} className="text-foreground/70 dark:text-foreground/50 hover:text-foreground">
                                Keep
                            </button>
                        </>
                    )}
                </span>
            )}
        </div>
    );
}

export function FilesCompact({ data, onFocus, limit = 6, footer = true, narrow = false }: SectionProps & { limit?: number; footer?: boolean; narrow?: boolean }) {
    const all = flattenFiles(data.files);
    if (!all.length) return <EmptyState title="No files yet" hint="Uploads, agent workspaces, volumes and the builder’s scratch folder all show up here." />;
    const totalBytes = all.reduce((a, f) => a + f.size, 0);
    return (
        <div>
            <div className={ROWS}>
                {all.slice(0, limit).map((f) => (
                    <FileRowView key={`${f.source.id}:${f.path}`} file={f} now={data.now} showSource={!narrow} />
                ))}
            </div>
            <div className="flex items-center justify-between pt-2 text-[11px] text-foreground/55 dark:text-foreground/35">
                {footer ? (
                    <span>
                        {all.length} files · {fmtBytes(totalBytes)} across {data.files.length} places
                    </span>
                ) : (
                    <span />
                )}
                {all.length > limit && <TextLink onClick={() => onFocus?.('files')}>{all.length - limit} more</TextLink>}
            </div>
        </div>
    );
}

export function FilesFull({ data }: SectionProps) {
    const actions = useDashboardActions();
    const [facet, setFacet] = useState<'all' | FileSourceKind>('all');
    const [query, setQuery] = useState('');
    // Folded places stay folded for the session, so a long list is scanned once.
    const [collapsed, setCollapsed] = useValtioState<string[]>('dashboard', 'files_collapsed', []);
    const toggle = (id: string) => setCollapsed(collapsed.includes(id) ? collapsed.filter((x) => x !== id) : [...collapsed, id]);
    const kinds: FileSourceKind[] = ['resources', 'workspace', 'volume', 'builder'];
    const sources = data.files.filter((s) => (facet === 'all' ? true : s.kind === facet));
    const q = query.trim().toLowerCase();
    const bytes = (ss: FileSource[]) => ss.reduce((a, s) => a + s.files.reduce((b, f) => b + f.size, 0), 0);
    const count = (ss: FileSource[]) => ss.reduce((a, s) => a + s.files.length, 0);
    const facetBtn = (key: 'all' | FileSourceKind, label: string, ss: FileSource[]) => (
        <button
            key={key}
            type="button"
            onClick={() => setFacet(key)}
            className={cn('flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-[12.5px] transition-colors', facet === key ? 'bg-foreground/[0.08] text-foreground' : 'text-foreground/70 dark:text-foreground/55 hover:text-foreground')}
        >
            <span className="flex-1 truncate">{label}</span>
            <span className="tabular-nums text-foreground/55 dark:text-foreground/35">{count(ss)}</span>
        </button>
    );
    return (
        <div className="grid gap-8 md:grid-cols-[200px_1fr]">
            <aside className="space-y-4">
                <div className="space-y-0.5">
                    {facetBtn('all', 'All files', data.files)}
                    {kinds.map((k) => facetBtn(k, SOURCE_LABEL[k], data.files.filter((s) => s.kind === k)))}
                </div>
                <p className="m-0 px-2.5 text-[11px] leading-relaxed text-foreground/55 dark:text-foreground/35">
                    {facet === 'all' ? `${count(data.files)} files · ${fmtBytes(bytes(data.files))}` : SOURCE_HINT[facet]}
                </p>
            </aside>
            <div className="min-w-0 space-y-6">
                <input
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder="Filter by name"
                    className="w-full rounded-md border border-border dark:border-foreground/10 bg-transparent px-3 py-1.5 text-[12.5px] outline-none placeholder:text-foreground/45 dark:placeholder:text-foreground/30 focus:border-foreground/30"
                />
                {sources.length === 0 && <EmptyState title="Nothing here yet" hint={facet !== 'all' ? SOURCE_HINT[facet] : undefined} />}
                {sources.map((s) => {
                    const files = s.files.filter((f) => !q || f.path.toLowerCase().includes(q));
                    if (q && !files.length) return null;
                    if (s.kind === 'workspace' && !s.files.length) return null;
                    const folded = collapsed.includes(s.id) && !q;
                    return (
                        <section key={s.id}>
                            <div className="mb-1 flex items-center gap-2">
                                <button
                                    type="button"
                                    onClick={() => toggle(s.id)}
                                    aria-expanded={!folded}
                                    aria-label={folded ? `Expand ${s.label}` : `Collapse ${s.label}`}
                                    className="-ml-1 grid h-5 w-5 shrink-0 place-items-center rounded text-foreground/45 transition-colors hover:bg-foreground/[0.06] hover:text-foreground dark:text-foreground/35"
                                >
                                    <ChevronDown className={cn('h-3.5 w-3.5 transition-transform', folded && '-rotate-90')} />
                                </button>
                                {s.workflow ? <MarkRow types={s.workflow.marks} size="xs" max={3} /> : s.agent ? <NodeMark type={agentMarkType(s.agent.model)} size="xs" /> : null}
                                {s.workflow ? (
                                    <button
                                        type="button"
                                        onClick={() => actions.openWorkflow(s.workflow!, s.agent?.nodeId)}
                                        className="min-w-0 truncate text-left text-[14px] font-medium decoration-foreground/30 underline-offset-4 hover:underline"
                                    >
                                        {s.label}
                                    </button>
                                ) : (
                                    <span className="min-w-0 truncate text-[14px] font-medium">{s.label}</span>
                                )}
                                <span className="hidden shrink-0 text-[12px] text-foreground/60 dark:text-foreground/40 md:inline">{s.sublabel}</span>
                                <span className="ml-auto flex shrink-0 items-center gap-3 text-[11px] text-foreground/55 dark:text-foreground/35">
                                    <span className="tabular-nums">
                                        {s.files.length} · {fmtBytes(s.files.reduce((a, f) => a + f.size, 0))}
                                    </span>
                                    {s.writable && actions.uploadTo && (
                                        <TextLink onClick={() => actions.uploadTo?.(s)} icon={false}>
                                            Upload
                                        </TextLink>
                                    )}
                                </span>
                            </div>
                            {folded ? null : files.length ? (
                                <div className={cn(ROWS, "border-t border-border dark:border-foreground/[0.06]")}>
                                    {files.map((f) => (
                                        <FileRowView
                                            key={f.path}
                                            file={{ ...f, source: s }}
                                            now={data.now}
                                            showSource={false}
                                            showDir
                                            onDelete={s.writable && actions.deleteFile ? () => actions.deleteFile!(f, s) : undefined}
                                        />
                                    ))}
                                </div>
                            ) : (
                                <p className="m-0 border-t border-border dark:border-foreground/[0.06] py-3 text-[12px] text-foreground/55 dark:text-foreground/35">Empty.</p>
                            )}
                            {s.truncated && <p className="m-0 pt-1.5 text-[11px] text-foreground/55 dark:text-foreground/35">Showing the first entries · the volume has more.</p>}
                        </section>
                    );
                })}
                {(() => {
                    const empty = sources.filter((s) => s.kind === 'workspace' && !s.files.length).length;
                    return empty > 0 ? (
                        <p className="m-0 text-[12px] text-foreground/55 dark:text-foreground/35">
                            {empty} agent {empty === 1 ? 'workspace is' : 'workspaces are'} empty — agents save into them only when asked to.
                        </p>
                    ) : null;
                })()}
            </div>
        </div>
    );
}

// ---------------------------------------------------------------------------
// Credentials

function credentialVerdict(c: CredentialEntry): VerdictStatus {
    return c.health === 'ok' ? 'ok' : c.health === 'unknown' ? 'idle' : 'failed';
}

const ACCESS_LABEL: Record<CredentialEntry['access'], string> = { owner: 'Yours', shared: 'Shared with you', shared_org: 'Workspace' };

function CredentialRowView({ c, now }: { c: CredentialEntry; now: string }) {
    const actions = useDashboardActions();
    const dead = c.health === 'disconnected' || c.health === 'revoked';
    return (
        <div className={cn('-mx-2 flex items-center gap-3 rounded-lg px-2 py-2', ROW_HOVER)}>
            <CredentialMark credentialType={c.credentialType} nodeType={c.nodeType} size="md" />
            <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 text-[14px]">
                    <span className="truncate">{c.name}</span>
                    <span className="shrink-0 text-[11.5px] text-foreground/55 dark:text-foreground/35">{credentialLabel(c.credentialType, c.nodeType)}</span>
                    {c.access !== 'owner' && <KindPill>{ACCESS_LABEL[c.access]}</KindPill>}
                </div>
                <div className="mt-0.5 flex items-center gap-2 text-[11px] text-foreground/60 dark:text-foreground/40">
                    {dead ? (
                        <span className="text-red-600 dark:text-red-400">{c.healthDetail}</span>
                    ) : c.lastRefreshAt ? (
                        <span>refreshed {relTime(c.lastRefreshAt, now)}</span>
                    ) : (
                        <span>added {relTime(c.createdAt, now)}</span>
                    )}
                    {c.recurringPerHour != null && <span>· {c.recurringPerHour} cr/h</span>}
                    {c.usedBy.length > 0 && (
                        <span className="inline-flex min-w-0 items-center gap-1 truncate">
                            · used by {c.usedBy.map((w) => w.name).join(', ')}
                        </span>
                    )}
                    {c.usedBy.length === 0 && <span>· not used yet</span>}
                </div>
            </div>
            <div className="flex shrink-0 items-center gap-2">
                {dead ? (
                    <PrimaryButton onClick={() => actions.reconnectCredential({ credentialId: c.id, credentialType: c.credentialType, name: c.name })}>Reconnect</PrimaryButton>
                ) : (
                    <>
                        <TextLink onClick={() => actions.manageCredential(c)} icon={false}>
                            Manage
                        </TextLink>
                        {actions.deleteCredential && (
                            <TextLink onClick={() => actions.deleteCredential?.(c)} icon={false} className="text-red-600 hover:text-red-700 dark:text-red-400 dark:hover:text-red-300">
                                Delete
                            </TextLink>
                        )}
                    </>
                )}
                <Verdict status={credentialVerdict(c)} className="w-4" label={c.health} />
            </div>
        </div>
    );
}

export function CredentialsCompact({ data, onFocus, style = 'tiles', footer = true }: SectionProps & { style?: 'tiles' | 'rows'; footer?: boolean }) {
    const actions = useDashboardActions();
    const creds = data.credentials;
    if (!creds.length) return <EmptyState title="No accounts connected" hint="Every service you connect shows up here with its health." />;
    const dead = creds.filter((c) => c.health === 'disconnected' || c.health === 'revoked');
    const sorted = [...dead, ...creds.filter((c) => !dead.includes(c))];
    if (style === 'rows') {
        return (
            <div>
                <div className={ROWS}>
                    {sorted.slice(0, 5).map((c) => (
                        <CredentialRowView key={c.id} c={c} now={data.now} />
                    ))}
                </div>
                {creds.length > 5 && (
                    <div className="pt-2">
                        <TextLink onClick={() => onFocus?.('credentials')}>{creds.length - 5} more</TextLink>
                    </div>
                )}
            </div>
        );
    }
    return (
        <div>
            <div className="flex flex-wrap gap-1.5">
                {sorted.map((c) => {
                    const isDead = dead.includes(c);
                    return (
                        <span key={c.id} className="group/cred relative inline-flex">
                            <button
                                type="button"
                                onClick={() => (isDead ? actions.reconnectCredential({ credentialId: c.id, credentialType: c.credentialType, name: c.name }) : actions.manageCredential(c))}
                                title={`${c.name} · ${credentialLabel(c.credentialType, c.nodeType)}${isDead ? ` · ${c.healthDetail}` : ''}`}
                                className={cn(
                                    'inline-flex h-8 items-center gap-2 rounded-md border px-2 text-[12px] transition-colors',
                                    isDead ? 'border-red-500/30 text-foreground hover:bg-red-500/[0.06]' : 'border-border dark:border-foreground/[0.08] text-foreground/70 hover:border-foreground/20 hover:text-foreground'
                                )}
                            >
                                <CredentialMark credentialType={c.credentialType} nodeType={c.nodeType} size="sm" />
                                <span className="max-w-[140px] truncate">{c.name}</span>
                                {isDead && <X className="h-3 w-3 text-red-600 dark:text-red-400" strokeWidth={2.5} />}
                            </button>
                            {actions.deleteCredential && (
                                <button
                                    type="button"
                                    aria-label={`Delete ${c.name}`}
                                    title="Delete credential"
                                    onClick={() => actions.deleteCredential?.(c)}
                                    className="absolute right-[3px] top-1/2 grid h-[24px] w-[26px] -translate-y-1/2 place-items-center rounded bg-[var(--surface)] text-foreground/55 opacity-0 shadow-[-10px_0_8px_-4px_var(--surface)] transition-opacity hover:text-red-600 focus-visible:opacity-100 group-hover/cred:opacity-100 dark:text-foreground/45 dark:hover:text-red-400"
                                >
                                    <Trash2 className="h-3.5 w-3.5" />
                                </button>
                            )}
                        </span>
                    );
                })}
            </div>
            {footer && (
                <div className="flex items-center justify-between pt-2.5 text-[11px] text-foreground/55 dark:text-foreground/35">
                    <span>
                        {creds.length} connected
                        {dead.length > 0 && (
                            <>
                                {' · '}
                                <span className="text-red-600 dark:text-red-400">{dead.length} need attention</span>
                            </>
                        )}
                    </span>
                    <TextLink onClick={() => onFocus?.('credentials')}>Manage</TextLink>
                </div>
            )}
        </div>
    );
}

/** The drill-down for credentials is Settings → Credentials itself (the
 *  product mounts that component here); this stands in wherever it can't. */
export function CredentialsFull({ onFocus }: SectionProps) {
    return <SettingsHandoff title="Credentials" section="credentials" onFocus={onFocus} />;
}

function SettingsHandoff({ title, section, onFocus }: { title: string; section: string; onFocus?: SectionProps['onFocus'] }) {
    const actions = useDashboardActions();
    return (
        <div className="flex flex-col items-start gap-3 py-6">
            <p className="m-0 inline-flex items-center gap-2 text-[14px] text-foreground/70">
                <Settings2 className="h-4 w-4 text-foreground/65 dark:text-foreground/45" /> {title} live in Settings — the same view opens here.
            </p>
            <PrimaryButton onClick={() => (section === 'credentials' ? actions.openCredentialsSettings : actions.openUsage)()}>Open Settings → {title}</PrimaryButton>
            {onFocus && <TextLink onClick={() => onFocus(null as unknown as FocusId)} icon={false}>Back</TextLink>}
        </div>
    );
}

// ---------------------------------------------------------------------------
// Triggers

function TriggerRowView({ t, now }: { t: TriggerEntry; now: string }) {
    const { openWorkflow } = useDashboardActions();
    return (
        <div className={cn('-mx-2 flex items-center gap-3 rounded-lg px-2 py-2', ROW_HOVER)}>
            <NodeMark type={t.nodeType} size="md" />
            <div className="min-w-0 flex-1">
                <div className="flex min-w-0 items-center gap-2 text-[14px]">
                    <span className="shrink-0 whitespace-nowrap">{t.label}</span>
                    <WorkflowLine workflow={t.workflow} className="min-w-0 shrink" showMarks={false} />
                </div>
                <div className={cn('mt-0.5 truncate text-[11px]', t.armed ? 'text-foreground/60 dark:text-foreground/40' : 'text-red-600 dark:text-red-400')}>
                    {t.armed
                        ? [t.schedule, t.nextRunAt ? `next ${relTime(t.nextRunAt, now)}` : null, t.lastFiredAt ? `last ${relTime(t.lastFiredAt, now)}` : 'never fired', `${compactNumber(t.fireCount)} runs`].filter(Boolean).join(' · ')
                        : t.error}
                </div>
            </div>
            <div className="flex shrink-0 items-center gap-2">
                {!t.armed && <PrimaryButton onClick={() => openWorkflow(t.workflow, t.nodeId)}>Fix</PrimaryButton>}
                {t.armed && <TextLink onClick={() => openWorkflow(t.workflow, t.nodeId)} icon={false}>Open</TextLink>}
                <Verdict status={t.armed ? 'ok' : 'failed'} className="w-4" label={t.armed ? 'Armed' : 'Not registered'} />
            </div>
        </div>
    );
}

export function TriggersCompact({ data, onFocus, stats = true }: SectionProps & { stats?: boolean }) {
    const { triggers } = data;
    if (!triggers.length) return <EmptyState title="No triggers" hint="Schedules, webhooks and app events that wake your workflows." />;
    const broken = triggers.filter((t) => !t.armed);
    const next = triggers.filter((t) => t.armed && t.nextRunAt).sort((a, b) => Date.parse(a.nextRunAt!) - Date.parse(b.nextRunAt!))[0];
    return (
        <div>
            <div className={cn('mb-2 flex items-baseline gap-4 text-[12px] text-foreground/70 dark:text-foreground/50', !stats && 'hidden')}>
                <span>
                    <span className="text-[15px] font-semibold tabular-nums text-foreground">{triggers.length - broken.length}</span> armed
                </span>
                {broken.length > 0 && (
                    <span>
                        <span className="text-[15px] font-semibold tabular-nums text-red-600 dark:text-red-400">{broken.length}</span> broken
                    </span>
                )}
                {next && (
                    <span className="ml-auto truncate">
                        next: {next.workflow.name} {relTime(next.nextRunAt!, data.now)}
                    </span>
                )}
            </div>
            <div className={ROWS}>
                {[...broken, ...triggers.filter((t) => t.armed)].slice(0, 4).map((t) => (
                    <TriggerRowView key={t.id} t={t} now={data.now} />
                ))}
            </div>
            {triggers.length > 4 && (
                <div className="pt-2">
                    <TextLink onClick={() => onFocus?.('triggers')}>{triggers.length - 4} more</TextLink>
                </div>
            )}
        </div>
    );
}

export function TriggersFull({ data }: SectionProps) {
    const broken = data.triggers.filter((t) => !t.armed);
    const armed = data.triggers.filter((t) => t.armed);
    return (
        <div className="space-y-8">
            {broken.length > 0 && (
                <div>
                    <Eyebrow className="mb-1">Broken</Eyebrow>
                    <div className={ROWS}>
                        {broken.map((t) => (
                            <TriggerRowView key={t.id} t={t} now={data.now} />
                        ))}
                    </div>
                </div>
            )}
            <div>
                <Eyebrow className="mb-1">Armed</Eyebrow>
                {armed.length ? (
                    <div className={ROWS}>
                        {armed.map((t) => (
                            <TriggerRowView key={t.id} t={t} now={data.now} />
                        ))}
                    </div>
                ) : (
                    <EmptyState title="No triggers" />
                )}
            </div>
        </div>
    );
}

// ---------------------------------------------------------------------------
// Credits

export function CreditsCompact({ data, onFocus }: SectionProps) {
    const { credits } = data;
    const pct = credits.cap ? credits.used / credits.cap : 0;
    return (
        <div>
            <div className="flex items-baseline justify-between">
                <span className="text-[22px] font-semibold tracking-tight">
                    {fmtCredits(credits.used)}
                    <span className="text-[13px] font-normal text-foreground/60 dark:text-foreground/40"> / {compactNumber(credits.cap)}</span>
                </span>
                <span className="text-[11px] text-foreground/60 dark:text-foreground/40">
                    resets {relTime(credits.nextRefreshAt, data.now)}
                    {credits.topup > 0 && ` · ${compactNumber(credits.topup)} top-up in reserve`}
                </span>
            </div>
            <Meter value={credits.used} max={credits.cap} className="mt-2" />
            <div className="mt-2 flex items-center justify-between gap-3 text-[11px] text-foreground/60 dark:text-foreground/40">
                <span className="shrink-0">{Math.round(pct * 100)}% of this {credits.period === 'month' ? 'month' : 'day'}’s {credits.tier} credits</span>
                {credits.topSpenders[0] && (
                    <button type="button" onClick={() => onFocus?.('credits')} className="min-w-0 truncate text-left transition-colors hover:text-foreground">
                        top: {credits.topSpenders[0].workflow.name} · {compactNumber(credits.topSpenders[0].credits)}
                    </button>
                )}
            </div>
        </div>
    );
}

/** The drill-down for credits is Settings → Usage itself (mounted by the product). */
export function CreditsFull({ onFocus }: SectionProps) {
    return <SettingsHandoff title="Usage" section="usage" onFocus={onFocus} />;
}

// ---------------------------------------------------------------------------
// Notifications

function NotificationRow({ n, now }: { n: NotificationEntry; now: string }) {
    const { openNotification } = useDashboardActions();
    const unread = !n.readAt;
    return (
        <button type="button" onClick={() => openNotification(n)} className={cn('-mx-2 flex w-[calc(100%+1rem)] items-start gap-3 rounded-lg px-2 py-2 text-left', ROW_HOVER)}>
            <span className="mt-[7px] flex w-2 shrink-0 justify-center">{unread && <span className="h-1.5 w-1.5 rounded-full bg-foreground" />}</span>
            <div className="min-w-0 flex-1">
                <div className={cn('text-[14px]', unread ? 'text-foreground' : 'text-foreground/75 dark:text-foreground/60')}>
                    {n.title}
                    {n.suppressedCount > 0 && <span className="ml-2 text-[11px] text-foreground/55 dark:text-foreground/35">+{n.suppressedCount} more</span>}
                </div>
                <p className="m-0 mt-0.5 line-clamp-2 text-[12px] text-foreground/65 dark:text-foreground/45">{n.body}</p>
            </div>
            <span className="shrink-0 text-[11px] tabular-nums text-foreground/55 dark:text-foreground/35">{relTime(n.createdAt, now)}</span>
        </button>
    );
}

export function NotificationsCompact({ data, onFocus, limit = 3 }: SectionProps & { limit?: number }) {
    if (!data.notifications.length) return <EmptyState title="No notifications" hint="Failures, credit alerts and your weekly digest." />;
    return (
        <div>
            <div className={ROWS}>
                {data.notifications.slice(0, limit).map((n) => (
                    <NotificationRow key={n.id} n={n} now={data.now} />
                ))}
            </div>
            {data.notifications.length > limit && (
                <div className="pt-2">
                    <TextLink onClick={() => onFocus?.('notifications')}>{data.notifications.length - limit} more</TextLink>
                </div>
            )}
        </div>
    );
}

export function NotificationsFull({ data }: SectionProps) {
    const actions = useDashboardActions();
    return (
        <div>
            <div className="mb-2 flex items-center justify-between">
                <span className="text-[12px] text-foreground/65 dark:text-foreground/45">{data.notifications.filter((n) => !n.readAt).length} unread</span>
                <span className="flex gap-3">
                    <TextLink onClick={() => actions.markNotificationsRead()} icon={false}>
                        Mark all read
                    </TextLink>
                    <TextLink onClick={() => actions.openPreferences()} icon={false}>
                        <Bell className="h-3 w-3" /> Preferences
                    </TextLink>
                </span>
            </div>
            {data.notifications.length ? (
                <div className={ROWS}>
                    {data.notifications.map((n) => (
                        <NotificationRow key={n.id} n={n} now={data.now} />
                    ))}
                </div>
            ) : (
                <EmptyState title="No notifications" />
            )}
        </div>
    );
}

// ---------------------------------------------------------------------------

export const FULL_VIEWS: Record<FocusId, (p: SectionProps) => ReactElement> = {
    attention: AttentionFull,
    runs: RunsFull,
    agents: AgentsFull,
    files: FilesFull,
    credentials: CredentialsFull,
    triggers: TriggersFull,
    upcoming: UpcomingFull,
    credits: CreditsFull,
    notifications: NotificationsFull,
};

export function focusCount(data: DashboardData, id: FocusId, attention: AttentionItem[]): number | undefined {
    switch (id) {
        case 'attention':
            return attention.length;
        case 'runs':
            return data.runs.days.reduce((a, b) => a + b.ok + b.failed, 0);
        case 'agents':
            return data.agents.running.length;
        case 'files':
            return data.files.reduce((a, s) => a + s.files.length, 0);
        case 'credentials':
            return data.credentials.length;
        case 'triggers':
            return data.triggers.length;
        case 'upcoming':
            return data.upcoming.filter((u) => u.at).length;
        case 'notifications':
            return data.notifications.filter((n) => !n.readAt).length;
        default:
            return undefined;
    }
}

export { SectionHeader, clockLabel };
