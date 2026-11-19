// What buying a machine offers, read from one `Machine.sizes({ includeDominated: true })`: the sizes worth listing (each
// at its best price anywhere, plus sold-out ones that would be worth buying in stock), the regions one size can go in,
// and what a quote becomes when its host runs out between the pick and Buy. Pure, so the picker and its tests share it.
// A size another beats on vCPUs and memory for the same price or less is never offered anywhere here.
import type { MachineHostName, MachineSize, MachineSizeName, RegionName } from 'noclick';

/** A size in one region, on the host that would place it there and at its price: what Buy agrees to. */
export interface Quote {
    size: MachineSizeName;
    region: RegionName;
    host: MachineHostName;
    usd: number;
    diskGb: number;
}

/** A size as the list shows it: `from` its best price anywhere (`varies`: its regions differ in price), or sold out
 *  everywhere (`from` null) though nothing in stock beats it. */
export interface SizeChoice {
    size: MachineSize;
    from: number | null;
    varies: boolean;
}

/** A region one size can go in: its quote there, or null where it's sold out there. */
export interface RegionChoice {
    region: RegionName;
    quote: Quote | null;
    /** Its disk there (the first host selling it there, while sold out). */
    diskGb: number;
}

export const HOST_NAMES: Record<MachineHostName, string> = { hetzner: 'Hetzner', digitalocean: 'DigitalOcean' };

type Place = MachineSize['regions'][number];
const roomy = (a: { cpu: number; memoryGb: number }, b: { cpu: number; memoryGb: number }) => a.cpu >= b.cpu && a.memoryGb >= b.memoryGb;
const quoteOf = (size: MachineSizeName, r: Place): Quote => ({ size, region: r.region, host: r.host, usd: r.monthlyUsd, diskGb: r.diskGb });
/** The cheapest of `sizes` at the place `at` finds for each. */
function cheapest(sizes: readonly MachineSize[], at: (s: MachineSize) => Place | undefined): { s: MachineSize; r: Place } | undefined {
    return sizes
        .map((s) => ({ s, r: at(s) }))
        .filter((x): x is { s: MachineSize; r: Place } => !!x.r)
        .sort((a, b) => a.r.monthlyUsd - b.r.monthlyUsd)[0];
}

/** The sizes to list, smallest first: each one worth buying now, and each sold out everywhere that nothing in stock
 *  beats at its price once in stock. A size another beats is left out, with nothing said about it. */
export function sizeChoices(sizes: readonly MachineSize[]): SizeChoice[] {
    return sizes
        .filter((s) => !s.dominatedBy)
        .map((size) => {
            const prices = size.regions.filter((r) => !r.dominatedBy).map((r) => r.monthlyUsd);
            return { size, from: size.available ? size.monthlyUsd : null, varies: new Set(prices).size > 1 };
        });
}

/** Where `size` can go, cheapest first, then the regions where it's sold out, in the order its hosts list them. A
 *  region where a size with at least its room is in stock for no more (than its price there once back) is left out. */
export function regionChoices(size: MachineSize, sizes: readonly MachineSize[]): RegionChoice[] {
    const inStock = size.regions.filter((r) => !r.dominatedBy).map((r) => ({ region: r.region, quote: quoteOf(size.name, r), diskGb: r.diskGb }));
    const listed = new Set(size.regions.map((r) => r.region));
    const soldOut: RegionChoice[] = [];
    for (const host of size.hosts) {
        for (const region of host.regions) {
            if (listed.has(region)) continue;
            listed.add(region);
            const beaten = sizes.some((other) => other.name !== size.name && roomy(other, size) && other.regions.some((r) => r.region === region && r.monthlyUsd <= host.monthlyUsd));
            if (!beaten) soldOut.push({ region, quote: null, diskGb: host.diskGb });
        }
    }
    return [...inStock, ...soldOut];
}

/** What `was` is quoted at instead once its host turned it away: the same size there on another host, else the same
 *  size where it's cheapest now, else the cheapest size with at least its room. `alternatives`: one more to pick, the
 *  cheapest with that room in the same region, unless the quote beats it. Null: nothing like it can be bought now. */
export interface Requote {
    quote: Quote;
    alternatives: Quote[];
    /** What changed: its price on the same host there, the host there, the region, or the size. */
    changed: 'price' | 'host' | 'region' | 'size';
}

export function requote(was: Quote, sizes: readonly MachineSize[]): Requote | null {
    const wasSize = sizes.find((s) => s.name === was.size);
    if (!wasSize) return null;
    const gone = (r: Place) => r.region === was.region && r.host === was.host && r.monthlyUsd === was.usd;
    // Each size's regions come cheapest first.
    const open = (s: MachineSize) => s.regions.find((r) => !r.dominatedBy && !gone(r));
    const here = (s: MachineSize) => s.regions.find((r) => r.region === was.region && !r.dominatedBy && !gone(r));
    const worth = sizes.filter((s) => s.available && !s.dominatedBy);
    const same = worth.find((s) => s.name === was.size);
    const roomier = worth.filter((s) => roomy(s, wasSize));
    const samePlace = same && (here(same) ?? open(same));
    const found = same && samePlace ? { s: same, r: samePlace } : cheapest(roomier.filter((s) => s !== same), open);
    if (!found) return null;
    const quote = quoteOf(found.s.name, found.r);
    const changed = quote.size !== was.size ? 'size' : quote.region !== was.region ? 'region' : quote.host !== was.host ? 'host' : 'price';
    const stay = changed === 'host' || changed === 'price' ? undefined : cheapest(roomier, here);
    const beats = stay && roomy(found.s, stay.s) && quote.usd <= stay.r.monthlyUsd;
    return { quote, alternatives: stay && !beats ? [quoteOf(stay.s.name, stay.r)] : [], changed };
}

/** A name for a new machine of `agentName`'s that none of `taken` has: `<agent>-box`, then `-2`, `-3`… */
export function machineNameFor(agentName: string, taken: readonly string[]): string {
    const base = `${agentName.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'agent'}-box`;
    const names = new Set(taken);
    let name = base;
    for (let n = 2; names.has(name); n++) name = `${base}-${n}`;
    return name;
}
