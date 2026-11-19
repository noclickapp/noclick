// What a new agent gets from its job until the person picks: its harness (live/coder.py's rule for work on code, over
// the AI accounts the account holds; NoClick's own agent for anything else), its name (after the app event that wakes
// it, else the job's words) and what wakes it (an app the job names and that app's event sharing the most words, a
// schedule, its inbox). A heuristic over the platform's real catalog; the person can change every part.
import type { HarnessName } from 'noclick';
import type { ModelAccount } from './accounts';

export const CODING = /\b(code|coding|repo|repos|pull requests?|PRs?|bugs?|tests?|deploy|refactor|github)\b/i;

/** live/coder.py's choose, for work on code: an Anthropic key runs Claude Code; else a ChatGPT plan or an OpenAI key
 *  runs Codex; else a Claude plan alone runs Claude Code; else Codex on NoClick's key. Anything else: NoClick's agent. */
export function harnessFor(job: string, accounts: readonly ModelAccount[]): HarnessName {
    if (!CODING.test(job)) return 'sdk';
    const has = (kind: ModelAccount['kind']) => accounts.some((a) => a.kind === kind && a.connected);
    if (has('anthropic_key')) return 'claude_code';
    if (has('chatgpt_plan') || has('openai_key')) return 'codex';
    if (has('claude_plan')) return 'claude_code';
    return 'codex';
}

const unique = (base: string, taken: readonly string[]) => {
    let name = base;
    for (let n = 2; taken.includes(name); n++) name = `${base} ${n}`;
    return name;
};

/** A name from the job's words: "Helpdesk", "Reviewer", "Daily numbers"…, kept unique. */
export function nameFor(job: string, taken: readonly string[]): string {
    const domain = job.match(/[\w.+-]+@([a-z0-9-]+)\./i)?.[1];
    const title = (w: string) => w.charAt(0).toUpperCase() + w.slice(1);
    const pick = /whats ?app/i.test(job)
        ? 'WhatsApp'
        : domain && /support|customer|refund|e-?mails?|inbox/i.test(job)
          ? `${title(domain)} support`
          : /pull requests?|\bPRs?\b|review/i.test(job)
            ? 'Reviewer'
            : /signups|revenue|payments|metrics|numbers/i.test(job)
              ? 'Daily numbers'
              : /report|summary|digest/i.test(job)
                ? 'Reports'
                : /support|customer|refund/i.test(job)
                  ? 'Helpdesk'
                  : /\b(e-?mails?|inbox)\b/i.test(job)
                    ? 'Inbox'
                    : CODING.test(job)
                      ? 'Coder'
                      : 'Assistant';
    return unique(pick, taken);
}

// ── what wakes it ───────────────────────────────────────────────────────────

/** An app with events an agent can wake on, from GET /v1/integrations. */
export interface EventApp {
    integration: string;
    /** Its name as the rest of NoClick says it ("GitHub"). */
    label: string;
    /** The node type it acts through, which draws its mark (GitHub's is `automation-github-rest`). */
    nodeType: string;
    events: { name: string; label: string }[];
}

/** One way it wakes: a built-in or an app's event, with its settings, and why NoClick proposed it if it did. */
export interface Wake {
    key: string;
    label: string;
    builtin?: 'schedule' | 'inbox' | 'webhook' | 'noclick';
    integration?: string;
    app?: string;
    /** Its app's node type, for its mark. */
    nodeType?: string;
    event?: string;
    settings: Record<string, string>;
    why?: string;
}

export const wakeTitle = (w: Wake) => (w.app ? `${w.app} · ${w.label}` : w.label);

/** "pull_request_opened" → "Pull request opened". */
export const eventWords = (name: string) => {
    const words = name.replace(/^on[\s_]+/i, '').replace(/_/g, ' ').trim();
    return words.charAt(0).toUpperCase() + words.slice(1).toLowerCase();
};

export const fromEvent = (app: EventApp, event: EventApp['events'][number]): Wake => ({ key: `${app.integration}:${event.name}`, label: event.label, integration: app.integration, app: app.label, nodeType: app.nodeType, event: event.name, settings: {} });

