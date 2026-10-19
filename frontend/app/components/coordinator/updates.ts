// What the coordinator says when nobody asked: a failed run it looked into, an agent that messaged it, work it
// finished. Each lands as a background note, and a run of them reads as one card instead of a wall: one entry per
// automation the notes are about (their `signal`), and each other note an entry of its own.
import type { AgentChatMessage } from '~/hooks/useAgentChat';

export interface UpdateRun {
    /** Index of the run's first note, where the card is drawn. */
    start: number;
    notes: AgentChatMessage[];
}

export interface UpdateNote {
    text: string;
    sentAt?: number;
}

export interface UpdateEntry {
    key: string;
    /** The automation the notes are about; absent for a note that names none. */
    automation?: string;
    /** Oldest first. */
    notes: UpdateNote[];
}

// A setup note carries its own card, so it never folds into the run.
function isNote(msg: AgentChatMessage): boolean {
    return !!msg.notification && !msg.isUser && !msg.error && !!msg.text && !msg.content?.length && !msg.setup;
}

/** The runs of notes that fold into a card, keyed by every index a run covers: any run about an automation, and
 *  any two notes or more in a row. A lone note that names no automation (a build you asked for, done) stays a
 *  message. */
export function updatesOf(messages: readonly AgentChatMessage[]): Map<number, UpdateRun> {
    const runs = new Map<number, UpdateRun>();
    let run: UpdateRun | null = null;
    const close = () => {
        if (run && (run.notes.length > 1 || run.notes.some((n) => n.signal))) {
            for (let i = run.start; i < run.start + run.notes.length; i++) runs.set(i, run);
        }
        run = null;
    };
    messages.forEach((msg, i) => {
        if (!isNote(msg)) return close();
        if (!run) run = { start: i, notes: [] };
        run.notes.push(msg);
    });
    close();
    return runs;
}

/** A run's entries, the most recently updated first. */
export function entriesOf(notes: readonly AgentChatMessage[]): UpdateEntry[] {
    const byAutomation = new Map<string, UpdateEntry>();
    const entries: UpdateEntry[] = [];
    notes.forEach((msg, i) => {
        const note = { text: msg.text, sentAt: msg.sentAt };
        const id = msg.signal?.workflow_id;
        if (!id) {
            entries.push({ key: msg.turnId ?? `note-${i}`, notes: [note] });
            return;
        }
        let entry = byAutomation.get(id);
        if (!entry) {
            entry = { key: id, automation: msg.signal!.workflow_name, notes: [] };
            byAutomation.set(id, entry);
            entries.push(entry);
        } else {
            // An automation's entry sits where its newest note is.
            entries.splice(entries.indexOf(entry), 1);
            entries.push(entry);
        }
        entry.notes.push(note);
    });
    return entries.reverse();
}

const URL = /https?:\/\/\S+/g;

/** A note's opening sentence as plain text, without the automation's name it so often starts with. */
export function headlineOf(text: string, automation?: string): string {
    const plain = text
        .replace(/!?\[([^\]]*)\]\([^)]*\)/g, '$1')
        .replace(URL, '')
        .replace(/[*_`#>]/g, '')
        .replace(/^\s*[-•]\s+/gm, '')
        .replace(/\s+/g, ' ')
        .trim();
    const sentence = /^.+?[.!?](?=\s|$)/.exec(plain)?.[0] ?? plain;
    if (!automation || !sentence.toLowerCase().startsWith(`${automation.toLowerCase()} `)) return sentence;
    const rest = sentence.slice(automation.length + 1);
    return rest.charAt(0).toUpperCase() + rest.slice(1);
}

const QUESTION = /https?:\/\/[^\s)]+\/b\/[\w-]+/;

/** The link to a builder question the note asks you to answer. */
export function answerLinkOf(text: string): string | undefined {
    return QUESTION.exec(text)?.[0];
}
