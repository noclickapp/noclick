// Which AI account a model runs on: the model connections the account holds (a key or a plan, as GET /v1/connections
// lists them) and NoClick's own key, with the rules the backend applies (agents/compiler.py: PLAN_HARNESSES,
// plan_serves, serving_integrations; the harness catalog's `integrations` and `noclickKey`), so the picker says why
// one can't run a model before the create is refused. The backend still judges; these only explain.
import type { Connection, HarnessInfo, HarnessName, JsonObject, Plan, PlanUsageSummary } from 'noclick';
import { addedLabel } from '@/lib/formatters';
import { fixWordCasing } from '@/lib/credentialLabels';
import { standing } from '@/slots';
import { CONNECTION_MARK } from '@/ui/slots';
import { harnessLabel } from '../agents/harness';

/** An AI credential's kind, as Connections lists them: a key, or a subscription sign-in. */
export type AccountKind = 'anthropic_key' | 'claude_plan' | 'openai_key' | 'chatgpt_plan' | 'openrouter_key' | 'key';

/** One account an agent's model can run on: a model connection, or NoClick's own key. */
export interface ModelAccount {
    /** What `modelConnection` takes: the connection's name, or `noclick`. */
    id: string;
    kind: AccountKind | 'noclick';
    /** The model provider (`anthropic`, `openai`, `openrouter`, …); null for NoClick's key. */
    integration: string | null;
    /** The provider's own label ("OpenRouter"), for a key of a provider without its own kind. */
    providerLabel: string | null;
    /** The name it was given, where it tells it apart ("work"); null for one named after its provider. */
    name: string | null;
    /** What tells it apart: who it signed in as, still waiting for its key, or signed out. */
    note: string;
    connected: boolean;
    /** `connected`, `pending` (never connected) or `disconnected` (signed out, or its key revoked). */
    status?: string;
    /** Who it signed in as (the provider's name for the account), kept while it's signed out. */
    email?: string | null;
    /** Why a disconnected one stopped working, as the platform says it (`GET /v1/connections`' `disconnected`). */
    down?: Down | null;
    /** The connection's id as frames name it (a plan's usage is re-read on its `usage` frame), and as a ref names it
     *  (`connection:<id>`). */
    connectionId?: string;
    /** The account's access to it: its own (`owner`), or shared with it (`edit`, `view`). */
    access?: 'owner' | 'edit' | 'view';
    /** A Claude or ChatGPT plan's tier ("Ultra", "Plus") and why it runs nothing, when it doesn't. */
    plan?: Plan | null;
    /** A plan's usage over every window, as NoClick last read it; null until a reading exists. */
    usage?: PlanUsageSummary | null;
}

/** Why an account stopped working: its provider refused its key, its sign-in ended, or it was disconnected. */
export interface Down {
    reason: 'refused' | 'signed_out' | 'revoked';
    message: string;
}

const DOWN_WORDS: Record<Down['reason'], string> = { refused: 'refused', signed_out: 'signed out', revoked: 'disconnected' };

/** A connection's `disconnected`, read; null while it works. */
export function downOf(raw: unknown): Down | null {
    if (!raw || typeof raw !== 'object') return null;
    const d = raw as JsonObject;
    const reason = d.reason === 'refused' || d.reason === 'signed_out' || d.reason === 'revoked' ? d.reason : null;
    return reason ? { reason, message: typeof d.message === 'string' ? d.message : '' } : null;
}

/** What a disconnected account says after its name: "refused", "signed out", "disconnected"; null while it works. */
export const downWord = (a: Pick<ModelAccount, 'status' | 'down'>): string | null => (a.status === 'disconnected' ? DOWN_WORDS[a.down?.reason ?? 'revoked'] : null);

export const NOCLICK_KEY = 'noclick';
export const NOCLICK_KEY_ACCOUNT: ModelAccount = { id: NOCLICK_KEY, kind: 'noclick', integration: null, providerLabel: null, name: null, note: 'At what the model costs, from your balance', connected: true };