/** The platform's own ways to wake an agent besides a message and an app's event. */
export const BUILT_INS: { key: string; builtin: NonNullable<Wake['builtin']>; label: string; detail: string; choices?: { label: string; value: string }[] }[] = [
    {
        key: 'b:schedule',
        builtin: 'schedule',
        label: 'On a schedule',
        detail: 'in your timezone',
        choices: [
            { label: 'Every weekday at 9:00', value: '0 9 * * 1-5' },
            { label: 'Every hour', value: '0 * * * *' },
            { label: 'Mondays at 8:00', value: '0 8 * * 1' },
            { label: 'Every day at 18:00', value: '0 18 * * *' },
        ],
    },
    { key: 'b:inbox', builtin: 'inbox', label: 'Emails to its inbox', detail: 'its own address, made with it' },
    { key: 'b:webhook', builtin: 'webhook', label: 'A webhook', detail: 'its own URL, made with it' },
    {
        key: 'b:noclick',
        builtin: 'noclick',
        label: 'A NoClick event',
        detail: 'a run fails, an agent asks you something',
        choices: [
            { label: 'A run fails', value: 'workflow.run.failed' },
            { label: 'An agent asks you something', value: 'agent.asked_owner' },
        ],
    },
];

export const fromBuiltIn = (b: (typeof BUILT_INS)[number]): Wake => ({ key: b.key, label: b.label, builtin: b.builtin, settings: b.choices ? { choice: b.choices[0].value } : {} });

const STOP = new Set('a an the to of for and or in on at it its every time when whenever each new my our me us with from by is are be this that then any all send email emails customer customers someone'.split(' '));
const stem = (w: string) => w.toLowerCase().replace(/[^a-z0-9]/g, '').replace(/(ing|ed|es|s)$/, '');

/** What its job says should wake it: an app it names and that app's event sharing the most words; a schedule; its
 *  inbox. */
export function inferWakes(job: string, apps: readonly EventApp[]): Wake[] {
    const out: Wake[] = [];
    const words = job.toLowerCase();
    for (const app of apps) {
        const name = app.label.toLowerCase();
        if (name.length < 3 || !new RegExp(`\\b${name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\b`).test(words)) continue;
        const tokens = [...new Set(job.split(/\s+/).map(stem).filter((t) => t && !STOP.has(t) && t !== stem(name)))];
        let best: { event: EventApp['events'][number]; score: number; hits: string[] } | null = null;
        for (const event of app.events) {
            const own = event.label.split(/\s+/).map(stem);
            const hits = tokens.filter((t) => own.includes(t));
            const score = hits.length * 2 - (own.length - hits.length) * 0.5;
            if (hits.length && (!best || score > best.score)) best = { event, score, hits };
        }
        if (best) out.push({ ...fromEvent(app, best.event), why: `it names ${app.label} and “${best.hits.join('”, “')}”` });
    }
    if (/every (weekday|day|morning|monday|hour|week)|daily|weekly|\bat \d/i.test(job)) out.push({ ...fromBuiltIn(BUILT_INS[0]), why: 'it runs on a schedule' });
    if (/\binbox\b|emails? (to|at|sent to) [\w.+-]+@/i.test(job)) out.push({ ...fromBuiltIn(BUILT_INS[1]), why: 'it answers an inbox' });
    return out;
}

/** An agent named after the app event that wakes it, kept unique: "Stripe · Payment failed" → "Stripe payments",
 *  "GitHub · Pull request opened" → "GitHub pull requests". None for a built-in. */
export function nameFromEvent(w: Wake, taken: readonly string[]): string | null {
    if (!w.app) return null;
    const words = w.label.split(/\s+/).filter((x) => !/^(new|on|any|custom)$/i.test(x));
    const last = words[words.length - 1] ?? '';
    const noun = (/(ed|sent|paid|won|lost)$/i.test(last) && words.length > 1 ? words.slice(0, -1) : words).slice(-2).map((x) => x.toLowerCase());
    if (!noun.length) return w.app;
    const end = noun[noun.length - 1];
    noun[noun.length - 1] = end.endsWith('s') ? end : end.endsWith('y') ? `${end.slice(0, -1)}ies` : `${end}s`;
    return unique(`${w.app} ${noun.join(' ')}`, taken);
}
