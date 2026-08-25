/* Bespoke per-app compositions for the staged trigger: a GitHub issue looks
   like a GitHub issue, a Monday item like a board row, a Stripe payment like
   a payment event. Each maps the staged lead — title / author / handle /
   body / time — into its app's iconic arrangement, painted with the app's
   DARK palette from appThemes, and rendered per OPERATION through the
   opGrammar tables: every trigger op in the registry has an authored pill /
   byline / caption / glyph in the app's own vocabulary (edited, assigned,
   labeled, pinned, milestoned, merged, no-show, past due, …). Display-only:
   editing swaps to the themed field stack in native.tsx. */

import type { CSSProperties, ReactNode } from 'react';
import {
    AlertTriangle,
    Bell,
    Calendar,
    CheckCircle2,
    Circle,
    CircleDot,
    ClipboardList,
    CreditCard,
    DollarSign,
    Eye,
    FileText,
    GitCommit,
    GitMerge,
    GitPullRequest,
    Lock,
    Mail,
    MessageSquare,
    Milestone,
    Pencil,
    Phone,
    Pin,
    RefreshCw,
    Shield,
    ShoppingCart,
    Star,
    Tag,
    Tags,
    Trash2,
    User,
    Users,
    Video,
    type LucideIcon,
} from 'lucide-react';
import type { Scenario } from './fixture';
import type { AppTheme } from './appThemes';
import {
    conjugate,
    resolveOpRender,
    TONE_HUES,
    type IconKey,
    type OpRender,
    type PillTone,
} from './opGrammar';

type Lead = Scenario['lead'];
interface FrameProps {
    lead: Lead;
    theme: AppTheme;
    operation?: string;
}

/* ------------------------------------------------------------ primitives */

const ICONS: Record<IconKey, LucideIcon> = {
    issue: CircleDot, pr: GitPullRequest, merge: GitMerge, commit: GitCommit,
    tag: Tag, star: Star, comment: MessageSquare, edit: Pencil, label: Tags,
    pin: Pin, lock: Lock, milestone: Milestone, trash: Trash2, user: User,
    users: Users, alert: AlertTriangle, check: CheckCircle2, calendar: Calendar,
    file: FileText, card: CreditCard, bell: Bell, mail: Mail, phone: Phone,
    video: Video, form: ClipboardList, cart: ShoppingCart, dollar: DollarSign,
    refresh: RefreshCw, eye: Eye, shield: Shield,
};

function toneHue(tone: PillTone, theme: AppTheme): string {
    if (tone === 'brand') return theme.accent;
    if (tone === 'neutral') return theme.sub;
    return TONE_HUES[tone];
}

function Pill({
    label,
    color,
    bg,
    border,
}: {
    label: string;
    color: string;
    bg: string;
    border?: string;
}) {
    return (
        <span
            className="inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-[10.5px] font-semibold"
            style={{ color, background: bg, ...(border ? { boxShadow: `inset 0 0 0 1px ${border}` } : {}) }}
        >
            {label}
        </span>
    );
}

/** State pill tinted from a hue on the app's own dark surface. */
function tintPill(label: string, hue: string) {
    return <Pill label={label} color={hue} bg={`${hue}26`} border={`${hue}55`} />;
}

/** The grammar's pill, tinted for this app. */
function opPill(r: OpRender | undefined, theme: AppTheme): ReactNode | null {
    if (!r?.pill) return null;
    return tintPill(r.pill.label, toneHue(r.pill.tone, theme));
}

/** The grammar's byline conjugated for the staged sender, else the default. */
function opByline(r: OpRender | undefined, lead: Lead, fallback: string): string {
    return r?.byline ? conjugate(r.byline, lead.author) : fallback;
}

function opIcon(r: OpRender | undefined): LucideIcon | undefined {
    return r?.icon ? ICONS[r.icon] : undefined;
}

function withTime(text: string, lead: Lead): string {
    return lead.time ? `${text} · ${lead.time}` : text;
}

