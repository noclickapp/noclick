// An agent's instructions on its profile, under its name: their first lines with Show all, Edit and Ask NoClick; and
// the sheet a skill opens in from the same page, to read them whole, edit them and see each version before with what
// it changed. A save names the text it was made on (its digest), so a change NoClick or code made meanwhile is shown
// in the editor, beside yours, and never overwritten unseen. NoClick's own agents show no editor: NoClick writes them.
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { toast } from 'sonner';
import { Bot, Code2, History, Pencil, UserRound, Workflow, X } from 'lucide-react';
import { Agent, Conflict, type AgentInstructions, type AgentInstructionsVersion } from 'noclick';
import { invalidateV1 } from '@/sdk/useV1';
import { useSlot } from '@/slots';
import { DiffView } from '@/screens/resources/DiffView';
import { BUTTON_GHOST } from '@/ui/buttons';
import { LogoMark } from '@/ui/LogoMark';
import { HAIRLINE, relTime } from '@/ui/primitives';
import { cn } from '@/ui/utils';
import { useWorkClient } from '../client';
import { useWork } from '../context';
import { harnessLabel } from '../agents/harness';
import { AGENTS_KEY, STATES_KEY } from '../agents/reads';
import { Sheet } from '../resources/knowledge/AttachDialog';
import { AgentFace, AREA, ICON_BUTTON, SMALL_PRIMARY } from '../resources/knowledge/parts';
import { REPLY_MARKDOWN } from '../slots';
import { rereadAgent, useInstructions } from './reads';

const MAX_CHARS = 64_000;
// Past this the editor counts what's left.
const COUNT_FROM = 56_000;
const QUIET = 'inline-flex h-7 items-center gap-1.5 rounded-full px-2 text-[12.5px] font-medium text-muted-foreground transition-colors hover:bg-foreground/[0.05] hover:text-foreground';
const ASK_PILL = 'inline-flex h-7 items-center gap-1.5 rounded-full bg-foreground/[0.06] px-2.5 text-[12.5px] font-medium text-foreground/85 transition-colors hover:bg-foreground/[0.1] hover:text-foreground';
// Their headings read as a document's sections, at the text's own size, not as a page's titles.
const MARKDOWN =
    'text-[14px] leading-relaxed [&_h1]:mb-1 [&_h1]:mt-3 [&_h1]:text-[15px] [&_h1]:font-semibold [&_h2]:mb-1 [&_h2]:mt-3 [&_h2]:text-[14px] [&_h2]:font-semibold [&_h3]:mb-1 [&_h3]:mt-3 [&_h3]:text-[14px] [&_h3]:font-semibold';

type Mode = 'read' | 'edit';

const words = (text: string) => text.split(/\s+/).filter(Boolean).length;
/** Whether the line under its name is its instructions' first sentence (NoClick wrote it), not one someone wrote. */
const derived = (role: string, text: string) => text.split(/\s+/).join(' ').startsWith(role.replace(/…$/, '').trimEnd());
const lines = (n: number) => `${n} line${n === 1 ? '' : 's'}`;
/** How long ago, as a version's line says it. */
const ago = (at: Date) => {
    const said = relTime(at.toISOString(), new Date().toISOString());
    return said === 'now' ? 'just now' : said;
};

/** What a version changed, in a few words. */
function changedLines(v: AgentInstructionsVersion): string {
    if (!v.diff) return `${words(v.instructions)} words`;
    if (v.added && v.removed) return v.added === v.removed ? `${lines(v.added)} changed` : `${lines(v.added)} added, ${v.removed} removed`;
    return v.added ? `${lines(v.added)} added` : `${lines(v.removed)} removed`;
}

