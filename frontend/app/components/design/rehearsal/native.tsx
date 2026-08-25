/* Native-shaped renderings for what arrives at the agent and what it would send
   back — an email reads as an email, a Slack message as a Slack message, a
   WhatsApp chat as a chat. Added because the bench originally rendered every
   trigger through one generic title/meta/body card, so switching mocks changed
   the words but not the design; recognising the shape of your own tools is most
   of what makes the rehearsal feel real. Frames are THEMED in the app's own
   palette (appThemes.ts — deliberate brand islands) and bespoke-shaped per app
   (bespokeFrames.tsx); apps without a theme keep the neutral structural
   frames — never a wrong brand. */

import { useEffect, useRef, type CSSProperties } from 'react';
import { CheckCheck, Mic, Paperclip } from 'lucide-react';
import { SerializedIcon } from '~/components/shared/SerializedIcon';
import { cn } from '~/lib/utils';
import { AGENT_NAME, type Scenario } from './fixture';
import { resolveAppTheme, type AppTheme } from './appThemes';
import { BespokeInbound } from './bespokeFrames';
import { conjugate, resolveOpRender } from './opGrammar';
import { ChatMarkup } from './chatMarkup';
import { MarkdownRenderer } from '~/components/chat/MarkdownRendererLazy';

export interface Mark {
    iconHtml?: string;
    iconColor?: string;
    /** Client-side alternative: a ready icon node. */
    node?: React.ReactNode;
}
type Icons = Record<string, Mark>;

function Glyph({ mark, className }: { mark?: Mark; className?: string }) {
    if (mark?.node) return <span className={cn('inline-flex', className)}>{mark.node}</span>;
    if (!mark?.iconHtml) return null;
    return (
        <SerializedIcon html={mark.iconHtml} iconColor={mark.iconColor} className={className} />
    );
}

/** Slack highlights mentions; rendering them flat loses the "this was aimed at
    the agent" beat that explains why the run started. Themed frames pass the
    app's own mention accent; the neutral frame keeps the sky default. */
function withMention(text: string, accent?: string) {
    const m = text.match(/@[\w-]+/);
    if (!m || m.index === undefined) return text;
    return (
        <>
            {text.slice(0, m.index)}
            <span
                className={cn('rounded px-1 py-px', !accent && 'bg-sky-400/15 text-sky-300')}
                style={accent ? { color: accent, background: `${accent}26` } : undefined}
            >
                {m[0]}
            </span>
            {text.slice(m.index + m[0].length)}
        </>
    );
}



/* ------------------------------------------------------------- editing */

export type LeadPatch = Partial<Scenario['lead']>;
export interface LeadEdit {
    onPatch: (patch: LeadPatch) => void;
}

/** A text field that dresses as the text it replaces: transparent, same
    typography, betrayed only by a faint underline. Editing the email inside
    the email is the point — a form would break the shape we spent all this
    effort rendering. */
function Editable({
    value,
    onChange,
    className,
    style,
    multiline = false,
    placeholder,
}: {
    value?: string;
    onChange: (v: string) => void;
    className?: string;
    /** Themed frames pass the app's inks (color + borderColor) — the token
        classes below only apply when no style overrides them. */
    style?: CSSProperties;
    multiline?: boolean;
    placeholder?: string;
}) {
    const shared = cn(
        'w-full min-w-0 bg-transparent outline-none placeholder:text-current placeholder:opacity-40',
        'border-b border-dashed border-foreground/15 focus:border-current',
        className
    );
    if (multiline) {
        return (
            <AutoTextarea
                value={value}
                onChange={onChange}
                className={shared}
                style={style}
                placeholder={placeholder}
            />
        );
    }
    return (
        <input
            value={value ?? ''}
            onChange={(e) => onChange(e.target.value)}
            placeholder={placeholder}
            className={shared}
            style={style}
        />
    );
}

/** Grows with its content and never scrolls: a scrollbar inside a message that
    is pretending to be text gives the whole trick away (and arrives in the
    browser's default light chrome on this black ground). Measured height
    instead of field-sizing, which not every engine supports yet. */
