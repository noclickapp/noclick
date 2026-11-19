// The box you write in, t3code's, on every page with an agent conversation (Work's, and the Chat page with NoClick):
// one card in the reading lane, menus and banners tucking out from behind its top edge. Its "+" adds files (picked,
// pasted, dropped, or sent before) and what a message points at (an automation, an account); / opens NoClick's commands
// and the ones its harness reports, @ its files, agents and people, $ the skills its harness reports, each only where
// there is something to offer. It carries the model control, and while the agent works, joining its turn (Enter) or
// queueing behind it (⌘Enter); with nothing typed, Stop. A question its harness asks opens over it; an approval it
// waits on turns what you type into a decline with your reasons. Scoped to one of its harness's subagents (`scope`), it
// writes to that subagent: words only, no commands, skills or queue, and Stop stays in the log's header.
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Bot, ChevronDown, CircleHelp, FileText, Loader2, Pencil, Sparkles, X } from 'lucide-react';
import { attachments, type AgentCommands, type Attachment, type HarnessRequest, type NoClick, type RequestDecision } from 'noclick';
import { COMPOSER_SURFACE, ComposerPrimaryButton } from '@/ui/composer';
import { ReferenceMark } from '@/ui/chat/references';
import { ComposerAddMenu, type ComposerSessionActions } from '@/ui/chat/ComposerAddMenu';
import type { ChatAttachment, ChatFile } from '@/ui/chat/useChatFiles';
import type { ChatReference } from '@/lib/agentThread/messages';
import { COMPOSER_SOURCES } from './composerSources';
import { composerPrimary } from '@/ui/composerPrimary';
import { ShortcutTooltip } from '@/ui/ShortcutTooltip';
import { cn } from '@/ui/utils';
import { ChoiceMark } from '../ui';
import { commandIn, MenuOverlay, mentionMenu, skillsMenu, slashCommands, slashMenu, type Control, type Menu, type Mentionable, type SlashCommand } from './menus';
import { DRAWER, INLINE, LANE, spent, TUCK, XS_BUTTON, XS_GHOST } from './styles';
import type { Queued, SendInput } from './useConversation';
import type { Step } from '@/lib/agentThread/thread';
import { subagentTask } from './Activity';

/** Something waiting in the box, sent with the next message: a file (uploading, then stored), what the message points
 *  at (an automation, an account), a skill, or one of its subagents the message is about (`Ask main about it`). */
export type Chip =
    | { key: string; kind: 'file'; name: string; preview?: string; attachment: Attachment | null; failed?: string }
    | { key: string; kind: 'reference'; name: string; reference: ChatReference }
    | { key: string; kind: 'skill'; name: string }
    | { key: string; kind: 'subagent'; name: string };

/** A file stored before (the "+" menu's files sent before), as a message carries it. */
export function attachmentOf(a: ChatAttachment): Attachment {
    const kind = a.mimeType.startsWith('image/') ? 'image' : a.mimeType.startsWith('video/') ? 'video' : a.mimeType.startsWith('audio/') ? 'audio' : 'file';
    return { id: a.resourceId, name: a.name, mimeType: a.mimeType, sizeBytes: a.sizeBytes, kind, url: a.url, voice: false, durationMs: null, peaks: null, createdAt: null, updatedAt: null, raw: {} };
}

const FILES_SHOWN = 30;

/** The account's files the "+" menu offers to send again, newest first, their names containing `query`. */
export async function accountFiles(client: NoClick, query: string): Promise<ChatFile[]> {
    return (await attachments({ query: query || undefined, limit: FILES_SHOWN, client })).flatMap((f) =>
        f.id ? [{ resourceId: f.id, url: f.url, name: f.name, mimeType: f.mimeType, sizeBytes: f.sizeBytes ?? 0, createdAt: String(f.raw.created_at ?? '') }] : []
    );
}

const referenceChip = (reference: ChatReference): Chip => ({ key: `ref:${reference.kind}:${reference.id}`, kind: 'reference', name: reference.label, reference });

/** A message about one of its subagents, as it's sent: what it's about, then what you wrote. */
export const aboutSubagent = (title: string, text: string): string => `About your subagent “${title}”:\n\n${text}`;