function InitialDot({ name, theme, square = false }: { name?: string; theme: AppTheme; square?: boolean }) {
    return (
        <span
            className={`grid h-6 w-6 shrink-0 place-items-center text-[11px] font-semibold ${square ? 'rounded-md' : 'rounded-full'}`}
            style={{ background: `${theme.accent}26`, color: theme.accent }}
        >
            {(name ?? '?').charAt(0).toUpperCase()}
        </span>
    );
}

function Surface({ theme, children, style }: { theme: AppTheme; children: ReactNode; style?: CSSProperties }) {
    return (
        <div
            className="rounded-lg px-3.5 py-3"
            style={{ background: theme.surface, color: theme.ink, boxShadow: `inset 0 0 0 1px ${theme.border}`, ...style }}
        >
            {children}
        </div>
    );
}

const sub = (theme: AppTheme): CSSProperties => ({ color: theme.sub });

/** "invoice_paid" → "Invoice paid" — the op itself when no table names it. */
function humanizeOp(operation?: string): string | undefined {
    const s = (operation ?? '').replace(/^on_/, '').replace(/[_-]+/g, ' ').trim();
    if (!s) return undefined;
    return s.charAt(0).toUpperCase() + s.slice(1);
}

/* --------------------------------------------------------------- shapes */

// GitHub paints state with its own exact hues, not the generic tones.
const GITHUB_HUES: Record<PillTone, (label: string) => string> = {
    good: () => '#3fb950',
    bad: () => '#f85149',
    warn: (l) => (l === 'Starred' ? '#e3b341' : '#d29922'),
    info: (l) => (l === 'Merged' ? '#a371f7' : '#58a6ff'),
    neutral: () => '#6e7681',
    brand: () => '#3fb950',
};

function GithubEvent({ lead, theme, operation }: FrameProps) {
    const r = resolveOpRender('github', operation);
    const isPr = /pull/.test(operation ?? '');
    const Icon =
        opIcon(r) ?? (isPr ? GitPullRequest : CircleDot);
    const hue = r?.pill ? GITHUB_HUES[r.pill.tone](r.pill.label) : theme.accent;
    const solidPill = r?.pill ? (
        <Pill
            label={r.pill.label}
            color={r.pill.tone === 'neutral' || r.pill.tone === 'warn' ? '#0d1117' : '#ffffff'}
            bg={hue}
        />
    ) : (
        <Pill label="Open" color="#ffffff" bg={theme.accent} />
    );
    const iconColor = r?.icon && ['edit', 'comment', 'commit'].includes(r.icon) ? theme.sub : hue;
    const mono = r?.icon === 'commit';
    return (
        <Surface theme={theme}>
            <div className="flex items-start gap-2.5">
                <Icon className="mt-0.5 h-4 w-4 shrink-0" style={{ color: iconColor }} />
                <div className="min-w-0 flex-1">
                    <div className="flex items-start justify-between gap-2">
                        <p className="m-0 text-[13.5px] font-semibold leading-snug">{lead.title}</p>
                        {solidPill}
                    </div>
                    <p className="m-0 mt-1 text-[11.5px]" style={sub(theme)}>
                        {withTime(opByline(r, lead, `opened by ${lead.author ?? 'someone'}`), lead)}
                    </p>
                    <p
                        className={`mb-0 mt-2 rounded-md px-2.5 py-2 text-[12.5px] leading-relaxed ${mono ? 'font-mono text-[11.5px]' : ''}`}
                        style={{ background: 'rgba(125,133,144,0.08)', boxShadow: `inset 0 0 0 1px ${theme.border}`, color: theme.ink }}
                    >
                        {lead.body}
                    </p>
                </div>
            </div>
        </Surface>
    );
}

