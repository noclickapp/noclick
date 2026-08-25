/*
Canvas-based animated star background.

Why canvas, not DOM: each DOM element with `will-change: opacity` (or an
animated opacity) gets promoted to its own GPU compositing layer on iOS
Safari. With 60-100 stars, that's 60-100 backing stores in the GPU process,
which trips iOS's per-process memory cap and gets the GPU process jetsam-
killed — that crash takes all WebContent processes down with it and surfaces
as "A problem repeatedly occurred". A single <canvas> is one bounded layer.

Skipped entirely on mobile — saves the main-thread rAF budget for the rest
of the page. (Not gated on prefers-reduced-motion: the twinkle is a slow
sub-pixel alpha pulse, far below the vestibular-trigger threshold that
preference is meant to address.)

When the canvas IS rendering, stars are drawn via `drawImage` from a single
pre-rendered circle sprite — one GPU blit per star, comparable to fillRect
in cost but actually circular. (Previous fillRect implementation rendered
visibly square stars at 2-3 px sizes on retina displays.)

The draw loop is throttled to ~30fps: the twinkle is a slow alpha pulse, so
halving the frame rate is imperceptible but halves the per-frame blit cost.
Pauses when perfState.shouldOptimize is true (drag operations) or when the
tab is hidden, so the rAF loop doesn't waste cycles in the background.
*/
import { useEffect, useLayoutEffect, useRef, useState, memo } from 'react';
import { perfState } from '~/lib/perf-state';
import { GameOfLifeBackground } from '~/components/utils/GameOfLifeBackground';

// Tracks the ACTUAL `dark` class on <html> (not the stored preference): pages
// outside the theme gate are forced dark with a light preference stored, and
// the stars must follow what is rendered, not what is stored.
function useIsDarkClass(): boolean {
    const [isDark, setIsDark] = useState(() =>
        typeof document === 'undefined'
            ? true
            : document.documentElement.classList.contains('dark')
    );
    useEffect(() => {
        const el = document.documentElement;
        const update = () => setIsDark(el.classList.contains('dark'));
        update();
        const mo = new MutationObserver(update);
        mo.observe(el, { attributes: true, attributeFilter: ['class'] });
        return () => mo.disconnect();
    }, []);
    return isDark;
}

interface ParticlesBackgroundProps {
    count?: number;
    className?: string;
    starOpacity?: number;
}

interface Star {
    x: number; // 0..1, fraction of canvas width
    y: number; // 0..1, fraction of canvas height
    size: number; // CSS px diameter
    duration: number; // seconds for a full twinkle cycle
    phase: number; // 0..1, current position in the cycle
}

// Only ever called from the mount effect, never from a render. Hydration
// compares the FIRST client render against the SSR html, so evaluating this in
// a useState initializer (where `window` exists) put a <canvas> on the client
// that the server never rendered — a mismatch that made React throw away and
// regenerate the whole auth-page tree.
function shouldRunParticles(): boolean {
    if (typeof window === 'undefined') return false;
    if (window.matchMedia('(max-width: 768px)').matches) return false;
    return true;
}