/** Its question over the box, as t3code asks one: options you pick with a click or their number key, and the box itself
 *  for an answer in your own words. Several questions go one at a time. It stops at about 40% of the screen: its
 *  question's first lines and its buttons stay put, the rest of the question and its options scroll, and the box
 *  under it stays in view. */
function QuestionPanel({ question, index, total, picked, onToggle, onDismiss }: { question: Record<string, unknown>; index: number; total: number; picked: string[]; onToggle: (label: string) => void; onDismiss: () => void }) {
    const [folded, setFolded] = useState(false);
    const options = Array.isArray(question.options) ? (question.options as { label?: string; description?: string }[]) : [];
    const multi = question.multi_select === true;
    return (
        <div role="dialog" aria-label="Its question" className="flex max-h-[40dvh] flex-col px-2 pb-2 pt-2">
            <div className="flex shrink-0 items-start gap-2 px-1.5">
                <CircleHelp className="mt-1 h-3.5 w-3.5 shrink-0 text-muted-foreground" strokeWidth={2} />
                <p className="max-h-[4.5rem] min-w-0 flex-1 overflow-y-auto text-sm leading-relaxed text-foreground/85 scrollbar-subtle [overflow-wrap:anywhere]">
                    {String(question.question ?? '')}
                    <span className="ml-1.5 text-xs text-muted-foreground">
                        {total > 1 && `${index + 1} of ${total} · `}
                        {multi ? 'Pick any' : 'Pick one'}, or type your own
                    </span>
                </p>
                <ShortcutTooltip label={folded ? 'Show the options' : 'Hide the options'}>
                    <button type="button" aria-label={folded ? 'Show the options' : 'Hide the options'} onClick={() => setFolded(!folded)} className={cn(XS_BUTTON, XS_GHOST, 'h-6 w-6 px-0')}>
                        <ChevronDown className={cn('h-3.5 w-3.5 transition-transform duration-200', folded && '-rotate-90')} strokeWidth={2} />
                    </button>
                </ShortcutTooltip>
                <ShortcutTooltip label="Skip the question">
                    <button type="button" aria-label="Skip the question" onClick={onDismiss} className={cn(XS_BUTTON, XS_GHOST, 'h-6 w-6 px-0')}>
                        <X className="h-3.5 w-3.5" strokeWidth={2} />
                    </button>
                </ShortcutTooltip>
            </div>
            {!folded && (
                <div className="mt-1 min-h-0 space-y-0.5 overflow-y-auto scrollbar-subtle" data-question-options>
                    {options.map((o) => {
                        const label = String(o.label ?? '');
                        const on = picked.includes(label);
                        return (
                            <button
                                key={label}
                                type="button"
                                role={multi ? 'checkbox' : 'radio'}
                                aria-checked={on}
                                onClick={() => onToggle(label)}
                                className={cn('flex w-full items-start gap-2.5 rounded-[18px] py-1.5 pl-2.5 pr-2 text-left transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/70', on ? 'text-foreground' : 'text-foreground/70 hover:bg-foreground/[0.04]')}
                            >
                                <ChoiceMark on={on} radio={!multi} className="mt-0.5" />
                                <span className="min-w-0 flex-1 [overflow-wrap:anywhere]">
                                    <span className="block text-sm font-medium">{label}</span>
                                    {o.description && <span className="block text-[11px] leading-4 text-muted-foreground">{o.description}</span>}
                                </span>
                            </button>
                        );
                    })}
                </div>
            )}
        </div>
    );
}

/** What runs beside the turn: its subagents, one line, as t3code's ThreadNow; it shows them in the log. Stop while
 *  their turn runs (one can outlive its turn's reply). */
