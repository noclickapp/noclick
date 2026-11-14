// The NoClick mascot kit: parts as SVG strings in a 100×100 disc, composed by a generator seeded by the agent's id.
// Every value drawn comes from this catalog or from numbers: a seed is only ever hashed and a name only ever matched
// against keywords, so no text an agent carries can reach the markup.
import type { AgentHue } from '../types';

const K = '#141414';
const W = '#ffffff';
const D = 'var(--d)';
const BLUSH = '#ff8db4';
const RED = '#ef4444';
const PAINT = '#7dd3fc';

// ── seeded randomness ────────────────────────────────────────────────────────

/** FNV-1a over the string's UTF-16 units. */
export function hash(str: string): number {
    let h = 2166136261;
    for (const c of str) {
        h ^= c.charCodeAt(0);
        h = Math.imul(h, 16777619);
    }
    return h >>> 0;
}

/** mulberry32 seeded by `hash(seed)`. */
function rng(seed: string): () => number {
    let a = hash(seed);
    return () => {
        a |= 0;
        a = (a + 0x6d2b79f5) | 0;
        let t = Math.imul(a ^ (a >>> 15), 1 | a);
        t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
}
const between = (r: () => number, a: number, b: number) => a + r() * (b - a);
const r1 = (n: number) => Math.round(n * 10) / 10;
const r2 = (n: number) => Math.round(n * 100) / 100;

// ── palette: the order the generator rolls a hue in when none is given ───────

export const KIT_HUES: readonly AgentHue[] = ['sky', 'blue', 'violet', 'purple', 'fuchsia', 'pink', 'teal', 'emerald'];

// ── bodies: one shoulders shape, six heads ───────────────────────────────────
// Heads are wide squircles (about 1.17× wider than tall) that flow into the shoulders as one outline.

interface Head {
    cx: number;
    cy: number;
    rx: number;
    ry: number;
    rot?: number;
}
interface Body {
    key: 'round' | 'lean' | 'tuft' | 'ears' | 'cowlick' | 'antenna';
    head: Head;
    bumps?: [number, number, number][];
    ears?: boolean;
    curl?: boolean;
    antenna?: boolean;
}
export const BODIES: readonly Body[] = [
    { key: 'round', head: { cx: 50, cy: 50, rx: 27.5, ry: 23.5 } },
    { key: 'lean', head: { cx: 51, cy: 50.5, rx: 27, ry: 23, rot: -9 } },
    { key: 'tuft', head: { cx: 50, cy: 51.5, rx: 27, ry: 22.5 }, bumps: [[38, 34.5, 8.5], [50, 30, 10], [62, 34.5, 8.5]] },
    { key: 'ears', head: { cx: 50, cy: 50, rx: 26, ry: 23 }, ears: true },
    { key: 'cowlick', head: { cx: 50, cy: 50.5, rx: 27.5, ry: 23 }, curl: true },
    { key: 'antenna', head: { cx: 50, cy: 50.5, rx: 27.5, ry: 23 }, antenna: true },
];
const SHOULDERS = 'M20 110C20 85 33 68.5 50 68.5S80 85 80 110Z';

// ── faces ────────────────────────────────────────────────────────────────────

type Eyes = 'dot' | 'happy' | 'wink' | 'glance' | 'wide' | 'closed';
type Mouth = 'smile' | 'grin' | 'small' | 'smirk' | 'o' | 'pout' | 'frown';
type Brows = 'curious' | 'bright' | 'worried';
type Accent = 'ticks' | 'zz' | 'sparkle' | 'dot';
interface Face {
    eyes: Eyes;
    mouth: Mouth;
    brows?: Brows;
    blush?: boolean;
}

/** The six resting faces (calm, content, cheerful, curious, bright, wink): the waiting state wears the seed's. */
export const REST: readonly Face[] = [
    { eyes: 'dot', mouth: 'smile' },
    { eyes: 'happy', mouth: 'smile' },
    { eyes: 'dot', mouth: 'grin', blush: true },
    { eyes: 'dot', mouth: 'small', brows: 'curious' },
    { eyes: 'dot', mouth: 'smirk', brows: 'bright' },
    { eyes: 'wink', mouth: 'smile', blush: true },
];

export type MascotState = 'working' | 'waiting' | 'needs' | 'asleep' | 'done' | 'failed';
interface StateLook extends Partial<Face> {
    /** Its loop's length in seconds. */
    loop: number;
    /** Wears the seed's resting face rather than one of its own. */
    rest?: boolean;
    accent?: Accent;
}
export const STATES: Readonly<Record<MascotState, StateLook>> = {
    working: { loop: 3.2, eyes: 'glance', mouth: 'smile', accent: 'ticks' },
    waiting: { loop: 3.6, rest: true },
    needs: { loop: 2.4, eyes: 'wide', mouth: 'o', accent: 'ticks' },
    asleep: { loop: 4, eyes: 'closed', mouth: 'pout', accent: 'zz' },
    done: { loop: 2.8, eyes: 'happy', mouth: 'grin', accent: 'sparkle' },
    failed: { loop: 3.6, eyes: 'dot', mouth: 'frown', brows: 'worried', accent: 'dot' },
};

// ── props: what an agent wears or holds for its job ──────────────────────────
// Slots: top (hats), ear (headset, pencil), face (glasses, magnifier), hands (held at the chest), beside (floats right).

type Slot = 'top' | 'ear' | 'face' | 'hands' | 'beside';
interface PropDef {
    slot: Slot;
    /** Raised up the right side: moves to the left hand when something floats beside. */
    right?: boolean;
    /** Drawn behind the head. */
    back?: boolean;
}
export const PROPS = {
    headset: { slot: 'ear' },
    newshat: { slot: 'top' },
    magnifier: { slot: 'face' },
    parcel: { slot: 'hands' },
    calendar: { slot: 'beside' },
    bubble: { slot: 'beside' },
    glasses: { slot: 'face' },
    envelope: { slot: 'beside' },
    phone: { slot: 'hands' },
    bag: { slot: 'hands' },
    chart: { slot: 'beside' },
    code: { slot: 'beside' },
    chefhat: { slot: 'top' },
    wrench: { slot: 'hands', right: true },
    brush: { slot: 'hands', right: true },
    gradcap: { slot: 'top' },
    globe: { slot: 'beside' },
    briefcase: { slot: 'hands' },
    clipboard: { slot: 'hands' },
    bell: { slot: 'beside' },
    megaphone: { slot: 'beside' },
    tag: { slot: 'beside' },
    pencil: { slot: 'ear', back: true },
    book: { slot: 'hands' },
    beanie: { slot: 'top' },
    mug: { slot: 'hands' },
} as const satisfies Record<string, PropDef>;
export type PropKey = keyof typeof PROPS;
const propDef = (k: PropKey): PropDef => PROPS[k];
export const PROP_KEYS = Object.keys(PROPS) as PropKey[];

type AccessoryKey = 'none' | 'blush' | 'bowtie' | 'sprout' | 'clip';
const ACCESSORIES: readonly { key: Exclude<AccessoryKey, 'none'>; slot: Slot | 'cheeks' }[] = [
    { key: 'blush', slot: 'cheeks' },
    { key: 'bowtie', slot: 'hands' },
    { key: 'sprout', slot: 'top' },
    { key: 'clip', slot: 'ear' },
];

// Role words → props, earliest match first.
const KEYWORDS: readonly [RegExp, PropKey][] = [
    [/support|help ?desk|customer|ticket|returns?/, 'headset'],
    [/news|digest|summar|newsletter|brief/, 'newshat'],
    [/lead|prospect|scout|search|find/, 'magnifier'],
    [/order|ship|parcel|deliver|fulfil|warehouse|stock|inventory/, 'parcel'],
    [/schedul|calendar|booking|meeting|appointment|reservation/, 'calendar'],
    [/chat|whatsapp|message|telegram|reply|\bdm/, 'bubble'],
    [/email|inbox|mail|gmail|outlook/, 'envelope'],
    [/call|phone|voice|sms|text/, 'phone'],
    [/shop|store|cart|commerce|shopify|retail/, 'bag'],
    [/report|chart|metric|analytic|dashboard|kpi|data/, 'chart'],
    [/code|develop|engineer|github|bug|deploy|\bapi\b|review/, 'code'],
    [/cook|chef|recipe|restaurant|menu|kitchen|food|bak/, 'chefhat'],
    [/fix|repair|maintenance|devops|on-?call|\bops\b|infra/, 'wrench'],
    [/design|art|brand|image|illustrat|paint/, 'brush'],
    [/teach|tutor|course|student|learn|school|lesson/, 'gradcap'],
    [/web|browse|translat|language|global|travel/, 'globe'],
    [/sales|deal|crm|finance|invoice|account|legal|contract/, 'briefcase'],
    [/approv|\bqa\b|check|audit|compliance|form|survey/, 'clipboard'],
    [/remind|alert|notif|monitor|watch/, 'bell'],
    [/market|social|post|announce|campaign|promo/, 'megaphone'],
    [/price|pricing|discount|listing|coupon/, 'tag'],
    [/write|blog|copy|content|draft|journal|note/, 'pencil'],
    [/doc|knowledge|faq|wiki|manual|book\b|library|read|research/, 'book'],
    [/winter|outdoor|ski|weather/, 'beanie'],
    [/coffee|morning|assistant|errand/, 'mug'],
];

/** One or two props for a role, in the order its words name them, never two in one slot. */
export function propsFor(text: string | null | undefined): PropKey[] {
    const t = (text ?? '').toLowerCase();
    const hits: [number, PropKey][] = [];
    for (const [re, prop] of KEYWORDS) {
        const m = re.exec(t);
        if (m) hits.push([m.index, prop]);
    }
    hits.sort((a, b) => a[0] - b[0]);
    const out: PropKey[] = [];
    const slots = new Set<Slot>();
    for (const [, p] of hits) {
        if (out.includes(p) || slots.has(propDef(p).slot)) continue;
        out.push(p);
        slots.add(propDef(p).slot);
        if (out.length === 2) break;
    }
    return out;
}

// ── generator ────────────────────────────────────────────────────────────────

/** One mascot's look: catalog keys and numbers only. */
export interface MascotLook {
    hue: AgentHue;
    body: number;
    scale: number;
    tilt: number;
    fdx: number;
    gap: number;
    rest: number;
    acc: AccessoryKey;
    props: PropKey[];
    /** Each prop's tilt and its alternate look. */
    pv: { tilt: number; alt: boolean }[];
    hw: number;
    hh: number;
    eye: number;
    oval: number;
    mw: number;
    fdy: number;
    ear: number;
    flip: boolean;
}

/** The look `seed` rolls. The props' own details roll from a stream of their own, so the head and face a seed gets stay
 *  the same whatever props it wears (a surface that knows no role draws the same agent, without them). */
export function generate(seed: string, props: readonly PropKey[], hue?: AgentHue): MascotLook {
    const r = rng(seed);
    const body = Math.floor(r() * BODIES.length);
    const worn = props.slice(0, 2);
    const slots = new Set<Slot | 'cheeks'>(worn.map((p) => propDef(p).slot));
    const accOk = ACCESSORIES.filter((a) => !slots.has(a.slot) && !(a.key === 'sprout' && ['tuft', 'cowlick', 'antenna'].includes(BODIES[body].key)));
    const accRoll = r();
    const rolledHue = KIT_HUES[Math.floor(r() * KIT_HUES.length)];
    const scale = r1(between(r, 0.96, 1.04) * 100) / 100;
    const tilt = r1(between(r, -3, 3));
    const fdx = r1(between(r, -1.8, 1.8));
    const gap = r1(between(r, 10, 11.6));
    const rest = Math.floor(r() * REST.length);
    const acc: AccessoryKey = accRoll < 0.42 || !accOk.length ? 'none' : accOk[Math.floor(r() * accOk.length)].key;
    const pr = rng(`${seed}:props`);
    return {
        hue: hue ?? rolledHue,
        body,
        scale,
        tilt,
        fdx,
        gap,
        rest,
        acc,
        props: worn,
        pv: worn.map(() => ({ tilt: r1(between(pr, -6, 6)), alt: pr() < 0.5 })),
        hw: r2(between(r, 0.94, 1.07)),
        hh: r2(between(r, 0.96, 1.05)),
        eye: r2(between(r, 0.86, 1.2)),
        oval: r2(between(r, 1.15, 1.45)),
        mw: r2(between(r, 0.85, 1.2)),
        fdy: r1(between(r, -1.2, 1.6)),
        ear: r1(between(r, 6, 9)),
        flip: r() < 0.5,
    };
}

// ── drawing ──────────────────────────────────────────────────────────────────

interface Geom {
    B: Body;
    h: Head;
    bumps: [number, number, number][] | undefined;
    hx: number;
    hy: number;
    rx: number;
    ry: number;
    rot: number;
    top: number;
    fx: number;
    fy: number;
}

function geom(p: MascotLook, xs: boolean): Geom {
    const B = BODIES[p.body];
    const hw = p.hw;
    const h: Head = { ...B.head, rx: r1(B.head.rx * hw), ry: r1(B.head.ry * p.hh) };
    const top = h.cy - h.ry;
    const lift = top - (B.head.cy - B.head.ry);
    const bumps = B.bumps?.map(([x, y, r]): [number, number, number] => [r1(h.cx + (x - h.cx) * hw), r1(y + lift), r]);
    const fx = h.cx + (h.rot ? 1.5 : 0) + (xs ? 0 : p.fdx);
    const fy = h.cy + 1.5 + (xs ? 0 : p.fdy);
    return { B, h, bumps, hx: h.cx, hy: h.cy, rx: h.rx, ry: h.ry, rot: h.rot ?? 0, top, fx, fy };
}

// A squircle: squarer across the crown, rounder at the chin.
function headPath(h: Head): string {
    const { cx, cy, rx, ry } = h;
    const k = 0.63;
    const kb = 0.56;
    const P = (dx: number, dy: number) => `${r1(cx + dx)} ${r1(cy + dy)}`;
    const d = `M${P(0, -ry)}C${P(k * rx, -ry)} ${P(rx, -k * ry)} ${P(rx, 0)}C${P(rx, kb * ry)} ${P(kb * rx, ry)} ${P(0, ry)}C${P(-kb * rx, ry)} ${P(-rx, kb * ry)} ${P(-rx, 0)}C${P(-rx, -k * ry)} ${P(-k * rx, -ry)} ${P(0, -ry)}Z`;
    return `<path d="${d}"${h.rot ? ` transform="rotate(${h.rot} ${cx} ${cy})"` : ''}/>`;
}
// Shapes outlined as one silhouette: thick strokes first, white fills over them.
const union = (shapes: string, sw: number, fill = W) => `<g fill="none" stroke="${K}" stroke-width="${2 * sw}" stroke-linejoin="round">${shapes}</g><g fill="${fill}">${shapes}</g>`;
const handPair = (sw: number, y = 88, l = 36, rr = 64) => `<g fill="${W}" stroke="${K}" stroke-width="${sw}"><circle cx="${l}" cy="${y}" r="4.6"/><circle cx="${rr}" cy="${y}" r="4.6"/></g>`;

// Upright ovals (oval = height ÷ size) from 40px; small sizes keep round dots so they still read.
function eyes(type: Eyes, G: Geom, gap: number, er: number, sw: number, oval: number): string {
    const L = G.fx - gap;
    const R = G.fx + gap;
    const y = G.fy;
    const dot = (x: number, yy = y, r = er) => (oval ? `<ellipse cx="${x}" cy="${yy}" rx="${r1(r * 0.76)}" ry="${r1(r * oval)}" fill="${K}"/>` : `<circle cx="${x}" cy="${yy}" r="${r}" fill="${K}"/>`);
    const arc = (x: number, up: boolean) =>
        up
            ? `<path d="M${x - er * 1.45} ${y + er * 0.55}Q${x} ${y - er * 1.7} ${x + er * 1.45} ${y + er * 0.55}" fill="none" stroke="${K}" stroke-width="${Math.max(sw * 0.8, er * 0.95)}" stroke-linecap="round"/>`
            : `<path d="M${x - er * 1.45} ${y - er * 0.35}Q${x} ${y + er * 1.6} ${x + er * 1.45} ${y - er * 0.35}" fill="none" stroke="${K}" stroke-width="${Math.max(sw * 0.8, er * 0.95)}" stroke-linecap="round"/>`;
    let s: string;
    switch (type) {
        case 'glance':
            s = dot(L) + dot(R) + `<circle cx="${L + er * 0.38}" cy="${y - er * 0.38}" r="${er * 0.36}" fill="${W}"/><circle cx="${R + er * 0.38}" cy="${y - er * 0.38}" r="${er * 0.36}" fill="${W}"/>`;
            break;
        case 'wide':
            s =
                sw > 3.2
                    ? dot(L, y - er * 0.5, er * 1.12) + dot(R, y - er * 0.5, er * 1.12)
                    : [L, R].map((x) => `<circle cx="${x}" cy="${y}" r="${er * 1.6}" fill="${W}" stroke="${K}" stroke-width="${sw * 0.62}"/><circle cx="${x}" cy="${y - er * 0.6}" r="${er * 0.88}" fill="${K}"/>`).join('');
            break;
        case 'happy':
            s = arc(L, true) + arc(R, true);
            break;
        case 'closed':
            s = arc(L, false) + arc(R, false);
            break;
        case 'wink':
            s = dot(L) + arc(R, true);
            break;
        default:
            s = dot(L) + dot(R);
    }
    return `<g class="m-eyes"><g class="m-lids">${s}</g></g>`;
}

// mw widens or narrows the mouth without thickening its line.
function mouth(type: Mouth, G: Geom, sw: number, mw: number): string {
    const x = G.fx;
    const y = G.fy + 7;
    const st = `fill="none" stroke="${K}" stroke-width="${sw * 0.85}" stroke-linecap="round" stroke-linejoin="round"`;
    const X = (d: number) => r1(x + d * mw);
    switch (type) {
        case 'smile':
            return `<path d="M${X(-4.2)} ${y - 0.6}Q${x} ${y + 3.6} ${X(4.2)} ${y - 0.6}" ${st}/>`;
        case 'grin':
            return `<path d="M${X(-4.6)} ${y - 1}Q${x} ${y + 6.4} ${X(4.6)} ${y - 1}Z" fill="${K}" stroke="${K}" stroke-width="${sw * 0.5}" stroke-linejoin="round"/><path d="M${X(-2.2)} ${y + 2.7}Q${x} ${y + 1.5} ${X(2.2)} ${y + 2.7}Q${x} ${y + 4.1} ${X(-2.2)} ${y + 2.7}Z" fill="${BLUSH}"/>`;
        case 'small':
            return `<path d="M${X(-2)} ${y}Q${x} ${y + 1.8} ${X(2)} ${y}" ${st}/>`;
        case 'smirk':
            return `<path d="M${X(-3.4)} ${y + 0.2}Q${X(0.4)} ${y + 3.2} ${X(3.8)} ${y - 1}" ${st}/>`;
        case 'o':
            return `<ellipse cx="${x}" cy="${y + 1}" rx="${r1(1.6 * mw)}" ry="2" fill="${K}"/>`;
        case 'pout':
            return `<path d="M${x - 1.6} ${y + 0.6}Q${x + 1.6} ${y - 0.4} ${x + 0.6} ${y + 1.6}Q${x + 2} ${y + 2.6} ${x - 0.8} ${y + 3}" ${st}/>`;
        case 'frown':
            return `<path d="M${X(-3.3)} ${y + 2.2}Q${x} ${y - 1.2} ${X(3.3)} ${y + 2.2}" ${st}/>`;
    }
}

function brows(type: Brows | undefined, G: Geom, gap: number, sw: number): string {
    if (!type) return '';
    const L = G.fx - gap;
    const R = G.fx + gap;
    const y = G.fy - 6.4;
    const st = `fill="none" stroke="${K}" stroke-width="${sw * 0.8}" stroke-linecap="round"`;
    if (type === 'worried') return `<path d="M${L - 3.2} ${y + 0.6}L${L + 2.6} ${y - 1.8}M${R + 3.2} ${y + 0.6}L${R - 2.6} ${y - 1.8}" ${st}/>`;
    if (type === 'bright') return `<path d="M${L - 2.9} ${y + 0.2}Q${L} ${y - 2.6} ${L + 2.9} ${y + 0.2}M${R - 2.9} ${y + 0.2}Q${R} ${y - 2.6} ${R + 2.9} ${y + 0.2}" ${st}/>`;
    return `<path d="M${L - 2.8} ${y + 0.4}L${L + 2.6} ${y + 0.2}M${R - 2.8} ${y - 0.6}Q${R} ${y - 3.4} ${R + 2.8} ${y - 1}" ${st}/>`;
}

function accent(type: Accent, sw: number, sm: boolean): string {
    const w = sm ? Math.max(3.4, sw * 1.15) : 3.4;
    const tk = `stroke="${W}" stroke-width="${w}" stroke-linecap="round"`;
    switch (type) {
        case 'ticks':
            return `<g class="m-ticks"><path class="m-t m-t1" d="M70.6 15.8L73 9.6" ${tk}/><path class="m-t m-t2" d="M77 19.8L81.6 14.8" ${tk}/><path class="m-t m-t3" d="M80.6 26.6L86.6 24.2" ${tk}/></g>`;
        case 'zz':
            return `<g fill="none" stroke="${W}" stroke-width="${w * 0.82}" stroke-linecap="round" stroke-linejoin="round"><path class="m-z m-z1" d="M70.6 24.6h4.8l-4.8 5.2h4.8"/><path class="m-z m-z2" d="M76.4 14.4h6.4l-6.4 7h6.4"/></g>`;
        case 'sparkle':
            return `<path class="m-spk" d="M77 10.5Q78.2 17.3 85 18.5Q78.2 19.7 77 26.5Q75.8 19.7 69 18.5Q75.8 17.3 77 10.5Z" fill="${W}"/>`;
        case 'dot':
            return `<circle class="m-rd" cx="79" cy="21" r="${sm ? 9.5 : 6.6}" fill="${RED}" stroke="${K}" stroke-width="${sw}"/>`;
    }
}

interface PropCtx {
    sw: number;
    alt: boolean;
    tilt: number;
    detail: boolean;
    er: number;
    gap: number;
}

// Each prop drawn on the head's geometry.
const PROP_DRAW: Record<PropKey, (G: Geom, c: PropCtx) => string> = {
    headset(G, c) {
        const L = G.hx - G.rx;
        const R = G.hx + G.rx;
        const y = G.hy + 2;
        const m = c.alt ? -1 : 1;
        const cup = (x: number) => `<rect x="${x - 4.2}" y="${y - 7}" width="8.4" height="14" rx="4.2" fill="${K}"/>`;
        const side = m > 0 ? L : R;
        const inner = G.fx - m * 9.5;
        return (
            `<path d="M${L - 0.6} ${y - 1}C${L - 1.5} ${G.top - 10} ${R + 1.5} ${G.top - 10} ${R + 0.6} ${y - 1}" fill="none" stroke="${K}" stroke-width="${c.sw * 1.55}" stroke-linecap="round"/>` +
            cup(L) +
            cup(R) +
            `<path d="M${side + m * 1.2} ${y + 6}Q${side + m * 3} ${y + 15.5} ${inner} ${y + 15.2}" fill="none" stroke="${K}" stroke-width="${c.sw * 0.95}" stroke-linecap="round"/>` +
            `<rect x="${inner - 3.2}" y="${y + 12.9}" width="6.4" height="4.8" rx="2.4" fill="${K}"/>`
        );
    },
    newshat(G, c) {
        const x = G.hx;
        const T = G.top;
        const det = c.detail
            ? `<g stroke="${K}" stroke-width="${c.sw * 0.55}" stroke-linecap="round" fill="none"><path d="M${x - 19} ${T + 7.6}l7.5-1.4M${x - 17.5} ${T + 3}l6-1.1M${x + 1} ${T + 6.2}h15M${x + 1.5} ${T + 9.6}h11"/><rect x="${x + 1.2}" y="${T - 3.4}" width="7.4" height="5.4" rx="0.8"/><path d="M${x + 11} ${T - 2}h5.5M${x + 11} ${T + 1}h4"/></g>`
            : '';
        return `<g transform="rotate(${c.alt ? -7 : 6} ${x} ${T + 3})"><path d="M${x - 25.5} ${T + 11.5}L${x - 11} ${T - 7.5}L${x + 13.5} ${T - 9.5}L${x + 26.5} ${T + 9.5}L${x + 21} ${T + 13.5}L${x - 20.5} ${T + 15.5}Z" fill="${W}" stroke="${K}" stroke-width="${c.sw}" stroke-linejoin="round"/><path d="M${x - 11} ${T - 7.5}L${x - 4.5} ${T + 14.6}" stroke="${K}" stroke-width="${c.sw * 0.75}" stroke-linecap="round"/>${det}</g>`;
    },
    chefhat(G, c) {
        const x = G.hx;
        const T = G.top;
        const shapes = `<circle cx="${x - 10}" cy="${T - 3}" r="8.5"/><circle cx="${x + 1}" cy="${T - 8}" r="10"/><circle cx="${x + 11}" cy="${T - 2.5}" r="8"/><rect x="${x - 14}" y="${T - 1}" width="28" height="11" rx="3"/>`;
        return `<g transform="rotate(${c.tilt * 0.5} ${x} ${T + 4})">${union(shapes, c.sw)}<path d="M${x - 5} ${T + 1.5}v6M${x + 4.5} ${T + 1.5}v6" stroke="${K}" stroke-width="${c.sw * 0.6}" stroke-linecap="round"/></g>`;
    },
    gradcap(G, c) {
        const x = G.hx;
        const T = G.top + 1;
        const m = c.alt ? -1 : 1;
        return `<g transform="rotate(${c.tilt * 0.6} ${x} ${T})"><path d="M${x - 14} ${T + 2}V${T + 9}Q${x} ${T + 15} ${x + 14} ${T + 9}V${T + 2}Z" fill="${K}"/><path d="M${x - 26} ${T + 1}L${x} ${T - 8.5}L${x + 26} ${T + 1}L${x} ${T + 10.5}Z" fill="${K}" stroke="${K}" stroke-width="${c.sw}" stroke-linejoin="round"/><path d="M${x} ${T + 1}L${x + m * 17} ${T + 5}" fill="none" stroke="${W}" stroke-width="${c.sw * 0.7}" stroke-linecap="round"/><path d="M${x + m * 17} ${T + 5}V${T + 13}" fill="none" stroke="${K}" stroke-width="${c.sw * 0.7}" stroke-linecap="round"/><path d="M${x + m * 17 - 2.4} ${T + 18.5}L${x + m * 17 - 1.4} ${T + 12.5}H${x + m * 17 + 1.4}L${x + m * 17 + 2.4} ${T + 18.5}Z" fill="${K}" stroke="${K}" stroke-width="${c.sw * 0.5}" stroke-linejoin="round"/></g>`;
    },
    beanie(G, c) {
        const x = G.hx;
        const T = G.top;
        return `<g transform="rotate(${c.tilt * 0.6} ${x} ${T + 6})"><path d="M${x - 23} ${T + 11}C${x - 23} ${T - 8} ${x + 23} ${T - 8} ${x + 23} ${T + 11}Z" fill="${D}" stroke="${K}" stroke-width="${c.sw}" stroke-linejoin="round"/><rect x="${x - 25}" y="${T + 7}" width="50" height="8.5" rx="4.25" fill="${W}" stroke="${K}" stroke-width="${c.sw}"/><circle cx="${x}" cy="${T - 6.5}" r="4.8" fill="${W}" stroke="${K}" stroke-width="${c.sw}"/>${c.detail ? `<path d="M${x - 9} ${T - 1}v6M${x} ${T - 2.4}v7M${x + 9} ${T - 1}v6" stroke="${K}" stroke-width="${c.sw * 0.5}" stroke-linecap="round" opacity=".55"/>` : ''}</g>`;
    },
    glasses(G, c) {
        const L = G.fx - c.gap;
        const R = G.fx + c.gap;
        const y = G.fy;
        const r = c.alt ? 6.4 : 6.2;
        const frame = (x: number) => (c.alt ? `<rect x="${x - 6.6}" y="${y - 5.4}" width="13.2" height="10.8" rx="4.2"/>` : `<circle cx="${x}" cy="${y}" r="${r}"/>`);
        return `<g fill="none" stroke="${K}" stroke-width="${c.sw * 0.85}" stroke-linecap="round">${frame(L)}${frame(R)}<path d="M${L + r} ${y - 0.8}Q${G.fx} ${y - 3} ${R - r} ${y - 0.8}M${L - r} ${y - 1.4}L${G.hx - G.rx + 1.2} ${y - 3.6}M${R + r} ${y - 1.4}L${G.hx + G.rx - 1.2} ${y - 3.6}"/></g>`;
    },
    magnifier(G, c) {
        const x = G.fx + c.gap + 1.2;
        const y = G.fy + 0.4;
        const r = 7.4;
        return `<path d="M${x + 4.8} ${y + 5.4}L${x + 13} ${y + 14.5}" stroke="${K}" stroke-width="${c.sw * 2.3}" stroke-linecap="round"/><circle cx="${x}" cy="${y}" r="${r}" fill="${W}" fill-opacity=".35" stroke="${K}" stroke-width="${c.sw}"/><circle cx="${x}" cy="${y}" r="${c.er * 1.5}" fill="${K}"/><path d="M${x - 4.2} ${y - 2.2}A4.8 4.8 0 0 1 ${x - 1.6} ${y - 4.6}" fill="none" stroke="${K}" stroke-width="${c.sw * 0.55}" stroke-linecap="round"/>`;
    },
    pencil(G, c) {
        const R = G.hx + G.rx + 4;
        const y = r1(G.hy - G.ry * 0.5);
        return `<g transform="rotate(-38 ${R} ${y})"><rect x="${R - 13}" y="${y - 2.8}" width="17" height="5.6" rx="1" fill="${W}" stroke="${K}" stroke-width="${c.sw}"/><path d="M${R + 4} ${y - 2.8}L${R + 10} ${y}L${R + 4} ${y + 2.8}Z" fill="${W}" stroke="${K}" stroke-width="${c.sw}" stroke-linejoin="round"/><path d="M${R + 8.2} ${y - 0.85}L${R + 10} ${y}L${R + 8.2} ${y + 0.85}Z" fill="${K}"/><rect x="${R - 17}" y="${y - 2.8}" width="4.6" height="5.6" rx="1.6" fill="${BLUSH}" stroke="${K}" stroke-width="${c.sw}"/></g>`;
    },
    parcel(_G, c) {
        return `<g transform="rotate(${c.tilt * 0.4} 50 86)"><rect x="37" y="76" width="26" height="21" rx="2.5" fill="${W}" stroke="${K}" stroke-width="${c.sw}"/><path d="M37 82H63" stroke="${K}" stroke-width="${c.sw * 0.7}"/><path d="M46.6 76V86.5L50 84L53.4 86.5V76" fill="${c.alt ? D : W}" stroke="${K}" stroke-width="${c.sw * 0.7}" stroke-linejoin="round"/></g>${handPair(c.sw)}`;
    },
    envelope(_G, c) {
        return `<g transform="rotate(${c.tilt * 0.8 - 4} 80 55)"><rect x="67.5" y="46.5" width="25" height="17.5" rx="2.6" fill="${W}" stroke="${K}" stroke-width="${c.sw}"/><path d="M68.8 48L80 56.4L91.2 48" fill="none" stroke="${K}" stroke-width="${c.sw * 0.85}" stroke-linejoin="round" stroke-linecap="round"/>${c.alt ? `<circle cx="80" cy="56.4" r="2.5" fill="${D}" stroke="${K}" stroke-width="${c.sw * 0.6}"/>` : ''}</g>`;
    },
    phone(_G, c) {
        return `<g transform="rotate(${c.tilt * 0.5} 50 85)"><rect x="41.5" y="71.5" width="17" height="27" rx="3.8" fill="${K}"/><rect x="44" y="75" width="12" height="18" rx="1.6" fill="${c.alt ? W : D}"/>${c.alt ? `<path d="M46.5 80h7M46.5 83.5h5" stroke="${K}" stroke-width="${c.sw * 0.5}" stroke-linecap="round"/>` : ''}</g>${handPair(c.sw, 88, 38.5, 61.5)}`;
    },
    bag(_G, c) {
        return `<g transform="rotate(${c.tilt * 0.4} 50 88)"><path d="M44.5 80.5V77a5.5 5.5 0 0 1 11 0v3.5" fill="none" stroke="${K}" stroke-width="${c.sw}" stroke-linecap="round"/><path d="M37.5 80H62.5L64.5 99H35.5Z" fill="${c.alt ? D : W}" stroke="${K}" stroke-width="${c.sw}" stroke-linejoin="round"/>${c.alt ? '' : `<circle cx="50" cy="87" r="2.4" fill="${D}" stroke="${K}" stroke-width="${c.sw * 0.6}"/>`}</g>${handPair(c.sw, 89, 35.5, 64.5)}`;
    },
    briefcase(_G, c) {
        return `<g transform="rotate(${c.tilt * 0.4} 50 88)"><path d="M45 79.5V76.5a2 2 0 0 1 2-2h6a2 2 0 0 1 2 2v3" fill="none" stroke="${K}" stroke-width="${c.sw}"/><rect x="35" y="79" width="30" height="19.5" rx="3.2" fill="${c.alt ? K : W}" stroke="${K}" stroke-width="${c.sw}"/><path d="M35 86.5H65" stroke="${c.alt ? W : K}" stroke-width="${c.sw * 0.6}"/><rect x="47.5" y="84.5" width="5" height="4" rx="1" fill="${c.alt ? W : K}"/></g>${handPair(c.sw, 90, 34, 66)}`;
    },
    clipboard(_G, c) {
        return `<g transform="rotate(${c.tilt * 0.4} 50 86)"><rect x="39" y="73" width="22" height="27" rx="2.6" fill="${W}" stroke="${K}" stroke-width="${c.sw}"/><rect x="44.5" y="70.4" width="11" height="5.6" rx="2" fill="${K}"/><path d="M43.5 81.6l2.2 2.3 4.2-4.6" fill="none" stroke="${c.alt ? D : K}" stroke-width="${c.sw * 0.8}" stroke-linecap="round" stroke-linejoin="round"/><path d="M52 81.6h5M43.5 88.5h13.5M43.5 93.4h9" stroke="${K}" stroke-width="${c.sw * 0.6}" stroke-linecap="round"/></g>${handPair(c.sw, 90, 37.5, 62.5)}`;
    },
    book(_G, c) {
        const page = 'M50 79C45.6 76.6 40.6 76.4 36.5 78V97C40.6 95.4 45.6 95.6 50 98Z';
        return `<g transform="rotate(${c.tilt * 0.5} 50 87)"><path d="M34.5 80.5V99.2C40 97.6 45.4 98 50 100.2C54.6 98 60 97.6 65.5 99.2V80.5Z" fill="${c.alt ? D : K}" stroke="${K}" stroke-width="${c.sw}" stroke-linejoin="round"/><g fill="${W}" stroke="${K}" stroke-width="${c.sw}" stroke-linejoin="round"><path d="${page}"/><path d="${page}" transform="translate(100 0) scale(-1 1)"/></g><path d="M40 83.2Q43.4 82.4 46.6 83.8M40 87.4Q43.4 86.6 46.6 88M53.4 83.8Q56.6 82.4 60 83.2M53.4 88Q56.6 86.6 60 87.4" fill="none" stroke="${K}" stroke-width="${c.sw * 0.5}" stroke-linecap="round"/></g>${handPair(c.sw, 89, 35.5, 64.5)}`;
    },
    mug(_G, c) {
        return `<g transform="rotate(${c.tilt * 0.4} 50 86)"><path d="M58 82.5a4.6 4.6 0 0 1 0 9.2" fill="none" stroke="${K}" stroke-width="${c.sw * 1.1}"/><rect x="41" y="78" width="17.5" height="20" rx="3" fill="${c.alt ? D : W}" stroke="${K}" stroke-width="${c.sw}"/>${c.detail ? `<path d="M46.5 74.5q-1.8-2.4 0-4.8M52 74.5q-1.8-2.4 0-4.8" fill="none" stroke="${K}" stroke-width="${c.sw * 0.7}" stroke-linecap="round"/>` : ''}</g><g fill="${W}" stroke="${K}" stroke-width="${c.sw}"><circle cx="39" cy="90" r="4.6"/></g>`;
    },
    wrench(_G, c) {
        // An open-end spanner: a C-shaped jaw on a straight handle with a hole at its end.
        const hole = c.detail ? `<circle cx="0" cy="24" r="1.4" fill="${D}" stroke="${K}" stroke-width="${c.sw * 0.5}"/>` : '';
        return `<g transform="translate(69 85) rotate(${24 + c.tilt * 0.6}) translate(0 -15)"><path d="M-2.5 -10V-4.6H2.5V-10A7 7 0 0 1 3 2.8V25A3 3 0 0 1 -3 25V2.8A7 7 0 0 1 -2.5 -10Z" fill="${W}" stroke="${K}" stroke-width="${c.sw}" stroke-linejoin="round"/>${hole}</g><circle cx="69" cy="85" r="4.6" fill="${W}" stroke="${K}" stroke-width="${c.sw}"/>`;
    },
    brush(_G, c) {
        // A pointed bristle tuft dipped in paint, a thin dark band, a long white handle; drawn 1.25× so strokes leave room.
        const k = 1.25;
        const w = c.sw / k;
        const tuft = 'M-4.6 -4C-6.6 -8.5 -4.8 -15 0 -20.5C4.8 -15 6.6 -8.5 4.6 -4Z';
        return `<g transform="translate(70 85) rotate(${22 + c.tilt * 0.6}) scale(${k}) translate(0 -13)"><path d="M-2.6 2L-1.8 22A1.8 1.8 0 0 0 1.8 22L2.6 2Z" fill="${W}" stroke="${K}" stroke-width="${w}" stroke-linejoin="round"/><path d="${tuft}" fill="${W}"/><path d="M-4.85 -11.9Q0 -9.9 4.85 -11.9C4.05 -14.75 2.4 -17.75 0 -20.5C-2.4 -17.75 -4.05 -14.75 -4.85 -11.9Z" fill="${c.alt ? PAINT : BLUSH}"/><path d="M-4.85 -11.9Q0 -9.9 4.85 -11.9" fill="none" stroke="${K}" stroke-width="${w * 0.6}" stroke-linecap="round"/><path d="${tuft}" fill="none" stroke="${K}" stroke-width="${w}" stroke-linejoin="round"/><path d="M-4.8 -4.6H4.8L4.2 2H-4.2Z" fill="${K}" stroke="${K}" stroke-width="${w * 0.6}" stroke-linejoin="round"/></g><circle cx="70" cy="85" r="4.6" fill="${W}" stroke="${K}" stroke-width="${c.sw}"/>`;
    },
    bubble(_G, c) {
        const shapes = `<rect x="66.5" y="43.5" width="27" height="16" rx="8"/><path d="M71 55L67 64.5L77.5 57.5Z"/>`;
        const inner = c.alt
            ? `<path d="M80 54.8c-2.6-1.6-4.4-3-4.4-4.8a2.2 2.2 0 0 1 4.4-.6a2.2 2.2 0 0 1 4.4 .6c0 1.8-1.8 3.2-4.4 4.8Z" fill="${BLUSH}" stroke="${K}" stroke-width="${c.sw * 0.5}"/>`
            : `<g class="m-typing" fill="${K}"><circle cx="73.4" cy="51.5" r="1.8"/><circle cx="80" cy="51.5" r="1.8"/><circle cx="86.6" cy="51.5" r="1.8"/></g>`;
        return union(shapes, c.sw) + inner;
    },
    calendar(_G, c) {
        const dots = c.detail
            ? `<g fill="${K}">${[0, 1, 2]
                  .map((i) =>
                      [0, 1].map((j) => `<circle cx="${73.6 + i * 6}" cy="${58.4 + j * 4.6}" r="1.3"/>`).join('')
                  )
                  .join('')}</g>`
            : '';
        return `<g transform="rotate(${c.tilt * 0.6} 80 56)"><rect x="68.5" y="46.5" width="23" height="20.5" rx="3" fill="${W}" stroke="${K}" stroke-width="${c.sw}"/><path d="M68.5 52.5V49.5a3 3 0 0 1 3-3h17a3 3 0 0 1 3 3v3Z" fill="${c.alt ? D : K}" stroke="${K}" stroke-width="${c.sw}" stroke-linejoin="round"/><path d="M74 43.6v5.4M86 43.6v5.4" stroke="${K}" stroke-width="${c.sw * 0.9}" stroke-linecap="round"/>${dots}</g>`;
    },
    chart(_G, c) {
        return `<g transform="rotate(${c.tilt * 0.6} 80 55)"><rect x="68" y="45" width="24" height="19.5" rx="3" fill="${W}" stroke="${K}" stroke-width="${c.sw}"/><g fill="${c.alt ? K : D}" stroke="${K}" stroke-width="${c.sw * 0.55}"><rect x="72.4" y="55.6" width="4" height="5.2" rx="0.8"/><rect x="78.2" y="52" width="4" height="8.8" rx="0.8"/><rect x="84" y="48.6" width="4" height="12.2" rx="0.8"/></g></g>`;
    },
    code(_G, c) {
        return `<g transform="rotate(${c.tilt * 0.6} 80 54)"><rect x="67" y="45.5" width="26" height="17" rx="${c.alt ? 8.5 : 4}" fill="${K}"/><path d="M75.4 50.6L71.6 54L75.4 57.4M84.6 50.6L88.4 54L84.6 57.4M81.6 49.6L78.4 58.4" fill="none" stroke="${W}" stroke-width="${c.sw * 0.85}" stroke-linecap="round" stroke-linejoin="round"/></g>`;
    },
    globe(_G, c) {
        return `<g transform="rotate(${c.tilt} 80 55)"><circle cx="80" cy="55" r="10.2" fill="${W}" stroke="${K}" stroke-width="${c.sw}"/><g fill="none" stroke="${K}" stroke-width="${c.sw * 0.6}"><ellipse cx="80" cy="55" rx="4.6" ry="10.2"/><path d="M69.8 55H90.2M71.5 49.8Q80 52 88.5 49.8M71.5 60.2Q80 58 88.5 60.2"/></g></g>`;
    },
    bell(_G, c) {
        return `<g transform="rotate(${c.alt ? -12 : 10} 80 48)"><circle cx="80" cy="67.2" r="2.8" fill="${K}"/><path d="M69.5 64.5H90.5C88 62.3 87.4 59.6 87.4 54.2A7.4 7.4 0 0 0 72.6 54.2C72.6 59.6 72 62.3 69.5 64.5Z" fill="${W}" stroke="${K}" stroke-width="${c.sw}" stroke-linejoin="round"/><path d="M73.2 61H86.8" stroke="${K}" stroke-width="${c.sw * 0.6}" stroke-linecap="round"/><circle cx="80" cy="45.6" r="2.1" fill="${K}"/></g>`;
    },
    megaphone(_G, c) {
        return `<g transform="rotate(${c.tilt * 0.8 - 6} 80 56)"><path d="M75.5 59.5L77.2 65.6" stroke="${K}" stroke-width="${c.sw * 1.1}" stroke-linecap="round"/><path d="M71.5 51.8L88.5 44.5V67.5L71.5 60.2Z" fill="${W}" stroke="${K}" stroke-width="${c.sw}" stroke-linejoin="round"/>${c.alt ? `<path d="M77 49.4V62.6" stroke="${K}" stroke-width="${c.sw * 0.6}"/>` : ''}<ellipse cx="88.5" cy="56" rx="3" ry="11.5" fill="${K}"/><rect x="67.6" y="50.6" width="5.2" height="10.8" rx="2" fill="${K}"/></g>`;
    },
    tag(_G, c) {
        return `<g transform="rotate(${-24 + c.tilt} 80 55)"><path d="M85.2 55C89 52.4 91.4 48.6 90.6 45.6" fill="none" stroke="${K}" stroke-width="${c.sw * 0.6}" stroke-linecap="round"/><path d="M68.5 48H84.5L91.5 55L84.5 62H68.5A2.5 2.5 0 0 1 66 59.5V50.5A2.5 2.5 0 0 1 68.5 48Z" fill="${W}" stroke="${K}" stroke-width="${c.sw}" stroke-linejoin="round"/><circle cx="85.2" cy="55" r="2.2" fill="${c.alt ? D : W}" stroke="${K}" stroke-width="${c.sw * 0.6}"/><path d="M70.5 53H79M70.5 57.4H76" stroke="${K}" stroke-width="${c.sw * 0.55}" stroke-linecap="round"/></g>`;
    },
};

function accessoryDraw(key: AccessoryKey, G: Geom, gap: number, sw: number, layer: 'face' | 'head' | 'body'): string {
    if (key === 'blush' && layer === 'face')
        return `<g fill="${BLUSH}" opacity=".7"><ellipse cx="${G.fx - gap - 4.4}" cy="${G.fy + 3.6}" rx="3.2" ry="1.9"/><ellipse cx="${G.fx + gap + 4.4}" cy="${G.fy + 3.6}" rx="3.2" ry="1.9"/></g>`;
    if (key === 'sprout' && layer === 'head')
        return `<path d="M${G.hx} ${G.top + 1}V${G.top - 6}" stroke="${K}" stroke-width="${sw}" stroke-linecap="round"/><path d="M${G.hx} ${G.top - 5}C${G.hx - 1} ${G.top - 11} ${G.hx + 6} ${G.top - 13} ${G.hx + 9.5} ${G.top - 10.5}C${G.hx + 8} ${G.top - 5.5} ${G.hx + 3} ${G.top - 4} ${G.hx} ${G.top - 5}Z" fill="${W}" stroke="${K}" stroke-width="${sw}" stroke-linejoin="round"/>`;
    if (key === 'clip' && layer === 'head') {
        const x = r1(G.hx - G.rx * 0.52);
        const y = r1(G.hy - G.ry * 0.68);
        return `<rect x="${x - 5}" y="${y - 1.9}" width="10" height="3.8" rx="1.9" transform="rotate(-38 ${x} ${y})" fill="${D}" stroke="${K}" stroke-width="${sw * 0.8}"/>`;
    }
    if (key === 'bowtie' && layer === 'body')
        return `<path d="M43.6 77L50 80.5L43.6 84ZM56.4 77L50 80.5L56.4 84Z" fill="${D}" stroke="${K}" stroke-width="${sw * 0.9}" stroke-linejoin="round"/><circle cx="50" cy="80.5" r="2" fill="${K}"/>`;
    return '';
}

/** The level of detail a size draws at: `xs` (20px and under) is the head and two eyes; `sm` (24–32px) adds the face,
 *  what the head wears and the state's mark; 40px and up holds and floats props and draws their details. */
export const tierOf = (size: number): 'xs' | 'sm' | 'lg' => (size <= 20 ? 'xs' : size <= 32 ? 'sm' : 'lg');

/** The whole mascot for one state at one size, as an `<svg>`. `marks: false` leaves out the state's mark (ticks, z's,
 *  sparkle, red dot), for where something else round it already says the state. */
export function draw(p: MascotLook, stateKey: MascotState, size: number, { marks = true }: { marks?: boolean } = {}): string {
    const xs = size <= 20;
    const sm = !xs && size <= 32;
    const u = 100 / size;
    const sw = Math.max(2.6, u * (xs ? 1.05 : 1));
    const st = STATES[stateKey];
    const face: Partial<Face> = st.rest ? REST[p.rest] : st;
    const G = geom(p, xs);
    const ev = p.eye;
    const er = xs ? u * 0.82 : sm ? Math.max(2.3, u * 0.72) * (1 + (ev - 1) * 0.4) : 2.35 * ev;
    const gap = xs ? Math.max(10, u * 1.7) : p.gap;
    const slots = new Set(p.props.map((k) => propDef(k).slot));
    const showProps = !xs;
    const hatK = Math.round((G.rx / 25) * 100) / 100; // hats are drawn for a 25-wide head
    const ctx = (i: number, k = 1): PropCtx => ({ sw: sw / k, alt: p.pv[i]?.alt ?? false, tilt: p.pv[i]?.tilt ?? 0, detail: size >= 40, er, gap });
    // 24–32px keeps only what the head wears; held and floating props start at 40px.
    const propsIn = (slotList: Slot[], back = false) =>
        showProps
            ? p.props
                  .map((k, i) => {
                      const P = propDef(k);
                      if (!slotList.includes(P.slot) || !!P.back !== back || (sm && (P.slot === 'hands' || P.slot === 'beside'))) return '';
                      // A tool raised up the right side moves to the left hand when something already floats on the right.
                      if (P.right && slots.has('beside')) return `<g transform="translate(100 0) scale(-1 1)">${PROP_DRAW[k](G, ctx(i))}</g>`;
                      if (P.slot !== 'top') return PROP_DRAW[k](G, ctx(i));
                      const ay = G.top + 10;
                      return `<g transform="translate(${G.hx} ${ay}) scale(${hatK}) translate(${-G.hx} ${-ay})">${PROP_DRAW[k](G, ctx(i, hatK))}</g>`;
                  })
                  .join('')
            : '';
    const acc: AccessoryKey = xs ? 'none' : p.acc;
    const hatOn = showProps && slots.has('top');

    // head + shoulders, outlined as one silhouette so the neck has no line across it
    const B = G.B;
    const h = G.h;
    let headShapes = headPath(h);
    if (G.bumps && !hatOn) headShapes = G.bumps.map(([x, y, r]) => `<circle cx="${x}" cy="${y}" r="${r}"/>`).join('') + headShapes;
    const ex = [h.cx - h.rx, h.cx + h.rx];
    const ey = h.cy - 1;
    const er2 = p.ear;
    const ek = er2 / 7.5;
    const ears = B.ears
        ? `<g fill="${W}" stroke="${K}" stroke-width="${sw}"><circle cx="${ex[0]}" cy="${ey}" r="${er2}"/><circle cx="${ex[1]}" cy="${ey}" r="${er2}"/></g>` +
          (xs
              ? ''
              : `<path d="M${r1(ex[0] - 2.4 * ek)} ${r1(ey - 2.6 * ek)}Q${r1(ex[0] - 5 * ek)} ${ey} ${r1(ex[0] - 2 * ek)} ${r1(ey + 2.8 * ek)}M${r1(ex[1] + 2.4 * ek)} ${r1(ey - 2.6 * ek)}Q${r1(ex[1] + 5 * ek)} ${ey} ${r1(ex[1] + 2 * ek)} ${r1(ey + 2.8 * ek)}" fill="none" stroke="${K}" stroke-width="${sw * 0.7}" stroke-linecap="round"/>`)
        : '';
    const T = G.top;
    const X = G.hx;
    const mirror = p.flip ? ` transform="translate(${2 * X} 0) scale(-1 1)"` : '';
    const curl = B.curl && !hatOn ? `<path${mirror} d="M${X - 1.4} ${T + 1}C${X - 3} ${T - 6.5} ${X + 4.4} ${T - 10.3} ${X + 7.8} ${T - 6.3}C${X + 10} ${T - 3.6} ${X + 7.4} ${T - 0.7} ${X + 4.6} ${T - 1.9}" fill="none" stroke="${K}" stroke-width="${sw}" stroke-linecap="round"/>` : '';
    const antenna =
        B.antenna && !hatOn && !xs
            ? `<g${mirror}><path d="M${X + 1.5} ${T + 0.6}Q${X + 2} ${T - 5} ${X + 6.2} ${T - 7.4}" fill="none" stroke="${K}" stroke-width="${sw}" stroke-linecap="round"/><circle cx="${X + 6.8}" cy="${T - 10}" r="3.4" fill="${W}" stroke="${K}" stroke-width="${sw}"/></g>`
            : '';
    const hdT = `rotate(${xs ? 0 : p.tilt} 50 72) translate(50 72) scale(${p.scale}) translate(-50 -72)`;

    let s = '';
    s += `<g class="m-fig"><g${xs ? ' transform="translate(50 66) scale(1.12) translate(-50 -66)"' : ''}>`;
    s += `<g transform="${hdT}">${ears}${propsIn(['ear'], true)}</g>`;
    s += union(`<path d="${SHOULDERS}"/><g transform="${hdT}">${headShapes}</g>`, sw);
    s += accessoryDraw(acc, G, gap, sw, 'body');
    s += `<g class="m-hd" transform="${hdT}">`;
    s += curl + antenna;
    s += accessoryDraw(acc, G, gap, sw, 'head');
    s += accessoryDraw(acc, G, gap, sw, 'face');
    s += brows(xs ? undefined : face.brows, G, gap, sw);
    s += eyes(face.eyes ?? 'dot', G, gap, er, sw, !xs && !sm ? p.oval : 0);
    s += xs ? '' : mouth(face.mouth ?? 'smile', G, sw, p.mw);
    if (face.blush && !xs && acc !== 'blush') s += accessoryDraw('blush', G, gap, sw, 'face');
    s += `<g${G.rot ? ` transform="rotate(${G.rot} ${G.hx} ${G.hy})"` : ''}>${propsIn(['top', 'ear'])}</g>`;
    s += propsIn(['face']);
    s += `</g>`;
    s += `<g transform="translate(0 -2)">${propsIn(['hands'])}</g><g transform="translate(-2 12)">${propsIn(['beside'])}</g>`;
    s += `</g></g>`;
    if (!xs && marks && st.accent) s += accent(st.accent, sw, sm);
    return `<svg viewBox="0 0 100 100" aria-hidden="true" focusable="false">${s}</svg>`;
}