function GitlabEvent({ lead, theme, operation }: FrameProps) {
    const r = resolveOpRender('gitlab', operation);
    const Icon = opIcon(r) ?? CircleDot;
    return (
        <Surface theme={theme} style={{ borderLeft: `3px solid ${theme.accent}` }}>
            <div className="flex items-start gap-2.5">
                <Icon className="mt-0.5 h-4 w-4 shrink-0" style={{ color: theme.accent }} />
                <div className="min-w-0 flex-1">
                    <div className="flex items-start justify-between gap-2">
                        <p className="m-0 text-[13.5px] font-semibold leading-snug">{lead.title}</p>
                        {opPill(r, theme) ?? tintPill('Open', '#5297ff')}
                    </div>
                    <p className="m-0 mt-1 text-[11.5px]" style={sub(theme)}>
                        {withTime(opByline(r, lead, lead.author ?? ''), lead)}
                    </p>
                    <p className="mb-0 mt-2 text-[12.5px] leading-relaxed" style={sub(theme)}>{lead.body}</p>
                </div>
            </div>
        </Surface>
    );
}

function LinearIssue({ lead, theme, operation }: FrameProps) {
    const r = resolveOpRender('linear', operation);
    const status = r?.pill;
    return (
        <Surface theme={theme}>
            <div className="flex items-center gap-2.5">
                <span className="flex shrink-0 items-end gap-[2px]">
                    {[4, 7, 10].map((h) => (
                        <span key={h} className="w-[3px] rounded-sm" style={{ height: h, background: theme.sub }} />
                    ))}
                </span>
                <p className="m-0 min-w-0 flex-1 truncate text-[13.5px] font-medium">{lead.title}</p>
                {status && (
                    <span className="inline-flex shrink-0 items-center gap-1.5 text-[11.5px]" style={sub(theme)}>
                        {status.tone === 'good' ? (
                            <CheckCircle2 className="h-3 w-3" style={{ color: toneHue(status.tone, theme) }} />
                        ) : (
                            <Circle className="h-3 w-3" style={{ color: toneHue(status.tone, theme) }} />
                        )}{' '}
                        {status.label}
                    </span>
                )}
            </div>
            <p className="m-0 mt-1.5 pl-[21px] text-[11.5px]" style={sub(theme)}>
                {withTime(opByline(r, lead, `created by ${lead.author ?? 'someone'}`), lead)}
            </p>
            <p className="mb-0 mt-1.5 pl-[21px] text-[12.5px] leading-relaxed" style={sub(theme)}>{lead.body}</p>
        </Surface>
    );
}

function JiraIssue({ lead, theme, operation }: FrameProps) {
    const r = resolveOpRender('jira', operation);
    // Atlassian dark lozenges: TO DO blue, DONE green, deleted red.
    const lozenge = r?.pill
        ? r.pill.tone === 'good'
            ? <Pill label={r.pill.label} color="#7ee2b8" bg="#164b35" />
            : r.pill.tone === 'bad'
              ? <Pill label={r.pill.label} color="#fd9891" bg="#42221f" />
              : <Pill label={r.pill.label} color="#85b8ff" bg="#1c2b41" />
        : <Pill label="TO DO" color="#85b8ff" bg="#1c2b41" />;
    return (
        <Surface theme={theme}>
            <div className="flex items-center gap-2">
                <span className="grid h-4 w-4 shrink-0 place-items-center rounded-[3px]" style={{ background: '#4bade8' }}>
                    <CheckCircle2 className="h-3 w-3 text-white" />
                </span>
                <p className="m-0 min-w-0 flex-1 truncate text-[13.5px] font-medium">{lead.title}</p>
                {lozenge}
            </div>
            <p className="m-0 mt-1.5 text-[11.5px]" style={sub(theme)}>
                {withTime(opByline(r, lead, `Reporter: ${lead.author ?? '—'}`), lead)}
            </p>
            <p className="mb-0 mt-1.5 text-[12.5px] leading-relaxed" style={sub(theme)}>{lead.body}</p>
        </Surface>
    );
}

