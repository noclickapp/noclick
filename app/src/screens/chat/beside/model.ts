// What the Chat page's Beside shows, derived from what the account's agents are at (atWork/model): every open ask as a
// Needs you entry with its one action (a held purchase or deletion, the account's cap, an account to connect, a start
// to try again), and the helpers at work (an app's coding agent, a child NoClick started) as Work's Beside items.
// Pure, so the card, the rail and the thread's own cards read one derivation.
import { browserItems, type BesideItem, type BesideStatus } from '@/screens/work/conversation/besideItems';
import type { Browser } from 'noclick';
import { heldAskOf, needsSentence, type Ask, type AtWork, type Part, type PartState, type Row } from '../atWork/model';
import type { HeldApproval } from '../atWork/types';

/** A helper: the agent NoClick handed work to, watched in its one session. */
export interface Helper {
    agentId: string;
}

/** One open ask. */
export interface NeedsYou {
    key: string;
    kind: Row['kind'];
    /** What it is, beside its action in a narrow list: "Buy morrowbakehouse.com?", "Delete tiktok?", "Monthly cap
     *  reached". */
    title: string;
    /** It said whole, where there's room: "Buying morrowbakehouse.com needs your OK", "Your $50 monthly cap paused
     *  Larkspur". */
    sentence: string;
    line: string | null;
    /** Its one action: a page, or a reply drafted to NoClick, which does it. */
    ask: Ask | null;
    /** The ids its card in the thread carries (an approval, an operation, an agent), where its title jumps. */
    refs: string[];
    /** The helper it waits on, opened where its card isn't in the thread. */
    helper: Helper | null;
    /** The agents the account's cap or balance holds. */
    held: string[];
    /** A held purchase's or deletion's approval, which its Review opens in place. */
    approval: HeldApproval | null;
}

export interface ChatBeside {
    needs: NeedsYou[];
    items: BesideItem[];
}

const helperOf = (part: Part | undefined): Helper | null => (part ? { agentId: part.agentId } : null);

const NEEDING: PartState[] = ['waiting', 'paused', 'failed'];

function needOf(row: Row): NeedsYou {
    const waiting = row.parts.filter((p) => NEEDING.includes(p.state));
    const part = waiting[0];
    // A held call's title already asks for an OK: its line is its price, or the kind of thing it deletes.
    const line = row.approval ? heldAskOf(row.approval).line : row.status || null;
    // Its card is the one that started what waits (a build's waiting child, not its siblings).
    const refs = row.approval || row.kind === 'automation' ? [row.key] : (waiting.length ? waiting : row.parts).flatMap((p) => [p.key, p.agentId, ...(p.stop ? [p.stop] : [])]);
    const said = needsSentence(row);
    return {
        key: row.key,
        kind: row.kind,
        title: said.short,
        sentence: said.long,
        line,
        ask: row.ask ?? null,
        refs: [...new Set(refs)],
        helper: row.kind === 'account' ? null : helperOf(part),
        held: row.kind === 'account' ? row.parts.map((p) => p.agentId) : [],
        approval: row.approval ?? null,
    };
}

const STATUS: Partial<Record<PartState, BesideStatus>> = { working: 'running', done: 'done' };

function itemOf(part: Part, status: BesideStatus, now: number): BesideItem {
    const startedAt = part.since ?? now;
    return {
        id: part.agentId,
        kind: 'agent',
        title: part.doing,
        status,
        startedAt,
        endedAt: status === 'running' ? null : now,
        activeAt: startedAt,
        line: part.status || null,
        call: null,
        turnRunning: false,
        agent: { agentId: part.agentId, name: part.agent, task: part.doing, jobId: part.stop ?? null },
        spendUsd: null,
    };
}

/** The asks, in the at-work order (what needs the person first), and the helpers working or done, then the chat's
 *  own browser. A helper that waits on the person is its ask, never a row of its own as well. */
export function besideOf(work: AtWork, now = Date.now(), browser: Browser | null = null): ChatBeside {
    const items = new Map<string, BesideItem>();
    for (const row of work.rows) {
        if (row.kind !== 'app' && row.kind !== 'agent') continue;
        for (const part of row.parts) {
            const status = STATUS[part.state];
            if (status && !items.has(part.agentId)) items.set(part.agentId, itemOf(part, status, now));
        }
    }
    return { needs: work.needs.map(needOf), items: [...items.values(), ...browserItems(browser, now)] };
}