/** A key, by the company Connections lists it under ("Claude key"). */
const keyKind = (credentialType: string, integration: string) => ({
    // Read as it's drawn, so it names the company whoever shows Work fills in (`connection.mark`).
    get label() {
        return `${standing(CONNECTION_MARK).aiCompany(credentialType) ?? fixWordCasing(integration.charAt(0).toUpperCase() + integration.slice(1))} key`;
    },
    credentialType,
    integration,
});

export const ACCOUNT_KINDS: Record<Exclude<AccountKind, 'key'>, { label: string; credentialType: string; integration: string }> = {
    anthropic_key: keyKind('agent_anthropic', 'anthropic'),
    claude_plan: { label: 'Claude plan', credentialType: 'agent_claude_code_oauth', integration: 'anthropic' },
    openai_key: keyKind('agent_openai', 'openai'),
    chatgpt_plan: { label: 'ChatGPT plan', credentialType: 'agent_codex_oauth', integration: 'openai' },
    openrouter_key: keyKind('agent_openrouter', 'openrouter'),
};

const KIND_OF_TYPE = new Map(Object.entries(ACCOUNT_KINDS).map(([kind, k]) => [k.credentialType, kind as AccountKind]));
const PLAN_HARNESSES: Record<'claude_plan' | 'chatgpt_plan', HarnessName[]> = { claude_plan: ['claude_code'], chatgpt_plan: ['codex', 'opencode', 'hermes', 'openclaw'] };

/** The model connections among the account's connections, as accounts; `models` are the model providers' names. One
 *  wears a name only beside another of its kind, the one that tells them apart as Connections does (accountNames.ts):
 *  who it's signed in as, else the name given it where the others don't share it, else when it was added ("Claude
 *  key · work", "Claude plan · rowan@…"). A key saved in the app goes by its `credential:<id>`: an agent takes it by
 *  that, never by the name it was saved under. */
export function accountsOf(connections: readonly Connection[], models: ReadonlySet<string>, labels: ReadonlyMap<string, string> = new Map()): ModelAccount[] {
    const kinded = connections
        .filter((c) => models.has(c.integration))
        .map((c) => ({ c, kind: KIND_OF_TYPE.get(c.credentialType ?? '') ?? KIND_OF_INTEGRATION[c.integration] ?? ('key' as AccountKind) }));
    return kinded.map(({ c, kind }) => {
        const same = kinded.filter((k) => k.kind === kind && k.c.integration === c.integration);
        const who = c.account ?? null;
        const status = c.status ?? (c.connected ? 'connected' : 'pending');
        const down = downOf((c.raw as JsonObject).disconnected);
        const ownName = !c.name.startsWith('credential:') && same.filter((k) => k.c.name === c.name).length === 1 ? c.name : null;
        const name = same.length > 1 ? (who ?? ownName ?? (c.createdAt ? addedLabel(c.createdAt.toISOString()) : c.name)) : null;
        const working = isPlanAccount({ kind }) ? 'Signed in' : 'Key saved';
        return {
            id: c.origin === 'app' ? c.id : c.name,
            kind,
            integration: c.integration,
            providerLabel: labels.get(c.integration) ?? null,
            name,
            // Who it is goes under it, unless its name says so already.
            note: c.connected ? (who && who !== name ? who : working) : status === 'disconnected' ? (down?.message || 'Signed out') : 'Waiting for its key',
            connected: c.connected,
            status,
            email: who,
            down,
            connectionId: c.id,
            access: c.access ?? 'owner',
            ...(isPlanAccount({ kind }) ? { plan: c.plan, usage: c.usageSummary } : {}),
        };
    });
}

const KIND_OF_INTEGRATION: Record<string, AccountKind> = { anthropic: 'anthropic_key', openai: 'openai_key', openrouter: 'openrouter_key' };

