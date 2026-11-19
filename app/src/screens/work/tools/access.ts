// What an agent may do with each app, as its Tools tab reads and writes it: the rules the platform keeps
// (`tool_rules`, GET /v1/agents/{id}/tool_access), each app's switch and each action's Allowed / Ask first / Off read
// from them, and the rules a change writes. The reading mirrors the API's:
// the most specific key naming a call decides it, `*` for what nothing names, allowed with none.
import type { AgentToolAction, AgentToolApp, ToolRule, ToolRules } from 'noclick';

export type ToolsMode = 'everything' | 'restricted';

const ALL = '*';

/** Everything on the account, or kept to the apps its rules turn on (an app connected later starts off). */
export const modeOf = (rules: ToolRules): ToolsMode => (rules[ALL] === 'off' ? 'restricted' : 'everything');

/** What the rules say of an app as a whole: its own key, else `*`, else allowed. The web's two actions are apps of
 *  their own by rule, so its row has no key. */
const appRule = (rules: ToolRules, app: AgentToolApp): ToolRule => (app.key ? rules[app.key] : undefined) ?? rules[ALL] ?? 'allow';

/** What the rules say of one action: its own key, else its app's. */
export function verdictOf(rules: ToolRules, app: AgentToolApp, action: AgentToolAction): ToolRule {
    return rules[action.key] ?? (app.key ? appRule(rules, app) : (rules[ALL] ?? 'allow'));
}

/** Whether anything of the app may run, the state of its switch. */
export function isOn(rules: ToolRules, app: AgentToolApp): boolean {
    if (!app.key) return app.actions.some((a) => verdictOf(rules, app, a) !== 'off');
    if (appRule(rules, app) !== 'off') return true;
    const prefix = `${app.key}.`;
    return Object.entries(rules).some(([key, value]) => key.startsWith(prefix) && value !== 'off');
}

/** The keys an app's actions are kept under besides its own. */
const actionKeys = (rules: ToolRules, app: AgentToolApp) => (app.key ? Object.keys(rules).filter((k) => k.startsWith(`${app.key}.`)) : app.actions.map((a) => a.key));

/** The rules switching to a mode. Restricted turns on every app shown, so nothing changes until a switch is turned
 *  off, and an app connected later starts off; Everything turns every app back on, keeping the actions held or off. */
export function rulesForMode(rules: ToolRules, apps: readonly AgentToolApp[], mode: ToolsMode): ToolRules {
    if (mode === 'restricted') {
        const next: ToolRules = { ...rules, [ALL]: 'off' };
        for (const app of apps) {
            if (app.key) next[app.key] ??= 'allow';
            else for (const a of app.actions) next[a.key] ??= 'allow';
        }
        return next;
    }
    // An action's key holds a dot; the web's actions are its own keys, which are its switch when every one is off.
    const web = new Set(apps.find((a) => !a.key)?.actions.map((a) => a.key) ?? []);
    const webOff = web.size > 0 && [...web].every((key) => rules[key] === 'off');
    return Object.fromEntries(Object.entries(rules).filter(([key, value]) => value !== 'allow' && (key.includes('.') || (web.has(key) && !webOff))));
}

/** The rules turning an app on or off: off, nothing of it runs (what its actions said goes with it); on, all of it. */
export function withApp(rules: ToolRules, app: AgentToolApp, on: boolean): ToolRules {
    const next: ToolRules = { ...rules };
    for (const key of actionKeys(rules, app)) delete next[key];
    if (app.key) next[app.key] = on ? 'allow' : 'off';
    else for (const a of app.actions) next[a.key] = on ? 'allow' : 'off';
    return next;
}

/** The rules setting one action; a verdict its app already gives needs no key of its own. */
export function withAction(rules: ToolRules, app: AgentToolApp, action: AgentToolAction, verdict: ToolRule): ToolRules {
    const next: ToolRules = { ...rules };
    delete next[action.key];
    if (verdictOf(next, app, action) !== verdict) next[action.key] = verdict;
    return next;
}

/** How many of an app's actions its rules hold or turn off, while it's on. */
export const exceptionsOf = (rules: ToolRules, app: AgentToolApp) => app.actions.filter((a) => verdictOf(rules, app, a) !== 'allow').length;

/** "41 uses this week", from the calls that ran in the last 7 days. */
export const usageLine = (calls: number) => (calls ? `${calls.toLocaleString('en')} ${calls === 1 ? 'use' : 'uses'} this week` : 'Not used this week');

export const KIND_WORDS: Record<AgentToolAction['kind'], string> = { read: 'reads', send: 'sends', change: 'changes', delete: 'deletes', money: 'moves money' };

/** An app with more actions than this shows a search, what it used this week and its groups to open. */
export const FEW_ACTIONS = 16;
const SEARCH_MOST = 40;
const TOP_MOST = 6;

export type ActionView =
    | { kind: 'all'; groups: [string | null, AgentToolAction[]][] }
    | { kind: 'found'; actions: AgentToolAction[]; more: number }
    | { kind: 'groups'; used: AgentToolAction[]; changed: AgentToolAction[]; groups: [string, AgentToolAction[]][] };

/** How an app's actions are shown: all of them by group when they're few; else what a search finds, or what it used
 *  this week (the most-used first) and what its rules set one by one, then its groups to open one at a time. */
export function actionView(rules: ToolRules, app: AgentToolApp, search: string): ActionView {
    const byGroup = (actions: readonly AgentToolAction[]) => {
        const groups = new Map<string, AgentToolAction[]>();
        for (const a of actions) groups.set(a.group ?? '', [...(groups.get(a.group ?? '') ?? []), a]);
        return [...groups.entries()];
    };
    if (app.actions.length <= FEW_ACTIONS) return { kind: 'all', groups: byGroup(app.actions).map(([g, list]) => [g || null, list]) };
    const q = search.trim().toLowerCase();
    if (q) {
        const found = app.actions.filter((a) => `${a.title} ${a.action} ${a.group ?? ''}`.toLowerCase().includes(q));
        return { kind: 'found', actions: found.slice(0, SEARCH_MOST), more: Math.max(0, found.length - SEARCH_MOST) };
    }
    const used = app.actions
        .filter((a) => a.calls > 0)
        .sort((a, b) => b.calls - a.calls)
        .slice(0, TOP_MOST);
    const changed = app.actions.filter((a) => rules[a.key] !== undefined && !used.includes(a));
    return { kind: 'groups', used, changed, groups: byGroup(app.actions).map(([g, list]) => [g || 'Other', list]) };
}
