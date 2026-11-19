// A fake of what machines can be bought and where, for Work's fixtures: Hetzner in Europe and DigitalOcean everywhere
// (or DigitalOcean alone, as production has it until Hetzner is turned on), each host's stock, and the two calls the
// machine picker makes. GET /v1/machines/sizes is judged as the platform judges it (`machines/hosting.listing`), and
// POST /v1/machines is placed on the named host at no more than `max_monthly_usd` or refused in the platform's words.
import { heldPurchase } from './machineWorld';

type Json = Record<string, unknown>;

const REGIONS = ['us-east', 'us-west', 'eu', 'ap', 'in'];
const SIZES = [
    { name: 'small', cpu: 2, memory_gb: 4, working_conversations: 2 },
    { name: 'medium', cpu: 4, memory_gb: 8, working_conversations: 4 },
    { name: 'large', cpu: 8, memory_gb: 16, working_conversations: 8 },
    { name: 'xlarge', cpu: 16, memory_gb: 32, working_conversations: 16 },
];
type Plan = [usd: number, disk: number];
/** Cheapest first: the order a new machine tries them in. */
const HOSTS: { host: string; label: string; regions: string[]; plans: Record<string, Plan> }[] = [
    { host: 'hetzner', label: 'Hetzner', regions: ['eu'], plans: { small: [8.39, 40], medium: [12.59, 80], large: [22.79, 160], xlarge: [42.59, 320] } },
    { host: 'digitalocean', label: 'DigitalOcean', regions: REGIONS, plans: { small: [31.2, 80], medium: [62.4, 160], large: [124.8, 320] } },
];
/** The lab's stock at the start: Hetzner has no medium or xlarge in Europe, DigitalOcean no large in US East. */
export const SAMPLE_OUT = ['hetzner:eu:medium', 'hetzner:eu:xlarge', 'digitalocean:us-east:large'];

export interface MachineStock {
    /** `host:region:size` a host can't place now; a test may add to it, as a host running out. */
    out: Set<string>;
    sizes(query: URLSearchParams): Json[];
    /** POST /v1/machines: the machine made, or the refusal. */
    create(body: Json, id: string, now: string): { status: number; body: Json };
}

interface Offer {
    host: string;
    size: (typeof SIZES)[number];
    usd: number;
    disk: number;
    regions: string[];
}
interface Buyable {
    region: string | null;
    offer: Offer;
    available: boolean;
    dominatedBy?: string | null;
}

