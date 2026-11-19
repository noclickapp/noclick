// How an agent's move between model connections reads in Work: an
// account as a sentence names it ("your work Claude plan", "NoClick’s key"), the line each move leaves in its
// conversation (switched, waiting for a plan's reset, back on), and its profile's line while a plan's limit has it on
// another. Times read on the reader's clock with AM/PM, as planWords says them; a line naming an account it can't find
// (the accounts not read yet, a connection since deleted) is NoClick's own, as it wrote it. Pure, so the words are
// tested apart from the views.
import type { ModelSwitchNote } from '@/lib/agentThread/thread';
import type { HarnessName } from 'noclick';
import { harnessLabel } from '../agents/harness';
import { NOCLICK_KEY, namesAccount, wayLabel, type ModelAccount } from './accounts';
import { clockAt } from './planWords';

const cap = (s: string) => s.slice(0, 1).toUpperCase() + s.slice(1);

/** An account as a sentence names it: "your Claude plan"; a name of one word before its kind ("your work Claude
 *  plan"), any other after it ("your Claude plan (rowan@example.com)"); "NoClick’s key". */
export function spokenAccount(a: ModelAccount): string {
    if (a.kind === 'noclick') return 'NoClick’s key';
    const kind = wayLabel(a);
    if (!a.name) return `your ${kind}`;
    return /^[\w-]{1,24}$/.test(a.name) ? `your ${a.name} ${kind}` : `your ${kind} (${a.name})`;
}

/** A connection by its ref (`modelConnection`'s), as a sentence names it: the account it is; null where it's none
 *  of `accounts` (or they aren't read yet). */
export function spokenRef(ref: string | null, accounts: readonly ModelAccount[] | undefined): string | null {
    if (ref === NOCLICK_KEY) return 'NoClick’s key';
    const held = ref ? accounts?.find((a) => namesAccount(a, ref)) : undefined;
    return held ? spokenAccount(held) : null;
}

/** The owner's say-so a switch names, and the channel it opens where their words are in one (else here, or their
 *  tap). */
export interface Told {
    text: string;
    channel: string | null;
}

/** A move's line: what happened in bold, who said so, and what changes where it moved to another harness. */
export interface SwitchWords {
    lead: string;
    told: Told | null;
    detail: string | null;
}

/** Who allowed a switch or made it, as its line names them: "told by you in #usage at 3:10 PM", "you allowed it". */
function toldOf(note: ModelSwitchNote, agentName: string, now: Date): Told | null {
    const evidence = note.grant?.evidence;
    const when = evidence?.at ? ` at ${clockAt(evidence.at, now)}` : '';
    if (note.grant?.source === 'cited' && evidence?.where === 'channel')
        return { text: `told by you in ${evidence.channelName ? `#${evidence.channelName}` : 'a channel'}${when}`, channel: evidence.channelId };
    if (note.grant?.source === 'cited') return { text: `told by you here${when}`, channel: null };
    if (note.grant?.source === 'asked') return { text: 'you allowed it', channel: null };
    if (note.by === 'owner') return { text: 'you moved it', channel: null };
    if (note.by === 'agent') return { text: note.reason ? `${agentName} switched: ${note.reason}` : `${agentName} switched`, channel: null };
    return null;
}

/** The line a move leaves in the conversation. `model` names a model as its harness's list does ("Opus 5.5"). */
export function switchWords(
    note: ModelSwitchNote,
    { accounts, agentName, model, now = new Date() }: { accounts: readonly ModelAccount[] | undefined; agentName: string; model: (harness: string, id: string) => string; now?: Date }
): SwitchWords {
    const until = note.resetsAt ? ` until ${clockAt(note.resetsAt, now)}` : '';
    if (note.state === 'waiting') {
        const out = spokenRef(note.connection, accounts);
        return { lead: out ? `${cap(out)} is out${until}` : note.lead, told: null, detail: note.picksUp ? `${agentName} picks this up then` : 'send it again once it’s back' };
    }
    const to = spokenRef(note.to, accounts);
    if (note.state === 'back_on') return { lead: to ? `Back on ${to}` : note.lead, told: null, detail: null };
    const limit = note.reason === 'limit' || !!note.resetsAt;
    const from = limit ? spokenRef(note.from, accounts) : null;
    const lead = !to || (limit && !from) ? note.lead : from ? `${cap(from)} used up. Now on ${to}${until}` : `Now on ${to}`;
    const moved = note.harnessFrom && note.harnessTo && note.harnessFrom !== note.harnessTo;
    const on = (harness: string, id: string | null) => `${harnessLabel(harness as HarnessName)}${id ? ` on ${model(harness, id)}` : ''}`;
    const detail = moved ? `${on(note.harnessTo!, note.modelTo)} instead of ${on(note.harnessFrom!, note.modelFrom)} · the conversation carries over` : null;
    return { lead, told: toldOf(note, agentName, now), detail };
}

/** The profile's line while a plan's limit has the agent on another connection: "On your personal Claude plan until
 *  3:20 PM, then back on your work Claude plan"; a connection no longer among the accounts by the name the platform
 *  gave it. */
export function switchedFromLine(
    { current, home, homeName, resetsAt }: { current: string | null; home: string; homeName: string | null; resetsAt: Date | null },
    accounts: readonly ModelAccount[],
    now: Date = new Date()
): string {
    const on = spokenRef(current, accounts) ?? current ?? 'its default account';
    const back = spokenRef(home, accounts) ?? homeName ?? home;
    return resetsAt ? `On ${on} until ${clockAt(resetsAt, now)}, then back on ${back}` : `On ${on} until ${back} is back`;
}
