// A browser at work said in plain words: each step's caption comes from its kind and the element it acted on, never
// from what it typed; where the browser stands follows its view (running is at work, in an act or in its turn's own
// calls; parked between turns is at rest); and the Beside counts it as the person's only when a step is theirs, and
// lists it with what runs while it runs, ahead of what's done.
import { describe, expect, it } from 'vitest';
import type { Browser } from 'noclick';
import { browserItems, grouped, type BesideItem } from '../conversation/besideItems';
import { captionOf, did, doing, headlineOf, siteOf, stateOf } from './words';

type View = Pick<Browser, 'id' | 'status' | 'acting' | 'held' | 'waitingOn' | 'steps' | 'url' | 'startedAt' | 'createdAt' | 'closedAt'>;

const NOW = new Date('2026-11-14T12:00:00Z').getTime();

function browser(fields: Partial<View> = {}): Browser {
    return {
        id: 'br_1', status: 'running', acting: true, held: false, waitingOn: null, url: 'https://www.kestrel.example/checkout',
        steps: [{ action: 'type', target: 'Email', at: new Date(NOW - 2000) }], startedAt: new Date(NOW - 60_000),
        createdAt: new Date(NOW - 61_000), closedAt: null, ...fields,
    } as unknown as Browser;
}

describe('the words of a step', () => {
    it('say what it acts on, as it happens and once done', () => {
        expect(doing({ action: 'click', target: 'Add to cart' })).toBe('Clicking Add to cart');
        expect(did({ action: 'click', target: 'Add to cart' })).toBe('Clicked Add to cart');
        expect(doing({ action: 'type', target: 'Email' })).toBe('Typing in Email');
        expect(did({ action: 'type', target: null })).toBe('Typed in a field');
        expect(doing({ action: 'goto', target: null, url: 'https://www.kestrel.example/cart' })).toBe('Opening kestrel.example');
        expect(did({ action: 'goto', target: null }, 'kestrel.example')).toBe('Opened kestrel.example');
        expect(doing({ action: 'something_new', target: 'x' })).toBe('Working on the page');
    });

    it('never carry what was typed: a step only names where', () => {
        // A step from the platform carries its kind and its element; the words have nothing else to show.
        const typed = { action: 'type', target: 'Password', detail: "'hunter2' into Password" } as never;
        expect(doing(typed)).toBe('Typing in Password');
        expect(did(typed)).not.toContain('hunter2');
    });

    it('find the site without its www', () => {
        expect(siteOf('https://www.kestrel.example/checkout?x=1')).toBe('kestrel.example');
        expect(siteOf('not a url')).toBeNull();
        expect(siteOf(null)).toBeNull();
    });
});

describe('where the browser stands', () => {
    it('follows its view: working, waiting on a person, held, at rest', () => {
        expect(stateOf(browser())).toBe('working');
        expect(captionOf(browser())).toBe('Typing in Email');
        expect(captionOf(browser({ steps: [] }))).toBe('Looking at the page');
        const asked = browser({ status: 'parked', acting: false, waitingOn: { person: 'Sign in to kestrel.example.', forYou: true } });
        expect(stateOf(asked)).toBe('needs');
        expect(captionOf(asked)).toBe('Sign in to kestrel.example.');
        expect(stateOf(browser({ status: 'parked', acting: false, held: true }))).toBe('control');
        expect(captionOf(browser({ status: 'parked', acting: false, held: true }))).toBe('You’re in control');
        expect(stateOf(browser({ status: 'starting', acting: false }))).toBe('starting');
        expect(stateOf(browser({ status: 'closed', acting: false }))).toBe('done');
    });

    it('is at work whenever it runs: a later turn opening pages itself, its earlier act’s steps no caption of it', () => {
        const turns = browser({ acting: false, url: 'https://www.apple.example/in/mac' });
        expect(stateOf(turns)).toBe('working');
        expect(captionOf(turns)).toBe('Looking at the page');
    });

    it('rests, paused, while it waits for the conversation’s next turn', () => {
        const parked = browser({ status: 'parked', acting: false });
        expect(stateOf(parked)).toBe('idle');
        expect(captionOf(parked)).toBe('Paused until the next turn');
    });
});

describe('the browser beside its conversation', () => {
    it('needs you only when the step is yours, or you hold it', () => {
        const mine = browser({ status: 'parked', acting: false, waitingOn: { person: 'Sign in.', forYou: true } });
        const theirs = browser({ status: 'parked', acting: false, waitingOn: { person: 'Sign in.', forYou: false } });
        expect(browserItems(mine, NOW)[0]).toMatchObject({ kind: 'browser', status: 'needs', line: 'Sign in.', endedAt: null });
        expect(browserItems(theirs, NOW)[0].status).toBe('running');
        expect(browserItems(browser({ held: true, status: 'parked', acting: false }), NOW)[0].status).toBe('needs');
        expect(browserItems(browser(), NOW)[0]).toMatchObject({ status: 'running', line: 'Typing in Email' });
    });

    it('runs while a follow-up turn uses it, ahead of what’s done, and is done again once it rests', () => {
        const done: BesideItem = { ...browserItems(browser({ id: 'br_0', status: 'closed', acting: false, closedAt: new Date(NOW - 60_000) }), NOW)[0], id: 'sub_1', kind: 'subagent' };
        const [followUp] = browserItems(browser({ acting: false }), NOW);
        expect(followUp).toMatchObject({ kind: 'browser', status: 'running', endedAt: null, line: 'Looking at the page' });
        const groups = grouped([done, followUp], NOW);
        expect(groups.running.map((b) => b.id)).toEqual(['br_1']);
        expect(groups.done.map((b) => b.id)).toEqual(['sub_1']);
        const [rested] = browserItems(browser({ status: 'parked', acting: false }), NOW);
        expect(rested).toMatchObject({ status: 'done', line: 'Paused until the next turn' });
        expect(grouped([done, rested], NOW).running).toEqual([]);
    });

    it('rests as done today, and an old one is gone', () => {
        const closed = browser({ status: 'closed', acting: false, closedAt: new Date(NOW - 60_000) });
        expect(browserItems(closed, NOW)[0]).toMatchObject({ status: 'done', endedAt: NOW - 60_000 });
        expect(browserItems(browser({ status: 'closed', acting: false, closedAt: new Date(NOW - 3 * 86_400_000) }), NOW)).toEqual([]);
        expect(browserItems(null, NOW)).toEqual([]);
    });
});

describe('an answer said in a line', () => {
    it('is its first sentence of prose, the markdown gone', () => {
        expect(headlineOf('Bought leostictactoe.com: $11.25 for a year, order K-20931')).toBe('Bought leostictactoe.com: $11.25 for a year, order K-20931');
        expect(headlineOf('The **Aero 13** starts at `$999`. It ships in a week.')).toBe('The Aero 13 starts at $999.');
        expect(headlineOf('## Prices\n**Monthly billing**\n| Plan | Price |\n|---|---|\n| Core | $16 |\n\n- Core is [$16](https://northwind.example/core) a month.')).toBe('Core is $16 a month.');
        expect(headlineOf('Price: $1.60 per 1,000 operations')).toBe('Price: $1.60 per 1,000 operations');
    });

    it('is cut at a word when its sentence runs long', () => {
        const long = `Northwind lists ${Array.from({ length: 40 }, (_, i) => `plan${i}`).join(' ')} on its page`;
        const line = headlineOf(long);
        expect(line.length).toBeLessThanOrEqual(161);
        expect(line.endsWith('…')).toBe(true);
        expect(line).not.toMatch(/ …$/);
    });
});