function RunningBeside({ subagents, onShow, onStop }: { subagents: Step[]; onShow: () => void; onStop?: () => void }) {
    const [now, setNow] = useState(() => Date.now());
    useEffect(() => {
        const t = setInterval(() => setNow(Date.now()), 1000);
        return () => clearInterval(t);
    }, []);
    const [only] = subagents.length === 1 ? subagents : [];
    return (
        <div className="flex min-h-10 items-center gap-2.5 pl-4 pr-2 text-xs text-muted-foreground" data-testid="running-beside">
            <Bot className="h-3.5 w-3.5 shrink-0" strokeWidth={2} />
            {/* What each was given, cut to a line here and whole on hover. */}
            <ShortcutTooltip label={subagents.map(subagentTask).join(', ')}>
                <button type="button" onClick={onShow} className="min-w-0 truncate rounded-full text-left transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/70">
                    <span className="text-foreground/85">{only ? 'Running a subagent' : `Running ${subagents.length} subagents`}</span>
                    <span className="ms-1.5 text-muted-foreground/70">{only ? subagentTask(only) : subagents.map(subagentTask).join(', ')}</span>
                </button>
            </ShortcutTooltip>
            <span className="ml-auto flex shrink-0 items-center gap-2.5">
                {only && <span className="tabular-nums">{spent(now - only.at)}</span>}
                <button type="button" onClick={onShow} className={cn(INLINE, 'text-muted-foreground hover:text-foreground')}>
                    Show
                </button>
                {onStop && (
                    <button type="button" onClick={onStop} className={cn(INLINE, 'text-foreground')}>
                        Stop
                    </button>
                )}
            </span>
        </div>
    );
}

/** What waits for its turn to end, t3code's way: the bubbles it will become, dashed and unfilled, on the right. Take
 *  one back, or edit it in the box. */
function QueuedRows({ queued, working, onUnqueue, onEdit }: { queued: Queued[]; working: boolean; onUnqueue: (key: string) => void; onEdit: (q: Queued) => void }) {
    const [all, setAll] = useState(false);
    if (!queued.length) return null;
    const shown = all ? queued : queued.slice(-3);
    return (
        <div className="flex flex-col items-end gap-3 pb-4" data-testid="queued">
            {queued.length > shown.length && (
                <button type="button" onClick={() => setAll(true)} className="flex items-center gap-1 text-xs text-muted-foreground transition-colors hover:text-foreground">
                    Show all {queued.length} queued
                    <ChevronDown className="h-3 w-3" strokeWidth={2} />
                </button>
            )}
            {shown.map((q) => (
                <div key={q.key} className="group flex max-w-[80%] flex-col items-end" data-queued>
                    <div className={cn('rounded-2xl rounded-br-sm border border-dashed border-muted-foreground/40 px-3 py-2 text-sm leading-relaxed text-muted-foreground', q.command && 'font-mono text-xs')}>{q.text}</div>
                    <div className="mt-1 flex items-center gap-0.5 text-xs text-muted-foreground">
                        <span className="mr-1">{q.command ? 'Runs between turns' : working ? 'Queued' : 'Sending…'}</span>
                        <ShortcutTooltip label="Edit in the box">
                            <button type="button" aria-label="Edit in the box" onClick={() => onEdit(q)} className={cn(XS_BUTTON, XS_GHOST, 'h-6 w-6 px-0')}>
                                <Pencil className="h-3 w-3" strokeWidth={2} />
                            </button>
                        </ShortcutTooltip>
                        <ShortcutTooltip label="Remove">
                            <button type="button" aria-label="Remove" onClick={() => onUnqueue(q.key)} className={cn(XS_BUTTON, XS_GHOST, 'h-6 w-6 px-0')}>
                                <X className="h-3 w-3" strokeWidth={2} />
                            </button>
                        </ShortcutTooltip>
                    </div>
                </div>
            ))}
        </div>
    );
}