function AutoTextarea({
    value,
    onChange,
    className,
    style,
    placeholder,
}: {
    value?: string;
    onChange: (v: string) => void;
    className?: string;
    style?: CSSProperties;
    placeholder?: string;
}) {
    const ref = useRef<HTMLTextAreaElement>(null);
    useEffect(() => {
        const el = ref.current;
        if (!el) return;
        el.style.height = 'auto';
        // scrollHeight excludes the border that border-box height includes;
        // without the delta the last line is clipped by a border-width.
        el.style.height = `${el.scrollHeight + el.offsetHeight - el.clientHeight}px`;
    }, [value]);
    return (
        <textarea
            ref={ref}
            value={value ?? ''}
            onChange={(e) => onChange(e.target.value)}
            placeholder={placeholder}
            rows={1}
            className={cn(className, 'resize-none overflow-hidden')}
            style={style}
        />
    );
}

/* --------------------------------------------------------- themed frames */

/** The app's own surface as the region behind the content. */
function AppSurface({
    theme,
    className,
    children,
}: {
    theme: AppTheme;
    className?: string;
    children: React.ReactNode;
}) {
    return (
        <div
            className={cn('rounded-lg', className)}
            style={{
                background: theme.surface,
                ...(theme.wallpaper ? { backgroundImage: theme.wallpaper } : {}),
                color: theme.ink,
                boxShadow: `inset 0 0 0 1px ${theme.border}`,
            }}
        >
            {children}
        </div>
    );
}

/** The corner the inbound bubble's tail cuts, per app. */
function tailClass(theme: AppTheme, side: 'in' | 'out'): string {
    if (theme.tail === 'none') return '';
    if (side === 'out') return 'rounded-br-sm';
    return theme.tail === 'bottom' ? 'rounded-bl-sm' : 'rounded-tl-sm';
}

/** The app's inert composer strip — attach / Message / mic. Pure garnish,
    but it is what makes the frame read as the real client. */
function ComposerRow({ theme }: { theme: AppTheme }) {
    return (
        <div aria-hidden className="mt-3 flex select-none items-center gap-2 opacity-60">
            <Paperclip className="h-4 w-4 shrink-0" style={{ color: theme.sub }} />
            <span
                className="min-w-0 flex-1 rounded-full px-3.5 py-1.5 text-[12.5px]"
                style={{
                    color: theme.sub,
                    background: theme.bubbleIn,
                    boxShadow: `inset 0 0 0 1px ${theme.border}`,
                }}
            >
                Message
            </span>
            <Mic className="h-4 w-4 shrink-0" style={{ color: theme.sub }} />
        </div>
    );
}

/** The app's own system line — "{author} joined the channel" — for chat
    events that aren't a plain message. Grammar-driven, per operation. */
function SystemLine({
    theme,
    lead,
    operation,
}: {
    theme: AppTheme;
    lead: Scenario['lead'];
    operation?: string;
}) {
    const r = resolveOpRender(theme.slug, operation);
    if (!r?.byline) return null;
    return (
        <p className="m-0 mb-2 text-center text-[11px]" style={{ color: theme.sub }}>
            {conjugate(r.byline, lead.author)}
        </p>
    );
}

