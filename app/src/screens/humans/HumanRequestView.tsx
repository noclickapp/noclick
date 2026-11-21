// The page a person sees for a platform human request (/h/{id}): the sending
// account's brand around a question, an approval, an update or a conversation
// an agent handed to them (its transcript, a reply box, Hand back). NoClick's
// page renders it full-viewport and posts answers to its own action; the developer
// console renders it in `preview` (a contained frame that never posts) and
// reuses its answer form in the request drawer.
import { useEffect, useState, type FormEvent, type ReactNode } from 'react';
import { Check } from 'lucide-react';
import { cn } from '@/ui/utils';
import { LogoMark } from '@/ui/LogoMark';
import { Textarea } from '@/ui/textarea';
import { brandPresentation, type Brand } from '@/lib/brandPresentation';
import { BUTTON_PRIMARY, BUTTON_SECONDARY } from '@/ui/buttons';
import { TITLE } from '@/ui/requestTitle';

export type { Brand } from '@/lib/brandPresentation';
export { brandPresentation } from '@/lib/brandPresentation';

export const DEFAULT_BRAND: Brand = { name: 'NoClick', logo_url: null, color: null, support_url: null };

export type HumanRequestKind = 'ask' | 'approve' | 'notify' | 'hand_off';
export type HumanRequestStatus = 'pending' | 'answered' | 'delivered' | 'expired' | 'canceled';

/** An approval's answer (`approved`, its `text`), or a question's (`choice`, `text`; `choices` for a question of
 *  several). */
export interface HumanRequestAnswer {
    approved?: boolean;
    choice?: string | null;
    choices?: string[] | null;
    text?: string | null;
}

/** One message of a handed-off conversation, as its page shows it. */
export interface HandOffMessage {
    role: 'user' | 'assistant' | 'person';
    text: string;
    created_at: string | null;
}

/** A conversation an agent handed to this person: open while `active`, until it's handed back. */
export interface HandOff {
    status: 'active' | 'returned';
    agent: string | null;
    summary: string;
    returned_at: string | null;
    transcript: HandOffMessage[];
    /** Set when the conversation is an email thread: the address the person's replies are emailed to. */
    emailed_to?: string | null;
}

/** What the page needs of a request (the public view carries exactly this). */
export interface HumanRequestContent {
    kind: HumanRequestKind;
    message: string;
    options: string[];
    /** They may choose several of the options. */
    multiple?: boolean;
    details: Record<string, unknown>;
    status: HumanRequestStatus;
    answer: HumanRequestAnswer | null;
    /** A `hand_off` request's conversation. */
    handoff?: HandOff | null;
}

/** What the person submitted; `choices` are a question of several's ticked options; `decision` is the approval
 *  button they pressed. */
export interface AnswerFields {
    choice?: string;
    choices?: string[];
    text?: string;
    decision?: 'approve' | 'deny';
}

/** The body the answer routes take: a choice (or several) and/or text, or `approved` with an optional note. */
export function answerFromFields(fields: AnswerFields): Record<string, unknown> {
    const body: Record<string, unknown> = {};
    if (fields.choice) body.choice = fields.choice;
    if (fields.choices?.length) body.choices = fields.choices;
    if (fields.text?.trim()) body.text = fields.text;
    if (fields.decision === 'approve' || fields.decision === 'deny') body.approved = fields.decision === 'approve';
    return body;
}

export const EYEBROW: Record<HumanRequestKind, string> = {
    ask: 'Question',
    approve: 'Approval request',
    notify: 'Update',
    hand_off: 'Conversation',
};


/** The page a person opens from a link: the sender's name and mark over a single column on the app's own ground, no
 *  card around it (on a phone it is the whole screen). Full-viewport on the real page; `contained` sits inside a
 *  console frame or a mock phone; `wide` holds a live browser. A brand colour is one bar across the top. */
