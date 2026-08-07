// Single entry point for the animated "AI is working" orb. Renders the
// thinking-orbs artwork (its exported MODE_DRAWS + resolvePreset) through our
// own ~30-line canvas shell instead of its <ThinkingOrb> component, because
// that component freezes to a static frame under `prefers-reduced-motion` with
// no prop to opt out — and that setting is widely used as a speed/battery
// toggle, not only for motion sensitivity. The shell keeps the library's real
// performance wins (offscreen + tab-hidden pausing, DPR capped at 2) and the
// orb is 20px of thin arcs, so it animates for everyone. Also owns
// orbStateForStatus, the one mapping from a builder status line to an
// animation, so every AI-activity surface shows the same orb for the same work.
import { useEffect, useRef, useState } from 'react';
import {
    MODE_DRAWS,
    resolvePreset,
    type OrbState,
    type ThinkingOrbProps,
} from 'thinking-orbs';

export type { OrbState };

/** The library's own per-state labels, which its component applies internally
 *  and we lose by rendering the canvas ourselves. Callers may override. */
const DEFAULT_LABELS: Record<OrbState, string> = {
    working: 'Working…',
    searching: 'Searching…',
    solving: 'Solving…',
    listening: 'Listening…',
    connecting: 'Connecting…',
    weaving: 'Weaving…',
    composing: 'Composing…',
    breathing: 'Thinking…',
    shaping: 'Shaping…',
};

/** Resolves the palette from the `dark` class the app actually renders with,
 *  rather than the stored theme preference — most routes are hardcoded dark
 *  regardless of preference (see CLAUDE.md), so the class is the truth. Dark
 *  is the initial value to match the app's SSR default. */
function useIsDark(): boolean {
    const [dark, setDark] = useState(true);
    useEffect(() => {
        const read = () =>
            setDark(document.documentElement.classList.contains('dark'));
        read();
        const observer = new MutationObserver(read);
        observer.observe(document.documentElement, {
            attributes: true,
            attributeFilter: ['class'],
        });
        return () => observer.disconnect();
    }, []);
    return dark;
}

/**
 * Our indicators all sit in text rows rather than avatar slots, so the 20px
 * preset is the default here (the library's own default is the 64px chat-avatar
 * design). The two sizes are separately tuned designs, not a scale factor.
 */
export function ThinkingOrb({
    state = 'working',
    size = 20,
    speed = 1,
    paused = false,
    style,
    'aria-label': ariaLabel,
    ...rest
}: ThinkingOrbProps) {
    const canvasRef = useRef<HTMLCanvasElement>(null);
    const dark = useIsDark();

    useEffect(() => {
        const canvas = canvasRef.current;
        if (!canvas) return;
        const dpr = Math.min(2, window.devicePixelRatio || 1);
        canvas.width = Math.round(size * dpr);
        canvas.height = Math.round(size * dpr);
        const ctx = canvas.getContext('2d');
        if (!ctx) return;

        const { mode, speed: presetSpeed, opts } = resolvePreset(state, size);
        const draw = MODE_DRAWS[mode];
        const rate = presetSpeed * speed;
        const paint = (t: number) => {
            ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
            ctx.clearRect(0, 0, size, size);
            draw(ctx, size, t, dark, opts);
        };

        let frameId = 0;
        let running = false;
        const tick = () => {
            paint((performance.now() / 1000) * rate);
            if (running) frameId = requestAnimationFrame(tick);
        };
        const start = () => {
            if (running || paused) return;
            running = true;
            frameId = requestAnimationFrame(tick);
        };
        const stop = () => {
            running = false;
            cancelAnimationFrame(frameId);
        };

        paint((performance.now() / 1000) * rate);

        // Don't burn frames on an orb nobody can see — a chat transcript can hold
        // several, and a backgrounded tab shouldn't animate at all.
        let onScreen = true;
        const observer =
            typeof IntersectionObserver !== 'undefined'
                ? new IntersectionObserver(([entry]) => {
                      onScreen = entry.isIntersecting;
                      if (onScreen && document.visibilityState !== 'hidden')
                          start();
                      else stop();
                  })
                : null;
        observer?.observe(canvas);
        const onVisibility = () => {
            if (document.visibilityState === 'hidden') stop();
            else if (onScreen) start();
        };
        document.addEventListener('visibilitychange', onVisibility);
        if (!observer) start();

        return () => {
            stop();
            observer?.disconnect();
            document.removeEventListener('visibilitychange', onVisibility);
        };
    }, [state, size, dark, speed, paused]);

    return (
        <canvas
            ref={canvasRef}
            role="img"
            aria-label={ariaLabel ?? DEFAULT_LABELS[state]}
            style={{ width: size, height: size, display: 'block', ...style }}
            {...rest}
        />
    );
}

// Leading-verb → orb, matched in order. Only the three verbs with a genuinely
// distinct animation are mapped; everything else — including a plain "Thinking"
// — is generic work and gets `working`, the house style. The statuses these
// recognise are the ones the agentic builder actually emits (`_status_for_ops`
// plus the per-op strings in backend/coder/workflow/agentic/builder.py:
// "Searching workflows", "Reading config for X", "Connecting nodes", …) and the
// FE's own edit-step lines ("Adding Slack node"). Status text is free-form, so
// this is a total function.
const STATUS_ORBS: ReadonlyArray<readonly [RegExp, OrbState]> = [
    [/^(searching|looking up|reading|listing)\b/i, 'searching'],
    [/^connecting\b/i, 'connecting'],
    [
        /^(modifying|creating|updating|adding|removing|building|configuring)\b/i,
        'weaving',
    ],
];

/** Pick the orb that depicts a builder status line. */
export function orbStateForStatus(status?: string | null): OrbState {
    if (!status) return 'working';
    const text = status.trim();
    for (const [pattern, state] of STATUS_ORBS) {
        if (pattern.test(text)) return state;
    }
    return 'working';
}
