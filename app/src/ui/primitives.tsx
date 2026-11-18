// Shared building blocks: marks, eyebrows, section headers, pills, stat tiles,
// sparklines and the small formatters. Black/zinc/white by design — brand marks
// are the only colour, red is reserved for failure, and a succeeded thing gets a
// zinc check, never a green one.
import React, { type ReactNode } from 'react';
import { ArrowUpRight, Box, Check, Circle, X } from 'lucide-react';
import { cn } from '@/ui/utils';
import { getNodeIconMeta } from '@/lib/nodeIconRegistry';
import { SerializedIcon } from '@/ui/SerializedIcon';

import { HAIRLINE, ROW_HOVER, SURFACE } from '@/ui/surfaces';

export { HAIRLINE, ROW_HOVER, SURFACE };

/** Props that make a clickable row a real control: role, tab stop, Enter/Space. */
export function clickableRow(onActivate?: () => void) {
    if (!onActivate) return {};
    return {
        role: 'button' as const,
        tabIndex: 0,
        onClick: onActivate,
        onKeyDown: (e: React.KeyboardEvent) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                onActivate();
            }
        },
    };
}

/** Hairlines between stacked rows. Drawn as a pseudo-element line rather than
 *  `divide-y`, whose line is the row's own top border and so bends around the
 *  row's rounded hover corners. */
export const ROWS =
    "[&>*+*]:relative [&>*+*]:before:pointer-events-none [&>*+*]:before:absolute [&>*+*]:before:inset-x-0 [&>*+*]:before:top-0 [&>*+*]:before:h-px [&>*+*]:before:bg-border [&>*+*]:before:content-[''] dark:[&>*+*]:before:bg-foreground/[0.06]";

/** Page and grid rhythm, shared by a grid of cards and its loading skeleton so
 *  the placeholder can never drift from the real page. */
export const LAYOUT = {
    pageMaxWidth: 1400,
    pagePad: 'px-4 py-5 sm:px-7 sm:py-6',
    gridGap: 'gap-3 sm:gap-[18px]',
    cardPad: 'p-4 sm:p-[18px]',
    // Cells draw their own right/bottom hairlines; the grid's -1px margins tuck
    // the outer ones under the card's border, so the ledger can wrap on phones.
    // Five cells: pairs on a narrow screen with the last one across, one row wide.
    ledgerGrid: 'grid -mb-px -mr-px grid-cols-2 lg:grid-cols-5 [&>*:last-child]:col-span-2 lg:[&>*:last-child]:col-span-1',
    ledgerCell: 'border-b border-r border-border px-4 py-3.5 dark:border-foreground/[0.06] sm:px-5 sm:py-4',
    greetingGap: 'mb-5',
    ledgerGap: 'mb-4',
} as const;

// ---------------------------------------------------------------------------
// Formatters

export { clockLabel, compactNumber, countOf, dateLabel, fmtBytes, fmtDuration, relTime } from '@/lib/formatters';

export function harnessLabel(model: string): string {
    switch (model) {
        case 'claude-code':
            return 'Claude Code';
        case 'codex':
            return 'Codex';
        case 'opencode':
            return 'OpenCode';
        case 'openclaw':
            return 'OpenClaw';
        default:
            return model.includes('hermes') ? 'Hermes' : model;
    }
}

export function agentMarkType(model: string): string {
    const kinds = ['claude-code', 'codex', 'opencode', 'openclaw'];
    if (kinds.includes(model)) return `agent:${model}`;
    if (model.includes('hermes')) return 'agent:hermes';
    return 'agent';
}

// ---------------------------------------------------------------------------
// Marks

export const MARK_SIZE = { xs: 'h-3.5 w-3.5', sm: 'h-4 w-4', md: 'h-5 w-5', lg: 'h-7 w-7' } as const;
export type MarkSize = keyof typeof MARK_SIZE;

/** A node's brand mark from the serialized catalog; a quiet cube when unknown. */
export function NodeMark({
    type,
    size = 'sm',
    className,
    title,
}: {
    type: string;
    size?: MarkSize;
    className?: string;
    title?: string;
}) {
    const meta = getNodeIconMeta(type);
    if (!meta?.iconHtml) {
        return <Box className={cn(MARK_SIZE[size], 'shrink-0 text-foreground/60 dark:text-foreground/40', className)} aria-label={title} />;
    }
    return (
        <span className={cn('inline-flex shrink-0 items-center justify-center', MARK_SIZE[size], className)} title={title ?? meta.label}>
            <SerializedIcon html={meta.iconHtml} iconColor={meta.iconColor} className="h-full w-full" />
        </span>
    );
}