/** WhatsApp / Telegram / iMessage: their bubble on their chat wallpaper. */
function ThemedBubbleIn({
    lead,
    theme,
    edit,
    operation,
}: {
    lead: Scenario['lead'];
    theme: AppTheme;
    edit?: LeadEdit;
    operation?: string;
}) {
    const inks = { color: theme.ink, borderColor: `${theme.sub}66` };
    return (
        <AppSurface theme={theme} className="p-3">
            {!edit && <SystemLine theme={theme} lead={lead} operation={operation} />}
            <div
                className={cn('max-w-[88%] rounded-2xl px-3.5 py-2.5', tailClass(theme, 'in'), edit && 'w-full')}
                style={{ background: theme.bubbleIn }}
            >
                {edit ? (
                    <div className="flex items-baseline gap-2">
                        <Editable
                            value={lead.author}
                            onChange={(v) => edit.onPatch({ author: v })}
                            placeholder="Contact"
                            className="w-36 text-[12.5px] font-semibold"
                            style={{ color: theme.author, borderColor: `${theme.sub}66` }}
                        />
                        <Editable
                            value={lead.handle}
                            onChange={(v) => edit.onPatch({ handle: v })}
                            placeholder="number"
                            className="font-mono text-[10.5px]"
                            style={{ color: theme.sub, borderColor: `${theme.sub}66` }}
                        />
                    </div>
                ) : (
                    <p className="m-0 flex items-baseline gap-2">
                        <span className="text-[12.5px] font-semibold" style={{ color: theme.author }}>
                            {lead.author}
                        </span>
                        <span className="font-mono text-[10.5px]" style={{ color: theme.sub }}>
                            {lead.handle}
                        </span>
                    </p>
                )}
                {edit ? (
                    <Editable
                        multiline
                        value={lead.body}
                        onChange={(v) => edit.onPatch({ body: v })}
                        placeholder="Message"
                        className="mt-1 text-[13px] leading-relaxed"
                        style={inks}
                    />
                ) : (
                    <p className="mb-0 mt-1 text-[13px] leading-relaxed">{lead.body}</p>
                )}
                {lead.time && (
                    <p className="m-0 mt-1 text-right text-[10px]" style={{ color: theme.sub }}>
                        {lead.time}
                    </p>
                )}
            </div>
            {theme.composer && !edit && <ComposerRow theme={theme} />}
        </AppSurface>
    );
}

/** Slack / Discord / Teams: the message row on the client's surface. */
function ThemedRowIn({
    lead,
    theme,
    edit,
    operation,
}: {
    lead: Scenario['lead'];
    theme: AppTheme;
    edit?: LeadEdit;
    operation?: string;
}) {
    const inks = { color: theme.ink, borderColor: `${theme.sub}66` };
    return (
        <AppSurface theme={theme} className="px-3.5 py-3">
            {!edit && <SystemLine theme={theme} lead={lead} operation={operation} />}
            {edit ? (
                <Editable
                    value={lead.title}
                    onChange={(v) => edit.onPatch({ title: v })}
                    placeholder="#channel"
                    className="mb-2.5 w-40 text-[11.5px] font-medium"
                    style={{ color: theme.sub, borderColor: `${theme.sub}66` }}
                />
            ) : (
                <p className="m-0 mb-2.5 text-[11.5px] font-medium" style={{ color: theme.sub }}>
                    {lead.title}
                </p>
            )}
            <div className="flex gap-2.5">
                <span
                    className="grid h-8 w-8 shrink-0 place-items-center rounded-md text-[12.5px] font-semibold"
                    style={{ background: `${theme.accent}26`, color: theme.accent }}
                >
                    {(lead.author ?? '?').charAt(0).toUpperCase()}
                </span>
                <div className="min-w-0 flex-1">
                    {edit ? (
                        <Editable
                            value={lead.author}
                            onChange={(v) => edit.onPatch({ author: v })}
                            placeholder="Author"
                            className="w-40 text-[13px] font-semibold"
                            style={{ color: theme.author, borderColor: `${theme.sub}66` }}
                        />
                    ) : (
                        <p className="m-0 flex items-baseline gap-2">
                            <span className="text-[13px] font-semibold" style={{ color: theme.author }}>
                                {lead.author}
                            </span>
                            {lead.time && (
                                <span className="font-mono text-[11px]" style={{ color: theme.sub }}>
                                    {lead.time}
                                </span>
                            )}
                        </p>
                    )}
                    {edit ? (
                        <Editable
                            multiline
                            value={lead.body}
                            onChange={(v) => edit.onPatch({ body: v })}
                            placeholder="Message"
                            className="mt-1 text-[13px] leading-relaxed"
                            style={inks}
                        />
                    ) : (
                        <p className="mb-0 mt-0.5 text-[13px] leading-relaxed">
                            {withMention(lead.body, theme.accent)}
                        </p>
                    )}
                </div>
            </div>
        </AppSurface>
    );
}

/** Gmail / Outlook / Mailgun: the reading pane, in the client's dark theme.
    Delivery-event operations (delivered / bounced / opened) add a status
    line under the envelope header. */
