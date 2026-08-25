// Two-key "leader" keyboard shortcuts (Linear-style). Press "G" then a key to go
// somewhere (G W → workflows), "N" then a key to create something (N C → new
// credential), or "O" then a key to open the palette scoped to a category
// (O W → workflows). The leader is armed for a short window; a matching key fires
// the action, any other key (or the timeout) disarms it. Ignored while typing in
// a field. Mounted once in the dashboard shell.
import { useEffect, useRef } from 'react';
import { isTextEntryTarget } from '~/lib/keyboard';
import {
    GOTO_DESTINATIONS,
    NEW_ACTIONS,
    OPEN_SCOPES,
    HELP_ACTIONS,
    isAddNodeShortcutActive,
    type LeaderShortcut,
} from '~/lib/shortcuts';

const LEADER_WINDOW_MS = 1500;

type Leader = 'g' | 'n' | 'o' | 'h';
const LEADER_MAP: Record<Leader, LeaderShortcut[]> = {
    g: GOTO_DESTINATIONS,
    n: NEW_ACTIONS,
    o: OPEN_SCOPES,
    h: HELP_ACTIONS,
};

export function useLeaderShortcuts(): void {
    const leaderRef = useRef<Leader | null>(null);
    const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    useEffect(() => {
        const disarm = () => {
            leaderRef.current = null;
            if (timerRef.current) {
                clearTimeout(timerRef.current);
                timerRef.current = null;
            }
        };

        const onKey = (e: KeyboardEvent) => {
            if (e.metaKey || e.ctrlKey || e.altKey) return;
            if (isTextEntryTarget(e.target)) return;
            const key = e.key.toLowerCase();

            const leader = leaderRef.current;
            if (leader) {
                // Second key of the sequence — fire on match, otherwise just
                // disarm and let the key behave normally (don't swallow Escape).
                const match = LEADER_MAP[leader].find((s) => s.key === key);
                disarm();
                if (match) {
                    e.preventDefault();
                    // Capture phase + stop here so the matched second key (e.g. the
                    // "c" in "G c") doesn't also trigger a bare-key shortcut like the
                    // browser's "C" = card view.
                    e.stopImmediatePropagation();
                    match.run();
                }
                return;
            }

            // On an open canvas, "N" adds a node (handled there) — don't arm the
            // new-X leader; let the key fall through to FlowCanvas.
            if (key === 'n' && isAddNodeShortcutActive()) return;

            if (key === 'g' || key === 'n' || key === 'o' || key === 'h') {
                leaderRef.current = key;
                timerRef.current = setTimeout(disarm, LEADER_WINDOW_MS);
            }
        };

        // Capture phase so we see (and can consume) the second key before any
        // bubble-phase bare-key handler.
        document.addEventListener('keydown', onKey, true);
        return () => {
            document.removeEventListener('keydown', onKey, true);
            disarm();
        };
    }, []);
}