/** Whose model it is, read from its id as the harness names it: Claude Code's are Anthropic's, Codex's OpenAI's, the
 *  rest say it (`anthropic/…`, `openrouter/…`). */
export function makerOf(harness: HarnessName, model: string): string {
    if (harness === 'claude_code') return 'anthropic';
    if (harness === 'codex') return 'openai';
    const head = model.split('/')[0].toLowerCase();
    if (model.includes('/')) return head;
    if (/^(claude|opus|sonnet|haiku)/i.test(model)) return 'anthropic';
    if (/^(gpt|o\d|codex)/i.test(model)) return 'openai';
    return head;
}

const kindLabel = (a: ModelAccount) => (a.kind === 'noclick' ? 'NoClick’s key' : a.kind === 'key' ? `${a.providerLabel ?? a.integration} key` : ACCOUNT_KINDS[a.kind].label);

/** Why this account can't run a harness on a model, or null when it can; `label` is the model as a person reads it
 *  ("GPT-6 Luna"), never its id. */
export function accountRefusal(account: ModelAccount, harness: HarnessInfo, model: string, label: string): string | null {
    const name = harnessLabel(harness.name);
    if (account.kind === 'noclick') {
        if (harness.name === 'sdk') return null;
        const key = noclickKeyOf(harness);
        if (!key.runs) return key.why ?? `${name} doesn’t run on NoClick’s key`;
        // NoClick's key reaches OpenRouter, so OpenCode runs OpenRouter's models on it.
        return harness.name === 'opencode' && !model.startsWith('openrouter/') ? 'On NoClick’s key OpenCode runs OpenRouter’s models' : null;
    }
    if (!account.connected) return account.status === 'disconnected' ? account.down?.message || 'Signed out' : 'Waiting for its key';
    const maker = makerOf(harness.name, model);
    // A plan whose tier runs nothing ("Claude Free doesn't include Claude Code.") says so, whatever the pick.
    if (account.plan?.refusal) return account.plan.refusal;
    if (account.kind === 'claude_plan') return PLAN_HARNESSES.claude_plan.includes(harness.name) ? null : 'A Claude plan runs only Claude Code';
    if (account.kind === 'chatgpt_plan') return harness.name === 'codex' || (PLAN_HARNESSES.chatgpt_plan.includes(harness.name) && maker === 'openai') ? null : 'A ChatGPT plan runs Codex, or OpenAI’s models in OpenCode, Hermes and OpenClaw';
    if (account.integration && harness.integrations.length && !harness.integrations.includes(account.integration)) return `${name} doesn’t take ${articleOf(account)} ${kindLabel(account)}`;
    // A key runs the models whose ids name its provider: an OpenRouter key `openrouter/…`, never another way's id.
    if (account.integration === maker) return null;
    return `${articleOf(account) === 'an' ? 'An' : 'A'} ${kindLabel(account)} runs ${account.providerLabel ?? account.integration}’s models, not ${label}`;
}

const articleOf = (a: ModelAccount) => (/^[aeiou]/i.test(kindLabel(a)) ? 'an' : 'a');

/** Whether NoClick's own key runs a harness (the harness catalog's `noclickKey`), and why not. */
export function noclickKeyOf(harness: HarnessInfo): { runs: boolean; models: string[]; why: string | null } {
    return harness.name === 'sdk' ? { runs: true, models: [], why: null } : harness.noclickKey;
}

/** The accounts to choose from on a harness: those held, then NoClick's key where it reaches the harness. */
export const accountChoices = (held: readonly ModelAccount[], harness: HarnessInfo): ModelAccount[] => (noclickKeyOf(harness).runs ? [...held, NOCLICK_KEY_ACCOUNT] : [...held]);

/** Whether `ref` (an agent's model connection, or one its `modelSwitching.allowed` names) is this account: its id, or
 *  `connection:<its connection's id>`. */
export const namesAccount = (a: ModelAccount, ref: string): boolean => a.id === ref || (!!a.connectionId && ref === `connection:${a.connectionId}`);