/** Who made a version, as its row says it. */
function whoMade(v: AgentInstructionsVersion): string {
    switch (v.source) {
        case 'app':
        case 'link':
            return 'You';
        case 'canvas':
            return 'You, on its canvas';
        case 'coordinator':
        case 'noclick':
            return v.said ? 'NoClick, on your word' : 'NoClick';
        case 'builder':
            return 'NoClick’s builder';
        case 'agent':
            return v.said ? 'An agent, on your word' : 'An agent';
        case 'restore':
            return v.restoredFrom ? `Restored from version ${v.restoredFrom}` : 'Restored';
        case 'baseline':
            return 'As first kept';
        default:
            return 'Your code';
    }
}

function WhoMark({ v }: { v: AgentInstructionsVersion }) {
    const box = 'grid h-7 w-7 shrink-0 place-items-center rounded-full bg-foreground/[0.06] text-foreground/75';
    if (v.source === 'coordinator' || v.source === 'noclick' || v.source === 'builder')
        return (
            <span className={box}>
                <LogoMark className="h-3.5 w-3.5" alt="" />
            </span>
        );
    const Icon = v.source === 'app' || v.source === 'link' ? UserRound : v.source === 'canvas' ? Workflow : v.source === 'agent' ? Bot : v.source === 'restore' || v.source === 'baseline' ? History : Code2;
    return (
        <span className={box}>
            <Icon className="h-3.5 w-3.5" strokeWidth={2} />
        </span>
    );
}

/** Under its name: its instructions' first lines (a line someone wrote by hand above them), Show all, Edit and Ask
 *  NoClick. NoClick's own agents, and one whose instructions the reader can't see, keep the line alone. */
export function InstructionsUnderName({ agent, name, role, kept }: { agent: Agent; name: string; role: string | null; kept: boolean }) {
    const { ask } = useWork();
    const MarkdownRenderer = useSlot(REPLY_MARKDOWN);
    const [sheet, setSheet] = useState<Mode | null>(null);
    const [clipped, setClipped] = useState(false);
    const box = useRef<HTMLDivElement>(null);
    const text = agent.instructions;
    useLayoutEffect(() => {
        const el = box.current;
        if (el) setClipped(el.scrollHeight > el.clientHeight + 1);
    }, [text]);
    // A helper NoClick made for an app takes its definition from each job it's handed.
    if (kept || !text || (agent.raw as { helper?: unknown }).helper === true)
        return (
            <>
                {role && <p className="mt-1 text-sm leading-snug text-muted-foreground">{role}</p>}
                {kept && <p className="mt-1.5 text-xs leading-snug text-muted-foreground">NoClick writes its instructions. Tell it how you like things and it keeps them in its memory.</p>}
            </>
        );
    return (
        <section data-testid="agent-instructions">
            {role && !derived(role, text) && <p className="mt-1 text-sm leading-snug text-muted-foreground">{role}</p>}
            <div ref={box} className="relative mt-2 max-h-[110px] cursor-pointer overflow-hidden" onClick={() => setSheet('read')}>
                <MarkdownRenderer content={text} className={cn(MARKDOWN, 'text-foreground/85')} />
                {clipped && <div aria-hidden className="pointer-events-none absolute inset-x-0 bottom-0 h-10 bg-gradient-to-b from-transparent to-background" />}
            </div>
            <div className="-ml-2 mt-1.5 flex flex-wrap items-center gap-1">
                <button type="button" onClick={() => setSheet('read')} className={QUIET}>
                    Show all
                </button>
                <button type="button" data-action="edit" onClick={() => setSheet('edit')} className={QUIET}>
                    <Pencil className="h-3.5 w-3.5" strokeWidth={2} />
                    Edit
                </button>
                {ask && (
                    <button type="button" onClick={() => ask(`Improve ${name}’s instructions: `)} className={ASK_PILL}>
                        <LogoMark className="h-3.5 w-3.5" alt="" />
                        Ask NoClick
                    </button>
                )}
            </div>
            {sheet && <InstructionsSheet agent={agent} name={name} start={sheet} onClose={() => setSheet(null)} />}
        </section>
    );
}

