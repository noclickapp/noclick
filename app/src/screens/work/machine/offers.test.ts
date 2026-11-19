// What buying a machine offers, read through the real SDK from the fake sizes listing: Hetzner in Europe and
// DigitalOcean everywhere at the lab's prices and stock (Hetzner out of medium and xlarge, DigitalOcean of large in US
// East), or DigitalOcean alone. A size another beats is never offered; a sold-out one is listed while nothing beats it;
// a quote whose host ran out becomes the closest thing still worth buying.
import { describe, expect, it } from 'vitest';
import { Machine, type MachineSize } from 'noclick';
import { fakeWork } from '../agents/fixtures/workAgents';
import { machineNameFor, regionChoices, requote, sizeChoices, type Quote } from './offers';

async function listing(hosts: 'two' | 'one' = 'two', out?: string[]) {
    const fake = fakeWork({ machineHosts: hosts });
    if (out) out.forEach((k) => fake.stock.out.add(k));
    return Machine.sizes({ client: fake.client, includeDominated: true });
}
const named = (sizes: MachineSize[], name: string) => sizes.find((s) => s.name === name)!;

describe('the sizes listed', () => {
    it('lists each size worth buying from its best price, greys one sold out everywhere, and leaves out one another beats', async () => {
        const choices = sizeChoices(await listing());
        expect(choices.map((c) => [c.size.name, c.from, c.varies])).toEqual([
            ['small', 8.39, true],
            ['large', 22.79, true],
            ['xlarge', null, false],
        ]);
    });

    it('with one host at one price everywhere, every size is worth buying and none varies by region', async () => {
        const choices = sizeChoices(await listing('one'));
        expect(choices.map((c) => [c.size.name, c.from, c.varies])).toEqual([
            ['small', 31.2, false],
            ['medium', 62.4, false],
            ['large', 124.8, false],
        ]);
    });
});

describe('where one size runs', () => {
    it('lists its regions cheapest first, then where it is sold out, with each one’s disk', async () => {
        const sizes = await listing();
        const large = regionChoices(named(sizes, 'large'), sizes);
        expect(large.map((r) => [r.region, r.quote?.usd ?? null, r.quote?.host ?? null, r.diskGb])).toEqual([
            ['eu', 22.79, 'hetzner', 160],
            ['us-west', 124.8, 'digitalocean', 320],
            ['ap', 124.8, 'digitalocean', 320],
            ['in', 124.8, 'digitalocean', 320],
            ['us-east', null, null, 320],
        ]);
    });

    it('leaves out a region where a size with at least its room costs no more', async () => {
        // Hetzner out of small in Europe: DigitalOcean's there ($31.20) is beaten by Hetzner's large ($22.79).
        const sizes = await listing('two', ['hetzner:eu:small']);
        const small = regionChoices(named(sizes, 'small'), sizes);
        expect(small.map((r) => r.region)).toEqual(['us-east', 'us-west', 'ap', 'in']);
        // Sold out everywhere in US East and nothing roomier there for less: it says so.
        const out = await listing('one', ['digitalocean:us-east:small']);
        expect(regionChoices(named(out, 'small'), out).at(-1)).toEqual({ region: 'us-east', quote: null, diskGb: 80 });
    });
});

describe('a quote whose host ran out', () => {
    const smallEu: Quote = { size: 'small', region: 'eu', host: 'hetzner', usd: 8.39, diskGb: 40 };

    it('becomes the cheapest size with at least its room when what is left of it is beaten', async () => {
        const after = await listing('two', ['hetzner:eu:small']);
        expect(requote(smallEu, after)).toEqual({ quote: { size: 'large', region: 'eu', host: 'hetzner', usd: 22.79, diskGb: 160 }, alternatives: [], changed: 'size' });
    });

    it('stays put on another host there when one still has it', async () => {
        const after = await listing('two', ['hetzner:eu:large']);
        const largeEu: Quote = { size: 'large', region: 'eu', host: 'hetzner', usd: 22.79, diskGb: 160 };
        expect(requote(largeEu, after)).toEqual({ quote: { size: 'large', region: 'eu', host: 'digitalocean', usd: 124.8, diskGb: 320 }, alternatives: [], changed: 'host' });
    });

    it('moves to where the size is cheapest now, offering the cheapest with its room in the region picked', async () => {
        const after = await listing('two', ['digitalocean:us-west:small']);
        const smallUsWest: Quote = { size: 'small', region: 'us-west', host: 'digitalocean', usd: 31.2, diskGb: 80 };
        expect(requote(smallUsWest, after)).toEqual({
            quote: smallEu,
            alternatives: [{ size: 'large', region: 'us-west', host: 'digitalocean', usd: 124.8, diskGb: 320 }],
            changed: 'region',
        });
        // Medium, which large beats anywhere, is never the one offered beside it, even where it's in stock.
        const usEast = await listing('two', ['digitalocean:us-east:small']);
        expect(requote({ ...smallUsWest, region: 'us-east' }, usEast)).toEqual({ quote: smallEu, alternatives: [], changed: 'region' });
    });

    it('says it’s the price that changed when the same host there now asks more', async () => {
        const after = await listing();
        const small = named(after, 'small');
        small.regions = small.regions.map((r) => (r.region === 'eu' ? { ...r, monthlyUsd: 9.1 } : r));
        expect(requote(smallEu, after)).toEqual({ quote: { ...smallEu, usd: 9.1 }, alternatives: [], changed: 'price' });
    });

    it('is nothing when nothing like it can be bought', async () => {
        const all = ['us-east', 'us-west', 'eu', 'ap', 'in'].flatMap((r) => ['small', 'medium', 'large'].map((s) => `digitalocean:${r}:${s}`));
        expect(requote({ size: 'small', region: 'us-east', host: 'digitalocean', usd: 31.2, diskGb: 80 }, await listing('one', all))).toBeNull();
    });

    it('never quotes again the offer just turned away, even while the listing still shows it', async () => {
        const stale = await listing('one');
        const next = requote({ size: 'small', region: 'us-east', host: 'digitalocean', usd: 31.2, diskGb: 80 }, stale);
        expect(next?.quote).toEqual({ size: 'small', region: 'us-west', host: 'digitalocean', usd: 31.2, diskGb: 80 });
    });
});

it('names a new machine for its agent, never one the account has', () => {
    expect(machineNameFor('Support Bot', [])).toBe('support-bot-box');
    expect(machineNameFor('Atlas', ['atlas-box', 'atlas-box-2'])).toBe('atlas-box-3');
});