function ThemedEmailIn({
    lead,
    theme,
    edit,
    operation,
}: {
    lead: Scenario['lead'];
    theme: AppTheme;
    edit?: LeadEdit;
    operation?: string;
}) {
    const r = resolveOpRender(theme.slug, operation);
    const inks = { color: theme.ink, borderColor: `${theme.sub}66` };
    return (
        <AppSurface theme={theme} className="px-3.5 py-3">
            {edit ? (
                <>
                    <Editable
                        value={lead.title}
                        onChange={(v) => edit.onPatch({ title: v })}
                        placeholder="Subject"
                        className="text-[13.5px] font-medium"
                        style={inks}
                    />
                    <div className="mt-1.5 flex items-baseline gap-2 pb-2.5">
                        <Editable
                            value={lead.author}
                            onChange={(v) => edit.onPatch({ author: v })}
                            placeholder="From"
                            className="w-32 text-[12px]"
                            style={{ color: theme.sub, borderColor: `${theme.sub}66` }}
                        />
                        <Editable
                            value={lead.handle}
                            onChange={(v) => edit.onPatch({ handle: v })}
                            placeholder="address"
                            className="font-mono text-[11px]"
                            style={{ color: theme.sub, borderColor: `${theme.sub}66` }}
                        />
                    </div>
                    <Editable
                        multiline
                        value={lead.body}
                        onChange={(v) => edit.onPatch({ body: v })}
                        placeholder="Body"
                        className="mt-1 text-[13px] leading-relaxed"
                        style={inks}
                    />
                </>
            ) : (
                <>
                    <p className="m-0 text-[13.5px] font-medium">{lead.title}</p>
                    <div
                        className="mt-1.5 flex items-baseline gap-2 border-b pb-2.5"
                        style={{ borderColor: theme.border }}
                    >
                        <span className="text-[12px] font-medium">{lead.author}</span>
                        <span className="min-w-0 truncate font-mono text-[11px]" style={{ color: theme.sub }}>
                            {lead.handle}
                        </span>
                        {lead.time && (
                            <span className="ml-auto shrink-0 font-mono text-[11px]" style={{ color: theme.sub }}>
                                {lead.time}
                            </span>
                        )}
                    </div>
                    {r && (r.pill || r.byline) && (
                        <p
                            className="m-0 mt-2 flex items-center gap-2 text-[11.5px]"
                            style={{ color: theme.sub }}
                        >
                            {r.pill && (
                                <span
                                    className="inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-[10.5px] font-semibold"
                                    style={{
                                        color: theme.accent,
                                        background: `${theme.accent}1f`,
                                        boxShadow: `inset 0 0 0 1px ${theme.accent}55`,
                                    }}
                                >
                                    {r.pill.label}
                                </span>
                            )}
                            {r.byline && <span>{conjugate(r.byline, lead.author)}</span>}
                        </p>
                    )}
                    <p className="mb-0 mt-2.5 text-[13px] leading-relaxed">{lead.body}</p>
                </>
            )}
        </AppSurface>
    );
}

/** Bespoke shapes edit via one themed field stack — the shape returns the
    moment editing ends, and the edit seam stays a single implementation. */
function ThemedEditStack({
    lead,
    theme,
    edit,
}: {
    lead: Scenario['lead'];
    theme: AppTheme;
    edit: LeadEdit;
}) {
    const inks = { color: theme.ink, borderColor: `${theme.sub}66` };
    const subInks = { color: theme.sub, borderColor: `${theme.sub}66` };
    return (
        <AppSurface theme={theme} className="px-3.5 py-3">
            <Editable
                value={lead.title}
                onChange={(v) => edit.onPatch({ title: v })}
                placeholder="Title"
                className="text-[13.5px] font-medium"
                style={inks}
            />
            <div className="mt-1.5 flex items-baseline gap-2">
                <Editable
                    value={lead.author}
                    onChange={(v) => edit.onPatch({ author: v })}
                    placeholder="From"
                    className="w-32 text-[12px]"
                    style={subInks}
                />
                <Editable
                    value={lead.handle}
                    onChange={(v) => edit.onPatch({ handle: v })}
                    placeholder="handle"
                    className="font-mono text-[11px]"
                    style={subInks}
                />
            </div>
            <Editable
                multiline
                value={lead.body}
                onChange={(v) => edit.onPatch({ body: v })}
                placeholder="Body"
                className="mt-2 text-[13px] leading-relaxed"
                style={inks}
            />
        </AppSurface>
    );
}