function NotionPage({ lead, theme, operation }: FrameProps) {
    const r = resolveOpRender('notion', operation);
    const Icon = opIcon(r) ?? FileText;
    return (
        <Surface theme={theme}>
            <p className="m-0 flex items-center gap-2 text-[15px] font-bold leading-snug">
                <Icon className="h-4 w-4 shrink-0" style={sub(theme)} /> {lead.title}
            </p>
            <p className="m-0 mt-1 text-[11.5px]" style={sub(theme)}>
                {withTime(opByline(r, lead, `Created by ${lead.author ?? 'someone'}`), lead)}
            </p>
            <div className="my-2 h-px" style={{ background: theme.border }} />
            <p className="mb-0 text-[13px] leading-relaxed">{lead.body}</p>
        </Surface>
    );
}

function MondayItem({ lead, theme, operation }: FrameProps) {
    const r = resolveOpRender('monday', operation);
    return (
        <Surface theme={theme} style={{ borderLeft: `4px solid ${theme.accent}` }}>
            <div className="flex items-center gap-2.5">
                <p className="m-0 min-w-0 flex-1 truncate text-[13.5px] font-medium">{lead.title}</p>
                {r?.pill ? (
                    <Pill label={r.pill.label} color="#ffffff" bg={r.pill.tone === 'info' ? '#0073ea' : toneHue(r.pill.tone, theme)} />
                ) : (
                    <Pill label="New" color="#ffffff" bg="#0073ea" />
                )}
                <InitialDot name={lead.author} theme={theme} />
            </div>
            <p className="m-0 mt-1 text-[11.5px]" style={sub(theme)}>
                {opByline(r, lead, `added by ${lead.author ?? 'someone'}`)}
            </p>
            <p className="mb-0 mt-1.5 text-[12.5px] leading-relaxed" style={sub(theme)}>{lead.body}</p>
        </Surface>
    );
}

function ClickupTask({ lead, theme, operation }: FrameProps) {
    const r = resolveOpRender('clickup', operation);
    return (
        <Surface theme={theme}>
            <div className="flex items-center gap-2.5">
                <span className="grid h-4 w-4 shrink-0 place-items-center rounded-[4px]" style={{ boxShadow: `inset 0 0 0 1.5px ${theme.accent}` }} />
                <p className="m-0 min-w-0 flex-1 truncate text-[13.5px] font-medium">{lead.title}</p>
                {opPill(r, theme) ?? tintPill('TO DO', theme.sub)}
                <InitialDot name={lead.author} theme={theme} />
            </div>
            <p className="m-0 mt-1 pl-[26px] text-[11.5px]" style={sub(theme)}>
                {opByline(r, lead, `created by ${lead.author ?? 'someone'}`)}
            </p>
            <p className="mb-0 mt-1.5 pl-[26px] text-[12.5px] leading-relaxed" style={sub(theme)}>{lead.body}</p>
        </Surface>
    );
}

function TrelloCard({ lead, theme, operation }: FrameProps) {
    const r = resolveOpRender('trello', operation);
    return (
        <div className="rounded-lg px-3 py-2.5" style={{ background: theme.surface }}>
            <div
                className="rounded-lg px-3 py-2.5 shadow-[0_1px_2px_rgba(0,0,0,0.5)]"
                style={{ background: theme.bubbleIn, color: theme.ink }}
            >
                <span className="mb-1.5 block h-2 w-9 rounded-full" style={{ background: theme.accent }} />
                <p className="m-0 text-[13.5px] leading-snug">{lead.title}</p>
                <p className="m-0 mt-1 text-[11.5px]" style={sub(theme)}>
                    {opByline(r, lead, `added by ${lead.author ?? 'someone'}`)}
                </p>
                <p className="m-0 mt-1.5 flex items-center justify-between gap-2 text-[11.5px]" style={sub(theme)}>
                    <span className="min-w-0 truncate">{lead.body}</span>
                    <InitialDot name={lead.author} theme={theme} />
                </p>
            </div>
        </div>
    );
}