/** Its instructions whole, in the sheet a skill opens in: read, edited in place, and the versions before. */
export function InstructionsSheet({ agent, name, start, onClose }: { agent: Agent; name: string; start: Mode; onClose: () => void }) {
    const client = useWorkClient();
    const { ask } = useWork();
    const MarkdownRenderer = useSlot(REPLY_MARKDOWN);
    const read = useInstructions(agent.id);
    const history = read.data;
    const [mode, setMode] = useState<Mode>(start);
    const [base, setBase] = useState<{ text: string; digest: string } | null>(null);
    const [draft, setDraft] = useState('');
    const [saving, setSaving] = useState(false);
    const [refused, setRefused] = useState<string | null>(null);
    const text = history?.instructions ?? agent.instructions ?? '';
    const dirty = mode === 'edit' && base !== null && draft !== base.text;
    // Editing starts from them as read, with the digest a save names them by.
    useEffect(() => {
        if (mode === 'edit' && base === null && history) {
            setBase({ text: history.instructions, digest: history.digest });
            setDraft(history.instructions);
        }
    }, [mode, base, history]);
    // Escape closes, unless it would throw away an edit.
    useEffect(() => {
        const key = (e: KeyboardEvent) => {
            if (e.key === 'Escape' && !dirty && !document.querySelector('[role="dialog"], [role="menu"]')) onClose();
        };
        window.addEventListener('keydown', key);
        return () => window.removeEventListener('keydown', key);
    }, [onClose, dirty]);
    // Changed by someone else while you edit: shown beside yours until you choose.
    const theirs = mode === 'edit' && base && history && !saving && history.digest !== base.digest && history.instructions !== draft ? history : null;
    const edit = () => {
        setBase(null);
        setRefused(null);
        setMode('edit');
    };
    const stop = () => {
        setMode('read');
        setBase(null);
        setRefused(null);
    };
    const save = async (instructions: string, on: string, done: string) => {
        setSaving(true);
        setRefused(null);
        try {
            await Agent.fromId(agent.id, { client }).update({ instructions, ifInstructions: on });
        } catch (error) {
            // Changed meanwhile: read again, and the editor shows theirs beside yours.
            if (error instanceof Conflict) rereadAgent(agent.id);
            else setRefused(error instanceof Error ? error.message : String(error));
            return false;
        } finally {
            setSaving(false);
        }
        rereadAgent(agent.id);
        invalidateV1(AGENTS_KEY);
        invalidateV1(STATES_KEY);
        toast(done, { description: `${name} uses them from its next turn.` });
        return true;
    };
    const head = history?.versions[0];
    const harness = agent.harness;
    const coding = harness && harness !== 'sdk' ? harness : null;
    return (
        <Sheet onClose={() => !dirty && onClose()} testId="instructions-sheet">
            <div className={cn('flex h-12 shrink-0 items-center gap-2 border-b px-3 sm:px-4', HAIRLINE)}>
                <span className="truncate text-[13px] text-muted-foreground">Instructions</span>
                <button type="button" aria-label="Close" onClick={onClose} className={cn(ICON_BUTTON, 'ml-auto')}>
                    <X className="h-[18px] w-[18px]" />
                </button>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto scrollbar-subtle">
                <div className="px-5 pb-12 pt-6 sm:px-8">
                    <header className="flex flex-wrap items-start gap-4">
                        <AgentFace agent={{ id: agent.id, name }} size={40} />
                        <div className="min-w-0 flex-1">
                            <h2 className="truncate text-[22px] font-semibold leading-tight tracking-[-0.01em]">{name}’s instructions</h2>
                            <p className="mt-1 text-sm leading-snug text-muted-foreground">
                                It reads these on every turn. {words(text).toLocaleString()} words
                                {head?.changedAt && `, changed ${ago(head.changedAt)} by ${whoMade(head).replace(/^You\b/, 'you')}`}.
                            </p>
                        </div>
                        <div className="flex w-full items-center gap-2 sm:w-auto">
                            {mode === 'edit' ? (
                                <>
                                    <button type="button" onClick={stop} className={BUTTON_GHOST.replace('h-9', 'h-8')}>
                                        Cancel
                                    </button>
                                    <button
                                        type="button"
                                        disabled={!base || !dirty || saving || !draft.trim() || draft.length > MAX_CHARS || !!theirs}
                                        onClick={async () => base && (await save(draft, base.digest, `Saved ${name}’s instructions`)) && stop()}
                                        className={SMALL_PRIMARY}
                                    >
                                        {saving ? 'Saving…' : 'Save'}
                                    </button>
                                </>
                            ) : (
                                <>
                                    {ask && (
                                        <button type="button" onClick={() => ask(`Improve ${name}’s instructions: `)} className={ASK_PILL.replace('h-7', 'h-8')}>
                                            <LogoMark className="h-3.5 w-3.5" alt="" />
                                            Ask NoClick
                                        </button>
                                    )}
                                    <button type="button" onClick={edit} className={SMALL_PRIMARY}>
                                        <Pencil className="h-3.5 w-3.5" strokeWidth={2} />
                                        Edit
                                    </button>
                                </>
                            )}
                        </div>
                    </header>
                    {mode === 'edit' ? (
                        <section className="mt-6" data-testid="instructions-edit">
                            {theirs && (
                                <ChangedMeanwhile
                                    theirs={theirs}
                                    onKeepMine={() => setBase({ text: theirs.instructions, digest: theirs.digest })}
                                    onUseTheirs={() => {
                                        setBase({ text: theirs.instructions, digest: theirs.digest });
                                        setDraft(theirs.instructions);
                                    }}
                                />
                            )}
                            <textarea
                                aria-label={`${name}’s instructions`}
                                value={base ? draft : text}
                                disabled={!base}
                                onChange={(e) => setDraft(e.target.value)}
                                rows={Math.min(28, Math.max(12, (base ? draft : text).split('\n').length + 2))}
                                className={cn(AREA, 'text-[16px] sm:text-[14px]')}
                            />
                            {refused && <p className="mt-2 text-[13px] text-red-600 dark:text-red-400">{refused}</p>}
                            <p className="mt-2.5 text-xs leading-relaxed text-muted-foreground">
                                {name} uses the new ones from its next turn. Rules and tone go here; facts it should know, like opening hours or this week’s stock, go in its memory, and a way of doing a task goes in a skill.
                                {coding && ` ${harnessLabel(coding)} reads them as its own instructions file, beside any its repo has.`}
                            </p>
                            {draft.length > COUNT_FROM && (
                                <p className={cn('mt-1 text-xs tabular-nums', draft.length > MAX_CHARS ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground')}>
                                    {draft.length.toLocaleString()} of {MAX_CHARS.toLocaleString()} characters
                                </p>
                            )}
                        </section>
                    ) : (
                        <div className="mt-6" data-testid="instructions-read">
                            <MarkdownRenderer content={text} className={MARKDOWN} />
                        </div>
                    )}
                    <VersionHistory history={history} loading={read.data === undefined && read.error === undefined} editing={mode === 'edit'} onRestore={(v, n) => history && void save(v.instructions, history.digest, `Restored version ${n}`)} />
                </div>
            </div>
        </Sheet>
    );
}

/** What someone else changed while you edited: theirs is in use now, yours still unsaved; you choose. */
function ChangedMeanwhile({ theirs, onKeepMine, onUseTheirs }: { theirs: AgentInstructions; onKeepMine: () => void; onUseTheirs: () => void }) {
    const [shown, setShown] = useState(true);
    const change = theirs.versions[0];
    const when = change?.changedAt ? ago(change.changedAt) : 'just now';
    return (
        <div className="mb-3 rounded-2xl bg-foreground/[0.05] px-4 py-3.5" data-testid="instructions-changed" role="status">
            <p className="text-sm font-medium">
                {change ? whoMade(change).replace(', on your word', '') : 'Someone'} changed them {when}, while you were editing.
            </p>
            <p className="mt-0.5 text-[13px] leading-snug text-foreground/75">Theirs are in use now; yours are still here, unsaved. Neither is lost until you choose.</p>
            {change?.said && <p className="mt-1.5 text-[13px] text-foreground/85">“{change.said}”</p>}
            {shown && change?.diff && (
                <div className={cn('mt-2.5 overflow-hidden rounded-xl border bg-background', HAIRLINE)}>
                    <DiffView patch={change.diff} path="instructions.md" wrap />
                </div>
            )}
            <div className="mt-3 flex flex-wrap gap-2">
                <button type="button" onClick={onUseTheirs} className={SMALL_PRIMARY}>
                    Use theirs
                </button>
                <button type="button" onClick={onKeepMine} className={BUTTON_GHOST.replace('h-9', 'h-8')}>
                    Keep mine, replacing theirs
                </button>
                {change?.diff && (
                    <button type="button" onClick={() => setShown(!shown)} className={QUIET.replace('h-7', 'h-8')}>
                        {shown ? 'Hide their change' : 'Show their change'}
                    </button>
                )}
            </div>
        </div>
    );
}

/** The versions in which they changed, newest first: who made each and when, what it changed (opened to its diff),
 *  the owner's words NoClick made it on, and Restore. */
function VersionHistory({ history, loading, editing, onRestore }: { history: AgentInstructions | undefined; loading: boolean; editing: boolean; onRestore: (v: AgentInstructionsVersion, n: number) => void }) {
    const [open, setOpen] = useState<number | null>(null);
    const versions = history?.versions ?? [];
    return (
        <section className={cn('mt-8 border-t pt-5', HAIRLINE)} data-testid="instructions-history">
            <h3 className="text-[13px] font-medium text-muted-foreground">History</h3>
            {loading ? (
                <p className="mt-2 text-sm text-muted-foreground">Loading…</p>
            ) : !versions.length ? (
                <p className="mt-2 text-sm text-muted-foreground">Each change from now on is kept here, with what it changed.</p>
            ) : (
                <ul className="-mx-2.5 mt-2">
                    {versions.map((v, i) => (
                        <li key={v.version}>
                            <div className={cn('flex items-start gap-3 rounded-2xl px-2.5 py-2.5 transition-colors', open === v.version ? 'bg-foreground/[0.05]' : 'hover:bg-foreground/[0.03]')}>
                                <WhoMark v={v} />
                                <button type="button" onClick={() => setOpen(open === v.version ? null : v.version)} aria-expanded={open === v.version} className="min-w-0 flex-1 text-left">
                                    <span className="block text-sm font-medium">Version {versions.length - i}</span>
                                    <span className="block text-xs text-muted-foreground">
                                        {whoMade(v)}
                                        {v.changedAt && ` · ${ago(v.changedAt)}`} · {changedLines(v)}
                                    </span>
                                    {v.said && <span className="mt-1 block text-[13px] text-foreground/85">“{v.said}”</span>}
                                </button>
                                {i === 0 ? (
                                    <span className="pt-1 text-xs text-muted-foreground">In use</span>
                                ) : (
                                    !editing && (
                                        <button type="button" onClick={() => onRestore(v, versions.length - i)} className={QUIET}>
                                            <History className="h-3.5 w-3.5" strokeWidth={1.75} />
                                            Restore
                                        </button>
                                    )
                                )}
                            </div>
                            {open === v.version && (
                                <div className={cn('mb-2 ml-12 mr-2.5 mt-1 overflow-hidden rounded-xl border', HAIRLINE)}>
                                    {v.diff ? <DiffView patch={v.diff} path="instructions.md" wrap /> : <p className="whitespace-pre-wrap px-4 py-3 text-[13px] leading-relaxed text-foreground/85">{v.instructions}</p>}
                                </div>
                            )}
                        </li>
                    ))}
                </ul>
            )}
            {history && <p className="mt-2 text-xs text-muted-foreground">Versions are kept {history.keptDays} days; the one in use always.</p>}
        </section>
    );
}