/** The kinds of key a coding harness runs on: Claude Code on Claude's, Codex on ChatGPT's, the others on these and
 *  OpenRouter's. */
const CODING_KEYS: readonly AccountKind[] = ['anthropic_key', 'openai_key', 'openrouter_key'];

/** What an agent on `harness` may move between when a plan runs out (backend agents/model_switch.py): the account's own
 *  model connections (never one shared with it) that run a coding harness (a plan whose tier runs one, a Claude,
 *  ChatGPT or OpenRouter key), then NoClick's key where it runs the agent's harness (Codex, OpenCode). */
export function switchChoices(accounts: readonly ModelAccount[], harness: HarnessInfo): ModelAccount[] {
    const own = accounts.filter((a) => a.connected && (a.access ?? 'owner') === 'owner' && (isPlanAccount(a) ? !a.plan || (a.plan.runs.length > 0 && !a.plan.refusal) : CODING_KEYS.includes(a.kind as AccountKind)));
    return harness.name !== 'sdk' && noclickKeyOf(harness).runs ? [...own, NOCLICK_KEY_ACCOUNT] : own;
}

/** The way to a model an account runs it by: the first of `routes` (each id that reaches the model, the pick's own
 *  first) it can run, else null. */
export function routeFor(account: ModelAccount, harness: HarnessInfo, routes: string | readonly string[]): string | null {
    return (typeof routes === 'string' ? [routes] : routes).find((r) => !accountRefusal(account, harness, r, r)) ?? null;
}

/** The account it runs on: the one preferred while it still runs the model (by any of its `routes`), else the first
 *  that does, else none. */
export function firstUsable(held: readonly ModelAccount[], harness: HarnessInfo, routes: string | readonly string[], prefer?: string | null): ModelAccount | null {
    const list = accountChoices(held, harness).filter((a) => routeFor(a, harness, routes));
    return list.find((a) => a.id === prefer) ?? list[0] ?? null;
}

/** The account an agent moving onto `harness` takes, asking only where there's a real choice: the one it runs on now
 *  while that runs the pick, else the one of yours that does; several of yours to choose from; none of yours, NoClick's
 *  key where it runs the pick (NoClick's own runtime always takes it); else none, so one is connected first. */
export type SwitchAccount = { account: ModelAccount } | { choose: ModelAccount[] } | { connect: true };

export function switchAccount(held: readonly ModelAccount[], harness: HarnessInfo, routes: string | readonly string[], current?: string | null): SwitchAccount {
    const yours = held.filter((a) => routeFor(a, harness, routes));
    const kept = yours.find((a) => a.id === current);
    if (kept) return { account: kept };
    if (harness.name === 'sdk') return { account: NOCLICK_KEY_ACCOUNT };
    if (yours.length === 1) return { account: yours[0] };
    if (yours.length > 1) return { choose: yours };
    const key = accountChoices([], harness).find((a) => routeFor(a, harness, routes));
    return key ? { account: key } : { connect: true };
}

/** What a pick with no account of its own runs on: NoClick's own runtime on NoClick's key (its connection left unset
 *  is NoClick's), any other harness on `first`, the first of yours that runs it. */
export const runsUnpicked = (harness: HarnessInfo, first: ModelAccount | null): ModelAccount | null => (harness.name === 'sdk' ? NOCLICK_KEY_ACCOUNT : first);

/** The harness a plan moves an agent to when it lands where the agent would run another (its first), or null where
 *  `account` isn't a plan or runs `harness` already. */
export function planHarness(account: ModelAccount, harness: HarnessName): HarnessName | null {
    if (account.kind !== 'claude_plan' && account.kind !== 'chatgpt_plan') return null;
    const runs = PLAN_HARNESSES[account.kind];
    return runs.includes(harness) ? null : runs[0];
}