export function nodeLabel(type: string): string {
    return getNodeIconMeta(type)?.label ?? type;
}

/** The marks that identify a workflow, in a tight row with +N overflow. */
export function MarkRow({ types, size = 'sm', max = 4, className, hideRest = false }: { types: string[]; size?: MarkSize; max?: number; className?: string; hideRest?: boolean }) {
    const shown = types.slice(0, max);
    const rest = types.length - shown.length;
    return (
        <span className={cn('inline-flex items-center gap-1.5', className)}>
            {shown.map((t, i) => (
                <NodeMark key={`${t}-${i}`} type={t} size={size} />
            ))}
            {rest > 0 && !hideRest && <span className="text-[10.5px] tabular-nums text-foreground/60 dark:text-foreground/40">+{rest}</span>}
        </span>
    );
}

// ---------------------------------------------------------------------------
// Typography + chrome

export function Eyebrow({ children, right, className }: { children: ReactNode; right?: ReactNode; className?: string }) {
    return (
        <div className={cn('flex items-center justify-between gap-3', className)}>
            <span className="text-[11px] font-semibold uppercase tracking-[0.1em] text-foreground/55 dark:text-foreground/35">{children}</span>
            {right}
        </div>
    );
}

/** A labelled text link — the configured affordance style (no border, no box). */
/** A visible but quiet control: the same borderless fill as the active filter
 *  chip and the navbar tab. For navigation that must be findable (the
 *  drill-down's way back) without competing with the page's primary actions. */
export function SoftButton({ children, onClick, className }: { children: ReactNode; onClick?: () => void; className?: string }) {
    return (
        <button
            type="button"
            onClick={onClick}
            className={cn(
                'inline-flex h-8 items-center gap-1.5 rounded-md bg-foreground/[0.07] px-3 text-[12.5px] font-medium text-foreground transition-colors hover:bg-foreground/[0.12]',
                className
            )}
        >
            {children}
        </button>
    );
}

export function TextLink({ children, onClick, className, icon = true }: { children: ReactNode; onClick?: () => void; className?: string; icon?: boolean }) {
    return (
        <button
            type="button"
            onClick={onClick}
            className={cn(
                'inline-flex items-center gap-1 text-[11.5px] text-foreground/65 dark:text-foreground/45 transition-colors hover:text-foreground',
                className
            )}
        >
            {children}
            {icon && <ArrowUpRight className="h-3 w-3" />}
        </button>
    );
}

/** Section title row: name, optional count, and the drill-down link. */
export function SectionHeader({
    title,
    count,
    meta,
    onOpen,
    openLabel = 'See all',
    className,
    as = 'eyebrow',
}: {
    title: string;
    count?: number;
    meta?: ReactNode;
    onOpen?: () => void;
    openLabel?: string;
    className?: string;
    as?: 'eyebrow' | 'title';
}) {
    return (
        <div className={cn('flex items-baseline justify-between gap-3', className)}>
            <div className="flex min-w-0 items-baseline gap-2">
                {as === 'eyebrow' ? (
                    <span className="text-[11px] font-semibold uppercase tracking-[0.1em] text-foreground/55 dark:text-foreground/35">{title}</span>
                ) : (
                    <span className="text-[15px] font-semibold tracking-tight text-foreground">{title}</span>
                )}
                {count != null && count > 0 && (
                    <span className={cn('tabular-nums text-foreground/55 dark:text-foreground/40', as === 'title' ? 'text-[13px]' : 'text-[11px]')}>{count}</span>
                )}
                {meta && <span className="truncate text-[11px] text-foreground/55 dark:text-foreground/35">{meta}</span>}
            </div>
            {onOpen && <TextLink onClick={onOpen}>{openLabel}</TextLink>}
        </div>
    );
}

export function KindPill({ children, tone = 'neutral', className }: { children: ReactNode; tone?: 'neutral' | 'failure' | 'live'; className?: string }) {
    return (
        <span
            className={cn(
                'inline-flex items-center gap-1 rounded-md px-1.5 py-[1px] text-[10.5px] font-medium',
                tone === 'failure'
                    ? 'bg-red-500/10 text-red-600 dark:text-red-400'
                    : tone === 'live'
                      ? 'bg-foreground/[0.08] text-foreground'
                      : 'bg-foreground/[0.06] text-foreground/75 dark:text-foreground/60',
                className
            )}
        >
            {children}
        </span>
    );
}

