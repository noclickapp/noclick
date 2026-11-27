// What NoClick's template gallery says of a template (`TemplateListing`), as plain words and choices: its contents
// counted, what it costs a month, its job, and which picture draws it. The cards, the pages, Work's Templates and the
// site draw from this, never from a listing's raw fields.
import type { TemplateListing } from 'noclick';

export type Listing = TemplateListing;

/** The jobs templates are filed under, in the gallery's filter order. */
export const JOBS: { id: string; label: string }[] = [
    { id: 'marketing', label: 'Marketing' },
    { id: 'sales', label: 'Sales' },
    { id: 'support', label: 'Support' },
    { id: 'operations', label: 'Operations' },
    { id: 'engineering', label: 'Engineering' },
    { id: 'personal', label: 'Personal' },
];

export const jobLabel = (job: string | null): string | null => JOBS.find((j) => j.id === job)?.label ?? null;

const counted = (n: number, one: string, many: string) => (n === 1 ? `${/^[aeiou]/.test(one) ? 'an' : 'a'} ${one}` : `${n} ${many}`);

/** "3 agents · 3 channels · a skill · a memory · an app": what it adds, counted. */
export function contentsLine(t: Listing): string {
    return [
        [t.agents.length, 'agent', 'agents'],
        [t.channels.length, 'channel', 'channels'],
        [t.skills.length, 'skill', 'skills'],
        [t.memories.length, 'memory', 'memories'],
        [t.automations.length, 'automation', 'automations'],
        [t.stores.length, 'data store', 'data stores'],
        [t.app ? 1 : 0, 'app', 'apps'],
    ]
        .filter(([n]) => Number(n) > 0)
        .map(([n, one, many]) => counted(Number(n), String(one), String(many)))
        .join(' · ');
}

/** Dollars as the gallery says them: `$0.42`, `$12`, never float noise. */
export function dollars(usd: number): string {
    if (usd <= 0) return '$0';
    if (usd < 0.01) return 'under $0.01';
    return Number.isInteger(usd) ? `$${usd}` : `$${usd.toFixed(2)}`;
}

/** What it costs a month, as a card's foot says it: what's priced before it runs (its app and data stores, at cost)
 *  as an estimate, and its agents by what they do, up to where they stop. */
export function priceLine(t: Listing): string {
    const hosting = t.estimate.monthlyUsd;
    const cap = t.agents.length ? t.budget.usdPerMonth : null;
    if (!t.agents.length) return hosting > 0 ? `~${dollars(hosting)} a month` : 'Nothing a month';
    const agents = cap !== null ? `by use, up to ${dollars(cap)}` : 'by use';
    return hosting > 0 ? `~${dollars(hosting)} + ${agents}` : `${agents[0].toUpperCase()}${agents.slice(1)} a month`;
}

/** Which picture a card draws: its own screenshots, else what it makes (its agents' faces, its app's frame, its skill,
 *  its memory, its automation's steps). */
export type PictureKind = 'screenshots' | 'faces' | 'app' | 'skill' | 'memory' | 'automation' | 'none';

export function pictureKind(t: Listing): PictureKind {
    if (t.pictures.length) return 'screenshots';
    if (t.agents.length) return 'faces';
    if (t.app) return 'app';
    if (t.automations.length) return 'automation';
    if (t.skills.length) return 'skill';
    if (t.memories.length) return 'memory';
    return 'none';
}

/** Whether `t` matches what someone searched for: its name, job, what it says, its agents and the apps it asks for. */
export function matches(t: Listing, query: string): boolean {
    const words = query.toLowerCase().split(/\s+/).filter(Boolean);
    if (!words.length) return true;
    const text = [t.name, t.description ?? '', jobLabel(t.job) ?? '', ...t.agents.flatMap((a) => [a.name, a.role ?? '']), ...t.connections.map((c) => c.label), contentsLine(t)].join(' ').toLowerCase();
    return words.every((w) => text.includes(w));
}
