// The tooltip Work's icon rails share: the folded list's faces and glyphs, and the model picker's harnesses. It names
// the icon and, after a dot, a state the rail knows ("Codex · not connected"), on the app's tooltip surface,
// pill-round, centred on the icon past the rail's or the picker's edge, so it never covers what's beside the icon (the
// list's rows reach under it, so it's placed by that edge, not by the row). One rail is one delay group: 300ms the
// first time, then at once while moving between neighbours; at once on keyboard focus; gone on Esc, on leaving, and
// while a click is in progress.
import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { TOOLTIP_SURFACE } from '@/ui/ShortcutTooltip';
import { cn } from '@/ui/utils';

export interface RailTipAt {
    text: string;
    /** What the rail knows of it, quieter after the name. */
    state?: string;
    /** The viewport x of the tip's near edge, and which way from it the tip sits. */
    x: number;
    y: number;
    side: 'left' | 'right';
}

export const TIP_DELAY_MS = 300;
/** After one hides, the next within this long shows at once: moving between neighbours. */
export const TIP_WARM_MS = 500;

export interface RailTips {
    tip: RailTipAt | null;
    /** The pointer came to an item: after the delay, or at once if a neighbour's tip just showed. */
    hover(at: RailTipAt): void;
    /** Keyboard focus came to an item: at once. */
    focus(at: RailTipAt): void;
    hide(): void;
    /** A click starting: no tip until it ends. */
    press(): void;
}

export function useRailTips(): RailTips {
    const [tip, setTip] = useState<RailTipAt | null>(null);
    const state = useRef({ timer: undefined as number | undefined, warmUntil: 0, pressing: false, shown: false });
    state.current.shown = !!tip;
    const api = useMemo(() => {
        const s = state.current;
        const clear = () => window.clearTimeout(s.timer);
        const hide = () => {
            clear();
            if (s.shown) s.warmUntil = Date.now() + TIP_WARM_MS;
            setTip(null);
        };
        return {
            hover(at: RailTipAt) {
                if (s.pressing) return;
                clear();
                if (s.shown || Date.now() < s.warmUntil) setTip(at);
                else s.timer = window.setTimeout(() => setTip(at), TIP_DELAY_MS);
            },
            focus(at: RailTipAt) {
                if (s.pressing) return;
                clear();
                setTip(at);
            },
            hide,
            press() {
                s.pressing = true;
                hide();
                const up = () => {
                    s.pressing = false;
                    window.removeEventListener('pointerup', up, true);
                    window.removeEventListener('pointercancel', up, true);
                };
                window.addEventListener('pointerup', up, true);
                window.addEventListener('pointercancel', up, true);
            },
        };
    }, []);
    useEffect(() => {
        if (!tip) return;
        const key = (e: KeyboardEvent) => {
            if (e.key === 'Escape') api.hide();
        };
        window.addEventListener('keydown', key, true);
        return () => window.removeEventListener('keydown', key, true);
    }, [tip, api]);
    useEffect(() => () => window.clearTimeout(state.current.timer), []);
    return useMemo(() => ({ tip, ...api }), [tip, api]);
}

/** A tip centred on `el`, `gap` px past `edge` (a viewport x: a rail's or a picker's outer edge) on `side`. */
export function tipBeside(el: Element, edge: number, side: 'left' | 'right', text: string, state?: string | null, gap = 8): RailTipAt {
    const r = el.getBoundingClientRect();
    return { text, state: state ?? undefined, side, y: r.top + r.height / 2, x: side === 'right' ? edge + gap : edge - gap };
}

export function RailTip({ tip }: { tip: RailTipAt | null }) {
    if (!tip || typeof document === 'undefined') return null;
    return createPortal(
        <div
            role="tooltip"
            className={cn(TOOLTIP_SURFACE, 'pointer-events-none fixed z-[90] max-w-[320px] -translate-y-1/2 truncate rounded-full border px-3 py-1.5 text-[13px] leading-tight')}
            style={{ top: tip.y, ...(tip.side === 'right' ? { left: tip.x } : { right: window.innerWidth - tip.x }) }}
        >
            {tip.text}
            {tip.state && <span className="text-muted-foreground"> · {tip.state}</span>}
        </div>,
        document.body
    );
}