function ChipPill({ chip, onRemove }: { chip: Chip; onRemove: () => void }) {
    const uploading = chip.kind === 'file' && !chip.attachment && !chip.failed;
    return (
        <ShortcutTooltip label={chip.kind === 'file' ? chip.failed : undefined}>
            <span
                className={cn('inline-flex h-7 max-w-[300px] items-center gap-1.5 rounded-full bg-foreground/[0.05] pl-1.5 pr-0.5 text-xs text-foreground/85 ring-1 ring-inset ring-foreground/[0.06]', chip.kind === 'file' && chip.failed && 'ring-red-500/40')}
                data-chip={chip.kind}
            >
                {chip.kind === 'file' && chip.preview ? (
                    <img src={chip.preview} alt="" className="h-5 w-5 shrink-0 rounded-full object-cover" />
                ) : (
                    <span className="pl-0.5">
                        {uploading ? (
                            <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" strokeWidth={2} />
                        ) : chip.kind === 'reference' ? (
                            <span className="grid h-4 w-4 place-items-center text-foreground/70">
                                <ReferenceMark reference={chip.reference} />
                            </span>
                        ) : chip.kind === 'skill' ? (
                            <Sparkles className="h-3.5 w-3.5 text-muted-foreground" strokeWidth={2} />
                        ) : chip.kind === 'subagent' ? (
                            <Bot className="h-3.5 w-3.5 text-muted-foreground" strokeWidth={2} />
                        ) : (
                            <FileText className="h-3.5 w-3.5 text-muted-foreground" strokeWidth={2} />
                        )}
                    </span>
                )}
                <span className="truncate">{chip.kind === 'skill' ? `$${chip.name}` : chip.name}</span>
                <ShortcutTooltip label="Remove">
                    <button type="button" aria-label={`Remove ${chip.name}`} onClick={onRemove} className="grid h-6 w-6 shrink-0 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-foreground/[0.08] hover:text-foreground">
                        <X className="h-3 w-3" strokeWidth={2.25} />
                    </button>
                </ShortcutTooltip>
            </span>
        </ShortcutTooltip>
    );
}

export interface ComposerProps {
    /** Under the box: what it runs on (its account, where, its budget), as New agent's draft has it. */
    footer?: ReactNode;
    agentName: string;
    harnessLabel: string;
    working: boolean;
    /** The agent's own fields are in: until then nothing sends. */
    ready: boolean;
    commands: AgentCommands | null;
    queued: Queued[];
    /** What its harness waits on you for, oldest first. */
    requests: HarnessRequest[];
    subagents: Step[];
    /** Scrolls the log to its subagents. */
    onShowSubagents: () => void;
    /** Its files, agents and people for @, read the first time @ is typed; without it, @ is plain text. */
    mentionables?: () => Promise<Mentionable[]>;
    /** Which of NoClick's own commands its / offers (every one where absent): a page offers those it can run. */
    controls?: readonly Control[];
    /** The account's files the "+" menu offers to send again, newest first, their names containing `query`. */
    listFiles?: (query: string) => Promise<ChatFile[]>;
    /** Clearing its session and resuming an earlier one, as its "+" menu offers them. */
    session?: ComposerSessionActions;
    /** What the box says while it's empty, in place of the agent's line. */
    placeholder?: string;
    /** `tall` opens with room for a few lines, for a page whose point is the box (its "+" menu then opens below it). */
    size?: 'default' | 'tall';
    /** Takes the caret once it's ready, where that doesn't pop a phone keyboard. */
    focusOnReady?: boolean;
    /** The box's view-transition-name, so a layout change can move it as one piece. */
    transitionName?: string;
    /** The outer frame's spacing, for a page that lays the box out itself. */
    className?: string;
    /** The model control, beside the button (the shared picker). */
    model: ReactNode;
    /** In Send's place while the account it runs on can't run a turn (its key refused, its sign-in ended): what to
     *  connect again, and Enter opens it too. */
    ask?: { button: ReactNode; open: () => void } | null;
    /** What a `/control` opens, and its drawer if it draws one in the box; `args`, what was typed after it. */
    onControl: (control: Control, args?: string) => void;
    drawer: ReactNode;
    onSend: (input: SendInput) => Promise<boolean>;
    onStop: () => void;
    onUnqueue: (key: string) => Promise<Queued | null>;
    onAnswer: (request: HarnessRequest, decision: RequestDecision, options?: { note?: string; answers?: Record<string, string | string[]> }) => void;
    upload: (file: File) => Promise<Attachment>;
    /** Text put back in the box (a reverted message, an Ask NoClick), changing each time; with `subagent`, that
     *  subagent goes in it as what the next message is about, and with `references`, what it points at. */
    putBack?: { text: string; n: number; subagent?: string; references?: readonly ChatReference[] };
    /** Writing to one of its harness's subagents: where it goes (left of the foot, in the files' place), the box's
     *  line, and what Enter does while it works. */
    scope?: { lead: ReactNode; placeholder: string; hint?: string };
}

