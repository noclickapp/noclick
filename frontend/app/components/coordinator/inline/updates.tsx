// What NoClick handled without being asked, as one card: an entry per automation it looked into (its latest line
// showing, every note one tap away) and an entry for each other note, the newest first. A note that asks you
// something keeps its Answer within reach while the rest stay folded.
import { useState } from 'react';
import { ChevronDown, MessageSquareText } from 'lucide-react';
import { MarkdownRenderer } from '~/components/chat/MarkdownRendererLazy';
import { AutomationMark } from '~/components/shell/glyphs';
import { cn } from '~/lib/utils';
import { dayRange, shortWhen, whenAt } from '../format';
import { answerLinkOf, headlineOf, type UpdateEntry, type UpdateNote } from '../updates';
import { CARD, PILL_QUIET, PILL_SECONDARY, Rows } from './primitives';

const ENTRIES_FOLDED = 4;
const NOTES_SHOWN = 5;

function plural(n: number, word: string): string {
    return `${n} ${word}${n === 1 ? '' : 's'}`;
}

function Notes({ notes, now }: { notes: UpdateNote[]; now?: Date }) {
    const [all, setAll] = useState(false);
    const newest = [...notes].reverse();
    const shown = all ? newest : newest.slice(0, NOTES_SHOWN);
    return (
        <div className="space-y-4 pb-3.5 pl-7 pt-1">
            {shown.map((note, i) => (
                <div key={i}>
                    {note.sentAt && <p className="mb-1 text-[12px] text-muted-foreground">{whenAt(note.sentAt, now)}</p>}
                    <MarkdownRenderer content={note.text} className="text-[14px] leading-relaxed" />
                </div>
            ))}
            {notes.length > NOTES_SHOWN && (
                <button type="button" className={cn(PILL_QUIET, '-ml-3')} onClick={() => setAll((v) => !v)}>
                    {all ? 'Show fewer' : `Show ${plural(notes.length - NOTES_SHOWN, 'earlier update')}`}
                </button>
            )}
        </div>
    );
}

function Entry({ entry, open, onToggle, now }: { entry: UpdateEntry; open: boolean; onToggle: () => void; now?: Date }) {
    const latest = entry.notes[entry.notes.length - 1];
    const headline = headlineOf(latest.text, entry.automation);
    const answer = answerLinkOf(latest.text);
    const count = entry.notes.length;
    return (
        <div>
            {/* The whole row toggles (the button's ::after covers it); Answer sits above that layer, and the time
                keeps one column whether or not a row asks something. */}
            <div className="relative -mx-2 flex min-h-[52px] items-center gap-3 rounded-lg px-2 py-2 transition-colors hover:bg-foreground/[0.025] has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring">
                <span className="shrink-0">
                    {entry.automation ? <AutomationMark className="h-4 w-4" /> : <MessageSquareText className="h-4 w-4 text-foreground/45" strokeWidth={1.75} />}
                </span>
                <button type="button" aria-expanded={open} onClick={onToggle} className="min-w-0 flex-1 text-left after:absolute after:inset-0 after:content-[''] focus-visible:outline-none">
                    <span className="block truncate text-[14px] text-foreground">
                        {entry.automation ?? headline}
                        {entry.automation && count > 1 && <span className="text-muted-foreground"> · {plural(count, 'update')}</span>}
                    </span>
                    {entry.automation && <span className="block truncate text-[12.5px] text-muted-foreground">{headline}</span>}
                </button>
                {answer && (
                    <a href={answer} target="_blank" rel="noopener noreferrer" className={cn(PILL_SECONDARY, 'relative z-10 h-7 px-3 text-[12.5px]')}>
                        Answer
                    </a>
                )}
                {latest.sentAt && <span className="shrink-0 text-[12.5px] tabular-nums text-muted-foreground">{shortWhen(latest.sentAt, now)}</span>}
                <ChevronDown aria-hidden="true" className={cn('h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform', open && 'rotate-180')} />
            </div>
            {open && <Notes notes={entry.notes} now={now} />}
        </div>
    );
}

/** A run of NoClick's own notes: what it handled, by automation, newest first. */
export function UpdatesCard({ entries, now }: { entries: UpdateEntry[]; now?: Date }) {
    const [all, setAll] = useState(false);
    const [open, setOpen] = useState<ReadonlySet<string>>(() => new Set());
    const notes = entries.flatMap((e) => e.notes);
    const times = notes.flatMap((n) => (n.sentAt ? [n.sentAt] : []));
    const shown = all ? entries : entries.slice(0, ENTRIES_FOLDED);
    const toggle = (key: string) =>
        setOpen((prev) => {
            const next = new Set(prev);
            if (!next.delete(key)) next.add(key);
            return next;
        });
    return (
        <section className={cn(CARD, 'px-4 py-1')}>
            <Rows>
                {shown.map((entry) => (
                    <Entry key={entry.key} entry={entry} open={open.has(entry.key)} onToggle={() => toggle(entry.key)} now={now} />
                ))}
            </Rows>
            {entries.length > 1 && (
                <div className="flex items-center gap-2 pb-2 pt-0.5">
                    <span className="min-w-0 flex-1 truncate text-[12.5px] text-muted-foreground">
                        {[plural(notes.length, 'update'), times.length && dayRange(Math.min(...times), Math.max(...times), now)].filter(Boolean).join(' · ')}
                    </span>
                    {entries.length > ENTRIES_FOLDED && (
                        <button type="button" className={cn(PILL_QUIET, '-mr-3')} aria-expanded={all} onClick={() => setAll((v) => !v)}>
                            {all ? 'Show less' : `Show all ${entries.length}`}
                            <ChevronDown className={cn('h-3.5 w-3.5 transition-transform', all && 'rotate-180')} />
                        </button>
                    )}
                </div>
            )}
        </section>
    );
}
