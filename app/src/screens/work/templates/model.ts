// What a space template's page of asks says, as plain data: the dry run's answer (`TemplatePlan`) read into the words
// the page shows. The page, its lab and its tests draw from this, never from the plan's raw fields.
import type { TemplatePart, TemplatePlan } from 'noclick';

export type PartKind = TemplatePart['kind'];

/** "3 agents · 3 channels · a skill · an automation · an app": what a template holds, counted. */
export function containsLine(parts: readonly TemplatePart[]): string {
    const counted: [PartKind, string, string][] = [
        ['agent', 'agent', 'agents'],
        ['channel', 'channel', 'channels'],
        ['skill', 'skill', 'skills'],
        ['memory', 'memory', 'memories'],
        ['automation', 'automation', 'automations'],
        ['store', 'data store', 'data stores'],
        ['app', 'app', 'apps'],
    ];
    return counted
        .flatMap(([kind, one, many]) => {
            const n = parts.filter((p) => p.kind === kind).length;
            return n === 0 ? [] : [n === 1 ? `${/^[aeiou]/.test(one) ? 'an' : 'a'} ${one}` : `${n} ${many}`];
        })
        .join(' · ');
}

/** Dollars as the page says them: never a figure hinging on float noise. */
export function dollars(usd: number): string {
    if (usd <= 0) return '$0';
    if (usd < 0.005) return 'under $0.01';
    return usd >= 10 && Number.isInteger(usd) ? `$${usd}` : `$${(Math.round(usd * 100) / 100).toFixed(2)}`;
}

/** An estimate, said as one: `~$1.20`. */
export const estimated = (usd: number) => (usd > 0.005 ? `~${dollars(usd)}` : dollars(usd));

export interface CostLine {
    key: string;
    name: string;
    /** What it's by, in words ("its site and code, by visits and storage"). */
    by: string;
    usd: number;
    /** Said as the most it spends, not an estimate (its agents' cap). */
    upTo?: boolean;
}

type Raw = Record<string, unknown>;
const num = (v: unknown) => (typeof v === 'number' && Number.isFinite(v) ? v : 0);

/** The estimate's lines: its app (its site and its copy of the code, as the deploy's estimate prices them), each data
 *  store, then its agents said as the cap they stop at (what they spend is by what they do). */
export function costLines(plan: TemplatePlan): { lines: CostLine[]; hostingUsd: number; agentsUpTo: number | null } {
    const items = Array.isArray(plan.estimate.items) ? (plan.estimate.items as Raw[]) : [];
    const app = items.filter((i) => i.kind === 'project' || i.kind === 'repo');
    const lines: CostLine[] = [];
    if (app.length) {
        lines.push({ key: 'app', name: String(app[0].name ?? 'Its app'), by: 'Its site and its code, by visits and storage', usd: app.reduce((s, i) => s + num(i.monthly_usd), 0) });
    }
    for (const item of items.filter((i) => i.kind === 'database' || i.kind === 'bucket')) {
        lines.push({ key: `store:${String(item.name)}`, name: String(item.name), by: item.kind === 'database' ? 'A database, by its rows and storage' : 'A bucket, by what it holds', usd: num(item.monthly_usd) });
    }
    const agents = (plan.estimate.agents ?? {}) as Raw;
    const upTo = typeof agents.up_to_usd === 'number' ? agents.up_to_usd : null;
    const names = Array.isArray(agents.names) ? (agents.names as string[]) : plan.parts.filter((p) => p.kind === 'agent' && p.included).map((p) => p.named);
    if (names.length) {
        lines.unshift({ key: 'agents', name: 'Its agents', by: `${and(names)}, by what they do`, usd: upTo ?? 0, upTo: true });
    }
    return { lines, hostingUsd: num(plan.estimate.monthly_usd), agentsUpTo: names.length ? upTo : null };
}

/** "Writer, Designer and Scheduler". */
export function and(names: readonly string[]): string {
    return names.length <= 1 ? (names[0] ?? '') : `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`;
}

/** A part's line on the page: what it is, and what it needs. */
export function partLine(part: TemplatePart, labels: Record<string, string>): string | null {
    const needs = part.needs.map((n) => labels[n] ?? n);
    const what =
        part.kind === 'channel'
            ? part.members.length
                ? and(part.members)
                : 'No agents'
            : part.kind === 'skill'
              ? (part.line ?? 'Read by its agents')
              : part.line;
    return [what, needs.length ? `needs ${and(needs)}` : null].filter(Boolean).join(' · ') || null;
}

/** The order the page lists a template's parts in. */
export const PART_ORDER: PartKind[] = ['agent', 'channel', 'skill', 'memory', 'automation', 'store', 'app'];

export function sortedParts(parts: readonly TemplatePart[]): TemplatePart[] {
    return [...parts].sort((a, b) => PART_ORDER.indexOf(a.kind) - PART_ORDER.indexOf(b.kind));
}

/** A part as `leaveOut` names it. */
export const partKey = (part: Pick<TemplatePart, 'kind' | 'name'>) => `${part.kind}:${part.name}`;

/** The source's host, as the page says where a template is from. */
export function fromWhere(address: string): string {
    try {
        const url = new URL(address.includes('://') ? address : `https://${address}`);
        const repo = url.searchParams.get('repo');
        return repo ? fromWhere(repo) : url.hostname;
    } catch {
        return address;
    }
}