export function machineStock(hosts: 'two' | 'one' = 'two', out: string[] = SAMPLE_OUT): MachineStock {
    const registered = hosts === 'two' ? HOSTS : HOSTS.filter((h) => h.host === 'digitalocean');
    const stock = new Set(out);
    const offersOf = (size: (typeof SIZES)[number]): Offer[] =>
        registered.flatMap((h) => (h.plans[size.name] ? [{ host: h.host, size, usd: h.plans[size.name][0], disk: h.plans[size.name][1], regions: h.regions }] : []));
    const has = (o: Offer, region: string) => !stock.has(`${o.host}:${region}:${o.size.name}`);
    const beats = (a: Buyable, b: Buyable) => a.available && a.offer.size !== b.offer.size && a.offer.size.cpu >= b.offer.size.cpu && a.offer.size.memory_gb >= b.offer.size.memory_gb && a.offer.usd <= b.offer.usd;
    const dominance = (all: Buyable[]) =>
        all.map((b) => ({ ...b, dominatedBy: all.filter((o) => beats(o, b)).sort((x, y) => x.offer.usd - y.offer.usd || x.offer.size.cpu - y.offer.size.cpu)[0]?.offer.size.name ?? null }));
    const place = (b: Buyable) => ({ region: b.region, host: b.available ? b.offer.host : null, disk_gb: b.offer.disk, monthly_usd: b.offer.usd, dominated_by: b.dominatedBy ?? null });

    return {
        out: stock,
        sizes(query) {
            const every = query.get('include_dominated') === 'true';
            const sold = SIZES.map((size) => ({ size, offered: offersOf(size) })).filter((s) => s.offered.length);
            const places = REGIONS.flatMap((region) =>
                dominance(
                    sold
                        .filter((s) => s.offered.some((o) => o.regions.includes(region)))
                        .map(({ offered }) => {
                            const there = offered.filter((o) => o.regions.includes(region));
                            const landing = there.find((o) => has(o, region));
                            return { region, offer: landing ?? there[0], available: !!landing };
                        })
                )
            );
            const where = (name: string) => places.filter((b) => b.offer.size.name === name && b.available).sort((a, b) => a.offer.usd - b.offer.usd || REGIONS.indexOf(a.region!) - REGIONS.indexOf(b.region!));
            const here = dominance(sold.map(({ size, offered }) => where(size.name)[0] ?? { region: null, offer: offered[0], available: false }));
            return sold.flatMap(({ size, offered }, i) => {
                const now = here[i];
                if (!every && (!now.available || now.dominatedBy)) return [];
                const regions = where(size.name).filter((b) => every || !b.dominatedBy);
                return [
                    {
                        object: 'machine_size',
                        ...size,
                        available: now.available,
                        region: now.region,
                        host: now.available ? now.offer.host : null,
                        disk_gb: now.offer.disk,
                        monthly_usd: now.offer.usd,
                        dominated_by: now.dominatedBy ?? null,
                        regions: regions.map(place),
                        hosts: offered.map((o) => ({ host: o.host, regions: o.regions, disk_gb: o.disk, monthly_usd: o.usd })),
                    },
                ];
            });
        },
        create(body, id, now) {
            const size = SIZES.find((s) => s.name === body.size)!;
            const region = String(body.region);
            const max = Number(body.max_monthly_usd);
            const there = offersOf(size).filter((o) => o.regions.includes(region));
            const named = there.filter((o) => !body.host || o.host === body.host);
            const label = (host: string) => HOSTS.find((h) => h.host === host)!.label;
            const refuse = (status: number, type: string, message: string, extra: Json = {}) => ({ status, body: { error: { type, message, ...extra } } });
            if (!named.length) return refuse(409, 'not_available', `A ${size.name} machine doesn't run in ${region}.`);
            if (named[0].usd > max) return refuse(402, 'price_exceeded', `A ${size.name} machine on ${label(named[0].host)} costs $${named[0].usd.toFixed(2)} a month, above max_monthly_usd ($${max.toFixed(2)}).`);
            const landing = named.find((o) => o.usd <= max && has(o, region));
            if (!landing) {
                const other = there.find((o) => !named.includes(o) && has(o, region));
                if (!other) return refuse(409, 'not_available', 'No machine of that size can be placed in that region right now.', { next_step: 'Retry in a few minutes, or pick another region or size.' });
                const said = `${label(named[0].host)} can't place a ${size.name} machine in ${region} right now; ${label(other.host)} can, at $${other.usd.toFixed(2)} a month`;
                const step = `quote it with host "${other.host}" ($${other.usd.toFixed(2)} a month), or retry in a few minutes.`;
                return other.usd > max
                    ? refuse(402, 'price_exceeded', `${said}, above max_monthly_usd ($${max.toFixed(2)}).`, { next_step: `Agree to its price there: pass max_monthly_usd ${other.usd.toFixed(2)} or ${step}`, host: other.host, monthly_usd: other.usd })
                    : refuse(409, 'not_available', `${said}.`, { next_step: `To place it there, ${step}`, host: other.host, monthly_usd: other.usd });
            }
            const machine = { object: 'machine', id, name: body.name, kind: 'noclick', status: 'provisioning', size: size.name, region, host: landing.host, cpu: size.cpu, memory_gb: size.memory_gb, disk_gb: landing.disk, monthly_usd: landing.usd, max_monthly_usd: max, created_at: now };
            return { status: 201, body: machine };
        },
    };
}

const reply = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

/** The picker's two calls over a fake's own machines: the sizes, and buying one (pushed onto `machines` once made, a
 *  taken name refused as the API refuses it). With `vetting`, a company not yet approved is refused until it's sent,
 *  and while it's reviewed the machine is held (`awaiting_approval`, nothing charged). Undefined for any other request. */
export function machineRoutes(
    world: { machines: Json[]; stock: MachineStock; id: () => string; now: () => string; vetting?: { value: Json } },
    method: string,
    path: string,
    query: URLSearchParams,
    body: Json
): Response | undefined {
    if (method === 'GET' && path === '/v1/machines/sizes') return reply({ object: 'list', data: world.stock.sizes(query), next_cursor: null });
    if (method !== 'POST' || path !== '/v1/machines') return undefined;
    if (world.machines.some((m) => m.name === body.name)) return reply({ error: { type: 'conflict', message: `A machine named '${body.name}' already exists.` } }, 409);
    const held = world.vetting ? heldPurchase({ vetting: world.vetting }) : undefined;
    if (held instanceof Response) return held;
    const bought = world.stock.create(body, world.id(), world.now());
    if (bought.status === 201 && held === 'held') Object.assign(bought.body, { status: 'awaiting_approval', spent_usd_this_month: 0 });
    if (bought.status === 201) world.machines.push(bought.body);
    return reply(bought.body, bought.status);
}