export function Shell({
    brand,
    children,
    contained = false,
    wide = false,
}: {
    brand: Brand;
    children: ReactNode;
    contained?: boolean;
    wide?: boolean;
}) {
    const { name, logoUrl, accent, supportUrl } = brandPresentation(brand);
    return (
        <div className={cn('flex flex-col bg-background text-foreground', !contained && 'min-h-dvh')}>
            {accent ? <div data-brand-accent aria-hidden className="h-1" style={{ backgroundColor: accent }} /> : null}
            <div className={cn('flex flex-1 justify-center px-5', contained ? 'py-7' : 'py-7 sm:items-center sm:py-16')}>
                <div className={cn('w-full', wide ? 'max-w-5xl' : 'max-w-[440px]')}>
                    <div className="mb-9 flex items-center gap-2 text-[13px] font-medium text-muted-foreground sm:mb-11">
                        {logoUrl ? (
                            <img src={logoUrl} alt="" referrerPolicy="no-referrer" className="h-[18px] w-[18px] rounded object-contain" />
                        ) : (
                            <LogoMark className="h-[18px] w-[18px]" />
                        )}
                        <span className="min-w-0 truncate">{name}</span>
                    </div>
                    {children}
                    {supportUrl ? (
                        <p className="mt-10 text-[12.5px] text-muted-foreground">
                            <a
                                href={supportUrl}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="underline-offset-2 hover:text-foreground hover:underline"
                            >
                                Questions? Contact {name}
                            </a>
                        </p>
                    ) : null}
                </div>
            </div>
        </div>
    );
}

const scalarRows = (values: Record<string, unknown>) =>
    Object.entries(values).filter(([, v]) => ['string', 'number', 'boolean'].includes(typeof v));

function DetailRows({ rows, label, className = 'mt-5' }: { rows: [string, unknown][]; label?: string; className?: string }) {
    return (
        <dl aria-label={label} className={cn('divide-y divide-border rounded-lg border border-border text-sm', className)}>
            {rows.map(([key, value]) => (
                <div key={key} className="flex gap-4 px-3 py-2">
                    <dt className="w-1/3 shrink-0 text-muted-foreground">{key}</dt>
                    <dd className="min-w-0 whitespace-pre-wrap break-words">{String(value)}</dd>
                </div>
            ))}
        </dl>
    );
}

/**
 * The request's scalar details as a key/value list (what the email shows too),
 * then an approval's `Arguments` (the held call's, one row each) as a table of their own.
 */
export function Details({ details }: { details: Record<string, unknown> }) {
    const rows = scalarRows(details);
    const shown = details.Arguments;
    const args = shown && typeof shown === 'object' && !Array.isArray(shown) ? scalarRows(shown as Record<string, unknown>) : [];
    if (!rows.length && !args.length) return null;
    return (
        <>
            {rows.length > 0 && <DetailRows rows={rows} />}
            {args.length > 0 && (
                <>
                    <p className="mt-5 text-xs font-semibold uppercase tracking-wider text-muted-foreground">Arguments</p>
                    <DetailRows rows={args} label="Arguments" className="mt-2" />
                </>
            )}
        </>
    );
}

/** "You approved this.", or the choice and text given. */
export function answerSummary(answer: HumanRequestAnswer | null, who = 'You'): string | null {
    if (answer?.approved !== undefined) {
        const verdict = `${who} ${answer.approved ? 'approved' : 'declined'} this.`;
        return answer.text ? `${verdict} ${answer.text}` : verdict;
    }
    return answer ? [answer.choice, answer.choices?.join(', '), answer.text].filter(Boolean).join(' — ') : null;
}

function Closed({ req }: { req: HumanRequestContent }) {
    const copy = {
        answered: { title: 'Thanks, your answer was sent', body: answerSummary(req.answer) },
        expired: { title: 'This request has expired', body: 'It can no longer be answered. Ask the sender for a new link.' },
        canceled: { title: 'This request was withdrawn', body: 'The sender no longer needs an answer.' },
    }[req.status as 'answered' | 'expired' | 'canceled'];
    return (
        <div className="text-center">
            {req.status === 'answered' ? (
                <div className="mx-auto mb-4 flex h-10 w-10 items-center justify-center rounded-full bg-foreground/[0.06]">
                    <Check className="h-5 w-5" />
                </div>
            ) : null}
            <h1 className={TITLE}>{copy.title}</h1>
            {copy.body ? <p className="mt-2 whitespace-pre-wrap text-[14px] leading-relaxed text-muted-foreground">{copy.body}</p> : null}
        </div>
    );
}

/** The capability pages' two buttons (this page's and the browser page's). */
export const primary = cn(BUTTON_PRIMARY, 'h-11 justify-center px-5 text-[14.5px]');
export const secondary = cn(BUTTON_SECONDARY, 'h-11 justify-center px-5 text-[14.5px]');

/**
 * The answer controls: options or a text box for a question, Approve / Deny
 * with an optional note for an approval. A native POST form, so the /h/{id}
 * page answers before (or without) hydration; once hydrated every submit goes
 * to `onAnswer` instead, and a preview (no `onAnswer`) submits nothing.
 */
