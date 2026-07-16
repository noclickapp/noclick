// Generates the hand-drawn marker underline as SVG path data (a filled brush
// stroke with tapered/frayed ends, a slight upward sweep, rough smoothed edges,
// and a lift-off flick) so it composes over the DOM title and is captured crisply
// by the image export. Deterministic per (width, thickness, seed) so it doesn't
// wiggle on every re-render.

export interface UnderlineGeometry {
    width: number; // svg box width (word width + right pad for the flick)
    height: number;
    fillPath: string; // filled brush body
    flickPath: string; // end lift-off stroke
    strokeWidth: number; // for the flick stroke
}

function mulberry32(a: number): () => number {
    return function () {
        a |= 0;
        a = (a + 0x6d2b79f5) | 0;
        let t = Math.imul(a ^ (a >>> 15), 1 | a);
        t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
}

function smooth(arr: number[]): number[] {
    for (let pass = 0; pass < 3; pass++) {
        const b = arr.slice();
        for (let j = 0; j < arr.length; j++) {
            const a = b[Math.max(0, j - 1)];
            const c = b[Math.min(b.length - 1, j + 1)];
            arr[j] = (a + b[j] + c) / 3;
        }
    }
    return arr;
}

export function buildUnderline(
    wordWidth: number,
    thickness: number,
    seed: number
): UnderlineGeometry {
    const rand = mulberry32(seed >>> 0 || 1);
    const rightPad = thickness * 3;
    const W = Math.max(1, wordWidth) + rightPad;
    const H = thickness * 4;
    const y0 = H * 0.6;
    const len = Math.max(1, wordWidth);
    const N = 64;
    const tilt = -thickness * (0.7 + rand() * 0.9);

    const rnd = (n: number) => {
        const o: number[] = [];
        for (let i = 0; i < n; i++) o.push(rand() - 0.5);
        return o;
    };
    const topN = smooth(rnd(N + 1));
    const botN = smooth(rnd(N + 1));
    const midN = smooth(rnd(N + 1));

    const pts: { cx: number; cy: number; th: number }[] = [];
    for (let i = 0; i <= N; i++) {
        const t = i / N;
        const cx = len * t;
        const cy = y0 + tilt * t + midN[i] * thickness * 0.5;
        const taper = Math.max(0, Math.min(1, t / 0.13, (1 - t) / 0.09));
        const th = thickness * (0.24 + 0.76 * taper);
        pts.push({ cx, cy, th });
    }

    const fmt = (n: number) => Math.round(n * 100) / 100;
    let d = '';
    for (let i = 0; i <= N; i++) {
        const p = pts[i];
        const yy = p.cy - p.th / 2 + topN[i] * thickness * 0.22;
        d += `${i === 0 ? 'M' : 'L'} ${fmt(p.cx)} ${fmt(yy)} `;
    }
    for (let i = N; i >= 0; i--) {
        const p = pts[i];
        const yy = p.cy + p.th / 2 + botN[i] * thickness * 0.26;
        d += `L ${fmt(p.cx)} ${fmt(yy)} `;
    }
    d += 'Z';

    // lift-off flick past the right end, in the sweep direction
    const e = pts[N];
    const e2 = pts[N - 2];
    let dx = e.cx - e2.cx;
    let dy = e.cy - e2.cy;
    const dl = Math.hypot(dx, dy) || 1;
    dx /= dl;
    dy /= dl;
    const fx = e.cx + dx * thickness * 2.4;
    const fy = e.cy + dy * thickness * 2.4 - thickness * 0.5;
    const flickPath = `M ${fmt(e.cx)} ${fmt(e.cy)} L ${fmt(fx)} ${fmt(fy)}`;

    return {
        width: W,
        height: H,
        fillPath: d,
        flickPath,
        strokeWidth: Math.round(thickness * 0.42 * 100) / 100,
    };
}