function AsanaTask({ lead, theme, operation }: FrameProps) {
    const r = resolveOpRender('asana', operation);
    return (
        <Surface theme={theme}>
            <div className="flex items-center gap-2.5">
                <CheckCircle2 className="h-5 w-5 shrink-0" style={sub(theme)} strokeWidth={1.5} />
                <p className="m-0 min-w-0 flex-1 truncate text-[13.5px] font-medium">{lead.title}</p>
                <InitialDot name={lead.author} theme={theme} />
            </div>
            <p className="m-0 mt-1 pl-[30px] text-[11.5px]" style={sub(theme)}>
                {opByline(r, lead, `assigned to ${lead.author ?? 'someone'}`)}
            </p>
            <p className="mb-0 mt-1.5 pl-[30px] text-[12.5px] leading-relaxed" style={sub(theme)}>{lead.body}</p>
        </Surface>
    );
}

function TodoistTask({ lead, theme, operation }: FrameProps) {
    const r = resolveOpRender('todoist', operation);
    return (
        <Surface theme={theme}>
            <div className="flex items-start gap-2.5">
                <span className="mt-0.5 h-4 w-4 shrink-0 rounded-full" style={{ boxShadow: `inset 0 0 0 1.5px ${theme.accent}` }} />
                <div className="min-w-0 flex-1">
                    <p className="m-0 text-[13.5px]">{lead.title}</p>
                    <p className="m-0 mt-1 text-[11.5px]" style={sub(theme)}>
                        {withTime(opByline(r, lead, `Inbox${lead.author ? ` · ${lead.author}` : ''}`), lead)}
                    </p>
                    <p className="mb-0 mt-1.5 text-[12.5px] leading-relaxed" style={sub(theme)}>{lead.body}</p>
                </div>
            </div>
        </Surface>
    );
}

function StripeEvent({ lead, theme, operation }: FrameProps) {
    const r = resolveOpRender('stripe', operation);
    return (
        <Surface theme={theme}>
            <div className="flex items-center justify-between gap-2">
                <p className="m-0 text-[11px] font-semibold uppercase tracking-wider" style={sub(theme)}>
                    {r?.caption ?? 'Payment'}
                </p>
                {opPill(r, theme) ?? tintPill('Succeeded', TONE_HUES.good)}
            </div>
            <p className="m-0 mt-1.5 text-[15px] font-bold">{lead.title}</p>
            <p className="m-0 mt-1 text-[11.5px]" style={sub(theme)}>
                {withTime(
                    opByline(r, lead, [lead.author, lead.handle].filter(Boolean).join(' · ')),
                    lead
                )}
            </p>
            <p className="mb-0 mt-2 text-[12.5px] leading-relaxed" style={sub(theme)}>{lead.body}</p>
        </Surface>
    );
}

function ShopifyOrder({ lead, theme, operation }: FrameProps) {
    const r = resolveOpRender('shopify', operation);
    return (
        <Surface theme={theme}>
            <div className="flex items-center justify-between gap-2">
                <p className="m-0 text-[13.5px] font-semibold">{lead.title}</p>
                {opPill(r, theme) ?? tintPill('Paid', TONE_HUES.good)}
            </div>
            <p className="m-0 mt-1 text-[11.5px]" style={sub(theme)}>
                {withTime(
                    opByline(r, lead, [lead.author, lead.handle].filter(Boolean).join(' · ')),
                    lead
                )}
            </p>
            <p className="mb-0 mt-2 text-[12.5px] leading-relaxed" style={sub(theme)}>{lead.body}</p>
        </Surface>
    );
}