/* -------------------------------------------------------------- inbound */

function InboundEmail({ lead, edit }: { lead: Scenario['lead']; edit?: LeadEdit }) {
    if (edit) {
        return (
            <div>
                <Editable
                    value={lead.title}
                    onChange={(v) => edit.onPatch({ title: v })}
                    placeholder="Subject"
                    className="text-[13.5px] font-medium"
                />
                <div className="mt-1.5 flex items-baseline gap-2 pb-2.5">
                    <Editable
                        value={lead.author}
                        onChange={(v) => edit.onPatch({ author: v })}
                        placeholder="From"
                        className="w-32 text-[12px] text-foreground/60"
                    />
                    <Editable
                        value={lead.handle}
                        onChange={(v) => edit.onPatch({ handle: v })}
                        placeholder="address"
                        className="font-mono text-[11px] text-foreground/35"
                    />
                </div>
                <Editable
                    multiline
                    value={lead.body}
                    onChange={(v) => edit.onPatch({ body: v })}
                    placeholder="Body"
                    className="mt-1 text-[13px] leading-relaxed text-foreground/60"
                />
            </div>
        );
    }
    return (
        <div>
            <p className="m-0 text-[13.5px] font-medium">{lead.title}</p>
            <div className="mt-1.5 flex items-baseline gap-2 border-b border-foreground/8 pb-2.5">
                <span className="text-[12px] text-foreground/60">{lead.author}</span>
                <span className="min-w-0 truncate font-mono text-[11px] text-foreground/35">
                    {lead.handle}
                </span>
                <span className="ml-auto shrink-0 font-mono text-[11px] text-foreground/30">
                    {lead.time}
                </span>
            </div>
            <p className="mb-0 mt-2.5 text-[13px] leading-relaxed text-foreground/60">
                {lead.body}
            </p>
        </div>
    );
}

/** The staged situation, in the shape AND palette it would really arrive —
    and, when an edit seam is passed, editable inside that same shape. Generic
    triggers resolve their theme from the node type (iconSlug); apps with no
    theme keep the neutral structural frames. */
export function InboundMessage({ scenario, edit }: { scenario: Scenario; edit?: LeadEdit }) {
    const slug =
        scenario.provider === 'generic'
            ? (scenario as { iconSlug?: string }).iconSlug
            : scenario.provider;
    const theme = resolveAppTheme(slug);
    if (theme) {
        if (theme.shape === 'bubble')
            return (
                <ThemedBubbleIn
                    lead={scenario.lead}
                    theme={theme}
                    edit={edit}
                    operation={scenario.operation}
                />
            );
        if (theme.shape === 'row')
            return (
                <ThemedRowIn
                    lead={scenario.lead}
                    theme={theme}
                    edit={edit}
                    operation={scenario.operation}
                />
            );
        if (theme.shape === 'email')
            return (
                <ThemedEmailIn
                    lead={scenario.lead}
                    theme={theme}
                    edit={edit}
                    operation={scenario.operation}
                />
            );
        return edit ? (
            <ThemedEditStack lead={scenario.lead} theme={theme} edit={edit} />
        ) : (
            <BespokeInbound lead={scenario.lead} theme={theme} operation={scenario.operation} />
        );
    }
    // Chat + email providers always resolve a theme above; anything left is
    // an unthemed app — the neutral email-ish frame.
    return <InboundEmail lead={scenario.lead} edit={edit} />;
}

/* ------------------------------------------------------------- outbound */

type Artifact = NonNullable<Scenario['artifacts']>[number];

/** Email is a SHAPE, not a provider: gmail sends and the internal send-email
    node both carry a subject and belong in the envelope frame. The outcome's
    destination bar uses the same predicate so frame and bar never disagree. */
