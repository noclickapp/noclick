// What an agent may do with each app, read from its rules and written back: the most specific key decides, Restricted
// turns on what's shown and leaves an app connected later off, a switch takes an app's own settings with it, an action
// that says what its app does needs no key, and Everything keeps only the actions held or off.
import { describe, expect, it } from 'vitest';
import type { AgentToolAction, AgentToolApp } from 'noclick';
import { actionView, FEW_ACTIONS, isOn, modeOf, rulesForMode, verdictOf, withAction, withApp } from './access';

const act = (app: string, action: string, extra: Partial<AgentToolAction> = {}): AgentToolAction => ({ key: `${app}.${action}`, action, title: action, group: 'Message', kind: 'send', verdict: 'allow', canAsk: true, calls: 0, ...extra });
const appOf = (key: string | null, app: string, actions: AgentToolAction[]): AgentToolApp => ({ key, app, kind: key ? 'connection' : 'web', integration: null, credentialType: null, label: app, account: null, status: null, on: true, calls: 0, actions });

const GMAIL = appOf('work-gmail', 'work-gmail', [act('work-gmail', 'send_email_message'), act('work-gmail', 'delete_email', { kind: 'delete' })]);
const SLACK = appOf('team-slack', 'team-slack', [act('team-slack', 'send_message')]);
const WEB = appOf(null, 'web', [act('', 'search', { key: 'search' }), act('', 'fetch', { key: 'fetch' })]);
const APPS = [GMAIL, SLACK, WEB];

describe('reading the rules', () => {
    it('lets the most specific key decide, and allows what nothing names', () => {
        const rules = { '*': 'off', 'work-gmail': 'ask', 'work-gmail.delete_email': 'off', search: 'allow' } as const;
        expect(verdictOf(rules, GMAIL, GMAIL.actions[0])).toBe('ask');
        expect(verdictOf(rules, GMAIL, GMAIL.actions[1])).toBe('off');
        expect(verdictOf(rules, SLACK, SLACK.actions[0])).toBe('off');
        expect(verdictOf(rules, WEB, WEB.actions[0])).toBe('allow');
        expect(verdictOf(rules, WEB, WEB.actions[1])).toBe('off');
        expect(verdictOf({}, SLACK, SLACK.actions[0])).toBe('allow');
        expect(modeOf(rules)).toBe('restricted');
        expect(modeOf({ 'work-gmail.delete_email': 'off' })).toBe('everything');
    });

    it('reads an app as on while anything of it may run', () => {
        expect(isOn({ '*': 'off', 'work-gmail.send_email_message': 'allow' }, GMAIL)).toBe(true);
        expect(isOn({ '*': 'off' }, GMAIL)).toBe(false);
        expect(isOn({ search: 'off', fetch: 'off' }, WEB)).toBe(false);
        expect(isOn({ search: 'off' }, WEB)).toBe(true);
    });
});

describe('writing them', () => {
    it('restricts to every app shown, so only one connected later starts off', () => {
        const rules = rulesForMode({ 'work-gmail.delete_email': 'off' }, APPS, 'restricted');
        expect(rules).toEqual({ '*': 'off', 'work-gmail': 'allow', 'team-slack': 'allow', search: 'allow', fetch: 'allow', 'work-gmail.delete_email': 'off' });
        expect(APPS.every((a) => isOn(rules, a))).toBe(true);
        expect(verdictOf(rules, appOf('later-slack', 'later-slack', []), act('later-slack', 'x'))).toBe('off');
    });

    it('goes back to everything keeping only the actions held or off', () => {
        const rules = { '*': 'off', 'work-gmail': 'allow', 'team-slack': 'off', search: 'off', fetch: 'off', 'work-gmail.delete_email': 'off', 'work-gmail.send_email_message': 'ask' } as const;
        expect(rulesForMode(rules, APPS, 'everything')).toEqual({ 'work-gmail.delete_email': 'off', 'work-gmail.send_email_message': 'ask' });
        // One web action asked about first is an exception of its own, not the web's switch.
        expect(rulesForMode({ '*': 'off', search: 'ask', fetch: 'allow' }, APPS, 'everything')).toEqual({ search: 'ask' });
    });

    it('turns an app off whole, its own settings going with it, and on again whole', () => {
        const before = { '*': 'off', 'work-gmail': 'allow', 'work-gmail.send_email_message': 'ask' } as const;
        const off = withApp(before, GMAIL, false);
        expect(off).toEqual({ '*': 'off', 'work-gmail': 'off' });
        expect(isOn(off, GMAIL)).toBe(false);
        expect(withApp(off, GMAIL, true)).toEqual({ '*': 'off', 'work-gmail': 'allow' });
        expect(withApp({ '*': 'off', search: 'allow', fetch: 'allow' }, WEB, false)).toEqual({ '*': 'off', search: 'off', fetch: 'off' });
    });

    it('sets an action, and drops its key once it says what its app does', () => {
        const held = withAction({ '*': 'off', 'work-gmail': 'allow' }, GMAIL, GMAIL.actions[0], 'ask');
        expect(held).toEqual({ '*': 'off', 'work-gmail': 'allow', 'work-gmail.send_email_message': 'ask' });
        expect(withAction(held, GMAIL, GMAIL.actions[0], 'allow')).toEqual({ '*': 'off', 'work-gmail': 'allow' });
        // An action turned on in an app that's off turns the app on with only it.
        const one = withAction({ '*': 'off' }, SLACK, SLACK.actions[0], 'allow');
        expect(one).toEqual({ '*': 'off', 'team-slack.send_message': 'allow' });
        expect(isOn(one, SLACK)).toBe(true);
    });
});

describe('showing an app’s actions', () => {
    const many = appOf(
        'gh',
        'gh',
        Array.from({ length: FEW_ACTIONS + 4 }, (_, i) => act('gh', `op_${i}`, { group: i % 2 ? 'Issues' : 'Repositories', title: i === 3 ? 'Merge pull request' : `Op ${i}`, calls: i === 5 ? 9 : i === 7 ? 2 : 0 }))
    );

    it('lists a few all at once, by group', () => {
        const view = actionView({}, GMAIL, '');
        expect(view.kind).toBe('all');
    });

    it('shows many as what it used, what was set and its groups, and a search over all of them', () => {
        const view = actionView({ 'gh.op_2': 'off' }, many, '');
        expect(view.kind === 'groups' && view.used.map((a) => a.action)).toEqual(['op_5', 'op_7']);
        expect(view.kind === 'groups' && view.changed.map((a) => a.action)).toEqual(['op_2']);
        expect(view.kind === 'groups' && view.groups.map(([g, list]) => [g, list.length])).toEqual([
            ['Repositories', 10],
            ['Issues', 10],
        ]);
        const found = actionView({}, many, 'merge');
        expect(found.kind === 'found' && found.actions.map((a) => a.action)).toEqual(['op_3']);
    });
});