export const ParticlesBackground = memo(function ParticlesBackground({
    count = 80,
    className = '',
    starOpacity = 0.6,
}: ParticlesBackgroundProps) {
    const canvasRef = useRef<HTMLCanvasElement>(null);
    // Track starOpacity via ref so prop changes apply on the next frame
    // without restarting the rAF loop (and without regenerating stars).
    const starOpacityRef = useRef(starOpacity);
    starOpacityRef.current = starOpacity;

    const isDark = useIsDarkClass();
    // Starts false on BOTH sides so the first client render matches the SSR
    // html; the mount effect below turns it on a frame later.
    const [viewportOk, setViewportOk] = useState(false);
    // Stars are a dark-mode effect: white specks read as dust on a light page.
    // Light mode swaps in a static soft wash (below) instead.
    const active = viewportOk && isDark;

    // Re-evaluate on viewport changes (e.g. rotation) so we cleanly
    // mount/unmount the canvas without a refresh.
    useEffect(() => {
        if (typeof window === 'undefined') return;
        const mq = window.matchMedia('(max-width: 768px)');
        const update = () => setViewportOk(shouldRunParticles());
        update();
        mq.addEventListener('change', update);
        return () => mq.removeEventListener('change', update);
    }, []);

    // Size the canvas + clear it BEFORE the browser paints the first frame,
    // so there's no flash of default canvas content (which has been known to
    // render solid-white in some iOS Safari versions).
    useLayoutEffect(() => {
        if (!active) return;
        const canvas = canvasRef.current;
        if (!canvas) return;
        const dpr = window.devicePixelRatio || 1;
        const rect = canvas.getBoundingClientRect();
        canvas.width = Math.max(1, Math.floor(rect.width * dpr));
        canvas.height = Math.max(1, Math.floor(rect.height * dpr));
        const ctx = canvas.getContext('2d');
        if (ctx) {
            ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
            ctx.clearRect(0, 0, rect.width, rect.height);
        }
    }, [active]);

    useEffect(() => {
        if (!active) return;
        const canvas = canvasRef.current;
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        if (!ctx) return;

        const stars: Star[] = [];
        for (let i = 0; i < count; i++) {
            stars.push({
                x: Math.random(),
                y: Math.random(),
                size: Math.random() * 2 + 1,
                duration: Math.random() * 3 + 2,
                phase: Math.random(),
            });
        }

        // Rendered at high res so the browser's bilinear downscale to the
        // 1-3 px target size produces a clean anti-aliased edge.
        const SPRITE_PX = 32;
        const sprite = document.createElement('canvas');
        sprite.width = SPRITE_PX;
        sprite.height = SPRITE_PX;
        const spriteCtx = sprite.getContext('2d');
        if (!spriteCtx) return;
        spriteCtx.fillStyle = 'white';
        spriteCtx.beginPath();
        spriteCtx.arc(
            SPRITE_PX / 2,
            SPRITE_PX / 2,
            SPRITE_PX / 2,
            0,
            Math.PI * 2
        );
        spriteCtx.fill();

        const dpr = window.devicePixelRatio || 1;
        let width = 0;
        let height = 0;

        const resize = () => {
            const rect = canvas.getBoundingClientRect();
            width = rect.width;
            height = rect.height;
            canvas.width = Math.floor(width * dpr);
            canvas.height = Math.floor(height * dpr);
            ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        };
        resize();
        const ro = new ResizeObserver(resize);
        ro.observe(canvas);

        let rafId = 0;
        let lastTime = performance.now();
        // Throttle the twinkle to ~30fps — a slow alpha pulse looks identical at
        // half the frame rate but halves the per-frame clear+blit cost.
        const FRAME_INTERVAL_MS = 1000 / 30;

        const draw = (now: number) => {
            rafId = requestAnimationFrame(draw);

            // Pause while a drag is optimizing the canvas, or when the tab
            // is backgrounded. Re-checks on each frame so we resume smoothly.
            if (perfState.shouldOptimize || document.hidden) {
                lastTime = now;
                return;
            }

            const elapsed = now - lastTime;
            if (elapsed < FRAME_INTERVAL_MS) return; // cap above ~30fps
            lastTime = now;
            const dt = elapsed / 1000;

            ctx.clearRect(0, 0, width, height);
            const baseOpacity = starOpacityRef.current;
            for (let i = 0; i < stars.length; i++) {
                const star = stars[i];
                star.phase = (star.phase + dt / star.duration) % 1;
                // sin-shaped 0.2..1.0 multiplier so stars never go fully dark
                const t = Math.sin(star.phase * Math.PI * 2) * 0.5 + 0.5;
                ctx.globalAlpha = baseOpacity * (0.2 + t * 0.8);
                const size = star.size;
                // Position so the full sprite stays inside the canvas — otherwise
                // stars near the edges render as visible half-circles.
                ctx.drawImage(
                    sprite,
                    star.x * (width - size),
                    star.y * (height - size),
                    size,
                    size
                );
            }
            ctx.globalAlpha = 1;
        };
        rafId = requestAnimationFrame(draw);

        return () => {
            cancelAnimationFrame(rafId);
            ro.disconnect();
        };
    }, [active, count]);

    // Parent <div> stays in the tree even when inactive so callers using
    // the wrapper as a positioned background slot don't see a layout shift
    // when particles toggle off.
    return (
        <div
            className={`absolute inset-0 pointer-events-none rr-block ph-no-capture ${className}`}
            style={{ zIndex: 0 }}
        >
            {active && (
                <canvas
                    ref={canvasRef}
                    className="absolute inset-0 w-full h-full"
                    style={{ background: 'transparent', display: 'block' }}
                />
            )}
            {/* Light-mode replacement for the stars: a slow Game of Life. Same
                viewport gate as the stars (desktop only). Self-contained in
                GameOfLifeBackground — remove this one line to drop the effect. */}
            {viewportOk && !isDark && <GameOfLifeBackground />}
        </div>
    );
});