function BookingCard({ lead, theme, operation }: FrameProps) {
    const r = resolveOpRender(theme.slug ?? 'cal_com', operation);
    const Icon = opIcon(r) ?? Calendar;
    return (
        <Surface theme={theme}>
            <div className="flex items-start gap-3">
                <span
                    className="grid h-11 w-11 shrink-0 place-items-center rounded-lg"
                    style={{ background: `${theme.accent}1f`, color: theme.accent }}
                >
                    <Icon className="h-5 w-5" />
                </span>
                <div className="min-w-0 flex-1">
                    <div className="flex items-start justify-between gap-2">
                        <p className="m-0 text-[13.5px] font-semibold leading-snug">{lead.title}</p>
                        {opPill(r, theme) ?? tintPill('Confirmed', TONE_HUES.good)}
                    </div>
                    <p className="m-0 mt-0.5 text-[11.5px]" style={sub(theme)}>
                        {withTime(
                            opByline(r, lead, [lead.author, lead.handle].filter(Boolean).join(' · ')),
                            lead
                        )}
                    </p>
                    <p className="mb-0 mt-1.5 text-[12.5px] leading-relaxed" style={sub(theme)}>{lead.body}</p>
                </div>
            </div>
        </Surface>
    );
}

function FormResponse({ lead, theme, operation }: FrameProps) {
    const r = resolveOpRender(theme.slug ?? '', operation);
    return (
        <Surface theme={theme}>
            <div className="flex items-center justify-between gap-2">
                <p className="m-0 text-[11px] font-semibold uppercase tracking-wider" style={sub(theme)}>
                    {r?.caption ?? humanizeOp(operation) ?? 'New response'}
                </p>
                {opPill(r, theme)}
            </div>
            <p className="m-0 mt-1 text-[13.5px] font-semibold">{lead.title}</p>
            <div className="mt-2 pl-3" style={{ borderLeft: `3px solid ${theme.accent}` }}>
                <p className="m-0 text-[12.5px] leading-relaxed">{lead.body}</p>
            </div>
            <p className="m-0 mt-2 text-[11.5px]" style={sub(theme)}>
                {opByline(r, lead, [lead.author, lead.handle].filter(Boolean).join(' · '))}
            </p>
        </Surface>
    );
}

function SheetRow({ lead, theme, operation }: FrameProps) {
    const r = resolveOpRender('google_sheets', operation);
    const cells = [lead.author ?? '—', lead.handle ?? lead.meta, lead.body];
    return (
        <Surface theme={theme} style={{ padding: 0 }}>
            <div className="grid grid-cols-[1fr_1fr_2fr] text-[11px]" style={sub(theme)}>
                {['A', 'B', 'C'].map((c) => (
                    <span key={c} className="px-2.5 py-1 text-center font-medium" style={{ boxShadow: `inset 0 0 0 0.5px ${theme.border}` }}>
                        {c}
                    </span>
                ))}
            </div>
            <div className="grid grid-cols-[1fr_1fr_2fr] text-[12px]" style={{ background: `${theme.accent}14` }}>
                {cells.map((cell, i) => (
                    <span key={i} className="min-w-0 truncate px-2.5 py-1.5" style={{ boxShadow: `inset 0 0 0 0.5px ${theme.border}` }}>
                        {cell}
                    </span>
                ))}
            </div>
            {r?.byline && (
                <p className="m-0 px-2.5 py-1.5 text-[11px]" style={sub(theme)}>
                    {conjugate(r.byline, lead.author)}
                </p>
            )}
        </Surface>
    );
}