/** Whether an account is a Claude or ChatGPT plan (a sign-in), not a key. */
export const isPlanAccount = (a: Pick<ModelAccount, 'kind'> | null | undefined): boolean => a?.kind === 'claude_plan' || a?.kind === 'chatgpt_plan';
/** A plan's product ("Claude"), else its provider ("OpenRouter"). */
const whoOf = (a: ModelAccount) => (a.kind === 'claude_plan' ? 'Claude' : a.kind === 'chatgpt_plan' ? 'ChatGPT' : (a.providerLabel ?? a.integration ?? 'it'));
const withArticle = (words: string) => `${/^[aeiou]/i.test(words) ? 'an' : 'a'} ${words}`;

/** A way to run a pick: a kind of account, and the model id it runs it as. */
export type Way = ModelAccount & { route: string };

/** Every kind of account that runs a harness on a model, through any of `routes` to it (the pick's own id, else
 *  another way to the same model), best first: plans, then the maker's key, then the others, OpenRouter's last. Each
 *  is judged by `accountRefusal` against the harness's catalog (its `integrations`). */
export function waysFor(harness: HarnessInfo, model: string, labels: ReadonlyMap<string, string> = new Map(), routes: readonly string[] = [model]): Way[] {
    const maker = makerOf(harness.name, model);
    const kinds = (harness.integrations.length ? harness.integrations : [maker]).flatMap((integration): ModelAccount[] => {
        const known = (Object.keys(ACCOUNT_KINDS) as (keyof typeof ACCOUNT_KINDS)[]).filter((k) => ACCOUNT_KINDS[k].integration === integration);
        const one = (kind: AccountKind): ModelAccount => ({ id: `way:${kind}:${integration}`, kind, integration, providerLabel: labels.get(integration) ?? integration, name: null, note: '', connected: true, status: 'connected', email: null });
        return known.length ? known.map(one) : [one('key')];
    });
    const ways = kinds.flatMap((k): Way[] => {
        const route = routes.find((r) => !accountRefusal(k, harness, r, r));
        return route ? [{ ...k, route }] : [];
    });
    const rank = (a: Way) => (isPlanAccount(a) ? 0 : a.integration === maker ? 1 : a.integration === 'openrouter' ? 3 : 2);
    return ways.sort((x, y) => rank(x) - rank(y));
}

/** What a pick lacks and how to ask for it, from the accounts held and the ways that run it: Send's words (one way by
 *  name, a company with several, an account where a plan is one of several companies, else a key; a plan signed out
 *  to sign in to again, a key its provider refused to reconnect), the connect popup's title, Send's mark, and what the
 *  empty chip says. A conversation asks of the one account it runs on alone. */
export function connectAsk(accounts: readonly ModelAccount[], harness: HarnessInfo, model: string, ways: readonly Way[], routes: readonly string[] = [model]) {
    const lapsed = accounts.find((a) => a.status === 'disconnected' && routeFor({ ...a, connected: true }, harness, routes)) ?? null;
    const refusedBy = accounts.filter((a) => a.connected).find((a) => !routeFor(a, harness, routes)) ?? null;
    const plan = ways.find(isPlanAccount) ?? null;
    const companies = new Set(ways.map((w) => w.integration));
    const one = ways.length === 1 ? ways[0] : null;
    const named = plan ?? ways[0];
    const [send, short, title, icon]: [string, string, string, 'reconnect' | 'plan' | 'plug' | 'key'] = lapsed
        ? isPlanAccount(lapsed)
            ? [`Sign in to ${whoOf(lapsed)} again to start`, 'Sign in again', `Sign in to ${whoOf(lapsed)} again`, 'reconnect']
            : [`Reconnect ${whoOf(lapsed)} to start`, `Reconnect ${whoOf(lapsed)}`, `Reconnect your ${kindLabel(lapsed)}`, 'reconnect']
        : one && !isPlanAccount(one)
          ? [`Add ${withArticle(kindLabel(one))} to start`, `Add ${kindLabel(one)}`, `Add ${withArticle(kindLabel(one))}`, 'key']
          : named && (one || companies.size === 1)
            ? [`Connect ${whoOf(named)} to start`, `Connect ${whoOf(named)}`, `Connect ${whoOf(named)}`, plan ? 'plan' : 'key']
            : plan
              ? ['Connect an account to start', 'Connect an account', 'Connect an account', 'plug']
              : ['Add a key to start', 'Add a key', 'Add a key', 'key'];
    const empty = lapsed ? `${kindLabel(lapsed)} · ${downWord(lapsed)}` : refusedBy ? `${kindLabel(refusedBy)} · not for ${harnessLabel(harness.name)}` : 'No account yet';
    // The way the popup opens on: the plan signed out, else the best.
    const lead = (lapsed && ways.find((w) => w.kind === lapsed.kind)) || ways[0] || null;
    return { send, short, title, icon, lapsed, refusedBy, plan, empty, lead };
}