export function AnswerForm({
    req,
    busy = false,
    onAnswer,
    className,
}: {
    req: Pick<HumanRequestContent, 'kind' | 'options' | 'multiple'>;
    busy?: boolean;
    onAnswer?: (fields: AnswerFields) => void;
    className?: string;
}) {
    const [choice, setChoice] = useState('');
    const [picked, setPicked] = useState<string[]>([]);
    const [text, setText] = useState('');
    // Server markup leaves Send enabled (`required` guards it); readiness gates it once hydrated.
    const [hydrated, setHydrated] = useState(false);
    useEffect(() => setHydrated(true), []);
    const hasOptions = req.kind === 'ask' && req.options.length > 0;
    // A question of several: any of its options, ticked as checkboxes (`choices`), in the order it offers them.
    const several = hasOptions && !!req.multiple;
    const chosen = several ? picked.length > 0 : !!choice;
    // A question's options are what most people pick; an answer in words takes its place, and beside a pick it's a note.
    const ready = chosen || !!text.trim();
    const noted = req.kind !== 'ask' || chosen;
    const textLabel = noted ? 'Add a note (optional)' : hasOptions ? 'Or answer in your own words' : 'Your answer';
    const toggle = (option: string) =>
        setPicked((was) => req.options.filter((o) => (o === option ? !was.includes(o) : was.includes(o))));
    const onSubmit = (e: FormEvent<HTMLFormElement>) => {
        e.preventDefault();
        const submitter = (e.nativeEvent as SubmitEvent).submitter;
        const pressed = submitter?.getAttribute('name') === 'decision' ? submitter.getAttribute('value') : null;
        const decision = pressed === 'approve' || pressed === 'deny' ? pressed : undefined;
        if (req.kind === 'approve' ? !decision : !ready) return;
        onAnswer?.(several ? { choices: picked, text, decision } : { choice: choice || undefined, text, decision });
    };
    return (
        <form method="post" onSubmit={onSubmit} className={cn('mt-6 space-y-3', className)}>
            {hasOptions ? (
                <div role={several ? 'group' : 'radiogroup'} aria-label={several ? 'Choose any' : undefined} className="space-y-2">
                    {several ? <p className="text-[13px] text-muted-foreground">Choose any that apply.</p> : null}
                    {req.options.map((option) => (
                        <label
                            key={option}
                            className="flex w-full cursor-pointer items-center justify-between gap-3 rounded-lg border border-border px-3 py-2.5 text-left text-sm transition-colors hover:bg-foreground/[0.04] has-[:checked]:border-foreground/40 has-[:checked]:bg-foreground/[0.08] has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring"
                        >
                            <input
                                type={several ? 'checkbox' : 'radio'}
                                name={several ? 'choices' : 'choice'}
                                value={option}
                                required={!several && !text.trim()}
                                checked={several ? picked.includes(option) : choice === option}
                                onChange={() => (several ? toggle(option) : setChoice(option))}
                                className="sr-only"
                            />
                            <span className="min-w-0">{option}</span>
                            {several && picked.includes(option) ? <Check aria-hidden className="h-4 w-4 shrink-0" /> : null}
                        </label>
                    ))}
                </div>
            ) : null}
            <Textarea
                name="text"
                aria-label={noted ? 'Note' : textLabel}
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder={textLabel}
                rows={hasOptions || req.kind === 'approve' ? 2 : 4}
                maxLength={4000}
                required={req.kind === 'ask' && !hasOptions}
            />
            {req.kind === 'approve' ? (
                <div className="flex gap-2">
                    <button type="submit" name="decision" value="approve" disabled={busy} className={cn(primary, 'flex-1')}>
                        Approve
                    </button>
                    <button type="submit" name="decision" value="deny" disabled={busy} className={cn(secondary, 'flex-1')}>
                        Deny
                    </button>
                </div>
            ) : (
                <button type="submit" disabled={busy || (hydrated && !ready)} className={cn(primary, 'w-full')}>
                    {busy ? 'Sending…' : 'Send answer'}
                </button>
            )}
        </form>
    );
}

/** How the person sees each side of a handed-off conversation. */
function speaker(role: HandOffMessage['role'], agent: string): string {
    return role === 'user' ? 'Them' : role === 'person' ? 'You' : agent;
}

/**
 * A conversation an agent handed to this person: its summary, the transcript,
 * a reply box (their reply joins the conversation) and Hand back. Both are
 * native POST forms carrying an `intent`, like the answer form; once hydrated
 * they go to `onReply` / `onHandBack`, and a preview submits nothing.
 */
