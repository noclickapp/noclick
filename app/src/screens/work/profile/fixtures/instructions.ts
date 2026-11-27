// An agent's instructions as the fake /v1 keeps them: GET /v1/agents/{id}/instructions with its versions, each with
// its unified diff from the one before, and PATCH /v1/agents/{id} with `instructions`, refused with a 409 when
// `if_instructions` names text that changed since. The first agent comes with three versions: its first kept, NoClick's
// change on the owner's word, and the owner's own edit, in use now. `raced`: NoClick changes them again just before
// the first save that names what it was made on, as a chat with NoClick would while someone edits on the page.
type Json = Record<string, unknown>;

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
const HOUR = 3_600_000;

export const FIRST = `Knows the Wirefern code and its customers.

## When a delivery fails
- Read the failed request in the logs before anything else.
- Retry it once. If it fails again, tell the customer what went wrong in one line.

## Changes to the code
- Work on a branch, run the tests and open a pull request. Never push to main.
- Ask me before you change billing or retries.

Answer customers in #support within the hour, plainly, and never promise a date.`;
export const SAID = 'When a delivery fails, have it check the dead-letter queue first, then the logs.';
const NOCLICKS = FIRST.replace('- Read the failed request in the logs before anything else.', '- Check the dead-letter queue first: most failed deliveries are waiting there.\n- Then read the failed request in the logs.');
export const IN_USE = NOCLICKS.replace('within the hour', 'within two hours');
/** What NoClick changes them to while someone edits (`raced`). */
export const RACED = IN_USE.replace('- Ask me before you change billing or retries.', '- Ask me before you change billing, retries or the webhook signatures.');
export const RACED_SAID = 'Make sure it asks me before touching the webhook signatures too.';

export async function digestOf(text: string): Promise<string> {
    const bytes = new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text)));
    return [...bytes].map((b) => b.toString(16).padStart(2, '0')).join('');
}

/** What `after` changed of `before`, as the API's unified diff (hunks only, two lines of context): the lines they
 *  share by a longest common subsequence, the rest added or removed. */
export function unifiedDiff(before: string, after: string): { diff: string | null; added: number; removed: number } {
    const a = before.split('\n');
    const b = after.split('\n');
    const lcs = a.map(() => new Array<number>(b.length + 1).fill(0));
    lcs.push(new Array<number>(b.length + 1).fill(0));
    for (let i = a.length - 1; i >= 0; i--) for (let j = b.length - 1; j >= 0; j--) lcs[i][j] = a[i] === b[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
    const ops: { mark: ' ' | '-' | '+'; text: string; old: number; new: number }[] = [];
    let i = 0;
    let j = 0;
    while (i < a.length || j < b.length) {
        if (i < a.length && j < b.length && a[i] === b[j]) ops.push({ mark: ' ', text: a[i++], old: i, new: ++j });
        else if (i < a.length && (j === b.length || lcs[i + 1][j] >= lcs[i][j + 1])) ops.push({ mark: '-', text: a[i++], old: i, new: j });
        else ops.push({ mark: '+', text: b[j++], old: i, new: j });
    }
    const changed = ops.map((op, k) => (op.mark !== ' ' ? k : -1)).filter((k) => k >= 0);
    if (!changed.length) return { diff: null, added: 0, removed: 0 };
    const out: string[] = [];
    let k = 0;
    while (k < changed.length) {
        const start = Math.max(0, changed[k] - 2);
        let end = changed[k];
        while (k < changed.length && changed[k] <= end + 4) end = changed[k++];
        const part = ops.slice(start, Math.min(ops.length, end + 3));
        const oldStart = part.find((op) => op.mark !== '+')?.old ?? part[0].old;
        const newStart = part.find((op) => op.mark !== '-')?.new ?? part[0].new;
        const olds = part.filter((op) => op.mark !== '+').length;
        const news = part.filter((op) => op.mark !== '-').length;
        out.push(`@@ -${oldStart},${olds} +${newStart},${news} @@`, ...part.map((op) => `${op.mark}${op.text}`));
    }
    return { diff: out.join('\n'), added: ops.filter((op) => op.mark === '+').length, removed: ops.filter((op) => op.mark === '-').length };
}

interface Kept {
    text: string;
    source: string;
    said: string | null;
    at: string;
}

export function instructionsFixture(agents: Json[], clock: number, options: { raced?: boolean } = {}) {
    const ago = (ms: number) => new Date(clock - ms).toISOString();
    const first = agents[0];
    // Each agent's versions, oldest first: the first agent's three; any other's none until a change.
    const kept = new Map<string, Kept[]>();
    if (first) {
        first.instructions = IN_USE;
        kept.set(String(first.id), [
            { text: FIRST, source: 'api', said: null, at: ago(12 * 24 * HOUR) },
            { text: NOCLICKS, source: 'coordinator', said: SAID, at: ago(3 * 24 * HOUR) },
            { text: IN_USE, source: 'app', said: null, at: ago(2 * HOUR) },
        ]);
    }
    let raced = options.raced === true;
    // The line under its name follows their first sentence, unless someone wrote it.
    const sentence = (text: string) => (/^.*?[.!?](\s|$)/.exec(text.split(/\s+/).join(' '))?.[0] ?? text).trim().replace(/[.!?]$/, '');
    const change = (agent: Json, text: string, source: string, said: string | null) => {
        kept.set(String(agent.id), [...(kept.get(String(agent.id)) ?? []), { text, source, said, at: new Date().toISOString() }]);
        if (typeof agent.role === 'string' && agent.role.replace(/\.$/, '') === sentence(String(agent.instructions))) agent.role = sentence(text);
        agent.instructions = text;
    };
    const read = async (agent: Json) => {
        const versions = (kept.get(String(agent.id)) ?? []).map((v, n, all) => {
            const { diff, added, removed } = n ? unifiedDiff(all[n - 1].text, v.text) : { diff: null, added: 0, removed: 0 };
            return { version: 40 + n, instructions: v.text, diff, added, removed, source: v.source, author: v.source === 'app' ? { user_id: 'usr_owner', key_id: 'key_console' } : null, said: v.said, restored_from: null, changed_at: v.at };
        });
        return { object: 'agent_instructions', agent_id: agent.id, instructions: agent.instructions, digest: await digestOf(String(agent.instructions)), versions: versions.reverse(), kept_days: 90 };
    };
    return {
        /** NoClick changes them, as a chat with NoClick on the owner's word would. */
        change: (agentId: string, text: string, said: string | null = null) => change(agents.find((a) => a.id === agentId)!, text, 'coordinator', said),
        /** The answer to a call about an agent's instructions; undefined for any other. */
        async answer(method: string, agent: Json, rest: string, body: Json): Promise<Response | undefined> {
            if (rest === '/instructions' && method === 'GET') return json(await read(agent));
            if (rest !== '' || method !== 'PATCH' || typeof body.instructions !== 'string') return undefined;
            if (body.if_instructions !== undefined && raced) {
                raced = false;
                change(agent, RACED, 'coordinator', RACED_SAID);
            }
            const now = String(agent.instructions);
            if (body.if_instructions !== undefined && body.if_instructions !== (await digestOf(now)) && body.instructions !== now)
                return json({ error: { type: 'conflict', message: 'Its instructions changed since this change was started from them, so nothing was changed.', field: 'instructions', instructions: now, digest: await digestOf(now) } }, 409);
            if (body.instructions !== now) change(agent, body.instructions, 'app', null);
            return undefined;
        },
    };
}