export type ConnectAsk = ReturnType<typeof connectAsk>;

/** The credential type a way or an account is saved as. */
export const wayType = (a: Pick<ModelAccount, 'kind' | 'integration'>) => (a.kind === 'key' ? `agent_${a.integration}` : ACCOUNT_KINDS[a.kind as Exclude<AccountKind, 'key'>].credentialType);

/** A way by name: "Claude plan", "OpenRouter key". */
export const wayLabel = (a: ModelAccount) => kindLabel(a);

/** The connect popup's title on a way: the pick's ask on the way it opens on, another way's own once picked. */
export const wayTitle = (way: ModelAccount, ask: ConnectAsk) => (way.id === ask.lead?.id ? ask.title : isPlanAccount(way) ? `Connect ${whoOf(way)}` : `Add ${withArticle(kindLabel(way))}`);

/** Its kind in a word, for a phone's row of pills: "Claude", "ChatGPT", "NoClick", "OpenRouter". */
export const wayShort = (a: ModelAccount) => kindLabel(a).replace(/(’s)? (plan|key)$/, '');

/** What the account chip says the pick runs on: "Your Claude plan", "Claude key · work", "NoClick’s key". */
export const chipLabel = (a: ModelAccount) => (isPlanAccount(a) ? `Your ${accountTitle(a)}` : accountTitle(a));

/** "Claude key · work", "Claude plan", "NoClick’s key", "OpenRouter key · refused". */
export const accountTitle = (a: ModelAccount) => [kindLabel(a), a.name, downWord(a)].filter(Boolean).join(' · ');
/** What the picker's pill says: its name where it has one ("work"), else its kind; one that stopped working, only
 *  that ("key refused", "plan signed out"), which is what the pill has room for. */
export const accountShort = (a: ModelAccount) => (downWord(a) ? `${isPlanAccount(a) ? 'plan' : 'key'} ${downWord(a)}` : (a.name ?? kindLabel(a)));
/** Who pays, as a profile says it: "your Claude key · work", "NoClick’s key, at cost". */
export const accountPayer = (a: ModelAccount) => (a.kind === 'noclick' ? 'NoClick’s key, at cost' : `your ${accountTitle(a)}`);

/** What a harness needs when no account runs it: "Claude Code on Sonnet 5.5 needs a Claude key or a Claude plan";
 *  `label` is the model as a person reads it. */
export function needsAccount(harness: HarnessInfo, model: string, label: string, labels: ReadonlyMap<string, string> = new Map()): string {
    return `${harnessLabel(harness.name)} on ${label} needs ${accountKinds(harness, model, labels)}`;
}

/** The kinds of account that run a harness on a model (`waysFor`), as a sentence lists them: "a Claude plan or a
 *  Claude key". */
export function accountKinds(harness: HarnessInfo, model: string, labels: ReadonlyMap<string, string> = new Map()): string {
    const kinds = waysFor(harness, model, labels).map((way) => withArticle(kindLabel(way)));
    return new Intl.ListFormat('en', { type: 'disjunction' }).format(kinds.length ? kinds : ['an account that runs it']);
}