function CrmRecord({ lead, theme, operation }: FrameProps) {
    const r = resolveOpRender(theme.slug ?? '', operation);
    return (
        <Surface theme={theme}>
            <div className="flex items-center gap-2.5">
                <InitialDot name={lead.author} theme={theme} />
                <div className="min-w-0 flex-1">
                    <p className="m-0 truncate text-[13.5px] font-semibold">{lead.author ?? lead.title}</p>
                    <p className="m-0 text-[11.5px]" style={sub(theme)}>
                        {r?.caption ?? humanizeOp(operation) ?? lead.title}
                    </p>
                </div>
                {opPill(r, theme)}
            </div>
            {r?.byline && (
                <p className="m-0 mt-1.5 text-[11.5px]" style={sub(theme)}>
                    {conjugate(r.byline, lead.author)}
                </p>
            )}
            <div className="mt-2 space-y-1 text-[12px]">
                {lead.handle && (
                    <p className="m-0 flex gap-2">
                        <span className="w-12 shrink-0" style={sub(theme)}>Email</span>
                        <span style={{ color: theme.accent }}>{lead.handle}</span>
                    </p>
                )}
                <p className="m-0 flex gap-2">
                    <span className="w-12 shrink-0" style={sub(theme)}>Note</span>
                    <span className="min-w-0">{lead.body}</span>
                </p>
            </div>
        </Surface>
    );
}

function Ticket({ lead, theme, operation }: FrameProps) {
    const r = resolveOpRender(theme.slug ?? '', operation);
    return (
        <Surface theme={theme}>
            <div className="flex items-center justify-between gap-2">
                <p className="m-0 min-w-0 truncate text-[13.5px] font-semibold">{lead.title}</p>
                {opPill(r, theme) ?? tintPill('Open', theme.accent)}
            </div>
            <p className="m-0 mt-1 text-[11.5px]" style={sub(theme)}>
                {withTime(
                    opByline(
                        r,
                        lead,
                        `${lead.author ?? ''}${lead.handle ? ` <${lead.handle}>` : ''}`
                    ),
                    lead
                )}
            </p>
            <p className="mb-0 mt-2 text-[12.5px] leading-relaxed" style={sub(theme)}>{lead.body}</p>
        </Surface>
    );
}

function AlertCard({ lead, theme, operation }: FrameProps) {
    const r = resolveOpRender(theme.slug ?? '', operation);
    const hue = r?.pill ? toneHue(r.pill.tone, theme) : theme.accent;
    const Icon = opIcon(r) ?? AlertTriangle;
    return (
        <Surface theme={theme} style={{ borderLeft: `3px solid ${hue}` }}>
            {r?.caption && (
                <p className="m-0 mb-1 text-[11px] font-semibold uppercase tracking-wider" style={sub(theme)}>
                    {r.caption}
                </p>
            )}
            <div className="flex items-center gap-2">
                <Icon className="h-4 w-4 shrink-0" style={{ color: hue }} />
                <p className="m-0 min-w-0 flex-1 truncate text-[13.5px] font-semibold">{lead.title}</p>
                {opPill(r, theme) ?? <Pill label="Triggered" color="#ffffff" bg={theme.accent} />}
            </div>
            {r?.byline && (
                <p className="m-0 mt-1.5 text-[11.5px]" style={sub(theme)}>
                    {conjugate(r.byline, lead.author)}
                </p>
            )}
            <p className="mb-0 mt-2 font-mono text-[12px] leading-relaxed" style={sub(theme)}>{lead.body}</p>
            {lead.time && (
                <p className="m-0 mt-1.5 font-mono text-[10.5px]" style={sub(theme)}>{lead.time}</p>
            )}
        </Surface>
    );
}

function SocialPost({ lead, theme, operation }: FrameProps) {
    const r = resolveOpRender(theme.slug ?? '', operation);
    return (
        <Surface theme={theme}>
            <div className="flex items-center gap-2.5">
                <InitialDot name={lead.author} theme={theme} />
                <p className="m-0 flex min-w-0 items-baseline gap-1.5 text-[13px]">
                    <span className="truncate font-bold">{lead.author}</span>
                    {lead.handle && <span style={sub(theme)}>{lead.handle}</span>}
                    {lead.time && <span style={sub(theme)}>· {lead.time}</span>}
                </p>
                <span className="ml-auto">{opPill(r, theme)}</span>
            </div>
            {r?.byline && (
                <p className="m-0 mt-1.5 text-[11.5px]" style={sub(theme)}>
                    {conjugate(r.byline, lead.author)}
                </p>
            )}
            <p className="mb-0 mt-2 text-[13.5px] leading-relaxed">{lead.body}</p>
        </Surface>
    );
}