export function isEmailShaped(artifact: Artifact): boolean {
    return artifact.provider === 'gmail' || Boolean(artifact.subject);
}

function AgentByline({
    icons,
    to,
    mark,
    showGlyph = true,
    via = false,
}: {
    icons: Icons;
    to?: string;
    mark?: Mark;
    showGlyph?: boolean;
    /** Show the channel's mark even without a destination — "via Gmail". The
        frame must always say which app the message would leave through. */
    via?: boolean;
}) {
    return (
        <p className="m-0 flex flex-wrap items-baseline gap-2">
            {showGlyph && (
                <span className="inline-flex translate-y-0.5 items-center">
                    <Glyph mark={icons.agent} className="h-3.5 w-3.5" />
                </span>
            )}
            <span className="text-[13.5px] font-semibold">{AGENT_NAME}</span>
            <span className="rounded border border-foreground/12 px-1 py-px text-[10px] font-medium uppercase tracking-wide text-foreground/35">
                app
            </span>
            {(to || (via && (mark?.node || mark?.iconHtml))) && (
                <span className="inline-flex items-center gap-1.5 text-[11.5px] text-foreground/35">
                    {/* a bare "via" with no glyph reads as broken — senders
                        with no registered mark just omit the chip */}
                    {to ? `to ${to}` : 'via'} <Glyph mark={mark} className="h-3 w-3" />
                </span>
            )}
        </p>
    );
}

function OutboundSlack({
    icons,
    artifact,
    hideDestination = false,
}: {
    icons: Icons;
    artifact: Artifact;
    hideDestination?: boolean;
}) {
    return (
        <div className="flex gap-3">
            <div className="grid h-8 w-8 shrink-0 place-items-center rounded-lg border border-foreground/10 bg-foreground/[0.04]">
                <Glyph mark={icons.agent} className="h-4 w-4" />
            </div>
            <div className="min-w-0 flex-1">
                <AgentByline
                    icons={icons}
                    to={hideDestination ? undefined : artifact.to}
                    // The artifact's OWN mark, never a borrowed one — this
                    // frame hosts any non-chat sender (the send-email node
                    // wore the Slack logo here, 2026-08-10).
                    mark={icons[artifact.provider]}
                    showGlyph={false}
                    // Without a destination there is no bar above naming the
                    // channel — the byline must say "via <app>" itself.
                    via={!artifact.to}
                />
                <p className="mb-0 mt-1.5 whitespace-pre-wrap text-[13px] leading-relaxed text-foreground/85">
                    <ChatMarkup text={artifact.text} />
                </p>
            </div>
        </div>
    );
}

/** The agent's send as the app's OWN message: right-aligned bubble in the
    app's outbound color, on its chat wallpaper. */
function ThemedBubbleOut({
    icons,
    artifact,
    theme,
    hideDestination = false,
}: {
    icons: Icons;
    artifact: Artifact;
    theme: AppTheme;
    hideDestination?: boolean;
}) {
    return (
        <div>
            <AgentByline
                icons={icons}
                to={hideDestination ? undefined : artifact.to}
                mark={icons[artifact.provider]}
                via={!artifact.to}
            />
            <AppSurface theme={theme} className="mt-2 p-3">
                <div className="flex justify-end">
                    <div
                        className={cn('max-w-[88%] rounded-2xl px-3.5 py-2.5', tailClass(theme, 'out'))}
                        style={{ background: theme.bubbleOut }}
                    >
                        <p className="m-0 whitespace-pre-wrap text-[13px] leading-relaxed">
                            <ChatMarkup text={artifact.text} accent={theme.accent} />
                        </p>
                        {theme.ticks && (
                            <p className="m-0 mt-0.5 flex justify-end">
                                <CheckCheck className="h-3.5 w-3.5" style={{ color: theme.ticks }} />
                            </p>
                        )}
                    </div>
                </div>
            </AppSurface>
        </div>
    );
}

/** The agent's send as a message row on the app's surface (Slack/Discord/
    Teams — and any themed sender whose artifact is a plain message). */