export function Composer(p: ComposerProps) {
    const [text, setText] = useState('');
    const [caret, setCaret] = useState(0);
    const [mod, setMod] = useState(false);
    const [dismissed, setDismissed] = useState<string | null>(null);
    const [active, setActive] = useState(0);
    const [chips, setChips] = useState<Chip[]>([]);
    const [dragging, setDragging] = useState(false);
    const [sending, setSending] = useState(false);
    const [mentionables, setMentionables] = useState<Mentionable[] | null>(null);
    const [asked, setAsked] = useState<{ id: string; index: number; picks: Record<string, string[]>; own: Record<string, string> }>({ id: '', index: 0, picks: {}, own: {} });
    const ref = useRef<HTMLTextAreaElement>(null);
    const card = useRef<HTMLDivElement>(null);

    // Put back as it opens too: words a page held for it before it was drawn.
    const [shownBack, setShownBack] = useState<ComposerProps['putBack']>(undefined);
    if (p.putBack !== shownBack) {
        setShownBack(p.putBack);
        if (p.putBack) {
            const about = p.putBack.subagent;
            const pointed = (p.putBack.references ?? []).map(referenceChip);
            setText(p.putBack.text);
            setCaret(p.putBack.text.length);
            if (about) setChips((c) => [...c.filter((x) => x.kind !== 'subagent'), { key: `subagent:${about}`, kind: 'subagent', name: about }]);
            if (pointed.length) setChips((c) => [...c.filter((x) => x.kind !== 'reference'), ...pointed]);
        }
    }
    useEffect(() => {
        if (p.putBack) ref.current?.focus();
    }, [p.putBack]);
    useEffect(() => {
        if (p.focusOnReady && p.ready && window.matchMedia('(pointer: fine)').matches) ref.current?.focus();
    }, [p.focusOnReady, p.ready]);

    const list = p.scope ? [] : slashCommands(p.commands, p.controls);
    const skills = !p.scope && !!p.commands?.skills.length;
    const typed = commandIn(list, text);
    const question = p.requests.find((r) => r.kind === 'question' && r.status === 'pending');
    const approval = p.requests.find((r) => r.kind === 'approval' && r.status === 'pending');
    const q = question && asked.id === question.id ? asked : { id: question?.id ?? '', index: 0, picks: {}, own: {} };
    const current = question?.questions[q.index];
    const currentId = current ? String(current.id ?? current.question ?? q.index) : '';
    const picked = q.picks[currentId] ?? [];
    const uploading = chips.some((c) => c.kind === 'file' && !c.attachment && !c.failed);
    const filled = !!text.trim() || chips.some((c) => (c.kind === 'file' && c.attachment) || c.kind === 'reference');
    const control = typed?.command.kind === 'control';
    const files = chips.some((c) => c.kind === 'file' && c.attachment);
    const primary = composerPrimary({
        question: !!question,
        scoped: !!p.scope,
        working: p.working,
        filled,
        ready: p.ready,
        uploading,
        sending,
        approval: !!approval && !!text.trim(),
        command: typed ? typed.command.kind : null,
        queueHeld: mod,
        // Files go with a message of their own: behind a running turn they wait for it.
        unsteerable: files,
        canStop: true,
        canSteer: true,
        canQueue: true,
    });
    const kind = primary.kind;

    const put = (value: string, at = value.length) => {
        setText(value);
        setCaret(at);
        setActive(0);
        requestAnimationFrame(() => {
            ref.current?.focus();
            ref.current?.setSelectionRange(at, at);
        });
    };

    const point = (reference: ChatReference) => {
        setChips((c) => (c.some((x) => x.kind === 'reference' && x.reference.kind === reference.kind && x.reference.id === reference.id) ? c : [...c, referenceChip(reference)]));
        requestAnimationFrame(() => ref.current?.focus());
    };
    const attachStored = (a: ChatAttachment) => setChips((c) => [...c, { key: `stored:${a.resourceId}`, kind: 'file', name: a.name, attachment: attachmentOf(a) }]);

    const attach = (files: FileList | File[]) => {
        if (p.scope) return;
        for (const file of Array.from(files)) {
            const key = `${file.name}:${file.size}:${Date.now()}:${Math.random()}`;
            const preview = file.type.startsWith('image/') && typeof URL.createObjectURL === 'function' ? URL.createObjectURL(file) : undefined;
            setChips((c) => [...c, { key, kind: 'file', name: file.name || 'Pasted file', preview, attachment: null }]);
            p.upload(file).then(
                (attachment) => setChips((c) => c.map((x) => (x.key === key && x.kind === 'file' ? { ...x, attachment } : x))),
                (e: unknown) => setChips((c) => c.map((x) => (x.key === key && x.kind === 'file' ? { ...x, failed: e instanceof Error ? e.message : 'It didn’t upload.' } : x)))
            );
        }
    };

    const toggleOption = (label: string) => {
        if (!question || !current) return;
        const multi = current.multi_select === true;
        const now = picked.includes(label) ? picked.filter((l) => l !== label) : multi ? [...picked, label] : [label];
        setAsked({ ...q, id: question.id, picks: { ...q.picks, [currentId]: now } });
    };

    const answerQuestion = (skip: boolean) => {
        if (!question) return;
        if (skip) {
            p.onAnswer(question, 'reject_once');
            setAsked({ id: '', index: 0, picks: {}, own: {} });
            return;
        }
        const own = { ...q.own, ...(text.trim() ? { [currentId]: text.trim() } : {}) };
        const next = { ...q, id: question.id, own };
        put('');
        if (q.index + 1 < question.questions.length) {
            setAsked({ ...next, index: q.index + 1 });
            return;
        }
        const answers: Record<string, string | string[]> = {};
        question.questions.forEach((qq, i) => {
            const id = String(qq.id ?? qq.question ?? i);
            const labels = next.picks[id] ?? [];
            const words = own[id];
            if (labels.length || words) answers[id] = words ? [...labels, words].join('; ') : labels;
        });
        p.onAnswer(question, 'allow_once', { answers });
        setAsked({ id: '', index: 0, picks: {}, own: {} });
    };

    const pickCommand = (c: SlashCommand) => {
        if (c.kind === 'control' && !c.hint) {
            put('');
            p.onControl(c.control);
            return;
        }
        put(`/${c.name} `);
    };

    const submit = async (queueIt: boolean) => {
        if (question) return answerQuestion(false);
        const value = text.trim();
        if (!value && !chips.some((c) => c.kind !== 'subagent')) return;
        if (uploading || sending) return;
        if (typed?.command.kind === 'control') {
            put('');
            return p.onControl(typed.command.control, typed.args);
        }
        if (approval && value && !typed) {
            put('');
            return p.onAnswer(approval, 'reject_once', { note: value });
        }
        if (p.ask && !p.working) return p.ask.open();
        const files = chips.flatMap((c) => (c.kind === 'file' && c.attachment ? [c.attachment] : []));
        const references = chips.flatMap((c) => (c.kind === 'reference' ? [c.reference] : []));
        const skill = chips.find((c) => c.kind === 'skill');
        const about = chips.find((c) => c.kind === 'subagent');
        const command = typed?.command.kind === 'harness' ? { name: typed.command.name, arguments: typed.args } : skill ? { name: skill.name, arguments: value } : undefined;
        const delivery = p.working && !p.scope ? (queueIt || command || files.length ? 'queue' : 'steer') : undefined;
        setSending(true);
        const before = { text, chips };
        put('');
        setChips([]);
        const ok = await p.onSend({ text: about && value ? aboutSubagent(about.name, value) : value, files, references, command, delivery });
        setSending(false);
        if (!ok) {
            setText(before.text);
            setChips(before.chips);
        }
    };

    // The menu open now, if any: / only where it has commands to offer.
    const slash = dismissed !== text && list.length ? /^\/(\S*)$/.exec(text)?.[1] : undefined;
    const mention = dismissed !== text && slash === undefined ? /(^|\s)([@$])([^\s@$]*)$/.exec(text.slice(0, caret)) : null;
    useEffect(() => {
        if (mention?.[2] === '@' && mentionables === null && p.mentionables) {
            p.mentionables().then(setMentionables, () => setMentionables([]));
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [mention?.[2]]);
    const takeMention = (m: Mentionable) => {
        const before = text.slice(0, caret).replace(/@[^\s@]*$/, `@${m.text} `);
        put(before + text.slice(caret), before.length);
    };
    const takeSkill = (name: string) => {
        const before = text.slice(0, caret).replace(/\$[^\s$]*$/, '');
        put(before + text.slice(caret), before.length);
        setChips((c) => [...c.filter((x) => x.kind !== 'skill'), { key: `skill:${name}`, kind: 'skill', name }]);
    };
    const menu: Menu | null =
        slash !== undefined
            ? slashMenu(list, p.commands, p.harnessLabel, slash, pickCommand)
            : mention?.[2] === '@' && p.mentionables
              ? mentionMenu(mentionables, mention[3], takeMention)
              : mention?.[2] === '$' && skills
                ? skillsMenu(p.commands, p.agentName, mention[3], takeSkill)
                : null;
    const items = menu?.items ?? [];

    const drawers: ReactNode[] = [];
    if (question && current)
        drawers.push(<QuestionPanel key={`${question.id}:${q.index}`} question={current} index={q.index} total={question.questions.length} picked={picked} onToggle={toggleOption} onDismiss={() => answerQuestion(true)} />);
    if (p.subagents.length) drawers.push(<RunningBeside key="beside" subagents={p.subagents} onShow={p.onShowSubagents} onStop={p.working ? p.onStop : undefined} />);

    const hint =
        !!text.trim() && !control && !question && !menu && (p.working || p.scope)
            ? approval && !typed
                ? 'Declines it, with your reasons'
                : p.scope
                  ? (p.scope.hint ?? null)
                  : kind === 'queue'
                    ? 'Goes after this turn'
                    : 'Joins what it’s doing now'
            : null;
    // What it says of what the box can do: only what there is to offer here.
    const offers = [p.mentionables && '@ files', skills && '$ skills', list.length && '/ commands'].filter(Boolean).join(', ');
    const placeholder = question
        ? 'Type your own answer, or leave this blank to use the selected option'
        : approval
          ? 'Send feedback to decline this request'
          : (p.scope?.placeholder ?? p.placeholder ?? `Ask ${p.agentName} anything${offers ? `. ${offers}` : ''}`);
    const lastQuestion = question ? q.index + 1 >= question.questions.length : true;

    return (
        <div className={cn('relative shrink-0 px-5 pb-4', p.className)}>
            <div aria-hidden className="pointer-events-none absolute inset-x-0 -top-2 h-2 bg-gradient-to-b from-transparent to-background" />
            <div className={LANE}>
                <QueuedRows
                    queued={p.queued}
                    working={p.working}
                    onUnqueue={(key) => void p.onUnqueue(key)}
                    onEdit={(item) => {
                        void p.onUnqueue(item.key).then((back) => back && put(back.text));
                    }}
                />
                {drawers.length > 0 && (
                    <div className={cn('wc-drawer relative z-0 mx-[1.375rem] divide-y divide-border/70 dark:divide-foreground/[0.06]', DRAWER)} style={{ marginBottom: -TUCK, paddingBottom: TUCK }}>
                        {drawers}
                    </div>
                )}
                <div className="relative">
                    {menu && <MenuOverlay menu={menu} active={Math.min(active, Math.max(items.length - 1, 0))} onActive={setActive} />}
                    {!menu && p.drawer}
                    <div
                        ref={card}
                        style={p.transitionName ? { viewTransitionName: p.transitionName } : undefined}
                        className={cn('relative z-10 rounded-[26px]', COMPOSER_SURFACE, 'dark:shadow-[inset_0_1px_0_hsl(var(--foreground)/0.04),0_14px_32px_-18px_rgb(0_0_0/0.75)]', dragging && 'ring-2 ring-foreground/30')}
                        onDragOver={(e) => {
                            if (!e.dataTransfer.types.includes('Files')) return;
                            e.preventDefault();
                            setDragging(true);
                        }}
                        onDragLeave={() => setDragging(false)}
                        onDrop={(e) => {
                            if (!e.dataTransfer.files.length) return;
                            e.preventDefault();
                            setDragging(false);
                            attach(e.dataTransfer.files);
                        }}
                    >
                        {chips.length > 0 && (
                            <div className="flex flex-wrap gap-1.5 px-3 pt-3">
                                {chips.map((c) => (
                                    <ChipPill key={c.key} chip={c} onRemove={() => setChips((all) => all.filter((x) => x.key !== c.key))} />
                                ))}
                            </div>
                        )}
                        <textarea
                            ref={ref}
                            value={text}
                            rows={1}
                            aria-label={`Message ${p.agentName}`}
                            onChange={(e) => {
                                setText(e.target.value);
                                setCaret(e.target.selectionStart);
                                setActive(0);
                            }}
                            onSelect={(e) => setCaret(e.currentTarget.selectionStart)}
                            onPaste={(e) => {
                                if (!e.clipboardData.files.length) return;
                                e.preventDefault();
                                attach(e.clipboardData.files);
                            }}
                            onKeyDown={(e) => {
                                if (e.key === 'Meta' || e.key === 'Control') setMod(true);
                                const enter = e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing;
                                if (menu && items.length) {
                                    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
                                        e.preventDefault();
                                        setActive((i) => (i + (e.key === 'ArrowDown' ? 1 : items.length - 1)) % items.length);
                                        return;
                                    }
                                    if (enter || e.key === 'Tab') {
                                        e.preventDefault();
                                        items[Math.min(active, items.length - 1)].pick();
                                        return;
                                    }
                                }
                                // A question's options answer to their number while the box is empty.
                                if (current && !text && /^[1-9]$/.test(e.key) && !e.metaKey && !e.ctrlKey) {
                                    const options = Array.isArray(current.options) ? (current.options as { label?: string }[]) : [];
                                    const option = options[Number(e.key) - 1];
                                    if (option) {
                                        e.preventDefault();
                                        toggleOption(String(option.label ?? ''));
                                        return;
                                    }
                                }
                                if (e.key === 'Escape' && menu) {
                                    e.preventDefault();
                                    setDismissed(text);
                                    return;
                                }
                                if (enter) {
                                    e.preventDefault();
                                    void submit(e.metaKey || e.ctrlKey);
                                }
                            }}
                            onKeyUp={(e) => {
                                if (e.key === 'Meta' || e.key === 'Control') setMod(false);
                            }}
                            onBlur={() => setMod(false)}
                            placeholder={placeholder}
                            className={cn('block max-h-52 min-h-[60px] w-full resize-none bg-transparent px-4 pb-1 pt-3.5 text-sm leading-relaxed outline-none [field-sizing:content] placeholder:text-muted-foreground/70', p.size === 'tall' && 'min-h-[68px] sm:min-h-[92px]')}
                        />
                        <div className="flex items-center gap-1 px-2 pb-2">
                            {p.scope ? (
                                p.scope.lead
                            ) : (
                                <ComposerAddMenu
                                    anchorRef={card}
                                    side={p.size === 'tall' ? 'bottom' : 'top'}
                                    onAddFiles={attach}
                                    listFiles={p.listFiles}
                                    onAttach={p.listFiles ? attachStored : undefined}
                                    onReference={point}
                                    session={p.session}
                                    sources={COMPOSER_SOURCES}
                                />
                            )}
                            <div className="ml-auto flex min-w-0 items-center justify-end gap-1">
                                {hint && <span className="mr-1 hidden whitespace-nowrap text-xs text-muted-foreground xl:inline">{hint}</span>}
                                <div className="flex min-w-0 items-center gap-0.5">{p.model}</div>
                                {kind === 'submit' ? (
                                    <button type="button" onClick={() => answerQuestion(false)} disabled={!picked.length && !text.trim()} className={cn('wc-swap h-8 shrink-0 rounded-full bg-foreground px-4 text-sm font-medium text-background shadow-[inset_0_1px_0_rgb(255_255_255/0.16)] transition-[transform,background-color] duration-150 hover:bg-foreground/90 active:scale-[0.97] disabled:cursor-not-allowed disabled:bg-foreground/[0.12] disabled:text-muted-foreground disabled:shadow-none')}>
                                        {lastQuestion ? 'Submit' : 'Next'}
                                    </button>
                                ) : p.ask && kind === 'send' ? (
                                    p.ask.button
                                ) : (
                                    <ComposerPrimaryButton
                                        kind={kind}
                                        size="sm"
                                        busy={sending}
                                        disabled={primary.disabled}
                                        onClick={(e) => (kind === 'stop' ? p.onStop() : void submit(kind === 'queue' || e.metaKey || e.ctrlKey))}
                                    />
                                )}
                            </div>
                        </div>
                    </div>
                </div>
                {p.footer && <div className="mt-1.5 px-1.5">{p.footer}</div>}
            </div>
        </div>
    );
}