export function HandOffView({
    request,
    busy = false,
    error,
    onReply,
    onHandBack,
}: {
    request: HumanRequestContent;
    busy?: boolean;
    error?: string | null;
    onReply?: (text: string) => void;
    onHandBack?: () => void;
}) {
    const [text, setText] = useState('');
    const handoff = request.handoff;
    const agent = handoff?.agent || 'the agent';
    const active = request.status === 'pending' && handoff?.status === 'active';
    const reply = (e: FormEvent<HTMLFormElement>) => {
        e.preventDefault();
        if (!text.trim()) return;
        onReply?.(text);
        setText('');
    };
    const handBack = (e: FormEvent<HTMLFormElement>) => {
        e.preventDefault();
        onHandBack?.();
    };
    return (
        <>
            <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{EYEBROW.hand_off}</p>
            <h1 className={cn(TITLE, 'mt-2')}>
                {active ? `${agent} handed this conversation to you` : `Handed back to ${agent}`}
            </h1>
            <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed">{handoff?.summary ?? request.message}</p>
            {handoff?.transcript.length ? (
                <ol aria-label="Conversation" className="mt-5 space-y-3 rounded-lg border border-border p-3">
                    {handoff.transcript.map((m, i) => (
                        <li key={i} className={cn('text-sm', m.role === 'person' && 'pl-6')}>
                            <span className="block text-xs font-medium text-muted-foreground">{speaker(m.role, agent)}</span>
                            <span className="whitespace-pre-wrap break-words">{m.text}</span>
                        </li>
                    ))}
                </ol>
            ) : null}
            {active ? (
                <>
                    <form method="post" onSubmit={reply} className="mt-5 space-y-3">
                        <input type="hidden" name="intent" value="reply" />
                        <Textarea
                            name="text"
                            aria-label="Your reply"
                            value={text}
                            onChange={(e) => setText(e.target.value)}
                            placeholder="Your reply"
                            rows={3}
                            maxLength={4000}
                            required
                        />
                        {handoff?.emailed_to ? (
                            <p className="text-xs text-muted-foreground">Your replies are emailed to {handoff.emailed_to}.</p>
                        ) : null}
                        <button type="submit" disabled={busy} className={cn(primary, 'w-full')}>
                            {busy ? 'Sending…' : 'Send reply'}
                        </button>
                    </form>
                    <form method="post" onSubmit={handBack} className="mt-2">
                        <input type="hidden" name="intent" value="hand_back" />
                        <button type="submit" disabled={busy} className={cn(secondary, 'w-full')}>
                            Hand back to {agent}
                        </button>
                    </form>
                </>
            ) : (
                <p className="mt-5 text-sm text-muted-foreground">
                    {request.status === 'expired'
                        ? `This hand-off ended, so the conversation went back to ${agent}.`
                        : `${agent} answers this conversation again.`}
                </p>
            )}
            {error ? <p className="mt-3 text-sm text-red-600 dark:text-red-400">{error}</p> : null}
        </>
    );
}

export interface HumanRequestViewProps {
    request: HumanRequestContent;
    brand: Brand;
    /** A contained frame that never posts (the console's brand preview). */
    preview?: boolean;
    busy?: boolean;
    error?: string | null;
    onAnswer?: (fields: AnswerFields) => void;
    /** A hand-off's reply, and its hand-back. */
    onReply?: (text: string) => void;
    onHandBack?: () => void;
}

export function HumanRequestView({ request, brand, preview = false, busy = false, error, onAnswer, onReply, onHandBack }: HumanRequestViewProps) {
    if (request.kind === 'hand_off') {
        return (
            <Shell brand={brand} contained={preview}>
                <HandOffView
                    request={request}
                    busy={busy}
                    error={error}
                    onReply={preview ? undefined : onReply}
                    onHandBack={preview ? undefined : onHandBack}
                />
            </Shell>
        );
    }
    const open = request.status === 'pending' || request.status === 'delivered';
    return (
        <Shell brand={brand} contained={preview}>
            {open ? (
                <>
                    <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{EYEBROW[request.kind]}</p>
                    <p className={cn(TITLE, 'mt-2 whitespace-pre-wrap')}>{request.message}</p>
                    <Details details={request.details} />
                    {request.status === 'pending' ? (
                        <AnswerForm req={request} busy={busy} onAnswer={preview ? undefined : onAnswer} />
                    ) : null}
                    {error ? <p className="mt-3 text-sm text-red-600 dark:text-red-400">{error}</p> : null}
                </>
            ) : (
                <Closed req={request} />
            )}
        </Shell>
    );
}