export function EmptyState({ title, hint, className }: { title: string; hint?: string; className?: string }) {
    return (
        <div className={cn('py-8 text-center', className)}>
            <p className="m-0 text-[13px] text-foreground/75 dark:text-foreground/60">{title}</p>
            {hint && <p className="m-0 mt-1 text-[11.5px] text-foreground/55 dark:text-foreground/35">{hint}</p>}
        </div>
    );
}

// ---------------------------------------------------------------------------
// Status

export type VerdictStatus = 'ok' | 'failed' | 'running' | 'waiting' | 'idle';

/** The verdict glyph: zinc check, red cross, a live dot, a hollow circle. */
export function Verdict({ status, className, label }: { status: VerdictStatus; className?: string; label?: string }) {
    const base = cn('inline-flex shrink-0 items-center justify-center', className);
    let glyph: ReactNode;
    switch (status) {
        case 'ok':
            glyph = <Check className="h-3.5 w-3.5 text-foreground/70 dark:text-foreground/50" strokeWidth={2.25} />;
            break;
        case 'failed':
            glyph = <X className="h-3.5 w-3.5 text-red-600 dark:text-red-400" strokeWidth={2.25} />;
            break;
        case 'running':
            glyph = <LiveDot />;
            break;
        case 'waiting':
            glyph = <Circle className="h-3 w-3 text-foreground/70" strokeWidth={2} />;
            break;
        default:
            glyph = <Circle className="h-2.5 w-2.5 text-foreground/40 dark:text-foreground/25" strokeWidth={2} />;
    }
    return (
        <span className={base} title={label}>
            {glyph}
        </span>
    );
}

export function LiveDot({ className }: { className?: string }) {
    return (
        <span className={cn('relative inline-flex h-2.5 w-2.5', className)}>
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-foreground/40" />
            <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-foreground" />
        </span>
    );
}

// ---------------------------------------------------------------------------
// Figures

/** Stat tile: label · value · optional delta · optional 14-point sparkline. */
export function StatTile({
    label,
    value,
    delta,
    trend,
    tone = 'neutral',
    onClick,
    className,
    hero = false,
}: {
    label: string;
    value: string;
    delta?: { text: string; good?: boolean };
    trend?: number[];
    tone?: 'neutral' | 'failure' | 'attention';
    onClick?: () => void;
    className?: string;
    hero?: boolean;
}) {
    const Tag = onClick ? 'button' : 'div';
    return (
        <Tag
            type={onClick ? 'button' : undefined}
            onClick={onClick}
            className={cn(
                'flex min-w-0 flex-col items-start gap-1 text-left',
                onClick && 'group/stat cursor-pointer',
                className
            )}
        >
            <span className="text-[11px] font-medium text-foreground/65 dark:text-foreground/45">{label}</span>
            <span className="flex w-full items-end justify-between gap-3">
                <span
                    className={cn(
                        'leading-none tracking-tight',
                        hero ? 'text-[48px] font-semibold' : 'text-[22px] font-semibold',
                        tone === 'failure' && 'text-red-600 dark:text-red-400',
                        tone === 'attention' && 'text-foreground'
                    )}
                >
                    {value}
                </span>
                {trend && <Sparkline values={trend} className="mb-[3px] shrink-0" />}
            </span>
            {delta && (
                <span className={cn('text-[11px]', delta.good === false ? 'text-red-600 dark:text-red-400' : 'text-foreground/60 dark:text-foreground/40')}>
                    {delta.text}
                </span>
            )}
        </Tag>
    );
}

/** 14-point sparkline, de-emphasis ink with the last point marked. */
export function Sparkline({ values, width = 72, height = 22, className }: { values: number[]; width?: number; height?: number; className?: string }) {
    if (!values.length) return null;
    const max = Math.max(1, ...values);
    const stepX = values.length > 1 ? width / (values.length - 1) : width;
    const pts = values.map((v, i) => [i * stepX, height - 2 - (v / max) * (height - 4)] as const);
    const path = pts.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)} ${y.toFixed(1)}`).join(' ');
    const [lx, ly] = pts[pts.length - 1];
    return (
        <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className={cn('overflow-visible', className)} aria-hidden>
            <path d={path} fill="none" stroke="hsl(var(--foreground) / 0.3)" strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" />
            <circle cx={lx} cy={ly} r={2.5} fill="hsl(var(--foreground))" stroke="hsl(var(--background))" strokeWidth={2} />
        </svg>
    );
}
