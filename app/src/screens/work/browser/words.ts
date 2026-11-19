// A browser at work, said in plain words: what each step is doing as it happens and what it did once done, from the
// step's kind and the element it acted on (a field's label, a button's text), never from what it typed, so a caption
// can't show a password or a code. And where the browser stands for the person watching it. Pure, so the tile, the
// big view, the turn's card and the receipt all say it the same way.
import type { Browser, BrowserWatchedStep } from 'noclick';

/** A step as the words read it: its kind, the element it acted on, and the page it was on where that's known. */
export interface StepLike {
    action: string;
    target: string | null;
    url?: string | null;
}

/** The site a page is on, without its `www.`: "kestrel.example". */
export function siteOf(url: string | null | undefined): string | null {
    if (!url) return null;
    try {
        const host = new URL(url).hostname.replace(/^www\./, '');
        return host || null;
    } catch {
        return null;
    }
}

type Said = [doing: (target: string | null, site: string | null) => string, did: (target: string | null, site: string | null) => string];

const on = (verb: string, target: string | null, rest: string) => (target ? `${verb} ${target}` : `${verb} ${rest}`);

// Each kind of step the browser's pilot names, as it's happening and once done.
const WORDS: Record<string, Said> = {
    goto: [(_, site) => `Opening ${site ?? 'a page'}`, (_, site) => `Opened ${site ?? 'a page'}`],
    click: [(t) => on('Clicking', t, 'on the page'), (t) => on('Clicked', t, 'on the page')],
    type: [(t) => on('Typing in', t, 'a field'), (t) => on('Typed in', t, 'a field')],
    key: [() => 'Pressing a key', () => 'Pressed a key'],
    select: [(t) => on('Choosing in', t, 'a list'), (t) => on('Chose in', t, 'a list')],
    scroll: [() => 'Scrolling the page', () => 'Scrolled the page'],
    upload: [() => 'Uploading a file', () => 'Uploaded a file'],
    download: [() => 'Downloading a file', () => 'Downloaded a file'],
    read: [() => 'Reading the page', () => 'Read the page'],
    tab: [() => 'Switching tabs', () => 'Switched tabs'],
    wait: [() => 'Waiting a moment', () => 'Waited a moment'],
    script: [() => 'Running a script on the page', () => 'Ran a script on the page'],
    ask: [() => 'Asking you to step in', () => 'Asked you to step in'],
    pay: [() => 'At the payment step', () => 'Reached the payment step'],
    network: [() => 'Reaching a site directly', () => 'Reached a site directly'],
    dialog: [() => 'Answering a popup', () => 'Answered a popup'],
};
const OTHER: Said = [() => 'Working on the page', () => 'Worked on the page'];

/** What a step is doing, as it happens: "Typing in Email". `site` is where the browser is, for a step with no page. */
export function doing(step: StepLike, site: string | null = null): string {
    return (WORDS[step.action] ?? OTHER)[0](step.target, siteOf(step.url) ?? site);
}

/** What a step did: "Typed in Email". */
export function did(step: StepLike, site: string | null = null): string {
    return (WORDS[step.action] ?? OTHER)[1](step.target, siteOf(step.url) ?? site);
}

// A receipt's line is a sentence, not a report: past this, it's cut at a word.
const HEADLINE_MAX = 160;

/** A task's answer as one plain line, for a receipt: the first sentence of its first line of prose, with the markdown
 *  gone (no `**`, no table, no heading or list marks), cut at a word past `HEADLINE_MAX`. A heading, a table and a
 *  line that's only bold are skipped: they name the answer, they don't say it. The whole answer belongs in the reply. */
export function headlineOf(text: string): string {
    const prose = text
        .replace(/```[\s\S]*?```/g, '\n')
        .split('\n')
        .map((l) => l.trim())
        .find((l) => l && !/^#{1,6}\s/.test(l) && !l.startsWith('|') && (l.match(/\|/g) ?? []).length < 2 && !/^[-*_=:|\s]{3,}$/.test(l) && !/^\*\*[^*]+\*\*:?$/.test(l));
    const plain = (prose ?? '')
        .replace(/^>\s?/, '')
        .replace(/^([-*+]|\d+[.)])\s+/, '')
        .replace(/!\[[^\]]*\]\([^)]*\)/g, '')
        .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
        .replace(/\*\*|__|~~|`|\*/g, '')
        .replace(/\s+/g, ' ')
        .trim();
    const first = /^(.*?[.!?])(\s|$)/.exec(plain)?.[1] ?? plain;
    if (first.length <= HEADLINE_MAX) return first;
    const cut = first.slice(0, HEADLINE_MAX);
    return `${cut.slice(0, Math.max(cut.lastIndexOf(' '), HEADLINE_MAX / 2)).replace(/[\s,;:–-]+$/, '')}…`;
}

/** Where a browser stands for the person watching it:
 *  - `starting`: it's starting;
 *  - `working`: it runs, in its conversation's turn (an act driving it, or the agent's own calls) or for an act;
 *  - `needs`: a step in it waits on a person (`forYou`: on you);
 *  - `control`: a person has taken it over;
 *  - `idle`: parked between its conversation's turns, unbilled, on the page it kept (`frameUrl`);
 *  - `done`: closed (or never started). */
export type BrowserState = 'starting' | 'working' | 'needs' | 'control' | 'idle' | 'done';

export function stateOf(browser: Pick<Browser, 'status' | 'held' | 'waitingOn'>): BrowserState {
    if (browser.status === 'starting') return 'starting';
    if (browser.status === 'closed' || browser.status === 'failed') return 'done';
    if (browser.held) return 'control';
    if (browser.waitingOn) return 'needs';
    // A conversation's browser runs only while something uses it: a turn's end, or its act's, parks it.
    return browser.status === 'running' ? 'working' : 'idle';
}

/** Whether it's at work beside the conversation: starting, working, or waiting on a person. Only then is it shown
 *  live: a picture streams from a browser that's connected, and a connected browser is billed. */
export const isLiveState = (state: BrowserState) => state !== 'idle' && state !== 'done';

/** The newest step, as the steps say it. */
export const newestStep = (steps: readonly BrowserWatchedStep[]): BrowserWatchedStep | null => steps[steps.length - 1] ?? null;

/** The live caption: what it's doing now, in a line. */
export function captionOf(browser: Pick<Browser, 'status' | 'acting' | 'held' | 'waitingOn' | 'steps' | 'url'>): string {
    const state = stateOf(browser);
    if (state === 'starting') return 'Starting a browser';
    if (state === 'control') return 'You’re in control';
    if (state === 'needs') return browser.waitingOn!.person;
    if (state === 'done') return 'Closed';
    if (state === 'idle') return 'Paused until the next turn';
    // Its steps are its newest act's: once no act drives it, they're an earlier act's, not what it does now.
    const step = browser.acting ? newestStep(browser.steps) : null;
    return step ? doing(step, siteOf(browser.url)) : 'Looking at the page';
}
