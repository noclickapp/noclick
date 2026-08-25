// Light-mode background for the chat sidebar: a slow Conway's Game of Life
// (B3/S23) on a toroidal grid. Cells ease in when born and out when they die so
// generations dissolve rather than flicker; seeded with a soup + a few gliders
// (the little diagonal "replicators" that drift across and wrap). Re-seeds when
// it gets too sparse so the field never dies out; the pattern is preserved
// across resizes, so it reflows as the sidebar is dragged/collapsed just like
// the dark-mode starfield.
//
// SELF-CONTAINED + EASY TO RIP OUT: this is the only file holding the effect.
// It's rendered by ParticlesBackground's light branch; to remove the effect,
// drop that one <GameOfLifeBackground/> line (and delete this file). NoClick /
// MessagesView never reference it. Tune the look via the constants below.

import { memo, useEffect, useRef } from 'react';

// ── Tunables ────────────────────────────────────────────────────────────────
const CELL = 16; // px per grid cell (spacing between dots)
const DOT = 6; // px of the drawn square, centered in the cell (leaves airy gaps)
const GEN_INTERVAL = 0.55; // seconds between generations (calm pace)
const MAX_ALPHA = 0.12; // peak opacity of a live cell (charcoal on light) — subtle
const EASE = 0.05; // per-frame fade toward live/dead — low = cells materialize /
// dissolve very gradually, so transient churn barely registers and only
// persistent structures surface (harder to notice than a snappy pop-in).
const SEED_DENSITY = 0.11; // initial live fraction
const REVIVE_BELOW = 0.03; // re-seed when population drops under this fraction
const CELL_RGB = '63,63,70'; // zinc-700 charcoal

function plantGlider(g: Uint8Array, C: number, R: number, x: number, y: number) {
    for (const [dx, dy] of [[1, 0], [2, 1], [0, 2], [1, 2], [2, 2]]) {
        g[((y + dy) % R) * C + ((x + dx) % C)] = 1;
    }
}

export const GameOfLifeBackground = memo(function GameOfLifeBackground({
    className = '',
}: {
    className?: string;
}) {
    const canvasRef = useRef<HTMLCanvasElement>(null);

    useEffect(() => {
        const canvas = canvasRef.current;
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        if (!ctx) return;
        const dpr = Math.min(window.devicePixelRatio || 1, 2);

        let w = 0;
        let h = 0;
        let cols = 0;
        let rows = 0;
        let grid = new Uint8Array(0);
        let alpha = new Float32Array(0);
        let lastGen = 0;
        let raf = 0;
        const start = performance.now();
        // Cells the user clicked, applied to the grid on the next generation.
        const pendingSeeds: Array<{ col: number; row: number }> = [];

        const seed = (g: Uint8Array, C: number, R: number, density: number, gliders: number) => {
            for (let i = 0; i < g.length; i++) if (Math.random() < density) g[i] = 1;
            for (let k = 0; k < gliders; k++) {
                plantGlider(g, C, R, (Math.random() * C) | 0, (Math.random() * R) | 0);
            }
        };

        const resize = () => {
            const r = canvas.getBoundingClientRect();
            w = Math.max(1, r.width);
            h = Math.max(1, r.height);
            canvas.width = Math.floor(w * dpr);
            canvas.height = Math.floor(h * dpr);
            ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
            const nc = Math.max(1, Math.ceil(w / CELL));
            const nr = Math.max(1, Math.ceil(h / CELL));
            if (nc === cols && nr === rows) return;
            const ng = new Uint8Array(nc * nr);
            const na = new Float32Array(nc * nr);
            if (grid.length === 0) {
                seed(ng, nc, nr, SEED_DENSITY, 4);
            } else {
                // Preserve the living pattern across a resize (copy the overlap).
                const mc = Math.min(nc, cols);
                const mr = Math.min(nr, rows);
                for (let y = 0; y < mr; y++)
                    for (let x = 0; x < mc; x++) {
                        ng[y * nc + x] = grid[y * cols + x];
                        na[y * nc + x] = alpha[y * cols + x];
                    }
            }
            cols = nc;
            rows = nr;
            grid = ng;
            alpha = na;
        };
        resize();
        const ro = new ResizeObserver(resize);
        ro.observe(canvas);

        // Click-to-seed: window-level so it catches clicks anywhere over the
        // sidebar (the canvas sits behind the chat content). Not preventDefault'd
        // — the click still does its normal thing; the dot is a bonus. Only clicks
        // landing inside the canvas box seed a cell (on the next generation).
        const onPointerDown = (e: PointerEvent) => {
            const r = canvas.getBoundingClientRect();
            const x = e.clientX - r.left;
            const y = e.clientY - r.top;
            if (x < 0 || y < 0 || x > r.width || y > r.height) return;
            pendingSeeds.push({ col: Math.floor(x / CELL), row: Math.floor(y / CELL) });
        };
        window.addEventListener('pointerdown', onPointerDown);

        const step = () => {
            const C = cols;
            const R = rows;
            const ng = new Uint8Array(grid.length);
            let pop = 0;
            for (let y = 0; y < R; y++)
                for (let x = 0; x < C; x++) {
                    let n = 0;
                    for (let dy = -1; dy <= 1; dy++)
                        for (let dx = -1; dx <= 1; dx++) {
                            if (dx === 0 && dy === 0) continue;
                            n += grid[(((y + dy + R) % R) * C) + ((x + dx + C) % C)];
                        }
                    const alive = grid[y * C + x];
                    ng[y * C + x] = alive ? (n === 2 || n === 3 ? 1 : 0) : n === 3 ? 1 : 0;
                    pop += ng[y * C + x];
                }
            if (pop < grid.length * REVIVE_BELOW) {
                for (let k = 0; k < grid.length * 0.06; k++) ng[(Math.random() * grid.length) | 0] = 1;
                plantGlider(ng, C, R, (Math.random() * C) | 0, (Math.random() * R) | 0);
            }
            // Apply user clicks accumulated since the last generation.
            for (const { col, row } of pendingSeeds) {
                if (col >= 0 && col < C && row >= 0 && row < R) ng[row * C + col] = 1;
            }
            pendingSeeds.length = 0;
            grid = ng;
        };

        const loop = (now: number) => {
            const t = (now - start) / 1000;
            if (t - lastGen >= GEN_INTERVAL) {
                lastGen = t;
                step();
            }
            ctx.clearRect(0, 0, w, h);
            const off = (CELL - DOT) / 2; // center the dot in its cell
            const rounded = !!ctx.roundRect;
            for (let i = 0; i < grid.length; i++) {
                alpha[i] += ((grid[i] ? 1 : 0) - alpha[i]) * EASE;
                if (alpha[i] > 0.02) {
                    const x = (i % cols) * CELL + off;
                    const y = ((i / cols) | 0) * CELL + off;
                    ctx.fillStyle = `rgba(${CELL_RGB},${alpha[i] * MAX_ALPHA})`;
                    ctx.beginPath();
                    if (rounded) ctx.roundRect(x, y, DOT, DOT, 1.5);
                    else ctx.rect(x, y, DOT, DOT);
                    ctx.fill();
                }
            }
            raf = requestAnimationFrame(loop);
        };
        raf = requestAnimationFrame(loop);

        return () => {
            cancelAnimationFrame(raf);
            ro.disconnect();
            window.removeEventListener('pointerdown', onPointerDown);
        };
    }, []);

    return (
        <canvas
            ref={canvasRef}
            className={`absolute inset-0 h-full w-full ${className}`}
            style={{ display: 'block', background: 'transparent' }}
            aria-hidden
        />
    );
});