function FileEvent({ lead, theme, operation }: FrameProps) {
    const r = resolveOpRender(theme.slug ?? '', operation);
    const Icon = opIcon(r) ?? FileText;
    return (
        <Surface theme={theme}>
            {r?.caption && (
                <p className="m-0 mb-1.5 text-[11px] font-semibold uppercase tracking-wider" style={sub(theme)}>
                    {r.caption}
                </p>
            )}
            <div className="flex items-start gap-2.5">
                <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg" style={{ background: `${theme.accent}1f` }}>
                    <Icon className="h-5 w-5" style={{ color: theme.accent }} />
                </span>
                <div className="min-w-0 flex-1">
                    <div className="flex items-start justify-between gap-2">
                        <p className="m-0 truncate text-[13.5px] font-medium">{lead.title}</p>
                        {opPill(r, theme)}
                    </div>
                    <p className="m-0 mt-0.5 text-[11.5px]" style={sub(theme)}>
                        {withTime(opByline(r, lead, `Added by ${lead.author ?? 'someone'}`), lead)}
                    </p>
                    <p className="mb-0 mt-1.5 text-[12.5px] leading-relaxed" style={sub(theme)}>{lead.body}</p>
                </div>
            </div>
        </Surface>
    );
}

function EventCard({ lead, theme, operation }: FrameProps) {
    const r = resolveOpRender(theme.slug ?? '', operation);
    const caption = r?.caption ?? humanizeOp(operation);
    return (
        <Surface theme={theme} style={{ borderLeft: `3px solid ${theme.accent}` }}>
            <div className="flex items-center justify-between gap-2">
                {caption ? (
                    <p className="m-0 text-[11px] font-semibold uppercase tracking-wider" style={sub(theme)}>
                        {caption}
                    </p>
                ) : (
                    <span />
                )}
                {opPill(r, theme)}
            </div>
            <p className="m-0 mt-1 text-[13.5px] font-semibold leading-snug">{lead.title}</p>
            <p className="m-0 mt-1 text-[11.5px]" style={sub(theme)}>
                {withTime(
                    opByline(r, lead, [lead.author, lead.handle].filter(Boolean).join(' · ')),
                    lead
                )}
            </p>
            <p className="mb-0 mt-2 text-[12.5px] leading-relaxed" style={sub(theme)}>{lead.body}</p>
        </Surface>
    );
}

/** The bespoke display for a themed non-chat, non-email shape. */
export function BespokeInbound(props: FrameProps) {
    switch (props.theme.shape) {
        case 'github': return <GithubEvent {...props} />;
        case 'gitlab': return <GitlabEvent {...props} />;
        case 'linear': return <LinearIssue {...props} />;
        case 'jira': return <JiraIssue {...props} />;
        case 'notion': return <NotionPage {...props} />;
        case 'monday': return <MondayItem {...props} />;
        case 'clickup': return <ClickupTask {...props} />;
        case 'trello': return <TrelloCard {...props} />;
        case 'asana': return <AsanaTask {...props} />;
        case 'todoist': return <TodoistTask {...props} />;
        case 'stripe': return <StripeEvent {...props} />;
        case 'shopify': return <ShopifyOrder {...props} />;
        case 'booking': return <BookingCard {...props} />;
        case 'response': return <FormResponse {...props} />;
        case 'sheet': return <SheetRow {...props} />;
        case 'record': return <CrmRecord {...props} />;
        case 'ticket': return <Ticket {...props} />;
        case 'alert': return <AlertCard {...props} />;
        case 'post': return <SocialPost {...props} />;
        case 'file': return <FileEvent {...props} />;
        default: return <EventCard {...props} />;
    }
}