function ThemedRowOut({
    icons,
    artifact,
    theme,
    hideDestination = false,
}: {
    icons: Icons;
    artifact: Artifact;
    theme: AppTheme;
    hideDestination?: boolean;
}) {
    return (
        <div>
            <AgentByline
                icons={icons}
                to={hideDestination ? undefined : artifact.to}
                mark={icons[artifact.provider]}
                showGlyph={false}
                via={!artifact.to}
            />
            <AppSurface theme={theme} className="mt-2 px-3.5 py-3">
                <div className="flex gap-2.5">
                    <span
                        className="grid h-8 w-8 shrink-0 place-items-center rounded-md"
                        style={{ background: `${theme.accent}26` }}
                    >
                        <Glyph mark={icons.agent} className="h-4 w-4" />
                    </span>
                    <div className="min-w-0 flex-1">
                        <p className="m-0 flex items-baseline gap-2">
                            <span className="text-[13px] font-semibold" style={{ color: theme.author }}>
                                {AGENT_NAME}
                            </span>
                            <span
                                className="rounded px-1 py-px text-[9.5px] font-semibold uppercase tracking-wide"
                                style={{ color: theme.sub, boxShadow: `inset 0 0 0 1px ${theme.border}` }}
                            >
                                app
                            </span>
                        </p>
                        <p className="mb-0 mt-0.5 whitespace-pre-wrap text-[13px] leading-relaxed">
                            <ChatMarkup text={artifact.text} accent={theme.accent} />
                        </p>
                    </div>
                </div>
            </AppSurface>
        </div>
    );
}

/** The agent's email in the reading pane it would land in. */
function ThemedEmailOut({
    icons,
    artifact,
    theme,
}: {
    icons: Icons;
    artifact: Artifact;
    theme: AppTheme;
}) {
    const hasEnvelope = Boolean(artifact.subject || artifact.to);
    return (
        <div>
            <AgentByline icons={icons} mark={icons[artifact.provider]} via />
            <AppSurface theme={theme} className="mt-2.5">
                {hasEnvelope && (
                    <div className="border-b px-3.5 py-2" style={{ borderColor: theme.border }}>
                        {artifact.subject && (
                            <p className="m-0 text-[13px] font-medium">{artifact.subject}</p>
                        )}
                        {artifact.to && (
                            <p
                                className={cn(
                                    'm-0 font-mono text-[11px]',
                                    artifact.subject && 'mt-0.5'
                                )}
                                style={{ color: theme.sub }}
                            >
                                To: {artifact.to}
                            </p>
                        )}
                    </div>
                )}
                {/* Email bodies are standard markdown, not chat dialect. */}
                <MarkdownRenderer
                    content={artifact.text}
                    className="px-3.5 py-2.5 text-[13px] leading-relaxed"
                />
            </AppSurface>
        </div>
    );
}

/** What would have gone out, in the shape AND palette it would really take. */
export function OutboundMessage({
    icons,
    artifact,
    hideDestination = false,
}: {
    icons: Icons;
    artifact: Artifact;
    hideDestination?: boolean;
}) {
    const theme = resolveAppTheme(artifact.provider);
    if (isEmailShaped(artifact)) {
        // Email is a shape: a themed email sender keeps its own palette, any
        // other email-shaped send (the internal send-email node) gets the
        // neutral white envelope theme.
        const emailTheme =
            theme?.shape === 'email' ? theme : resolveAppTheme('send_email')!;
        return <ThemedEmailOut icons={icons} artifact={artifact} theme={emailTheme} />;
    }
    if (theme?.shape === 'bubble')
        return (
            <ThemedBubbleOut
                icons={icons}
                artifact={artifact}
                theme={theme}
                hideDestination={hideDestination}
            />
        );
    if (theme)
        return (
            <ThemedRowOut
                icons={icons}
                artifact={artifact}
                theme={theme}
                hideDestination={hideDestination}
            />
        );
    // No theme — the plain neutral message frame with the sender's own mark.
    return <OutboundSlack icons={icons} artifact={artifact} hideDestination={hideDestination} />;
}
